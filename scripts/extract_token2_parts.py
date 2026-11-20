#!/usr/bin/env python3
"""
Separates assets/Token-2.psd into individual standalone component types:
  - Border/          (Black Borders only)
  - Name Box/        (Title Box only, per color)
  - Pinlines/        (Type Box only, Text Box only, and Full Frame, per color)
  - PT Box/          (P/T Box only, per color)

All outputs are 1500x2100 RGBA PNGs in exact 5:7 card coordinates (144px MPC bleed cropped),
ready to be mixed, moved, cropped, or deleted independently in Card Builder.
"""

import os
from PIL import Image
from psd_tools import PSDImage

PSD_PATH = "assets/Token-2.psd"
OUT_ROOT = "assets/Automated Templates/token-2"

BLEED_BOX = (144, 144, 3144, 4344)
TARGET_SIZE = (1500, 2100)

# Vertical split points in 1500x2100 space for separating Name Box, Type Box, and Text Box
TITLE_MAX_Y = 250       # Top title bar region (y: 0..250)
TYPE_MIN_Y = 1420       # Type bar region (y: 1420..1585)
TYPE_MAX_Y = 1585
TEXTBOX_MIN_Y = 1575    # Rules textbox region (y: 1575..1935)
TEXTBOX_MAX_Y = 1935

COLOR_VARIANTS = [
    ("01_W", "White", "White"),
    ("02_U", "Blue", "Blue"),
    ("03_B", "Black", "Black/Gray"),
    ("04_R", "Red", "Red"),
    ("05_G", "Green", "Green"),
    ("06_Gold", "Gold", "Gold"),
    ("07_Artifact", "Gray", "Black/Gray"),
    ("08_Purple", "Purple", "Purple"),
]

TOP_HIDE = {"Background", "ART GOES HERE", "Set Symbol Common", "Footer", "Text", "ART EXTENSION"}


def find_child(group, name):
    for layer in group:
        if layer.name == name:
            return layer
    raise KeyError(f"Layer not found: {name}")


def crop_bleed(img: Image.Image) -> Image.Image:
    return img.crop(BLEED_BOX).resize(TARGET_SIZE, Image.LANCZOS)


def keep_y_band(rgba: Image.Image, y0: int, y1: int) -> Image.Image:
    out = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    band = rgba.crop((0, y0, rgba.width, y1))
    out.paste(band, (0, y0))
    return out


def set_color_variant(color_grp, tint_grp, color_name, tint_name):
    for lyr in color_grp:
        lyr.visible = (lyr.name == color_name)
    tint_names = {"Green", "Blue", "White", "Red", "Black/Gray", "Purple", "Gold"}
    for lyr in tint_grp:
        if lyr.name in tint_names:
            lyr.visible = (lyr.name == tint_name)


def main():
    border_dir = os.path.join(OUT_ROOT, "Border")
    name_dir = os.path.join(OUT_ROOT, "Name Box")
    pin_dir = os.path.join(OUT_ROOT, "Pinlines")
    pt_dir = os.path.join(OUT_ROOT, "PT Box")
    for d in (border_dir, name_dir, pin_dir, pt_dir):
        os.makedirs(d, exist_ok=True)

    print(f"Opening {PSD_PATH}...")
    psd = PSDImage.open(PSD_PATH)
    for layer in psd:
        if layer.name in TOP_HIDE:
            layer.visible = False

    black_borders = find_child(psd, "Black Borders")
    drop_shadow_grp = find_child(psd, "Box Drop Shadow")
    color_grp = find_child(psd, "COLOR")
    box_outlines = find_child(psd, "Box Outlines")
    color_tint = find_child(psd, "COLOR TINT")

    ds_with_pt = find_child(drop_shadow_grp, "Drop Shadow")
    ds_no_pt = find_child(drop_shadow_grp, "Drop Shadow (no PT)")
    boxes_grp = find_child(color_tint, "Boxes")
    text_box_copy = find_child(boxes_grp, "Text Box copy")
    name_type_pt_grp = find_child(boxes_grp, "Name/Type/PT Boxes")
    pt_box_layer = find_child(name_type_pt_grp, "P/T Box")
    name_type_copy = find_child(name_type_pt_grp, "Name/Type Boxes copy")
    black_title_box = find_child(color_tint, "BLACK TITLE BOX")

    # 1. Standalone Black Border
    border_out = os.path.join(border_dir, "01_Black_Border.png")
    black_borders.visible = True
    drop_shadow_grp.visible = False
    color_grp.visible = False
    box_outlines.visible = False
    color_tint.visible = False
    b_img = crop_bleed(psd.composite(force=True))
    # Seal bottom-right PT cutout so border is complete
    box = (1048, 1913, 1417, 2030)
    patch = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), (0, 0, 0, 255))
    patch.alpha_composite(b_img.crop(box))
    b_img.paste(patch, (box[0], box[1]))
    b_img.save(border_out, format="PNG", optimize=True)
    del b_img
    print("  [ok] Border/01_Black_Border.png")

    # 2. Per-color standalone Name Box, Type Box, and Text Box (without Black Borders)
    black_borders.visible = False
    drop_shadow_grp.visible = True
    ds_with_pt.visible = False
    ds_no_pt.visible = True
    color_grp.visible = True
    box_outlines.visible = True
    color_tint.visible = True
    text_box_copy.visible = True
    name_type_copy.visible = True
    black_title_box.visible = True
    pt_box_layer.visible = False

    for code, c_name, t_name in COLOR_VARIANTS:
        set_color_variant(color_grp, color_tint, c_name, t_name)
        noborder = crop_bleed(psd.composite(force=True))

        # Title / Name Box only
        title_only = keep_y_band(noborder, 0, TITLE_MAX_Y)
        title_only.save(os.path.join(name_dir, f"{code}_Title_Box.png"), format="PNG", optimize=True)

        # Type Box only
        type_only = keep_y_band(noborder, TYPE_MIN_Y, TYPE_MAX_Y)
        type_only.save(os.path.join(pin_dir, f"{code}_Type_Box.png"), format="PNG", optimize=True)

        # Text Box only
        text_only = keep_y_band(noborder, TEXTBOX_MIN_Y, TEXTBOX_MAX_Y)
        text_only.save(os.path.join(pin_dir, f"{code}_Text_Box.png"), format="PNG", optimize=True)

        del noborder, title_only, type_only, text_only
        print(f"  [ok] {code}: Title Box, Type Box, Text Box")

    print("Done extracting separated components from Token-2.psd!")


if __name__ == "__main__":
    main()
