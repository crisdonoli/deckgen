import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, Optional

from config import DEFAULT_STYLE_KEY
from core.asset_paths import migrate_card_frame_paths, migrate_style_key

STATE_FILENAME = "state.json"

DEFAULT_DECK_GEN_CONFIG = {
    "source_folder": "",
    "paper": "a4",
    "landscape": False,
    "cut": "corners",
    "card_spacing": 0.0,
    "color": "#ff0000",
    "thickness": 0.5,
    "mark_len": 3.0,
    "duplex_flip": True,
    "view_mode": "both",
    "export_dpi": 300,
    "card_scales": {},
    "custom_backs": {},
    "generic_back": "",
    "dfc_backs": False,
}


def default_project_state(root_dir: str, project_name: Optional[str] = None) -> Dict[str, Any]:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    abs_root = os.path.abspath(root_dir)
    name = (project_name or os.path.basename(abs_root) or "DeckGen Project").strip()
    return {
        "version": 2,
        "project_name": name,
        "root_dir": abs_root,
        "created_at": now,
        "updated_at": now,
        "card_builder": {
            "cards": [],
            "ready_ids": [],
            "active_card_id": None,
            "global_frame_style": DEFAULT_STYLE_KEY,
            "export_dpi": 1200,
            "export_format": "pdf",
        },
        "deck_generator": dict(DEFAULT_DECK_GEN_CONFIG),
    }


def ensure_workspace_subdirs(root_dir: str) -> Dict[str, str]:
    abs_root = os.path.abspath(root_dir)
    paths = {
        "root": abs_root,
        "cards": os.path.join(abs_root, "cards"),
        "fronts": os.path.join(abs_root, "cards", "fronts"),
        "backs": os.path.join(abs_root, "cards", "backs"),
        "json": os.path.join(abs_root, "cards", "json"),
        "sheets": os.path.join(abs_root, "sheets"),
        "cache": os.path.join(abs_root, ".deckgen_cache"),
    }
    for p in paths.values():
        os.makedirs(p, exist_ok=True)
    return paths


def atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def create_project(root_dir: str, project_name: Optional[str] = None) -> Dict[str, Any]:
    if not root_dir or not str(root_dir).strip():
        raise ValueError("Root directory path is required.")
    abs_root = os.path.abspath(os.path.expanduser(root_dir.strip()))
    ensure_workspace_subdirs(abs_root)
    state = default_project_state(abs_root, project_name)
    state_path = os.path.join(abs_root, STATE_FILENAME)
    atomic_write_json(state_path, state)
    return state


