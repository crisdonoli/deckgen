import json
import os
import re
import xml.etree.ElementTree as ET

from config import PREVIEW_CACHE_DIR
from core.pdf_build import image_to_standard_pdf
from utils.text import normalize_card_text


def collect_front_pdfs(export_dir):
    for source_dir in (
        os.path.join(export_dir, "fronts"),
        os.path.join(export_dir, "pdfs"),
        export_dir,
    ):
        if not os.path.isdir(source_dir):
            continue
        pdfs = sorted(
            os.path.join(source_dir, f)
            for f in os.listdir(source_dir)
            if f.lower().endswith(".pdf") and "back" not in f.lower()
        )
        if pdfs:
            return pdfs
    if os.path.isdir(export_dir):
        pdfs = sorted(
            os.path.join(export_dir, f)
            for f in os.listdir(export_dir)
            if f.lower().endswith(".pdf")
        )
        if pdfs:
            return pdfs
    raise ValueError(f"no front PDFs found in {export_dir}")


def collect_back_pdfs(export_dir):
    backs_dir = os.path.join(export_dir, "backs")
    if os.path.isdir(backs_dir):
        pdfs = sorted(
            os.path.join(backs_dir, f)
            for f in os.listdir(backs_dir)
            if f.lower().endswith(".pdf")
        )
        if pdfs:
            return pdfs

    for root, _, files in os.walk(export_dir):
        backs = sorted(
            os.path.join(root, f)
            for f in files
            if f.lower().endswith(".pdf") and "back" in f.lower()
        )
        if backs:
            return backs

    return []


def collect_pdfs(export_dir, face):
    if face == "backs":
        backs = collect_back_pdfs(export_dir)
        if backs:
            return backs
        raise ValueError(f"no back PDFs found in {export_dir}")
    return collect_front_pdfs(export_dir)


