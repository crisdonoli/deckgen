import asyncio
import base64
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

from config import DATA_DIR, FRAMES_DIR, SHARED_DIR
from core.asset_catalog import build_folder_frame_catalog, scan_frames_from_folders, scan_shared_folder
from core.asset_paths import frame_file_path, frame_url, shared_file_path, shared_url
from core.card_layouts import load_frame_layouts
from core.card_renderer import save_recipe_png
from core.frame_resolver import build_recipe
from core.workspace import ensure_workspace_subdirs
from services.card_project import (
    USER_AGENT,
    ScryfallError,
    _throttle_scryfall,
    build_card_project,
    cache_path_for_key,
    load_project_file,
    register_card_project,
    resolve_card,
    save_project_file,
)
from utils.text import safe_card_filename

router = APIRouter(prefix="/api/card-builder")

_SCRYFALL_SEARCH_URL = "https://api.scryfall.com/cards/search"
_SEARCH_TTL = 300.0
_SEARCH_CACHE_MAX = 100
_search_cache: Dict[tuple, tuple] = {}
_SYMBOLS_CACHE: Dict[str, Any] | None = None


_MATERIAL_LABELS = {
    "white_marble": "White (Marble)",
    "blue_water": "Blue (Water)",
    "black_swamp": "Black (Swamp)",
    "red_volcanic": "Red (Volcanic)",
    "green_bark": "Green (Bark)",
    "gold_metallic": "Multicolor (Gold)",
    "artifact_steel_modern": "Artifact (Steel)",
    "artifact_brown_retro": "Artifact (Retro)",
    "colorless_stone": "Colorless (Stone)",
    "land_neutral": "Land (Neutral)",
    "vehicle_bronze_riveted": "Vehicle (Bronze)",
    "nyx_starfield": "Nyx (Starfield)",
    "transparent_fullart": "Full-Art",
    "showcase_custom": "Showcase",
}

_FRAME_ERA_LABELS = {
    "2015": "M15",
    "2003": "8th Edition",
    "1997": "Retro 1997",
    "1993": "Classic 1993",
    "future": "Future Sight",
}

_LAYOUT_LABELS = {
    "modal_dfc": "Modal DFC",
    "transform": "Transform",
    "saga": "Saga",
    "adventure": "Adventure",
    "class": "Class",
    "battle": "Battle",
    "split": "Split",
    "token": "Token",
}

_STRUCTURAL_LABELS = {
    "planeswalker": "Planeswalker",
    "saga": "Saga",
    "class": "Class",
    "battle": "Battle",
}

_CROWN_LABELS = {
    "standard": "Legendary Crown",
    "floating": "Floating Crown",
    "companion": "Companion Crown",
    "nyx": "Nyx Crown",
}

_BORDER_LABELS = {
    "black": "Black Border",
    "white": "White Border",
    "silver": "Silver Border",
    "gold": "Gold Border",
    "borderless": "Borderless",
}


def _taxonomy_label(role, frame_era, layout, structural, box_variant, crown_style, showcase_style, material, border_color, orig_path):
    parts = []
    p = str(orig_path or "").lower()
    if role == "border":
        if border_color and border_color in _BORDER_LABELS:
            parts.append(_BORDER_LABELS[border_color])
        elif "white" in p:
            parts.append("Borde Blanco")
        elif "silver" in p:
            parts.append("Borde Plateado")
        elif "gold" in p:
            parts.append("Borde Dorado")
        else:
            parts.append("Borde Negro")
    elif role == "stamp":
        if material and material in _MATERIAL_LABELS:
            parts.append(f"Sello {_MATERIAL_LABELS[material]}")
        elif "holostamp" in p or "stamp.png" in p:
            parts.append("Sello Holo Ovalado")
        else:
            parts.append("Sello Holo")
    elif role == "crown":
        if material and material in _MATERIAL_LABELS:
            parts.append(_MATERIAL_LABELS[material])
        if crown_style and crown_style in _CROWN_LABELS:
            parts.append(_CROWN_LABELS[crown_style])
        else:
            parts.append("Corona Legendaria")
    elif role == "pt_box":
        if material and material in _MATERIAL_LABELS:
            parts.append(_MATERIAL_LABELS[material])
        else:
            parts.append("Caja F/R")
    else:
        if material and material in _MATERIAL_LABELS:
            parts.append(_MATERIAL_LABELS[material])

    if structural and structural in _STRUCTURAL_LABELS:
        tag = _STRUCTURAL_LABELS[structural]
        if box_variant == "tall":
            tag += " Alto"
        parts.append(tag)
    elif layout and layout in _LAYOUT_LABELS:
        parts.append(_LAYOUT_LABELS[layout])
    elif "extended" in p:
        parts.append("Arte Extendido")
    elif "fullart" in p or "borderless" in p:
        parts.append("Sin Borde")
    elif showcase_style and showcase_style not in ("none", ""):
        parts.append(str(showcase_style).replace("_", " ").title())
    elif frame_era and frame_era in _FRAME_ERA_LABELS:
        parts.append(_FRAME_ERA_LABELS[frame_era])

    if not parts:
        return "Estándar"
    # Deduplicate preserving order
    seen = set()
    uniq = []
    for item in parts:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    return " · ".join(uniq)


