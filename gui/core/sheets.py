from typing import Dict, List, Optional, Tuple
from PIL import Image, ImageDraw

from config import CARD_H_MM, CARD_W_MM, PAPER_SIZES
from utils.conversions import mm_to_px, parse_hex, pt_to_px


def compute_grid(paper_w_mm: float, paper_h_mm: float, card_spacing: float = 0.0) -> Tuple[int, int]:
    cols = int((paper_w_mm + card_spacing) // (CARD_W_MM + card_spacing))
    rows = int((paper_h_mm + card_spacing) // (CARD_H_MM + card_spacing))
    if cols < 1 or rows < 1:
        raise ValueError("Paper size too small for one card")
    return cols, rows


def sheet_geometry(paper: str, landscape: bool, dpi: int, card_spacing: float = 0.0):
    paper_w_mm, paper_h_mm = PAPER_SIZES[paper]
    if landscape:
        paper_w_mm, paper_h_mm = paper_h_mm, paper_w_mm
    cols, rows = compute_grid(paper_w_mm, paper_h_mm, card_spacing)
    paper_px = (mm_to_px(paper_w_mm, dpi), mm_to_px(paper_h_mm, dpi))
    card_px = (mm_to_px(CARD_W_MM, dpi), mm_to_px(CARD_H_MM, dpi))
    gap_px = mm_to_px(card_spacing, dpi)
    grid_w = cols * card_px[0] + (cols - 1) * gap_px
    grid_h = rows * card_px[1] + (rows - 1) * gap_px
    margin_x = max(0, (paper_px[0] - grid_w) // 2)
    margin_y = max(0, (paper_px[1] - grid_h) // 2)
    return cols, rows, paper_px, card_px, margin_x, margin_y, gap_px


def back_offset_px(back_offset_mm: Optional[Tuple[float, float]], dpi: int) -> Tuple[int, int]:
    """Back sheet shift (x, y) in px from mm, clamped to +/-10 mm. It compensates the
    printer's duplex registration error: positive x moves the backs right and positive y
    moves them down, as the back page is seen in the PDF."""
    if not back_offset_mm:
        return 0, 0
    out = []
    for v in back_offset_mm[:2]:
        try:
            mm = float(v)
        except (TypeError, ValueError):
            mm = 0.0
        mm = max(-10.0, min(10.0, mm))
        out.append(int(round(mm * dpi / 25.4)))
    while len(out) < 2:
        out.append(0)
    return out[0], out[1]


def _mirror_rect_x(x: int, y: int, w: int, h: int, paper_w: int) -> Tuple[int, int]:
    return (paper_w - x - w, y)


def _apply_individual_card_scale(img: Image.Image, target_w: int, target_h: int, scale: float) -> Image.Image:
    """
    Applies individual per-card scaling within the fixed slot (target_w, target_h).
    - scale > 1.0 zooms in around the center and crops to slot (trims excess black border).
    - scale < 1.0 shrinks card centered on white background.
    """
    try:
        s = float(scale)
    except (TypeError, ValueError):
        s = 1.0
    s = max(0.70, min(1.30, s))

    if abs(s - 1.0) < 0.001:
        return img.resize((target_w, target_h), Image.LANCZOS) if img.size != (target_w, target_h) else img

    sw = max(1, int(round(target_w * s)))
    sh = max(1, int(round(target_h * s)))
    scaled = img.resize((sw, sh), Image.LANCZOS)

    if s > 1.0:
        left = (sw - target_w) // 2
        top = (sh - target_h) // 2
        return scaled.crop((left, top, left + target_w, top + target_h))
    else:
        slot = Image.new("RGB", (target_w, target_h), (255, 255, 255))
        slot.paste(scaled, ((target_w - sw) // 2, (target_h - sh) // 2))
        return slot


def _prepare_back_card_image(img: Image.Image, target_w: int, target_h: int, duplex_flip: bool = True, scale: float = 1.0) -> Image.Image:
    is_landscape_target = target_w > target_h
    is_landscape_img = img.width > img.height
    if is_landscape_target != is_landscape_img:
        angle = 90 if duplex_flip else -90
        img = img.rotate(angle, expand=True)
    elif is_landscape_target and is_landscape_img and duplex_flip:
        img = img.rotate(180, expand=True)
    return _apply_individual_card_scale(img, target_w, target_h, scale)


def generate_base_sheets(
    images: List[Image.Image],
    paper: str,
    landscape: bool,
    dpi: int,
    card_spacing: float = 0.0,
    is_back: bool = False,
    duplex_flip: bool = True,
    card_scales: Optional[Dict[str, float]] = None,
    global_start_index: int = 0,
    back_offset_mm: Optional[Tuple[float, float]] = None,
    bleed_mm: float = 0.0,
) -> List[Image.Image]:
    cols, rows, paper_px, card_px, margin_x, margin_y, gap_px = sheet_geometry(
        paper, landscape, dpi, card_spacing
    )
    paper_w, _ = paper_px
    pitch_x = card_px[0] + gap_px
    pitch_y = card_px[1] + gap_px
    cards_per_sheet = cols * rows
    sheets = []
    scales_map = card_scales or {}
    off_x, off_y = back_offset_px(back_offset_mm, dpi) if is_back else (0, 0)
    try:
        bleed_px = mm_to_px(max(0.0, min(5.0, float(bleed_mm or 0.0))), dpi)
    except (TypeError, ValueError):
        bleed_px = 0

    for sheet_idx in range(0, len(images), cards_per_sheet):
        canvas = Image.new("RGB", paper_px, (255, 255, 255))
        batch = images[sheet_idx : sheet_idx + cards_per_sheet]
        placed: List[Tuple[Image.Image, int, int]] = []

        for idx, image in enumerate(batch):
            abs_idx = global_start_index + sheet_idx + idx
            scale = float(scales_map.get(str(abs_idx), scales_map.get(abs_idx, 1.0)))

            row = idx // cols
            col = idx % cols
            x_front = margin_x + col * pitch_x
            y_front = margin_y + row * pitch_y
            w, h = card_px

            if is_back and duplex_flip:
                x, y = _mirror_rect_x(x_front, y_front, w, h, paper_w)
                img_to_paste = _prepare_back_card_image(image, w, h, duplex_flip=True, scale=scale)
            else:
                x, y = x_front, y_front
                img_to_paste = _apply_individual_card_scale(image, w, h, scale)

            placed.append((img_to_paste, x + off_x, y + off_y))

        # Black bleed border: a rectangle bleed_px larger than each card, drawn under all
        # cards first, so it only shows where a card edge faces the white sheet.
        if bleed_px > 0:
            draw = ImageDraw.Draw(canvas)
            for img_to_paste, x, y in placed:
                draw.rectangle(
                    [x - bleed_px, y - bleed_px, x + img_to_paste.width + bleed_px - 1, y + img_to_paste.height + bleed_px - 1],
                    fill=(0, 0, 0),
                )
        for img_to_paste, x, y in placed:
            canvas.paste(img_to_paste, (x, y))
        sheets.append(canvas)
    return sheets


def draw_cut_lines_on_canvas(
    canvas: Image.Image,
    paper: str,
    landscape: bool,
    dpi: int,
    cut: str,
    color: str,
    thickness: float,
    mark_len: float,
    card_spacing: float = 0.0,
    is_back: bool = False,
    duplex_flip: bool = True,
    back_offset_mm: Optional[Tuple[float, float]] = None,
) -> Image.Image:
    if cut == "none":
        return canvas
    cols, rows, paper_px, card_px, margin_x, margin_y, gap_px = sheet_geometry(
        paper, landscape, dpi, card_spacing
    )
    if is_back and duplex_flip:
        grid_w = cols * card_px[0] + (cols - 1) * gap_px
        margin_x = paper_px[0] - margin_x - grid_w
    if is_back:
        off_x, off_y = back_offset_px(back_offset_mm, dpi)
        margin_x += off_x
        margin_y += off_y

    draw = ImageDraw.Draw(canvas)
    mark_px = mm_to_px(mark_len, dpi)
    line_width = pt_to_px(thickness, dpi)
    line_color = parse_hex(color)

    pitch_x = card_px[0] + gap_px
    pitch_y = card_px[1] + gap_px
    grid_w = cols * card_px[0] + (cols - 1) * gap_px
    grid_h = rows * card_px[1] + (rows - 1) * gap_px
    right = margin_x + grid_w
    bottom = margin_y + grid_h

    xs = sorted({margin_x + c * pitch_x for c in range(cols)} | {margin_x + c * pitch_x + card_px[0] for c in range(cols)})
    ys = sorted({margin_y + r * pitch_y for r in range(rows)} | {margin_y + r * pitch_y + card_px[1] for r in range(rows)})

    if cut == "corners":
        for x in xs:
            for y in ys:
                if y == margin_y:
                    draw.line([(x, y), (x, min(y + mark_px, bottom))], fill=line_color, width=line_width)
                elif y == bottom:
                    draw.line([(x, max(y - mark_px, margin_y)), (x, y)], fill=line_color, width=line_width)
                else:
                    draw.line([(x, max(y - mark_px // 2, margin_y)), (x, min(y + mark_px // 2, bottom))], fill=line_color, width=line_width)
                if x == margin_x:
                    draw.line([(x, y), (min(x + mark_px, right), y)], fill=line_color, width=line_width)
                elif x == right:
                    draw.line([(max(x - mark_px, margin_x), y), (x, y)], fill=line_color, width=line_width)
                else:
                    draw.line([(max(x - mark_px // 2, margin_x), y), (min(x + mark_px // 2, right), y)], fill=line_color, width=line_width)
    else:
        for x in xs:
            draw.line([(x, margin_y), (x, bottom)], fill=line_color, width=line_width)
        for y in ys:
            draw.line([(margin_x, y), (right, y)], fill=line_color, width=line_width)
    return canvas


def generate_sheets(
    images: List[Image.Image],
    paper: str,
    landscape: bool,
    dpi: int,
    cut: str,
    color: str,
    thickness: float,
    mark_len: float,
    card_spacing: float = 0.0,
    is_back: bool = False,
    duplex_flip: bool = True,
    card_scales: Optional[Dict[str, float]] = None,
    global_start_index: int = 0,
    back_offset_mm: Optional[Tuple[float, float]] = None,
    bleed_mm: float = 0.0,
) -> List[Image.Image]:
    sheets = generate_base_sheets(
        images,
        paper,
        landscape,
        dpi,
        card_spacing=card_spacing,
        is_back=is_back,
        duplex_flip=duplex_flip,
        card_scales=card_scales,
        global_start_index=global_start_index,
        back_offset_mm=back_offset_mm,
        bleed_mm=bleed_mm,
    )
    for canvas in sheets:
        draw_cut_lines_on_canvas(
            canvas,
            paper,
            landscape,
            dpi,
            cut,
            color,
            thickness,
            mark_len,
            card_spacing=card_spacing,
            is_back=is_back,
            duplex_flip=duplex_flip,
            back_offset_mm=back_offset_mm,
        )
    return sheets
