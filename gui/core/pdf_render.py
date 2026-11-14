import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading

from PIL import Image

from config import CARD_H_MM, CARD_W_MM
from utils.conversions import mm_to_px

RENDER_CACHE_DIR = "/tmp/opencode/render_cache"


def _file_digest(pdf_path):
    hasher = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _cached_png_path(pdf_path, dpi):
    key = hashlib.sha256(f"{_file_digest(pdf_path)}\x00{dpi}".encode()).hexdigest()
    return os.path.join(RENDER_CACHE_DIR, f"{key}.png")


def _store_in_cache(src_path, cache_path):
    os.makedirs(RENDER_CACHE_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=RENDER_CACHE_DIR, suffix=".tmp")
    os.close(fd)
    shutil.copyfile(src_path, tmp_path)
    os.replace(tmp_path, cache_path)


def render_pdf_to_png(pdf_path, dpi, tmp_dir):
    target_w = mm_to_px(CARD_W_MM, dpi)
    target_h = mm_to_px(CARD_H_MM, dpi)
    cache_path = _cached_png_path(pdf_path, dpi)
    if os.path.exists(cache_path):
        out_path = cache_path
    else:
        base = os.path.splitext(os.path.basename(pdf_path))[0]
        safe_base = re.sub(r"[^a-zA-Z0-9_\-]", "_", base)
        out_prefix = os.path.join(tmp_dir, f"{safe_base}_{dpi}_{os.getpid()}_{threading.get_ident()}")
        cmd = [
            "pdftoppm",
            "-png",
            "-scale-to-x",
            str(target_w),
            "-scale-to-y",
            str(target_h),
            "-singlefile",
            pdf_path,
            out_prefix,
        ]
        subprocess.run(cmd, check=True)
        out_path = out_prefix + ".png"
        if not os.path.exists(out_path):
            raise RuntimeError(f"pdftoppm did not produce {out_path}")
        _store_in_cache(out_path, cache_path)
    img = Image.open(out_path).convert("RGB")
    if img.size != (target_w, target_h):
        img = img.resize((target_w, target_h), Image.LANCZOS)
    return img