def _infer_carousel_template(orig_path: str, frame_era, layout, structural, box_variant) -> str:
    p = str(orig_path or "").lower()
    if structural == "planeswalker" or "/planeswalker/" in p:
        return "PlaneswalkerTall" if (box_variant == "tall" or "/tall/" in p) else "PlaneswalkerRegular"
    if layout == "modal_dfc" or "/modal/" in p:
        return "ModalShort" if "/modal/short/" in p else "ModalRegular"
    if layout == "transform" or "/transform/" in p:
        return "TransformRegular"
    if layout == "saga" or "/saga/" in p:
        return "SagaRegular"
    if "/extended/" in p:
        return "M15Extended"
    if "/fullart/" in p or "/borderless/" in p:
        return "M15Borderless"
    if frame_era == "2003" or "/8th/" in p:
        return "Eighth"
    if frame_era == "1997" or "/7th/" in p:
        return "Seventh"
    if frame_era == "future" or "/future/" in p:
        return "Future"
    return "M15Regular"


def _carousel_priority(role: str, orig_path: str) -> int:
    p = str(orig_path or "").lower()
    if role == "base_frame":
        if p.startswith("img/frames/m15/new/") and p.count("/") == 4:
            return 0
        if p.startswith("img/frames/m15/new/extended/"):
            return 1
        if p.startswith("img/frames/m15/new/fullart/"):
            return 2
        if p.startswith("img/frames/m15/new/nyx/"):
            return 3
        if p.startswith("img/frames/modal/regular/"):
            return 4
        if p.startswith("img/frames/planeswalker/"):
            return 5
        if p.startswith("img/frames/8th/") and p.count("/") == 3:
            return 6
        return 10
    if role == "crown":
        if "m15/crowns/new/" in p:
            return 0
        if "m15/crowns/" in p:
            return 1
        return 5
    if role == "pt_box":
        if "m15/new/" in p or "m15/regular/" in p:
            return 0
        if "8th/pt/" in p:
            return 1
        return 5
    if role == "stamp":
        if "holostamps/stamp.png" in p:
            return 0
        if "holostamps/m15holostamp" in p:
            return 1
        if "m15/ub/regular/stamp/" in p:
            return 2
        return 5
    if role == "border":
        if "m15/new/border.png" in p:
            return 0
        if "m15/" in p:
            return 1
        return 5
    return 10


