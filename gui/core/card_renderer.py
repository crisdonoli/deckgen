import base64
import gc
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageOps

from config import (
    ASSETS_DIR,
    DEFAULT_EXPORT_DPI,
    DPI,
    MAX_EXPORT_DPI,
    MIN_EXPORT_DPI,
    STANDARD_CARD_H_PX,
    STANDARD_CARD_W_PX,
)
from core.art_index import art_index
from utils.conversions import parse_hex
from utils.text import safe_card_filename

try:
    import pymupdf  # type: ignore
except ImportError:
    pymupdf = None

Image.MAX_IMAGE_PIXELS = max(getattr(Image, "MAX_IMAGE_PIXELS", 89478485) or 89478485, 120_000_000)

CARD_WIDTH_INCHES = 2.5
BASE_DPI = STANDARD_CARD_W_PX / float(CARD_WIDTH_INCHES)


def pt(points: float) -> int:
    return int(round((points * BASE_DPI) / 72.0))


DEFAULT_LAYOUT = {
    "canvas": {"w": STANDARD_CARD_W_PX, "h": STANDARD_CARD_H_PX},
    "art": {"x": 34, "y": 109, "w": 682, "h": 477, "scale": 1.0, "offset_x": 0, "offset_y": 0},
    "title": {"x": 56, "y": 90, "max_w": 490, "font_size": pt(9.0), "color": "#111111"},
    "official_title": {"x": 56, "y": 114, "max_w": 490, "font_size": pt(5.5), "color": "#111111"},
    "mana_cost": {"x": 692, "y": 88, "size": pt(8.5), "align": "right"},
    "type_line": {"x": 56, "y": 629, "max_w": 550, "font_size": pt(7.5), "color": "#111111"},
    "set_symbol": {"x": 692, "y": 620, "size": pt(9.8), "align": "right"},
    "oracle_box": {"x": 56, "y": 663, "w": 638, "h": 303, "font_size": pt(7.2), "color": "#111111"},
    "pt_box": {"x": 580, "y": 934, "w": 135, "h": 71},
    "pt_text": {"x": 648, "y": 970, "font_size": pt(9.2), "color": "#111111"},
    "artist": {"x": 47, "y": 1022, "font_size": pt(4.3), "color": "#ffffff"},
}

GUILD_PAIRS = ["WU", "UB", "BR", "RG", "GW", "WB", "BG", "GU", "UR", "RW"]


def clamp_export_dpi(raw_dpi: Any) -> int:
    try:
        val = int(round(float(raw_dpi)))
    except (TypeError, ValueError):
        val = DEFAULT_EXPORT_DPI
    return max(MIN_EXPORT_DPI, min(MAX_EXPORT_DPI, val))


def get_color_code_for_templates(colors, color_identity, type_line):
    tl = (type_line or "").lower()
    active_colors = colors if colors else (color_identity if "land" in tl else [])
    if len(active_colors) == 1:
        return active_colors[0], active_colors[0]
    if len(active_colors) == 2:
        pair_set = set(active_colors)
        for gp in GUILD_PAIRS:
            if set(gp) == pair_set:
                return gp, "Gold"
        return "Gold", "Gold"
    if len(active_colors) > 2:
        return "Gold", "Gold"
    if "vehicle" in tl:
        return "Vehicle", "Vehicle"
    if "artifact" in tl:
        return "Artifact", "Artifact"
    if "land" in tl:
        return "Land", "Land"
    return "Colourless", "Colourless"


