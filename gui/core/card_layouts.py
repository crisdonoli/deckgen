"""Card text/art layout: default positions and per-template layout loader from gui/data/frame_layouts.json."""
import json
from typing import Dict

from config import FRAME_LAYOUTS_PATH, STANDARD_CARD_H_PX, STANDARD_CARD_W_PX

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

_FRAME_LAYOUTS_CACHE: Dict[str, dict] = {}


def load_frame_layouts(path: str = None) -> dict:
    key = path or FRAME_LAYOUTS_PATH
    if key not in _FRAME_LAYOUTS_CACHE:
        with open(key, encoding="utf-8") as fh:
            _FRAME_LAYOUTS_CACHE[key] = json.load(fh)
    return _FRAME_LAYOUTS_CACHE[key]


def _scaled_default_layout() -> dict:
    art = DEFAULT_LAYOUT["art"]
    title = DEFAULT_LAYOUT["title"]
    type_line = DEFAULT_LAYOUT["type_line"]
    mana = DEFAULT_LAYOUT["mana_cost"]
    oracle = DEFAULT_LAYOUT["oracle_box"]
    symbol = DEFAULT_LAYOUT["set_symbol"]
    pt_text = DEFAULT_LAYOUT["pt_text"]
    return {
        "pack": None,
        "art_bounds": {"x": art["x"] * 2, "y": art["y"] * 2, "width": art["w"] * 2, "height": art["h"] * 2},
        "text_bounds": {
            "title": {"x": title["x"] * 2, "y": title["y"] * 2, "width": title["max_w"] * 2, "size": title["font_size"] * 2},
            "mana": {"x": mana["x"] * 2, "y": mana["y"] * 2, "size": mana["size"] * 2, "align": mana["align"]},
            "type": {"x": type_line["x"] * 2, "y": type_line["y"] * 2, "width": type_line["max_w"] * 2, "size": type_line["font_size"] * 2},
            "rules": {"x": oracle["x"] * 2, "y": oracle["y"] * 2, "width": oracle["w"] * 2, "height": oracle["h"] * 2, "size": oracle["font_size"] * 2},
            "pt": {"x": pt_text["x"] * 2, "y": pt_text["y"] * 2, "size": pt_text["font_size"] * 2},
        },
        "set_symbol_bounds": {"x": symbol["x"] * 2, "y": symbol["y"] * 2, "width": symbol["size"] * 2, "height": symbol["size"] * 2},
        "notes": ["fallback_default_layout"],
    }


def get_template_layout(name: str) -> dict:
    templates = load_frame_layouts()["templates"]
    if name in templates:
        return templates[name]
    return _scaled_default_layout()