def _build_symbols_payload() -> Dict[str, Any]:
    global _SYMBOLS_CACHE
    if _SYMBOLS_CACHE is not None:
        return _SYMBOLS_CACHE

    mana_map: Dict[str, str] = {}
    set_map: Dict[str, str] = {}
    frames_by_role: Dict[str, list] = {
        "background": [],
        "name_box": [],
        "crown": [],
        "border": [],
        "pt_box": [],
    }
    defaults_by_material: Dict[str, Dict[str, str]] = {
        "crown": {},
        "pt_box": {},
        "border": {},
        "stamp": {},
    }

    mana_files = scan_shared_folder("mana_symbol")
    for code, rel in mana_files.items():
        mana_map[code] = shared_url(rel)
    if "untap" in mana_map and "q" not in mana_map:
        mana_map["q"] = mana_map["untap"]
    if "inf" in mana_map and "∞" not in mana_map:
        mana_map["∞"] = mana_map["inf"]
    if "half" in mana_map:
        mana_map.setdefault("1/2", mana_map["half"])
        mana_map.setdefault("½", mana_map["half"])

    set_files = scan_shared_folder("set_symbol")
    for code, rel in set_files.items():
        set_map[code] = shared_url(rel)
        if code.endswith("-c"):
            set_map.setdefault(code[:-2], shared_url(rel))

    role_to_slot = {
        "base_frame": "background",
        "stamp": "name_box",
        "crown": "crown",
        "border": "border",
        "pt_box": "pt_box",
    }
    rows = scan_frames_from_folders()

    bucket_items: Dict[str, list] = {k: [] for k in frames_by_role}
    tax_sets: Dict[str, set] = {
        "frame_era": set(),
        "layout": set(),
        "material": set(),
        "showcase_style": set(),
        "structural": set(),
    }
    for row in rows:
        non_off = row.get("non_official_category") or "official_mtg"
        if non_off not in ("official_mtg", "custom_mtg_community"):
            continue
        role = row.get("asset_role")
        if role not in role_to_slot:
            continue
        fid = row.get("id")
        orig_path = row.get("original_path") or ""
        fname = row.get("file") or ""
        frame_era = row.get("frame")
        layout = row.get("layout")
        structural = row.get("structural_type_override")
        box_variant = row.get("box_variant")
        crown_style = row.get("crown_style")
        showcase_style = row.get("showcase_style")
        material = row.get("frame_texture_material")
        border_color = row.get("border_color")
        p_low = str(orig_path or "").lower()
        if not fname or fid == "4d82f3272976dc05" or "cornercutout" in p_low or "acorn.png" in p_low or "alchemy.png" in p_low:
            continue
        if role == "border" and "/margins/" in p_low:
            continue
        slot = role_to_slot.get(role)
        if not slot:
            continue
        url = frame_url(str(fname))
        label = _taxonomy_label(
            role, frame_era, layout, structural, box_variant, crown_style, showcase_style, material, border_color, orig_path
        )
        prio = _carousel_priority(role, orig_path) + (100 if non_off != "official_mtg" else 0)
        if role == "base_frame":
            if frame_era:
                tax_sets["frame_era"].add(frame_era)
            if layout:
                tax_sets["layout"].add(layout)
            if material:
                tax_sets["material"].add(material)
            if showcase_style and showcase_style not in ("none", ""):
                tax_sets["showcase_style"].add(showcase_style)
            if structural and structural not in ("standard", ""):
                tax_sets["structural"].add(structural)
        bucket_items[slot].append((
            prio,
            label,
            {
                "id": fid,
                "filename": fname,
                "rel_path": url,
                "url": url,
                "label": label,
                "asset_role": role,
                "frame_era": frame_era or "",
                "layout": layout or "",
                "structural": structural or "",
                "box_variant": box_variant or "",
                "crown_style": crown_style or "",
                "showcase_style": showcase_style or "",
                "material": material or "",
                "border_color": border_color or "",
                "non_official_category": non_off,
                "template": _infer_carousel_template(orig_path, frame_era, layout, structural, box_variant) if role == "base_frame" else None,
            },
        ))

        if role == "crown" and material and "m15/crowns/new/" in p_low:
            defaults_by_material["crown"].setdefault(material, url)
        elif role == "crown" and material:
            defaults_by_material["crown"].setdefault(material, url)
        elif role == "pt_box" and material and ("m15/regular/" in p_low or "m15/new/" in p_low):
            defaults_by_material["pt_box"].setdefault(material, url)
        elif role == "pt_box" and material:
            defaults_by_material["pt_box"].setdefault(material, url)
        elif role == "border" and "m15/new/border.png" in p_low:
            defaults_by_material["border"]["default"] = url
        elif role == "border" and "black" in p_low:
            defaults_by_material["border"].setdefault("default", url)
        elif role == "stamp" and "holostamps/stamp.png" in p_low:
            defaults_by_material["stamp"]["default"] = url
        elif role == "stamp" and "m15/ub/regular/stamp/" in p_low and material:
            defaults_by_material["stamp"].setdefault(material, url)

    for slot, entries in bucket_items.items():
        entries.sort(key=lambda x: (x[0], x[1]))
        frames_by_role[slot] = [item for _, _, item in entries]

    layouts_data = load_frame_layouts() or {}
    templates = layouts_data.get("templates") or {}
    taxonomy_options = {
        "frame_era": [
            {"value": v, "label": _FRAME_ERA_LABELS.get(v, v)}
            for v in sorted(tax_sets["frame_era"])
        ],
        "layout": [
            {"value": v, "label": _LAYOUT_LABELS.get(v, v.replace("_", " ").title())}
            for v in sorted(tax_sets["layout"])
        ],
        "material": [
            {"value": v, "label": _MATERIAL_LABELS.get(v, v.replace("_", " ").title())}
            for v in sorted(tax_sets["material"])
        ],
        "showcase_style": [
            {"value": v, "label": v.replace("_", " ").title()}
            for v in sorted(tax_sets["showcase_style"])
        ],
        "structural": [
            {"value": v, "label": _STRUCTURAL_LABELS.get(v, v.replace("_", " ").title())}
            for v in sorted(tax_sets["structural"])
        ],
    }

    frame_catalog = build_folder_frame_catalog()

    _SYMBOLS_CACHE = {
        "mana": mana_map,
        "sets": set_map,
        "templates": templates,
        "frames_by_role": frames_by_role,
        "defaults_by_material": defaults_by_material,
        "taxonomy_options": taxonomy_options,
        "frame_catalog": frame_catalog,
    }
    return _SYMBOLS_CACHE