def scan_template_catalog() -> Dict[str, Dict[str, List[dict]]]:
    catalog: Dict[str, Dict[str, List[dict]]] = {}
    for group in ("Automated Templates", "Manual Templates"):
        group_dir = os.path.join(ASSETS_DIR, group)
        if not os.path.isdir(group_dir):
            continue
        for style in sorted(os.listdir(group_dir)):
            style_path = os.path.join(group_dir, style)
            if not os.path.isdir(style_path) or style in ("Automated Templates", "WIP"):
                continue
            style_key = f"{group}/{style}"
            categories = {
                "background": [],
                "pinlines": [],
                "name_box": [],
                "crown": [],
                "border": [],
                "pt_box": [],
                "overlays": [],
            }
            for root, _, files in os.walk(style_path):
                rel_folder = os.path.relpath(root, style_path).replace("\\", "/")
                if any(skip in rel_folder for skip in ("Text and Icons", "Legal")):
                    continue
                for f in sorted(files):
                    if not f.lower().endswith(".jpg"):
                        continue
                    if "Border Crop" in f or "Reference" in f:
                        continue
                    rel_asset_path = os.path.relpath(os.path.join(root, f), ASSETS_DIR).replace("\\", "/")
                    item = {
                        "label": f.replace("_[oculta].jpg", "").replace(".jpg", ""),
                        "rel_path": rel_asset_path,
                        "url": f"/assets/{urllib.parse.quote(rel_asset_path)}",
                        "folder": rel_folder,
                    }
                    rf_lower = rel_folder.lower()
                    if "background" in rf_lower or "nyx" in rf_lower or rf_lower in ("land", "nonland"):
                        categories["background"].append(item)
                    elif "pinlines" in rf_lower or "textbox" in rf_lower:
                        categories["pinlines"].append(item)
                    elif "name" in rf_lower:
                        categories["name_box"].append(item)
                    elif "crown" in rf_lower or "companion" in rf_lower:
                        categories["crown"].append(item)
                    elif "border" in rf_lower or "border" in f.lower():
                        categories["border"].append(item)
                    elif "pt box" in rf_lower or "pt and level" in rf_lower:
                        categories["pt_box"].append(item)
                    elif rf_lower == ".":
                        if "basic" in style.lower() and any(
                            land in f for land in ("Forest", "Mountain", "Swamp", "Island", "Plains", "Wastes")
                        ):
                            categories["background"].append(item)
                        else:
                            categories["overlays"].append(item)
                    else:
                        categories["overlays"].append(item)
            catalog[style_key] = categories
    return catalog


def _pick_layer(items, preferred_tokens, folder_hint=None):
    if not items:
        return ""
    candidates = items
    if folder_hint:
        hinted = [it for it in items if folder_hint.lower() in it["folder"].lower()]
        if hinted:
            candidates = hinted
    for token in preferred_tokens:
        tk = token.strip().lower()
        if not tk:
            continue
        # 1. Exact label match
        for it in candidates:
            if it["label"].lower() == tk:
                return it["rel_path"]
        # 2. Numeric prefix exact match (e.g. "04_R", "01_W")
        prefix_pat = re.compile(rf"^\d+_{re.escape(tk)}$", re.IGNORECASE)
        for it in candidates:
            if prefix_pat.match(it["label"]):
                return it["rel_path"]
        # 3. Word/token boundary match (never match "r" inside "Artifact" or "Border")
        boundary_pat = re.compile(rf"(?<![a-z0-9]){re.escape(tk)}(?![a-z0-9])", re.IGNORECASE)
        for it in candidates:
            if boundary_pat.search(it["label"]):
                return it["rel_path"]
        # 4. Substring fallback only for multi-char descriptive tokens (e.g. "Legendary Border", "Gold")
        if len(tk) > 2:
            for it in candidates:
                if tk in it["label"].lower():
                    return it["rel_path"]
    return ""


