"""Card renderer module delegating recipe rendering and export helpers."""
import re
from typing import List, Tuple

from config import DEFAULT_EXPORT_DPI, MAX_EXPORT_DPI, MIN_EXPORT_DPI
from core.recipe_renderer import (  # noqa: F401
    draw_art,
    draw_layers,
    draw_mana,
    draw_rich_rules_box,
    draw_set_symbol,
    draw_text,
    render_recipe,
    save_recipe_png,
)


def clamp_export_dpi(raw_dpi: int) -> int:
    try:
        val = int(round(float(raw_dpi)))
    except (TypeError, ValueError):
        val = DEFAULT_EXPORT_DPI
    return max(MIN_EXPORT_DPI, min(MAX_EXPORT_DPI, val))


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
