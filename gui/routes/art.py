import hashlib
import io
import os
import re
import urllib.parse

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from PIL import Image

from config import CACHE_ROOT
from core.art_index import art_index

router = APIRouter(prefix="/api/art")
_IMG_CACHE_DIR = os.path.join(CACHE_ROOT, "img_proxy")
_MPCFILL_SOURCES_CACHE = None
_UA = "DeckGenStudio/2.0 (https://github.com/cridonoso/deckgen)"


@router.get("/stats")
async def api_art_stats():
    return art_index.stats


@router.get("/lookup")
async def api_art_lookup(name: str = Query(...)):
    matches = art_index.lookup_exact(name)
    return {"name": name, "results": matches, "count": len(matches)}


@router.get("/search")
async def api_art_search(q: str = Query(default=""), limit: int = Query(default=40, ge=1, le=120)):
    results = art_index.search(q, limit=limit)
    return {"query": q, "results": results, "count": len(results)}


@router.get("/scryfall-prints")
async def api_art_scryfall_prints(name: str = Query(...)):
    if not name.strip():
        raise HTTPException(status_code=400, detail="Nombre de carta requerido.")
    prints = await art_index.fetch_scryfall_prints(name.strip())
    return {"name": name, "prints": prints, "count": len(prints)}


@router.get("/mpcfill")
async def api_art_mpcfill(q: str = Query(...), limit: int = Query(default=36, ge=1, le=60)):
    global _MPCFILL_SOURCES_CACHE
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query requerida.")
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            if not _MPCFILL_SOURCES_CACHE:
                rs = await client.get("https://mpcfill.com/2/sources/", headers=headers)
                if rs.status_code == 200:
                    src_data = rs.json().get("results") or {}
                    _MPCFILL_SOURCES_CACHE = [[int(k), True] for k in src_data.keys()]
            sources = _MPCFILL_SOURCES_CACHE or []

            ids = []
            for fuzzy in (False, True):
                payload = {
                    "searchSettings": {
                        "searchTypeSettings": {"fuzzySearch": fuzzy, "filterCardbacks": False},
                        "sourceSettings": {"sources": sources},
                        "filterSettings": {
                            "minimumDPI": 0,
                            "maximumDPI": 2400,
                            "maximumSize": 30,
                            "languages": ["EN"],
                            "includesTags": [],
                            "excludesTags": [],
                        },
                    },
                    "queries": [{"query": query, "cardType": "CARD"}],
                }
                r_search = await client.post("https://mpcfill.com/2/editorSearch/", json=payload, headers=headers)
                if r_search.status_code == 200:
                    res_map = r_search.json().get("results") or {}
                    for val in res_map.values():
                        card_ids = (val or {}).get("CARD") or []
                        if card_ids:
                            ids = card_ids[:limit]
                            break
                if ids:
                    break

            if not ids:
                return {"query": query, "results": [], "count": 0}

            r_cards = await client.post("https://mpcfill.com/2/cards/", json={"cardIdentifiers": ids}, headers=headers)
            if r_cards.status_code != 200:
                return {"query": query, "results": [], "count": 0}

            cards_map = r_cards.json().get("results") or {}
            results = []
            for cid in ids:
                info = cards_map.get(cid)
                if not info:
                    continue
                thumb = info.get("smallThumbnailUrl") or info.get("mediumThumbnailUrl") or ""
                # Direct high-res Google Drive thumbnail (1600px) avoids virus-scan interstitial pages
                full_url = f"https://drive.google.com/thumbnail?sz=w1600-h1600&id={cid}" if info.get("sourceType") == "Google Drive" else (info.get("mediumThumbnailUrl") or thumb)
                if not thumb:
                    continue
                results.append({
                    "id": cid,
                    "name": info.get("name") or query,
                    "source": info.get("sourceName") or info.get("source") or "MPCFill",
                    "dpi": info.get("dpi") or 0,
                    "thumb_url": thumb,
                    "image_url": full_url,
                })
            return {"query": query, "results": results, "count": len(results)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error consultando MPCFill: {exc}")


@router.get("/wikimedia")
async def api_art_wikimedia(q: str = Query(...), limit: int = Query(default=30, ge=1, le=50)):
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query requerida.")
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}",
        "gsrnamespace": "6",
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": "600",
        "format": "json",
    }
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get("https://commons.wikimedia.org/w/api.php", params=params, headers=headers)
        if resp.status_code != 200:
            return {"query": query, "results": [], "count": 0}
        pages = (resp.json().get("query") or {}).get("pages") or {}
        results = []
        for p in pages.values():
            ii = (p.get("imageinfo") or [{}])[0]
            thumb = ii.get("thumburl") or ""
            full_url = ii.get("url") or thumb
            if not thumb or not full_url:
                continue
            meta = ii.get("extmetadata") or {}
            raw_artist = (meta.get("Artist") or {}).get("value") or ""
            artist = re.sub(r"<[^>]+>", "", raw_artist).strip()[:60]
            title = (p.get("title") or "").replace("File:", "").rsplit(".", 1)[0]
            results.append({
                "title": title,
                "artist": artist or "Wikimedia Commons",
                "thumb_url": thumb,
                "image_url": full_url,
            })
        return {"query": query, "results": results, "count": len(results)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error consultando Wikimedia: {exc}")


def _crop_art_box_bytes(raw_bytes: bytes) -> bytes:
    """Recorta solo la ventana del arte de una carta completa (ej. MPCFill con o sin bleed)."""
    with Image.open(io.BytesIO(raw_bytes)) as im:
        rgb = im.convert("RGB")
        w, h = rgb.size
        ratio = w / h if h else 0.0
        # Si incluye bleed MPC (3288x4488, ratio ~0.7326), recortar bleed primero
        if w < h and 0.720 <= ratio <= 0.746:
            bx = int(round(w * (144.0 / 3288.0)))
            by = int(round(h * (144.0 / 4488.0)))
            rgb = rgb.crop((bx, by, w - bx, h - by))
            w, h = rgb.size
        # Recortar la ventana estándar del arte (x: 8%..92%, y: 11.2%..55.4%)
        x0 = int(round(w * 0.078))
        y0 = int(round(h * 0.112))
        x1 = int(round(w * 0.922))
        y1 = int(round(h * 0.554))
        cropped = rgb.crop((x0, y0, max(x0 + 10, x1), max(y0 + 10, y1)))
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=93)
        return buf.getvalue()


