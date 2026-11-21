"""Card text/art layout: default positions and per-template-style overrides.

All coordinates are in the 750x1050 preview canvas space; the exporter scales
them to the export DPI.
"""
from typing import Dict

from config import STANDARD_CARD_H_PX, STANDARD_CARD_W_PX

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
    # Adventure spell (card["adventure"], only drawn for adventure cards): left page of the
    # Templates/adventure textbox. Title bar y 661-707, dark type bar 707-757, text below.
    "adventure_title": {"x": 60, "y": 694, "max_w": 240, "font_size": 28, "color": "#111111"},
    "adventure_mana_cost": {"x": 362, "y": 692, "size": 26, "align": "right"},
    "adventure_type_line": {"x": 60, "y": 742, "max_w": 290, "font_size": 25, "color": "#ffffff"},
    "adventure_oracle_box": {"x": 58, "y": 764, "w": 306, "h": 196, "font_size": 26, "color": "#111111"},
}

# Per-style layout overrides on top of DEFAULT_LAYOUT (750x1050 canvas coordinates).
# Only the listed fields change; any field overridden by some style is reset to its
# DEFAULT_LAYOUT value when switching to a style that doesn't override it.
# "art_below_frame" moves the art layer under the background (for full-art templates
# whose background is transparent except for the title/type bars).
#
# "art" boxes are the bounding box of each style's "Art Frame" layer
# ("Planeswalker Art Frame" / "Basic Art Frame" where that's the only one).
# Regenerate them with: python scripts/measure_art_frames.py
STYLE_LAYOUT_OVERRIDES: Dict[str, dict] = {
    "Templates/token": {
        # Frame layer (pinlines) on top, textbox Fade (background) over the art.
        "art_below_frame": True,
        "layout": {
            "art": {"x": 27, "y": 27, "w": 696, "h": 964},
            "title": {"x": 150, "y": 90},
            "type_line": {"y": 760},
            "set_symbol": {"y": 751},
            "oracle_box": {"y": 778, "h": 180},
        },
    },
    "Templates/token-textless": {  # no Art Frame layer: full card
        "art_below_frame": True,
        "layout": {
            "art": {"x": 0, "y": 0, "w": 750, "h": 1050},
            "type_line": {"y": 897},
            "set_symbol": {"y": 886},
            "oracle_box": {"hidden": True},
        },
    },
    "Templates/ixalan": {
        "art_below_frame": False,
        "layout": {
            "art": {"x": 26, "y": 111, "w": 698, "h": 482},
            "title": {"x": 100, "y": 90, "max_w": 490, "font_size": pt(9.0), "color": "#111111"},
            "type_line": {"x": 150, "y": 629, "max_w": 550, "font_size": pt(7.5), "color": "#111111"},
        },
    },
    "Templates/adventure": {
        "layout": {
            "art": {'x': 54, 'y': 117, 'w': 642, 'h': 467},  # Art Frame.pdf
            # Main card's rules text on the right page of the book; the left page is the adventure.
            "oracle_box": {"x": 390, "w": 303, "h": 300},
        },
    },
    "Templates/doublefaced-back": {"layout": {"art": {'x': 54, 'y': 117, 'w': 642, 'h': 467}}},  # Art Frame.pdf
    "Templates/doublefaced-front": {"layout": {"art": {'x': 54, 'y': 117, 'w': 642, 'h': 467}}},  # Art Frame.pdf
    # Templates/ikoria: no art frame layer
    "Templates/ixalan": {"layout": {"art": {'x': 26, 'y': 111, 'w': 698, 'h': 482}}},  # Art Frame.pdf
    "Templates/lands-basic": {"layout": {"art": {'x': 54, 'y': 117, 'w': 642, 'h': 467}}},  # Basic Art Frame.pdf
    "Templates/lands-classic": {"layout": {"art": {'x': 83, 'y': 101, 'w': 585, 'h': 469}}},  # Basic Art Frame.pdf
    "Templates/lands-theros": {"layout": {"art": {'x': 27, 'y': 28, 'w': 696, 'h': 939}}},  # Basic Art Frame.pdf
    "Templates/lands-unstable": {"layout": {"art": {'x': 0, 'y': 0, 'w': 750, 'h': 968}}},  # Basic Art Frame.pdf
    "Templates/lands-zendikar": {"layout": {"art": {'x': 26, 'y': 106, 'w': 698, 'h': 756}}},  # Art Frame.pdf
    "Templates/leveler": {"layout": {"art": {'x': 54, 'y': 117, 'w': 642, 'h': 467}}},  # Art Frame.pdf
    "Templates/manual-doublefaced-extended-back": {"layout": {"art": {'x': 51, 'y': 104, 'w': 648, 'h': 860}}},  # Planeswalker Art Frame.pdf
    "Templates/manual-doublefaced-extended-front": {"layout": {"art": {'x': 51, 'y': 104, 'w': 648, 'h': 860}}},  # Planeswalker Art Frame.pdf
    "Templates/masterpiece": {"layout": {"art": {'x': 27, 'y': 28, 'w': 696, 'h': 947}}},  # Art Frame.pdf
    "Templates/miracle": {"layout": {"art": {'x': 54, 'y': 117, 'w': 642, 'h': 467}}},  # Art Frame.pdf
    "Templates/mutate": {"layout": {"art": {'x': 42, 'y': 117, 'w': 666, 'h': 677}}},  # Art Frame.pdf
    "Templates/normal": {"layout": {"art": {'x': 54, 'y': 117, 'w': 642, 'h': 467}}},  # Art Frame.pdf
    "Templates/normal-classic": {"layout": {"art": {'x': 83, 'y': 101, 'w': 585, 'h': 469}}},  # Art Frame.pdf
    "Templates/normal-extended": {"layout": {"art": {'x': 0, 'y': 95, 'w': 750, 'h': 557}}},  # Art Frame.pdf
    "Templates/planar": {"layout": {"art": {'x': 39, 'y': 78, 'w': 672, 'h': 895}}},  # Art Frame.pdf
    "Templates/planeswalker": {"layout": {"art": {'x': 51, 'y': 104, 'w': 648, 'h': 860}}},  # Planeswalker Art Frame.pdf
    "Templates/planeswalker-extended": {"layout": {"art": {'x': 0, 'y': 0, 'w': 750, 'h': 1050}}},  # Planeswalker Art Frame.pdf
    "Templates/saga": {"layout": {"art": {'x': 376, 'y': 118, 'w': 320, 'h': 763}}},  # Art Frame.pdf
    "Templates/snow": {"layout": {"art": {'x': 54, 'y': 117, 'w': 642, 'h': 467}}},  # Art Frame.pdf
    "Templates/stargazing": {"layout": {"art": {'x': 42, 'y': 117, 'w': 666, 'h': 853}}},  # Art Frame.pdf
    "Templates/token": {"layout": {"art": {'x': 27, 'y': 27, 'w': 696, 'h': 964}}},  # Art Frame.pdf
    # Templates/token-textless: no art frame layer
    "Templates/transformers-back": {"layout": {"art": {'x': 54, 'y': 117, 'w': 642, 'h': 467}}},  # Art Frame.pdf
    "Templates/transformers-front": {"layout": {"art": {'x': 54, 'y': 117, 'w': 642, 'h': 467}}},  # Art Frame.pdf
    "Templates/universesbeyond": {"layout": {"art": {'x': 41, 'y': 117, 'w': 668, 'h': 854}}},  # Art Frame.pdf
    "Templates/womensday": {"layout": {"art": {'x': 0, 'y': 0, 'w': 750, 'h': 975}}},  # Art Frame.pdf
    # Templates/ikoria has no Art Frame layer: uses DEFAULT_LAYOUT["art"].
}

