import io
import os
import tempfile

from PIL import Image, ImageOps

from config import DPI, STANDARD_CARD_H_PX, STANDARD_CARD_W_PX


def build_pdf(sheets, tmp_dir):
    out_path = os.path.join(tmp_dir, "sheets.pdf")
    first = sheets[0]
    rest = sheets[1:]
    first.save(out_path, format="PDF", save_all=True, append_images=rest, resolution=float(DPI))
    return out_path


def image_to_standard_pdf(image_bytes, dest_path):
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    card = ImageOps.fit(
        image, (STANDARD_CARD_W_PX, STANDARD_CARD_H_PX), method=Image.LANCZOS
    )
    card.save(dest_path, format="PDF", resolution=DPI)


def _build_pdf_bytes(sheets):
    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = build_pdf(sheets, tmp_dir)
        with open(pdf_path, "rb") as f:
            return f.read()
