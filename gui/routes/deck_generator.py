import asyncio
import base64
import io
import os
import shutil
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from config import DPI, PREVIEW_CACHE_DIR, RENDER_CACHE_DIR
from core.pdf_build import IMAGE_EXTS, build_pdf, image_to_standard_pdf
from core.workspace import check_dir_collision, ensure_workspace_subdirs, load_project_from_dir, resolve_collision_target
from services.card_project import ScryfallError, register_card_project, resolve_card
from services.deck_service import build_card_project, build_deck_sheets, dfc_back_pairs

router = APIRouter(prefix="/api/deck")

_PROGRESS_STATE: Dict[str, Any] = {"percent": 0, "message": "Listo", "done": True}


def _set_progress(done: int, total: int, message: str) -> None:
    pct = int(round((done / max(1, total)) * 100))
    _PROGRESS_STATE["percent"] = min(99, max(0, pct))
    _PROGRESS_STATE["message"] = message
    _PROGRESS_STATE["done"] = False


@router.get("/progress")
async def api_deck_progress():
    return _PROGRESS_STATE


@router.get("/cards")
async def api_deck_cards(root_dir: str = Query(...)):
    if not root_dir or not os.path.isdir(root_dir):
        return {"cards": []}
    state = load_project_from_dir(root_dir)
    return {"cards": state["card_builder"].get("cards") or []}


@router.post("/import-cards")
async def api_deck_import_cards(payload: Dict[str, Any] = Body(...)):
    root_dir = (payload.get("root_dir") or "").strip()
    if not root_dir or not os.path.isdir(root_dir):
        raise HTTPException(status_code=400, detail="Debe haber un proyecto activo (root_dir).")
    entries = payload.get("cards") or []
    if not entries:
        raise HTTPException(status_code=400, detail="No hay cartas para importar.")

    loop = asyncio.get_running_loop()
    imported, errors = [], []
    for entry in entries:
        try:
            card = await loop.run_in_executor(
                None,
                lambda e=entry: resolve_card(card=e) if isinstance(e, dict) else resolve_card(name=str(e)),
            )
            project = await loop.run_in_executor(None, lambda c=card: build_card_project(c))
        except ScryfallError as exc:
            errors.append({"entry": entry.get("name") if isinstance(entry, dict) else entry, "error": exc.message})
            continue
        imported.append(await loop.run_in_executor(None, lambda p=project: register_card_project(root_dir, p)))

    return {"status": "ok", "cards": imported, "errors": errors}


