import io
import os
from typing import Callable, List, Optional

from PIL import Image, ImageOps

from config import DPI, STANDARD_CARD_H_PX, STANDARD_CARD_W_PX

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def build_pdf(sheets: List[Image.Image], out_dir: str, filename: str = "sheets.pdf", dpi: int = DPI) -> str:
    if not sheets:
        raise ValueError("No sheets generated to export")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, filename)
    first = sheets[0].convert("RGB")
    rest = [s.convert("RGB") for s in sheets[1:]]
    first.save(out_path, format="PDF", save_all=True, append_images=rest, resolution=float(dpi))
    return out_path


def image_to_standard_pdf(image_bytes: bytes, dest_path: str, dpi: int = DPI) -> str:
    with Image.open(io.BytesIO(image_bytes)) as raw:
        image = raw.convert("RGB")
    scale = dpi / float(DPI)
    w = max(1, int(round(STANDARD_CARD_W_PX * scale)))
    h = max(1, int(round(STANDARD_CARD_H_PX * scale)))
    card = ImageOps.fit(image, (w, h), method=Image.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
    card.save(dest_path, format="PDF", resolution=float(dpi))
    return dest_path


def convert_images_folder_to_pdfs(
    source_dir: str,
    dest_pdf_dir: str,
    dpi: int = DPI,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> List[str]:
    """Background conversion of PNG/JPG images in source_dir to standard-sized PDFs."""
    if not os.path.isdir(source_dir):
        return []
    img_files = sorted(
        f for f in os.listdir(source_dir)
        if f.lower().endswith(IMAGE_EXTS) and os.path.isfile(os.path.join(source_dir, f))
    )
    if not img_files:
        return []

    os.makedirs(dest_pdf_dir, exist_ok=True)
    converted = []
    total = len(img_files)
    for idx, fname in enumerate(img_files, start=1):
        src_path = os.path.join(source_dir, fname)
        stem = os.path.splitext(fname)[0]
        dest_path = os.path.join(dest_pdf_dir, f"{stem}.pdf")
        if not os.path.isfile(dest_path) or os.path.getmtime(src_path) > os.path.getmtime(dest_path):
            with open(src_path, "rb") as f:
                image_to_standard_pdf(f.read(), dest_path, dpi=dpi)
        converted.append(dest_path)
        if progress_cb:
            progress_cb(idx, total)
    return converted
