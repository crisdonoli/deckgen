"""Repair fonts in assets/resources/_shared/fonts that Chrome's font sanitizer (OTS) rejects.

Some old Mac-converted fonts (e.g. mplantin.ttf) have cmap subtables with a non-zero
language id. Chrome then refuses the whole font ("cmap: language id should be zero") and the
Card Builder preview silently falls back to Georgia, while the server-side export (Pillow)
uses the real font. This sets those language ids to 0 (language-independent), which does not
touch any glyph, and keeps a <name>.orig backup of every file it changes.

Needs fontTools (not in requirements.txt):  uv pip install fonttools
Usage: python scripts/fix_fonts_for_browser.py [--dry-run]
"""
import argparse
import shutil
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gui"))
from config import SHARED_DIR  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="only report what would change")
    args = parser.parse_args()

    fonts_dir = Path(SHARED_DIR) / "fonts"
    changed = 0
    for path in sorted(fonts_dir.iterdir()):
        if path.suffix.lower() not in (".ttf", ".otf"):
            continue
        try:
            font = TTFont(str(path))
        except Exception as exc:  # unreadable font: report and move on
            print("skip %s (%s)" % (path.name, exc))
            continue
        if "cmap" not in font:
            continue
        bad = [t for t in font["cmap"].tables if getattr(t, "language", 0) != 0]
        if not bad:
            continue
        print("%s: cmap subtables with language != 0: %s" % (
            path.name, [(t.platformID, t.platEncID, t.format, t.language) for t in bad]))
        changed += 1
        if args.dry_run:
            continue
        for table in bad:
            table.language = 0
        backup = path.with_name(path.name + ".orig")
        if not backup.exists():
            shutil.copy2(path, backup)
        font.save(str(path))
        print("  fixed (backup: %s)" % backup.name)
    print("%d font(s) %s" % (changed, "would change" if args.dry_run else "fixed"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