@router.get("/symbols")
async def api_cb_symbols():
    return _build_symbols_payload()


@router.post("/open-component-folder")
async def api_cb_open_component_folder(payload: Dict[str, Any] = Body(...)):
    raw = str(payload.get("url") or payload.get("path") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Component path is required.")
    unquoted = urllib.parse.unquote(raw)
    if unquoted.startswith("/assets/resources/frames/"):
        rel = unquoted[len("/assets/resources/frames/"):]
        target = frame_file_path(rel).resolve()
        root = Path(FRAMES_DIR).resolve()
    elif unquoted.startswith("/assets/resources/_shared/"):
        rel = unquoted[len("/assets/resources/_shared/"):]
        target = shared_file_path(rel).resolve()
        root = Path(SHARED_DIR).resolve()
    else:
        target = frame_file_path(unquoted).resolve()
        root = Path(FRAMES_DIR).resolve()

    if root != target and root not in target.parents:
        raise HTTPException(status_code=403, detail="Invalid component path.")
    folder = target.parent if target.is_file() else (target if target.is_dir() else target.parent)
    if not folder.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found on disk.")

    try:
        if sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        elif sys.platform == "darwin":
            cmd = ["open", "-R", str(target)] if target.is_file() else ["open", str(folder)]
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        elif os.name == "nt":
            if target.is_file():
                subprocess.Popen(["explorer", "/select,", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["explorer", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not open folder: {exc}")

    return {"ok": True, "folder": str(folder), "file": str(target)}


def _search_card(card: dict) -> dict:
    face = (card.get("card_faces") or [{}])[0]
    images = card.get("image_uris") or face.get("image_uris") or {}
    item = {
        "id": card.get("id"),
        "name": card.get("name"),
        "set": card.get("set"),
        "set_name": card.get("set_name"),
        "collector_number": card.get("collector_number"),
        "rarity": card.get("rarity"),
        "mana_cost": card.get("mana_cost") or face.get("mana_cost") or "",
        "type_line": card.get("type_line") or face.get("type_line") or "",
        "layout": card.get("layout"),
        "image": images.get("normal") or "",
        "art_crop": images.get("art_crop") or "",
        "scryfall_uri": card.get("scryfall_uri"),
        "oracle_text": card.get("oracle_text") or face.get("oracle_text") or "",
        "artist": card.get("artist") or face.get("artist") or "",
    }
    item["art_crop_url"] = item["art_crop"]
    return item


def _search_cache_get(key):
    entry = _search_cache.get(key)
    if entry and time.monotonic() - entry[0] < _SEARCH_TTL:
        return entry[1]
    return None


def _search_cache_put(key, payload):
    if len(_search_cache) >= _SEARCH_CACHE_MAX:
        _search_cache.pop(next(iter(_search_cache)))
    _search_cache[key] = (time.monotonic(), payload)


def _search_payload(query, page, cards, has_more, total_cards) -> dict:
    return {
        "query": query,
        "page": page,
        "has_more": has_more,
        "total_cards": total_cards,
        "results": cards,
        "cards": cards,
    }


@router.post("/search")
async def api_cb_search(payload: Dict[str, Any] = Body(...)):
    query = (payload.get("query") or "").strip()
    if not query:
        return JSONResponse(status_code=400, content={"error": "empty_query"})
    page = int(payload.get("page") or 1)
    page_size = int(payload.get("page_size") or 20)
    unique = payload.get("unique") if payload.get("unique") in ("cards", "prints") else "cards"

    key = (query.lower(), page, unique, page_size)
    cached = _search_cache_get(key)
    if cached is not None:
        return cached

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    params = {"q": query, "page": page, "unique": unique, "order": "name"}
    await asyncio.get_running_loop().run_in_executor(None, _throttle_scryfall)
    try:
        async with httpx.AsyncClient(headers=headers, timeout=20.0, transport=httpx.AsyncHTTPTransport(local_address="0.0.0.0", retries=2)) as client:
            resp = await client.get(_SCRYFALL_SEARCH_URL, params=params)
    except httpx.HTTPError:
        return JSONResponse(status_code=502, content={"error": "scryfall_unavailable"})

    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After") or ""
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited", "retry_after": int(retry_after) if retry_after.isdigit() else 60},
        )
    if resp.status_code == 404:
        empty = _search_payload(query, page, [], False, 0)
        _search_cache_put(key, empty)
        return empty
    if resp.status_code >= 400:
        return JSONResponse(status_code=502, content={"error": "scryfall_unavailable"})

    body = resp.json()
    cards = [_search_card(c) for c in (body.get("data") or [])][:page_size]
    result = _search_payload(query, page, cards, bool(body.get("has_more")), int(body.get("total_cards") or 0))
    _search_cache_put(key, result)
    return result


def _project_recipe(card: dict, face_index, showcase_style_override) -> dict:
    source = dict(card)
    if showcase_style_override:
        source["showcase_style_override"] = showcase_style_override
    recipe = build_recipe(source)
    if face_index is not None:
        recipe["recipes"] = [r for r in recipe.get("recipes") or [] if r.get("face_index") == face_index]
    return recipe


@router.post("/import-scryfall")
async def api_cb_import_scryfall(payload: Dict[str, Any] = Body(...)):
    try:
        card = resolve_card(
            card=payload.get("card"),
            url=(payload.get("url") or "").strip() or None,
            name=(payload.get("name") or "").strip() or None,
            set_code=(payload.get("set") or "").strip() or None,
        )
    except ScryfallError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)

    face_index = payload.get("face_index")
    face_index = int(face_index) if face_index is not None else None
    showcase_style_override = (payload.get("showcase_style_override") or None)
    loop = asyncio.get_running_loop()
    project = await loop.run_in_executor(
        None,
        lambda: build_card_project(
            card,
            face_index=face_index,
            showcase_style_override=showcase_style_override,
        ),
    )

    root_dir = (payload.get("root_dir") or "").strip()
    if root_dir and os.path.isdir(root_dir):
        register_card_project(root_dir, project)
    return project


@router.get("/project/{project_id}")
async def api_cb_project(project_id: str):
    project = load_project_file(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
    return project


@router.get("/asset/{key}")
async def api_cb_asset(key: str):
    path = cache_path_for_key(key)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Asset no encontrado.")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.post("/export-batch")
async def api_cb_export_batch(payload: Dict[str, Any] = Body(...)):
    root_dir = (payload.get("root_dir") or "").strip()
    project_ids = payload.get("project_ids") or []
    target_dir = (payload.get("target_dir") or "").strip()

    if not root_dir or not os.path.isdir(root_dir):
        raise HTTPException(status_code=400, detail="Invalid active project.")
    if not project_ids:
        raise HTTPException(status_code=400, detail="No projects selected for export.")

    dest_dir = target_dir or os.path.join(ensure_workspace_subdirs(root_dir)["cards"], "png")
    os.makedirs(dest_dir, exist_ok=True)

    files = []
    for project_id in project_ids:
        project = load_project_file(project_id)
        if project is None or not project.get("recipe"):
            raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        out_path = os.path.join(dest_dir, f"{safe_card_filename(project.get('name') or project_id)}.png")
        save_recipe_png(project["recipe"], out_path)
        files.append(out_path)

    return {"status": "ok", "dest_dir": dest_dir, "exported_count": len(files), "files": files}


@router.post("/export")
async def api_cb_export(payload: Dict[str, Any] = Body(...)):
    project = load_project_file(payload.get("project_id") or "")
    if project is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")

    face_index = payload.get("face_index")
    face_index = 0 if face_index is None else int(face_index)
    recipe = dict(project.get("recipe") or {})
    all_recipes = recipe.get("recipes") or []
    faces = [r for r in all_recipes if (r.get("face_index") or 0) == face_index]
    if faces:
        target_face = dict(faces[0])
        if isinstance(payload.get("text_layers"), dict):
            merged_tl = dict(target_face.get("text_layers") or {})
            for k, v in payload["text_layers"].items():
                if isinstance(v, dict):
                    merged_tl[k] = {**(merged_tl.get(k) or {}), **v}
            target_face["text_layers"] = merged_tl
        recipe["recipes"] = [target_face]

    art_override = None
    data_url = payload.get("art_override_dataurl")
    if data_url:
        header, _, encoded = data_url.partition(",")
        if not header.startswith("data:image/") or not encoded:
            raise HTTPException(status_code=400, detail="dataURL inválida.")
        try:
            art_override = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise HTTPException(status_code=400, detail="dataURL inválida.")

    fd, out_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        save_recipe_png(recipe, out_path, art_override=art_override)
        with open(out_path, "rb") as handle:
            png_bytes = handle.read()
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
    finally:
        if os.path.exists(out_path):
            os.remove(out_path)

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": 'attachment; filename="card.png"'},
    )

