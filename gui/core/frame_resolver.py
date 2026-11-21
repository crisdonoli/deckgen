"""Resolve a Scryfall card into a frame recipe backed by assets/resources/assets.db."""
import argparse
import json
import re
import sqlite3
import sys
from copy import deepcopy
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_MAP_PATH = _ROOT / "assets" / "scryfall-map.json"
_DEFAULT_DB = _ROOT / "assets" / "resources" / "assets.db"

try:
    from .card_layouts import DEFAULT_LAYOUT, get_template_layout
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from core.card_layouts import DEFAULT_LAYOUT, get_template_layout

CANVAS = {"width": 1500, "height": 2100}
_LAYOUT_BASE = {"w": DEFAULT_LAYOUT["canvas"]["w"], "h": DEFAULT_LAYOUT["canvas"]["h"]}
_SCALE = CANVAS["width"] / float(_LAYOUT_BASE["w"])

FACE_LAYOUTS = ("transform", "modal_dfc", "reversible_card", "double_faced_token")
DIMS = (
    "frame",
    "layout",
    "structural_type_override",
    "box_variant",
    "crown_style",
    "showcase_style",
    "frame_texture_material",
    "color_blend_mode",
    "border_color",
    "corner_cut",
    "has_nickname",
)
_ROLE_SQL = (
    "SELECT id, original_path, file, asset_role, frame, layout, structural_type_override, "
    "box_variant, frame_effects, crown_style, has_nickname, border_color, corner_cut, "
    "frame_texture_material, showcase_style, color_blend_mode, non_official_category, width, height "
    "FROM frames"
)
_MONO_TEXTURE = {
    "W": "white_marble",
    "U": "blue_water",
    "B": "black_swamp",
    "R": "red_volcanic",
    "G": "green_bark",
}
_MAP = None


def _map():
    global _MAP
    if _MAP is None:
        _MAP = json.loads(_MAP_PATH.read_text())
    return _MAP


def _eval(cond, ctx):
    if cond is None or cond == "default":
        return True, None
    expr = re.sub(r"\btrue\b", "True", str(cond))
    expr = re.sub(r"\bfalse\b", "False", expr)
    scope = {"__builtins__": {}, "len": len, "any": any, "all": all, "bool": bool, "set": set, "sorted": sorted}
    try:
        return bool(eval(expr, scope, ctx)), None
    except Exception as exc:  # noqa: BLE001 - map conditions are data, not code
        return False, "%s: %s" % (type(exc).__name__, exc)


def _eval_material(expr, ctx):
    if not isinstance(expr, str) or (" if " not in expr and " else " not in expr):
        return expr
    scope = {"__builtins__": {}, "len": len, "any": any, "all": all, "bool": bool, "set": set, "sorted": sorted}
    return eval(expr, scope, ctx)


def _ctx(card, face):
    src = dict(card)
    if face:
        src.update({k: v for k, v in face.items() if not k.startswith("_")})
    names = [f.get("name") for f in (card.get("card_faces") or []) if f.get("name")]
    if not names and src.get("name"):
        names = [src["name"]]

    def val(key, default):
        return src.get(key) if src.get(key) is not None else default

    return {
        "set": val("set", ""),
        "lang": val("lang", "en"),
        "frame": str(val("frame", "")),
        "frame_effects": val("frame_effects", []),
        "border_color": val("border_color", ""),
        "type_line": val("type_line", ""),
        "oracle_text": val("oracle_text", ""),
        "layout": val("layout", "normal"),
        "keywords": val("keywords", []),
        "promo_types": val("promo_types", []),
        "finishes": val("finishes", []),
        "security_stamp": val("security_stamp", ""),
        "colors": val("colors", []),
        "color_identity": val("color_identity", []),
        "produced_mana": val("produced_mana", []),
        "mana_cost": val("mana_cost", ""),
        "rarity": val("rarity", ""),
        "textless": bool(val("textless", False)),
        "full_art": bool(val("full_art", False)),
        "flavor_name": val("flavor_name", ""),
        "names": names,
        "name": val("name", ""),
    }


def _art_crop(card, face):
    face = face or {}
    uris = face.get("image_uris") or {}
    if uris.get("art_crop"):
        return uris["art_crop"]
    uris = card.get("image_uris") or {}
    return uris.get("art_crop")