@router.post("/preview")
async def api_deck_preview(payload: Dict[str, Any] = Body(...)):
    source_dir = (payload.get("source_folder") or "").strip()
    root_dir = (payload.get("root_dir") or "").strip()
    if not source_dir and root_dir:
        cand = os.path.join(root_dir, "cards", "fronts")
        if os.path.isdir(cand):
            source_dir = cand

    face = payload.get("face", "fronts")
    paper = payload.get("paper", "a4")
    landscape = bool(payload.get("landscape", False))
    cut = payload.get("cut", "corners")
    color = payload.get("color", "#ff0000")
    thickness = float(payload.get("thickness", 0.5))
    mark_len = float(payload.get("mark_len", 3.0))
    card_spacing = float(payload.get("card_spacing", 0.0))
    duplex_flip = bool(payload.get("duplex_flip", True))
    page = int(payload.get("page", 0))
    card_scales = payload.get("card_scales") or {}
    generic_back = payload.get("generic_back") or None
    custom_backs = payload.get("custom_backs") or {}
    dfc_pairs = dfc_back_pairs(root_dir)
    dfc_as_backs = bool(payload.get("dfc_backs"))

    loop = asyncio.get_running_loop()
    try:
        sheets, meta = await loop.run_in_executor(
            None,
            lambda: build_deck_sheets(
                source_dir=source_dir,
                face=face,
                paper=paper,
                landscape=landscape,
                cut=cut,
                color=color,
                thickness=thickness,
                mark_len=mark_len,
                card_spacing=card_spacing,
                duplex_flip=duplex_flip,
                preview=True,
                page=page,
                card_scales=card_scales,
                generic_back_path=generic_back,
                custom_backs=custom_backs,
                dfc_pairs=dfc_pairs,
                dfc_as_backs=dfc_as_backs,
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    buf = io.BytesIO()
    sheets[0].save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {
        "image_data_url": f"data:image/png;base64,{b64}",
        "meta": meta,
    }


@router.post("/generate")
async def api_deck_generate(payload: Dict[str, Any] = Body(...)):
    root_dir = (payload.get("root_dir") or "").strip()
    source_dir = (payload.get("source_folder") or "").strip()
    if not root_dir or not os.path.isdir(root_dir):
        raise HTTPException(status_code=400, detail="Debe haber un proyecto activo (root_dir).")

    paths = ensure_workspace_subdirs(root_dir)
    if not source_dir:
        source_dir = paths["fronts"]
    if not os.path.isdir(source_dir):
        raise HTTPException(status_code=400, detail=f"Carpeta de origen no encontrada: {source_dir}")

    face = payload.get("face", "fronts")
    paper = payload.get("paper", "a4")
    landscape = bool(payload.get("landscape", False))
    cut = payload.get("cut", "corners")
    color = payload.get("color", "#ff0000")
    thickness = float(payload.get("thickness", 0.5))
    mark_len = float(payload.get("mark_len", 3.0))
    card_spacing = float(payload.get("card_spacing", 0.0))
    duplex_flip = bool(payload.get("duplex_flip", True))
    export_dpi = int(payload.get("export_dpi", DPI))
    card_scales = payload.get("card_scales") or {}
    generic_back = payload.get("generic_back") or None
    custom_backs = payload.get("custom_backs") or {}
    dfc_pairs = dfc_back_pairs(root_dir)
    dfc_as_backs = bool(payload.get("dfc_backs"))
    collision_mode = payload.get("collision_mode")  # None | "check" | "overwrite" | "version"

    export_base_name = f"{face}_{paper}"
    if collision_mode in (None, "check"):
        col_info = check_dir_collision(paths["sheets"], export_base_name)
        if col_info["collision"]:
            return {"status": "collision", "collision": col_info}

    dest_dir = resolve_collision_target(paths["sheets"], export_base_name, collision_mode or "version")
    _PROGRESS_STATE.update({"percent": 5, "message": "Iniciando generación de hojas...", "done": False})

    loop = asyncio.get_running_loop()
    try:
        sheets, meta = await loop.run_in_executor(
            None,
            lambda: build_deck_sheets(
                source_dir=source_dir,
                face=face,
                paper=paper,
                landscape=landscape,
                cut=cut,
                color=color,
                thickness=thickness,
                mark_len=mark_len,
                card_spacing=card_spacing,
                duplex_flip=duplex_flip,
                preview=False,
                export_dpi=export_dpi,
                card_scales=card_scales,
                generic_back_path=generic_back,
                custom_backs=custom_backs,
                dfc_pairs=dfc_pairs,
                dfc_as_backs=dfc_as_backs,
                progress_cb=_set_progress,
            ),
        )
        _PROGRESS_STATE.update({"percent": 92, "message": "Guardando PDF final...", "done": False})
        pdf_name = f"deckgen_{face}_{paper}.pdf"
        pdf_path = await loop.run_in_executor(
            None, lambda: build_pdf(sheets, dest_dir, filename=pdf_name, dpi=export_dpi)
        )
        _PROGRESS_STATE.update({"percent": 100, "message": "Completado", "done": True})
    except Exception as exc:
        _PROGRESS_STATE.update({"percent": 0, "message": f"Error: {exc}", "done": True})
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "status": "ok",
        "pdf_path": pdf_path,
        "dest_dir": dest_dir,
        "download_url": f"/api/deck/download?path={pdf_path}",
        "meta": meta,
    }


@router.get("/download")
async def api_deck_download(path: str = Query(...)):
    abs_path = os.path.abspath(path)
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")
    return FileResponse(abs_path, filename=os.path.basename(abs_path), media_type="application/pdf")


@router.post("/clear-cache")
async def api_deck_clear_cache():
    for d in (RENDER_CACHE_DIR, PREVIEW_CACHE_DIR):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    return {"status": "ok"}


@router.post("/upload-back")
async def api_deck_upload_back(
    file: UploadFile = File(...),
    root_dir: str = Form(...),
    card_name: str = Form(default=""),
):
    from utils.text import safe_card_filename
    root_dir = (root_dir or "").strip()
    if not root_dir or not os.path.isdir(root_dir):
        raise HTTPException(status_code=400, detail="Active project root_dir is required.")
    paths = ensure_workspace_subdirs(root_dir)
    backs_dir = paths["backs"]
    os.makedirs(backs_dir, exist_ok=True)

    orig_name = file.filename or "back.pdf"
    ext = os.path.splitext(orig_name)[1].lower()
    stem = safe_card_filename(os.path.splitext(card_name)[0]) if card_name.strip() else "back"
    final_pdf = os.path.join(backs_dir, f"{stem}.pdf")
    raw_bytes = await file.read()

    if ext == ".pdf":
        with open(final_pdf, "wb") as f:
            f.write(raw_bytes)
    elif ext in IMAGE_EXTS:
        tmp_img = os.path.join(backs_dir, f"_tmp_{stem}{ext}")
        with open(tmp_img, "wb") as f:
            f.write(raw_bytes)
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: image_to_standard_pdf(tmp_img, final_pdf, dpi=DPI))
        finally:
            if os.path.isfile(tmp_img):
                os.remove(tmp_img)
    else:
        raise HTTPException(status_code=400, detail="Back file must be PDF or PNG/JPG image.")

    return {"status": "ok", "path": final_pdf, "filename": os.path.basename(final_pdf)}


