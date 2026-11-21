"""Extract per-template layout metrics from CardConjurer frame packs into gui/data/frame_layouts.json."""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAMES_DIR = ROOT / "assets/cardconjurer/js/frames"
OUT_PATH = ROOT / "gui/data/frame_layouts.json"

CANVAS_W, CANVAS_H = 1500, 2100
SOURCE_W, SOURCE_H = 2010, 2814

TEMPLATE_PACKS = {
    "M15Regular": "packM15RegularNew",
    "M15Extended": "packM15ExtendedArtNew",
    "M15Borderless": "packBorderless",
    "PlaneswalkerRegular": "packPlaneswalkerRegular",
    "PlaneswalkerTall": "packPlaneswalkerTall",
    "SagaRegular": "packSagaRegular",
    "Class": "packClass",
    "ModalRegular": "packModalRegular",
    "ModalShort": "packModalShort",
    "TransformRegular": "packM15TransformFront",
    "Split": "packSplit",
    "Battle": "packBattle",
    "Adventure": "packAdventure",
    "TokenRegular": "packTokenRegular-1",
    "TokenTextless": "packTokenTextless-1",
    "Seventh": "packSeventh",
    "Eighth": "pack8th",
    "Future": "packFutureRegular",
}

TEXT_KEYS = ("title", "mana", "type", "rules", "pt", "loyalty", "defense")
KEEP_FIELDS = ("size", "font", "align", "oneLine", "color")
BOUND_KEYS = ("x", "y", "width", "height")

ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Call, ast.Name, ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd, ast.Mod, ast.Pow,
)
EVAL_ENV = {"getStandardWidth": lambda: SOURCE_W, "getStandardHeight": lambda: SOURCE_H}


def strip_comments(text):
    out = []
    i, n = 0, len(text)
    quote = None
    while i < n:
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
        elif ch in "'\"`":
            quote = ch
            out.append(ch)
            i += 1
        elif ch == "/" and text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif ch == "/" and text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def slice_block(text, start):
    depth = 0
    quote = None
    i = start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return text[start:]


