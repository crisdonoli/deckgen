import asyncio
import base64
import os
import tempfile
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

from core.card_renderer import save_recipe_png
from core.frame_resolver import build_recipe
from core.workspace import ensure_workspace_subdirs
from services.card_project import (
    ScryfallError,
    build_card_project,
    cache_path_for_key,
    load_project_file,
    register_card_project,
    resolve_card,
    save_project_file,
)
from utils.text import safe_card_filename

router = APIRouter(prefix="/api/card-builder")


def _project_recipe(card: dict, face_index, showcase_style_override) -> dict:
    source = dict(card)
    if showcase_style_override:
        source["showcase_style_override"] = showcase_style_override
    recipe = build_recipe(source)
    if face_index is not None:
        recipe["recipes"] = [r for r in recipe.get("recipes") or [] if r.get("face_index") == face_index]
    return recipe


@router.post("/import-scryfall")
async def api_cb_import_scryfall(payload: Dict[str, Any] = Body(...)):
    try:
        card = resolve_card(
            card=payload.get("card"),
            url=(payload.get("url") or "").strip() or None,
            name=(payload.get("name") or "").strip() or None,
            set_code=(payload.get("set") or "").strip() or None,
        )
    except ScryfallError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)

    face_index = payload.get("face_index")
    face_index = int(face_index) if face_index is not None else None
    showcase_style_override = (payload.get("showcase_style_override") or None)
    loop = asyncio.get_running_loop()
    project, recipe = await loop.run_in_executor(
        None,
        lambda: (
            build_card_project(
                card,
                face_index=face_index,
                showcase_style_override=showcase_style_override,
            ),
            _project_recipe(card, face_index, showcase_style_override),
        ),
    )
    project["recipe"] = recipe
    save_project_file(project)

    root_dir = (payload.get("root_dir") or "").strip()
    if root_dir and os.path.isdir(root_dir):
        register_card_project(root_dir, project)
    return project


@router.get("/project/{project_id}")
async def api_cb_project(project_id: str):
    project = load_project_file(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
    return project


@router.get("/asset/{key}")
async def api_cb_asset(key: str):
    path = cache_path_for_key(key)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Asset no encontrado.")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.post("/export-batch")
async def api_cb_export_batch(payload: Dict[str, Any] = Body(...)):
    root_dir = (payload.get("root_dir") or "").strip()
    project_ids = payload.get("project_ids") or []
    target_dir = (payload.get("target_dir") or "").strip()

    if not root_dir or not os.path.isdir(root_dir):
        raise HTTPException(status_code=400, detail="Invalid active project.")
    if not project_ids:
        raise HTTPException(status_code=400, detail="No projects selected for export.")

    dest_dir = target_dir or os.path.join(ensure_workspace_subdirs(root_dir)["cards"], "png")
    os.makedirs(dest_dir, exist_ok=True)

    files = []
    for project_id in project_ids:
        project = load_project_file(project_id)
        if project is None or not project.get("recipe"):
            raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        out_path = os.path.join(dest_dir, f"{safe_card_filename(project.get('name') or project_id)}.png")
        save_recipe_png(project["recipe"], out_path)
        files.append(out_path)

    return {"status": "ok", "dest_dir": dest_dir, "exported_count": len(files), "files": files}


@router.post("/export")
async def api_cb_export(payload: Dict[str, Any] = Body(...)):
    project = load_project_file(payload.get("project_id") or "")
    if project is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")

    face_index = payload.get("face_index")
    face_index = 0 if face_index is None else int(face_index)
    recipe = dict(project.get("recipe") or {})
    faces = [r for r in recipe.get("recipes") or [] if r.get("face_index") == face_index]
    if faces:
        recipe["recipes"] = faces

    art_override = None
    data_url = payload.get("art_override_dataurl")
    if data_url:
        header, _, encoded = data_url.partition(",")
        if not header.startswith("data:image/") or not encoded:
            raise HTTPException(status_code=400, detail="dataURL inválida.")
        try:
            art_override = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise HTTPException(status_code=400, detail="dataURL inválida.")

    fd, out_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        save_recipe_png(recipe, out_path, art_override=art_override)
        with open(out_path, "rb") as handle:
            png_bytes = handle.read()
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
    finally:
        if os.path.exists(out_path):
            os.remove(out_path)

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": 'attachment; filename="card.png"'},
    )

