import asyncio
import base64
import io
import json
import logging
import os
import re
import tempfile
import urllib.parse
from string import Template

import numpy as np
import pymupdf
import tornado.httpclient
import tornado.web
from PIL import Image, ImageOps

from config import ASSETS_DIR, DPI, STANDARD_CARD_H_PX, STANDARD_CARD_W_PX

DEFAULT_LAYOUT = {
    "canvas": {"w": 750, "h": 1050},
    "art": {"x": 64, "y": 136, "w": 622, "h": 446, "scale": 1.0, "offset_x": 0, "offset_y": 0},
    "title": {"x": 84, "y": 116, "max_w": 450, "font_size": 28, "color": "#111111"},
    "mana_cost": {"x": 664, "y": 116, "size": 25, "align": "right"},
    "type_line": {"x": 84, "y": 622, "max_w": 500, "font_size": 23, "color": "#111111"},
    "set_symbol": {"x": 664, "y": 614, "size": 32, "align": "right"},
    "oracle_box": {"x": 88, "y": 658, "w": 574, "h": 272, "font_size": 21, "color": "#111111"},
    "pt_box": {"x": 562, "y": 908, "w": 123, "h": 66},
    "pt_text": {"x": 624, "y": 941, "font_size": 29, "color": "#111111"},
    "artist": {"x": 76, "y": 990, "font_size": 14, "color": "#ffffff"},
}

GUILD_PAIRS = ["WU", "UB", "BR", "RG", "GW", "WB", "BG", "GU", "UR", "RW"]


def safe_card_filename(name):
    clean = re.sub(r"[^\w\s\-]", "", name).strip()
    return re.sub(r"[\s]+", "_", clean).lower()


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


def scan_template_catalog():
    """Escanea Automated Templates y Manual Templates devolviendo solo archivos .jpg agrupados por estilo y categoría."""
    catalog = {}
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
                # Ignorar carpetas de referencias de texto para no saturar memoria ni selectores
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
                        # En estilos como basic/ los fondos están en la raíz del estilo
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
        filtered = [it for it in items if folder_hint.lower() in it["folder"].lower()]
        if filtered:
            candidates = filtered
    for token in preferred_tokens:
        pattern = re.compile(rf"^\d+_{re.escape(token)}(_\[oculta\])?$", re.IGNORECASE)
        for it in candidates:
            if pattern.match(it["label"]):
                return it["rel_path"]
        for it in candidates:
            if token.lower() in it["label"].lower():
                return it["rel_path"]
    return candidates[0]["rel_path"]


def auto_select_frame_components(card_data, style_key="Automated Templates/normal", catalog=None):
    if catalog is None:
        catalog = scan_template_catalog()
    style_cats = catalog.get(style_key) or next(iter(catalog.values()), {})
    type_line = card_data.get("type_line", "")
    tl_lower = type_line.lower()
    is_legendary = "legendary" in tl_lower
    is_land = "land" in tl_lower
    has_pt = card_data.get("power") is not None and str(card_data.get("power")).strip() != ""

    pair_or_color, broad_color = get_color_code_for_templates(
        card_data.get("colors") or [],
        card_data.get("color_identity") or [],
        type_line,
    )

    # Si es tierra básica y estamos en estilo basic, buscar por nombre de tierra
    card_name = card_data.get("name", "")
    search_tokens = [pair_or_color, broad_color, "Gold", "Artifact", "Land", "W"]
    if "basic" in style_key.lower():
        search_tokens = [card_name] + search_tokens

    bg = _pick_layer(
        style_cats.get("background", []),
        ["Land"] + search_tokens if is_land else search_tokens,
    )
    pinlines = _pick_layer(
        style_cats.get("pinlines", []),
        search_tokens,
        folder_hint="Land Pinlines" if is_land else "Pinlines & Textbox",
    )
    name_box = _pick_layer(
        style_cats.get("name_box", []),
        ["Land"] + search_tokens if is_land else [broad_color, pair_or_color, "Gold"],
    )
    crown = (
        _pick_layer(style_cats.get("crown", []), [pair_or_color, broad_color, "Gold"])
        if is_legendary
        else ""
    )
    border = _pick_layer(
        style_cats.get("border", []),
        ["Legendary Border"] if is_legendary else ["Normal Border"],
    )
    pt_box = (
        _pick_layer(style_cats.get("pt_box", []), [broad_color, pair_or_color, "Gold", "Artifact"])
        if has_pt
        else ""
    )

    return {
        "style": style_key,
        "background": bg,
        "pinlines": pinlines,
        "name_box": name_box,
        "crown": crown,
        "border": border,
        "pt_box": pt_box,
    }


