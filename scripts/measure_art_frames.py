#!/usr/bin/env python3
"""Measure the art window of every template style from its "Art Frame" layer.

Each style folder has a reference layer ("Art Frame", "Planeswalker Art Frame" or
"Basic Art Frame") that is a solid shape where the artwork goes. This script
renders it at the 750x1050 canvas size, takes the bounding box of its opaque
pixels and prints "art" entries ready to paste into STYLE_LAYOUT_OVERRIDES
(gui/core/card_layouts.py).

"Full Art Frame" (the full-art variant) is ignored. A layer without any
transparency (e.g. pw-extended) means the art covers the whole card.

Usage:
    python scripts/measure_art_frames.py
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gui"))

from config import ASSETS_DIR  # noqa: E402
from core.card_renderer import STANDARD_CARD_H_PX, STANDARD_CARD_W_PX, render_pdf_layer_rgba  # noqa: E402

GROUPS = ("Templates",)
FRAME_NAMES = ("Art Frame", "Planeswalker Art Frame", "Basic Art Frame")


def find_frame(style_dir):
    for name in FRAME_NAMES:
        for ext in (".pdf", ".jpg"):
            path = os.path.join(style_dir, name + ext)
            if os.path.isfile(path):
                return path
    return None


def measure(path):
    rgba = np.asarray(render_pdf_layer_rgba(path, STANDARD_CARD_W_PX, STANDARD_CARD_H_PX))
    mask = rgba[:, :, 3] > 128
    if not mask.any() or mask.all():
        return {"x": 0, "y": 0, "w": STANDARD_CARD_W_PX, "h": STANDARD_CARD_H_PX}, 1.0
    ys, xs = np.where(mask)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    fill = float(mask[y0:y1 + 1, x0:x1 + 1].mean())
    return {"x": x0, "y": y0, "w": x1 - x0 + 1, "h": y1 - y0 + 1}, fill


def main():
    for group in GROUPS:
        group_dir = os.path.join(ASSETS_DIR, group)
        if not os.path.isdir(group_dir):
            continue
        for style in sorted(os.listdir(group_dir)):
            style_dir = os.path.join(group_dir, style)
            if not os.path.isdir(style_dir) or style == "WIP":
                continue
            frame = find_frame(style_dir)
            if not frame:
                print(f"    # {group}/{style}: no art frame layer")
                continue
            box, fill = measure(frame)
            note = "" if fill > 0.99 else f"  # not rectangular ({fill:.0%} of the box)"
            print(f'    "{group}/{style}": {{"layout": {{"art": {box}}}}},{note}  # {os.path.basename(frame)}')


if __name__ == "__main__":
    main()
