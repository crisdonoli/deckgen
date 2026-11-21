"""Draw a resolved frame recipe (core.frame_resolver.build_recipe) onto a PNG canvas."""
import io
import os
import re
import sqlite3
import sys
from pathlib import Path

import httpx
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

try:
    from .card_layouts import DEFAULT_LAYOUT, get_template_layout
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from core.card_layouts import DEFAULT_LAYOUT, get_template_layout

ROOT = Path(__file__).resolve().parents[2]
FRAMES_DIR = ROOT / "assets" / "resources" / "frames"
SHARED_DIR = ROOT / "assets" / "resources" / "_shared"
DB_PATH = ROOT / "assets" / "resources" / "assets.db"
DEFAULT_CANVAS = (1500, 2100)

TEXT_COLOR = "#f2f2f2"
COLLECTOR_COLOR = "#222222"
MANA_FONT_SIZE_RATIO = 1.0
FONT_PREFS = {
    "title": ("beleren-b", "beleren-bsc", "beleren"),
    "type": ("matrix-b", "matrix", "beleren-b"),
    "body": ("mplantin", "mplantin-i", "matrix"),
    "pt": ("beleren-b", "matrix-b", "matrix"),
}
_MANA_TOKEN = re.compile(r"\{([^{}]+)\}")
_ART_CACHE = {}
_FONT_CACHE = {}
_CODE_INDEX = {}


def _db_index(category: str) -> dict:
    if category not in _CODE_INDEX:
        conn = sqlite3.connect(str(DB_PATH))
        try:
            rows = conn.execute(
                "SELECT symbol_code, file FROM shared_resources WHERE category = ?", (category,)
            ).fetchall()
        finally:
            conn.close()
        _CODE_INDEX[category] = {str(code).lower(): str(name) for code, name in rows}
    return _CODE_INDEX[category]


def _open_rgba(path) -> Image.Image:
    with Image.open(path) as img:
        return img.convert("RGBA")


def _hex_rgba(value: str, alpha: int = 255) -> tuple:
    code = value.strip().lstrip("#")
    return (int(code[0:2], 16), int(code[2:4], 16), int(code[4:6], 16), alpha)


def _fetch_remote(url: str):
    cached = _ART_CACHE.get(url)
    if cached is not None:
        return cached.copy()
    try:
        response = httpx.get(url, timeout=15.0, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    img = Image.open(io.BytesIO(response.content)).convert("RGBA")
    _ART_CACHE[url] = img
    return img.copy()


def load_art(source, warnings: list):
    if source is None:
        return None
    if isinstance(source, (bytes, bytearray)):
        return Image.open(io.BytesIO(bytes(source))).convert("RGBA")
    ref = os.fspath(source) if isinstance(source, os.PathLike) else str(source)
    if ref.startswith(("http://", "https://")):
        return _fetch_remote(ref)
    path = Path(ref)
    return _open_rgba(path) if path.is_file() else None


def _transform_art(img: Image.Image, transform: dict) -> Image.Image:
    scale = float(transform.get("scale") or 1.0)
    if scale != 1.0:
        size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
        img = img.resize(size, Image.LANCZOS)
    angle = float(transform.get("rotation") or 0.0)
    if angle:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=False)
    return img


def draw_art(canvas: Image.Image, art_layer: dict, override, warnings: list) -> int:
    art_layer = art_layer or {}
    source = override if override is not None else art_layer.get("source")
    if source is None:
        return 0
    img = load_art(source, warnings)
    if img is None:
        warnings.append("art_unavailable")
        return 0
    transform = art_layer.get("transform") or {}
    bounds = art_layer.get("bounds") or {}
    width = int(bounds.get("w") or canvas.width)
    height = int(bounds.get("h") or canvas.height)
    x = int(transform.get("x", bounds.get("x") or 0))
    y = int(transform.get("y", bounds.get("y") or 0))
    img = ImageOps.fit(_transform_art(img, transform), (width, height), method=Image.LANCZOS, centering=(0.5, 0.5))
    canvas.alpha_composite(img, (x, y))
    return 1


def _find_asset(filename: str):
    if not filename:
        return None
    for base in (FRAMES_DIR, SHARED_DIR):
        candidate = base / filename
        if candidate.is_file():
            return candidate
    return None


