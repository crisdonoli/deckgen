import os
import re
import shutil
import xml.etree.ElementTree as ET

from config import PREVIEW_CACHE_DIR
from utils.text import normalize_card_text


def find_deck_files(export_dir):
    deck_files = []
    if export_dir and os.path.isdir(export_dir):
        for root, _, files in os.walk(export_dir):
            for f in files:
                f_lower = f.lower()
                if f_lower.endswith(".xml") or (f_lower.endswith(".txt") and "requirements" not in f_lower):
                    deck_files.append(os.path.join(root, f))
    def sort_key(p):
        rel = os.path.relpath(p, export_dir)
        depth = len(rel.split(os.sep))
        base = os.path.basename(p).lower()
        is_txt = base.endswith(".txt")
        is_cards = "cards.xml" in base
        score = 0 if (depth == 1 and (is_txt or is_cards)) else (1 if is_txt else 2)
        return (depth, score, rel)
    return sorted(deck_files, key=sort_key)


def find_deck_xmls(export_dir):
    return find_deck_files(export_dir)


def parse_mtgo_txt(content):
    cards = []
    lines = content.splitlines() if isinstance(content, str) else content.decode("utf-8", errors="replace").splitlines()
    slot_idx = 0
    in_sideboard = False
    sideboard_cards = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        lower_line = line.lower()
        if lower_line.startswith(("sideboard", "// sideboard", "# sideboard")):
            in_sideboard = True
            continue
        if lower_line.startswith(("//", "#")):
            continue
        m = re.match(r"^(\d+)\s*[xX]?\s+(.+)$", line)
        if not m:
            continue
        qty = int(m.group(1))
        raw = m.group(2).strip()
        name = re.sub(r"\s*\*F\*\s*$", "", raw, flags=re.IGNORECASE)
        name = re.sub(r"\s*\{[A-Za-z0-9_]+\}\s*$", "", name)
        name = re.sub(r"\s*\([A-Za-z0-9_]{3,5}\)\s*[A-Za-z0-9_{}-]*$", "", name)
        name = re.sub(r"\s*\[[A-Za-z0-9_]{3,5}\]\s*[A-Za-z0-9_{}-]*$", "", name)
        name = name.strip()
        slots = list(range(slot_idx, slot_idx + qty))
        slot_idx += qty
        entry = {
            "id": "",
            "name": name,
            "query": name.lower(),
            "slots": slots,
            "required_count": qty,
        }
        if in_sideboard:
            sideboard_cards.append(entry)
        else:
            cards.append(entry)

    total_quantity = sum(c["required_count"] for c in cards)
    return total_quantity, cards, sideboard_cards


def inspect_deck_file(export_dir, deck_path=None, file_content=None):
    if not export_dir or not os.path.isdir(export_dir):
        return {"error": f"Directory '{export_dir}' does not exist or is not valid."}

    available_files = find_deck_files(export_dir)
    chosen_file = deck_path if (deck_path and os.path.isfile(deck_path)) else (available_files[0] if available_files else None)

    is_txt = False
    raw_text = None
    if file_content:
        raw_text = file_content if isinstance(file_content, str) else file_content.decode("utf-8", errors="replace")
        if not raw_text.strip().startswith("<"):
            is_txt = True
    elif chosen_file:
        if chosen_file.lower().endswith(".txt"):
            is_txt = True
            with open(chosen_file, "r", encoding="utf-8", errors="replace") as f:
                raw_text = f.read()

    cards_data = []
    if is_txt:
        quantity, all_cards, _ = parse_mtgo_txt(raw_text)
        display_path = chosen_file or "uploaded TXT"
    elif file_content or chosen_file:
        try:
            if file_content:
                root = ET.fromstring(file_content)
                display_path = "uploaded XML"
            else:
                tree = ET.parse(chosen_file)
                root = tree.getroot()
                display_path = chosen_file
            try:
                quantity = int(root.findtext("details/quantity", "100"))
            except ValueError:
                quantity = 100
            all_cards = []
            for c in root.findall("fronts/card"):
                cid = c.findtext("id", "").strip()
                cname = c.findtext("name", "").strip()
                cquery = c.findtext("query", "").strip()
                slots_str = c.findtext("slots", "").strip()
                slots = [int(s) for s in slots_str.split(",") if s.strip()]
                all_cards.append({
                    "id": cid,
                    "name": cname,
                    "query": cquery,
                    "slots": slots,
                    "required_count": len(slots),
                })
        except Exception as e:
            return {"error": f"Error reading deck file: {e}"}
    else:
        return {"error": "No deck file (.xml or .txt) found in the directory.", "available_files": [], "available_xmls": []}

    pdf_dir = os.path.join(export_dir, "pdfs")
    target_dir = pdf_dir if os.path.isdir(pdf_dir) else export_dir
    files_on_disk = [
        f for f in sorted(os.listdir(target_dir))
        if f.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")) and not f.lower().startswith("sheet") and "back" not in f.lower()
    ]

    matched_files = set()
    all_slots = set()

    for c in all_cards:
        cid = c.get("id", "")
        cname = c.get("name", "")
        cquery = c.get("query", "")
        slots = c.get("slots", [])
        all_slots.update(slots)

        matches = []
        for f in files_on_disk:
            f_norm = normalize_card_text(f)
            if cid and cid in f:
                matches.append(f)
                continue
            m = re.match(r"^\(([^)]+)\)\s*\(([^)]+)\)", f)
            if m:
                orig = normalize_card_text(m.group(1))
                if orig and (orig == normalize_card_text(cquery) or orig == normalize_card_text(cname)):
                    matches.append(f)
                    continue
            q_norm = normalize_card_text(cquery)
            n_norm = normalize_card_text(cname)
            if q_norm and (q_norm == f_norm or q_norm in f_norm or f_norm in q_norm):
                matches.append(f)
                continue
            if n_norm and (n_norm == f_norm or n_norm in f_norm or f_norm in n_norm):
                matches.append(f)
                continue
            words = [w for w in re.findall(r"[a-z0-9]+", (cquery or cname).lower()) if len(w) > 3]
            if words and all(w in f.lower() for w in words):
                matches.append(f)
                continue

        unique_matches = []
        for m in matches:
            if m not in unique_matches:
                unique_matches.append(m)

        for m in unique_matches:
            matched_files.add(m)

        required = c["required_count"]
        found_count = len(unique_matches)
        if found_count == 0:
            status = "missing"
        elif found_count < required:
            status = "needs_copies"
        else:
            status = "ok"

        cards_data.append({
            "id": cid,
            "name": cname,
            "query": cquery,
            "slots": slots,
            "required_count": required,
            "existing_copies": found_count,
            "status": status,
            "matched_file": unique_matches[0] if unique_matches else None,
            "all_matched_files": unique_matches,
        })

    extra_files = [f for f in sorted(files_on_disk) if f not in matched_files]
    missing_slots = sorted(set(range(quantity)) - all_slots) if quantity else []

    return {
        "deck_file_path": display_path,
        "xml_path": display_path,
        "format": "txt" if is_txt else "xml",
        "available_files": available_files,
        "available_xmls": available_files,
        "target_dir": target_dir,
        "quantity": quantity,
        "total_slots": len(all_slots),
        "total_cards": len(cards_data),
        "total_cards_xml": len(cards_data),
        "total_files_disk": len(files_on_disk),
        "missing_slots": missing_slots,
        "cards": cards_data,
        "extra_files": extra_files,
    }