def extract_scryfall_card_payload(raw_card, count=1, catalog=None):
    faces = raw_card.get("card_faces")
    primary = faces[0] if faces else raw_card
    image_uris = primary.get("image_uris") or raw_card.get("image_uris") or {}
    type_line = primary.get("type_line") or raw_card.get("type_line", "")

    default_style = "Automated Templates/basic" if "Basic Land" in type_line else "Automated Templates/normal"

    base_info = {
        "id": raw_card.get("id"),
        "name": primary.get("name") or raw_card.get("name", ""),
        "full_name": raw_card.get("name", ""),
        "count": count,
        "mana_cost": primary.get("mana_cost") or raw_card.get("mana_cost", ""),
        "type_line": type_line,
        "oracle_text": primary.get("oracle_text") or raw_card.get("oracle_text", ""),
        "flavor_text": primary.get("flavor_text") or raw_card.get("flavor_text", ""),
        "power": primary.get("power") if "power" in primary else raw_card.get("power"),
        "toughness": primary.get("toughness") if "toughness" in primary else raw_card.get("toughness"),
        "loyalty": primary.get("loyalty") if "loyalty" in primary else raw_card.get("loyalty"),
        "colors": primary.get("colors") or raw_card.get("colors") or [],
        "color_identity": raw_card.get("color_identity") or [],
        "set": raw_card.get("set", "mtg").lower(),
        "set_name": raw_card.get("set_name", ""),
        "rarity": raw_card.get("rarity", "common").lower(),
        "artist": primary.get("artist") or raw_card.get("artist", ""),
        "art_crop_url": image_uris.get("art_crop", ""),
        "normal_image_url": image_uris.get("normal", ""),
        "custom_art_data": None,
        "layout": json.loads(json.dumps(DEFAULT_LAYOUT)),
    }
    base_info["frame_components"] = auto_select_frame_components(base_info, default_style, catalog=catalog)
    return base_info


async def fetch_card_from_scryfall(query, exact=False):
    client = tornado.httpclient.AsyncHTTPClient()
    headers = {"User-Agent": "DeckGenCardBuilder/1.0", "Accept": "application/json"}
    mode = "exact" if exact else "fuzzy"
    url = f"https://api.scryfall.com/cards/named?{mode}={urllib.parse.quote(query)}"
    try:
        resp = await client.fetch(
            url, headers=headers, raise_error=False, request_timeout=30, connect_timeout=10
        )
        if resp.code == 200:
            return json.loads(resp.body.decode("utf-8"))
        search_url = f"https://api.scryfall.com/cards/search?q={urllib.parse.quote(query)}"
        resp_s = await client.fetch(
            search_url, headers=headers, raise_error=False, request_timeout=30, connect_timeout=10
        )
        if resp_s.code == 200:
            data = json.loads(resp_s.body.decode("utf-8"))
            if data.get("data"):
                return data["data"][0]
    except Exception:
        return None
    return None


def get_json_dir(target_dir):
    if not target_dir:
        return None
    norm = os.path.normpath(target_dir)
    return norm if os.path.basename(norm) == "json" else os.path.join(norm, "json")


def save_card_json_to_dir(card_payload, target_dir):
    json_dir = get_json_dir(target_dir)
    if not json_dir:
        return None
    os.makedirs(json_dir, exist_ok=True)
    fname = f"{safe_card_filename(card_payload['name'])}.json"
    out_path = os.path.join(json_dir, fname)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(card_payload, f, indent=2, ensure_ascii=False)
    return out_path


