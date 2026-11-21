"""Smoke test for gui.core.frame_resolver: 4 offline Scryfall-shaped fixtures."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gui.core.frame_resolver import build_recipe  # noqa: E402

FIXTURES_PATH = ROOT / "assets" / "fixtures" / "scryfall_samples.json"
PROTECTED = [ROOT / "assets" / "taxonomy.json", ROOT / "assets" / "scryfall-map.json"]
DB_PATH = ROOT / "assets" / "resources" / "assets.db"

FIXTURES = [
    {
        "id": "fixture-mono-creature",
        "name": "Test Beast",
        "set": "m15",
        "set_name": "Magic 2015",
        "rarity": "rare",
        "frame": "2015",
        "layout": "normal",
        "border_color": "black",
        "lang": "en",
        "collector_number": "1",
        "artist": "Test Artist",
        "colors": ["G"],
        "color_identity": ["G"],
        "mana_cost": "{2}{G}",
        "type_line": "Creature — Beast",
        "oracle_text": "Trample.",
        "power": "3",
        "toughness": "3",
        "finishes": ["nonfoil", "foil"],
        "image_uris": {"art_crop": "https://example.test/art-mono.jpg"},
    },
    {
        "id": "fixture-dual-land",
        "name": "Test Delta",
        "set": "m15",
        "set_name": "Magic 2015",
        "rarity": "rare",
        "frame": "2015",
        "layout": "normal",
        "border_color": "black",
        "lang": "en",
        "collector_number": "2",
        "artist": "Test Artist",
        "colors": ["W", "U"],
        "color_identity": ["W", "U"],
        "produced_mana": ["W", "U"],
        "mana_cost": "",
        "type_line": "Land",
        "oracle_text": "This land enters tapped.\n{T}: Add {W} or {U}.",
        "image_uris": {"art_crop": "https://example.test/art-land.jpg"},
    },
    {
        "id": "fixture-transform",
        "name": "Test Wanderer // Test Nightmare",
        "set": "neo",
        "set_name": "Kamigawa: Neon Dynasty",
        "rarity": "mythic",
        "frame": "2015",
        "layout": "transform",
        "border_color": "borderless",
        "lang": "en",
        "collector_number": "3",
        "artist": "Test Artist",
        "frame_effects": ["legendary", "showcase"],
        "finishes": ["nonfoil", "foil"],
        "promo_types": ["boosterfun"],
        "color_identity": ["U"],
        "card_faces": [
            {
                "name": "Test Wanderer",
                "mana_cost": "{1}{U}",
                "type_line": "Legendary Creature — Human",
                "oracle_text": "When this creature enters, draw a card.",
                "power": "2",
                "toughness": "2",
                "colors": ["U"],
                "image_uris": {"art_crop": "https://example.test/art-front.jpg"},
            },
            {
                "name": "Test Nightmare",
                "mana_cost": "",
                "type_line": "Legendary Creature — Nightmare",
                "oracle_text": "Flying",
                "power": "4",
                "toughness": "4",
                "colors": ["U"],
                "image_uris": {"art_crop": "https://example.test/art-back.jpg"},
            },
        ],
    },
    {
        "id": "fixture-planeswalker",
        "name": "Test Vess",
        "set": "m15",
        "set_name": "Magic 2015",
        "rarity": "mythic",
        "frame": "2015",
        "layout": "normal",
        "border_color": "black",
        "lang": "en",
        "collector_number": "4",
        "artist": "Test Artist",
        "colors": ["B"],
        "color_identity": ["B"],
        "mana_cost": "{3}{B}{B}",
        "type_line": "Legendary Planeswalker — Vess",
        "oracle_text": "+1: Draw a card.\n-3: Target creature gets -3/-3 until end of turn.\n-7: You get an emblem.",
        "loyalty": "4",
        "image_uris": {"art_crop": "https://example.test/art-pw.jpg"},
    },
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    FIXTURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURES_PATH.write_text(json.dumps(FIXTURES, indent=2, ensure_ascii=False) + "\n")
    before = {str(p): sha(p) for p in PROTECTED}

    results = [build_recipe(card, db_path=str(DB_PATH)) for card in FIXTURES]

    failures = 0

    def check(name, ok):
        nonlocal failures
        print("%s %s" % ("PASS" if ok else "FAIL", name))
        if not ok:
            failures += 1

    import sqlite3

    conn = sqlite3.connect(str(DB_PATH))
    known = {row[0] for row in conn.execute("SELECT id FROM frames")}
    conn.close()

    ids = [
        layer["id"]
        for result in results
        for recipe in result["recipes"]
        for layer in recipe["layers"]
        if layer.get("id")
    ]
    check("layer ids exist in frames.id", all(i in known for i in ids))

    z_ok = all(
        all(a["z_index"] < b["z_index"] for a, b in zip(recipe["layers"], recipe["layers"][1:]))
        for result in results
        for recipe in result["recipes"]
    )
    check("z_index strictly ascending", z_ok)

    canvas_ok = all(
        result["meta"]["canvas"] == {"width": 1500, "height": 2100} for result in results
    )
    check("canvas 1500x2100", canvas_ok)

    after = {str(p): sha(p) for p in PROTECTED}
    check("taxonomy/map hashes unchanged", before == after)

    dfc = results[2]["recipes"]
    check("DFC has 2 face recipes", len(dfc) == 2)

    print("recipes_per_fixture=%s" % [len(r["recipes"]) for r in results])
    for result in results:
        for recipe in result["recipes"]:
            roles = [layer.get("asset_role") or layer.get("type") for layer in recipe["layers"]]
            print("  %s -> %s" % (recipe["face_ref"], roles))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
