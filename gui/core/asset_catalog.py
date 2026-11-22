"""Folder-backed asset discovery for frames, fonts, mana symbols, and set symbols (no SQLite DB)."""

import json
import os
import re
import urllib.parse
from pathlib import Path
from typing import Dict, List

from config import DATA_DIR, FRAMES_DIR, SHARED_DIR

FRAME_METADATA_PATH = os.path.join(DATA_DIR, "frame_metadata.json")
FRAME_CATALOG_PATH = os.path.join(DATA_DIR, "frame_catalog.json")

_META_CACHE: Dict[str, dict] | None = None

_SHARED_SUBDIRS = {
    "font": "fonts",
    "mana_symbol": "mana_symbols",
    "set_symbol": "set_symbols",
}


def _load_frame_metadata() -> Dict[str, dict]:
    global _META_CACHE
    if _META_CACHE is None:
        if os.path.isfile(FRAME_METADATA_PATH):
            with open(FRAME_METADATA_PATH, "r", encoding="utf-8") as fh:
                _META_CACHE = json.load(fh)
        else:
            _META_CACHE = {}
    return _META_CACHE


def scan_shared_folder(category: str) -> Dict[str, str]:
    """Scan assets/resources/_shared/<subdir> directly on disk -> {code_lower: 'subdir/filename'}."""
    sub = _SHARED_SUBDIRS.get(category, category)
    folder = Path(SHARED_DIR) / sub
    out: Dict[str, str] = {}
    if not folder.is_dir():
        return out
    for root, _, files in os.walk(folder):
        for fname in sorted(files):
            if fname.startswith("."):
                continue
            full = Path(root) / fname
            rel = full.relative_to(SHARED_DIR).as_posix()
            code = full.stem.strip().lower()
            if code and code not in out:
                out[code] = rel
    return out


def _infer_role_from_path(rel_path: str) -> str:
    p = rel_path.lower()
    if "/crowns/" in p or "crown" in p:
        return "crown"
    if "/pt/" in p or re.search(r"pt[wubrgmaclv]\.png$", p) or "ptbox" in p or "pt_box" in p:
        return "pt_box"
    if "/holostamps/" in p or "stamp" in p:
        return "stamp"
    if "mask" in p:
        return "mask"
    if "pinline" in p:
        return "pinline"
    if ("border" in p or "/margins/" in p) and "borderless" not in p:
        return "border"
    return "base_frame"


def scan_frames_from_folders() -> List[dict]:
    """Walk assets/resources/frames/ directly on disk and merge optional taxonomy metadata."""
    meta = _load_frame_metadata()
    rows: List[dict] = []
    base = Path(FRAMES_DIR)
    if not base.is_dir():
        return rows

    for root, _, files in os.walk(base):
        for fname in sorted(files):
            fl = fname.lower()
            if not (fl.endswith(".png") or fl.endswith(".svg") or fl.endswith(".jpg") or fl.endswith(".jpeg")):
                continue
            if "thumb." in fl or fname.startswith("."):
                continue
            rel = (Path(root) / fname).relative_to(base).as_posix()
            rec = meta.get(rel)
            if rec:
                row = dict(rec)
                row["file"] = rel
            else:
                role = _infer_role_from_path(rel)
                row = {
                    "id": rel,
                    "original_path": f"img/frames/{rel}",
                    "file": rel,
                    "width": None,
                    "height": None,
                    "frame": "2015",
                    "layout": "normal",
                    "structural_type_override": "standard",
                    "box_variant": "regular",
                    "frame_effects": "[]",
                    "crown_style": "standard" if role == "crown" else "none",
                    "has_nickname": 0,
                    "border_color": "black",
                    "corner_cut": "modern_radius",
                    "frame_texture_material": "",
                    "showcase_style": "none",
                    "color_blend_mode": "monocolor",
                    "non_official_category": "custom_mtg_community",
                    "asset_role": role,
                }
            rows.append(row)
    return rows


def build_folder_frame_catalog() -> dict:
    """Load Card Conjurer ordered groups verified live against disk, plus any new custom folders."""
    base = Path(FRAMES_DIR)
    catalog_groups: List[dict] = []
    known_rels: set = set()

    if os.path.isfile(FRAME_CATALOG_PATH):
        try:
            with open(FRAME_CATALOG_PATH, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            for g in raw.get("groups") or []:
                valid_packs = []
                for p in g.get("packs") or []:
                    valid_items = []
                    for it in p.get("items") or []:
                        rel = str(it.get("rel_path") or "").lstrip("/")
                        if rel and (base / rel).is_file():
                            known_rels.add(rel)
                            valid_items.append(it)
                    if valid_items:
                        valid_packs.append({**p, "items": valid_items})
                if valid_packs:
                    catalog_groups.append({**g, "packs": valid_packs})
        except Exception:
            pass

    # Discover any brand-new files added directly to assets/resources/frames/<folder>/
    role_to_slot = {
        "base_frame": "background",
        "crown": "crown",
        "pt_box": "pt_box",
        "border": "border",
        "stamp": "name_box",
    }
    extra_by_folder: Dict[str, List[dict]] = {}
    if base.is_dir():
        for root, _, files in os.walk(base):
            for fname in sorted(files):
                fl = fname.lower()
                if not (fl.endswith(".png") or fl.endswith(".jpg") or fl.endswith(".jpeg")):
                    continue
                if "thumb." in fl or fname.startswith("."):
                    continue
                rel = (Path(root) / fname).relative_to(base).as_posix()
                if rel in known_rels:
                    continue
                role = _infer_role_from_path(rel)
                slot = role_to_slot.get(role)
                if not slot:
                    continue
                folder_key = os.path.dirname(rel) or "Root"
                extra_by_folder.setdefault(folder_key, []).append({
                    "name": Path(fname).stem.replace("_", " "),
                    "rel_path": rel,
                    "url": "/assets/resources/frames/" + urllib.parse.quote(rel, safe="/"),
                    "slot": slot,
                    "group": "Local Folders (Added)",
                    "group_id": "LocalFolders",
                    "pack": folder_key,
                    "pack_id": f"folder:{folder_key}",
                })

    if extra_by_folder:
        extra_packs = [
            {"id": f"folder:{fk}", "name": fk, "section": "Local", "items": items}
            for fk, items in sorted(extra_by_folder.items())
        ]
        catalog_groups.append({
            "id": "LocalFolders",
            "name": "Local Folders (Added)",
            "packs": extra_packs,
        })

    return {"groups": catalog_groups}