def normalize_loaded_state(raw: Dict[str, Any], fallback_root: Optional[str] = None) -> Dict[str, Any]:
    root = raw.get("root_dir") or fallback_root or os.getcwd()
    base = default_project_state(root, raw.get("project_name"))
    if isinstance(raw.get("created_at"), str):
        base["created_at"] = raw["created_at"]
    base["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    cb = raw.get("card_builder") or {}
    if isinstance(cb, dict):
        if isinstance(cb.get("cards"), list):
            base["card_builder"]["cards"] = cb["cards"]
        elif isinstance(raw.get("cards"), list):
            base["card_builder"]["cards"] = raw["cards"]
        for card in base["card_builder"]["cards"]:
            migrate_card_frame_paths(card)
        if isinstance(cb.get("ready_ids"), list):
            base["card_builder"]["ready_ids"] = cb["ready_ids"]
        base["card_builder"]["active_card_id"] = cb.get("active_card_id")
        if cb.get("global_frame_style"):
            base["card_builder"]["global_frame_style"] = migrate_style_key(cb["global_frame_style"])
        if cb.get("export_dpi"):
            base["card_builder"]["export_dpi"] = cb["export_dpi"]
        if cb.get("export_format") in ("pdf", "png"):
            base["card_builder"]["export_format"] = cb["export_format"]

    dg = raw.get("deck_generator") or {}
    if isinstance(dg, dict):
        for k, v in DEFAULT_DECK_GEN_CONFIG.items():
            if k in dg and dg[k] is not None:
                base["deck_generator"][k] = dg[k]
        scales = base["deck_generator"].get("card_scales")
        if isinstance(scales, dict) and scales:
            from services.deck_service import migrate_index_card_scales
            source = base["deck_generator"].get("source_folder") or os.path.join(base["root_dir"], "cards", "fronts")
            base["deck_generator"]["card_scales"] = migrate_index_card_scales(scales, source)

    return base


def load_project_from_dir(root_dir: str) -> Dict[str, Any]:
    if not root_dir or not str(root_dir).strip():
        raise ValueError("Root directory path is required.")
    abs_root = os.path.abspath(os.path.expanduser(root_dir.strip()))
    if not os.path.isdir(abs_root):
        raise FileNotFoundError(f"Directory not found: {abs_root}")
    state_path = os.path.join(abs_root, STATE_FILENAME)
    ensure_workspace_subdirs(abs_root)
    if os.path.isfile(state_path):
        with open(state_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        state = normalize_loaded_state(raw, fallback_root=abs_root)
    else:
        state = default_project_state(abs_root)
    atomic_write_json(state_path, state)
    return state


def save_project_state(root_dir: str, state: Dict[str, Any]) -> Dict[str, Any]:
    abs_root = os.path.abspath(os.path.expanduser(root_dir.strip()))
    ensure_workspace_subdirs(abs_root)
    normalized = normalize_loaded_state(state, fallback_root=abs_root)
    normalized["root_dir"] = abs_root
    state_path = os.path.join(abs_root, STATE_FILENAME)
    atomic_write_json(state_path, normalized)
    return normalized


def next_versioned_dir(parent_dir: str, base_name: str) -> str:
    idx = 1
    while True:
        cand = os.path.join(parent_dir, f"{base_name}-{idx}")
        if not os.path.exists(cand):
            return cand
        idx += 1


def check_dir_collision(parent_dir: str, base_name: str) -> Dict[str, Any]:
    target = os.path.join(os.path.abspath(parent_dir), base_name)
    exists = os.path.isdir(target)
    has_files = False
    if exists:
        try:
            with os.scandir(target) as it:
                has_files = any(not e.name.startswith(".") for e in it)
        except OSError:
            has_files = False
    return {
        "target": target,
        "exists": exists,
        "has_files": has_files,
        "collision": exists and has_files,
        "next_version": next_versioned_dir(os.path.abspath(parent_dir), base_name),
    }


def resolve_collision_target(parent_dir: str, base_name: str, collision_mode: str = "version") -> str:
    abs_parent = os.path.abspath(parent_dir)
    os.makedirs(abs_parent, exist_ok=True)
    target = os.path.join(abs_parent, base_name)
    if collision_mode == "overwrite":
        if os.path.isdir(target):
            for entry in os.scandir(target):
                if entry.is_file() or entry.is_symlink():
                    os.unlink(entry.path)
                elif entry.is_dir():
                    shutil.rmtree(entry.path)
        os.makedirs(target, exist_ok=True)
        return target
    if collision_mode == "version":
        has_non_dot = False
        if os.path.isdir(target):
            with os.scandir(target) as it:
                has_non_dot = any(not e.name.startswith(".") for e in it)
        if has_non_dot:
            target = next_versioned_dir(abs_parent, base_name)
        os.makedirs(target, exist_ok=True)
        return target
    os.makedirs(target, exist_ok=True)
    return target


def pick_native_directory(initial_dir: Optional[str] = None) -> Dict[str, Any]:
    """Attempt native OS folder picker via tkinter in a subprocess; gracefully report unsupported if headless."""
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return {"supported": False, "path": None, "reason": "No GUI display detected"}
    script = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "root = tk.Tk()\n"
        "root.withdraw()\n"
        "root.attributes('-topmost', True)\n"
        f"p = filedialog.askdirectory(initialdir={repr(initial_dir or os.path.expanduser('~'))})\n"
        "print(p or '')\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            return {"supported": False, "path": None, "reason": proc.stderr.strip()}
        chosen = proc.stdout.strip()
        return {"supported": True, "path": chosen or None}
    except Exception as exc:
        return {"supported": False, "path": None, "reason": str(exc)}