def parse_mtgo_txt(content):
    entries = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//") or line.lower().startswith("sideboard"):
            continue
        match = re.match(r"^(\d+)x?\s+(.+)$", line)
        if match:
            count = int(match.group(1))
            name = re.sub(r"\s*\([A-Za-z0-9]+\)\s*\d*$", "", match.group(2).strip()).strip()
            entries.append((count, name))
        else:
            entries.append((1, line))
    return entries


def remove_solid_bg_pil(pil_img, tolerance=28):
    """Elimina el fondo sólido (blanco o negro de las esquinas) de una capa renderizada desde PDF para superponerla."""
    rgba = pil_img.convert("RGBA")
    arr = np.array(rgba, dtype=np.int16)
    corners = [arr[0, 0, :3], arr[0, -1, :3], arr[-1, 0, :3], arr[-1, -1, :3]]
    bg = np.median(corners, axis=0)
    # Solo eliminar si el color de las esquinas es casi blanco (>235) o casi negro (<20)
    if not (np.all(bg > 235) or np.all(bg < 20)):
        return rgba
    diff = np.max(np.abs(arr[:, :, :3] - bg), axis=2)
    alpha = np.where(diff < tolerance, 0, np.clip((diff - tolerance) * 8, 0, 255)).astype(np.uint8)
    arr[:, :, 3] = np.minimum(arr[:, :, 3].astype(np.uint8), alpha)
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def jpg_rel_path_to_pdf_abs_path(rel_path):
    """Convierte la ruta relativa de un componente .jpg en su archivo hermano .pdf dentro de assets/."""
    if not rel_path:
        return None
    clean_rel = urllib.parse.unquote(rel_path).lstrip("/")
    if clean_rel.startswith("assets/"):
        clean_rel = clean_rel[len("assets/"):]
    base_no_ext, _ = os.path.splitext(clean_rel)
    pdf_abs = os.path.join(ASSETS_DIR, base_no_ext + ".pdf")
    if os.path.isfile(pdf_abs):
        return pdf_abs
    jpg_abs = os.path.join(ASSETS_DIR, clean_rel)
    return jpg_abs if os.path.isfile(jpg_abs) else None


class CardBuilderHandler(tornado.web.RequestHandler):
    def get(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        nav_path = os.path.join(base_dir, "templates", "components", "navbar.html")
        tpl_path = os.path.join(base_dir, "templates", "card_builder.html")
        with open(nav_path, "r", encoding="utf-8") as f:
            navbar = f.read()
        with open(tpl_path, "r", encoding="utf-8") as f:
            tpl = Template(f.read())
        self.write(tpl.safe_substitute(navbar=navbar))


class CardBuilderTemplatesHandler(tornado.web.RequestHandler):
    def get(self):
        catalog = scan_template_catalog()
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"catalog": catalog}))


