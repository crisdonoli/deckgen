import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading

from PIL import Image

from config import CARD_H_MM, CARD_W_MM, RENDER_CACHE_DIR
from utils.conversions import mm_to_px


def _file_digest(file_path: str) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _cached_png_path(file_path: str, dpi: int) -> str:
    key = hashlib.sha256(f"{_file_digest(file_path)}\x00{dpi}".encode()).hexdigest()
    return os.path.join(RENDER_CACHE_DIR, f"{key}.png")


def _store_in_cache(src_path: str, cache_path: str) -> None:
    os.makedirs(RENDER_CACHE_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=RENDER_CACHE_DIR, suffix=".tmp")
    os.close(fd)
    shutil.copyfile(src_path, tmp_path)
    os.replace(tmp_path, cache_path)


def render_card_file_to_image(file_path: str, dpi: int, tmp_dir: str) -> Image.Image:
    """Render a card PDF or image file to an RGB Pillow Image at exact card dimensions."""
    target_w = mm_to_px(CARD_W_MM, dpi)
    target_h = mm_to_px(CARD_H_MM, dpi)

    if not file_path.lower().endswith(".pdf"):
        with Image.open(file_path) as src:
            img = src.convert("RGB")
        if img.size != (target_w, target_h):
            img = img.resize((target_w, target_h), Image.LANCZOS)
        return img

    cache_path = _cached_png_path(file_path, dpi)
    if os.path.exists(cache_path):
        with Image.open(cache_path) as cached:
            img = cached.convert("RGB")
    else:
        base = os.path.splitext(os.path.basename(file_path))[0]
        safe_base = re.sub(r"[^a-zA-Z0-9_\-]", "_", base)
        out_prefix = os.path.join(tmp_dir, f"{safe_base}_{dpi}_{os.getpid()}_{threading.get_ident()}")
        out_path = out_prefix + ".png"

        if shutil.which("pdftoppm"):
            cmd = [
                "pdftoppm",
                "-png",
                "-scale-to-x", str(target_w),
                "-scale-to-y", str(target_h),
                "-singlefile",
                file_path,
                out_prefix,
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(file_path)
            page = doc[0]
            scale = max(target_w / max(1.0, page.get_width()), target_h / max(1.0, page.get_height()))
            bitmap = page.render(scale=scale)
            pil_img = bitmap.to_pil().convert("RGB")
            pil_img.save(out_path, format="PNG")
            doc.close()

        if not os.path.exists(out_path):
            raise RuntimeError(f"Failed to render PDF to PNG: {file_path}")
        _store_in_cache(out_path, cache_path)
        with Image.open(out_path) as rendered:
            img = rendered.convert("RGB")

    if img.size != (target_w, target_h):
        img = img.resize((target_w, target_h), Image.LANCZOS)
    return img
