import json
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import tornado.web
from PIL import Image

from config import CARD_H_MM, CARD_W_MM, DPI, PAPER_SIZES, PREVIEW_CACHE_DIR, PREVIEW_DPI
from core.cache import _preview_cache_key, _preview_cache_path
from core.pdf_build import image_to_standard_pdf
from core.pdf_render import render_pdf_to_png
from core.sheets import (
    _draw_cut_lines_on_canvas,
    compute_grid,
    generate_base_sheets,
    generate_sheets,
)
from core.upload import _uploaded_dir_name, resolve_export_dir, save_uploaded_export
from domain.custom_backs import collect_front_pdfs, find_generic_back_pdf, load_custom_backs
from utils.conversions import mm_to_px, parse_bool


def parse_and_build_sheets(handler, preview=False, progress_callback=None, source_files=None, preview_meta=None):
    try:
        face = handler.get_body_argument("face")
        paper = handler.get_body_argument("paper")
        landscape = parse_bool(handler.get_body_argument("landscape", "false"))
        cut = handler.get_body_argument("cut")
        color = handler.get_body_argument("color")
        thickness = float(handler.get_body_argument("thickness"))
        mark_len = float(handler.get_body_argument("mark_len"))
        card_spacing = float(handler.get_body_argument("card_spacing", "0"))
    except (ValueError, tornado.web.MissingArgumentError) as exc:
        return None, f"invalid form input: {exc}"

    if source_files is None:
        files = handler.request.files.get("files", [])
        source_files = handler.request.files.get("source_files", [])
        if not source_files:
            source_files = files

    back_files = handler.request.files.get("back_file", [])
    export_dir_param = handler.get_body_argument("export_dir", "").strip()

    if not preview and not source_files and not (export_dir_param and os.path.isdir(export_dir_param)) and not (face == "backs" and back_files):
        return None, "no source directory uploaded or valid export directory specified"

    if face not in ("fronts", "backs"):
        return None, "invalid face"

    if paper not in PAPER_SIZES:
        return None, "invalid paper"

    if cut not in ("none", "full", "corners"):
        return None, "invalid cut mode"

    dpi = PREVIEW_DPI if preview else DPI

    source_uploads = source_files
    source_name = _uploaded_dir_name(source_uploads) if source_uploads else (os.path.basename(export_dir_param) if export_dir_param else "back_only")

    with tempfile.TemporaryDirectory() as source_dir:
        real_source_dir = None
        if source_uploads:
            saved = save_uploaded_export(source_uploads, source_dir)
            if saved > 0:
                try:
                    real_source_dir = resolve_export_dir(source_dir)
                except ValueError:
                    real_source_dir = source_dir
        elif export_dir_param and os.path.isdir(export_dir_param):
            real_source_dir = export_dir_param

        # Conteo de cartas fronts para saber cuántos backs se requieren en generación completa
        front_count = None
        if real_source_dir:
            try:
                front_count = len(collect_front_pdfs(real_source_dir))
            except ValueError:
                pass

        paper_w_mm, paper_h_mm = PAPER_SIZES[paper]
        if landscape:
            paper_w_mm, paper_h_mm = paper_h_mm, paper_w_mm
        cols, rows = compute_grid(paper_w_mm, paper_h_mm, card_spacing)
        sheet_capacity = cols * rows

        duplex_flip = handler.get_body_argument("duplex_flip", "true").lower() in ("true", "1", "on", "yes")

        front_pdfs = []
        if real_source_dir:
            try:
                front_pdfs = collect_front_pdfs(real_source_dir)
            except ValueError:
                pass
        if not front_pdfs and export_dir_param and os.path.isdir(export_dir_param):
            try:
                front_pdfs = collect_front_pdfs(export_dir_param)
            except ValueError:
                pass

        if face == "fronts":
            if not front_pdfs:
                if preview:
                    pdfs = [None] * sheet_capacity
                else:
                    return None, "no source files uploaded for fronts"
            else:
                pdfs = front_pdfs
        else:
            # face == "backs"
            back_pdf_path = None
            if back_files:
                bf = back_files[0]
                fname = bf.get("filename", "").lower()
                body = bf.get("body", b"")
                if fname.endswith((".png", ".jpg", ".jpeg")):
                    back_pdf_path = os.path.join(source_dir, "uploaded_back.pdf")
                    image_to_standard_pdf(body, back_pdf_path)
                else:
                    back_pdf_path = os.path.join(source_dir, "uploaded_back.pdf")
                    with open(back_pdf_path, "wb") as f:
                        f.write(body)

            if not back_pdf_path and real_source_dir:
                back_pdf_path = find_generic_back_pdf(real_source_dir)

            if not back_pdf_path and export_dir_param and os.path.isdir(export_dir_param):
                back_pdf_path = find_generic_back_pdf(export_dir_param)

            effective_dir = export_dir_param if (export_dir_param and os.path.isdir(export_dir_param)) else real_source_dir
            custom_map = load_custom_backs(effective_dir)

            custom_back_map_raw = handler.get_body_argument("custom_back_map", "").strip()
            if custom_back_map_raw:
                try:
                    client_map = json.loads(custom_back_map_raw)
                except json.JSONDecodeError:
                    client_map = {}
                saved_field_paths = {}
                for card_fname, field_key in client_map.items():
                    if field_key not in saved_field_paths:
                        up_files = handler.request.files.get(field_key, [])
                        if up_files:
                            uf = up_files[0]
                            uf_name = uf.get("filename", "custom_back.pdf")
                            uf_body = uf.get("body", b"")
                            out_pdf = os.path.join(source_dir, f"cb_{len(saved_field_paths)}.pdf")
                            if uf_name.lower().endswith((".png", ".jpg", ".jpeg")):
                                image_to_standard_pdf(uf_body, out_pdf)
                            else:
                                with open(out_pdf, "wb") as f:
                                    f.write(uf_body)
                            saved_field_paths[field_key] = out_pdf
                    if field_key in saved_field_paths:
                        custom_map[card_fname] = saved_field_paths[field_key]

            if front_pdfs:
                pdfs = []
                for f in front_pdfs:
                    f_base = os.path.basename(f)
                    cback = custom_map.get(f_base)
                    if not cback:
                        clean_stem = os.path.splitext(f_base)[0]
                        cback = custom_map.get(clean_stem)

                    assigned_path = None
                    if cback:
                        if os.path.isabs(cback) and os.path.isfile(cback):
                            assigned_path = cback
                        elif effective_dir:
                            cand = os.path.join(effective_dir, cback)
                            if os.path.isfile(cand):
                                assigned_path = cand
                            else:
                                cand2 = os.path.join(effective_dir, "backs", cback)
                                if os.path.isfile(cand2):
                                    assigned_path = cand2

                    if assigned_path:
                        pdfs.append(assigned_path)
                    elif back_pdf_path:
                        pdfs.append(back_pdf_path)
                    else:
                        pdfs.append(None)
            elif back_pdf_path:
                needed = sheet_capacity
                pdfs = [back_pdf_path] * needed
            else:
                needed = sheet_capacity
                pdfs = [None] * needed

        if preview:
            try:
                req_page = max(0, int(handler.get_body_argument("page", "0")))
            except ValueError:
                req_page = 0
            total_pages = max(1, (len(pdfs) + sheet_capacity - 1) // sheet_capacity)
            page = min(req_page, total_pages - 1)
            if preview_meta is not None:
                preview_meta["total_pages"] = total_pages
                preview_meta["page"] = page
            pdfs = pdfs[page * sheet_capacity : (page + 1) * sheet_capacity]
            cache_key = _preview_cache_key(
                source_name, face, paper, landscape, card_spacing, pdfs, duplex_flip=duplex_flip
            )
            cache_path = _preview_cache_path(cache_key)
            if os.path.exists(cache_path):
                base = Image.open(cache_path).convert("RGB")
                canvas = base.copy()
                _draw_cut_lines_on_canvas(
                    canvas,
                    paper,
                    landscape,
                    dpi,
                    cut,
                    color,
                    thickness,
                    mark_len,
                    card_spacing,
                    is_back=(face == "backs"),
                    duplex_flip=duplex_flip,
                )
                return [canvas], None

        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                rendered_cache = {}
                if any(p is None for p in pdfs):
                    blank_w = mm_to_px(CARD_W_MM, dpi)
                    blank_h = mm_to_px(CARD_H_MM, dpi)
                    rendered_cache[None] = Image.new("RGB", (blank_w, blank_h), (255, 255, 255))
                unique_pdfs = [p for p in dict.fromkeys(pdfs) if p is not None]
                workers = min(8, os.cpu_count() or 1)
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(render_pdf_to_png, pdf, dpi, tmp_dir): pdf
                        for pdf in unique_pdfs
                    }
                    for future in as_completed(futures):
                        pdf = futures[future]
                        rendered_cache[pdf] = future.result()
                        if progress_callback:
                            progress_callback(len(rendered_cache), len(unique_pdfs))
                images = [rendered_cache[pdf] for pdf in pdfs]
                if preview:
                    base_sheets = generate_base_sheets(
                        images,
                        paper,
                        landscape,
                        dpi,
                        card_spacing,
                        is_back=(face == "backs"),
                        duplex_flip=duplex_flip,
                    )
                    base = base_sheets[0]
                    os.makedirs(PREVIEW_CACHE_DIR, exist_ok=True)
                    base.save(cache_path, format="PNG")
                    canvas = base.copy()
                    _draw_cut_lines_on_canvas(
                        canvas,
                        paper,
                        landscape,
                        dpi,
                        cut,
                        color,
                        thickness,
                        mark_len,
                        card_spacing,
                        is_back=(face == "backs"),
                        duplex_flip=duplex_flip,
                    )
                    return [canvas], None
                sheets = generate_sheets(
                    images,
                    paper,
                    landscape,
                    dpi,
                    cut,
                    color,
                    thickness,
                    mark_len,
                    card_spacing,
                    is_back=(face == "backs"),
                    duplex_flip=duplex_flip,
                )
            except (subprocess.CalledProcessError, ValueError, RuntimeError, OSError) as exc:
                return None, str(exc)
    return sheets, None