def load_custom_backs(export_dir):
    if not export_dir or not os.path.isdir(export_dir):
        return {}
    cb_path = os.path.join(export_dir, "custom_backs.json")
    if os.path.isfile(cb_path):
        try:
            with open(cb_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def save_custom_backs(export_dir, mapping):
    if not export_dir or not os.path.isdir(export_dir):
        return False
    cb_path = os.path.join(export_dir, "custom_backs.json")
    try:
        with open(cb_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def find_generic_back_pdf(export_dir):
    if not export_dir or not os.path.isdir(export_dir):
        return None
    backs_dir = os.path.join(export_dir, "backs")
    search_dirs = [backs_dir, export_dir] if os.path.isdir(backs_dir) else [export_dir]
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for cand in ["card_back.pdf", "back.pdf", "cardback.pdf", "generic_back.pdf", "reverso.pdf"]:
            p = os.path.join(d, cand)
            if os.path.isfile(p):
                return p
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".pdf") and "back" in f.lower() and not f.lower().startswith(("sheet", "deckgen_")):
                return os.path.join(d, f)
    if os.path.isdir(backs_dir):
        pdfs = sorted([
            os.path.join(backs_dir, f)
            for f in os.listdir(backs_dir)
            if f.lower().endswith(".pdf") and not f.lower().startswith(("sheet", "deckgen_"))
        ])
        if pdfs:
            return pdfs[0]
    return None


def inspect_custom_backs(export_dir):
    if not export_dir or not os.path.isdir(export_dir):
        return {"error": f"Directory not found: '{export_dir}'"}

    try:
        front_pdfs = collect_front_pdfs(export_dir)
    except Exception as e:
        return {"error": f"No front cards found: {e}"}

    backs_dir = os.path.join(export_dir, "backs")
    available_backs = []
    if os.path.isdir(backs_dir):
        for f in sorted(os.listdir(backs_dir)):
            if f.lower().endswith(".pdf") and not f.lower().startswith(("sheet", "deckgen_")):
                available_backs.append(os.path.join("backs", f))
    for f in sorted(os.listdir(export_dir)):
        if f.lower().endswith(".pdf") and "back" in f.lower() and not f.lower().startswith(("sheet", "deckgen_")):
            if f not in available_backs:
                available_backs.append(f)

    custom_map = load_custom_backs(export_dir)

    # Check cards.xml for back slot pairing
    xml_pairs = {}
    for xml_cand in [os.path.join(export_dir, "cards.xml"), os.path.join(export_dir, "images", "cards.xml")]:
        if os.path.isfile(xml_cand):
            try:
                tree = ET.parse(xml_cand)
                root = tree.getroot()
                f_by_slot = {}
                for c in root.findall("fronts/card"):
                    cname = c.findtext("name", "").strip()
                    cid = c.findtext("id", "").strip()
                    cquery = c.findtext("query", "").strip()
                    for s in [x.strip() for x in c.findtext("slots", "").split(",") if x.strip()]:
                        f_by_slot[s] = {"name": cname, "id": cid, "query": cquery}
                for b in root.findall("backs/card"):
                    bname = b.findtext("name", "").strip()
                    bid = b.findtext("id", "").strip()
                    bquery = b.findtext("query", "").strip()
                    for s in [x.strip() for x in b.findtext("slots", "").split(",") if x.strip()]:
                        if s in f_by_slot:
                            f_info = f_by_slot[s]
                            xml_pairs[normalize_card_text(f_info["name"])] = bname
                            xml_pairs[normalize_card_text(f_info["query"])] = bname
            except Exception:
                pass
            break

    cards_data = []
    custom_count = 0
    for idx, fpath in enumerate(front_pdfs):
        fname = os.path.basename(fpath)
        stem = os.path.splitext(fname)[0]
        m = re.match(r"^\(([^)]+)\)\s*\(([^)]+)\)", fname)
        if m:
            clean_name = f"{m.group(2)} ({m.group(1)})"
        else:
            clean_name = re.sub(r"\s*\(copia \d+\)", "", stem)
            clean_name = re.sub(r"\s*\([a-zA-Z0-9_\-]{20,}\)", "", clean_name)
            clean_name = re.sub(r"\s*\[.*?\]|\{.*?\}", "", clean_name).strip()

        assigned_back = custom_map.get(fname) or custom_map.get(stem)
        is_custom = bool(assigned_back)
        if is_custom:
            custom_count += 1

        norm = normalize_card_text(fname)
        paired_xml = xml_pairs.get(norm)

        cards_data.append({
            "index": idx + 1,
            "filename": fname,
            "name": clean_name,
            "custom_back": assigned_back,
            "custom_back_filename": os.path.basename(assigned_back) if assigned_back else None,
            "is_custom": is_custom,
            "xml_paired_back": paired_xml,
        })

    generic_back = find_generic_back_pdf(export_dir)

    return {
        "status": "ok",
        "export_dir": export_dir,
        "total_cards": len(cards_data),
        "custom_count": custom_count,
        "generic_count": len(cards_data) - custom_count,
        "available_backs": available_backs,
        "generic_back": os.path.basename(generic_back) if generic_back else None,
        "cards": cards_data,
    }


def assign_custom_backs(export_dir, card_filenames, back_file_body=None, back_filename=None, original_filename=None):
    if not export_dir or not os.path.isdir(export_dir):
        return {"error": f"Directory not found: '{export_dir}'"}
    if not card_filenames:
        return {"error": "No cards selected to assign a back."}

    backs_dir = os.path.join(export_dir, "backs")
    os.makedirs(backs_dir, exist_ok=True)

    assigned_rel_path = None
    if back_file_body:
        fname = original_filename or "custom_back.pdf"
        base, ext = os.path.splitext(fname)
        if ext.lower() not in (".pdf", ".png", ".jpg", ".jpeg"):
            ext = ".pdf"
        safe_fname = re.sub(r"[^\w\s\-\.\(\)]", "_", base).strip() + ext
        dest_path = os.path.join(backs_dir, safe_fname)
        if ext.lower() in (".png", ".jpg", ".jpeg"):
            pdf_dest = os.path.join(backs_dir, base + ".pdf")
            image_to_standard_pdf(back_file_body, pdf_dest)
            assigned_rel_path = os.path.join("backs", os.path.basename(pdf_dest))
        else:
            with open(dest_path, "wb") as f:
                f.write(back_file_body)
            assigned_rel_path = os.path.join("backs", safe_fname)
    elif back_filename:
        cand = os.path.join(export_dir, back_filename)
        cand_backs = os.path.join(backs_dir, back_filename)
        if os.path.isfile(cand):
            assigned_rel_path = back_filename
        elif os.path.isfile(cand_backs):
            assigned_rel_path = os.path.join("backs", back_filename)
        else:
            return {"error": f"Back file not found: '{back_filename}'"}
    else:
        return {"error": "No back file or name provided."}

    mapping = load_custom_backs(export_dir)
    for cf in card_filenames:
        mapping[cf] = assigned_rel_path

    save_custom_backs(export_dir, mapping)

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
        "assigned_back": assigned_rel_path,
        "updated_count": len(card_filenames),
        "message": f"Assigned '{os.path.basename(assigned_rel_path)}' to {len(card_filenames)} card(s)."
    }


