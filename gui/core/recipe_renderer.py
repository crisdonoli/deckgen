"""Draw a resolved frame recipe (core.frame_resolver.build_recipe) onto a PNG canvas."""
import io
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

import httpx
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

try:
    from ..config import FRAMES_DIR as _CFG_FRAMES_DIR, SHARED_DIR as _CFG_SHARED_DIR
    from .asset_catalog import scan_shared_folder
    from .canvas_replay import replay_canvas_ops
    from .asset_paths import FRAMES_URL_PREFIX, SHARED_URL_PREFIX, find_resource_file, frame_file_path, shared_file_path
    from .card_layouts import DEFAULT_LAYOUT, get_template_layout
    from .svg_raster import backend as svg_backend, rasterize_svg
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from config import FRAMES_DIR as _CFG_FRAMES_DIR, SHARED_DIR as _CFG_SHARED_DIR
    from core.asset_catalog import scan_shared_folder
    from core.canvas_replay import replay_canvas_ops
    from core.asset_paths import FRAMES_URL_PREFIX, SHARED_URL_PREFIX, find_resource_file, frame_file_path, shared_file_path
    from core.card_layouts import DEFAULT_LAYOUT, get_template_layout
    from core.svg_raster import backend as svg_backend, rasterize_svg

FRAMES_DIR = Path(_CFG_FRAMES_DIR)
SHARED_DIR = Path(_CFG_SHARED_DIR)
DEFAULT_CANVAS = (1500, 2100)

TEXT_COLOR = "#111111"
COLLECTOR_COLOR = "#f2f2f2"
MANA_FONT_SIZE_RATIO = 1.0
FONT_PREFS = {
    "title": ("beleren-b", "beleren-bsc", "beleren"),
    "type": ("beleren-b", "matrix-b", "matrix"),
    "body": ("mplantin", "mplantin-i", "matrix"),
    "body_italic": ("mplantin-i", "mplantin", "matrix"),
    "pt": ("beleren-b", "beleren-bsc", "matrix-b", "matrix"),
}
_MANA_TOKEN = re.compile(r"\{([^{}]+)\}")
_HTTP_USER_AGENT = "DeckGenStudio/2.0 (https://github.com/cridonoso/deckgen)"
_ART_CACHE = {}
_FONT_CACHE = {}
_SYMBOL_CACHE = {}
_CODE_INDEX = {}


def _db_index(category: str) -> dict:
    if category not in _CODE_INDEX:
        _CODE_INDEX[category] = scan_shared_folder(category)
    return _CODE_INDEX[category]


def _normalize_mana_code(raw: str) -> str:
    code = str(raw or "").strip().lower().replace("/", "")
    if code == "q":
        return "untap"
    if code == "∞":
        return "inf"
    if code in ("1/2", "½"):
        return "half"
    return code


def _open_rgba(path) -> Image.Image:
    with Image.open(path) as img:
        return img.convert("RGBA")


def _hex_rgba(value: str, alpha: int = 255) -> tuple:
    raw = str(value or "").strip().lower()
    if raw == "white":
        return (242, 242, 242, alpha)
    if raw == "black":
        return (17, 17, 17, alpha)
    code = raw.lstrip("#")
    if len(code) == 3:
        code = "".join(ch * 2 for ch in code)
    if len(code) != 6:
        return (17, 17, 17, alpha)
    return (int(code[0:2], 16), int(code[2:4], 16), int(code[4:6], 16), alpha)


def _fetch_remote(url: str):
    cached = _ART_CACHE.get(url)
    if cached is not None:
        return cached.copy()
    try:
        # Scryfall's image CDN rejects requests without a User-Agent (HTTP 400).
        headers = {"User-Agent": _HTTP_USER_AGENT, "Accept": "image/*,*/*;q=0.8"}
        with httpx.Client(timeout=15.0, follow_redirects=True, headers=headers, transport=httpx.HTTPTransport(local_address="0.0.0.0", retries=2)) as client:
            response = client.get(url)
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
    source = override if override is not None else (art_layer.get("local_path") or art_layer.get("source"))
    if source is None:
        return 0
    img = load_art(source, warnings)
    if img is None:
        warnings.append("art_unavailable")
        return 0
    transform = art_layer.get("transform") or {}
    bounds = art_layer.get("bounds") or {}
    width = int(bounds.get("w") or bounds.get("width") or canvas.width)
    height = int(bounds.get("h") or bounds.get("height") or canvas.height)
    x = int(transform.get("x", bounds.get("x") or 0))
    y = int(transform.get("y", bounds.get("y") or 0))
    img = ImageOps.fit(_transform_art(img, transform), (width, height), method=Image.LANCZOS, centering=(0.5, 0.5))
    canvas.alpha_composite(img, (x, y))
    return 1


def _find_asset(filename: str):
    if not filename:
        return None
    direct = Path(filename)
    if direct.is_file():
        return direct
    name = direct.name
    for base in (FRAMES_DIR, SHARED_DIR):
        candidate = base / name
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


def _place_component(canvas: Image.Image, img: Image.Image, role: str) -> None:
    cw, ch = canvas.size
    iw, ih = img.size
    if (iw, ih) == (cw, ch):
        canvas.alpha_composite(img)
        return
    aspect = iw / float(ih) if ih else 1.0
    card_aspect = cw / float(ch)
    if abs(aspect - card_aspect) <= 0.04:
        canvas.alpha_composite(img.resize((cw, ch), Image.LANCZOS))
        return
    # Thresholds below are in base (1500 px wide) canvas units; `base` keeps small
    # components proportional when exporting at a higher DPI.
    base = cw / float(DEFAULT_CANVAS[0])
    if role == "crown":
        scale = cw / 2010.0 if iw > DEFAULT_CANVAS[0] else base
        tw = max(1, int(round(iw * scale)))
        th = max(1, int(round(ih * scale)))
        resized = img.resize((tw, th), Image.LANCZOS) if scale != 1.0 else img
        x = (cw - tw) // 2
        y = int(round(45 * (ch / 2100.0)))
        canvas.alpha_composite(resized, (max(0, x), max(0, y)))
        return
    if role == "pt_box":
        scale = (cw / 2010.0) if iw > 320 else base
        tw = max(1, int(round(iw * scale)))
        th = max(1, int(round(ih * scale)))
        resized = img.resize((tw, th), Image.LANCZOS) if scale != 1.0 else img
        x = int(round(1152 * (cw / 1500.0)))
        y = int(round(1862 * (ch / 2100.0)))
        canvas.alpha_composite(resized, (max(0, x), max(0, y)))
        return
    if role in ("stamp", "name_box") and iw < DEFAULT_CANVAS[0] * 0.4:
        tw = max(1, int(round(iw * (cw / 1500.0))))
        th = max(1, int(round(ih * (ch / 2100.0))))
        resized = img.resize((tw, th), Image.LANCZOS) if (tw, th) != (iw, ih) else img
        x = (cw - tw) // 2
        y = int(round(1885 * (ch / 2100.0)))
        canvas.alpha_composite(resized, (max(0, x), max(0, y)))
        return
    canvas.alpha_composite(ImageOps.fit(img, (cw, ch), method=Image.LANCZOS))


def draw_layers(canvas: Image.Image, layers: list, warnings: list) -> int:
    drawn = 0
    masks_skipped = 0
    for layer in sorted(layers or [], key=lambda item: item.get("z_index") or 0):
        if layer.get("type") == "procedural":
            _draw_procedural(canvas, layer, warnings)
            drawn += 1
            continue
        role = layer.get("asset_role")
        if role in ("mask", "pinline"):
            masks_skipped += 1
            continue
        orig_path = str(layer.get("original_path") or "")
        if "cornerCutout" in orig_path or "/stamp/" in orig_path or "/margins/" in orig_path:
            continue
        path = _find_asset(layer.get("filename") or "")
        if path is None:
            warnings.append("layer_missing:%s" % layer.get("filename"))
            continue
        img = _open_rgba(path)
        mask_name = layer.get("mask_id") or layer.get("mask")
        if mask_name:
            img = _destination_in(img, mask_name, warnings)
        if layer.get("blend") == "multiply":
            if img.size != canvas.size:
                img = ImageOps.fit(img, canvas.size, method=Image.LANCZOS)
            _composite_multiply(canvas, img)
        else:
            _place_component(canvas, img, role or "")
        drawn += 1
    if masks_skipped:
        warnings.append("mask_layers_skipped")
    return drawn


def _resolve_frame_ref(ref: str):
    """Map a frame URL from the Card Builder (/assets/resources/...) to a file on disk."""
    raw = str(ref or "").strip()
    if not raw or raw.startswith("data:"):
        return None
    path = urllib.parse.unquote(urllib.parse.urlsplit(raw).path)
    if path.startswith(FRAMES_URL_PREFIX):
        candidate = frame_file_path(path[len(FRAMES_URL_PREFIX):])
    elif path.startswith(SHARED_URL_PREFIX):
        candidate = shared_file_path(path[len(SHARED_URL_PREFIX):])
    elif raw.startswith(("http://", "https://")) or path.startswith("/"):
        return None
    else:
        candidate = find_resource_file(path)
    return candidate if candidate is not None and Path(candidate).is_file() else None


def _tinted(img: Image.Image, tint: str) -> Image.Image:
    # Same as the browser's source-atop fill: keep the alpha, replace every colour.
    solid = Image.new("RGBA", img.size, _hex_rgba(tint))
    solid.putalpha(img.getchannel("A"))
    return solid


def _with_opacity(img: Image.Image, opacity) -> Image.Image:
    try:
        opacity = max(0.0, min(1.0, float(opacity)))
    except (TypeError, ValueError):
        return img
    if opacity < 1.0:
        img.putalpha(img.getchannel("A").point(lambda a: int(round(a * opacity))))
    return img


def _clip_rows(img: Image.Image, y0: int, y1: int) -> Image.Image:
    band = Image.new("L", img.size, 0)
    band.paste(255, (0, max(0, y0), img.width, max(0, y1)))
    img.putalpha(ImageChops.multiply(img.getchannel("A"), band))
    return img


def _spec_split_y(face: dict, spec: dict, canvas_h: int, scale_y: float) -> int:
    """Same rule as layer_manager.computeFrameSplitY: just above the type line."""
    if not spec.get("split_y_from_face"):
        bounds = ((face.get("text_layers") or {}).get("type_line") or {}).get("bounds") or {}
        try:
            type_y = float(bounds.get("y"))
        except (TypeError, ValueError):
            type_y = None
        if type_y is not None and 400 < type_y < 1950:
            return int(round(max(0.0, type_y - 22) * canvas_h / 2100.0))
    try:
        return int(round(float(spec.get("split_y")) * scale_y))
    except (TypeError, ValueError):
        return int(round(1167 * canvas_h / 2100.0))


def _fallback_art_placement(face: dict) -> dict:
    art = face.get("art_layer") or {}
    bounds = art.get("bounds") or {}
    bounds = {
        "x": bounds.get("x", 115),
        "y": bounds.get("y", 237),
        "w": bounds.get("w") or bounds.get("width") or 1271,
        "h": bounds.get("h") or bounds.get("height") or 930,
    }
    transform = dict(art.get("transform") or {})
    tx = float(transform.get("x") or 0)
    ty = float(transform.get("y") or 0)
    transform["x"] = 0 if tx == float(bounds["x"] or 0) else tx
    transform["y"] = 0 if ty == float(bounds["y"] or 0) else ty
    transform["scale"] = float(transform.get("scale") or 1.0)
    return {"bounds": bounds, "transform": transform}


def _draw_spec_art(canvas: Image.Image, face: dict, layer: dict, art_override, scale_x: float, scale_y: float, warnings: list) -> int:
    """Port of crop_masks.drawArtInto: cover-fit the art into its zone, then offset, zoom and rotate."""
    source = layer.get("source")
    if source is None:
        source = art_override
    if source is None:
        art = face.get("art_layer") or {}
        source = art.get("local_path") or art.get("source")
    img = load_art(source, warnings) if source is not None else None
    if img is None:
        warnings.append("art_unavailable")
        return 0
    placement = layer.get("placement") or _fallback_art_placement(face)
    bounds = placement.get("bounds") or {}
    transform = placement.get("transform") or {}
    zx = float(bounds.get("x") or 0) * scale_x
    zy = float(bounds.get("y") or 0) * scale_y
    zw = float(bounds.get("w") or 0) * scale_x
    zh = float(bounds.get("h") or 0) * scale_y
    if zw <= 0 or zh <= 0:
        return 0
    zoom = float(transform.get("scale") or 1.0)
    fit = max(zw / img.width, zh / img.height) * zoom
    dw, dh = max(1, int(round(img.width * fit))), max(1, int(round(img.height * fit)))
    art = img.resize((dw, dh), Image.LANCZOS)
    brightness = float(layer.get("brightness") or 1.0)
    if abs(brightness - 1.0) > 0.01:
        alpha = art.getchannel("A")
        art = ImageEnhance.Brightness(art.convert("RGB")).enhance(brightness).convert("RGBA")
        art.putalpha(alpha)
    ox = float(transform.get("x") or 0) * scale_x
    oy = float(transform.get("y") or 0) * scale_y
    rotation = float(transform.get("rotation") or 0)
    if rotation:
        art = art.rotate(-rotation, resample=Image.BICUBIC, expand=True)
        px = zx + zw / 2 + ox - art.width / 2
        py = zy + zh / 2 + oy - art.height / 2
    else:
        px = zx + (zw - dw) / 2 + ox
        py = zy + (zh - dh) / 2 + oy
    piece = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    piece.paste(art, (int(round(px)), int(round(py))), art)
    if not layer.get("unclipped"):
        zone = Image.new("L", canvas.size, 0)
        zone.paste(255, (int(round(zx)), int(round(zy)), int(round(zx + zw)), int(round(zy + zh))))
        piece.putalpha(ImageChops.multiply(piece.getchannel("A"), zone))
    canvas.alpha_composite(_with_opacity(piece, layer.get("opacity", 1.0)))
    return 1


def _draw_spec_shape(canvas: Image.Image, layer: dict, scale_x: float, scale_y: float) -> int:
    try:
        opacity = max(0.0, min(1.0, float(layer.get("opacity", 0.55))))
        x = float(layer.get("x") or 0) * scale_x
        y = float(layer.get("y") or 0) * scale_y
        w = float(layer.get("w") or 0) * scale_x
        h = float(layer.get("h") or 0) * scale_y
        radius = float(layer.get("radius") or 0) * scale_x
    except (TypeError, ValueError):
        return 0
    if opacity <= 0.001 or w <= 0 or h <= 0:
        return 0
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    fill = _hex_rgba(layer.get("color") or "#000000", int(round(255 * opacity)))
    box = [x, y, x + w, y + h]
    kind = layer.get("type")
    if kind == "circle":
        draw.ellipse(box, fill=fill)
    elif kind == "rounded":
        draw.rounded_rectangle(box, radius=max(0.0, min(radius, w / 2, h / 2)), fill=fill)
    else:
        draw.rectangle(box, fill=fill)
    canvas.alpha_composite(overlay)
    return 1


def draw_frame_spec(canvas: Image.Image, face: dict, spec: dict, art_override, warnings: list) -> int:
    """Draw the card as laid out in the Card Builder (layer_manager.buildFrameExportSpec).

    Covers what the preview controls: layer order, frame images, opacity, tint, shapes,
    the art's position/zoom/rotation/opacity/brightness and, for pop-out cards, the frame
    split at the type line (Top half and Bottom/textbox half can use different images).
    """
    cw, ch = canvas.size
    scale_x = cw / float(spec.get("canvas_width") or cw)
    scale_y = ch / float(spec.get("canvas_height") or ch)
    split_y = _spec_split_y(face, spec, ch, scale_y)
    drawn = 0
    for layer in spec.get("layers") or []:
        if not isinstance(layer, dict):
            continue
        key = layer.get("key")
        if key == "art":
            drawn += _draw_spec_art(canvas, face, layer, art_override, scale_x, scale_y, warnings)
            continue
        if key == "shape":
            drawn += _draw_spec_shape(canvas, layer, scale_x, scale_y)
            continue
        if key == "pw_backdrop":
            if isinstance(layer.get("ops"), list):
                replay_canvas_ops(canvas, layer["ops"], warnings, scale=scale_x)
            else:
                _draw_planeswalker_backdrop(canvas, face)
            continue
        path = _resolve_frame_ref(layer.get("url"))
        if path is None:
            warnings.append("frame_missing:%s" % layer.get("url"))
            continue
        img = _open_rgba(path)
        tint = str(layer.get("tint") or "")
        if re.fullmatch(r"#[0-9a-fA-F]{6}", tint):
            img = _tinted(img, tint)
        clip = layer.get("clip")
        opacity = layer.get("opacity", 1.0)
        try:
            opaque = float(opacity) >= 1.0
        except (TypeError, ValueError):
            opaque = True
        if clip not in ("top", "bottom") and opaque:
            # Common case: draw straight onto the card (saves a full-size layer at high DPI).
            _place_component(canvas, img, str(layer.get("role") or ""))
            drawn += 1
            continue
        piece = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        _place_component(piece, img, str(layer.get("role") or ""))
        if clip == "top":
            _clip_rows(piece, 0, split_y)
        elif clip == "bottom":
            _clip_rows(piece, split_y, ch)
        canvas.alpha_composite(_with_opacity(piece, opacity))
        drawn += 1
    return drawn


def _resolve_set_symbol_file(recipe: dict) -> Path | None:
    symbol = recipe.get("set_symbol") or {}
    local = symbol.get("path") or symbol.get("url") or ""
    if local:
        found = _find_asset(local)
        if found is not None:
            return found
    collector = (recipe.get("text_layers") or {}).get("collector_info") or {}
    set_code = str(collector.get("set") or "").strip().lower()
    rarity = str(collector.get("rarity") or "common").strip().lower()
    r_char = rarity[0] if rarity else "c"
    idx = _db_index("set_symbol")
    for cand in (f"{set_code}-{r_char}", f"{set_code}-c", set_code, f"cc-{r_char}", "cc-c"):
        fname = idx.get(cand)
        if fname and (SHARED_DIR / fname).is_file():
            return SHARED_DIR / fname
    return None


def draw_set_symbol(canvas: Image.Image, recipe: dict, layout: dict, warnings: list) -> int:
    bounds = recipe.get("set_symbol_bounds") or layout.get("set_symbol_bounds") or {}
    bw = int(bounds.get("width") or bounds.get("w") or 0)
    bh = int(bounds.get("height") or bounds.get("h") or 0)
    if bounds.get("x", 0) in (1, 2) or bw <= 0 or bh <= 0:
        warnings.append("set_symbol_skipped")
        return 0
    path = _resolve_set_symbol_file(recipe)
    if path is None:
        return 0
    suffix = path.suffix.lower()
    target_dim = max(bw, bh, 64)
    if suffix == ".svg":
        try:
            png_path = rasterize_svg(str(path), size=target_dim * 2)
            raw = _open_rgba(png_path)
        except (OSError, subprocess.CalledProcessError, ValueError):
            warnings.append("set_symbol_raster_failed")
            return 0
    else:
        raw = _open_rgba(path)
    raw.thumbnail((bw, bh), Image.LANCZOS)
    rx = int(bounds.get("x", 0))
    ry = int(bounds.get("y", 0))
    # Set symbol bounds in frame_layouts use right/center anchor at (rx, ry) when rx > 1200
    draw_x = rx - raw.width if rx > 1100 else rx
    draw_y = ry - raw.height // 2
    canvas.alpha_composite(raw, (max(0, draw_x), max(0, draw_y)))
    return 1


def _font(kind: str, size: int, warnings: list):
    key = (kind, int(size))
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    index = _db_index("font")
    font = None
    for code in FONT_PREFS.get(kind, FONT_PREFS["body"]):
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


def _mana_image(code: str, size: int, warnings: list, with_shadow: bool = True):
    norm_code = _normalize_mana_code(code)
    filename = _db_index("mana_symbol").get(norm_code)
    if not filename:
        return None
    path = SHARED_DIR / filename
    if not path.is_file():
        return None
    key = (str(path), size, bool(with_shadow))
    cached = _SYMBOL_CACHE.get(key)
    if cached is not None:
        return cached
    suffix = path.suffix.lower()
    if suffix == ".svg":
        try:
            png = rasterize_svg(str(path), size=size * 2)
            glyph = _open_rgba(png).resize((size, size), Image.LANCZOS)
        except (OSError, subprocess.CalledProcessError, ValueError):
            note = "mana_raster_failed:%s" % (svg_backend() or "none")
            if note not in warnings:
                warnings.append(note)
            return None
        if not svg_backend() and "mana_raster_fallback" not in warnings:
            warnings.append("mana_raster_fallback")
    elif suffix in (".png", ".jpg", ".jpeg"):
        glyph = _open_rgba(path).resize((size, size), Image.LANCZOS)
    else:
        return None

    if with_shadow:
        pad = max(2, size // 12)
        out = Image.new("RGBA", (size + pad, size + pad), (0, 0, 0, 0))
        shadow = Image.new("RGBA", (size + pad, size + pad), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        off_x = max(1, size // 28)
        off_y = max(2, size // 18)
        sdraw.ellipse((off_x, off_y, off_x + size - 1, off_y + size - 1), fill=(0, 0, 0, 155))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(1.0, size / 32.0)))
        out.alpha_composite(shadow, (0, 0))
        out.alpha_composite(glyph, (0, 0))
        img = out
    else:
        img = glyph

    _SYMBOL_CACHE[key] = img
    return img


def draw_mana(
    canvas: Image.Image,
    cost: str,
    right_x: int,
    y: int,
    size: int,
    warnings: list,
    color: str = TEXT_COLOR,
) -> int:
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
    gap = max(3, size // 14)
    for kind, value in items:
        if kind == "symbol":
            img = _mana_image(value, size, warnings, with_shadow=True)
            if img is not None:
                step = size + gap
                rendered.append(("img", img, step))
                total += step
                continue
            warnings.append("mana_symbol_missing:%s" % value)
            value = "{%s}" % value
        width = int(draw.textlength(value, font=font))
        rendered.append(("text", value, width))
        total += width
    cursor = right_x - total
    for kind, value, width in rendered:
        if kind == "img":
            canvas.alpha_composite(value, (max(0, int(cursor)), max(0, int(y))))
        else:
            draw.text((cursor, y), value, font=font, fill=_hex_rgba(color))
        cursor += width
    return len(rendered)


def _tokenize_inline_word(draw: ImageDraw.ImageDraw, word: str, font, sym_size: int, warnings: list) -> tuple[list, float]:
    tokens = []
    total_w = 0.0
    pos = 0
    for match in _MANA_TOKEN.finditer(word):
        if match.start() > pos:
            txt = word[pos:match.start()]
            w = draw.textlength(txt, font=font)
            tokens.append(("text", txt, w))
            total_w += w
        code = match.group(1)
        img = _mana_image(code, sym_size, warnings, with_shadow=True)
        if img is not None:
            w = float(sym_size + max(2, sym_size // 16))
            tokens.append(("sym", img, w, sym_size))
            total_w += w
        else:
            warnings.append("mana_symbol_missing:%s" % code)
            raw = "{%s}" % code
            w = draw.textlength(raw, font=font)
            tokens.append(("text", raw, w))
            total_w += w
        pos = match.end()
    if pos < len(word):
        txt = word[pos:]
        w = draw.textlength(txt, font=font)
        tokens.append(("text", txt, w))
        total_w += w
    return tokens, total_w


_LOYALTY_RE = re.compile(r"^\[?([+\-\u2212\u2013\u2014](?:\d+|X)|0)\]?\s*:\s*(.*)$", re.IGNORECASE)


def _parse_loyalty_line(para: str):
    m = _LOYALTY_RE.match(str(para or "").strip())
    if not m:
        return None
    raw = m.group(1).upper()
    direction = "zero"
    label = raw
    if raw.startswith("+"):
        direction = "up"
    elif raw[0] in ("-", "\u2212", "\u2013", "\u2014"):
        direction = "down"
        label = "\u2212" + raw[1:]
    return {"label": label, "dir": direction, "rest": m.group(2) or ""}


def _draw_loyalty_badge_pil(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, direction: str, label: str, warnings: list):
    hw = w / 2.0
    hh = h / 2.0
    if direction == "up":
        pts = [
            (cx, cy - hh),
            (cx + hw, cy - hh * 0.22),
            (cx + hw * 0.88, cy + hh),
            (cx - hw * 0.88, cy + hh),
            (cx - hw, cy - hh * 0.22),
        ]
    elif direction == "down":
        pts = [
            (cx - hw * 0.88, cy - hh),
            (cx + hw * 0.88, cy - hh),
            (cx + hw, cy + hh * 0.22),
            (cx, cy + hh),
            (cx - hw, cy + hh * 0.22),
        ]
    elif direction == "start":
        pts = [
            (cx - hw * 0.92, cy - hh * 0.72),
            (cx, cy - hh * 0.98),
            (cx + hw * 0.92, cy - hh * 0.72),
            (cx + hw, cy + hh * 0.12),
            (cx + hw * 0.6, cy + hh * 0.82),
            (cx, cy + hh),
            (cx - hw * 0.6, cy + hh * 0.82),
            (cx - hw, cy + hh * 0.12),
        ]
    else:
        pts = [
            (cx - hw * 0.82, cy - hh * 0.86),
            (cx + hw * 0.82, cy - hh * 0.86),
            (cx + hw, cy),
            (cx + hw * 0.82, cy + hh * 0.86),
            (cx - hw * 0.82, cy + hh * 0.86),
            (cx - hw, cy),
        ]
    draw.polygon(pts, fill=(17, 19, 23, 255), outline=(212, 218, 227, 255), width=max(2, int(round(h * 0.065))))
    f_px = max(14, int(round(h * (0.44 if len(label) >= 3 else 0.52))))
    lfont = _font("title", f_px, warnings)
    y_nudge = hh * 0.12 if direction == "up" else (-hh * 0.10 if direction == "down" else 0.0)
    draw.text((cx, cy + y_nudge), label, font=lfont, fill=(255, 255, 255, 255), anchor="mm")


def _layout_rich_paragraphs(
    draw: ImageDraw.ImageDraw,
    oracle_text: str,
    flavor_text: str,
    max_w: int,
    font_size: int,
    warnings: list,
) -> tuple[list, int, any, any]:
    font = _font("body", font_size, warnings)
    italic_font = _font("body_italic", max(14, int(round(font_size * 0.94))), warnings)
    sym_size = max(14, int(round(font_size * 0.88)))
    line_h = int(round(font_size * 1.22))
    para_gap = int(round(font_size * 0.28))
    space_w = draw.textlength(" ", font=font)

    blocks = []
    total_h = 0

    if oracle_text:
        paragraphs = [p.strip() for p in str(oracle_text).split("\n") if p.strip()]
        badge_indent = int(round(font_size * 1.45))
        for p_idx, para in enumerate(paragraphs):
            loy = _parse_loyalty_line(para)
            eff_max_w = max(160, max_w - badge_indent) if loy else max_w
            body = loy["rest"] if loy else para
            words = body.split()
            para_lines = []
            cur_line = []
            cur_w = 0.0
            for word in words:
                w_tokens, w_width = _tokenize_inline_word(draw, word, font, sym_size, warnings)
                if cur_line and cur_w + space_w + w_width > eff_max_w:
                    para_lines.append(cur_line)
                    cur_line = list(w_tokens)
                    cur_w = w_width
                else:
                    if cur_line:
                        cur_line.append(("text", " ", space_w))
                        cur_w += space_w
                    cur_line.extend(w_tokens)
                    cur_w += w_width
            if cur_line:
                para_lines.append(cur_line)
            if loy:
                min_h = int(round(font_size * 1.55))
                bh = max(len(para_lines) * line_h, min_h)
                blocks.append(("loyalty_para", (loy, para_lines, line_h, badge_indent), bh))
                total_h += bh
            else:
                for ln in para_lines:
                    blocks.append(("oracle_line", ln, line_h))
                    total_h += line_h
            if p_idx < len(paragraphs) - 1:
                blocks.append(("gap", None, para_gap))
                total_h += para_gap

    if flavor_text and (not oracle_text or _normalized(flavor_text) not in _normalized(oracle_text)):
        if blocks:
            sep_h = int(round(font_size * 0.45))
            blocks.append(("divider", None, sep_h))
            total_h += sep_h
        f_line_h = int(round(italic_font.size * 1.18))
        for para in str(flavor_text).split("\n"):
            words = para.split()
            if not words:
                continue
            line = words[0]
            for word in words[1:]:
                probe = line + " " + word
                if draw.textlength(probe, font=italic_font) <= max_w:
                    line = probe
                else:
                    blocks.append(("flavor_line", line, f_line_h))
                    total_h += f_line_h
                    line = word
            blocks.append(("flavor_line", line, f_line_h))
            total_h += f_line_h

    return blocks, total_h, font, italic_font


def draw_rich_rules_box(
    canvas: Image.Image,
    oracle_text: str,
    flavor_text: str,
    geometry: dict,
    default_color: str,
    warnings: list,
) -> int:
    draw = ImageDraw.Draw(canvas)
    x = int(geometry.get("x") or 129)
    y = int(geometry.get("y") or 1328)
    max_w = _width(geometry, 1242)
    max_h = int(geometry.get("height") or geometry.get("h") or 604)
    start_size = min(_font_size(geometry, 62), 64)
    min_size = 24
    color_rgba = _hex_rgba(_color(geometry, default_color))

    chosen_size = start_size
    blocks, total_h, font, italic_font = _layout_rich_paragraphs(
        draw, oracle_text, flavor_text, max_w, chosen_size, warnings
    )
    while chosen_size > min_size and total_h > max_h:
        chosen_size -= 2
        blocks, total_h, font, italic_font = _layout_rich_paragraphs(
            draw, oracle_text, flavor_text, max_w, chosen_size, warnings
        )

    cur_y = y + max(0, (max_h - total_h) // 2)
    bottom_limit = y + max_h

    for kind, content, h in blocks:
        if cur_y + int(h * 0.75) > bottom_limit:
            break
        if kind == "gap":
            cur_y += h
        elif kind == "divider":
            mid_y = cur_y + h // 2
            line_color = (color_rgba[0], color_rgba[1], color_rgba[2], 80)
            draw.line([(x + 40, mid_y), (x + max_w - 40, mid_y)], fill=line_color, width=2)
            cur_y += h
        elif kind == "flavor_line":
            draw.text((x, cur_y), content, font=italic_font, fill=color_rgba)
            cur_y += h
        elif kind == "loyalty_para":
            loy, para_lines, l_h, b_indent = content
            badge_w = int(round(chosen_size * 1.95))
            badge_h = int(round(chosen_size * 1.42))
            badge_cx = x + int(round(chosen_size * 0.12))
            badge_cy = cur_y + h // 2
            _draw_loyalty_badge_pil(draw, badge_cx, badge_cy, badge_w, badge_h, loy["dir"], loy["label"], warnings)
            txt_h = len(para_lines) * l_h
            line_y = cur_y + max(0, (h - txt_h) // 2)
            for ln in para_lines:
                cur_x = float(x + b_indent)
                for tok in ln:
                    if tok[0] == "text":
                        draw.text((cur_x, line_y), tok[1], font=font, fill=color_rgba)
                        cur_x += tok[2]
                    elif tok[0] == "sym":
                        sym_im = tok[1]
                        sym_s = tok[3]
                        sym_y = int(round(line_y + (chosen_size - sym_s) * 0.55))
                        if sym_im is not None:
                            canvas.alpha_composite(sym_im, (int(round(cur_x)), max(0, sym_y)))
                        cur_x += tok[2]
                line_y += l_h
            cur_y += h
        elif kind == "oracle_line":
            cur_x = float(x)
            for tok in content:
                if tok[0] == "text":
                    draw.text((cur_x, cur_y), tok[1], font=font, fill=color_rgba)
                    cur_x += tok[2]
                elif tok[0] == "sym":
                    sym_img = tok[1]
                    sym_size = tok[3]
                    sym_y = int(round(cur_y + (chosen_size - sym_size) * 0.55))
                    canvas.alpha_composite(sym_img, (int(round(cur_x)), max(0, sym_y)))
                    cur_x += tok[2]
            cur_y += h

    return cur_y


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
    "loyalty": ("loyalty", "pt_text"),
    "defense": ("defense", "pt_text"),
    "collector_info": ("collector_info", "artist"),
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


def _draw_single_line_shrunk(draw, text, font_kind, target_size, geometry, default_w, default_color, warnings):
    x = int(geometry.get("x") or 0)
    y = int(geometry.get("y") or 0)
    width = _width(geometry, default_w)
    align = geometry.get("align")
    color = _hex_rgba(_color(geometry, default_color))
    size = int(target_size)
    font = _font(font_kind, size, warnings)
    while size > 20 and draw.textlength(str(text), font=font) > width:
        size -= 2
        font = _font(font_kind, size, warnings)
    line_w = draw.textlength(str(text), font=font)
    if align == "center":
        line_x = x + (width - line_w) / 2
    elif align == "right":
        line_x = x + width - line_w
    else:
        line_x = x
    draw.text((line_x, y), str(text), font=font, fill=color)
    return y + int(font.size * 1.18)


def _normalized(text: str) -> str:
    return " ".join(str(text).split())


def _default_text_color_for_face(recipe: dict) -> str:
    tax = recipe.get("taxonomy") or {}
    effects = set(tax.get("frame_effects") or [])
    if "inverted" in effects or tax.get("border_color") == "borderless" or recipe.get("template") == "M15Borderless":
        return "#f2f2f2"
    return TEXT_COLOR


def draw_text(canvas: Image.Image, recipe: dict, layout: dict, warnings: list) -> int:
    layers = recipe.get("text_layers") or {}
    draw = ImageDraw.Draw(canvas)
    drawn = 0
    face_text_color = _default_text_color_for_face(recipe)

    mana_entry = layers.get("mana_cost") or {}
    mana_text = mana_entry if isinstance(mana_entry, str) else mana_entry.get("text")
    mana_tokens = _MANA_TOKEN.findall(str(mana_text or ""))

    for key, default_w in (("title", 980), ("type_line", 1100)):
        entry = layers.get(key) or {}
        text = entry.get("text")
        if not text:
            continue
        geometry = dict(_geometry(entry, key, layout, warnings))
        if key == "title" and mana_tokens:
            mana_size = 76
            avail_w = max(300, (canvas.width - 110) - len(mana_tokens) * (mana_size + 6) - int(geometry.get("x") or 125) - 20)
            geometry["max_w"] = min(_width(geometry, default_w), avail_w)
        font_kind = "title" if key == "title" else "type"
        _draw_single_line_shrunk(
            draw, text, font_kind, _font_size(geometry, 74 if key == "title" else 64), geometry, default_w, face_text_color, warnings
        )
        drawn += 1

    if mana_text:
        geometry = mana_entry if isinstance(mana_entry, str) else _geometry(mana_entry, "mana_cost", layout, warnings)
        x = int(geometry.get("x") or 0)
        width = int(geometry.get("width") or geometry.get("w") or 0)
        right_x = x + width if width else (x if x > 500 else canvas.width - 106)
        y = int(geometry.get("y") or 118)
        draw_mana(canvas, mana_text, right_x, y, min(_font_size(geometry, 68), 76), warnings, _color(geometry, face_text_color))
        drawn += 1

    oracle_entry = layers.get("oracle_text") or {}
    oracle_text = oracle_entry.get("text")
    flavor_entry = layers.get("flavor_text") or {}
    flavor_text = flavor_entry.get("text")
    if oracle_text or flavor_text:
        geometry = _geometry(oracle_entry if oracle_text else flavor_entry, "oracle_text", layout, warnings)
        draw_rich_rules_box(canvas, oracle_text or "", flavor_text or "", geometry, face_text_color, warnings)
        drawn += 1

    adv_title = (layers.get("adventure_title") or {}).get("text")
    adv_mana = (layers.get("adventure_mana_cost") or {}).get("text")
    adv_type = (layers.get("adventure_type_line") or {}).get("text")
    adv_oracle = (layers.get("adventure_oracle_text") or {}).get("text")
    if adv_mana:
        g = _geometry(layers.get("adventure_mana_cost") or {}, "adventure_mana_cost", layout, warnings)
        rx = int(g.get("x") or 0) + int(g.get("width") or g.get("w") or 724)
        draw_mana(canvas, adv_mana, rx, int(g.get("y") or 1340), min(_font_size(g, 52), 56), warnings, "#ffffff")
        drawn += 1
    if adv_title:
        g = _geometry(layers.get("adventure_title") or {}, "adventure_title", layout, warnings)
        _draw_single_line_shrunk(draw, adv_title, "title", _font_size(g, 54), g, int(g.get("w") or g.get("width") or 470), "#ffffff", warnings)
        drawn += 1
    if adv_type:
        g = _geometry(layers.get("adventure_type_line") or {}, "adventure_type_line", layout, warnings)
        _draw_single_line_shrunk(draw, adv_type, "type", _font_size(g, 46), g, int(g.get("w") or g.get("width") or 584), "#ffffff", warnings)
        drawn += 1
    if adv_oracle:
        g = _geometry(layers.get("adventure_oracle_text") or {}, "adventure_oracle_text", layout, warnings)
        draw_rich_rules_box(canvas, adv_oracle, "", g, face_text_color, warnings)
        drawn += 1

    entry = layers.get("pt") or {}
    power, toughness = entry.get("power"), entry.get("toughness")
    if power is not None and toughness is not None:
        geometry = _geometry(entry, "pt", layout, warnings)
        _draw_single_line_shrunk(draw, "%s/%s" % (power, toughness), "pt", _font_size(geometry, 74), geometry, 205, face_text_color, warnings)
        drawn += 1

    for key in ("loyalty", "defense"):
        entry = layers.get(key) or {}
        text = entry.get("text")
        if not text:
            continue
        geometry = _geometry(entry, key, layout, warnings)
        if key == "loyalty":
            bx = int(geometry.get("x") or 1209) + _width(geometry, 210) / 2.0
            by = int(geometry.get("y") or 1894) + int(geometry.get("height") or geometry.get("h") or 78) / 2.0
            _draw_loyalty_badge_pil(draw, bx, by, 185, 138, "start", str(text), warnings)
        else:
            _draw_single_line_shrunk(draw, text, "pt", _font_size(geometry, 74), geometry, 205, "#f2f2f2", warnings)
        drawn += 1

    entry = layers.get("collector_info") or {}
    artist_name = str(entry.get("artist") or "").strip()
    col_num = str(entry.get("collector_number") or "").strip()
    set_up = str(entry.get("set") or "mtg").strip().upper()
    lang_up = str(entry.get("lang") or "en").strip().upper()
    rar_ch = str(entry.get("rarity") or "c").strip()[:1].upper() or "C"
    if artist_name or col_num or set_up:
        f_size = 30
        base_x = 94
        line2_y = 1998
        line1_y = line2_y - int(round(f_size * 1.24))
        col2_x = base_x + int(round(f_size * 6.4))
        cfont = _font("title", f_size, warnings)
        cfill = _hex_rgba(COLLECTOR_COLOR)
        if col_num:
            draw.text((base_x, line1_y), col_num, font=cfont, fill=cfill)
        draw.text((col2_x, line1_y), rar_ch, font=cfont, fill=cfill)
        draw.text((base_x, line2_y), f"{set_up} \u2022 {lang_up}", font=cfont, fill=cfill)
        if artist_name:
            draw.text((col2_x, line2_y), artist_name, font=cfont, fill=cfill)
        drawn += 1

    return drawn


def _pick_recipe(recipe: dict) -> tuple:
    if recipe.get("recipes"):
        face = recipe["recipes"][0] if recipe["recipes"] else {}
        return face, recipe.get("meta") or {}
    return recipe, recipe.get("meta") or {}


def _draw_planeswalker_backdrop(canvas: Image.Image, recipe: dict) -> None:
    tax = recipe.get("taxonomy") or {}
    if tax.get("structural_type_override") != "planeswalker":
        return
    is_tall = tax.get("box_variant") == "tall" or recipe.get("template") == "PlaneswalkerTall"
    s = canvas.width / 1500.0
    y0 = (1148 if is_tall else 1285) * s
    y1 = 1906 * s
    x0, x1 = 112 * s, 1388 * s
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.rounded_rectangle([x0, y0, x1, y1], radius=22 * s, fill=(235, 238, 244, 210))
    # Subtle alternating ability bands
    bands = 4 if is_tall else 3
    band_h = (y1 - y0) / float(bands)
    for idx in range(bands):
        if idx % 2 == 1:
            by0 = int(round(y0 + idx * band_h))
            by1 = int(round(y0 + (idx + 1) * band_h))
            odraw.rectangle([x0 + 6 * s, by0, x1 - 6 * s, min(y1 - 6 * s, by1)], fill=(210, 216, 226, 110))
    canvas.alpha_composite(overlay)


def render_recipe(recipe: dict, art_override=None, canvas: tuple = DEFAULT_CANVAS, scale: float = 1.0) -> dict:
    """Render the first face. `scale` multiplies the 1500x2100 canvas (2.0 = 3000x4200).

    With a Card Builder frame_spec everything is drawn at the target size (frames and art are
    resampled once from their sources; text, SVG symbols and shapes are drawn natively), so a
    higher scale adds real detail. The legacy recipe path is drawn at 1x and upscaled.
    """
    face, meta = _pick_recipe(recipe)
    declared = meta.get("canvas") or {}
    base_w = int(declared.get("width") or canvas[0])
    base_h = int(declared.get("height") or canvas[1])
    scale = max(0.25, min(4.0, float(scale or 1.0)))
    out_w, out_h = int(round(base_w * scale)), int(round(base_h * scale))
    warnings = []
    frame_spec = face.get("frame_spec")
    use_spec = isinstance(frame_spec, dict) and bool(frame_spec.get("layers"))
    background = _hex_rgba(frame_spec.get("bg_color") or "#111111") if use_spec else (17, 17, 17, 255)
    width, height = (out_w, out_h) if use_spec else (base_w, base_h)
    image = Image.new("RGBA", (width, height), background)
    if use_spec:
        draw_frame_spec(image, face, frame_spec, art_override, warnings)
    else:
        draw_art(image, face.get("art_layer") or {}, art_override, warnings)
        _draw_planeswalker_backdrop(image, face)
        draw_layers(image, face.get("layers") or [], warnings)
    layout = get_template_layout(face.get("template") or "")
    text_ops = frame_spec.get("text_ops") if use_spec else None
    if isinstance(text_ops, list):
        # Set symbol and text exactly as the Card Builder preview drew them.
        spec_w = float(frame_spec.get("canvas_width") or base_w)
        replay_canvas_ops(image, text_ops, warnings, scale=width / spec_w)
    else:
        draw_set_symbol(image, face, layout, warnings)
        if not (use_spec and frame_spec.get("hide_text")):
            draw_text(image, face, layout, warnings)
    if image.size != (out_w, out_h):
        image = image.resize((out_w, out_h), Image.LANCZOS)
    buffer = io.BytesIO()
    # Physical size metadata: the 1500 px wide card is 2.5 in, i.e. 600 DPI at scale 1.
    dpi = 600.0 * out_w / float(base_w)
    image.save(buffer, format="PNG", dpi=(dpi, dpi))
    return {"png": buffer.getvalue(), "width": out_w, "height": out_h, "warnings": warnings}


def save_recipe_png(recipe: dict, out_path: str, art_override=None, scale: float = 1.0) -> str:
    result = render_recipe(recipe, art_override=art_override, scale=scale)
    with open(out_path, "wb") as handle:
        handle.write(result["png"])
    return out_path