_LAYOUT_FIELD_FALLBACKS = {"hidden": False}


def style_layout_patch(style_key: str) -> dict:
    """Layout fields to apply when switching a card to `style_key` (overrides or defaults)."""
    style_layout = (STYLE_LAYOUT_OVERRIDES.get(style_key) or {}).get("layout", {})
    patch: Dict[str, dict] = {}
    for cfg in STYLE_LAYOUT_OVERRIDES.values():
        for key, fields in cfg.get("layout", {}).items():
            for field in fields:
                if field in style_layout.get(key, {}):
                    value = style_layout[key][field]
                else:
                    value = DEFAULT_LAYOUT.get(key, {}).get(field, _LAYOUT_FIELD_FALLBACKS.get(field))
                patch.setdefault(key, {})[field] = value
    return patch


def style_art_below_frame(style_key: str) -> bool:
    return bool((STYLE_LAYOUT_OVERRIDES.get(style_key) or {}).get("art_below_frame"))


def apply_style_layout(card: dict, style_key: str) -> None:
    layout = card.setdefault("layout", {})
    for key, fields in style_layout_patch(style_key).items():
        layout[key] = {**(layout.get(key) or {}), **fields}
    order = [k for k in (card.get("layer_order") or []) if k != "art"]
    if "background" in order:
        bg_idx = order.index("background")
        order.insert(bg_idx if style_art_below_frame(style_key) else bg_idx + 1, "art")
        card["layer_order"] = order


import json
from pathlib import Path

FRAME_LAYOUTS_PATH = str(Path(__file__).resolve().parents[1] / "data" / "frame_layouts.json")

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
