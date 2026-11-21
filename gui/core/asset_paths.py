"""Compatibility for template asset paths saved before the file names were cleaned up.

Template files used to carry their PSD layer index and hidden flag
("Background/001_W_[oculta].jpg"). They are now plain names ("Background/W.jpg"),
see scripts/strip_asset_prefixes.py.
Projects saved earlier still reference the old names, so map them on load.
"""
import os
import re
from typing import Any, Dict

from config import ASSETS_DIR

_PREFIX_RE = re.compile(r"^\d+_(?=.)")
_HIDDEN_RE = re.compile(r"_\[oculta\]$", re.IGNORECASE)
FRAME_PATH_KEYS = ("background", "pinlines", "name_box", "crown", "border", "pt_box")


def clean_layer_stem(stem: str) -> str:
    """"001_W_[oculta]" -> "W" (old PSD-export naming -> current naming)."""
    return _HIDDEN_RE.sub("", _PREFIX_RE.sub("", stem))


def _exists(rel_path: str) -> bool:
    stem = os.path.splitext(os.path.join(ASSETS_DIR, rel_path))[0]
    return os.path.isfile(stem + ".jpg") or os.path.isfile(stem + ".pdf")


def migrate_rel_path(rel_path: str) -> str:
    """Return the current name of a template asset, dropping the obsolete "NNN_"
    prefix and "_[oculta]" suffix.

    Leaves the path untouched when it still exists (assets not renamed yet) or
    when the cleaned-up file doesn't exist either.
    """
    if not isinstance(rel_path, str) or not rel_path:
        return rel_path
    folder, name = os.path.split(rel_path)
    stem, ext = os.path.splitext(name)
    new_name = clean_layer_stem(stem) + ext
    if new_name == name or _exists(rel_path):
        return rel_path
    candidate = f"{folder}/{new_name}" if folder else new_name
    return candidate if _exists(candidate) else rel_path


def migrate_card_frame_paths(card: Dict[str, Any]) -> None:
    fc = card.get("frame_components") if isinstance(card, dict) else None
    if not isinstance(fc, dict):
        return
    for key in FRAME_PATH_KEYS:
        if fc.get(key):
            fc[key] = migrate_rel_path(fc[key])
