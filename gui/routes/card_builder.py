import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import tempfile
from typing import Any, Dict, List

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Response, UploadFile
from PIL import Image, ImageDraw

from config import DEFAULT_EXPORT_DPI
from core.art_index import art_index
from core.card_renderer import (
    auto_select_frame_components,
    clamp_export_dpi,
    compose_card_export,
    create_blank_card_from_image,
    extract_scryfall_card_payload,
    jpg_rel_path_to_pdf_abs_path,
    parse_mtgo_txt,
    render_pdf_layer_rgba,
    scan_template_catalog,
)
from core.workspace import check_dir_collision, ensure_workspace_subdirs, resolve_collision_target
from utils.text import safe_card_filename

router = APIRouter(prefix="/api/card-builder")
logger = logging.getLogger(__name__)


@router.get("/templates")
async def api_cb_templates():
    return {"catalog": scan_template_catalog()}


@router.post("/search")
async def api_cb_search(payload: Dict[str, Any] = Body(...)):
    query = (payload.get("query") or "").strip()
    root_dir = (payload.get("root_dir") or "").strip()
    style_key = (payload.get("style_key") or "Automated Templates/normal").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Debe ingresar el nombre de una carta.")

    catalog = scan_template_catalog()
    if root_dir and os.path.isdir(root_dir):
        paths = ensure_workspace_subdirs(root_dir)
        json_path = os.path.join(paths["json"], f"{safe_card_filename(query)}.json")
        if os.path.isfile(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if "frame_components" not in cached:
                cached["frame_components"] = auto_select_frame_components(cached, style_key=style_key, catalog=catalog)
            return {"card": cached, "saved_path": json_path, "cached": True}

    # Priority 1: Try unified local JSON first (if Scryfall fails or offline)
    hd_matches = art_index.lookup_exact(query)
    raw_card = await art_index.fetch_scryfall_card(query, exact=False)

    if raw_card:
        card_payload = extract_scryfall_card_payload(raw_card, count=1, catalog=catalog, style_key=style_key)
    elif hd_matches:
        m = hd_matches[0]
        card_payload = create_blank_card_from_image(m["name"], "", style_key=style_key, catalog=catalog)
        card_payload["art_crop_url"] = m["image_url"]
        card_payload["artist"] = m.get("artist", "")
        card_payload["set"] = m.get("set", "mtg")
        card_payload["art_source"] = "unified_json"
    else:
        raise HTTPException(status_code=404, detail=f"No se encontró la carta '{query}' ni en JSON local ni en Scryfall.")

    saved_path = None
    if root_dir and os.path.isdir(root_dir):
        paths = ensure_workspace_subdirs(root_dir)
        saved_path = os.path.join(paths["json"], f"{safe_card_filename(card_payload['name'])}.json")
        with open(saved_path, "w", encoding="utf-8") as f:
            json.dump(card_payload, f, ensure_ascii=False, indent=2)

    return {"card": card_payload, "saved_path": saved_path, "cached": False}


@router.post("/upload-txt")
async def api_cb_upload_txt(
    root_dir: str = Form(default=""),
    style_key: str = Form(default="Automated Templates/normal"),
    txt_file: UploadFile = File(...),
):
    raw_bytes = await txt_file.read()
    content = raw_bytes.decode("utf-8", errors="replace")
    entries = parse_mtgo_txt(content)
    if not entries:
        raise HTTPException(status_code=400, detail="El archivo .txt no contiene cartas válidas.")

    json_dir = None
    if root_dir and os.path.isdir(root_dir):
        paths = ensure_workspace_subdirs(root_dir)
        json_dir = paths["json"]

    catalog = scan_template_catalog()
    loaded_cards: List[dict] = []
    errors: List[str] = []

    for count, card_name in entries:
        fname = f"{safe_card_filename(card_name)}.json"
        if json_dir:
            json_path = os.path.join(json_dir, fname)
            if os.path.isfile(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        card_payload = json.load(f)
                    card_payload["count"] = count
                    if "frame_components" not in card_payload:
                        card_payload["frame_components"] = auto_select_frame_components(
                            card_payload, style_key=style_key, catalog=catalog
                        )
                    loaded_cards.append(card_payload)
                    continue
                except Exception:
                    pass

        raw_card = await art_index.fetch_scryfall_card(card_name, exact=True)
        if not raw_card:
            raw_card = await art_index.fetch_scryfall_card(card_name, exact=False)

        if raw_card:
            card_payload = extract_scryfall_card_payload(raw_card, count=count, catalog=catalog, style_key=style_key)
        else:
            hd_matches = art_index.lookup_exact(card_name)
            if hd_matches:
                m = hd_matches[0]
                card_payload = create_blank_card_from_image(m["name"], "", style_key=style_key, catalog=catalog)
                card_payload["count"] = count
                card_payload["art_crop_url"] = m["image_url"]
                card_payload["artist"] = m.get("artist", "")
                card_payload["art_source"] = "unified_json"
            else:
                errors.append(card_name)
                continue

        if json_dir:
            with open(os.path.join(json_dir, f"{safe_card_filename(card_payload['name'])}.json"), "w", encoding="utf-8") as f:
                json.dump(card_payload, f, ensure_ascii=False, indent=2)
        loaded_cards.append(card_payload)

    return {"cards": loaded_cards, "errors": errors, "total_unique": len(loaded_cards)}


@router.post("/import-pngs")
async def api_cb_import_pngs(
    style_key: str = Form(default="Automated Templates/normal"),
    files: List[UploadFile] = File(...),
):
    catalog = scan_template_catalog()
    cards = []
    for uf in files:
        fname = uf.filename or "card.png"
        if not fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        raw = await uf.read()
        ext = os.path.splitext(fname)[1].lower().lstrip(".") or "png"
        mime = "jpeg" if ext in ("jpg", "jpeg") else ext
        data_url = f"data:image/{mime};base64,{base64.b64encode(raw).decode('ascii')}"
        stem = os.path.splitext(os.path.basename(fname))[0].replace("_", " ").strip()
        cards.append(create_blank_card_from_image(stem or "Custom Card", data_url, style_key=style_key, catalog=catalog))
    return {"cards": cards, "count": len(cards)}


@router.post("/import-png-dir")
async def api_cb_import_png_dir(payload: Dict[str, Any] = Body(...)):
    dir_path = (payload.get("dir_path") or "").strip()
    style_key = (payload.get("style_key") or "Automated Templates/normal").strip()
    if not dir_path or not os.path.isdir(dir_path):
        raise HTTPException(status_code=400, detail="Directorio de imágenes no encontrado.")

    catalog = scan_template_catalog()
    cards = []
    for fname in sorted(os.listdir(dir_path)):
        if not fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        full_path = os.path.join(dir_path, fname)
        if not os.path.isfile(full_path):
            continue
        with open(full_path, "rb") as f:
            raw = f.read()
        ext = os.path.splitext(fname)[1].lower().lstrip(".") or "png"
        mime = "jpeg" if ext in ("jpg", "jpeg") else ext
        data_url = f"data:image/{mime};base64,{base64.b64encode(raw).decode('ascii')}"
        stem = os.path.splitext(fname)[0].replace("_", " ").strip()
        cards.append(create_blank_card_from_image(stem or "Custom Card", data_url, style_key=style_key, catalog=catalog))
    return {"cards": cards, "count": len(cards)}


@router.post("/save-card")
async def api_cb_save_card(payload: Dict[str, Any] = Body(...)):
    card = payload.get("card")
    root_dir = (payload.get("root_dir") or "").strip()
    if not isinstance(card, dict) or not card.get("name"):
        raise HTTPException(status_code=400, detail="Datos de carta inválidos.")
    if not root_dir:
        raise HTTPException(status_code=400, detail="No hay proyecto activo (root_dir requerido).")

    paths = ensure_workspace_subdirs(root_dir)
    dest = os.path.join(paths["json"], f"{safe_card_filename(card['name'])}.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(card, f, ensure_ascii=False, indent=2)
    return {"status": "ok", "saved_path": dest}


@router.post("/export-batch")
async def api_cb_export_batch(payload: Dict[str, Any] = Body(...)):
    from utils.text import safe_card_filename
    root_dir = (payload.get("root_dir") or "").strip()
    cards = payload.get("cards") or []
    face = (payload.get("face") or "fronts").strip().lower()
    export_format = (payload.get("export_format") or "pdf").strip().lower()
    export_dpi = clamp_export_dpi(payload.get("export_dpi", DEFAULT_EXPORT_DPI))
    collision_mode = payload.get("collision_mode")  # None | "check" | "overwrite" | "version"
    single_card = bool(payload.get("single_card", False))
    explicit_target_dir = (payload.get("target_dir") or "").strip()

    if face not in ("fronts", "backs"):
        raise HTTPException(status_code=400, detail="face must be 'fronts' or 'backs'.")
    if export_format not in ("pdf", "png"):
        raise HTTPException(status_code=400, detail="export_format must be 'pdf' or 'png'.")
    if not root_dir or not os.path.isdir(root_dir):
        raise HTTPException(status_code=400, detail="Invalid active project.")
    if not cards:
        raise HTTPException(status_code=400, detail="No cards selected for export.")

    paths = ensure_workspace_subdirs(root_dir)
    cards_parent = paths["cards"]

    if explicit_target_dir:
        dest_dir = explicit_target_dir
    elif single_card and len(cards) == 1:
        dest_dir = os.path.join(cards_parent, face)
        os.makedirs(dest_dir, exist_ok=True)
        c0 = cards[0].get("card") if isinstance(cards[0], dict) and "card" in cards[0] else cards[0]
        base_fname = safe_card_filename(c0.get("name", "card"))
        ext = "png" if export_format == "png" else "pdf"
        candidate = os.path.join(dest_dir, f"{base_fname}.{ext}")
        if os.path.isfile(candidate):
            if collision_mode in (None, "check"):
                return {
                    "status": "collision",
                    "collision": {
                        "collision": True,
                        "target_dir": candidate,
                        "base_name": f"{base_fname}.{ext}",
                        "suggested_version": f"{base_fname}-1.{ext}",
                    },
                }
            if collision_mode == "version":
                idx = 1
                while os.path.isfile(os.path.join(dest_dir, f"{base_fname}-{idx}.{ext}")):
                    idx += 1
                c0 = dict(c0)
                c0["name"] = f"{base_fname}-{idx}"
                if isinstance(cards[0], dict) and "card" in cards[0]:
                    cards[0]["card"] = c0
                else:
                    cards[0] = c0
    else:
        if collision_mode in (None, "check"):
            col_info = check_dir_collision(cards_parent, face)
            if col_info["collision"]:
                return {"status": "collision", "collision": col_info}
        dest_dir = resolve_collision_target(cards_parent, face, collision_mode or "version")
    loop = asyncio.get_running_loop()
    exported_files = []

    for item in cards:
        card = item.get("card") if isinstance(item, dict) and "card" in item else item
        art_b64 = item.get("art_overlay_data_url", "") if isinstance(item, dict) else ""
        txt_b64 = item.get("text_overlay_data_url", "") if isinstance(item, dict) else ""
        full_b64 = item.get("image_data_url", "") if isinstance(item, dict) else ""
        card_name = card.get("name", "card")

        dest_path, _ = await loop.run_in_executor(
            None,
            lambda c=card, n=card_name, d=dest_dir, ab=art_b64, tb=txt_b64, fb=full_b64: compose_card_export(
                c, n, d, ab, tb, fb, export_dpi=export_dpi, export_format=export_format
            ),
        )
        exported_files.append(dest_path)

    return {
        "status": "ok",
        "dest_dir": dest_dir,
        "exported_count": len(exported_files),
        "files": exported_files,
        "dpi": export_dpi,
        "format": export_format,
    }


@router.post("/auto-frame")
async def api_cb_auto_frame(payload: Dict[str, Any] = Body(...)):
    card = payload.get("card") or {}
    style_key = (payload.get("style_key") or "Automated Templates/normal").strip()
    catalog = scan_template_catalog()
    fc = auto_select_frame_components(card, style_key=style_key, catalog=catalog)
    return {"frame_components": fc}


_TPL_PREVIEW_CACHE_DIR = os.path.join(tempfile.gettempdir(), "deckgen_tpl_previews_v1")


def _render_template_preview_bytes(style_key: str) -> bytes:
    os.makedirs(_TPL_PREVIEW_CACHE_DIR, exist_ok=True)
    digest = hashlib.md5(style_key.encode("utf-8")).hexdigest()[:12]
    cache_path = os.path.join(_TPL_PREVIEW_CACHE_DIR, f"{digest}.jpg")
    if os.path.isfile(cache_path):
        with open(cache_path, "rb") as f:
            return f.read()

    w, h = 225, 315
    catalog = scan_template_catalog()
    sample_card = {
        "name": "Example Card",
        "type_line": "Legendary Creature — Wizard",
        "colors": ["U"],
        "color_identity": ["U"],
        "power": "3",
        "toughness": "3",
    }
    fc = auto_select_frame_components(sample_card, style_key=style_key, catalog=catalog)

    canvas = Image.new("RGBA", (w, h), (17, 17, 17, 255))

    def _draw_layer(layer_key: str):
        rel = fc.get(layer_key)
        if not rel:
            return
        pdf_p = jpg_rel_path_to_pdf_abs_path(rel)
        if not pdf_p:
            return
        try:
            rgba = render_pdf_layer_rgba(pdf_p, w, h)
            canvas.alpha_composite(rgba)
        except Exception:
            pass

    _draw_layer("background")

    # Subtle sample artwork gradient inside the art box so the template layout is immediately clear
    art_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ad = ImageDraw.Draw(art_layer)
    ax0, ay0, ax1, ay1 = 10, 33, 215, 176
    for yy in range(ay0, ay1):
        t = (yy - ay0) / max(1, (ay1 - ay0))
        r = int(28 + 38 * t)
        g = int(52 + 72 * (1 - abs(t - 0.5) * 2))
        b = int(95 + 80 * (1 - t))
        ad.line([(ax0, yy), (ax1, yy)], fill=(r, g, b, 255))
    # Decorative moon/silhouette accent in sample art
    ad.ellipse([142, 48, 184, 90], fill=(230, 240, 255, 190))
    ad.polygon([(10, 176), (72, 112), (138, 176)], fill=(18, 28, 48, 220))
    ad.polygon([(95, 176), (160, 102), (215, 176)], fill=(14, 22, 38, 235))
    canvas.alpha_composite(art_layer)

    for lk in ("pinlines", "name_box", "crown", "pt_box"):
        _draw_layer(lk)

    # Sample placeholder text strokes so the user sees text areas clearly
    td = ImageDraw.Draw(canvas)
    td.text((18, 20), "Example Card", fill=(20, 20, 20, 235))
    td.text((18, 182), "Creature — Wizard", fill=(20, 20, 20, 235))
    td.text((18, 212), "Flying, vigilance", fill=(30, 30, 30, 215))
    td.text((18, 228), "Whenever this attacks,", fill=(30, 30, 30, 205))
    td.text((18, 242), "draw a card.", fill=(30, 30, 30, 205))
    td.text((184, 284), "3/3", fill=(20, 20, 20, 235))

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="JPEG", quality=86)
    data = buf.getvalue()
    try:
        with open(cache_path, "wb") as f:
            f.write(data)
    except Exception:
        pass
    return data


@router.get("/template-preview")
async def api_cb_template_preview(style: str = Query(...)):
    style_key = style.strip()
    if not style_key:
        raise HTTPException(status_code=400, detail="Missing style parameter")
    loop = asyncio.get_running_loop()
    img_bytes = await loop.run_in_executor(None, lambda: _render_template_preview_bytes(style_key))
    return Response(
        content=img_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )
