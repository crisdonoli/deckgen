"""Replay Canvas 2D calls recorded by the Card Builder (static/js/modules/canvas_recorder.js).

The browser decides every position and size (text is recorded with its final font, left x,
alphabetic baseline and measured width); this module only paints those calls with Pillow so
the exported PNG matches the preview. Shapes and text are rendered supersampled for
anti-aliasing, and canvas shadows are emulated with a Gaussian blur.
"""
import base64
import copy
import io
import math
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont

try:
    from .asset_paths import FRAMES_URL_PREFIX, SHARED_URL_PREFIX, frame_file_path, shared_file_path
    from .svg_raster import rasterize_svg
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from core.asset_paths import FRAMES_URL_PREFIX, SHARED_URL_PREFIX, frame_file_path, shared_file_path
    from core.svg_raster import rasterize_svg

_BASE_SUPERSAMPLE = 4
_supersample = _BASE_SUPERSAMPLE  # set per replay (see replay_canvas_ops)
_CURVE_STEPS = 24

# Mirrors the @font-face rules in templates/card_builder.html. Beleren is declared for every
# weight (the file is already Bold), so the browser never synthesises bold for it. MPlantin is
# declared normal-weight only, so a bold request is faux-bolded by the browser (see _faux_bold).
_FONT_FILES = {
    ("belerenlocal", False): "fonts/beleren-b.ttf",
    ("belerenlocal", True): "fonts/beleren-b.ttf",
    ("mplantinlocal", False): "fonts/mplantin.ttf",
    ("mplantinlocal", True): "fonts/mplantin-i.ttf",
}
_SYNTHETIC_BOLD_FAMILIES = {"mplantinlocal"}
_FONT_RE = re.compile(r"^(?P<pre>.*?)(?P<size>\d+(?:\.\d+)?)px(?:\s*/\s*\S+)?\s+(?P<families>.+)$")
_RGBA_RE = re.compile(r"^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$")
_FONT_CACHE = {}
_IMAGE_CACHE = {}


class _State:
    def __init__(self):
        self.fillStyle = "#000000"
        self.strokeStyle = "#000000"
        self.lineWidth = 1.0
        self.font = "10px sans-serif"
        self.textAlign = "start"
        self.textBaseline = "alphabetic"
        self.shadowColor = "rgba(0, 0, 0, 0)"
        self.shadowBlur = 0.0
        self.shadowOffsetX = 0.0
        self.shadowOffsetY = 0.0
        self.globalAlpha = 1.0
        self.globalCompositeOperation = "source-over"
        self.clip = None  # (x0, y0, x1, y1) in canvas px


def _parse_color(value, warnings):
    if not isinstance(value, str):
        warnings.append("canvas_style_unsupported")
        return (0, 0, 0, 0.0)
    raw = value.strip().lower()
    if raw in ("", "transparent"):
        return (0, 0, 0, 0.0)
    match = _RGBA_RE.match(raw)
    if match:
        r, g, b = (int(round(float(match.group(i)))) for i in (1, 2, 3))
        a = float(match.group(4)) if match.group(4) is not None else 1.0
        return (r, g, b, max(0.0, min(1.0, a)))
    try:
        rgb = ImageColor.getrgb(raw)
    except ValueError:
        warnings.append("canvas_color_unsupported:%s" % raw)
        return (0, 0, 0, 1.0)
    if len(rgb) == 4:
        return (rgb[0], rgb[1], rgb[2], rgb[3] / 255.0)
    return (rgb[0], rgb[1], rgb[2], 1.0)


def _parse_font(css_font: str):
    match = _FONT_RE.match(str(css_font or "").strip())
    if not match:
        return None
    pre = match.group("pre").lower().split()
    italic = "italic" in pre or "oblique" in pre
    weight = 400
    for token in pre:
        if token == "bold":
            weight = 700
        elif token.isdigit():
            weight = int(token)
    families = [f.strip().strip('"').strip("'").lower() for f in match.group("families").split(",")]
    return float(match.group("size")), weight, italic, families


def _faux_bold_stroke(size: float) -> int:
    """Skia's synthetic bold widens glyph outlines by size/24 (<=9px) to size/32 (>=36px)."""
    if size <= 9:
        ratio = 1 / 24.0
    elif size >= 36:
        ratio = 1 / 32.0
    else:
        t = (size - 9) / 27.0
        ratio = (1 / 24.0) + t * ((1 / 32.0) - (1 / 24.0))
    return int(round(_supersample * size * ratio / 2.0))


def _font_for(css_font: str, warnings: list):
    parsed = _parse_font(css_font)
    if parsed is None:
        warnings.append("canvas_font_unparsed:%s" % css_font)
        return None, 0, 10.0
    size, weight, italic, families = parsed
    for family in families:
        rel = _FONT_FILES.get((family, italic))
        if rel is None:
            continue
        path = shared_file_path(rel)
        if not path.is_file():
            continue
        key = (str(path), size, _supersample)
        font = _FONT_CACHE.get(key)
        if font is None:
            font = ImageFont.truetype(str(path), max(1, int(round(size * _supersample))))
            _FONT_CACHE[key] = font
        stroke = _faux_bold_stroke(size) if weight >= 600 and family in _SYNTHETIC_BOLD_FAMILIES else 0
        return font, stroke, size
    warnings.append("canvas_font_missing:%s" % css_font)
    return None, 0, size


def _resolve_image(src: str, target_px: int, warnings: list, local_path=None):
    raw = str(local_path or src or "")
    cache_key = (raw if not raw.startswith("data:") else hash(raw), target_px)
    if cache_key in _IMAGE_CACHE:
        return _IMAGE_CACHE[cache_key]
    img = None
    if raw.startswith("data:"):
        header, _, encoded = raw.partition(",")
        if header.startswith("data:image/") and encoded:
            try:
                img = Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGBA")
            except (ValueError, OSError):
                img = None
    else:
        path = urllib.parse.unquote(urllib.parse.urlsplit(raw).path)
        local = None
        if local_path:
            local = Path(local_path)
        elif path.startswith(FRAMES_URL_PREFIX):
            local = frame_file_path(path[len(FRAMES_URL_PREFIX):])
        elif path.startswith(SHARED_URL_PREFIX):
            local = shared_file_path(path[len(SHARED_URL_PREFIX):])
        if local is not None and Path(local).is_file():
            try:
                if Path(local).suffix.lower() == ".svg":
                    local = rasterize_svg(str(local), size=max(64, int(target_px)))
                with Image.open(local) as opened:
                    img = opened.convert("RGBA")
            except (OSError, ValueError, subprocess.CalledProcessError):
                img = None
    if img is None:
        warnings.append("canvas_image_missing:%s" % raw[:120])
    _IMAGE_CACHE[cache_key] = img
    return img


def _box_mask(size, box, origin):
    """L mask (canvas px, positioned at origin) that is 255 inside box."""
    mask = Image.new("L", size, 0)
    x0, y0, x1, y1 = box
    ox, oy = origin
    mask.paste(255, (int(math.floor(x0 - ox)), int(math.floor(y0 - oy)), int(math.ceil(x1 - ox)), int(math.ceil(y1 - oy))))
    return mask


def _composite(canvas: Image.Image, coverage: Image.Image, origin, color, state: _State, warnings: list, rgba_source=None):
    """Paint `color` (or `rgba_source`) through `coverage` at `origin`, with shadow, alpha and clip."""
    if state.globalCompositeOperation not in ("source-over", None):
        warnings.append("canvas_composite_unsupported:%s" % state.globalCompositeOperation)
    ox, oy = int(round(origin[0])), int(round(origin[1]))
    alpha_mul = max(0.0, min(1.0, float(state.globalAlpha)))
    if state.clip is not None:
        coverage = ImageChops.multiply(coverage, _box_mask(coverage.size, state.clip, (ox, oy)))
    if rgba_source is not None:
        layer = rgba_source.copy()
        layer.putalpha(ImageChops.multiply(layer.getchannel("A"), coverage))
    else:
        r, g, b, a = color
        layer = Image.new("RGBA", coverage.size, (r, g, b, 0))
        layer.putalpha(coverage.point(lambda v, k=a: int(round(v * k))))
    if alpha_mul < 1.0:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(round(v * alpha_mul))))

    sr, sg, sb, sa = _parse_color(state.shadowColor, warnings)
    blur = float(state.shadowBlur or 0)
    dx, dy = float(state.shadowOffsetX or 0), float(state.shadowOffsetY or 0)
    if sa > 0 and (blur > 0 or dx or dy):
        pad = int(math.ceil(blur * 1.5)) + 2
        shadow_alpha = Image.new("L", (layer.width + 2 * pad, layer.height + 2 * pad), 0)
        shadow_alpha.paste(layer.getchannel("A"), (pad, pad))
        if blur > 0:
            shadow_alpha = shadow_alpha.filter(ImageFilter.GaussianBlur(blur / 2.0))
        shadow = Image.new("RGBA", shadow_alpha.size, (sr, sg, sb, 0))
        shadow.putalpha(shadow_alpha.point(lambda v: int(round(v * sa))))
        _paste_rgba(canvas, shadow, (ox - pad + int(round(dx)), oy - pad + int(round(dy))))
    _paste_rgba(canvas, layer, (ox, oy))