def inspect_deck_xml(export_dir, xml_path=None, xml_content=None):
    return inspect_deck_file(export_dir, xml_path, xml_content)


def duplicate_deck_cards(export_dir, target_file=None, count=1, auto_deck=False, deck_path=None, file_content=None, auto_xml=False, xml_path=None, xml_content=None):
    if not export_dir or not os.path.isdir(export_dir):
        return {"error": f"Directory not found: {export_dir}", "created": []}

    pdf_dir = os.path.join(export_dir, "pdfs")
    target_dir = pdf_dir if os.path.isdir(pdf_dir) else export_dir
    images_dir = os.path.join(export_dir, "images")
    has_images = os.path.isdir(images_dir)

    effective_auto = auto_deck or auto_xml
    effective_path = deck_path or xml_path
    effective_content = file_content or xml_content

    created = []

    def copy_file_variant(src_path, num_copies):
        new_files = []
        d = os.path.dirname(src_path)
        base = os.path.basename(src_path)
        stem, ext = os.path.splitext(base)
        clean_stem = re.sub(r"\s*\(copia \d+\)$", "", stem)
        n = 2
        for _ in range(num_copies):
            while True:
                cand = os.path.join(d, f"{clean_stem} (copia {n}){ext}")
                if not os.path.exists(cand):
                    break
                n += 1
            shutil.copy2(src_path, cand)
            new_files.append(cand)
            n += 1
        return new_files

    if effective_auto:
        inspection = inspect_deck_file(export_dir, effective_path, effective_content)
        if "error" in inspection:
            return {"error": inspection["error"], "created": []}
        for card in inspection["cards"]:
            if card["status"] == "needs_copies" and card["matched_file"]:
                src_path = os.path.join(target_dir, card["matched_file"])
                if os.path.exists(src_path):
                    missing = card["required_count"] - card["existing_copies"]
                    if missing > 0:
                        new_files = copy_file_variant(src_path, missing)
                        created.extend(new_files)
                        if has_images:
                            stem = os.path.splitext(card["matched_file"])[0]
                            clean_stem = re.sub(r"\s*\(copia \d+\)$", "", stem)
                            for img_ext in (".png", ".jpg", ".jpeg"):
                                img_src = os.path.join(images_dir, clean_stem + img_ext)
                                if os.path.exists(img_src):
                                    copy_file_variant(img_src, missing)
                                    break
    elif target_file:
        src_path = os.path.join(target_dir, target_file)
        if not os.path.exists(src_path):
            return {"error": f"File '{target_file}' not found in {target_dir}", "created": []}
        new_files = copy_file_variant(src_path, count)
        created.extend(new_files)
        if has_images:
            stem = os.path.splitext(target_file)[0]
            clean_stem = re.sub(r"\s*\(copia \d+\)$", "", stem)
            for img_ext in (".png", ".jpg", ".jpeg"):
                img_src = os.path.join(images_dir, clean_stem + img_ext)
                if os.path.exists(img_src):
                    copy_file_variant(img_src, count)
                    break
    else:
        return {"error": "No duplication action specified.", "created": []}

    # Invalidate preview cache
    if os.path.exists(PREVIEW_CACHE_DIR):
        for f in os.listdir(PREVIEW_CACHE_DIR):
            if f.startswith("deckgen_preview_"):
                try:
                    os.remove(os.path.join(PREVIEW_CACHE_DIR, f))
                except OSError:
                    pass

    return {
        "status": "ok",
        "created": [os.path.basename(f) for f in created],
        "count": len(created),
        "message": f"Successfully created {len(created)} card copy(ies)."
    }