def auto_select_frame_components(card_data: dict, style_key: str = "Automated Templates/normal", catalog: Optional[dict] = None):
    if catalog is None:
        catalog = scan_template_catalog()
    style_cat = catalog.get(style_key) or catalog.get("Automated Templates/normal")
    if not style_cat:
        return {}

    colors = card_data.get("colors") or []
    color_id = card_data.get("color_identity") or []
    type_line = card_data.get("type_line") or ""
    tl_lower = type_line.lower()
    is_land = "land" in tl_lower
    is_legendary = "legendary" in tl_lower
    is_creature = bool(card_data.get("power") is not None or card_data.get("toughness") is not None or "creature" in tl_lower)

    pin_code, bg_code = get_color_code_for_templates(colors, color_id, type_line)
    bg_tokens = [bg_code] + (["Land"] if is_land else []) + ["Colourless"]
    pin_tokens = [pin_code, bg_code, "Gold", "Colourless"]

    border_pref = ["Black", "Border", "Borderless"]
    if "extended" in style_key.lower() or "full art" in style_key.lower():
        border_pref = ["Borderless", "Black", "Border"]

    return {
        "style": style_key,
        "background": _pick_layer(style_cat["background"], bg_tokens),
        "pinlines": _pick_layer(style_cat["pinlines"], pin_tokens, folder_hint=("Land" if is_land else "Nonland")),
        "name_box": _pick_layer(style_cat["name_box"], bg_tokens),
        "crown": _pick_layer(style_cat["crown"], pin_tokens) if is_legendary else "",
        "border": _pick_layer(style_cat["border"], border_pref),
        "pt_box": _pick_layer(style_cat["pt_box"], [bg_code, "Colourless"]) if is_creature else "",
    }


def extract_scryfall_card_payload(raw_card: dict, count: int = 1, catalog: Optional[dict] = None, style_key: str = "Automated Templates/normal") -> dict:
    faces = raw_card.get("card_faces") or []
    face0 = faces[0] if faces else raw_card
    image_uris = raw_card.get("image_uris") or face0.get("image_uris") or {}
    name = face0.get("name") or raw_card.get("name", "Unknown Card")

    # Priority 1: Check unified HD local JSON
    hd_matches = art_index.lookup_exact(name)
    hd_art_url = hd_matches[0]["image_url"] if hd_matches else ""
    scryfall_art_url = image_uris.get("art_crop") or image_uris.get("large") or image_uris.get("normal") or ""
    art_url = hd_art_url or scryfall_art_url
    art_source = "unified_json" if hd_art_url else "scryfall"

    payload = {
        "id": str(uuid.uuid4()),
        "name": name,
        "official_name": raw_card.get("printed_name") or "",
        "mana_cost": face0.get("mana_cost") or raw_card.get("mana_cost", ""),
        "type_line": face0.get("type_line") or raw_card.get("type_line", ""),
        "oracle_text": face0.get("oracle_text") or raw_card.get("oracle_text", ""),
        "flavor_text": face0.get("flavor_text") or raw_card.get("flavor_text", ""),
        "power": face0.get("power") if face0.get("power") is not None else raw_card.get("power"),
        "toughness": face0.get("toughness") if face0.get("toughness") is not None else raw_card.get("toughness"),
        "artist": (hd_matches[0].get("artist") if hd_matches else None) or face0.get("artist") or raw_card.get("artist", ""),
        "set": raw_card.get("set", "mtg"),
        "rarity": raw_card.get("rarity", "common"),
        "colors": face0.get("colors") if face0.get("colors") is not None else raw_card.get("colors", []),
        "color_identity": raw_card.get("color_identity", []),
        "art_crop_url": art_url,
        "scryfall_art_url": scryfall_art_url,
        "art_source": art_source,
        "full_image_url": image_uris.get("png") or image_uris.get("large") or "",
        "count": count,
        "brightness": 1.0,
        "bg_color": "#111111",
        "crop_mask": "free",
        "frame_opacity": 1.0,
        "layer_order": ["background", "art", "pinlines", "name_box", "crown", "border", "pt_box"],
        "hidden_layers": {"border": True},
        "layer_opacities": {},
        "layout": json.loads(json.dumps(DEFAULT_LAYOUT)),
    }
    fc = auto_select_frame_components(payload, style_key=style_key, catalog=catalog)
    payload["frame_components"] = fc
    payload["hidden_layers"]["border"] = True
    for k in ("crown", "pt_box"):
        if not fc.get(k):
            payload["hidden_layers"][k] = True
    return payload


