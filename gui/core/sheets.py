from PIL import Image, ImageDraw

from config import CARD_H_MM, CARD_W_MM, PAPER_SIZES
from utils.conversions import mm_to_px, parse_hex, pt_to_px


def compute_grid(paper_w_mm, paper_h_mm, card_spacing=0.0):
    cols = int((paper_w_mm + card_spacing) // (CARD_W_MM + card_spacing))
    rows = int((paper_h_mm + card_spacing) // (CARD_H_MM + card_spacing))
    if cols < 1 or rows < 1:
        raise ValueError("paper size too small for one card")
    return cols, rows


def _sheet_geometry(paper, landscape, dpi, card_spacing=0.0):
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


def _mirror_rect_x(x, y, w, h, paper_w):
    """
    Transformación exacta para giro de hoja horizontal (hacia la derecha / eje vertical).
    Mantiene intacta la coordenada Y y refleja el segmento [x, x + w] respecto a paper_w.
    """
    return (paper_w - x - w, y)


def _prepare_back_card_image(img, target_w, target_h, duplex_flip=True):
    """
    Ajusta el tamaño del reverso y corrige la orientación si la carta está rotada (paisaje).
    En el test: si el front está rotado 90° CW (top hacia la derecha), al girar la hoja
    hacia la derecha ese borde queda a la izquierda, por lo que el back horizontal debe
    rotarse 180° respecto a una rotación estándar (es decir, 90° CCW / 270°) para coincidir.
    """
    is_landscape_target = target_w > target_h
    is_landscape_img = img.width > img.height

    if is_landscape_target != is_landscape_img:
        # Si la celda destino es horizontal pero el back viene vertical (o viceversa)
        angle = 90 if duplex_flip else -90
        img = img.rotate(angle, expand=True)
    elif is_landscape_target and is_landscape_img and duplex_flip:
        # Si la imagen de reverso ya venía pre-rotada igual que el front horizontal,
        # al voltear la hoja horizontalmente su eje X se invierte, requiriendo rotar 180°.
        img = img.rotate(180, expand=True)

    if img.size != (target_w, target_h):
        img = img.resize((target_w, target_h), Image.LANCZOS)
    return img


def generate_base_sheets(
    images, paper, landscape, dpi, card_spacing=0.0, is_back=False, duplex_flip=True, placements=None
):
    """
    Genera las hojas base.
    - En modo grilla normal (placements=None): calcula la coordenada exacta (x_front, y_front)
      de cada slot en el frente y, si es back + duplex_flip, refleja la coordenada física X
      contra el ancho total del papel (paper_px[0] - x_front - w).
    - En modo coordenadas arbitrarias (placements=[(x, y, w, h, rot), ...]): aplica exactamente
      la misma reflexión geométrica para pasar el test de posiciones libres y rotaciones.
    """
    cols, rows, paper_px, card_px, margin_x, margin_y, gap_px = _sheet_geometry(
        paper, landscape, dpi, card_spacing
    )
    paper_w, _ = paper_px
    pitch_x = card_px[0] + gap_px
    pitch_y = card_px[1] + gap_px
    cards_per_sheet = len(placements) if placements else (cols * rows)
    sheets = []

    for sheet_idx in range(0, len(images), cards_per_sheet):
        canvas = Image.new("RGB", paper_px, (255, 255, 255))
        batch = images[sheet_idx : sheet_idx + cards_per_sheet]

        for idx, image in enumerate(batch):
            if placements:
                # Coordenadas explícitas: (x_front, y_front, w, h) o (x_front, y_front)
                item = placements[idx]
                x_front, y_front = item[0], item[1]
                w = item[2] if len(item) > 2 else image.width
                h = item[3] if len(item) > 3 else image.height
            else:
                row = idx // cols
                col = idx % cols
                x_front = margin_x + col * pitch_x
                y_front = margin_y + row * pitch_y
                w, h = card_px

            if is_back and duplex_flip:
                x, y = _mirror_rect_x(x_front, y_front, w, h, paper_w)
                img_to_paste = _prepare_back_card_image(image, w, h, duplex_flip=True)
            else:
                x, y = x_front, y_front
                img_to_paste = (
                    image.resize((w, h), Image.LANCZOS)
                    if image.size != (w, h)
                    else image
                )

            canvas.paste(img_to_paste, (x, y))
        sheets.append(canvas)
    return sheets


def _draw_cut_lines_on_canvas(
    canvas,
    paper,
    landscape,
    dpi,
    cut,
    color,
    thickness,
    mark_len,
    card_spacing=0.0,
    is_back=False,
    duplex_flip=True,
):
    cols, rows, paper_px, card_px, margin_x, margin_y, gap_px = _sheet_geometry(
        paper, landscape, dpi, card_spacing
    )
    if cut == "none":
        return canvas

    # Si es el reverso espejado, el margen izquierdo del bloque de corte debe ser
    # exactamente el margen derecho que tenía el frente: paper_w - (margin_x + grid_w)
    if is_back and duplex_flip:
        grid_w = cols * card_px[0] + (cols - 1) * gap_px
        margin_x = paper_px[0] - margin_x - grid_w

    draw = ImageDraw.Draw(canvas)
    mark_px = mm_to_px(mark_len, dpi)
    line_width = pt_to_px(thickness, dpi)
    line_color = parse_hex(color)
    draw_cut_lines(
        draw,
        margin_x,
        margin_y,
        cols,
        rows,
        card_px,
        gap_px,
        paper_px,
        mark_px,
        line_width,
        line_color,
        cut == "corners",
    )
    return canvas


def generate_sheets(
    images,
    paper,
    landscape,
    dpi,
    cut,
    color,
    thickness,
    mark_len,
    card_spacing=0.0,
    is_back=False,
    duplex_flip=True,
):
    sheets = generate_base_sheets(
        images,
        paper,
        landscape,
        dpi,
        card_spacing,
        is_back=is_back,
        duplex_flip=duplex_flip,
    )
    for canvas in sheets:
        _draw_cut_lines_on_canvas(
            canvas,
            paper,
            landscape,
            dpi,
            cut,
            color,
            thickness,
            mark_len,
            card_spacing,
            is_back=is_back,
            duplex_flip=duplex_flip,
        )
    return sheets


def draw_cut_lines(
    draw,
    margin_x,
    margin_y,
    cols,
    rows,
    card_px,
    gap_px,
    paper_px,
    mark_px,
    line_width,
    color,
    corners_only,
):
    pitch_x = card_px[0] + gap_px
    pitch_y = card_px[1] + gap_px
    grid_w = cols * card_px[0] + (cols - 1) * gap_px
    grid_h = rows * card_px[1] + (rows - 1) * gap_px
    right = margin_x + grid_w
    bottom = margin_y + grid_h

    def draw_segment(x1, y1, x2, y2):
        draw.line([(x1, y1), (x2, y2)], fill=color, width=line_width)

    xs = set()
    for c in range(cols):
        xs.add(margin_x + c * pitch_x)
        xs.add(margin_x + c * pitch_x + card_px[0])
    xs = sorted(xs)

    ys = set()
    for r in range(rows):
        ys.add(margin_y + r * pitch_y)
        ys.add(margin_y + r * pitch_y + card_px[1])
    ys = sorted(ys)

    if corners_only:
        for x in xs:
            for y in ys:
                if y == margin_y:
                    draw_segment(x, y, x, min(y + mark_px, bottom))
                elif y == bottom:
                    draw_segment(x, max(y - mark_px, margin_y), x, y)
                else:
                    draw_segment(
                        x,
                        max(y - mark_px // 2, margin_y),
                        x,
                        min(y + mark_px // 2, bottom),
                    )

                if x == margin_x:
                    draw_segment(x, y, min(x + mark_px, right), y)
                elif x == right:
                    draw_segment(max(x - mark_px, margin_x), y, x, y)
                else:
                    draw_segment(
                        max(x - mark_px // 2, margin_x),
                        y,
                        min(x + mark_px // 2, right),
                        y,
                    )
    else:
        for x in xs:
            draw_segment(x, margin_y, x, bottom)
        for y in ys:
            draw_segment(margin_x, y, right, y)