@router.get("/project-cards")
async def api_deck_project_cards(root_dir: str = Query(...), source_folder: str = Query(default="")):
    import urllib.parse
    root_dir = (root_dir or "").strip()
    if not root_dir or not os.path.isdir(root_dir):
        return {"cards": []}
    paths = ensure_workspace_subdirs(root_dir)
    scan_dirs = []
    for d in (paths["backs"], paths["fronts"], source_folder.strip()):
        if d and os.path.isdir(d) and d not in scan_dirs:
            scan_dirs.append(d)
        sub_pdfs = os.path.join(d, "pdfs") if d else ""
        if sub_pdfs and os.path.isdir(sub_pdfs) and sub_pdfs not in scan_dirs:
            scan_dirs.append(sub_pdfs)

    seen_paths = set()
    items = []
    valid_exts = (".pdf",) + IMAGE_EXTS
    for d in scan_dirs:
        folder_label = os.path.basename(d.rstrip("/\\")) or d
        for fname in sorted(os.listdir(d)):
            if not fname.lower().endswith(valid_exts) or fname.lower().startswith("deckgen_"):
                continue
            fpath = os.path.join(d, fname)
            if not os.path.isfile(fpath) or fpath in seen_paths:
                continue
            seen_paths.add(fpath)
            items.append({
                "name": os.path.splitext(fname)[0],
                "filename": fname,
                "path": fpath,
                "folder": folder_label,
                "thumb_url": f"/api/deck/card-thumb?path={urllib.parse.quote(fpath)}",
            })
    return {"cards": items}


@router.get("/card-thumb")
async def api_deck_card_thumb(path: str = Query(...)):
    import hashlib
    import tempfile
    from fastapi.responses import Response
    from core.pdf_render import render_card_file_to_image

    abs_path = os.path.abspath(path)
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="Card file not found.")

    os.makedirs(PREVIEW_CACHE_DIR, exist_ok=True)
    mtime = int(os.path.getmtime(abs_path))
    cache_key = hashlib.sha256(f"{abs_path}:{mtime}".encode("utf-8")).hexdigest()
    thumb_path = os.path.join(PREVIEW_CACHE_DIR, f"thumb_{cache_key}.png")

    if not os.path.isfile(thumb_path):
        loop = asyncio.get_running_loop()
        def _build():
            with tempfile.TemporaryDirectory() as tmp_d:
                img = render_card_file_to_image(abs_path, 72, tmp_d)
                img.thumbnail((180, 252))
                img.save(thumb_path, format="PNG")
        await loop.run_in_executor(None, _build)

    with open(thumb_path, "rb") as f:
        return Response(content=f.read(), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