def create_blank_card_from_image(name: str, data_url: str, style_key: str = "Automated Templates/normal", catalog: Optional[dict] = None) -> dict:
    payload = {
        "id": str(uuid.uuid4()),
        "name": name,
        "official_name": "",
        "mana_cost": "",
        "type_line": "Card",
        "oracle_text": "",
        "flavor_text": "",
        "power": None,
        "toughness": None,
        "artist": "",
        "set": "mtg",
        "rarity": "common",
        "colors": [],
        "color_identity": [],
        "art_crop_url": "",
        "art_source": "local_png",
        "custom_art_data": data_url,
        "count": 1,
        "brightness": 1.0,
        "bg_color": "#111111",
        "crop_mask": "free",
        "frame_opacity": 1.0,
        "layer_order": ["background", "art", "pinlines", "name_box", "crown", "border", "pt_box"],
        "hidden_layers": {"border": True},
        "layer_opacities": {},
        "layout": json.loads(json.dumps(DEFAULT_LAYOUT)),
    }
    fc = auto_select_frame_components(payload, style_key=style_key, catalog=catalog)
    payload["frame_components"] = fc
    for k in ("border", "crown", "pt_box"):
        if not fc.get(k):
            payload["hidden_layers"][k] = True
    return payload


def parse_mtgo_txt(content: str) -> List[Tuple[int, str]]:
    entries: List[Tuple[int, str]] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//") or line.lower() in ("sideboard", "commander", "companion", "deck"):
            continue
        m = re.match(r"^(\d+)[xX]?\s+(.+?)(?:\s+\([A-Za-z0-9]+\)\s*\d*.*)?$", line)
        if m:
            count = int(m.group(1))
            name = m.group(2).strip()
        else:
            count = 1
            name = line
        if name:
            entries.append((count, name))
    return entries


def remove_solid_bg_pil(pil_img: Image.Image, tolerance: int = 28, clear_art_box_black: bool = True) -> Image.Image:
    rgba = pil_img.convert("RGBA")
    arr = np.array(rgba, dtype=np.int16)
    h, w, _ = arr.shape
    if h == 0 or w == 0:
        return rgba
    corners = np.array([arr[0, 0, :3], arr[0, w - 1, :3], arr[h - 1, 0, :3], arr[h - 1, w - 1, :3]])
    bg_rgb = np.median(corners, axis=0)
    dist = np.max(np.abs(arr[:, :, :3] - bg_rgb), axis=2)
    mask = dist > tolerance
    arr[:, :, 3] = np.where(mask, 255, 0)

    if clear_art_box_black and w >= 100 and h >= 100:
        sx = w / 750.0
        sy = h / 1050.0
        pts = [(375, 340), (180, 220), (560, 220), (180, 460), (560, 460)]
        if all(
            np.max(arr[int(py * sy), int(px * sx), :3]) < 22 and arr[int(py * sy), int(px * sx), 3] > 200
            for px, py in pts
        ):
            x0, x1 = int(34 * sx), int(716 * sx)
            y0, y1 = int(109 * sy), int(586 * sy)
            sub = arr[y0:y1, x0:x1, :3]
            black_mask = np.max(sub, axis=2) < 22
            arr[y0:y1, x0:x1, 3] = np.where(black_mask, 0, arr[y0:y1, x0:x1, 3])

    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def jpg_rel_path_to_pdf_abs_path(rel_path: str) -> Optional[str]:
    if not rel_path:
        return None
    norm = os.path.normpath(rel_path).lstrip("/\\")
    if norm.startswith(".."):
        return None
    jpg_abs = os.path.join(ASSETS_DIR, norm)
    stem, _ = os.path.splitext(jpg_abs)
    pdf_abs = stem + ".pdf"
    if os.path.isfile(pdf_abs):
        return pdf_abs
    if os.path.isfile(jpg_abs):
        return jpg_abs
    return None


