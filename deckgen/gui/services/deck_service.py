import hashlib
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image

from config import CARD_H_MM, CARD_W_MM, DPI, PAPER_SIZES, PREVIEW_CACHE_DIR, PREVIEW_DPI
from core.pdf_build import IMAGE_EXTS, build_pdf, convert_images_folder_to_pdfs, image_to_standard_pdf
from core.pdf_render import render_card_file_to_image
from core.sheets import draw_cut_lines_on_canvas, generate_base_sheets, generate_sheets, sheet_geometry
from utils.conversions import mm_to_px
from utils.text import safe_card_filename


def list_card_pdfs(source_dir: str) -> List[str]:
    """Card PDFs in source_dir (or source_dir/pdfs), in sheet order. Never converts images."""
    if not source_dir or not os.path.isdir(source_dir):
        return []
    direct_pdfs = sorted(
        os.path.join(source_dir, f)
        for f in os.listdir(source_dir)
        if f.lower().endswith(".pdf") and not f.lower().startswith("deckgen_") and os.path.isfile(os.path.join(source_dir, f))
    )
    if direct_pdfs:
        return direct_pdfs
    pdfs_subdir = os.path.join(source_dir, "pdfs")
    if os.path.isdir(pdfs_subdir):
        return sorted(
            os.path.join(pdfs_subdir, f)
            for f in os.listdir(pdfs_subdir)
            if f.lower().endswith(".pdf") and os.path.isfile(os.path.join(pdfs_subdir, f))
        )
    return []


def migrate_index_card_scales(card_scales: Dict[str, float], source_dir: str) -> Dict[str, float]:
    """Old projects keyed card_scales by sheet position ("3"); map them to that card's file name.

    Positions are resolved against the current front files (without DFC pairing, which
    didn't exist when positions were used). Unresolvable positions are kept as-is.
    """
    if not any(str(k).isdigit() for k in card_scales):
        return card_scales
    names = [os.path.basename(f) for f in list_card_pdfs(source_dir)]
    if not names:
        return card_scales
    out: Dict[str, float] = {}
    for k, v in card_scales.items():
        k = str(k)
        if k.isdigit() and int(k) < len(names):
            out.setdefault(names[int(k)], v)
        else:
            out[k] = v
    return out


def collect_card_sources(source_dir: str, progress_cb: Optional[Callable[[int, int, str], None]] = None) -> Tuple[List[str], bool]:
    """
    Collects card PDFs from source_dir (or source_dir/pdfs).
    If only PNG/JPG images are present and no PDFs exist, automatically converts them
    in background to standard PDFs inside <source_dir>/pdfs/!
    Returns (list_of_pdf_paths, did_background_conversion).
    """
    if not source_dir or not os.path.isdir(source_dir):
        return [], False

    existing = list_card_pdfs(source_dir)
    if existing:
        return existing, False
    pdfs_subdir = os.path.join(source_dir, "pdfs")

    # Check for PNG/JPG images -> automatic background conversion
    has_imgs = any(
        f.lower().endswith(IMAGE_EXTS) and os.path.isfile(os.path.join(source_dir, f))
        for f in os.listdir(source_dir)
    )
    if has_imgs:
        def _cb(done, total):
            if progress_cb:
                progress_cb(done, total, f"Convirtiendo imágenes a PDF ({done}/{total})...")
        converted = convert_images_folder_to_pdfs(source_dir, pdfs_subdir, dpi=DPI, progress_cb=_cb)
        return converted, True

    return [], False


def find_generic_back_file(source_dir: str) -> Optional[str]:
    if not source_dir or not os.path.isdir(source_dir):
        return None
    for cand_name in ("back.pdf", "back.png", "back.jpg", "card_back.pdf", "card_back.png"):
        p = os.path.join(source_dir, cand_name)
        if os.path.isfile(p):
            return p
    return None