def _paste_rgba(canvas: Image.Image, layer: Image.Image, pos):
    x, y = pos
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(canvas.width, x + layer.width), min(canvas.height, y + layer.height)
    if x1 <= x0 or y1 <= y0:
        return
    canvas.alpha_composite(layer.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


def _poly_coverage(subpaths, stroke_width=None):
    """Supersampled coverage mask for filled (or stroked) polylines. Returns (mask, origin)."""
    points = [pt for sub in subpaths for pt in sub]
    if not points:
        return None, None
    pad = (stroke_width or 0) / 2.0 + 2
    x0 = math.floor(min(p[0] for p in points) - pad)
    y0 = math.floor(min(p[1] for p in points) - pad)
    x1 = math.ceil(max(p[0] for p in points) + pad)
    y1 = math.ceil(max(p[1] for p in points) + pad)
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    big = Image.new("L", (w * _supersample, h * _supersample), 0)
    draw = ImageDraw.Draw(big)
    for sub in subpaths:
        scaled = [((px - x0) * _supersample, (py - y0) * _supersample) for px, py in sub]
        if stroke_width is None:
            if len(scaled) >= 3:
                draw.polygon(scaled, fill=255)
        elif len(scaled) >= 2:
            width = max(1, int(round(stroke_width * _supersample)))
            draw.line(scaled, fill=255, width=width, joint="curve")
    return big.resize((w, h), Image.LANCZOS), (x0, y0)


class _Path:
    def __init__(self):
        self.subpaths = []  # list of {"pts": [...], "closed": bool}

    def _current(self):
        return self.subpaths[-1]["pts"] if self.subpaths else None

    def move_to(self, x, y):
        self.subpaths.append({"pts": [(x, y)], "closed": False})

    def line_to(self, x, y):
        if not self.subpaths:
            self.move_to(x, y)
        else:
            self._current().append((x, y))

    def quad_to(self, cx, cy, x, y):
        cur = self._current()
        if not cur:
            self.move_to(cx, cy)
            cur = self._current()
        sx, sy = cur[-1]
        for i in range(1, _CURVE_STEPS + 1):
            t = i / float(_CURVE_STEPS)
            mt = 1 - t
            cur.append((mt * mt * sx + 2 * mt * t * cx + t * t * x, mt * mt * sy + 2 * mt * t * cy + t * t * y))

    def cubic_to(self, c1x, c1y, c2x, c2y, x, y):
        cur = self._current()
        if not cur:
            self.move_to(c1x, c1y)
            cur = self._current()
        sx, sy = cur[-1]
        for i in range(1, _CURVE_STEPS + 1):
            t = i / float(_CURVE_STEPS)
            mt = 1 - t
            cur.append((
                mt ** 3 * sx + 3 * mt * mt * t * c1x + 3 * mt * t * t * c2x + t ** 3 * x,
                mt ** 3 * sy + 3 * mt * mt * t * c1y + 3 * mt * t * t * c2y + t ** 3 * y,
            ))

    def ellipse(self, cx, cy, rx, ry, rotation, a0, a1, ccw=False):
        if ccw:
            if a0 - a1 >= 2 * math.pi:
                a1 = a0 - 2 * math.pi
            elif a1 > a0:
                a1 -= 2 * math.pi * math.ceil((a1 - a0) / (2 * math.pi))
        else:
            if a1 - a0 >= 2 * math.pi:
                a1 = a0 + 2 * math.pi
            elif a1 < a0:
                a1 += 2 * math.pi * math.ceil((a0 - a1) / (2 * math.pi))
        steps = max(8, int(abs(a1 - a0) / (2 * math.pi) * 96))
        cos_r, sin_r = math.cos(rotation), math.sin(rotation)
        pts = []
        for i in range(steps + 1):
            a = a0 + (a1 - a0) * i / float(steps)
            ex, ey = rx * math.cos(a), ry * math.sin(a)
            pts.append((cx + ex * cos_r - ey * sin_r, cy + ex * sin_r + ey * cos_r))
        if self.subpaths:
            self._current().extend(pts)
        else:
            self.subpaths.append({"pts": pts, "closed": False})

    def rect(self, x, y, w, h):
        self.subpaths.append({"pts": [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], "closed": True})
        self.move_to(x, y)

    def round_rect(self, x, y, w, h, radii):
        r = radii[0] if isinstance(radii, list) and radii else radii
        try:
            r = float(r or 0)
        except (TypeError, ValueError):
            r = 0.0
        r = max(0.0, min(r, abs(w) / 2.0, abs(h) / 2.0))
        if r <= 0:
            self.rect(x, y, w, h)
            return
        self.move_to(x + r, y)
        self.line_to(x + w - r, y)
        self.ellipse(x + w - r, y + r, r, r, 0, -math.pi / 2, 0)
        self.line_to(x + w, y + h - r)
        self.ellipse(x + w - r, y + h - r, r, r, 0, 0, math.pi / 2)
        self.line_to(x + r, y + h)
        self.ellipse(x + r, y + h - r, r, r, 0, math.pi / 2, math.pi)
        self.line_to(x, y + r)
        self.ellipse(x + r, y + r, r, r, 0, math.pi, 1.5 * math.pi)
        self.close()

    def close(self):
        if self.subpaths:
            sub = self.subpaths[-1]
            sub["closed"] = True
            first = sub["pts"][0]
            self.subpaths.append({"pts": [first], "closed": False})

    def polylines(self, for_stroke=False):
        out = []
        for sub in self.subpaths:
            pts = list(sub["pts"])
            if len(pts) < 2:
                continue
            if for_stroke and sub["closed"]:
                pts.append(pts[0])
            out.append(pts)
        return out

    def bbox(self):
        pts = [p for sub in self.subpaths for p in sub["pts"]]
        if not pts:
            return None
        return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))


def _draw_text(canvas, op, state, warnings):
    text = str(op.get("text") or "")
    if not text.strip():
        return
    font, stroke, size = _font_for(op.get("font") or state.font, warnings)
    if font is None:
        return
    ascent, descent = font.getmetrics()
    natural = font.getlength(text) / float(_supersample)
    pad = stroke + 4 * _supersample
    big_w = int(math.ceil(font.getlength(text))) + 2 * pad
    big_h = ascent + descent + 2 * pad
    big = Image.new("L", (big_w, big_h), 0)
    ImageDraw.Draw(big).text((pad, pad + ascent), text, font=font, fill=255, anchor="ls", stroke_width=stroke, stroke_fill=255)
    # Match the width the browser measured (kerning/hinting differ slightly between engines,
    # and fillText's maxWidth condenses text horizontally).
    target_w = float(op.get("width") or natural)
    scale_x = target_w / natural if natural > 0 else 1.0
    scale_x = max(0.4, min(2.5, scale_x))
    out_w = max(1, int(round(big_w / float(_supersample) * scale_x)))
    out_h = max(1, int(round(big_h / float(_supersample))))
    coverage = big.resize((out_w, out_h), Image.LANCZOS)
    origin_x = float(op.get("x") or 0) - (pad / float(_supersample)) * scale_x
    origin_y = float(op.get("y") or 0) - (pad + ascent) / float(_supersample)
    _composite(canvas, coverage, (origin_x, origin_y), _parse_color(state.fillStyle, warnings), state, warnings)