def remove_custom_backs(export_dir, card_filenames):
    if not export_dir or not os.path.isdir(export_dir):
        return {"error": f"Directory not found: '{export_dir}'"}
    if not card_filenames:
        return {"error": "No cards selected."}

    mapping = load_custom_backs(export_dir)
    removed = 0
    for cf in card_filenames:
        if cf in mapping:
            del mapping[cf]
            removed += 1
        stem = os.path.splitext(cf)[0]
        if stem in mapping:
            del mapping[stem]
            removed += 1

    save_custom_backs(export_dir, mapping)

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
        "removed_count": removed,
        "message": f"Restored {len(card_filenames)} card(s) to the generic back."
    }


def auto_detect_custom_backs(export_dir):
    if not export_dir or not os.path.isdir(export_dir):
        return {"error": f"Directory not found: '{export_dir}'"}

    try:
        front_pdfs = collect_front_pdfs(export_dir)
    except Exception as e:
        return {"error": f"Could not read front cards: {e}"}

    backs_dir = os.path.join(export_dir, "backs")
    back_files = []
    if os.path.isdir(backs_dir):
        back_files = [f for f in os.listdir(backs_dir) if f.lower().endswith(".pdf")]

    mapping = load_custom_backs(export_dir)
    new_detected = 0

    # 1. XML detection
    for xml_cand in [os.path.join(export_dir, "cards.xml"), os.path.join(export_dir, "images", "cards.xml")]:
        if os.path.isfile(xml_cand):
            try:
                tree = ET.parse(xml_cand)
                root = tree.getroot()
                f_by_slot = {}
                for c in root.findall("fronts/card"):
                    cname = c.findtext("name", "").strip()
                    cid = c.findtext("id", "").strip()
                    cquery = c.findtext("query", "").strip()
                    for s in [x.strip() for x in c.findtext("slots", "").split(",") if x.strip()]:
                        f_by_slot[s] = {"name": cname, "id": cid, "query": cquery}

                for b in root.findall("backs/card"):
                    bname = b.findtext("name", "").strip()
                    bid = b.findtext("id", "").strip()
                    bquery = b.findtext("query", "").strip()
                    for s in [x.strip() for x in b.findtext("slots", "").split(",") if x.strip()]:
                        if s in f_by_slot:
                            f_info = f_by_slot[s]
                            f_match = None
                            for f in front_pdfs:
                                f_base = os.path.basename(f)
                                if (f_info["id"] and f_info["id"] in f_base) or \
                                   (normalize_card_text(f_info["name"]) and normalize_card_text(f_info["name"]) in normalize_card_text(f_base)) or \
                                   (normalize_card_text(f_info["query"]) and normalize_card_text(f_info["query"]) in normalize_card_text(f_base)):
                                    f_match = f_base
                                    break
                            b_match = None
                            for bf in back_files:
                                if (bid and bid in bf) or \
                                   (normalize_card_text(bname) and normalize_card_text(bname) in normalize_card_text(bf)) or \
                                   (normalize_card_text(bquery) and normalize_card_text(bquery) in normalize_card_text(bf)):
                                    b_match = os.path.join("backs", bf)
                                    break
                            if f_match and b_match:
                                mapping[f_match] = b_match
                                new_detected += 1
            except Exception:
                pass
            break

    # 2. Disk name matching in backs/
    if back_files:
        for f in front_pdfs:
            f_base = os.path.basename(f)
            if f_base in mapping:
                continue
            f_norm = normalize_card_text(f_base)
            for bf in back_files:
                if bf.lower().startswith(("sheet", "deckgen_", "card_back", "back.pdf", "cardback")):
                    continue
                bf_norm = normalize_card_text(bf)
                if bf_norm and (bf_norm == f_norm or bf_norm in f_norm or f_norm in bf_norm):
                    mapping[f_base] = os.path.join("backs", bf)
                    new_detected += 1
                    break

    save_custom_backs(export_dir, mapping)

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
        "detected_count": new_detected,
        "total_custom": len(mapping),
        "message": f"Auto-detected {new_detected} custom back(s)."
    }
