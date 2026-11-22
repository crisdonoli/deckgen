"""Rasterize SVG assets to PNG behind a content-addressed cache."""
import argparse
import hashlib
import importlib
import importlib.util
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:
    from ..config import CACHE_ROOT
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from config import CACHE_ROOT

CACHE_DIR = Path(CACHE_ROOT) / "svg_cache"
BACKENDS = ("cairosvg", "rsvg-convert", "inkscape", "convert")
MANA_COLORS = {
    "W": (248, 231, 185, 255),
    "U": (14, 104, 171, 255),
    "B": (21, 11, 0, 255),
    "R": (211, 32, 42, 255),
    "G": (0, 115, 62, 255),
    "C": (150, 150, 150, 255),
}
_FALLBACK_COLOR = (150, 150, 150, 255)


@lru_cache(maxsize=1)
def backend() -> str:
    if importlib.util.find_spec("cairosvg"):
        return "cairosvg"
    for name in BACKENDS[1:]:
        if shutil.which(name):
            return name
    return ""


def _convert(svg_path: str, out_path: str, size: int, name: str) -> None:
    if name == "cairosvg":
        importlib.import_module("cairosvg").svg2png(
            url=svg_path, write_to=out_path, output_width=size, output_height=size
        )
        return
    if name == "rsvg-convert":
        cmd = ["rsvg-convert", "-w", str(size), "-h", str(size), "-o", out_path, svg_path]
    elif name == "inkscape":
        cmd = [
            "inkscape",
            svg_path,
            "--export-type=png",
            "--export-filename=%s" % out_path,
            "--export-width=%d" % size,
            "--export-height=%d" % size,
        ]
    elif name == "convert":
        cmd = ["convert", "-background", "none", "-density", "384", svg_path, "-resize", "%dx%d" % (size, size), out_path]
    else:
        raise ValueError("unknown svg backend: %s" % name)
    subprocess.run(cmd, check=True, capture_output=True)


def _symbol_code(svg_path: str) -> str:
    stem = Path(svg_path).stem
    return stem[:2].strip("-_").upper()


def _fallback_png(svg_path: str, out_path: str, size: int) -> None:
    color = MANA_COLORS.get(_symbol_code(svg_path), _FALLBACK_COLOR)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = max(1, size // 16)
    draw.ellipse((pad, pad, size - pad - 1, size - pad - 1), fill=color)
    label = Path(svg_path).stem[:2].strip("-_") or "?"
    font = ImageFont.load_default(size=max(8, int(size * 0.45)))
    left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
    draw.text(
        ((size - (right - left)) / 2 - left, (size - (bottom - top)) / 2 - top),
        label,
        font=font,
        fill=(255, 255, 255, 255),
    )
    img.save(out_path, format="PNG")


def cache_path(svg_path: str, size: int) -> Path:
    path = Path(svg_path)
    digest = hashlib.sha1(("%s:%d:%d" % (path.resolve(), path.stat().st_mtime_ns, size)).encode()).hexdigest()
    return CACHE_DIR / ("%s.png" % digest)


def rasterize_svg(svg_path: str, size: int = 256, out_path: str = None) -> str:
    if out_path:
        target = Path(out_path)
    else:
        target = cache_path(svg_path, size)
        if target.is_file():
            return str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    name = backend()
    if name:
        _convert(str(svg_path), str(target), size, name)
    else:
        _fallback_png(str(svg_path), str(target), size)
    return str(target)


def rasterize_dir_to_png(src_dir: str, out_dir: str, size: int = 256) -> list:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for svg in sorted(Path(src_dir).glob("*.svg")):
        target = out / ("%s.png" % svg.stem)
        rasterize_svg(str(svg), size=size, out_path=str(target))
        results.append({"src": str(svg), "out": str(target), "bytes": target.stat().st_size})
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="svg_raster")
    parser.add_argument("--dir", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    print("backend=%s" % (backend() or "fallback"))
    out_dir = args.out or str(CACHE_DIR / "cli")
    rows = rasterize_dir_to_png(args.dir, out_dir, size=args.size)
    if args.limit:
        rows = rows[: args.limit]
    for row in rows:
        print("%s -> %s (%d bytes)" % (row["src"], row["out"], row["bytes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