def _composite_multiply(base: Image.Image, top: Image.Image) -> None:
    blended = ImageChops.multiply(base.convert("RGB"), top.convert("RGB")).convert("RGBA")
    blended.putalpha(top.getchannel("A"))
    base.alpha_composite(blended)


def _destination_in(img: Image.Image, mask_name: str, warnings: list) -> Image.Image:
    mask_path = _find_asset(mask_name)
    if mask_path is None:
        warnings.append("mask_missing:%s" % mask_name)
        return img
    mask = _open_rgba(mask_path)
    if mask.size != img.size:
        mask = ImageOps.fit(mask, img.size, method=Image.NEAREST)
    img.putalpha(ImageChops.multiply(img.getchannel("A"), mask.getchannel("A")))
    return img


def _draw_procedural(canvas: Image.Image, layer: dict, warnings: list) -> None:
    operation = str(layer.get("operation") or "")
    if operation.startswith("canvas_fill_hex:"):
        canvas.alpha_composite(Image.new("RGBA", canvas.size, _hex_rgba(operation.split(":", 1)[1])))
    elif operation == "no_corner_clip":
        return
    else:
        warnings.append("procedural_unsupported:%s" % operation)


def draw_layers(canvas: Image.Image, layers: list, warnings: list) -> int:
    drawn = 0
    masks_skipped = 0
    for layer in sorted(layers or [], key=lambda item: item.get("z_index") or 0):
        if layer.get("type") == "procedural":
            _draw_procedural(canvas, layer, warnings)
            drawn += 1
            continue
        if layer.get("asset_role") == "mask":
            masks_skipped += 1
            continue
        path = _find_asset(layer.get("filename") or "")
        if path is None:
            warnings.append("layer_missing:%s" % layer.get("filename"))
            continue
        img = _open_rgba(path)
        if img.size != canvas.size:
            img = ImageOps.fit(img, canvas.size, method=Image.LANCZOS)
        mask_name = layer.get("mask_id") or layer.get("mask")
        if mask_name:
            img = _destination_in(img, mask_name, warnings)
        if layer.get("blend") == "multiply":
            _composite_multiply(canvas, img)
        else:
            canvas.alpha_composite(img)
        drawn += 1
    if masks_skipped:
        warnings.append("mask_layers_skipped")
    return drawn


def draw_set_symbol(canvas: Image.Image, recipe: dict, layout: dict, warnings: list) -> int:
    symbol = recipe.get("set_symbol") or {}
    local = symbol.get("path") or symbol.get("url") or ""
    if not local:
        return 0
    bounds = recipe.get("set_symbol_bounds") or layout.get("set_symbol_bounds") or {}
    if bounds.get("x", 0) > 1 or bounds.get("width", 0) == 0:
        warnings.append("set_symbol_skipped")
        return 0
    path = _find_asset(Path(local).name)
    if path is None:
        warnings.append("set_symbol_missing")
        return 0
    img = _open_rgba(path).resize((int(bounds["width"]), int(bounds["height"])), Image.LANCZOS)
    canvas.alpha_composite(img, (int(bounds.get("x", 0)), int(bounds.get("y", 0))))
    return 1


def _font(kind: str, size: int, warnings: list):
    key = (kind, int(size))
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    index = _db_index("font")
    font = None
    for code in FONT_PREFS[kind]:
        filename = index.get(code)
        if not filename or not (SHARED_DIR / filename).is_file():
            continue
        try:
            font = ImageFont.truetype(str(SHARED_DIR / filename), max(1, int(size)))
            ImageDraw.Draw(Image.new("RGB", (8, 8))).text((0, 0), "A", font=font)
        except OSError:
            font = None
            continue
        break
    if font is None:
        font = ImageFont.load_default()
        warnings.append("font_fallback")
    _FONT_CACHE[key] = font
    return font


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list:
    lines = []
    for paragraph in str(text).split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        line = words[0]
        for word in words[1:]:
            probe = line + " " + word
            if draw.textlength(probe, font=font) <= max_w:
                line = probe
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def _draw_lines(draw, text, font, x, y, max_w, color, line_ratio=1.18):
    lines = _wrap(draw, text, font, max_w)
    line_h = int(font.size * line_ratio)
    for offset, line in enumerate(lines):
        draw.text((x, y + offset * line_h), line, font=font, fill=color)
    return y + len(lines) * line_h