def _draw_image(canvas, op, state, warnings):
    args = [float(a) for a in (op.get("args") or []) if isinstance(a, (int, float))]
    if len(args) == 2:
        dx, dy, dw, dh, src_box = args[0], args[1], None, None, None
    elif len(args) == 4:
        dx, dy, dw, dh, src_box = args[0], args[1], args[2], args[3], None
    elif len(args) == 8:
        src_box = args[0:4]
        dx, dy, dw, dh = args[4:8]
    else:
        warnings.append("canvas_drawimage_args")
        return
    target_px = int(max(dw or 0, dh or 0) * 2) if dw else 256
    img = _resolve_image(op.get("src"), target_px, warnings, op.get("local_path"))
    if img is None:
        return
    if src_box is not None:
        sx, sy, sw, sh = src_box
        img = img.crop((int(round(sx)), int(round(sy)), int(round(sx + sw)), int(round(sy + sh))))
    if dw is None:
        dw, dh = img.width, img.height
    out = img.resize((max(1, int(round(dw))), max(1, int(round(dh)))), Image.LANCZOS)
    _composite(canvas, Image.new("L", out.size, 255), (dx, dy), None, state, warnings, rgba_source=out)


_FONT_PX_RE = re.compile(r"(\d+(?:\.\d+)?)px")
_SCALED_STATE = ("lineWidth", "shadowBlur", "shadowOffsetX", "shadowOffsetY")


def _scale_font(css_font, s: float):
    if not isinstance(css_font, str):
        return css_font
    return _FONT_PX_RE.sub(lambda m: "%gpx" % (float(m.group(1)) * s), css_font, count=1)


def _scaled_op(op: dict, s: float) -> dict:
    """The same call on a canvas `s` times larger: coordinates, sizes, line widths, shadow
    blur/offsets and font sizes scale; angles and source-image crop rectangles do not."""
    if s == 1.0:
        return op
    name = op.get("op")
    args = op.get("args") or []
    num = lambda v: v * s if isinstance(v, (int, float)) and not isinstance(v, bool) else v  # noqa: E731
    out = dict(op)
    if name in ("moveTo", "lineTo", "quadraticCurveTo", "bezierCurveTo", "rect", "fillRect", "strokeRect"):
        out["args"] = [num(a) for a in args]
    elif name == "arc":
        out["args"] = [num(a) for a in args[:3]] + list(args[3:])
    elif name == "ellipse":
        out["args"] = [num(a) for a in args[:4]] + list(args[4:])
    elif name == "roundRect":
        radii = args[4] if len(args) > 4 else 0
        radii = [num(r) for r in radii] if isinstance(radii, list) else num(radii)
        out["args"] = [num(a) for a in args[:4]] + [radii]
    elif name == "drawImage":
        if len(args) == 8:
            out["args"] = list(args[:4]) + [num(a) for a in args[4:]]
        else:
            out["args"] = [num(a) for a in args]
    elif name == "set":
        if op.get("k") in _SCALED_STATE:
            out["v"] = num(op.get("v"))
        elif op.get("k") == "font":
            out["v"] = _scale_font(op.get("v"), s)
    elif name == "text":
        out["x"], out["y"], out["width"] = num(op.get("x") or 0), num(op.get("y") or 0), num(op.get("width") or 0)
        out["font"] = _scale_font(op.get("font"), s)
    return out