def resolve_faces(card):
    faces = card.get("card_faces") or []
    if card.get("layout") in FACE_LAYOUTS and faces:
        out = []
        for idx, face in enumerate(faces):
            merged = dict(card)
            merged.update(face)
            merged["_face_index"] = idx
            merged["_face_ref"] = face.get("name")
            merged["_art_crop"] = _art_crop(card, face)
            merged["_notes"] = []
            if not merged["_art_crop"]:
                merged["_notes"].append("no_art_crop")
            out.append(merged)
        return out
    merged = dict(card)
    merged["_face_index"] = None
    merged["_face_ref"] = card.get("name")
    merged["_art_crop"] = _art_crop(card, None)
    merged["_notes"] = []
    if not merged["_art_crop"]:
        merged["_notes"].append("no_art_crop")
    return [merged]


def _first_true(rules, ctx, notes, dim):
    for idx, rule in enumerate(rules):
        cond = rule.get("condition")
        ok, err = _eval(cond, ctx)
        if err:
            notes.append("condition_error:%s:%s" % (dim, cond))
        if ok:
            return rule, idx, cond
    return None, None, None


def infer_taxonomy(card, face=None):
    m = _map()
    ctx = _ctx(card, face)
    notes = []
    trace = {}
    tax = {}

    frame_rules = m["frame_mapping"]["rules"]
    frame_val = ctx["frame"]
    if frame_val in frame_rules:
        tax["frame"] = frame_rules[frame_val].get("taxonomy_value", "2015")
        trace["frame"] = {
            "section": "frame_mapping",
            "rule": frame_val,
            "condition": None,
            "fork_directories": list(frame_rules[frame_val].get("fork_directories") or []),
        }
    else:
        tax["frame"] = "2015"
        notes.append("frame_default_2015")
        trace["frame"] = {"section": "frame_mapping", "rule": None, "condition": None, "fork_directories": []}

    layout_rules = m["layout_mapping"]["rules"]
    layout_key = ctx["layout"]
    cond = None
    rule = None
    if layout_key == "split" and "Aftermath" in ctx["keywords"] and "aftermath" in layout_rules:
        rule, layout_key, cond = layout_rules["aftermath"], "aftermath", layout_rules["aftermath"].get("condition")
    elif layout_key in layout_rules:
        rule = layout_rules[layout_key]
        cond = rule.get("condition")
    if rule is not None:
        ok, err = _eval(cond, ctx)
        if err:
            notes.append("condition_error:layout:%s" % cond)
        tax["layout"] = rule.get("taxonomy_value") if ok else None
        if not ok:
            notes.append("layout_condition_false")
    else:
        tax["layout"] = None
        notes.append("layout_no_rule")
    trace["layout"] = {
        "section": "layout_mapping",
        "rule": layout_key,
        "condition": cond,
        "fork_directories": list((rule or {}).get("fork_directories") or []),
    }

    structural = None
    for idx, rule in enumerate(m["structural_type_override_mapping"]["rules"]):
        match = rule.get("match")
        if match is not None:
            hit = match in ctx["type_line"]
            condition = "match:%s" % match
        else:
            hit, err = _eval(rule.get("condition"), ctx)
            condition = rule.get("condition")
            if err:
                notes.append("condition_error:structural_type_override:%s" % condition)
        if hit:
            structural = rule.get("taxonomy_value")
            trace["structural_type_override"] = {
                "section": "structural_type_override_mapping",
                "rule": idx,
                "condition": condition,
                "fork_directories": list(rule.get("fork_directories") or []),
            }
            break
    if structural is None:
        allowed = [
            r.get("taxonomy_value")
            for r in m["structural_type_override_mapping"]["rules"]
            if r.get("taxonomy_value") == "standard"
        ]
        structural = "standard" if allowed else None
        notes.append("structural_type_override_no_rule")
        trace["structural_type_override"] = {
            "section": "structural_type_override_mapping",
            "rule": None,
            "condition": None,
            "fork_directories": [],
        }
    tax["structural_type_override"] = structural

    box_rules = m["box_variant_mapping"]["rules"]
    box_rule, box_idx, box_cond = _first_true(box_rules, ctx, notes, "box_variant")
    if box_rule is None:
        tax["box_variant"] = "regular"
        trace["box_variant"] = {
            "section": "box_variant_mapping",
            "rule": None,
            "condition": None,
            "fork_directories": [],
        }
    else:
        tax["box_variant"] = box_rule.get("taxonomy_value", "regular")
        trace["box_variant"] = {
            "section": "box_variant_mapping",
            "rule": box_idx,
            "condition": box_cond,
            "fork_directories": list(box_rule.get("fork_directories") or []),
        }

    effects = []
    fx_forks = []
    fx_keys = []
    fx_rules = m["frame_effects_and_finish_mapping"]["rules"]
    for key, rule in fx_rules.items():
        in_source = key in ctx["frame_effects"] or key in ctx["finishes"] or key in ctx["promo_types"]
        ok = False
        cond = rule.get("condition")
        if cond is not None:
            ok, err = _eval(cond, ctx)
            if err:
                notes.append("condition_error:frame_effects:%s" % cond)
        if in_source or ok:
            fx_keys.append(key)
            fx_forks.extend(rule.get("fork_directories") or [])
            value = rule.get("taxonomy_value")
            if value == "universes_beyond":
                value = "showcase"
                notes.append("substituted:universes_beyond->showcase")
            if value and value not in effects:
                effects.append(value)
    tax["frame_effects"] = effects
    trace["frame_effects"] = {
        "section": "frame_effects_and_finish_mapping",
        "rule": fx_keys,
        "condition": None,
        "fork_directories": fx_forks,
    }

    crown_rule, crown_idx, crown_cond = _first_true(m["crown_style_mapping"]["rules"], ctx, notes, "crown_style")
    tax["crown_style"] = crown_rule.get("taxonomy_value", "none") if crown_rule else "none"
    trace["crown_style"] = {
        "section": "crown_style_mapping",
        "rule": crown_idx,
        "condition": crown_cond,
        "fork_directories": list((crown_rule or {}).get("fork_directories") or []),
    }
    if tax["crown_style"] == "none":
        legendary = (
            "Legendary" in ctx["type_line"]
            or "legendary" in ctx["frame_effects"]
            or "showcase" in ctx["frame_effects"]
        )
        if legendary:
            floating = ctx["border_color"] == "borderless" or "extendedart" in ctx["frame_effects"]
            tax["crown_style"] = "floating" if floating else "standard"
            notes.append("crown_style_fallback:%s" % tax["crown_style"])
            trace["crown_style"]["fallback"] = tax["crown_style"]

    tax["has_nickname"] = bool(ctx["flavor_name"])
    nickname_key = "is_not_null" if tax["has_nickname"] else "is_null"
    nickname_rule = m["has_nickname_mapping"]["rules"].get(nickname_key) or {}
    trace["has_nickname"] = {
        "section": "has_nickname_mapping",
        "rule": nickname_key,
        "condition": None,
        "fork_directories": list(nickname_rule.get("fork_directories") or []),
    }

    border_rules = m["border_color_mapping"]["rules"]
    border = ctx["border_color"]
    if border in border_rules and border != "borderless":
        tax["border_color"] = border
    else:
        tax["border_color"] = "black"
        notes.append("border_color_default_black")
    trace["border_color"] = {
        "section": "border_color_mapping",
        "rule": border,
        "condition": None,
        "fork_directories": list((border_rules.get(border) or {}).get("fork_directories") or []),
    }

    corner_rules = m["corner_cut_mapping"]["rules"]
    corner_rule = None
    corner_key = None
    for key, rule in corner_rules.items():
        ok, err = _eval(rule.get("condition"), ctx)
        if err:
            notes.append("condition_error:corner_cut:%s" % rule.get("condition"))
        if ok:
            corner_rule, corner_key = rule, key
            break
    tax["corner_cut"] = corner_rule.get("taxonomy_value", "modern_radius") if corner_rule else "modern_radius"
    trace["corner_cut"] = {
        "section": "corner_cut_mapping",
        "rule": corner_key,
        "condition": corner_rule.get("condition") if corner_rule else None,
    }

    texture = None
    blend = None
    texture_pair = None
    texture_rule = None
    for idx, rule in enumerate(m["texture_and_color_blend_mapping"]["file_suffix_rules"]):
        ok, err = _eval(rule.get("condition"), ctx)
        if err:
            notes.append("condition_error:texture:%s" % rule.get("condition"))
        if ok:
            texture_rule = rule
            texture = _eval_material(rule.get("texture_material"), ctx)
            blend = rule.get("color_blend_mode")
            trace["frame_texture_material"] = {
                "section": "texture_and_color_blend_mapping",
                "rule": idx,
                "condition": rule.get("condition"),
            }
            break
    if texture_rule is None:
        notes.append("texture_no_rule")
        trace["frame_texture_material"] = {
            "section": "texture_and_color_blend_mapping",
            "rule": None,
            "condition": None,
        }
    if texture == "hybrid_pair":
        colors = ctx["colors"]
        texture_pair = [_MONO_TEXTURE.get(c) for c in colors[:2]]
        texture = None
        blend = "hybrid_gradient"
        notes.append("hybrid_pair_not_in_taxonomy")
    tax["frame_texture_material"] = texture
    tax["color_blend_mode"] = blend
    trace["color_blend_mode"] = dict(trace["frame_texture_material"])

    showcase_rule, showcase_idx, showcase_cond = _first_true(
        m["showcase_style_mapping"]["rules"], ctx, notes, "showcase_style"
    )
    if showcase_rule is None:
        tax["showcase_style"] = "none"
    else:
        value = showcase_rule.get("taxonomy_value")
        if value == "multiverse_legends_mom":
            tax["showcase_style"] = None
            notes.append("mom_multiverse_ambiguous")
        else:
            tax["showcase_style"] = value
    trace["showcase_style"] = {
        "section": "showcase_style_mapping",
        "rule": showcase_idx,
        "condition": showcase_cond,
        "fork_directories": list((showcase_rule or {}).get("fork_directories") or []),
    }
    override = face.get("showcase_style_override") if face else None
    if override is None:
        override = card.get("showcase_style_override")
    if override is not None:
        tax["showcase_style"] = override
        notes.append("showcase_style_override:%s" % override)
        trace["showcase_style"] = {
            "section": "showcase_style_mapping",
            "rule": "override",
            "condition": None,
        }

    tax["_trace"] = trace
    tax["_notes"] = notes
    tax["_texture_pair"] = texture_pair
    dir_set, dir_warning = _frame_dir_set(trace, tax)
    tax["_frame_dir_set"] = dir_set
    trace["frame_dir_set"] = {"directories": dir_set, "warning": dir_warning}
    if dir_warning:
        notes.append(dir_warning)
    return tax


