import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from core.workspace import (
    check_dir_collision,
    create_project,
    load_project_from_dir,
    normalize_loaded_state,
    pick_native_directory,
    save_project_state,
)

router = APIRouter(prefix="/api")


@router.post("/workspace/create")
async def api_workspace_create(payload: Dict[str, Any] = Body(...)):
    root_dir = (payload.get("root_dir") or "").strip()
    project_name = payload.get("project_name")
    if not root_dir:
        raise HTTPException(status_code=400, detail="Debe seleccionar un directorio raíz.")
    try:
        state = create_project(root_dir, project_name)
        return {"status": "ok", "state": state}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/load")
async def api_workspace_load(payload: Dict[str, Any] = Body(...)):
    root_dir = (payload.get("root_dir") or "").strip()
    if not root_dir:
        raise HTTPException(status_code=400, detail="Debe seleccionar un directorio raíz.")
    try:
        state = load_project_from_dir(root_dir)
        return {"status": "ok", "state": state}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/load-json")
async def api_workspace_load_json(payload: Dict[str, Any] = Body(...)):
    raw_state = payload.get("state")
    if not isinstance(raw_state, dict):
        raise HTTPException(status_code=400, detail="Archivo state.json inválido.")
    root_dir = (payload.get("root_dir") or raw_state.get("root_dir") or "").strip()
    state = normalize_loaded_state(raw_state, fallback_root=root_dir or None)
    if root_dir and os.path.isdir(root_dir):
        state = save_project_state(root_dir, state)
    return {"status": "ok", "state": state}


@router.get("/workspace/state")
async def api_workspace_get_state(root_dir: str = Query(...)):
    try:
        state = load_project_from_dir(root_dir)
        return {"status": "ok", "state": state}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/state")
async def api_workspace_save_state(payload: Dict[str, Any] = Body(...)):
    root_dir = (payload.get("root_dir") or "").strip()
    state = payload.get("state")
    if not root_dir or not isinstance(state, dict):
        raise HTTPException(status_code=400, detail="Faltan root_dir o state.")
    try:
        saved = save_project_state(root_dir, state)
        return {"status": "ok", "state": saved}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/native-pick")
async def api_workspace_native_pick(payload: Dict[str, Any] = Body(default={})):
    initial = payload.get("initial_dir")
    return pick_native_directory(initial)


@router.post("/workspace/check-collision")
async def api_workspace_check_collision(payload: Dict[str, Any] = Body(...)):
    parent_dir = (payload.get("parent_dir") or "").strip()
    base_name = (payload.get("base_name") or "").strip()
    if not parent_dir or not base_name:
        raise HTTPException(status_code=400, detail="parent_dir y base_name son requeridos.")
    return check_dir_collision(parent_dir, base_name)


@router.get("/fs/browse")
async def api_fs_browse(path: str = Query(default="")):
    req_path = path.strip()
    if req_path and os.path.isdir(req_path):
        current = os.path.abspath(req_path)
    elif req_path and os.path.isdir(os.path.dirname(req_path)):
        current = os.path.abspath(os.path.dirname(req_path))
    else:
        current = os.path.expanduser("~")
        if not os.path.isdir(current):
            current = os.getcwd()

    dirs = []
    has_state_json = os.path.isfile(os.path.join(current, "state.json"))
    try:
        for entry in os.scandir(current):
            if entry.is_dir() and not entry.name.startswith("."):
                dirs.append(entry.name)
        dirs.sort(key=str.lower)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    parent = os.path.dirname(current)
    return {
        "current": current,
        "parent": parent if parent != current else None,
        "dirs": dirs,
        "has_state_json": has_state_json,
    }


@router.post("/fs/mkdir")
async def api_fs_mkdir(payload: Dict[str, Any] = Body(...)):
    current = (payload.get("current") or "").strip()
    folder_name = (payload.get("folder_name") or "").strip()
    if not current or not os.path.isdir(current):
        raise HTTPException(status_code=400, detail="Directorio actual inválido.")
    if not folder_name or "/" in folder_name or "\\" in folder_name or folder_name in (".", ".."):
        raise HTTPException(status_code=400, detail="Nombre de carpeta inválido.")
    new_dir = os.path.join(os.path.abspath(current), folder_name)
    try:
        os.makedirs(new_dir, exist_ok=True)
        return {"status": "ok", "created": new_dir}
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/fs/list-files")
async def api_fs_list_files(path: str = Query(...), exts: str = Query(default=".png,.jpg,.jpeg,.pdf")):
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Directorio no encontrado.")
    allowed = tuple(e.strip().lower() for e in exts.split(",") if e.strip())
    files = sorted(
        f for f in os.listdir(path)
        if os.path.isfile(os.path.join(path, f)) and f.lower().endswith(allowed)
    )
    return {"path": os.path.abspath(path), "files": files, "count": len(files)}