def render_pdf_layer_rgba(file_path: str, target_w: int, target_h: int) -> Image.Image:
    if file_path.lower().endswith(".pdf"):
        if pymupdf is not None:
            doc = pymupdf.open(file_path)
            try:
                page = doc[0]
                rect = page.rect
                ratio = rect.width / rect.height if rect.height else 0.0
                if rect.width < rect.height and 0.724 <= ratio <= 0.742:
                    bx = rect.width * (144.0 / 3288.0)
                    by = rect.height * (144.0 / 4488.0)
                    clip = pymupdf.Rect(bx, by, rect.width - bx, rect.height - by)
                else:
                    clip = rect
                mat = pymupdf.Matrix(target_w / clip.width, target_h / clip.height)
                pix = page.get_pixmap(matrix=mat, clip=clip, alpha=True)
                rgba = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
                del pix
                if rgba.size != (target_w, target_h):
                    rgba = rgba.resize((target_w, target_h), Image.LANCZOS)
            finally:
                doc.close()
        else:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(file_path)
            page = doc[0]
            scale = max(target_w / max(1.0, page.get_width()), target_h / max(1.0, page.get_height()))
            rgba = page.render(scale=scale).to_pil().convert("RGBA")
            doc.close()
            if rgba.size != (target_w, target_h):
                rgba = rgba.resize((target_w, target_h), Image.LANCZOS)
    else:
        with Image.open(file_path) as src_img:
            rgba = src_img.convert("RGBA")
            w, h = rgba.size
            ratio = w / h if h else 0.0
            if w < h and 0.724 <= ratio <= 0.742:
                bx = int(round(w * (144.0 / 3288.0)))
                by = int(round(h * (144.0 / 4488.0)))
                rgba = rgba.crop((bx, by, w - bx, h - by))
            rgba = rgba.resize((target_w, target_h), Image.LANCZOS)

    extrema = rgba.getextrema()
    if len(extrema) >= 4 and extrema[3] == (255, 255):
        return remove_solid_bg_pil(rgba)
    return rgba


def _apply_layer_opacity(rgba_img: Image.Image, opacity: float) -> Image.Image:
    if opacity >= 0.999:
        return rgba_img
    r, g, b, a = rgba_img.split()
    a = a.point(lambda p: int(p * opacity))
    return Image.merge("RGBA", (r, g, b, a))


def _apply_brightness(rgba_img: Image.Image, brightness: float) -> Image.Image:
    try:
        b = float(brightness)
    except (TypeError, ValueError):
        b = 1.0
    if abs(b - 1.0) < 0.01:
        return rgba_img
    b = max(0.2, min(2.2, b))
    rgb = rgba_img.convert("RGB")
    enh = ImageEnhance.Brightness(rgb).enhance(b)
    r, g, bl = enh.split()
    _, _, _, a = rgba_img.split()
    return Image.merge("RGBA", (r, g, bl, a))


