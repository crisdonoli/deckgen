#!/usr/bin/env python3
"""Ingest the CardConjurer fork into assets/resources (frames/, _shared/, assets.db).

    python3 scripts/build_image_db.py --dry-run
    python3 scripts/build_image_db.py
    python3 scripts/build_image_db.py --force
"""

import argparse
import collections
import datetime
import hashlib
import json
import re
import shutil
import sqlite3
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FORK = ASSETS / "cardconjurer"
TAXONOMY_PATH = ASSETS / "taxonomy.json"
MAP_PATH = ASSETS / "scryfall-map.json"
RESOURCES = ASSETS / "resources"
FRAMES_DIR = RESOURCES / "frames"
SHARED_DIR = RESOURCES / "_shared"
DB_PATH = RESOURCES / "assets.db"
MANIFEST_PATH = RESOURCES / "manifest.json"

FRAME_ROOT = "img/frames/"
SHARED_PREFIXES = {
    "img/manaSymbols/": ("mana_symbol", None),
    "img/setSymbols/": ("set_symbol", None),
    "fonts/": ("font", {".ttf", ".otf", ".woff", ".woff2"}),
}
OTHER_TCG_PREFIXES = (
    "img/frames/fab/",
    "img/frames/custom/pokemon/",
    "img/frames/cardbacks/",
)
CUSTOM_MTG_PREFIX = "img/frames/custom/"

MAP_DIMENSIONS = {
    "frame_mapping": "frame",
    "layout_mapping": "layout",
    "structural_type_override_mapping": "structural_type_override",
    "box_variant_mapping": "box_variant",
    "frame_effects_and_finish_mapping": "frame_effects",
    "showcase_style_mapping": "showcase_style",
    "corner_cut_mapping": "corner_cut",
    "border_color_mapping": "border_color",
}
PATTERN_DIMENSIONS = {
    "frame_texture_material_mapping": "frame_texture_material",
    "color_blend_mode_mapping": "color_blend_mode",
    "crown_style_mapping": "crown_style",
}
SINGLE_DIMENSIONS = (
    "frame",
    "layout",
    "structural_type_override",
    "box_variant",
    "crown_style",
    "border_color",
    "corner_cut",
    "frame_texture_material",
    "showcase_style",
    "color_blend_mode",
)
MOM_PREFIX_REFINEMENT = (
    ("img/frames/ravnica/", "ravnica_architecture_mom"),
    ("img/frames/tarkir/", "tarkir_sketch_mom"),
    ("img/frames/crystal/", "ikoria_crystal_mom"),
    ("img/frames/ixalanCoin/", "ixalan_coin_lcc"),
    ("img/frames/invocation/mul/", "invocation_akh"),
    ("img/frames/m15/invention/mul/", "invention_kld"),
    ("img/frames/storybook/mul/", "storybook_eld"),
)
PT_STEMS = {"pt", "r", "u", "b", "g", "w", "c", "m", "a", "l", "t"}
BASE_STEMS = {"frame", "r", "u", "b", "g", "w", "c", "m", "a", "l", "v", "top", "bottom"}

FRAME_COLUMNS = (
    "id", "original_path", "file", "sha256", "width", "height", "frame", "layout",
    "structural_type_override", "box_variant", "frame_effects", "crown_style",
    "has_nickname", "border_color", "corner_cut", "frame_texture_material",
    "showcase_style", "color_blend_mode", "non_official_category", "asset_role",
)
SHARED_COLUMNS = (
    "id", "category", "symbol_code", "file", "original_path", "ext", "sha256",
    "width", "height",
)

DDL = """
CREATE TABLE frames (
    id TEXT PRIMARY KEY,
    original_path TEXT NOT NULL,
    file TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    frame TEXT,
    layout TEXT,
    structural_type_override TEXT,
    box_variant TEXT,
    frame_effects TEXT,
    crown_style TEXT,
    has_nickname INTEGER NOT NULL,
    border_color TEXT,
    corner_cut TEXT,
    frame_texture_material TEXT,
    showcase_style TEXT,
    color_blend_mode TEXT,
    non_official_category TEXT NOT NULL,
    asset_role TEXT NOT NULL
);
CREATE TABLE shared_resources (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    symbol_code TEXT NOT NULL,
    file TEXT NOT NULL,
    original_path TEXT NOT NULL,
    ext TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    width INTEGER,
    height INTEGER
);
CREATE INDEX idx_frames_frame ON frames(frame);
CREATE INDEX idx_frames_layout ON frames(layout);
CREATE INDEX idx_frames_showcase_style ON frames(showcase_style);
CREATE INDEX idx_frames_texture ON frames(frame_texture_material);
CREATE INDEX idx_frames_border ON frames(border_color);
CREATE INDEX idx_frames_original_path ON frames(original_path);
CREATE INDEX idx_shared_category ON shared_resources(category);
CREATE INDEX idx_shared_symbol_code ON shared_resources(symbol_code);
CREATE INDEX idx_shared_original_path ON shared_resources(original_path);
"""