def replay_canvas_ops(canvas: Image.Image, ops: list, warnings: list, scale: float = 1.0) -> int:
    """Replay recorded calls. `scale` maps the recording canvas onto this one (export DPI)."""
    global _supersample
    scale = float(scale or 1.0)
    # Supersampling only smooths sub-pixel geometry; at 2x/4x the card is already large.
    _supersample = max(1, int(round(_BASE_SUPERSAMPLE / max(1.0, scale))))
    ops = [_scaled_op(op, scale) for op in (ops or []) if isinstance(op, dict)]
    state = _State()
    stack = []
    path = _Path()
    drawn = 0
    for op in ops or []:
        if not isinstance(op, dict):
            continue
        name = op.get("op")
        args = op.get("args") or []
        try:
            if name == "set":
                key = op.get("k")
                if hasattr(state, key) and key != "clip":
                    setattr(state, key, op.get("v"))
            elif name == "save":
                stack.append(copy.copy(state))
            elif name == "restore":
                if stack:
                    state = stack.pop()
            elif name == "beginPath":
                path = _Path()
            elif name == "moveTo":
                path.move_to(float(args[0]), float(args[1]))
            elif name == "lineTo":
                path.line_to(float(args[0]), float(args[1]))
            elif name == "quadraticCurveTo":
                path.quad_to(*[float(a) for a in args[:4]])
            elif name == "bezierCurveTo":
                path.cubic_to(*[float(a) for a in args[:6]])
            elif name == "arc":
                x, y, r, a0, a1 = [float(a) for a in args[:5]]
                path.ellipse(x, y, r, r, 0.0, a0, a1, bool(args[5]) if len(args) > 5 else False)
            elif name == "ellipse":
                x, y, rx, ry, rot, a0, a1 = [float(a) for a in args[:7]]
                path.ellipse(x, y, rx, ry, rot, a0, a1, bool(args[7]) if len(args) > 7 else False)
            elif name == "rect":
                path.rect(*[float(a) for a in args[:4]])
            elif name == "roundRect":
                path.round_rect(float(args[0]), float(args[1]), float(args[2]), float(args[3]), args[4] if len(args) > 4 else 0)
            elif name == "closePath":
                path.close()
            elif name == "fill":
                coverage, origin = _poly_coverage(path.polylines())
                if coverage is not None:
                    _composite(canvas, coverage, origin, _parse_color(state.fillStyle, warnings), state, warnings)
                    drawn += 1
            elif name == "stroke":
                coverage, origin = _poly_coverage(path.polylines(for_stroke=True), stroke_width=float(state.lineWidth or 1))
                if coverage is not None:
                    _composite(canvas, coverage, origin, _parse_color(state.strokeStyle, warnings), state, warnings)
                    drawn += 1
            elif name == "clip":
                box = path.bbox()
                if box is not None:
                    if state.clip is not None:
                        c = state.clip
                        box = (max(box[0], c[0]), max(box[1], c[1]), min(box[2], c[2]), min(box[3], c[3]))
                    state.clip = box
            elif name == "fillRect":
                x, y, w, h = [float(a) for a in args[:4]]
                rect = _Path()
                rect.rect(x, y, w, h)
                coverage, origin = _poly_coverage(rect.polylines())
                if coverage is not None:
                    _composite(canvas, coverage, origin, _parse_color(state.fillStyle, warnings), state, warnings)
                    drawn += 1
            elif name == "text":
                _draw_text(canvas, op, state, warnings)
                drawn += 1
            elif name == "drawImage":
                _draw_image(canvas, op, state, warnings)
                drawn += 1
            elif name in ("translate", "rotate", "scale", "setTransform", "resetTransform", "strokeRect"):
                warnings.append("canvas_op_unsupported:%s" % name)
        except (TypeError, ValueError, IndexError) as exc:
            warnings.append("canvas_op_failed:%s:%s" % (name, exc.__class__.__name__))
    return drawn
