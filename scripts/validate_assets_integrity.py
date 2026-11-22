#!/usr/bin/env python3
"""Validate referential integrity between disk (/assets/resources/) and SQLite (assets.db) + taxonomy.json."""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gui"))

from config import ASSETS_DB_PATH, FRAMES_DIR, SCRYFALL_MAP_PATH, SHARED_DIR, TAXONOMY_PATH  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ALLOWED_CACHE_DIRS = {"png_cache", "svg_cache"}
MAGIC_HEADERS = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "ttf": (b"\x00\x01\x00\x00", b"true", b"typ1", b"OTTO"),
    "otf": (b"OTTO", b"\x00\x01\x00\x00"),
    "woff": (b"wOFF",),
    "woff2": (b"wOF2",),
}


def has_valid_header(path: Path, ext: str) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    ext = ext.lower().lstrip(".")
    head = path.read_bytes()[:64]
    if ext == "svg":
        text = head.lstrip().lower()
        return text.startswith((b"<svg", b"<?xml", b"<!--")) or b"<svg" in path.read_bytes()[:512].lower()
    expected = MAGIC_HEADERS.get(ext)
    if expected:
        return any(head.startswith(sig) for sig in expected)
    return len(head) > 0


def main() -> int:
    frames_dir = Path(FRAMES_DIR)
    shared_dir = Path(SHARED_DIR)
    db_path = Path(ASSETS_DB_PATH)
    taxonomy = json.loads(Path(TAXONOMY_PATH).read_text(encoding="utf-8"))
    smap = json.loads(Path(SCRYFALL_MAP_PATH).read_text(encoding="utf-8"))

    conn = sqlite3.connect(str(db_path))
    failures = []

    # 1. Verify no absolute paths in DB
    for table, col in (
        ("frames", "file"),
        ("frames", "original_path"),
        ("shared_resources", "file"),
        ("shared_resources", "original_path"),
    ):
        bad = [
            r[0]
            for r in conn.execute(f"SELECT {col} FROM {table}")
            if str(r[0]).startswith("/") or ":" in str(r[0]) or "\\" in str(r[0])
        ]
        if bad:
            failures.append(f"{table}.{col} contains non-portable paths: {bad[:5]}")

    # 2. Verify Planeswalker mapping & DB rows
    pw_rules = [
        r
        for r in smap["structural_type_override_mapping"]["rules"]
        if r.get("match") == "Planeswalker"
    ]
    pw_dirs = set(pw_rules[0].get("fork_directories", [])) if pw_rules else set()
    required_pw_dirs = {
        "img/frames/planeswalker/regular/",
        "img/frames/planeswalker/tall/",
        "img/frames/planeswalker/compleated/",
    }
    if not required_pw_dirs.issubset(pw_dirs):
        failures.append(f"scryfall-map.json missing Planeswalker dirs: {required_pw_dirs - pw_dirs}")

    pw_nulls = conn.execute(
        "SELECT COUNT(*) FROM frames WHERE original_path LIKE '%planeswalker%' "
        "AND (structural_type_override IS NULL OR structural_type_override != 'planeswalker')"
    ).fetchone()[0]
    if pw_nulls != 0:
        failures.append(f"Planeswalker rows with structural_type_override != 'planeswalker': {pw_nulls}")

    # 3. Verify frames table <-> frames/ directory
    frame_rows = conn.execute("SELECT id, file FROM frames").fetchall()
    db_frame_files = set()
    missing_frames = []
    empty_or_invalid_frames = []
    for fid, fname in frame_rows:
        db_frame_files.add(fname)
        fpath = frames_dir / fname
        if not fpath.is_file():
            missing_frames.append(fname)
        elif not has_valid_header(fpath, "png"):
            empty_or_invalid_frames.append(fname)

    disk_frame_files = {p.name for p in frames_dir.iterdir() if p.is_file()}
    orphan_frames = disk_frame_files - db_frame_files
    if missing_frames:
        failures.append(f"Missing frame files on disk: {len(missing_frames)}")
    if empty_or_invalid_frames:
        failures.append(f"Empty/invalid frame PNGs on disk: {len(empty_or_invalid_frames)}")
    if orphan_frames:
        failures.append(f"Orphan files in frames/: {len(orphan_frames)}")

    # 4. Verify shared_resources table <-> _shared/ directory + fonts load in PIL
    shared_rows = conn.execute("SELECT id, category, symbol_code, file, ext FROM shared_resources").fetchall()
    db_shared_files = set()
    missing_shared = []
    invalid_shared = []
    corrupt_fonts = []
    for sid, cat, code, fname, ext in shared_rows:
        db_shared_files.add(fname)
        spath = shared_dir / fname
        if not spath.is_file():
            missing_shared.append(fname)
            continue
        if not has_valid_header(spath, ext):
            invalid_shared.append(fname)
            continue
        if cat == "font" and ext.lower() in ("ttf", "otf"):
            try:
                font = ImageFont.truetype(str(spath), 32)
                ImageDraw.Draw(Image.new("RGB", (16, 16))).text((0, 0), "A", font=font)
            except Exception as exc:
                corrupt_fonts.append(f"{code} ({fname}): {exc}")

    disk_shared_files = {
        p.name
        for p in shared_dir.iterdir()
        if p.is_file() and p.name not in ALLOWED_CACHE_DIRS
    }
    orphan_shared = disk_shared_files - db_shared_files
    if missing_shared:
        failures.append(f"Missing shared files on disk: {len(missing_shared)}")
    if invalid_shared:
        failures.append(f"Invalid header in shared files: {len(invalid_shared)}")
    if orphan_shared:
        failures.append(f"Orphan files in _shared/: {len(orphan_shared)}")
    if corrupt_fonts:
        failures.append(f"Corrupt fonts in _shared/: {corrupt_fonts}")

    # 5. Verify 0 taxonomy domain violations
    violations = []
    for col, domain in taxonomy.items():
        if col == "frame_effects":
            for (val,) in conn.execute("SELECT frame_effects FROM frames WHERE frame_effects IS NOT NULL"):
                for item in json.loads(val):
                    if item not in domain:
                        violations.append((col, item))
        elif col == "has_nickname":
            for (val,) in conn.execute("SELECT has_nickname FROM frames"):
                if bool(val) not in domain:
                    violations.append((col, val))
        else:
            for (val,) in conn.execute(f"SELECT DISTINCT {col} FROM frames WHERE {col} IS NOT NULL"):
                if val not in domain:
                    violations.append((col, val))
    if violations:
        failures.append(f"Taxonomy domain violations ({len(violations)}): {violations[:10]}")

    conn.close()

    print(f"frames_indexed={len(db_frame_files)} frames_on_disk={len(disk_frame_files)} missing={len(missing_frames)} orphans={len(orphan_frames)} invalid={len(empty_or_invalid_frames)}")
    print(f"shared_indexed={len(db_shared_files)} shared_on_disk={len(disk_shared_files)} missing={len(missing_shared)} orphans={len(orphan_shared)} invalid={len(invalid_shared)}")
    print(f"planeswalker_null_overrides={pw_nulls} corrupt_fonts={len(corrupt_fonts)} taxonomy_violations={len(violations)}")

    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("PASS: All disk <-> SQLite integrity and taxonomy checks succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
