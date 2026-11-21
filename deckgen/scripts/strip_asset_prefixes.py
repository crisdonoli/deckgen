#!/usr/bin/env python3
"""Clean up template asset file names.

Removes the numeric PSD-layer prefix and the "_[oculta]" (hidden layer) suffix:

    "Background/001_W.jpg"              -> "Background/W.jpg"
    "PT Box/147_W_[oculta].pdf"         -> "PT Box/W.pdf"

Only files inside ``assets/Templates`` (or the older ``Automated Templates`` /
``Manual Templates`` folders) are touched. The .jpg/.pdf pair of a layer always gets the same new name. If two
layers in the same folder would end up with the same name, the later ones get
" (2)", " (3)"... in their original numeric order.

Optionally (--delete-unused) deletes what the app never reads:
  - the "Text and Icons" / "Text & Icons" and "Legal" folders of every style (the
    Card Builder draws text, mana and set symbols itself);
  - "Border Crop" and "... Reference" layers (guides from the PSD templates).
scan_template_catalog() skips all of them. Can be run again after the rename.

Usage:
    python scripts/strip_asset_prefixes.py                          # dry run
    python scripts/strip_asset_prefixes.py --delete-unused          # dry run incl. deletion
    python scripts/strip_asset_prefixes.py --apply [--delete-unused]
    python scripts/strip_asset_prefixes.py --revert                 # undo the rename

The rename log is written to ``assets/.prefix_rename_log.json`` (old -> new,
relative to assets/) so the rename can be reverted. Deleted files and folders
can NOT be restored by --revert; re-download them from the original assets if needed.

Saved projects (state.json) don't need to be edited by hand: the backend maps
old paths to the new names when a project is loaded.
"""
import argparse
import json
import os
import re
import shutil
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(ROOT, "assets")
GROUPS = ("Templates", "Automated Templates", "Manual Templates")
UNUSED_FOLDERS = ("Text and Icons", "Text & Icons", "Legal")
UNUSED_FILE_RE = re.compile(r"(Border Crop|Reference)$", re.IGNORECASE)  # matched on the clean stem
LOG_PATH = os.path.join(ASSETS_DIR, ".prefix_rename_log.json")
PREFIX_RE = re.compile(r"^(\d+)_(?=.)")
HIDDEN_RE = re.compile(r"_\[oculta\]$", re.IGNORECASE)


def clean_stem(stem):
    return HIDDEN_RE.sub("", PREFIX_RE.sub("", stem))


def sort_key(stem):
    m = PREFIX_RE.match(stem)
    return (int(m.group(1)) if m else -1, stem)


def find_unused_dirs():
    found = []
    for group in GROUPS:
        group_dir = os.path.join(ASSETS_DIR, group)
        if not os.path.isdir(group_dir):
            continue
        for root, dirs, _ in os.walk(group_dir):
            for d in list(dirs):
                if d in UNUSED_FOLDERS:
                    found.append(os.path.join(root, d))
                    dirs.remove(d)
    return sorted(found)


def find_unused_files(skip_dirs=()):
    skip = {os.path.normpath(d) for d in skip_dirs}
    found = []
    for group in GROUPS:
        group_dir = os.path.join(ASSETS_DIR, group)
        if not os.path.isdir(group_dir):
            continue
        for root, dirs, files in os.walk(group_dir):
            dirs[:] = [d for d in dirs if os.path.normpath(os.path.join(root, d)) not in skip]
            for f in files:
                if UNUSED_FILE_RE.search(clean_stem(os.path.splitext(f)[0])):
                    found.append(os.path.join(root, f))
    return sorted(found)


def build_plan(skip_dirs=(), skip_files=()):
    """Return a list of (old_rel, new_rel) pairs, relative to ASSETS_DIR."""
    skip = {os.path.normpath(d) for d in skip_dirs}
    skip_f = {os.path.normpath(f) for f in skip_files}
    plan = []
    for group in GROUPS:
        group_dir = os.path.join(ASSETS_DIR, group)
        if not os.path.isdir(group_dir):
            continue
        for root, dirs, files in os.walk(group_dir):
            dirs[:] = [d for d in dirs if os.path.normpath(os.path.join(root, d)) not in skip]
            files = [
                f for f in files
                if not f.startswith(".") and os.path.normpath(os.path.join(root, f)) not in skip_f
            ]
            # group the files of one layer (same stem, any extension) by their clean stem
            layers = defaultdict(set)
            for f in files:
                stem = os.path.splitext(f)[0]
                layers[clean_stem(stem)].add(stem)
            taken = set()
            for clean, stems in sorted(layers.items()):
                for idx, orig_stem in enumerate(sorted(stems, key=sort_key)):
                    new_stem = clean if idx == 0 else f"{clean} ({idx + 1})"
                    if new_stem in taken:
                        sys.exit(f"Conflict in {root}: {new_stem}")
                    taken.add(new_stem)
                    if new_stem == orig_stem:
                        continue
                    for f in files:
                        base, ext = os.path.splitext(f)
                        if base == orig_stem:
                            plan.append((
                                os.path.relpath(os.path.join(root, f), ASSETS_DIR),
                                os.path.relpath(os.path.join(root, new_stem + ext), ASSETS_DIR),
                            ))
    return sorted(plan)