class CardBuilderSearchHandler(tornado.web.RequestHandler):
    async def post(self):
        self.set_header("Content-Type", "application/json")
        query = self.get_body_argument("query", "").strip()
        target_dir = self.get_body_argument("target_dir", "").strip()
        if not query:
            self.set_status(400)
            self.write(json.dumps({"error": "Debe ingresar el nombre de una carta."}))
            return

        catalog = scan_template_catalog()
        if target_dir:
            json_dir = get_json_dir(target_dir)
            potential_json = os.path.join(json_dir, f"{safe_card_filename(query)}.json")
            if not os.path.isfile(potential_json):
                legacy_json = os.path.join(target_dir, f"{safe_card_filename(query)}.json")
                if os.path.isfile(legacy_json):
                    potential_json = legacy_json
            if os.path.isfile(potential_json):
                with open(potential_json, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if "frame_components" not in cached:
                    cached["frame_components"] = auto_select_frame_components(cached, catalog=catalog)
                self.write(json.dumps({"card": cached, "saved_path": potential_json, "cached": True}))
                return

        raw_card = await fetch_card_from_scryfall(query, exact=False)
        if not raw_card:
            self.set_status(404)
            self.write(json.dumps({"error": f"No se encontró la carta '{query}' en Scryfall."}))
            return

        card_payload = extract_scryfall_card_payload(raw_card, count=1, catalog=catalog)
        saved_path = save_card_json_to_dir(card_payload, target_dir) if target_dir else None
        self.write(json.dumps({"card": card_payload, "saved_path": saved_path, "cached": False}))


class CardBuilderUploadTxtHandler(tornado.web.RequestHandler):
    def on_connection_close(self):
        self._aborted = True

    async def post(self):
        self._aborted = False
        self.set_header("Content-Type", "application/json")
        target_dir = self.get_body_argument("target_dir", "").strip()
        txt_files = self.request.files.get("txt_file")

        content = ""
        if txt_files:
            file_info = txt_files[0]
            content = file_info["body"].decode("utf-8", errors="replace")
            if not target_dir:
                base_name = os.path.splitext(os.path.basename(file_info["filename"]))[0]
                target_dir = os.path.abspath(os.path.join(".", "decks_json", base_name))
            else:
                os.makedirs(target_dir, exist_ok=True)
                txt_dest = os.path.join(target_dir, os.path.basename(file_info["filename"]))
                if not os.path.isfile(txt_dest):
                    with open(txt_dest, "wb") as f:
                        f.write(file_info["body"])
        elif target_dir and os.path.isfile(target_dir) and target_dir.endswith(".txt"):
            with open(target_dir, "r", encoding="utf-8") as f:
                content = f.read()
            target_dir = os.path.dirname(os.path.abspath(target_dir))
        elif target_dir and os.path.isdir(target_dir):
            txt_cands = sorted(
                f for f in os.listdir(target_dir)
                if f.lower().endswith(".txt") and os.path.isfile(os.path.join(target_dir, f))
            )
            if txt_cands:
                with open(os.path.join(target_dir, txt_cands[0]), "r", encoding="utf-8") as f:
                    content = f.read()
            else:
                self.set_status(400)
                self.write(json.dumps({"error": "Sube un archivo .txt MTGO o coloca uno dentro de la carpeta."}))
                return
        else:
            self.set_status(400)
            self.write(json.dumps({"error": "Sube un archivo .txt MTGO o indica su ruta."}))
            return

        entries = parse_mtgo_txt(content)
        if not entries:
            self.set_status(400)
            self.write(json.dumps({"error": "El archivo .txt no contiene cartas válidas."}))
            return

        os.makedirs(target_dir, exist_ok=True)
        json_dir = get_json_dir(target_dir)
        os.makedirs(json_dir, exist_ok=True)
        catalog = scan_template_catalog()
        loaded_cards = []
        errors = []

        for count, card_name in entries:
            if self._aborted:
                return
            fname = f"{safe_card_filename(card_name)}.json"
            json_path = os.path.join(json_dir, fname)
            if not os.path.isfile(json_path):
                legacy_path = os.path.join(target_dir, fname)
                if os.path.isfile(legacy_path):
                    json_path = legacy_path
            if os.path.isfile(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        card_payload = json.load(f)
                    card_payload["count"] = count
                    if "frame_components" not in card_payload:
                        card_payload["frame_components"] = auto_select_frame_components(card_payload, catalog=catalog)
                    if json_path != os.path.join(json_dir, fname):
                        save_card_json_to_dir(card_payload, target_dir)
                    loaded_cards.append(card_payload)
                    continue
                except Exception:
                    pass

            if self._aborted:
                return
            raw_card = await fetch_card_from_scryfall(card_name, exact=True)
            if not raw_card and not self._aborted:
                raw_card = await fetch_card_from_scryfall(card_name, exact=False)
            if self._aborted:
                return

            if raw_card:
                card_payload = extract_scryfall_card_payload(raw_card, count=count, catalog=catalog)
                save_card_json_to_dir(card_payload, target_dir)
                loaded_cards.append(card_payload)
            else:
                errors.append(card_name)

            await asyncio.sleep(0.1)

        if self._aborted:
            return

        self.write(json.dumps({
            "target_dir": target_dir,
            "cards": loaded_cards,
            "errors": errors,
            "total_unique": len(loaded_cards),
        }))


class CardBuilderSaveCardHandler(tornado.web.RequestHandler):
    def post(self):
        self.set_header("Content-Type", "application/json")
        try:
            body = json.loads(self.request.body.decode("utf-8"))
            card = body.get("card")
            target_dir = body.get("target_dir", "").strip()
            if not card or not card.get("name"):
                self.set_status(400)
                self.write(json.dumps({"error": "Datos de carta inválidos."}))
                return
            if not target_dir:
                target_dir = os.path.abspath(os.path.join(".", "decks_json", "custom"))
            saved_path = save_card_json_to_dir(card, target_dir)
            self.write(json.dumps({"status": "ok", "saved_path": saved_path}))
        except Exception as e:
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))