def dfc_back_pairs(root_dir: str) -> Dict[str, str]:
    """{front file stem: back file stem} for the double-faced cards in the project's Card Builder.

    Both faces must be in the project (the Card Builder adds them together, see
    extract_scryfall_card_payloads). Stems match the exported file names.
    """
    state_path = os.path.join(root_dir or "", "state.json")
    if not os.path.isfile(state_path):
        return {}
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            cards = (json.load(f).get("card_builder") or {}).get("cards") or []
    except (OSError, ValueError):
        return {}
    names = {c.get("name") for c in cards if isinstance(c, dict)}
    pairs = {}
    for c in cards:
        dfc = (c.get("dfc") if isinstance(c, dict) else None) or {}
        faces = dfc.get("face_names") or []
        if dfc.get("face_index") == 0 and len(faces) >= 2 and faces[1] in names:
            pairs[safe_card_filename(faces[0])] = safe_card_filename(faces[1])
    return pairs


def build_deck_sheets(
    source_dir: str,
    face: str = "fronts",
    paper: str = "a4",
    landscape: bool = False,
    cut: str = "corners",
    color: str = "#ff0000",
    thickness: float = 0.5,
    mark_len: float = 3.0,
    card_spacing: float = 0.0,
    duplex_flip: bool = True,
    preview: bool = False,
    page: int = 0,
    export_dpi: int = DPI,
    card_scales: Optional[Dict[str, float]] = None,
    generic_back_path: Optional[str] = None,
    custom_backs: Optional[Dict[str, str]] = None,
    dfc_pairs: Optional[Dict[str, str]] = None,
    dfc_as_backs: bool = False,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[List[Image.Image], Dict[str, Any]]:
    if paper not in PAPER_SIZES:
        raise ValueError(f"Invalid paper size: {paper}")
    if face not in ("fronts", "backs"):
        raise ValueError(f"Invalid face: {face}")
    if cut not in ("none", "full", "corners"):
        raise ValueError(f"Invalid cut mode: {cut}")

    dpi = PREVIEW_DPI if preview else max(150, min(1200, int(export_dpi)))
    paper_w_mm, paper_h_mm = PAPER_SIZES[paper]
    if landscape:
        paper_w_mm, paper_h_mm = paper_h_mm, paper_w_mm
    cols, rows, paper_px, card_px, margin_x, margin_y, gap_px = sheet_geometry(
        paper, landscape, dpi, card_spacing
    )
    sheet_capacity = cols * rows

    front_pdfs, did_bg_convert = collect_card_sources(source_dir, progress_cb=progress_cb)
    custom_map = custom_backs or {}

    # Double-faced cards printed back-to-back: the back face file leaves the fronts and
    # becomes the back of its front face (unless that front has its own custom back).
    # dfc_pairs ({front stem: back stem}) also labels DFC slots in the preview when this is off.
    dfc_pairs = dfc_pairs or {}
    dfc_back_for: Dict[str, str] = {}
    if dfc_as_backs:
        by_stem = {os.path.splitext(os.path.basename(f))[0]: f for f in front_pdfs}
        for front_stem, back_stem in dfc_pairs.items():
            if front_stem in by_stem and back_stem in by_stem:
                dfc_back_for[front_stem] = by_stem[back_stem]
        dfc_back_files = set(dfc_back_for.values())
        front_pdfs = [f for f in front_pdfs if f not in dfc_back_files]
    g_back = generic_back_path if (generic_back_path and os.path.isfile(generic_back_path)) else find_generic_back_file(source_dir)

    if face == "fronts":
        files_list = front_pdfs if front_pdfs else ([None] * sheet_capacity if preview else [])
        if not files_list:
            raise ValueError("No card PDFs or images found in the selected folder.")
    else:
        if front_pdfs:
            files_list = []
            for f in front_pdfs:
                base = os.path.basename(f)
                stem = os.path.splitext(base)[0]
                cb = custom_map.get(base) or custom_map.get(stem) or dfc_back_for.get(stem)
                if cb and os.path.isfile(cb):
                    files_list.append(cb)
                elif g_back:
                    files_list.append(g_back)
                else:
                    files_list.append(None)
        elif g_back:
            files_list = [g_back] * sheet_capacity
        else:
            files_list = [None] * sheet_capacity if preview else []
            if not files_list:
                raise ValueError("No back files or front cards found.")

    # card_scales is keyed by the front card's file name; a back shares its front's scale.
    # Slots without a front file (blank/generic-only back sheets) fall back to their position.
    slot_keys = [os.path.basename(f) for f in front_pdfs]
    slot_keys += [str(i) for i in range(len(slot_keys), len(files_list))]
    scales_by_key = card_scales or {}
    index_scales = {str(i): float(scales_by_key[k]) for i, k in enumerate(slot_keys) if k in scales_by_key}

    total_cards = len(files_list)
    total_pages = max(1, (total_cards + sheet_capacity - 1) // sheet_capacity)
    safe_page = max(0, min(page, total_pages - 1))
    start_idx = safe_page * sheet_capacity if preview else 0
    slice_files = files_list[start_idx : start_idx + sheet_capacity] if preview else files_list

    with tempfile.TemporaryDirectory() as tmp_dir:
        rendered_cache: Dict[Optional[str], Image.Image] = {}
        if any(p is None for p in slice_files):
            blank_w = mm_to_px(CARD_W_MM, dpi)
            blank_h = mm_to_px(CARD_H_MM, dpi)
            rendered_cache[None] = Image.new("RGB", (blank_w, blank_h), (255, 255, 255))

        unique_files = [p for p in dict.fromkeys(slice_files) if p is not None]
        workers = min(8, os.cpu_count() or 1)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(render_card_file_to_image, fp, dpi, tmp_dir): fp
                for fp in unique_files
            }
            done_count = 0
            for fut in as_completed(futures):
                fp = futures[fut]
                rendered_cache[fp] = fut.result()
                done_count += 1
                if progress_cb:
                    progress_cb(done_count, len(unique_files), f"Renderizando cartas ({done_count}/{len(unique_files)})...")

        images = [rendered_cache[fp] for fp in slice_files]
        sheets = generate_sheets(
            images,
            paper,
            landscape,
            dpi,
            cut,
            color,
            thickness,
            mark_len,
            card_spacing=card_spacing,
            is_back=(face == "backs"),
            duplex_flip=duplex_flip,
            card_scales=index_scales,
            global_start_index=start_idx,
        )

    front_of = {back: front for front, back in dfc_pairs.items()}

    def _slot_dfc(abs_idx: int) -> Optional[Dict[str, Any]]:
        """Which face of a double-faced card a slot shows, for the preview badge."""
        if face == "fronts":
            fp = files_list[abs_idx]
            stem = os.path.splitext(os.path.basename(fp))[0] if fp else ""
            if stem in dfc_pairs:
                return {"role": "front", "other": dfc_pairs[stem], "back_on_reverse": stem in dfc_back_for}
            if stem in front_of:
                return {"role": "back", "other": front_of[stem], "back_on_reverse": False}
            return None
        if abs_idx < len(front_pdfs):
            stem = os.path.splitext(os.path.basename(front_pdfs[abs_idx]))[0]
            if stem in dfc_back_for and files_list[abs_idx] == dfc_back_for[stem]:
                return {"role": "back", "other": stem, "back_on_reverse": True}
        return None

    # Compute normalized slot rectangles for interactive individual card scaling in preview
    slots_meta = []
    pitch_x = card_px[0] + gap_px
    pitch_y = card_px[1] + gap_px
    pw, ph = paper_px
    for idx in range(len(slice_files)):
        r = idx // cols
        c = idx % cols
        xf = margin_x + c * pitch_x
        yf = margin_y + r * pitch_y
        x = (pw - xf - card_px[0]) if (face == "backs" and duplex_flip) else xf
        abs_idx = start_idx + idx
        slots_meta.append({
            "index": abs_idx,
            "scale_key": slot_keys[abs_idx],
            "dfc": _slot_dfc(abs_idx),
            "name": os.path.basename(slice_files[idx]) if slice_files[idx] else f"Slot {abs_idx + 1}",
            "x_pct": round(x / pw, 5),
            "y_pct": round(yf / ph, 5),
            "w_pct": round(card_px[0] / pw, 5),
            "h_pct": round(card_px[1] / ph, 5),
            "scale": index_scales.get(str(abs_idx), 1.0),
        })

    meta = {
        "page": safe_page,
        "total_pages": total_pages,
        "total_cards": total_cards,
        "cols": cols,
        "rows": rows,
        "did_background_convert": did_bg_convert,
        "slots": slots_meta,
    }
    return sheets, meta