def sha1_hex(data):
    return hashlib.sha1(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def asset_id(rel):
    return hashlib.sha256(rel.encode()).hexdigest()[:16]


def png_size(path):
    with open(path, "rb") as handle:
        head = handle.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def non_official_category(rel):
    if rel.startswith(OTHER_TCG_PREFIXES):
        return "other_tcg_or_accessory"
    if rel.startswith(CUSTOM_MTG_PREFIX):
        return "custom_mtg_community"
    return "official_mtg"


def asset_role(rel):
    name = rel.rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0]
    lower_path = rel.lower()
    if "Mask" in name or stem.lower().startswith("mask"):
        return "mask"
    if "crown" in lower_path or "Crown" in name:
        return "crown"
    if "pt/" in rel and (stem.lower() == "pt" or stem.lower() in PT_STEMS):
        return "pt_box"
    if "stamp" in lower_path:
        return "stamp"
    if "pinline" in stem.lower():
        return "pinline"
    if "border" in stem.lower() or "border" in lower_path:
        return "border"
    if stem.lower() in BASE_STEMS or "Frame" in name:
        return "base_frame"
    return "other"


def symbol_code(rel, category):
    stem = Path(rel).stem
    if category == "font":
        return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "font"
    return stem


def scan_fork():
    frames, shared = [], []
    discarded = collections.Counter()
    thumbs = 0
    font_ignored = 0
    for path in sorted(FORK.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(FORK).as_posix()
        top = rel.split("/", 1)[0]
        suffix = path.suffix.lower()
        if rel.startswith(FRAME_ROOT):
            if suffix != ".png":
                discarded[top] += 1
            elif path.name.lower().endswith("thumb.png"):
                thumbs += 1
            else:
                frames.append(rel)
            continue
        category = None
        for prefix, (cat, extensions) in SHARED_PREFIXES.items():
            if rel.startswith(prefix) and (extensions is None or suffix in extensions):
                category = cat
                break
        if category:
            shared.append((rel, category))
            continue
        if rel.startswith("fonts/") and suffix == ".svg":
            font_ignored += 1
        discarded[top] += 1
    return frames, shared, discarded, thumbs, font_ignored


def compile_pattern_rules(rules):
    return [
        {
            "index": index,
            "value": rule["taxonomy_value"],
            "prefixes": rule.get("path_prefixes", []) + rule.get("fork_directories", []),
            "patterns": [re.compile(pattern) for pattern in rule.get("filename_patterns", [])],
            "exclude": rule.get("exclude_paths", []),
        }
        for index, rule in enumerate(rules)
    ]


def load_rules(mapping):
    by_dimension = collections.defaultdict(list)
    file_rules, patterns = {}, {}
    order = 0
    for section, dimension in MAP_DIMENSIONS.items():
        body = mapping[section]
        rules = body.get("rules") or []
        if isinstance(rules, dict):
            rules = list(rules.values())
        for rule in rules:
            for prefix in rule.get("fork_directories", []):
                by_dimension[dimension].append({
                    "prefix": prefix,
                    "value": rule["taxonomy_value"],
                    "order": order,
                })
                order += 1
            for rel in rule.get("fork_files", []):
                file_rules.setdefault(rel, []).append((dimension, rule["taxonomy_value"]))
    for section, dimension in PATTERN_DIMENSIONS.items():
        for rule in mapping[section].get("rules", []):
            for rel in rule.get("fork_files", []):
                file_rules.setdefault(rel, []).append((dimension, rule["taxonomy_value"]))
        patterns[dimension] = compile_pattern_rules(mapping[section].get("rules", []))
    return {"by_dimension": by_dimension, "files": file_rules, "patterns": patterns}


def best_prefix_value(rel, dimension, rules):
    best = None
    for rule in rules["by_dimension"].get(dimension, []):
        if not rel.startswith(rule["prefix"]):
            continue
        key = (len(rule["prefix"]), -rule["order"])
        if best is None or key > best[0]:
            best = (key, rule["value"])
    return best[1] if best else None


def match_pattern(rel, name, rules, require_all=False):
    haystack = "/" + rel
    best = None
    for rule in rules:
        if any("/" + excluded in haystack for excluded in rule["exclude"]):
            continue
        prefixes = rule["prefixes"]
        matched_prefix = max((prefix for prefix in prefixes if rel.startswith(prefix)), key=len, default=None)
        matched_pattern = any(pattern.search(name) for pattern in rule["patterns"])
        if require_all:
            if prefixes and matched_prefix is None:
                continue
            if rule["patterns"] and not matched_pattern:
                continue
        elif matched_prefix is None and not matched_pattern:
            continue
        # explicit prefix beats a global pattern, which beats a prefix-scoped pattern
        if require_all:
            tier = 3 if rule["patterns"] and matched_pattern else 2
        else:
            tier = 3 if matched_prefix else (2 if not prefixes else 1)
        key = (tier, len(matched_prefix or ""), -rule["index"])
        if best is None or key > best[0]:
            best = (key, rule["value"])
    return best[1] if best else None


def substitute(dimension, value, rel, taxonomy):
    if value in taxonomy[dimension]:
        return value, None
    if dimension == "showcase_style" and value == "multiverse_legends_mom":
        for prefix, refined in MOM_PREFIX_REFINEMENT:
            if rel.startswith(prefix):
                return refined, {"from": value, "to": refined}
    return value, None


def collect_frame_effects(rel, rules, taxonomy):
    values, subs = [], []
    for rule in rules["by_dimension"].get("frame_effects", []):
        if not rel.startswith(rule["prefix"]):
            continue
        value = rule["value"]
        if value not in taxonomy["frame_effects"] and value == "universes_beyond":
            subs.append({"from": value, "to": "showcase"})
            value = "showcase"
        if value not in values:
            values.append(value)
    return values, subs


def resolve_dimensions(rel, rules, taxonomy):
    name = rel.rsplit("/", 1)[-1]
    dims, subs = {}, []
    for dimension in SINGLE_DIMENSIONS:
        value = next(
            (held_value for held_dim, held_value in rules["files"].get(rel, []) if held_dim == dimension),
            None,
        )
        if value is None:
            value = best_prefix_value(rel, dimension, rules)
        if value is None and dimension in rules["patterns"]:
            value = match_pattern(rel, name, rules["patterns"][dimension], dimension == "crown_style")
        if value is None:
            continue
        value, sub = substitute(dimension, value, rel, taxonomy)
        if sub:
            subs.append(sub)
        dims[dimension] = value
    effects, effect_subs = collect_frame_effects(rel, rules, taxonomy)
    if effects:
        dims["frame_effects"] = effects
        subs.extend(effect_subs)
    dims["has_nickname"] = 1 if "/nickname/" in rel else 0
    dims["non_official_category"] = non_official_category(rel)
    dims["asset_role"] = asset_role(rel)
    return dims, subs


def db_value(column, value):
    if column == "frame_effects":
        return json.dumps(value, separators=(",", ":")) if value else None
    return value


def build(args):
    taxonomy = json.loads(TAXONOMY_PATH.read_text())
    duplicates = []

    def track_duplicates(pairs):
        seen = set()
        for key, _ in pairs:
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        return dict(pairs)

    mapping = json.loads(MAP_PATH.read_text(), object_pairs_hook=track_duplicates)
    rules = load_rules(mapping)

    frames, shared, discarded, thumbs, font_ignored = scan_fork()
    stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")

    frame_rows, shared_rows = [], []
    violations = []
    unreadable = []

    for rel in frames:
        dims, subs = resolve_dimensions(rel, rules, taxonomy)
        for dimension, value in dims.items():
            domain = taxonomy.get(dimension)
            if domain is None:
                continue
            candidate = value if dimension != "frame_effects" else None
            if candidate is not None and candidate not in domain:
                violations.append({"dimension": dimension, "value": candidate, "path": rel})
            if dimension == "frame_effects":
                for effect in value:
                    if effect not in domain:
                        violations.append({"dimension": dimension, "value": effect, "path": rel})
        source = FORK / rel
        size = png_size(source)
        if size is None:
            unreadable.append(rel)
        row = {
            "id": asset_id(rel),
            "original_path": rel,
            "file": asset_id(rel) + ".png",
            "sha256": sha256_file(source),
            "width": size[0] if size else None,
            "height": size[1] if size else None,
            "substitutions": subs,
        }
        for column in FRAME_COLUMNS:
            if column not in row:
                row[column] = dims.get(column)
        frame_rows.append(row)

    for rel, category in shared:
        source = FORK / rel
        size = png_size(source) if source.suffix.lower() == ".png" else None
        if source.suffix.lower() == ".png" and size is None:
            unreadable.append(rel)
        suffix = source.suffix.lower().lstrip(".")
        shared_rows.append({
            "id": asset_id(rel),
            "category": category,
            "symbol_code": symbol_code(rel, category),
            "file": asset_id(rel) + (("." + suffix) if suffix else ""),
            "original_path": rel,
            "ext": suffix,
            "sha256": sha256_file(source),
            "width": size[0] if size else None,
            "height": size[1] if size else None,
        })

    if violations:
        for violation in violations[:20]:
            print("ERR:taxonomy_domain_{}_{} {}".format(
                violation["dimension"], violation["value"], violation["path"]))
        print("ERR:taxonomy_domain_total={}".format(len(violations)))
        return 1

    dupe_pairs = {}
    for label, rows in (("frames", frame_rows), ("shared", shared_rows)):
        groups = collections.Counter(row["sha256"] for row in rows)
        dupe_pairs[label] = sum(n * (n - 1) // 2 for n in groups.values() if n > 1)
    total_dupe_pairs = sum(dupe_pairs.values())

    coverage = {}
    for dimension, values in taxonomy.items():
        counts = {}
        for value in values:
            if dimension == "frame_effects":
                count = sum(1 for row in frame_rows if value in (row["frame_effects"] or []))
            elif dimension == "has_nickname":
                count = sum(1 for row in frame_rows if bool(row["has_nickname"]) == bool(value))
            else:
                count = sum(1 for row in frame_rows if row.get(dimension) == value)
            label = str(int(bool(value))) if dimension == "has_nickname" else value
            counts[label] = count
        coverage[dimension] = {
            "values_with_assets": sum(1 for count in counts.values() if count > 0),
            "values_total": len(values),
            "counts": counts,
        }

    stale = []
    for section, body in mapping.items():
        if section == "non_official_fork_assets":
            for dirs in body.values():
                if isinstance(dirs, list):
                    stale.extend(rel for rel in dirs if not (FORK / rel).exists())
            continue
        if not isinstance(body, dict):
            continue
        entries = body.get("rules") or []
        if isinstance(entries, dict):
            entries = list(entries.values())
        for rule in entries:
            for key in ("fork_directories", "fork_files"):
                stale.extend(rel for rel in rule.get(key, []) if not (FORK / rel).exists())

    substitutions = collections.Counter()
    for row in frame_rows:
        for sub in row["substitutions"]:
            substitutions[(sub["from"], sub["to"])] += 1
    substitution_meta = [
        {"from": pair[0], "to": pair[1], "count": count}
        for pair, count in substitutions.items()
    ]

    expected_frames = {row["file"] for row in frame_rows}
    expected_shared = {row["file"] for row in shared_rows}
    populated = (
        FRAMES_DIR.is_dir() and any(FRAMES_DIR.iterdir())
        and SHARED_DIR.is_dir() and any(SHARED_DIR.iterdir())
    )
    store_state = "copied"
    skip_copy = populated and not args.force

    if skip_copy:
        actual_frames = {path.name for path in FRAMES_DIR.iterdir() if path.is_file()}
        actual_shared = {path.name for path in SHARED_DIR.iterdir() if path.is_file()}
        if actual_frames != expected_frames or actual_shared != expected_shared:
            print("ERR:store_mismatch frames_extra={} frames_missing={} shared_extra={} shared_missing={}".format(
                len(actual_frames - expected_frames), len(expected_frames - actual_frames),
                len(actual_shared - expected_shared), len(expected_shared - actual_shared)))
            print("hint: rerun with --force")
            return 2
        store_state = "skipped_valid"

    validation = {
        "counts": {
            "frames": len(frame_rows),
            "shared": len(shared_rows),
            "discarded": sum(discarded.values()),
            "thumbs_excluded": thumbs,
            "content_dupes": total_dupe_pairs,
            "png_unreadable": len(unreadable),
            "font_svg_ignored": font_ignored,
        },
        "discarded_by_top_dir": dict(sorted(discarded.items(), key=lambda item: -item[1])),
        "domain_violations": len(violations),
        "coverage": {
            dimension: "{}/{}".format(stats["values_with_assets"], stats["values_total"])
            for dimension, stats in coverage.items()
        },
        "stale_prefixes": stale,
        "content_dupes": {
            "pairs": total_dupe_pairs,
            "frames_pairs": dupe_pairs["frames"],
            "shared_pairs": dupe_pairs["shared"],
        },
        "duplicate_json_keys": duplicates,
        "map_mom_condition": "set in ['mom', 'mul']" in json.dumps(mapping["showcase_style_mapping"]),
        "store": "dry-run" if args.dry_run else store_state,
    }

    print("frames={} shared={} discarded={} thumbs_excluded={} png_unreadable={}".format(
        len(frame_rows), len(shared_rows), sum(discarded.values()), thumbs, len(unreadable)))
    print("domain_violations={}".format(len(violations)))
    for dimension in ("frame_texture_material", "color_blend_mode", "border_color", "corner_cut"):
        print("coverage.{}={}".format(dimension, validation["coverage"][dimension]))
    for dimension, stats in coverage.items():
        print("coverage {} {}/{}".format(
            dimension, stats["values_with_assets"], stats["values_total"]))
    print("stale_prefixes={} {}".format(len(stale), stale))
    print("discarded_by_top_dir={}".format(validation["discarded_by_top_dir"]))
    print("content_dupes={} {}".format(total_dupe_pairs, dupe_pairs))
    print("store={}".format(validation["store"]))

    if args.dry_run:
        return 0

    RESOURCES.mkdir(parents=True, exist_ok=True)
    for leftover in RESOURCES.glob("*.png"):
        leftover.unlink()
    for leftover in ("index.json", "coverage.json"):
        path = RESOURCES / leftover
        if path.exists():
            path.unlink()

    if not skip_copy:
        if args.force:
            for directory in (FRAMES_DIR, SHARED_DIR):
                if directory.is_dir():
                    shutil.rmtree(directory)
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        SHARED_DIR.mkdir(parents=True, exist_ok=True)
        for row in frame_rows:
            shutil.copy2(FORK / row["original_path"], FRAMES_DIR / row["file"])
        for row in shared_rows:
            shutil.copy2(FORK / row["original_path"], SHARED_DIR / row["file"])

    manifest = {
        "meta": {
            "generated": stamp,
            "taxonomy_sha1": sha1_hex(TAXONOMY_PATH.read_bytes()),
            "map_sha1": sha1_hex(MAP_PATH.read_bytes()),
            "counts": validation["counts"],
            "substitutions": substitution_meta,
            "coverage": coverage,
            "validation": validation,
        },
        "frames": frame_rows,
        "shared": shared_rows,
    }

    tmp_db = DB_PATH.with_suffix(".tmp")
    if tmp_db.exists():
        tmp_db.unlink()
    connection = sqlite3.connect(tmp_db)
    connection.executescript(DDL)
    connection.executemany(
        "INSERT INTO frames ({}) VALUES ({})".format(
            ", ".join(FRAME_COLUMNS), ", ".join("?" * len(FRAME_COLUMNS))),
        [tuple(db_value(column, row[column]) for column in FRAME_COLUMNS) for row in frame_rows],
    )
    connection.executemany(
        "INSERT INTO shared_resources ({}) VALUES ({})".format(
            ", ".join(SHARED_COLUMNS), ", ".join("?" * len(SHARED_COLUMNS))),
        [tuple(row[column] for column in SHARED_COLUMNS) for row in shared_rows],
    )
    connection.commit()
    connection.close()
    tmp_db.replace(DB_PATH)

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print("db={} manifest={}".format(DB_PATH, MANIFEST_PATH))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Ingest CardConjurer assets into assets/resources")
    parser.add_argument("--dry-run", action="store_true", help="report without copying or writing")
    parser.add_argument("--force", action="store_true", help="rebuild frames/ and _shared/ from scratch")
    return build(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