def split_top(s, sep=","):
    parts, buf, depth, quote, i = [], [], 0, None, 0
    while i < len(s):
        ch = s[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < len(s):
                buf.append(s[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
            buf.append(ch)
        elif ch in "{([":
            depth += 1
            buf.append(ch)
        elif ch in "})]":
            depth -= 1
            buf.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if "".join(buf).strip():
        parts.append("".join(buf))
    return parts


def eval_expr(s):
    s = s.strip()
    if not s:
        return None
    try:
        tree = ast.parse(s, mode="eval")
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            return None
        if isinstance(node, ast.Name) and node.id not in EVAL_ENV:
            return None
        if isinstance(node, ast.Call) and not isinstance(node.func, ast.Name):
            return None
    try:
        return eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, EVAL_ENV)
    except Exception:
        return None


def parse_value(s):
    s = s.strip()
    if not s:
        return None
    if s[0] in "{[":
        return parse_literal(s)
    if s[0] in "'\"`" and s[-1] == s[0]:
        return s[1:-1]
    if s in ("true", "false"):
        return s == "true"
    if s == "null":
        return None
    value = eval_expr(s)
    return s if value is None else value


def parse_literal(s):
    """Parse a JS object/array literal into python (arith values evaluated)."""
    s = s.strip()
    if not s:
        return None
    if s[0] == "{":
        body = s[1:s.rindex("}")]
        out = {}
        for part in split_top(body):
            pair = part.split(":", 1)
            if len(pair) != 2:
                continue
            key = pair[0].strip().strip("'\"`")
            out[key] = parse_value(pair[1])
        return out
    if s[0] == "[":
        body = s[1:s.rindex("]")]
        return [parse_value(p) for p in split_top(body)]
    return parse_value(s)


def take_statement(text, start):
    if text[start] == "{":
        return slice_block(text, start)
    depth, quote, i = 0, None, start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
        elif ch in "{([":
            depth += 1
        elif ch in "})]":
            depth -= 1
        elif ch == ";" and depth == 0:
            return text[start:i]
        i += 1
    return text[start:]


def resolve_var(text, name):
    m = re.search(r"\b(?:var|let|const)\s+" + re.escape(name) + r"\s*=", text)
    if not m:
        return None
    return take_statement(text, m.end())


def extract_prop(text, prop):
    m = re.search(r"(?:card\.)?" + prop + r"\s*=(?!=)\s*", text)
    if not m:
        return None
    rhs = take_statement(text, m.end()).strip()
    if re.fullmatch(r"[A-Za-z_$][\w$]*", rhs):
        rhs = resolve_var(text, rhs)
        if rhs is None:
            return None
    return parse_literal(rhs)


def extract_call_object(text, call):
    m = re.search(r"\b" + call + r"\s*\(", text)
    if not m:
        return None
    i = m.end()
    while i < len(text) and text[i] != "{":
        if text[i] in ");":
            return None
        i += 1
    return parse_literal(slice_block(text, i))


def scale_box(box):
    if not box:
        return None
    out = {}
    for key in BOUND_KEYS:
        if key in box and isinstance(box[key], (int, float)):
            axis = CANVAS_W if key in ("x", "width") else CANVAS_H
            out[key] = int(round(box[key] * axis))
    return out or None


def scale_text_entry(entry):
    if not isinstance(entry, dict):
        return None
    out = scale_box(entry) or {}
    if isinstance(entry.get("size"), (int, float)):
        out["size"] = int(round(entry["size"] * CANVAS_H))
    for field in KEEP_FIELDS:
        if field in entry and field != "size":
            out[field] = entry[field]
    return out


def in_canvas(box):
    # anchor point must be on canvas; BoxBlur-style boxes may overflow the right/bottom edge
    # because CardConjurer anchors them by 'vertical'/'horizontal' alignment.
    return (
        box is not None
        and 0 <= box.get("x", -1) <= CANVAS_W
        and 0 <= box.get("y", -1) <= CANVAS_H
        and box.get("width", 0) > 0
        and box.get("height", 0) > 0
    )


def extract_pack(pack_name):
    path = FRAMES_DIR / (pack_name + ".js")
    text = strip_comments(path.read_text(encoding="utf-8"))
    notes = []
    if re.search(r"\[\s*2814\s*,\s*2010", text) or re.search(r"canvas\s*:\s*\[\s*2814\s*,\s*2010", text):
        notes.append("rotated_canvas")

    art_bounds = scale_box(extract_prop(text, "artBounds"))
    symbol_box = extract_prop(text, "setSymbolBounds")
    symbol_bounds = scale_box(symbol_box)
    if symbol_bounds and not in_canvas(symbol_bounds):
        notes.append("set_symbol_offcanvas")
        symbol_bounds = {key: symbol_box[key] for key in ("x", "y") if key in symbol_box}
        symbol_bounds.update(width=0, height=0)

    text_options = extract_call_object(text, "loadTextOptions") or {}
    text_bounds = {}
    for key in TEXT_KEYS:
        if key in text_options:
            scaled = scale_text_entry(text_options[key])
            if scaled:
                text_bounds[key] = scaled

    bottom = extract_call_object(text, "loadBottomInfo") or {}
    if isinstance(bottom.get("bottom"), dict):
        scaled = scale_text_entry(bottom["bottom"])
        if scaled:
            text_bounds["collector_info"] = scaled
            notes.append("collector_info")

    for key in ("artBounds", "setSymbolBounds"):
        if key not in text:
            notes.append(key[0].lower() + key[1:] + "_missing")
    if not text_options:
        notes.append("text_options_missing")

    return {
        "pack": pack_name + ".js",
        "art_bounds": art_bounds,
        "text_bounds": text_bounds,
        "set_symbol_bounds": symbol_bounds,
        "notes": notes,
    }


def main():
    templates, unmapped = {}, []
    packs = {p.stem for p in FRAMES_DIR.glob("pack*.js")}
    for template, pack in TEMPLATE_PACKS.items():
        if not (FRAMES_DIR / (pack + ".js")).exists():
            raise SystemExit("missing pack for %s: %s" % (template, pack))
        templates[template] = extract_pack(pack)
        packs.discard(pack)
    unmapped = sorted(packs)

    doc = {
        "meta": {
            "canvas": {"w": CANVAS_W, "h": CANVAS_H},
            "source": "assets/cardconjurer/js/frames/pack*.js",
            "canvas_source": "%dx%d" % (SOURCE_W, SOURCE_H),
            "templates_total": len(templates),
            "templates_mapped": len(templates),
            "font_scale": "px=size*2100",
        },
        "templates": templates,
        "unmapped": unmapped,
    }
    OUT_PATH.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print("wrote %s templates=%d unmapped=%d" % (OUT_PATH, len(templates), len(unmapped)))


if __name__ == "__main__":
    main()
