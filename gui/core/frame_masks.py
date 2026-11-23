"""Resolve Card Conjurer component mask PNGs (title, type, rules, pinline, border) for frame decomposition.

This module scans ``assets/resources/frames/`` (or a supplied list of relative paths for testing)
and builds a compact directory-indexed mask catalog used by both the Card Builder frontend
(``/api/card-builder/symbols``) and the high-DPI backend renderer (``recipe_renderer.py``).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:
    from config import FRAMES_DIR
    from core.asset_paths import frame_url
except ImportError:
    from ..config import FRAMES_DIR
    from .asset_paths import frame_url

MASK_SLOTS = ("title", "type", "rules", "pinline", "border")

# Ordered inheritance rules: first matching prefix provides fallback mask directories.
# Only families that share exact Card Conjurer pixel geometry inherit from canonical masks;
# bespoke showcase frames (e.g., pipboy, wanted, snc/artDeco, old/abu) fall back to
# template-aware geometric rounded-rect masks so they never misalign.
FAMILY_INHERITANCE_RULES: List[Tuple[str, List[str]]] = [
    ("m15/new/extended", ["m15/new/extended", "m15/new", "m15/regular"]),
    ("m15/new", ["m15/new", "m15/regular"]),
    ("m15/transform/regular/new", ["m15/transform/regular/new", "m15/transform/regular", "m15/new", "m15/regular"]),
    ("m15/transform/regular", ["m15/transform/regular", "m15/new", "m15/regular"]),
    ("m15/transform", ["m15/transform/regular", "m15/new", "m15/regular"]),
    ("m15/battle", ["m15/battle"]),
    ("m15/commanderLegends", ["m15/commanderLegends", "m15/new", "m15/regular"]),
    ("m15/boxTopper/short", ["m15/boxTopper/short", "m15/new", "m15/regular"]),
    ("m15/equinox", ["m15/equinox", "m15/new", "m15/regular"]),
    ("m15/spree", ["m15/spree", "m15/new", "m15/regular"]),
    ("m15/praetors", ["m15/praetors", "m15/new", "m15/regular"]),
    ("m15/oilslick", ["m15/oilslick", "m15/new", "m15/regular"]),
    ("m15/zendikarRising", ["m15/zendikarRising"]),
    ("m15/genericShowcase", ["m15/genericShowcase", "m15/new", "m15/regular"]),
    ("m15/nickname", ["m15/nickname", "m15/new", "m15/regular"]),
    ("m15", ["m15/new", "m15/regular"]),
    ("doubleFeature", ["m15/new", "m15/regular"]),
    ("etched/regular", ["m15/new", "m15/regular"]),
    ("extended", ["m15/new/extended", "m15/new", "m15/regular"]),
    ("modal/short", ["modal/short", "modal", "m15/new", "m15/regular"]),
    ("modal", ["modal", "m15/new", "m15/regular"]),
    ("planeswalker/tall", ["planeswalker/tall", "planeswalker/regular", "planeswalker"]),
    ("planeswalker/compleated", ["planeswalker/compleated", "planeswalker"]),
    ("planeswalker", ["planeswalker/regular", "planeswalker"]),
    ("token/short", ["token/short", "m15/new", "m15/regular"]),
    ("token/textless", ["token/textless"]),
    ("token", ["token"]),
    ("saga/ub", ["saga/ub", "saga"]),
    ("saga", ["saga", "saga/ub"]),
    ("kaldheim/nonleg", ["kaldheim/nonleg", "kaldheim"]),
    ("kaldheim", ["kaldheim"]),
    ("8th", ["8th"]),
    ("custom/m15-eighth", ["8th"]),
    ("promo", ["promo", "m15/new", "m15/regular"]),
    ("crystal", ["crystal"]),
    ("lotr", ["lotr"]),
    ("mh2", ["mh2", "m15/new", "m15/regular"]),
    ("ravnica", ["ravnica"]),
    ("expedition/bfz", ["expedition/bfz"]),
    ("expedition/znr", ["expedition/znr"]),
    ("textless/2022", ["textless/2022"]),
    ("textless/zendikar", ["textless/zendikar"]),
    ("textless", ["textless"]),
]


def _classify_mask_file(rel_path: str) -> Optional[Tuple[str, int]]:
    """Return ``(slot, priority)`` (lower priority = preferred) if ``rel_path`` is a component mask."""
    p = rel_path.replace("\\", "/")
    p_low = p.lower()
    fname = os.path.basename(p_low)

    if not fname.endswith(".png"):
        return None
    # Skip non-component utility masks (halves, thirds, crowns, loyalty, pt, inner-only, bevels, margins)
    if any(skip in fname for skip in (
        "lefthalf", "righthalf", "middlethird", "maskright", "crown", "loyalty",
        "nooverlay", "reminder", "truename", "strokeless", "sliver", "hedrons",
        "defense", "bevel", "cutout", "ptcorners", "banner", "details", "titleless",
        "inner.png", "outer.png", "cover.png", "flavor", "invention.png",
    )):
        return None
    if "/margins/" in p_low or "/crowns/" in p_low or "/pt/" in p_low or "/holostamps/" in p_low:
        return None

    # --- Pinline masks (check before rules/type so *TextlessPinline* never matches rules/type) ---
    if fname in ("pinline.png", "maskpinline.png"):
        return ("pinline", 0)
    if "mask" in fname and "pinline" in fname:
        if "textless" in fname:
            return ("pinline", 4)
        if "super" in fname or "full" in fname:
            return ("pinline", 3)
        if "front" in fname:
            return ("pinline", 1)
        if "back" in fname or "right" in fname:
            return ("pinline", 4)
        return ("pinline", 1)

    # --- Border masks ---
    if fname in ("border.png", "maskborder.png"):
        return ("border", 0)
    if "mask" in fname and "border" in fname:
        if "back" in fname:
            return ("border", 4)
        return ("border", 1)

    # --- Title Box masks ---
    if fname in ("title.png", "masktitle.png", "sagamasktitle.png"):
        return ("title", 0)
    if "mask" in fname and "title" in fname:
        return ("title", 1)

    # --- Type Box masks ---
    if fname in ("type.png", "masktype.png"):
        return ("type", 0)
    if "mask" in fname and "type" in fname:
        if "textless" in fname:
            return ("type", 4)
        if "short" in fname:
            return ("type", 2)
        return ("type", 1)

    # --- Rules / Ability Textbox masks ---
    if fname in ("rules.png", "maskrules.png", "masktextbox.png", "masktext.png", "text.png"):
        return ("rules", 0)
    if "mask" in fname and "textless" not in fname and re.search(r"(rules|textbox|text(?!less))", fname):
        if "right" in fname or "back" in fname:
            return ("rules", 5)
        if "front" in fname:
            return ("rules", 1)
        if "short" in fname:
            return ("rules", 2)
        return ("rules", 1)

    return None


def _iter_disk_frame_files(frames_dir: Optional[str | Path] = None) -> Iterable[str]:
    base = Path(frames_dir or FRAMES_DIR)
    if not base.is_dir():
        return
    for root, _, files in os.walk(base):
        for fname in sorted(files):
            if fname.startswith(".") or not fname.lower().endswith(".png"):
                continue
            yield (Path(root) / fname).relative_to(base).as_posix()


def build_frame_masks_catalog(
    frames_dir: Optional[str | Path] = None,
    known_files: Optional[Iterable[str]] = None,
) -> Dict[str, object]:
    """Build a directory-indexed map of verified component masks and inheritance rules."""
    files = list(known_files) if known_files is not None else list(_iter_disk_frame_files(frames_dir))

    # best[dir_key][slot] = (priority, rel_path)
    best: Dict[str, Dict[str, Tuple[int, str]]] = {}
    for rel in files:
        classified = _classify_mask_file(rel)
        if not classified:
            continue
        slot, prio = classified
        dir_key = os.path.dirname(rel).replace("\\", "/")
        if not dir_key:
            continue
        slot_map = best.setdefault(dir_key, {})
        prev = slot_map.get(slot)
        if prev is None or prio < prev[0] or (prio == prev[0] and rel < prev[1]):
            slot_map[slot] = (prio, rel)

    by_dir: Dict[str, Dict[str, str]] = {}
    for dir_key, slot_map in sorted(best.items()):
        by_dir[dir_key] = {slot: frame_url(rel) for slot, (_, rel) in sorted(slot_map.items())}

    # Special sub-variants inside token/ (regular vs textless share the parent token/ directory)
    if "token" in by_dir:
        token_files = {os.path.basename(r).lower(): r for r in files if os.path.dirname(r).replace("\\", "/") == "token"}
        if "tokenmasktextlesstype.png" in token_files or "tokenmasktextlesspinline.png" in token_files:
            tl_map: Dict[str, str] = {}
            if "tokenmasktextlesstype.png" in token_files:
                tl_map["type"] = frame_url(token_files["tokenmasktextlesstype.png"])
            if "tokenmasktextlesspinline.png" in token_files:
                tl_map["pinline"] = frame_url(token_files["tokenmasktextlesspinline.png"])
            by_dir["token/textless"] = {**tl_map, **by_dir.get("token/textless", {})}
            by_dir["token/textless-borderless"] = {**tl_map, **by_dir.get("token/textless-borderless", {})}

    return {
        "by_dir": by_dir,
        "family_rules": [
            {"prefix": prefix, "inherit": inherit}
            for prefix, inherit in FAMILY_INHERITANCE_RULES
        ],
    }


def resolve_masks_for_frame(
    frame_rel_or_url: str,
    catalog: Optional[Dict[str, object]] = None,
) -> Dict[str, Optional[str]]:
    """Resolve ``{title, type, rules, pinline, border}`` mask URLs for a given frame path/URL."""
    cat = catalog if catalog is not None else build_frame_masks_catalog()
    by_dir: Dict[str, Dict[str, str]] = cat.get("by_dir") or {}  # type: ignore[assignment]
    rules = cat.get("family_rules") or []

    raw = str(frame_rel_or_url or "").strip()
    prefix = "/assets/resources/frames/"
    if prefix in raw:
        raw = raw.split(prefix, 1)[1]
    rel = raw.lstrip("/")
    dir_key = os.path.dirname(rel).replace("\\", "/")

    result: Dict[str, Optional[str]] = {slot: None for slot in MASK_SLOTS}
    if not dir_key:
        return result

    candidates: List[str] = [dir_key]
    parent = os.path.dirname(dir_key)
    if parent:
        # Don't let token/textless inherit regular token rules mask from parent 'token'
        if not (dir_key.lower().startswith("token/textless") and parent.lower() == "token"):
            candidates.append(parent)

    dir_low = dir_key.lower()
    for rule in rules:
        rp = str(rule.get("prefix") or "").lower()
        if dir_low == rp or dir_low.startswith(rp + "/"):
            for inh in rule.get("inherit") or []:
                if inh not in candidates:
                    candidates.append(inh)
            break

    for cand in candidates:
        slot_map = by_dir.get(cand)
        if not slot_map:
            continue
        for slot in MASK_SLOTS:
            if result[slot] is None and slot in slot_map:
                result[slot] = slot_map[slot]

    return result