def compose_card_export(
    card: dict,
    card_name: str,
    dest_dir: str,
    art_overlay_b64: str = "",
    text_overlay_b64: str = "",
    fallback_full_b64: str = "",
    export_dpi: int = DEFAULT_EXPORT_DPI,
    export_format: str = "pdf",
) -> Tuple[str, List[str]]:
    effective_dpi = clamp_export_dpi(export_dpi)
    export_scale = effective_dpi / float(DPI)
    export_w = int(round(STANDARD_CARD_W_PX * export_scale))
    export_h = int(round(STANDARD_CARD_H_PX * export_scale))

    os.makedirs(dest_dir, exist_ok=True)
    ext = "png" if export_format.lower() == "png" else "pdf"
    dest_path = os.path.join(dest_dir, f"{safe_card_filename(card_name)}.{ext}")

    fc = card.get("frame_components") or {}
    frame_keys = ("background", "pinlines", "name_box", "crown", "border", "pt_box")
    default_order = ["background", "art", "pinlines", "name_box", "crown", "border", "pt_box"]
    raw_order = card.get("layer_order") if isinstance(card.get("layer_order"), list) else []
    layer_order = [k for k in raw_order if k in default_order]
    for k in default_order:
        if k not in layer_order:
            layer_order.append(k)

    hidden_layers = card.get("hidden_layers") or {}

    def _is_layer_hidden(key):
        if isinstance(hidden_layers, list):
            return key in hidden_layers
        if isinstance(hidden_layers, dict):
            return bool(hidden_layers.get(key))
        return False

    has_any_fc = any(bool(fc.get(k)) for k in frame_keys)
    default_opacity = max(0.0, min(1.0, float(card.get("frame_opacity", 1.0))))
    layer_opacities = card.get("layer_opacities") or {}

    def _layer_op(key):
        if _is_layer_hidden(key):
            return 0.0
        try:
            return max(0.0, min(1.0, float(layer_opacities.get(key, default_opacity))))
        except (TypeError, ValueError):
            return default_opacity

    bg_rgb = parse_hex(card.get("bg_color", "#111111"), fallback=(17, 17, 17))
    canvas_img = Image.new("RGBA", (export_w, export_h), (*bg_rgb, 255))
    used_pdf_components: List[str] = []
    brightness = card.get("brightness", 1.0)

    def _composite_art():
        art_op = _layer_op("art")
        if art_op <= 0.001:
            return
        if art_overlay_b64:
            _, b64_art = art_overlay_b64.split(",", 1) if "," in art_overlay_b64 else ("", art_overlay_b64)
            with Image.open(io.BytesIO(base64.b64decode(b64_art))) as raw_art:
                art_layer = raw_art.convert("RGBA")
            if art_layer.size != (export_w, export_h):
                art_layer = art_layer.resize((export_w, export_h), Image.LANCZOS)
            art_layer = _apply_brightness(art_layer, brightness)
            canvas_img.alpha_composite(_apply_layer_opacity(art_layer, art_op))
            del art_layer
        else:
            art_layout = (card.get("layout") or {}).get("art") or DEFAULT_LAYOUT["art"]
            art_img = None
            if card.get("custom_art_data"):
                _, b64_raw = card["custom_art_data"].split(",", 1) if "," in card["custom_art_data"] else ("", card["custom_art_data"])
                with Image.open(io.BytesIO(base64.b64decode(b64_raw))) as raw_custom:
                    art_img = raw_custom.convert("RGBA")
            elif card.get("art_crop_url"):
                try:
                    resp = httpx.get(
                        card["art_crop_url"],
                        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0.0.0", "Accept": "image/*", "Referer": card["art_crop_url"]},
                        timeout=20.0,
                        follow_redirects=True,
                    )
                    if resp.status_code == 200:
                        with Image.open(io.BytesIO(resp.content)) as raw_fetched:
                            art_img = raw_fetched.convert("RGBA")
                except Exception:
                    pass

            if art_img:
                art_img = _apply_brightness(art_img, brightness)
                aw = max(1, int(round(float(art_layout["w"]) * export_scale)))
                ah = max(1, int(round(float(art_layout["h"]) * export_scale)))
                ax = int(round(float(art_layout["x"]) * export_scale))
                ay = int(round(float(art_layout["y"]) * export_scale))
                scale = float(art_layout.get("scale", 1.0))
                ox = int(round(float(art_layout.get("offset_x", 0)) * export_scale))
                oy = int(round(float(art_layout.get("offset_y", 0)) * export_scale))
                base_scale = max(aw / art_img.width, ah / art_img.height) * scale
                dw, dh = max(1, int(art_img.width * base_scale)), max(1, int(art_img.height * base_scale))
                resized_art = art_img.resize((dw, dh), Image.LANCZOS)
                del art_img
                art_box_canvas = Image.new("RGBA", (export_w, export_h), (0, 0, 0, 0))
                pop_out = bool(card.get("art_over_top")) or (
                    "art" in layer_order and "name_box" in layer_order
                    and layer_order.index("art") > layer_order.index("name_box")
                )
                if pop_out:
                    art_box_canvas.paste(resized_art, (ax + (aw - dw) // 2 + ox, ay + (ah - dh) // 2 + oy))
                    del resized_art
                    max_h = max(int(round(587 * export_scale)), ay + ah)
                    if max_h < export_h:
                        art_box_canvas.paste((0, 0, 0, 0), (0, max_h, export_w, export_h))
                else:
                    crop_box = Image.new("RGBA", (aw, ah), (0, 0, 0, 0))
                    crop_box.paste(resized_art, ((aw - dw) // 2 + ox, (ah - dh) // 2 + oy))
                    del resized_art
                    art_box_canvas.paste(crop_box, (ax, ay))
                    del crop_box
                canvas_img.alpha_composite(_apply_layer_opacity(art_box_canvas, art_op))
                del art_box_canvas

    def _composite_comp(comp_key):
        comp_op = _layer_op(comp_key)
        if comp_op <= 0.001:
            return
        rel_p = fc.get(comp_key)
        if not rel_p:
            return
        pdf_p = jpg_rel_path_to_pdf_abs_path(rel_p)
        if not pdf_p:
            return
        rel_used = os.path.relpath(pdf_p, ASSETS_DIR)
        if rel_used not in used_pdf_components:
            used_pdf_components.append(rel_used)
        comp_rgba = render_pdf_layer_rgba(pdf_p, export_w, export_h)
        canvas_img.alpha_composite(_apply_layer_opacity(comp_rgba, comp_op))
        del comp_rgba

    if card.get("art_over_top"):
        split_y = int(round(587 * export_scale))
        for comp_key in layer_order:
            if comp_key in ("art", "pt_box"):
                continue
            _composite_comp(comp_key)
        _composite_art()
        for comp_key in layer_order:
            if comp_key in ("pinlines", "border"):
                comp_op = _layer_op(comp_key)
                rel_p = fc.get(comp_key)
                if rel_p and comp_op > 0.001:
                    pdf_p = jpg_rel_path_to_pdf_abs_path(rel_p)
                    if pdf_p:
                        comp_img = render_pdf_layer_rgba(pdf_p, export_w, export_h)
                        bottom_crop = comp_img.crop((0, split_y, export_w, export_h))
                        canvas_img.alpha_composite(_apply_layer_opacity(bottom_crop, comp_op), dest=(0, split_y))
                        del comp_img, bottom_crop
            elif comp_key == "pt_box":
                _composite_comp(comp_key)
    else:
        for comp_key in layer_order:
            if comp_key == "art":
                _composite_art()
            else:
                _composite_comp(comp_key)

    if text_overlay_b64:
        _, b64_txt = text_overlay_b64.split(",", 1) if "," in text_overlay_b64 else ("", text_overlay_b64)
        with Image.open(io.BytesIO(base64.b64decode(b64_txt))) as raw_txt:
            txt_img = raw_txt.convert("RGBA")
        if txt_img.size != (export_w, export_h):
            txt_img = txt_img.resize((export_w, export_h), Image.LANCZOS)
        canvas_img.alpha_composite(txt_img)
        del txt_img
        final_rgb = canvas_img.convert("RGB")
    elif fallback_full_b64:
        _, b64_full = fallback_full_b64.split(",", 1) if "," in fallback_full_b64 else ("", fallback_full_b64)
        with Image.open(io.BytesIO(base64.b64decode(b64_full))) as raw_full:
            full_img = raw_full.convert("RGB")
        final_rgb = ImageOps.fit(full_img, (export_w, export_h), method=Image.LANCZOS)
        del full_img
    else:
        final_rgb = canvas_img.convert("RGB")

    del canvas_img
    gc.collect()

    if ext == "png":
        final_rgb.save(dest_path, format="PNG", dpi=(effective_dpi, effective_dpi))
    else:
        final_rgb.save(dest_path, format="PDF", resolution=float(effective_dpi))
    del final_rgb
    gc.collect()
    return dest_path, used_pdf_components