def _json_list(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _score(asset, tax):
    matched = []
    unmatched = []
    total = 0
    for dim in DIMS:
        av = asset.get(dim)
        if av is None:
            continue
        total += 1
        tv = tax.get(dim)
        if dim == "has_nickname":
            av = bool(av)
        if tv == av:
            matched.append(dim)
        else:
            unmatched.append(dim)
    return (len(matched) / total if total else 0.0), matched, unmatched


def _face_key(asset):
    name = str(asset.get("original_path") or "").rsplit("/", 1)[-1].lower()
    if name.startswith("front"):
        return 0
    if name.startswith("back"):
        return 1
    return None


def _face_ranked(asset, layout, face_index):
    if layout not in FACE_LAYOUTS or face_index not in (0, 1):
        return 0.0
    return 0.25 if _face_key(asset) == face_index else 0.0


def _face_rows(rows, layout, face_index, strict=False):
    if layout not in FACE_LAYOUTS or face_index not in (0, 1):
        return rows
    keys = [_face_key(row) for row in rows]
    if 0 not in keys or 1 not in keys:
        return rows
    if strict:
        return [row for row, key in zip(rows, keys) if key == face_index]
    return [row for row, key in zip(rows, keys) if key != 1 - face_index]


def _ranked(rows, tax, face_index=None):
    scored = []
    effects = set(tax.get("frame_effects") or [])
    layout = tax.get("layout")
    for asset in rows:
        score, matched, unmatched = _score(asset, tax)
        overlap = bool(effects & set(_json_list(asset.get("frame_effects"))))
        scored.append(
            {
                "asset": asset,
                "score": score,
                "face": _face_ranked(asset, layout, face_index),
                "matched": matched,
                "unmatched": unmatched,
                "overlap": overlap,
            }
        )
    strict = [item for item in scored if not item["unmatched"]]
    if strict:
        strict.sort(
            key=lambda item: (
                -int(item["overlap"]),
                -item["score"],
                -item["face"],
                item["asset"]["original_path"].count("/"),
                item["asset"]["original_path"],
            )
        )
        return strict
    scored.sort(
        key=lambda item: (
            -int(item["overlap"]),
            len(item["unmatched"]),
            -item["score"],
            -item["face"],
            item["asset"]["original_path"].count("/"),
            item["asset"]["original_path"],
        )
    )
    return scored


def _rows(conn, roles, extra="", prefixes=None):
    marks = ",".join("?" for _ in roles)
    params = list(roles)
    sql = _ROLE_SQL + " WHERE asset_role IN (%s)" % marks
    if prefixes:
        sql += " AND (" + " OR ".join("original_path LIKE ?" for _ in prefixes) + ")"
        params += [p + "%" for p in prefixes]
    if extra:
        sql += " AND " + extra
    cursor = conn.execute(sql, params)
    keys = [d[0] for d in cursor.description]
    return [dict(zip(keys, row)) for row in cursor]


def _official(rows, notes):
    official = [row for row in rows if row.get("non_official_category") == "official_mtg"]
    if official:
        return official
    if rows:
        notes.append("non_official_fallback")
    return rows


def _select(rows, tax, notes, face_index=None):
    return _ranked(_official(rows, notes), tax, face_index)


def _dir_path(original_path):
    return original_path.rsplit("/", 1)[0]


def _common_segments(left, right):
    count = 0
    for a, b in zip(left.split("/"), right.split("/")):
        if a != b:
            break
        count += 1
    return count


def _fork_dirs(trace, section):
    return [p for p in ((trace.get(section) or {}).get("fork_directories") or []) if p]


def _frame_dir_set(trace, tax):
    layout = _fork_dirs(trace, "layout")
    structural = _fork_dirs(trace, "structural_type_override")
    showcase = _fork_dirs(trace, "showcase_style") if tax.get("showcase_style") not in (None, "none") else []
    candidates = [lst for lst in (showcase, structural, layout) if lst]
    if not candidates:
        return [], None
    base = max(candidates, key=lambda lst: max(len(p) for p in lst))
    frame = _fork_dirs(trace, "frame")
    compatible = [
        p
        for p in base
        if any(_common_segments(p, q) >= 3 for q in frame + structural)
    ]
    if compatible:
        return compatible, None
    return base, "dir_scope_relaxed"


def _face_hit(asset, layout, face_index):
    if layout not in FACE_LAYOUTS or face_index not in (0, 1):
        return 0
    name = str(asset.get("original_path") or "").rsplit("/", 1)[-1].lower()
    want = "front" if face_index == 0 else "back"
    return 1 if want in name else 0


def _frame_dir_rows(conn, role, tax, base_dirs, prefixes=None, face_index=None):
    layout = tax.get("layout")
    anchors = base_dirs or prefixes or []
    pool = [
        row
        for row in _rows(conn, (role,), prefixes=prefixes)
        if layout is not None and row.get("layout") in (None, layout)
    ]
    depth = {}
    hits = {}
    for row in pool:
        directory = _dir_path(row["original_path"])
        segments = max((_common_segments(directory, base) for base in anchors), default=0)
        if segments >= 3:
            depth[directory] = max(depth.get(directory, 0), segments)
            hits[directory] = hits.get(directory, 0) + _face_hit(row, layout, face_index)
    if not depth:
        return [], None
    best = max(depth, key=lambda directory: (hits[directory], depth[directory], directory))
    rows = _face_rows(pool, layout, face_index)
    return [row for row in rows if _dir_path(row["original_path"]) == best], best


def _crown_dirs(tax):
    if tax.get("layout") in ("transform", "modal_dfc"):
        return [
            "img/frames/m15/transform/crowns/regular/",
            "img/frames/m15/transform/crowns/",
            "img/frames/m15/crowns/new/",
            "img/frames/m15/crowns/",
        ]
    if tax.get("crown_style") == "standard":
        return ["img/frames/m15/crowns/new/", "img/frames/m15/crowns/"]
    return ["img/frames/m15/crowns/"]


def _pick_dir(rows, directories):
    for directory in directories:
        hits = [row for row in rows if row["original_path"].startswith(directory)]
        if hits:
            return hits, directory
    return rows, None


def _layer(z, asset, pick):
    return {
        "z_index": z,
        "asset_role": asset.get("asset_role"),
        "id": asset.get("id"),
        "filename": asset.get("file"),
        "original_path": asset.get("original_path"),
        "width": asset.get("width"),
        "height": asset.get("height"),
        "match_score": round(pick["score"], 4),
        "dims_matched": pick["matched"],
        "dims_unmatched": pick["unmatched"],
    }


def select_layers(tax, face, conn):
    face = face or {}
    face_index = face.get("_face_index")
    layout = tax.get("layout")
    layers = []
    notes = []
    m = _map()
    pair = tax.get("_texture_pair")
    dir_set = list(tax.get("_frame_dir_set") or [])
    scope = dir_set[0] if dir_set else "no_scope"

    mask_rows, mask_dir = _frame_dir_rows(conn, "mask", tax, dir_set, prefixes=dir_set, face_index=face_index)
    mask_rows = _official(mask_rows, notes)
    pinline_rows, pinline_dir = _frame_dir_rows(
        conn, "pinline", tax, [mask_dir] if mask_dir else dir_set, prefixes=dir_set, face_index=face_index
    )
    pinline_rows = _official(pinline_rows, notes)

    base_rows = _rows(conn, ("base_frame",), prefixes=dir_set) if dir_set else _rows(conn, ("base_frame",))
    anchor_dir = mask_dir or pinline_dir
    if anchor_dir:
        same_dir = [row for row in base_rows if _dir_path(row["original_path"]) == anchor_dir]
        if same_dir:
            base_rows = same_dir
        else:
            notes.append("base_dir_relaxed")
    base_rows = _face_rows(base_rows, layout, face_index)

    if tax.get("color_blend_mode") == "hybrid_gradient" and pair:
        for i, material in enumerate(pair):
            if not material:
                continue
            sub = dict(tax)
            sub["frame_texture_material"] = material
            sub["color_blend_mode"] = "monocolor"
            ranked = _select(base_rows, sub, notes, face_index)
            if ranked:
                layers.append(_layer(10 if i == 0 else 15, ranked[0]["asset"], ranked[0]))
            else:
                notes.append("no_base_frame_for_texture:%s" % material)
    else:
        ranked = _select(base_rows, tax, notes, face_index)
        if ranked:
            layers.append(_layer(10, ranked[0]["asset"], ranked[0]))
        else:
            notes.append("no_base_frame_in_%s" % scope)

    base_dirs = [_dir_path(layer["original_path"]) for layer in layers if layer.get("asset_role") == "base_frame"]
    mask_scope = [mask_dir] if mask_dir else (base_dirs or dir_set)

    if tax.get("color_blend_mode") == "hybrid_gradient" and pair and pair[0] and pair[1]:
        right = [row for row in mask_rows if row["original_path"].endswith("maskRightHalf.png")]
        if right:
            pick = {"score": 1.0, "matched": ["filename"], "unmatched": []}
            layers.append(_layer(15, right[0], pick))
            notes.append("mask_dir:%s" % mask_dir)
        else:
            notes.append("no_mask_right_half_in_%s" % (mask_scope[0] if mask_scope else "no_scope"))

    if mask_rows:
        ranked_masks = _ranked(mask_rows, tax, face_index)
        selected = sorted(ranked_masks, key=lambda item: item["asset"]["original_path"])
        for idx, item in enumerate(selected[:10]):
            layers.append(_layer(20 + idx, item["asset"], item))
        notes.append("mask_dir:%s" % mask_dir)
    elif any("invocation" in directory for directory in mask_scope):
        notes.append("no_mask_by_design")
    else:
        notes.append("no_mask_in_%s" % (mask_scope[0] if mask_scope else "no_scope"))

    if tax.get("crown_style") != "none":
        crown_rows = _rows(conn, ("crown",), prefixes=dir_set) if dir_set else _rows(conn, ("crown",))
        if not crown_rows:
            crown_rows = _rows(conn, ("crown",), prefixes=["img/frames/m15/crowns/"])
        crown_rows = _official(crown_rows, notes)
        styled = [row for row in crown_rows if row.get("crown_style") == tax.get("crown_style")]
        candidates, crown_dir = _pick_dir(styled or crown_rows, _crown_dirs(tax))
        ranked = _ranked(candidates, tax)
        if ranked:
            layers.append(_layer(30, ranked[0]["asset"], ranked[0]))
            trace = tax.get("_trace", {}).get("crown_style")
            if trace is not None:
                trace["dir"] = crown_dir
            if crown_dir:
                notes.append("crown_dir:%s" % crown_dir)
        else:
            notes.append("no_crown")

    if face.get("power") is not None or face.get("toughness") is not None:
        rows = _rows(conn, ("pt_box",), prefixes=dir_set) if dir_set else _rows(conn, ("pt_box",))
        ranked = _select(rows, tax, notes)
        if ranked:
            layers.append(_layer(40, ranked[0]["asset"], ranked[0]))
        else:
            notes.append("no_pt_box_in_%s" % scope)

    if tax.get("frame") == "2015" and face.get("rarity") in ("rare", "mythic"):
        rows = _rows(conn, ("stamp",), prefixes=dir_set) if dir_set else _rows(conn, ("stamp",))
        if not rows:
            rows = _rows(conn, ("stamp",), prefixes=["img/frames/m15/"])
        ranked = _select(rows, tax, notes)
        if ranked:
            layers.append(_layer(50, ranked[0]["asset"], ranked[0]))
        else:
            notes.append("no_stamp")

    border_rule = m["border_color_mapping"]["rules"].get(tax.get("border_color")) or {}
    rows = _rows(conn, ("border",), prefixes=dir_set) if dir_set else _rows(conn, ("border",))
    if not rows:
        rows = _rows(conn, ("border",), prefixes=["img/frames/margins/", "img/frames/bleedEdge/"])
    ranked = _select(rows, tax, notes)
    if ranked:
        layers.append(_layer(60, ranked[0]["asset"], ranked[0]))
    elif border_rule.get("procedural_fallback"):
        layers.append(
            {
                "z_index": 60,
                "type": "procedural",
                "operation": border_rule["procedural_fallback"],
                "id": None,
            }
        )
    else:
        notes.append("no_border_in_%s" % scope)

    corner_rule = m["corner_cut_mapping"]["rules"].get(tax.get("corner_cut")) or {}
    corner_rows = [
        row
        for row in _rows(conn, ("border", "other"))
        if row.get("corner_cut") is not None
    ]
    ranked = _ranked(_official(corner_rows, notes), tax)
    if ranked:
        layers.append(_layer(70, ranked[0]["asset"], ranked[0]))
    elif corner_rule.get("procedural_fallback"):
        layers.append(
            {
                "z_index": 70,
                "type": "procedural",
                "operation": corner_rule["procedural_fallback"],
                "id": None,
            }
        )
    else:
        notes.append("no_corner_cut")

    if pinline_rows:
        ranked = _ranked(pinline_rows, tax, face_index)
        layers.append(_layer(80, ranked[0]["asset"], ranked[0]))
        notes.append("pinline_dir:%s" % pinline_dir)
    else:
        notes.append("no_pinline_in_%s" % (mask_scope[0] if mask_scope else "no_scope"))

    return layers, notes


def _scaled(field):
    out = {}
    for key in ("x", "y", "w", "h", "max_w"):
        if key in field:
            out[key] = int(round(field[key] * _SCALE))
    return out


def _art_layer(face):
    art = DEFAULT_LAYOUT["art"]
    bounds = {
        "x": int(round(art["x"] * _SCALE)),
        "y": int(round(art["y"] * _SCALE)),
        "w": int(round(art["w"] * _SCALE)),
        "h": int(round(art["h"] * _SCALE)),
    }
    return {
        "source": face.get("_art_crop"),
        "transform": {"x": bounds["x"], "y": bounds["y"], "scale": 1.0, "rotation": 0},
        "bounds": bounds,
        "normalized": {
            "x": round(bounds["x"] / CANVAS["width"], 6),
            "y": round(bounds["y"] / CANVAS["height"], 6),
            "w": round(bounds["w"] / CANVAS["width"], 6),
            "h": round(bounds["h"] / CANVAS["height"], 6),
        },
    }


def _text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _text_layers(face):
    template = face.get("template")
    text_bounds = (get_template_layout(template).get("text_bounds") or {}) if template else {}

    def bounds(key, fallback=None):
        value = text_bounds.get(key)
        if value:
            return dict(value)
        fallback = fallback or key
        return _scaled(DEFAULT_LAYOUT[fallback]) if fallback in DEFAULT_LAYOUT else None

    title = _text(re.split(r"\s*//\s*", str(face.get("name") or ""), maxsplit=1)[0])
    collector_parts = (
        face.get("set"),
        face.get("collector_number"),
        face.get("rarity"),
        face.get("artist"),
    )
    collector_text = " \u00b7 ".join(str(part) for part in collector_parts if part)
    rules_bounds = bounds("rules", "oracle_box")
    return {
        "title": {"text": title, "bounds": bounds("title")},
        "mana_cost": {"text": _text(face.get("mana_cost")), "bounds": bounds("mana")},
        "type_line": {"text": _text(face.get("type_line")), "bounds": bounds("type")},
        "oracle_text": {"text": _text(face.get("oracle_text")), "bounds": rules_bounds},
        "flavor_text": {
            "text": _text(face.get("flavor_text")),
            "bounds": dict(rules_bounds) if rules_bounds else None,
        },
        "pt": {
            "power": _text(face.get("power")),
            "toughness": _text(face.get("toughness")),
            "bounds": bounds("pt", "pt_text"),
        },
        "loyalty": {"text": _text(face.get("loyalty")), "bounds": bounds("loyalty", "pt_text")},
        "defense": {"text": _text(face.get("defense")), "bounds": bounds("defense", "pt_text")},
        "collector_info": {
            "text": collector_text or None,
            "set": face.get("set"),
            "collector_number": face.get("collector_number"),
            "rarity": face.get("rarity"),
            "artist": face.get("artist"),
            "lang": face.get("lang"),
            "bounds": bounds("collector", "artist"),
        },
    }


def build_recipe(card, *, db_path=None):
    db_path = str(db_path or _DEFAULT_DB)
    conn = sqlite3.connect(db_path)
    try:
        recipes = []
        meta_notes = []
        for face in resolve_faces(card):
            tax = infer_taxonomy(card, face)
            layers, layer_notes = select_layers(tax, face, conn)
            warnings = list(face.get("_notes") or []) + list(tax.get("_notes") or []) + layer_notes
            recipes.append(
                {
                    "face_index": face.get("_face_index"),
                    "face_ref": face.get("_face_ref"),
                    "taxonomy": {k: v for k, v in deepcopy(tax).items() if not k.startswith("_")}
                    | {"_trace": tax.get("_trace")},
                    "texture_pair": tax.get("_texture_pair"),
                    "layers": layers,
                    "art_layer": _art_layer(face),
                    "text_layers": _text_layers(face),
                    "warnings": warnings,
                }
            )
    finally:
        conn.close()

    return {
        "meta": {
            "canvas": dict(CANVAS),
            "geometry_source": "card_layouts",
            "db_path": db_path,
            "resolver": "frame_resolver/v1",
            "notes": meta_notes,
        },
        "recipes": recipes,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="frame_resolver")
    parser.add_argument("--card", required=True, help="Scryfall JSON file, or - for stdin")
    parser.add_argument("--out", required=True)
    parser.add_argument("--db", default=None)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    if args.card == "-":
        card = json.load(sys.stdin)
    else:
        card = json.loads(Path(args.card).read_text())
    result = build_recipe(card, db_path=args.db)
    Path(args.out).write_text(
        json.dumps(result, indent=2 if args.pretty else None, ensure_ascii=False) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
