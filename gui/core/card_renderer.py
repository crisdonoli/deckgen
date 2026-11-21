import os
import re
from typing import List, Tuple

import numpy as np
from PIL import Image

from config import DEFAULT_EXPORT_DPI, MAX_EXPORT_DPI, MIN_EXPORT_DPI

try:
    import pymupdf  # type: ignore
except ImportError:
    pymupdf = None

Image.MAX_IMAGE_PIXELS = max(getattr(Image, "MAX_IMAGE_PIXELS", 89478485) or 89478485, 120_000_000)


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


def remove_solid_bg_pil(pil_img: Image.Image, tolerance: int = 28, clear_art_box_black: bool = True) -> Image.Image:
    rgba = pil_img.convert("RGBA")
    arr = np.array(rgba, dtype=np.int16)
    h, w, _ = arr.shape
    if h == 0 or w == 0:
        return rgba
    corners = np.array([arr[0, 0, :3], arr[0, w - 1, :3], arr[h - 1, 0, :3], arr[h - 1, w - 1, :3]])
    bg_rgb = np.median(corners, axis=0)
    dist = np.max(np.abs(arr[:, :, :3] - bg_rgb), axis=2)
    mask = dist > tolerance
    arr[:, :, 3] = np.where(mask, 255, 0)

    if clear_art_box_black and w >= 100 and h >= 100:
        sx = w / 750.0
        sy = h / 1050.0
        pts = [(375, 340), (180, 220), (560, 220), (180, 460), (560, 460)]
        if all(
            np.max(arr[int(py * sy), int(px * sx), :3]) < 22 and arr[int(py * sy), int(px * sx), 3] > 200
            for px, py in pts
        ):
            x0, x1 = int(34 * sx), int(716 * sx)
            y0, y1 = int(109 * sy), int(586 * sy)
            sub = arr[y0:y1, x0:x1, :3]
            black_mask = np.max(sub, axis=2) < 22
            arr[y0:y1, x0:x1, 3] = np.where(black_mask, 0, arr[y0:y1, x0:x1, 3])

    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def render_pdf_layer_rgba(file_path: str, target_w: int, target_h: int) -> Image.Image:
    if file_path.lower().endswith(".pdf"):
        if pymupdf is not None:
            doc = pymupdf.open(file_path)
            try:
                page = doc[0]
                rect = page.rect
                ratio = rect.width / rect.height if rect.height else 0.0
                if rect.width < rect.height and 0.724 <= ratio <= 0.742:
                    bx = rect.width * (144.0 / 3288.0)
                    by = rect.height * (144.0 / 4488.0)
                    clip = pymupdf.Rect(bx, by, rect.width - bx, rect.height - by)
                else:
                    clip = rect
                mat = pymupdf.Matrix(target_w / clip.width, target_h / clip.height)
                pix = page.get_pixmap(matrix=mat, clip=clip, alpha=True)
                rgba = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
                del pix
                if rgba.size != (target_w, target_h):
                    rgba = rgba.resize((target_w, target_h), Image.LANCZOS)
            finally:
                doc.close()
        else:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(file_path)
            page = doc[0]
            scale = max(target_w / max(1.0, page.get_width()), target_h / max(1.0, page.get_height()))
            rgba = page.render(scale=scale).to_pil().convert("RGBA")
            doc.close()
            if rgba.size != (target_w, target_h):
                rgba = rgba.resize((target_w, target_h), Image.LANCZOS)
    else:
        with Image.open(file_path) as src_img:
            rgba = src_img.convert("RGBA")
            w, h = rgba.size
            ratio = w / h if h else 0.0
            if w < h and 0.724 <= ratio <= 0.742:
                bx = int(round(w * (144.0 / 3288.0)))
                by = int(round(h * (144.0 / 4488.0)))
                rgba = rgba.crop((bx, by, w - bx, h - by))
            rgba = rgba.resize((target_w, target_h), Image.LANCZOS)

    extrema = rgba.getextrema()
    if len(extrema) >= 4 and extrema[3] == (255, 255):
        return remove_solid_bg_pil(rgba)
    return rgba


from core.recipe_renderer import render_recipe, save_recipe_png  # noqa: F401
