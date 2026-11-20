#!/usr/bin/env python3
"""
Extracts high-resolution RGBA PNG frame layers from assets/Token-2.psd
into assets/Automated Templates/token-2/ (Pinlines + PT Box) for Card Builder.
"""

import os
from PIL import Image
from psd_tools import PSDImage

PSD_PATH = "assets/Token-2.psd"
OUT_ROOT = "assets/Automated Templates/token-2"
PINLINES_DIR = os.path.join(OUT_ROOT, "Pinlines")
PT_DIR = os.path.join(OUT_ROOT, "PT Box")

# Crop 144px MPC bleed (3288x4488 -> 3000x4200) and scale to 1500x2100 (600 DPI 5:7)
BLEED_BOX = (144, 144, 3144, 4344)
TARGET_SIZE = (1500, 2100)

# (output_filename, COLOR_layer_name, COLOR_TINT_layer_name)
COLOR_VARIANTS = [
    ("01_W.png", "White", "White"),
    ("02_U.png", "Blue", "Blue"),
    ("03_B.png", "Black", "Black/Gray"),
    ("04_R.png", "Red", "Red"),
    ("05_G.png", "Green", "Green"),
    ("06_Gold.png", "Gold", "Gold"),
    ("07_Artifact.png", "Gray", "Black/Gray"),
    ("08_Colourless.png", "Gray", "Black/Gray"),
    ("09_Purple.png", "Purple", "Purple"),
]

TOP_HIDE = {"Background", "ART GOES HERE", "Set Symbol Common", "Footer", "Text", "ART EXTENSION"}


def find_child(group, name):
    for layer in group:
        if layer.name == name:
            return layer
    raise KeyError(f"Layer not found: {name}")


def set_color_variant(color_grp, tint_grp, color_name, tint_name):
    for lyr in color_grp:
        lyr.visible = (lyr.name == color_name)
    tint_names = {"Green", "Blue", "White", "Red", "Black/Gray", "Purple", "Gold"}
    for lyr in tint_grp:
        if lyr.name in tint_names:
            lyr.visible = (lyr.name == tint_name)


def save_cropped_rgba(img: Image.Image, out_path: str, seal_pt_cutout: bool = False):
    cropped = img.crop(BLEED_BOX).resize(TARGET_SIZE, Image.LANCZOS)
    if seal_pt_cutout:
        # Seal the PT-box mask cutout in the bottom-right black border so non-creature tokens have no hole
        box = (1048, 1913, 1417, 2030)
        patch = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), (0, 0, 0, 255))
        patch.alpha_composite(cropped.crop(box))
        cropped.paste(patch, (box[0], box[1]))
    cropped.save(out_path, format="PNG", optimize=True)


def main():
    os.makedirs(PINLINES_DIR, exist_ok=True)
    os.makedirs(PT_DIR, exist_ok=True)

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

    # Cache Gray/Black/Gray so Colourless reuses Artifact without recompositing
    cached_pin = {}
    cached_pt = {}

    for fname, c_name, t_name in COLOR_VARIANTS:
        key = (c_name, t_name)
        pin_out = os.path.join(PINLINES_DIR, fname)
        pt_out = os.path.join(PT_DIR, fname)

        if key in cached_pin:
            with open(cached_pin[key], "rb") as src, open(pin_out, "wb") as dst:
                dst.write(src.read())
            with open(cached_pt[key], "rb") as src, open(pt_out, "wb") as dst:
                dst.write(src.read())
            print(f"  [cached] {fname}")
            continue

        set_color_variant(color_grp, color_tint, c_name, t_name)

        # 1. Full Frame without P/T Box
        black_borders.visible = True
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

        frame_img = psd.composite(force=True)
        save_cropped_rgba(frame_img, pin_out, seal_pt_cutout=True)
        del frame_img

        # 2. Standalone P/T Box in full card coordinates (exact 1500x2100 RGBA)
        black_borders.visible = False
        drop_shadow_grp.visible = False
        color_grp.visible = False
        box_outlines.visible = False
        text_box_copy.visible = False
        name_type_copy.visible = False
        black_title_box.visible = False
        pt_box_layer.visible = True

        pt_img = psd.composite(force=True)
        save_cropped_rgba(pt_img, pt_out)
        del pt_img

        cached_pin[key] = pin_out
        cached_pt[key] = pt_out
        print(f"  [ok] {fname} (Pinlines + PT Box)")

    print("Done extracting Token-2.psd!")


if __name__ == "__main__":
    main()
