"""Render frame recipes from a Scryfall fixture to PNG files."""
import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "gui"))

from core.frame_resolver import build_recipe  # noqa: E402
from core.recipe_renderer import render_recipe  # noqa: E402

DEFAULT_OUT_DIR = Path("/tmp/opencode")


def _cards(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("cards"), list):
        return raw["cards"]
    return [raw]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="render_recipe_cli")
    parser.add_argument("--card", required=True, help="Scryfall fixture JSON (card, list or {cards:[...]})")
    parser.add_argument("--out", default=None, help="Output PNG path (or path prefix when the fixture has several faces)")
    parser.add_argument("--art", default=None, help="Local art image replacing art_layer.source")
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)

    cards = _cards(json.loads(Path(args.card).read_text()))
    jobs = []
    for card in cards:
        recipe = build_recipe(card, db_path=args.db)
        for face in recipe["recipes"]:
            single = {"meta": recipe["meta"], "recipes": [face]}
            jobs.append((card.get("id") or card.get("name") or "card", face.get("face_index"), single))

    written = []
    for index, (card_id, face_index, recipe) in enumerate(jobs):
        suffix = "" if len(jobs) == 1 and args.out else "_face%s" % ("0" if face_index is None else face_index)
        if args.out:
            out = Path(args.out)
            if len(jobs) > 1 or face_index is not None:
                out = out.with_name(out.stem + suffix + out.suffix)
        else:
            out = DEFAULT_OUT_DIR / ("render_%s%s.png" % (card_id, suffix))
        out.parent.mkdir(parents=True, exist_ok=True)
        result = render_recipe(recipe, art_override=args.art)
        out.write_bytes(result["png"])
        written.append((out, result))
        print("face=%s %dx%d bytes=%d warnings=%s" % (face_index, result["width"], result["height"], len(result["png"]), sorted(set(result["warnings"]))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
