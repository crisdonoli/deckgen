"""Compatibility for template asset paths saved under older asset layouts.

Older projects reference templates that have since been reorganized:
  - files carried their PSD layer index and hidden flag ("Background/001_W_[oculta].jpg"),
    now plain names ("Background/W.jpg"), see scripts/strip_asset_prefixes.py;
  - styles lived in "Automated Templates/<style>" or "Manual Templates/<style>",
    now all in "Templates/<style>", and a few styles were renamed (STYLE_ALIASES).
Saved paths and style keys are mapped to the current names when a project loads.
A mapping is only applied when the target exists, so this is safe either way.
"""
import os
import re
from typing import Any, Dict

from config import ASSETS_DIR, TEMPLATES_GROUP

_PREFIX_RE = re.compile(r"^\d+_(?=.)")
_HIDDEN_RE = re.compile(r"_\[oculta\]$", re.IGNORECASE)
_OLD_GROUPS = ("Automated Templates", "Manual Templates")
FRAME_PATH_KEYS = ("background", "pinlines", "name_box", "crown", "border", "pt_box")

# Old style folder name -> current one.
STYLE_ALIASES = {
    "pw": "planeswalker",
    "pw-extended": "planeswalker-extended",
    "lands-basic-classic": "lands-classic",
    "lands-basic-theros": "lands-theros",
    "lands-basic-unstable": "lands-unstable",
}


def clean_layer_stem(stem: str) -> str:
    """"001_W_[oculta]" -> "W" (old PSD-export naming -> current naming)."""
    return _HIDDEN_RE.sub("", _PREFIX_RE.sub("", stem))


def _exists(rel_path: str) -> bool:
    stem = os.path.splitext(os.path.join(ASSETS_DIR, rel_path))[0]
    return os.path.isfile(stem + ".jpg") or os.path.isfile(stem + ".pdf")


def _style_dir_exists(style: str) -> bool:
    return os.path.isdir(os.path.join(ASSETS_DIR, TEMPLATES_GROUP, style))


def _current_style(style: str) -> str:
    if _style_dir_exists(style):
        return style
    alias = STYLE_ALIASES.get(style)
    return alias if alias and _style_dir_exists(alias) else style


def migrate_style_key(style_key: str) -> str:
    """"Automated Templates/pw" -> "Templates/planeswalker" (unchanged if already current)."""
    if not isinstance(style_key, str) or not style_key:
        return style_key
    group, _, style = style_key.partition("/")
    if group not in _OLD_GROUPS + (TEMPLATES_GROUP,) or not style:
        return style_key
    new_key = f"{TEMPLATES_GROUP}/{_current_style(style)}"
    return new_key if _style_dir_exists(new_key.split("/", 1)[1]) else style_key


def migrate_rel_path(rel_path: str) -> str:
    """Return the current path of a template asset saved under an older layout.

    Leaves the path untouched when it still exists, or when no current file matches.
    """
    if not isinstance(rel_path, str) or not rel_path or _exists(rel_path):
        return rel_path
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) >= 3 and parts[0] in _OLD_GROUPS + (TEMPLATES_GROUP,):
        parts = [TEMPLATES_GROUP, _current_style(parts[1])] + parts[2:]
    stem, ext = os.path.splitext(parts[-1])
    parts[-1] = clean_layer_stem(stem) + ext
    candidate = "/".join(parts)
    return candidate if _exists(candidate) else rel_path


def migrate_card_frame_paths(card: Dict[str, Any]) -> None:
    fc = card.get("frame_components") if isinstance(card, dict) else None
    if not isinstance(fc, dict):
        return
    if fc.get("style"):
        fc["style"] = migrate_style_key(fc["style"])
    for key in FRAME_PATH_KEYS:
        if fc.get(key):
            fc[key] = migrate_rel_path(fc[key])
