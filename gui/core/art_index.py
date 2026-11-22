import asyncio
import difflib
import hashlib
import json
import logging
import os
import re
import time
import urllib.parse
from typing import Dict, List, Optional, Set, Tuple

import httpx

from config import DATA_DIR, SCRYFALL_CACHE_DIR, UNIFIED_ART_PATH
from utils.text import normalize_card_name

logger = logging.getLogger(__name__)

_SCRYFALL_LOCK = asyncio.Lock()
_LAST_SCRYFALL_CALL = 0.0
_SCRYFALL_MIN_INTERVAL = 0.11  # Respect Scryfall 10 req/s rate limit


class ArtIndex:
    """In-memory O(1) + inverted-token + fuzzy index of unified HD art JSON + Scryfall fallback."""

    def __init__(self, json_path: str = UNIFIED_ART_PATH, cache_dir: str = SCRYFALL_CACHE_DIR):
        self.json_path = json_path
        self.cache_dir = cache_dir
        self._by_norm_name: Dict[str, List[dict]] = {}
        self._token_index: Dict[str, Set[int]] = {}
        self._norm_names: List[str] = []
        self._all_entries: List[dict] = []
        self._seen_urls: Set[str] = set()
        self._loaded = False

    def _index_entry(self, entry: dict) -> None:
        if not isinstance(entry, dict):
            return
        name = (entry.get("name") or "").strip()
        url = (entry.get("image_url") or entry.get("art_crop_url") or "").strip()
        if not name or not url or url in self._seen_urls:
            return
        clean_entry = {
            "name": name,
            "image_url": url,
            "set": (entry.get("set") or "").strip(),
            "artist": (entry.get("artist") or "").strip(),
        }
        idx = len(self._all_entries)
        self._all_entries.append(clean_entry)
        self._seen_urls.add(url)

        norm = normalize_card_name(name)
        self._norm_names.append(norm)
        self._by_norm_name.setdefault(norm, []).append(clean_entry)

        hay = f"{norm} {clean_entry['set'].lower()} {clean_entry['artist'].lower()}"
        for tok in set(re.findall(r"[a-z0-9]+", hay)):
            if len(tok) >= 2:
                self._token_index.setdefault(tok, set()).add(idx)

    def _load_json_file(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for entry in data:
                    self._index_entry(entry)
            elif isinstance(data, dict) and isinstance(data.get("cards"), list):
                for entry in data["cards"]:
                    self._index_entry(entry)
        except Exception as exc:
            logger.exception("Failed to load art JSON %s: %s", path, exc)

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if os.path.isfile(self.json_path):
            self._load_json_file(self.json_path)
        else:
            logger.warning("Unified art JSON not found at %s", self.json_path)

        # Also index any extra *.json files placed in DATA_DIR
        if os.path.isdir(DATA_DIR):
            for fname in sorted(os.listdir(DATA_DIR)):
                if not fname.lower().endswith(".json"):
                    continue
                fpath = os.path.join(DATA_DIR, fname)
                if os.path.abspath(fpath) == os.path.abspath(self.json_path):
                    continue
                self._load_json_file(fpath)

        logger.info(
            "Loaded art index: %d entries, %d unique card names, %d indexed tokens",
            len(self._all_entries),
            len(self._by_norm_name),
            len(self._token_index),
        )

    def lookup_exact(self, name: str) -> List[dict]:
        self.ensure_loaded()
        norm = normalize_card_name(name)
        if not norm:
            return []
        return list(self._by_norm_name.get(norm, []))

    def search(self, query: str, limit: int = 40) -> List[dict]:
        self.ensure_loaded()
        q = (query or "").strip().lower()
        if not q:
            return self._all_entries[:limit]

        norm_q = normalize_card_name(q)
        scored: List[Tuple[float, int, dict]] = []
        seen_idx: Set[int] = set()

        # 1. O(1) exact normalized name match
        if norm_q and norm_q in self._by_norm_name:
            for i, e in enumerate(self._all_entries):
                if self._norm_names[i] == norm_q:
                    scored.append((1.0, i, e))
                    seen_idx.add(i)

        # 2. Substring match on normalized card name
        if len(scored) < limit and norm_q:
            for i, norm_name in enumerate(self._norm_names):
                if i in seen_idx:
                    continue
                if norm_q in norm_name:
                    scored.append((0.92, i, self._all_entries[i]))
                    seen_idx.add(i)

        # 3. Inverted token index AND-intersection (all query tokens must match)
        q_tokens = [t for t in re.findall(r"[a-z0-9]+", norm_q) if len(t) >= 2]
        if len(scored) < limit and q_tokens:
            token_sets: List[Set[int]] = []
            for qt in q_tokens:
                if qt in self._token_index:
                    token_sets.append(self._token_index[qt])
                else:
                    pref_set: Set[int] = set()
                    for tok, idxs in self._token_index.items():
                        if tok.startswith(qt):
                            pref_set.update(idxs)
                    token_sets.append(pref_set)
            if token_sets:
                common = set.intersection(*token_sets)
                for idx in common:
                    if idx not in seen_idx:
                        scored.append((0.85, idx, self._all_entries[idx]))
                        seen_idx.add(idx)

        # 4. Strict fuzzy fallback ONLY when no exact/substring/all-token matches were found (handles typos)
        if not scored and norm_q:
            for idx, norm_name in enumerate(self._norm_names):
                if abs(len(norm_name) - len(norm_q)) > max(8, len(norm_q) // 2):
                    continue
                ratio = difflib.SequenceMatcher(None, norm_q, norm_name).ratio()
                if ratio >= 0.72:
                    scored.append((ratio * 0.8, idx, self._all_entries[idx]))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in scored[:limit]]

    @property
    def stats(self) -> dict:
        self.ensure_loaded()
        return {
            "total_entries": len(self._all_entries),
            "unique_cards": len(self._by_norm_name),
            "indexed_tokens": len(self._token_index),
        }

    def _cache_path(self, key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, f"{digest}.json")

    def _read_cache(self, key: str) -> Optional[dict]:
        p = self._cache_path(key)
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def _write_cache(self, key: str, payload: dict) -> None:
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            p = self._cache_path(key)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except Exception:
            pass

    async def _scryfall_get_json(self, url: str) -> Optional[dict]:
        cached = self._read_cache(url)
        if cached is not None:
            return cached

        global _LAST_SCRYFALL_CALL
        async with _SCRYFALL_LOCK:
            now = time.monotonic()
            wait = _SCRYFALL_MIN_INTERVAL - (now - _LAST_SCRYFALL_CALL)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, transport=httpx.AsyncHTTPTransport(local_address="0.0.0.0", retries=2)) as client:
                    resp = await client.get(
                        url,
                        headers={
                            "User-Agent": "DeckGenRefactored/2.0",
                            "Accept": "application/json",
                        },
                    )
                _LAST_SCRYFALL_CALL = time.monotonic()
                if resp.status_code == 200:
                    data = resp.json()
                    self._write_cache(url, data)
                    return data
            except Exception as exc:
                _LAST_SCRYFALL_CALL = time.monotonic()
                logger.warning("Scryfall request failed for %s: %s", url, exc)
        return None

    async def fetch_scryfall_card(self, query: str, exact: bool = False) -> Optional[dict]:
        q = (query or "").strip()
        if not q:
            return None
        param = "exact" if exact else "fuzzy"
        url = f"https://api.scryfall.com/cards/named?{param}={urllib.parse.quote(q)}"
        return await self._scryfall_get_json(url)

    async def fetch_scryfall_prints(self, card_name: str, limit: int = 36) -> List[dict]:
        q = (card_name or "").strip()
        if not q:
            return []
        url = (
            "https://api.scryfall.com/cards/search"
            f"?q={urllib.parse.quote(chr(33) + chr(34) + q + chr(34) + chr(32) + 'unique:prints')}&order=released&dir=desc"
        )
        data = await self._scryfall_get_json(url)
        if not data or "data" not in data:
            url2 = (
                "https://api.scryfall.com/cards/search"
                f"?q={urllib.parse.quote(q)}&unique=prints&order=released&dir=desc"
            )
            data = await self._scryfall_get_json(url2)
        if not data or "data" not in data:
            return []

        prints = []
        for raw in data["data"][:limit]:
            faces = raw.get("card_faces") or []
            uris = raw.get("image_uris") or (faces[0].get("image_uris") if faces else {}) or {}
            art_crop = uris.get("art_crop") or ""
            full_img = uris.get("png") or uris.get("large") or uris.get("normal") or ""
            if not art_crop and not full_img:
                continue
            prints.append({
                "id": raw.get("id", ""),
                "name": raw.get("name", q),
                "set": raw.get("set_name") or raw.get("set", ""),
                "set_code": raw.get("set", ""),
                "artist": raw.get("artist", ""),
                "art_crop_url": art_crop or full_img,
                "full_url": full_img or art_crop,
                "frame_effects": raw.get("frame_effects") or [],
                "full_art": bool(raw.get("full_art")),
                "border_color": raw.get("border_color", ""),
            })
        return prints


art_index = ArtIndex()
