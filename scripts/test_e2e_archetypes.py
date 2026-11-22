#!/usr/bin/env python3
"""End-to-end integration test suite for Scryfall import, art replacement, SVG symbols, and 1500x2100 PNG export."""
import base64
import io
import os
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gui"))

from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402
from core.recipe_renderer import _mana_image, render_recipe  # noqa: E402
from services.card_project import build_card_project, resolve_card  # noqa: E402

OUT_DIR = Path("/home/choroy/.gemini/antigravity/brain/f1496424-a8a3-4ed5-9b71-b2f85994d5ae/scratch/e2e_exports")


def make_external_art_bytes(color=(38, 92, 168)) -> bytes:
    img = Image.new("RGBA", (900, 700), (*color, 255))
    draw = ImageDraw.Draw(img)
    for step in range(0, 700, 40):
        draw.rectangle([step // 2, step // 3, 900 - step // 2, 700 - step // 3], outline=(240, 210, 110, 255), width=4)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def verify_mana_symbols() -> None:
    required_symbols = (
        ["W", "U", "B", "R", "G", "C", "X", "T", "Q"]
        + [str(i) for i in range(21)]
        + ["W/U", "U/B", "B/R", "R/G", "G/W", "W/B", "U/R", "B/G", "R/W", "G/U"]
        + ["W/P", "U/P", "B/P", "R/P", "G/P", "2/W", "2/U", "2/B", "2/R", "2/G"]
    )
    warnings = []
    for sym in required_symbols:
        img = _mana_image(sym, 64, warnings, with_shadow=True)
        assert img is not None, f"Failed to rasterize symbol {{{sym}}}"
        assert img.mode == "RGBA" and img.width >= 64 and img.height >= 64
        extrema = img.getextrema()
        assert extrema[3][0] == 0 and extrema[3][1] > 200, f"Symbol {{{sym}}} lacks clean alpha channel: {extrema}"
    assert not warnings, f"Unexpected warnings during symbol rasterization: {warnings}"
    print(f"PASS: All {len(required_symbols)} mana/tap/hybrid/phyrexian SVG symbols rasterized with clean alpha and shadow.")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    verify_mana_symbols()

    client = TestClient(app)
    art_bytes = make_external_art_bytes()
    art_data_url = "data:image/png;base64," + base64.b64encode(art_bytes).decode("ascii")

    archetypes = [
        {
            "label": "1_standard_2015_normal",
            "query": {"name": "Sol Ring", "set": "cmr"},
            "expect_faces": 1,
            "expect_tax": {"frame": "2015", "layout": "normal"},
        },
        {
            "label": "2_borderless_land_inverted",
            "query": {
                "card": {
                    "id": "chocobo-camp-fin",
                    "name": "Chocobo Camp",
                    "set": "fin",
                    "collector_number": "275",
                    "rarity": "rare",
                    "frame": "2015",
                    "layout": "normal",
                    "border_color": "borderless",
                    "frame_effects": ["inverted"],
                    "colors": [],
                    "color_identity": ["G", "W"],
                    "produced_mana": ["G", "W"],
                    "mana_cost": "",
                    "type_line": "Land — Plains Forest",
                    "oracle_text": "({T}: Add {G} or {W}.)\nChocobo Camp enters tapped unless you control two or more basic lands.\n{2}{G/W}, {T}: Create a 2/2 green Bird creature token.",
                    "flavor_text": "Where golden feathers gather, travelers rest safe from the wilds.",
                    "artist": "Final Fantasy Studio",
                    "image_uris": {"art_crop": "https://cards.scryfall.io/art_crop/front/c/8/c8817585-0d32-4d56-9142-0d29512e86a9.jpg"},
                }
            },
            "expect_faces": 1,
            "expect_tax": {"frame": "2015", "layout": "normal"},
        },
        {
            "label": "3_hybrid_phyrexian_long_text",
            "query": {"name": "Compleated Huntmaster", "set": "mom"},
            "fallback_card": {
                "id": "omnath-locus-of-all",
                "name": "Omnath, Locus of All",
                "set": "mom",
                "collector_number": "249",
                "rarity": "mythic",
                "frame": "2015",
                "layout": "normal",
                "border_color": "black",
                "frame_effects": ["legendary"],
                "colors": ["W", "U", "B", "R", "G"],
                "color_identity": ["W", "U", "B", "R", "G"],
                "mana_cost": "{W}{U}{B/P}{R}{G}",
                "type_line": "Legendary Creature — Phyrexian Elemental",
                "oracle_text": "If you would lose unspent mana, that mana becomes black instead.\nAt the beginning of your precombat main phase, look at the top card of your library. You may reveal that card if it has three or more colored mana symbols in its mana cost. If you do, add three mana in any combination of its colors and put it into your hand. Otherwise, put it into your hand.\n{W/U}{B/R}{G/P}, {T}, {Q}: Add {C}{0}{1}{2}{10}{20}{X}.",
                "flavor_text": "Five suns twisted into one dark eclipse across the blind eternities.",
                "power": "4",
                "toughness": "4",
                "artist": "Victor Adame Minguez",
                "image_uris": {"art_crop": "https://cards.scryfall.io/art_crop/front/3/3/33d548c9-c41f-4c23-9a25-2c32c7651162.jpg"},
            },
            "expect_faces": 1,
            "expect_tax": {"frame": "2015", "layout": "normal"},
        },
        {
            "label": "4_planeswalker_tall_4_abilities",
            "query": {"name": "Jace, the Mind Sculptor", "set": "2xm"},
            "expect_faces": 1,
            "expect_tax": {"structural_type_override": "planeswalker", "box_variant": "tall"},
        },
        {
            "label": "5_dfc_transform_both_faces",
            "query": {"name": "Delver of Secrets", "set": "isd"},
            "expect_faces": 2,
            "expect_tax": {"layout": "transform"},
        },
    ]

    with tempfile.TemporaryDirectory() as ws_root:
        for arch in archetypes:
            payload = dict(arch["query"])
            if "fallback_card" in arch:
                payload = {"card": arch["fallback_card"]}
            payload["root_dir"] = ws_root
            resp = client.post("/api/card-builder/import-scryfall", json=payload)
            assert resp.status_code == 200, f"{arch['label']} import failed: {resp.status_code} {resp.text}"
            project = resp.json()
            faces = project.get("faces") or []
            assert len(faces) == arch["expect_faces"], f"{arch['label']} expected {arch['expect_faces']} faces, got {len(faces)}"

            # Verify set symbol and art_crop are decoupled from frame_stack
            assert project.get("set_symbol") is not None
            for f_idx, face in enumerate(faces):
                tax = face.get("taxonomy") or {}
                for k, v in arch["expect_tax"].items():
                    assert tax.get(k) == v, f"{arch['label']} face {f_idx} expected taxonomy {k}={v}, got {tax.get(k)}"
                if arch["label"] == "2_borderless_land_inverted":
                    assert "inverted" in (tax.get("frame_effects") or []), "Expected inverted in frame_effects"
                if arch["label"] == "4_planeswalker_tall_4_abilities":
                    orig_paths = [l.get("original_path") or "" for l in (project["recipe"]["recipes"][f_idx].get("layers") or [])]
                    assert any("planeswalker/tall/" in p for p in orig_paths), f"Expected planeswalker/tall/ in layers, got {orig_paths}"

                stack_roles = [l.get("asset_role") for l in (face.get("frame_stack") or [])]
                assert "art" not in stack_roles and "set_symbol" not in stack_roles

                # Export PNG 1500x2100 with external art override
                exp_face_idx = face.get("face_index") if face.get("face_index") is not None else 0
                exp_resp = client.post(
                    "/api/card-builder/export",
                    json={
                        "project_id": project["project_id"],
                        "face_index": exp_face_idx,
                        "art_override_dataurl": art_data_url,
                    },
                )
                assert exp_resp.status_code == 200, f"{arch['label']} export face {exp_face_idx} failed: {exp_resp.text}"
                png_bytes = exp_resp.content
                with Image.open(io.BytesIO(png_bytes)) as im:
                    assert im.size == (1500, 2100), f"{arch['label']} expected 1500x2100, got {im.size}"
                out_file = OUT_DIR / f"{arch['label']}_face{exp_face_idx}.png"
                out_file.write_bytes(png_bytes)

                # Also verify direct render_recipe warnings do not include font_fallback or mana_symbol_missing
                single_recipe = {
                    "meta": project["recipe"]["meta"],
                    "recipes": [project["recipe"]["recipes"][f_idx]],
                }
                rr = render_recipe(single_recipe, art_override=art_bytes)
                bad_warns = [w for w in rr["warnings"] if w.startswith(("font_fallback", "mana_symbol_missing", "mana_raster_failed", "layer_missing"))]
                assert not bad_warns, f"{arch['label']} face {exp_face_idx} produced errors in warnings: {bad_warns}"
                print(f"PASS: {arch['label']} face={exp_face_idx} -> {out_file.name} (1500x2100, {len(png_bytes)} bytes, warnings={rr['warnings']})")

    print("ALL 5 E2E ARCHETYPES PASSED SUCCESSFULLY.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
