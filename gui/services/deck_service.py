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


def collect_card_sources(source_dir: str, progress_cb: Optional[Callable[[int, int, str], None]] = None) -> Tuple[List[str], bool]:
    """
    Collects card PDFs from source_dir (or source_dir/pdfs).
    If only PNG/JPG images are present and no PDFs exist, automatically converts them
    in background to standard PDFs inside <source_dir>/pdfs/!
    Returns (list_of_pdf_paths, did_background_conversion).
    """
    if not source_dir or not os.path.isdir(source_dir):
        return [], False

    pdfs_subdir = os.path.join(source_dir, "pdfs")
    direct_pdfs = sorted(
        os.path.join(source_dir, f)
        for f in os.listdir(source_dir)
        if f.lower().endswith(".pdf") and not f.lower().startswith("deckgen_") and os.path.isfile(os.path.join(source_dir, f))
    )
    if direct_pdfs:
        return direct_pdfs, False

    if os.path.isdir(pdfs_subdir):
        sub_pdfs = sorted(
            os.path.join(pdfs_subdir, f)
            for f in os.listdir(pdfs_subdir)
            if f.lower().endswith(".pdf") and os.path.isfile(os.path.join(pdfs_subdir, f))
        )
        if sub_pdfs:
            return sub_pdfs, False

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
                cb = custom_map.get(base) or custom_map.get(stem)
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
            card_scales=card_scales,
            global_start_index=start_idx,
        )

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
            "name": os.path.basename(slice_files[idx]) if slice_files[idx] else f"Slot {abs_idx + 1}",
            "x_pct": round(x / pw, 5),
            "y_pct": round(yf / ph, 5),
            "w_pct": round(card_px[0] / pw, 5),
            "h_pct": round(card_px[1] / ph, 5),
            "scale": float((card_scales or {}).get(str(abs_idx), 1.0)),
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
