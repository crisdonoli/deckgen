import re

from config import MM_TO_INCH


def mm_to_px(mm, dpi):
    return int(round(mm / MM_TO_INCH * dpi))


def parse_bool(value):
    return value in ("true", "True", "1", "on")


def parse_hex(color):
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("color must be #RRGGBB")
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)
    return (r, g, b)


def pt_to_px(pt, dpi):
    return max(1, int(round(pt / 72.0 * dpi)))