def render_pdf_layer_rgba(file_path, target_w, target_h):
    """Renderiza una capa PDF o imagen preservando su canal alfa nativo; solo limpia fondo sólido si es opaca."""
    if file_path.lower().endswith(".pdf"):
        doc = pymupdf.open(file_path)
        try:
            page = doc[0]
            rect = page.rect
            mat = pymupdf.Matrix(target_w / rect.width, target_h / rect.height)
            pix = page.get_pixmap(matrix=mat, alpha=True)
            rgba = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
            if rgba.size != (target_w, target_h):
                rgba = rgba.resize((target_w, target_h), Image.LANCZOS)
        finally:
            doc.close()
    else:
        rgba = Image.open(file_path).convert("RGBA").resize((target_w, target_h), Image.LANCZOS)

    arr = np.array(rgba)
    if np.all(arr[:, :, 3] == 255):
        return remove_solid_bg_pil(rgba)
    return rgba


def compose_card_pdf(card, card_name, target_dir, art_overlay_b64, text_overlay_b64, fallback_full_b64):
    fronts_dir = os.path.join(target_dir, "fronts")
    os.makedirs(fronts_dir, exist_ok=True)
    dest_path = os.path.join(fronts_dir, f"{safe_card_filename(card_name)}.pdf")

    fc = card.get("frame_components") or {}
    layer_order = ["background", "pinlines", "name_box", "crown", "border", "pt_box"]
    active_rel_paths = [fc.get(k) for k in layer_order if fc.get(k)]

    used_pdf_components = []
    canvas_img = Image.new("RGBA", (STANDARD_CARD_W_PX, STANDARD_CARD_H_PX), (17, 17, 17, 255))

    # 1. Renderizar Background desde su versión .pdf preservando transparencia
    bg_rel = fc.get("background")
    if bg_rel:
        bg_pdf_path = jpg_rel_path_to_pdf_abs_path(bg_rel)
        if bg_pdf_path:
            used_pdf_components.append(os.path.relpath(bg_pdf_path, ASSETS_DIR))
            bg_img = render_pdf_layer_rgba(bg_pdf_path, STANDARD_CARD_W_PX, STANDARD_CARD_H_PX)
            canvas_img.alpha_composite(bg_img)

    # 2. Superponer la capa de Arte ya recortada y encuadrada desde el cliente
    if art_overlay_b64:
        _, b64_art = art_overlay_b64.split(",", 1) if "," in art_overlay_b64 else ("", art_overlay_b64)
        art_layer = Image.open(io.BytesIO(base64.b64decode(b64_art))).convert("RGBA")
        if art_layer.size != (STANDARD_CARD_W_PX, STANDARD_CARD_H_PX):
            art_layer = art_layer.resize((STANDARD_CARD_W_PX, STANDARD_CARD_H_PX), Image.LANCZOS)
        canvas_img.alpha_composite(art_layer)
    else:
        # Respaldo descargando desde Scryfall con User-Agent
        art_layout = (card.get("layout") or {}).get("art") or DEFAULT_LAYOUT["art"]
        art_img = None
        if card.get("custom_art_data"):
            _, b64_raw = card["custom_art_data"].split(",", 1)
            art_img = Image.open(io.BytesIO(base64.b64decode(b64_raw))).convert("RGBA")
        elif card.get("art_crop_url"):
            resp = tornado.httpclient.HTTPClient().fetch(
                card["art_crop_url"],
                headers={"User-Agent": "DeckGenCardBuilder/1.0", "Accept": "image/*"},
                raise_error=False,
                request_timeout=30,
                connect_timeout=10,
            )
            if resp.code == 200:
                art_img = Image.open(io.BytesIO(resp.body)).convert("RGBA")

        if art_img:
            aw, ah = int(art_layout["w"]), int(art_layout["h"])
            ax, ay = int(art_layout["x"]), int(art_layout["y"])
            scale = float(art_layout.get("scale", 1.0))
            ox = int(art_layout.get("offset_x", 0))
            oy = int(art_layout.get("offset_y", 0))
            base_scale = max(aw / art_img.width, ah / art_img.height) * scale
            dw, dh = max(1, int(art_img.width * base_scale)), max(1, int(art_img.height * base_scale))
            resized_art = art_img.resize((dw, dh), Image.LANCZOS)
            art_box_canvas = Image.new("RGBA", (aw, ah), (0, 0, 0, 0))
            art_box_canvas.paste(resized_art, ((aw - dw) // 2 + ox, (ah - dh) // 2 + oy))
            canvas_img.paste(art_box_canvas, (ax, ay), art_box_canvas)

    # 3. Renderizar el resto de componentes del frame usando su archivo .pdf hermano
    for comp_key in ("pinlines", "name_box", "crown", "border", "pt_box"):
        rel_p = fc.get(comp_key)
        if not rel_p:
            continue
        pdf_p = jpg_rel_path_to_pdf_abs_path(rel_p)
        if not pdf_p:
            continue
        used_pdf_components.append(os.path.relpath(pdf_p, ASSETS_DIR))
        comp_rgba = render_pdf_layer_rgba(pdf_p, STANDARD_CARD_W_PX, STANDARD_CARD_H_PX)
        canvas_img.alpha_composite(comp_rgba)

    # 4. Superponer la capa transparente de textos e iconos
    if text_overlay_b64 and active_rel_paths:
        _, b64_txt = text_overlay_b64.split(",", 1) if "," in text_overlay_b64 else ("", text_overlay_b64)
        txt_img = Image.open(io.BytesIO(base64.b64decode(b64_txt))).convert("RGBA")
        if txt_img.size != (STANDARD_CARD_W_PX, STANDARD_CARD_H_PX):
            txt_img = txt_img.resize((STANDARD_CARD_W_PX, STANDARD_CARD_H_PX), Image.LANCZOS)
        canvas_img.alpha_composite(txt_img)
        final_rgb = canvas_img.convert("RGB")
    elif fallback_full_b64:
        _, b64_full = fallback_full_b64.split(",", 1) if "," in fallback_full_b64 else ("", fallback_full_b64)
        full_img = Image.open(io.BytesIO(base64.b64decode(b64_full))).convert("RGB")
        final_rgb = ImageOps.fit(full_img, (STANDARD_CARD_W_PX, STANDARD_CARD_H_PX), method=Image.LANCZOS)
    else:
        final_rgb = canvas_img.convert("RGB")

    final_rgb.save(dest_path, format="PDF", resolution=DPI)

    return dest_path, used_pdf_components


class CardBuilderExportPdfHandler(tornado.web.RequestHandler):
    async def post(self):
        self.set_header("Content-Type", "application/json")
        try:
            body = json.loads(self.request.body.decode("utf-8"))
            card = body.get("card") or {}
            card_name = body.get("card_name") or card.get("name", "card")
            target_dir = body.get("target_dir", "").strip() or os.path.abspath("./exports")
            art_overlay_b64 = body.get("art_overlay_data_url", "")
            text_overlay_b64 = body.get("text_overlay_data_url", "")
            fallback_full_b64 = body.get("image_data_url", "")

            loop = asyncio.get_running_loop()
            dest_path, used_pdf_components = await loop.run_in_executor(
                None,
                lambda: compose_card_pdf(
                    card, card_name, target_dir, art_overlay_b64, text_overlay_b64, fallback_full_b64
                ),
            )

            self.write(json.dumps({
                "status": "ok",
                "pdf_path": dest_path,
                "pdf_components_used": used_pdf_components,
            }))
        except Exception as e:
            logging.exception("PDF export failed")
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))