def dir_size_gb(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / 1024 ** 3


def apply(plan):
    if os.path.exists(LOG_PATH):
        sys.exit(f"{LOG_PATH} already exists. Revert first or delete it.")
    done = []
    try:
        for old, new in plan:
            new_abs = os.path.join(ASSETS_DIR, new)
            if os.path.exists(new_abs):
                raise SystemExit(f"Refusing to overwrite {new_abs}")
            os.rename(os.path.join(ASSETS_DIR, old), new_abs)
            done.append([old, new])
    finally:
        with open(LOG_PATH, "w", encoding="utf-8") as fh:
            json.dump(done, fh, ensure_ascii=False, indent=1)
    print(f"Renamed {len(done)} files. Log: {LOG_PATH}")


def revert():
    if not os.path.exists(LOG_PATH):
        sys.exit(f"No log found at {LOG_PATH}")
    with open(LOG_PATH, encoding="utf-8") as fh:
        done = json.load(fh)
    for old, new in reversed(done):
        new_abs = os.path.join(ASSETS_DIR, new)
        if os.path.exists(new_abs):
            os.rename(new_abs, os.path.join(ASSETS_DIR, old))
    os.remove(LOG_PATH)
    print(f"Reverted {len(done)} files.")


def main():
    global ASSETS_DIR, LOG_PATH
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="make the changes (default is a dry run)")
    ap.add_argument("--delete-unused", action="store_true",
                    help=f"also delete the {' / '.join(UNUSED_FOLDERS)} folders and the "
                         "Border Crop / Reference layers (not revertible)")
    ap.add_argument("--revert", action="store_true", help="undo a previous rename using the log")
    ap.add_argument("--assets-dir", default=ASSETS_DIR, help="assets folder (default: <repo>/assets)")
    args = ap.parse_args()

    ASSETS_DIR = os.path.abspath(args.assets_dir)
    LOG_PATH = os.path.join(ASSETS_DIR, ".prefix_rename_log.json")

    if args.revert:
        revert()
        return

    unused = find_unused_dirs() if args.delete_unused else []
    unused_files = find_unused_files(skip_dirs=unused) if args.delete_unused else []
    plan = build_plan(skip_dirs=unused, skip_files=unused_files)
    collisions = [(o, n) for o, n in plan if re.search(r" \(\d+\)\.\w+$", n)]

    if not args.apply:
        for old, new in plan[:10]:
            print(f"{old}\n  -> {os.path.basename(new)}")
        print(f"{len(plan)} files would be renamed.")
        if collisions:
            print("Name collisions resolved with a suffix:")
            for old, new in collisions:
                print(f"  {old} -> {os.path.basename(new)}")
        if unused:
            gb = sum(dir_size_gb(d) for d in unused)
            print(f"{len(unused)} unused folders would be deleted ({gb:.1f} GB), e.g.:")
            for d in unused[:5]:
                print(f"  {os.path.relpath(d, ASSETS_DIR)}")
        if unused_files:
            gb = sum(os.path.getsize(f) for f in unused_files) / 1024 ** 3
            names = sorted({os.path.basename(f) for f in unused_files})
            print(f"{len(unused_files)} unused files would be deleted ({gb:.1f} GB): {', '.join(names)}")
        print("Dry run only. Re-run with --apply to make the changes.")
        return

    for d in unused:
        shutil.rmtree(d)
    if unused:
        print(f"Deleted {len(unused)} unused folders.")
    for f in unused_files:
        os.remove(f)
    if unused_files:
        print(f"Deleted {len(unused_files)} unused files.")
    if plan:
        apply(plan)
    else:
        print("Nothing to rename.")


if __name__ == "__main__":
    main()