def _mana_image(code: str, size: int):
    filename = _db_index("mana_symbol").get(code.lower())
    if not filename or Path(filename).suffix.lower() not in (".png", ".jpg", ".jpeg"):
        return None
    path = SHARED_DIR / filename
    if not path.is_file():
        return None
    return _open_rgba(path).resize((size, size), Image.LANCZOS)


def draw_mana(canvas: Image.Image, cost: str, right_x: int, y: int, size: int, warnings: list, color: str = TEXT_COLOR) -> int:
    draw = ImageDraw.Draw(canvas)
    font = _font("body", size, warnings)
    items = []
    position = 0
    for match in _MANA_TOKEN.finditer(str(cost)):
        if match.start() > position:
            items.append(("text", str(cost)[position:match.start()]))
        items.append(("symbol", match.group(1)))
        position = match.end()
    if position < len(str(cost)):
        items.append(("text", str(cost)[position:]))
    rendered = []
    total = 0
    for kind, value in items:
        if kind == "symbol":
            img = _mana_image(value, size)
            if img is not None:
                rendered.append(("img", img, size))
                total += size
                continue
            warnings.append("mana_symbol_missing:%s" % value)
            value = "{%s}" % value
        width = int(draw.textlength(value, font=font))
        rendered.append(("text", value, width))
        total += width
    cursor = right_x - total
    for kind, value, width in rendered:
        if kind == "img":
            canvas.alpha_composite(value, (cursor, y))
        else:
            draw.text((cursor, y), value, font=font, fill=color)
        cursor += width
    return len(rendered)


def _font_size(geometry: dict, default: int) -> int:
    for field in ("size", "font_size"):
        if geometry.get(field):
            return int(geometry[field])
    return default


def _width(geometry: dict, default: int) -> int:
    for field in ("max_w", "width", "w"):
        if geometry.get(field):
            return int(geometry[field])
    return default


def _color(geometry: dict, default: str) -> str:
    return geometry.get("color") or default


_TEXT_LAYOUT_KEY = {
    "title": ("title", "title"),
    "mana_cost": ("mana", "mana_cost"),
    "type_line": ("type", "type_line"),
    "oracle_text": ("rules", "oracle_box"),
    "flavor_text": ("rules", "oracle_box"),
    "pt": ("pt", "pt_text"),
    "loyalty": ("pt", "pt_text"),
    "defense": ("pt", "pt_text"),
    "collector_info": ("collector", "artist"),
}


def _default_geometry(key: str) -> dict:
    field = DEFAULT_LAYOUT[_TEXT_LAYOUT_KEY[key][1]]
    factor = DEFAULT_CANVAS[0] / float(DEFAULT_LAYOUT["canvas"]["w"])
    return {
        name: int(round(value * factor)) if isinstance(value, (int, float)) else value
        for name, value in field.items()
    }


def _geometry(entry: dict, key: str, layout: dict, warnings: list) -> dict:
    geometry = entry.get("bounds")
    if geometry:
        return geometry
    template_key = _TEXT_LAYOUT_KEY[key][0]
    geometry = (layout.get("text_bounds") or {}).get(template_key)
    if geometry:
        return geometry
    warnings.append("text_bounds_default")
    return _default_geometry(key)


def _draw_block(draw, text, font, geometry, default_w, default_color):
    x = int(geometry.get("x") or 0)
    y = int(geometry.get("y") or 0)
    width = _width(geometry, default_w)
    align = geometry.get("align")
    color = _color(geometry, default_color)
    lines = _wrap(draw, text, font, width)
    line_h = int(font.size * 1.18)
    for offset, line in enumerate(lines):
        line_w = draw.textlength(line, font=font)
        if align == "center":
            line_x = x + (width - line_w) / 2
        elif align == "right":
            line_x = x + width - line_w
        else:
            line_x = x
        draw.text((line_x, y + offset * line_h), line, font=font, fill=color)
    return y + len(lines) * line_h


def _normalized(text: str) -> str:
    return " ".join(str(text).split())