@router.get("/proxy")
async def api_art_proxy(url: str = Query(...), crop_art: bool = Query(default=False)):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="URL inválida.")

    cache_key_src = f"{url}|crop_art={int(crop_art)}"
    key = hashlib.sha256(cache_key_src.encode("utf-8")).hexdigest()
    cache_path = os.path.join(_IMG_CACHE_DIR, key)
    meta_path = cache_path + ".mime"

    if os.path.isfile(cache_path) and os.path.isfile(meta_path):
        with open(meta_path, "r", encoding="utf-8") as mf:
            ctype = mf.read().strip() or "image/jpeg"
        with open(cache_path, "rb") as cf:
            return Response(
                content=cf.read(),
                media_type=ctype,
                headers={"Cache-Control": "public, max-age=86400"},
            )

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8",
                    "Referer": f"{parsed.scheme}://{parsed.netloc}/",
                },
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="No se pudo descargar la imagen.")
        content = resp.content
        ctype = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if crop_art:
            content = _crop_art_box_bytes(content)
            ctype = "image/jpeg"
        os.makedirs(_IMG_CACHE_DIR, exist_ok=True)
        with open(cache_path, "wb") as cf:
            cf.write(content)
        with open(meta_path, "w", encoding="utf-8") as mf:
            mf.write(ctype)
        return Response(
            content=content,
            media_type=ctype,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error proxy de imagen: {exc}")
