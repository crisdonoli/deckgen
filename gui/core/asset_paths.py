"""Single source of truth for asset filesystem paths and frontend URLs."""
import os
from pathlib import Path
from typing import Optional

from config import (
    ASSETS_DB_PATH,
    ASSETS_DIR,
    DATA_DIR,
    DEFAULT_FRAME_PROFILE,
    FRAME_LAYOUTS_PATH,
    FRAMES_DIR,
    PREVIEW_CACHE_DIR,
    RENDER_CACHE_DIR,
    RESOURCES_DIR,
    SCRYFALL_CACHE_DIR,
    SCRYFALL_MAP_PATH,
    SHARED_DIR,
    TAXONOMY_PATH,
    UNIFIED_ART_PATH,
    WORKSPACES_DIR,
)

import urllib.parse

FRAMES_URL_PREFIX = "/assets/resources/frames/"
SHARED_URL_PREFIX = "/assets/resources/_shared/"


def _safe_rel(filename: str) -> str:
    clean = str(filename or "").replace("\\", "/").lstrip("/")
    parts = [p for p in clean.split("/") if p and p not in (".", "..")]
    return "/".join(parts)


def frame_file_path(filename: str) -> Path:
    rel = _safe_rel(filename)
    direct = Path(FRAMES_DIR) / rel
    if direct.is_file() or "/" in rel:
        return direct
    return Path(FRAMES_DIR) / os.path.basename(rel)


def shared_file_path(filename: str) -> Path:
    return Path(SHARED_DIR) / _safe_rel(filename)


def frame_url(filename: str) -> str:
    rel = _safe_rel(filename)
    return FRAMES_URL_PREFIX + urllib.parse.quote(rel, safe="/")


def shared_url(filename: str) -> str:
    rel = _safe_rel(filename)
    return SHARED_URL_PREFIX + urllib.parse.quote(rel, safe="/")


def find_resource_file(filename: str) -> Optional[Path]:
    if not filename:
        return None
    rel = _safe_rel(filename)
    for base in (FRAMES_DIR, SHARED_DIR):
        candidate = Path(base) / rel
        if candidate.is_file():
            return candidate
        base_cand = Path(base) / os.path.basename(rel)
        if base_cand.is_file():
            return base_cand
    return None


__all__ = [
    "ASSETS_DB_PATH",
    "ASSETS_DIR",
    "DATA_DIR",
    "DEFAULT_FRAME_PROFILE",
    "FRAME_LAYOUTS_PATH",
    "FRAMES_DIR",
    "FRAMES_URL_PREFIX",
    "PREVIEW_CACHE_DIR",
    "RENDER_CACHE_DIR",
    "RESOURCES_DIR",
    "SCRYFALL_CACHE_DIR",
    "SCRYFALL_MAP_PATH",
    "SHARED_DIR",
    "SHARED_URL_PREFIX",
    "TAXONOMY_PATH",
    "UNIFIED_ART_PATH",
    "WORKSPACES_DIR",
    "find_resource_file",
    "frame_file_path",
    "frame_url",
    "shared_file_path",
    "shared_url",
]