def draw_text(canvas: Image.Image, recipe: dict, layout: dict, warnings: list) -> int:
    layers = recipe.get("text_layers") or {}
    draw = ImageDraw.Draw(canvas)
    drawn = 0

    for key, default_w in (("title", 980), ("type_line", 1100)):
        entry = layers.get(key) or {}
        text = entry.get("text")
        if not text:
            continue
        geometry = _geometry(entry, key, layout, warnings)
        font = _font("title" if key == "title" else "type", _font_size(geometry, 76), warnings)
        _draw_block(draw, text, font, geometry, default_w, TEXT_COLOR)
        drawn += 1

    entry = layers.get("mana_cost") or {}
    mana_text = entry if isinstance(entry, str) else entry.get("text")
    if mana_text:
        geometry = entry if isinstance(entry, str) else _geometry(entry, "mana_cost", layout, warnings)
        x = int(geometry.get("x") or 0)
        width = int(geometry.get("width") or geometry.get("w") or 0)
        right_x = x + width if width else x or canvas.width - 40
        y = int(geometry.get("y") or 0)
        draw_mana(canvas, mana_text, right_x, y, _font_size(geometry, 68), warnings, _color(geometry, TEXT_COLOR))
        drawn += 1

    entry = layers.get("oracle_text") or {}
    oracle_text = entry.get("text")
    bottom = None
    if oracle_text:
        geometry = _geometry(entry, "oracle_text", layout, warnings)
        font = _font("body", _font_size(geometry, 58), warnings)
        bottom = _draw_block(draw, oracle_text, font, geometry, 1276, TEXT_COLOR)
        drawn += 1

    entry = layers.get("flavor_text") or {}
    flavor_text = entry.get("text")
    if flavor_text and oracle_text and _normalized(flavor_text) not in _normalized(oracle_text):
        geometry = _geometry(entry, "flavor_text", layout, warnings)
        flavor_geometry = dict(geometry)
        flavor_geometry["y"] = (bottom if bottom is not None else int(geometry.get("y") or 0)) + 24
        font = _font("body", _font_size(geometry, 58), warnings)
        _draw_block(draw, flavor_text, font, flavor_geometry, 1276, TEXT_COLOR)
        drawn += 1

    entry = layers.get("pt") or {}
    power, toughness = entry.get("power"), entry.get("toughness")
    if power is not None and toughness is not None:
        geometry = _geometry(entry, "pt", layout, warnings)
        font = _font("pt", _font_size(geometry, 74), warnings)
        _draw_block(draw, "%s/%s" % (power, toughness), font, geometry, 205, TEXT_COLOR)
        drawn += 1

    for key in ("loyalty", "defense"):
        entry = layers.get(key) or {}
        text = entry.get("text")
        if not text:
            continue
        geometry = _geometry(entry, key, layout, warnings)
        font = _font("pt", _font_size(geometry, 74), warnings)
        _draw_block(draw, text, font, geometry, 205, TEXT_COLOR)
        drawn += 1

    entry = layers.get("collector_info") or {}
    text = entry.get("text")
    if text:
        geometry = _geometry(entry, "collector_info", layout, warnings)
        font = _font("body", _font_size(geometry, 34), warnings)
        _draw_block(draw, text, font, geometry, 800, COLLECTOR_COLOR)
        drawn += 1

    return drawn


def _pick_recipe(recipe: dict) -> tuple:
    if recipe.get("recipes"):
        face = recipe["recipes"][0] if recipe["recipes"] else {}
        return face, recipe.get("meta") or {}
    return recipe, recipe.get("meta") or {}


def render_recipe(recipe: dict, art_override=None, canvas: tuple = DEFAULT_CANVAS) -> dict:
    face, meta = _pick_recipe(recipe)
    declared = meta.get("canvas") or {}
    width = int(declared.get("width") or canvas[0])
    height = int(declared.get("height") or canvas[1])
    warnings = []
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_art(image, face.get("art_layer") or {}, art_override, warnings)
    draw_layers(image, face.get("layers") or [], warnings)
    layout = get_template_layout(face.get("template") or "")
    draw_set_symbol(image, face, layout, warnings)
    draw_text(image, face, layout, warnings)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return {"png": buffer.getvalue(), "width": width, "height": height, "warnings": warnings}


def save_recipe_png(recipe: dict, out_path: str, art_override=None) -> str:
    result = render_recipe(recipe, art_override=art_override)
    with open(out_path, "wb") as handle:
        handle.write(result["png"])
    return out_path
