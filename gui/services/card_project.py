import datetime
import hashlib
import json
import os
import re
import urllib.parse
import uuid

import httpx

from config import DATA_DIR
from core.frame_resolver import build_recipe
from core.workspace import atomic_write_json, load_project_from_dir, save_project_state

CACHE_DIR = os.path.join(DATA_DIR, "cache", "scryfall")
PROJECTS_DIR = os.path.join(DATA_DIR, "cache", "projects")
USER_AGENT = "DeckGen/2.0"
_TIMEOUT = 20.0
_CARD_URL_RE = re.compile(r"scryfall\.com/(?:card|cards)/([^/]+)/([^/?#]+)")


class ScryfallError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _headers(json_accept: bool = True) -> dict:
    accept = "application/json" if json_accept else "*/*"
    return {"User-Agent": USER_AGENT, "Accept": accept}


def _url_ext(url: str) -> str:
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    return ext if ext in (".png", ".jpg", ".jpeg", ".svg", ".webp") else ".bin"


def cache_name(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest() + _url_ext(url)


def cache_path_for_key(key: str) -> str:
    name = os.path.basename(key)
    return os.path.join(CACHE_DIR, name) if name == key else ""


def asset_url(path: str) -> str:
    return "/api/card-builder/asset/" + os.path.basename(path)


def download(url: str) -> str:
    target = os.path.join(CACHE_DIR, cache_name(url))
    if os.path.isfile(target) and os.path.getsize(target) > 0:
        return target
    os.makedirs(CACHE_DIR, exist_ok=True)
    with httpx.Client(headers=_headers(json_accept=False), timeout=_TIMEOUT, follow_redirects=True) as client:
        response = client.get(url)
    response.raise_for_status()
    with open(target + ".tmp", "wb") as f:
        f.write(response.content)
    os.replace(target + ".tmp", target)
    return target


def cached(url: str):
    target = os.path.join(CACHE_DIR, cache_name(url))
    return target if os.path.isfile(target) and os.path.getsize(target) > 0 else None


def resolve_card(card=None, url=None, name=None, set_code=None) -> dict:
    if isinstance(card, dict):
        return card
    if url:
        match = _CARD_URL_RE.search(url)
        if not match:
            raise ScryfallError(400, "URL de Scryfall inválida.")
        endpoint = "https://api.scryfall.com/cards/%s/%s" % (match.group(1), match.group(2))
    elif name:
        query = {"fuzzy": name}
        if set_code:
            query["set"] = set_code
        endpoint = "https://api.scryfall.com/cards/named?" + urllib.parse.urlencode(query)
    else:
        raise ScryfallError(400, "Envía 'card', 'url' o 'name'.")

    try:
        with httpx.Client(headers=_headers(), timeout=_TIMEOUT, follow_redirects=True) as client:
            response = client.get(endpoint)
    except httpx.HTTPError as exc:
        raise ScryfallError(502, "Scryfall no respondió: %s" % exc.__class__.__name__)

    if response.status_code == 404:
        raise ScryfallError(404, "Carta no encontrada en Scryfall.")
    if response.status_code >= 400:
        raise ScryfallError(502, "Scryfall devolvió %s." % response.status_code)
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("object") == "error":
        raise ScryfallError(404, "Carta no encontrada en Scryfall.")
    return payload


def _face_art(recipe: dict, warnings: list):
    source = (recipe.get("art_layer") or {}).get("source")
    if not source:
        warnings.append("art_crop_missing")
        return {"url": None, "transform": (recipe.get("art_layer") or {}).get("transform"), "bounds": (recipe.get("art_layer") or {}).get("bounds"), "source_original": None}
    try:
        local = download(source)
        url = asset_url(local)
    except httpx.HTTPError:
        local = cached(source)
        url = asset_url(local) if local else None
        if not local:
            warnings.append("art_offline_no_cache")
            warnings.append("art_fetch_failed")
    return {
        "url": url,
        "transform": (recipe.get("art_layer") or {}).get("transform"),
        "bounds": (recipe.get("art_layer") or {}).get("bounds"),
        "source_original": source,
    }


def _frame_stack(recipe: dict, warnings: list):
    stack = []
    for layer in recipe.get("layers") or []:
        filename = layer.get("filename")
        if not filename:
            continue
        stack.append({
            "z_index": layer.get("z_index"),
            "asset_role": layer.get("asset_role"),
            "id": layer.get("id"),
            "filename": filename,
            "url": "/assets/resources/frames/" + filename,
        })
    if not stack:
        warnings.append("no_frame_layers")
    return stack


def _set_symbol(set_code, warnings: list):
    if not set_code:
        return {"url": None}
    url = "https://svgs.scryfall.io/sets/%s.svg" % set_code.lower()
    try:
        local = download(url)
    except httpx.HTTPStatusError as exc:
        warnings.append("set_symbol_%s" % exc.response.status_code)
        return {"url": None}
    except httpx.HTTPError:
        local = cached(url)
        if not local:
            warnings.append("set_symbol_offline_no_cache")
            return {"url": None}
    return {"url": asset_url(local)}


def build_card_project(card: dict, face_index=None, showcase_style_override=None, db_path=None) -> dict:
    source = dict(card)
    if showcase_style_override:
        source["showcase_style_override"] = showcase_style_override
    resolved = build_recipe(source, db_path=db_path)
    recipes = resolved.get("recipes") or []
    if face_index is not None:
        recipes = [r for r in recipes if r.get("face_index") == face_index]

    warnings = list((resolved.get("meta") or {}).get("notes") or [])
    faces = []
    for recipe in recipes:
        face_warnings = list(recipe.get("warnings") or [])
        faces.append({
            "face_index": recipe.get("face_index"),
            "face_ref": recipe.get("face_ref"),
            "taxonomy": recipe.get("taxonomy"),
            "frame_stack": _frame_stack(recipe, face_warnings),
            "art_layer": _face_art(recipe, face_warnings),
            "text_layers": recipe.get("text_layers") or {},
            "warnings": face_warnings,
        })

    project = {
        "project_id": uuid.uuid4().hex,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "name": source.get("name"),
        "set": source.get("set"),
        "collector_number": source.get("collector_number"),
        "canvas": dict((resolved.get("meta") or {}).get("canvas") or {"width": 1500, "height": 2100}),
        "faces": faces,
        "set_symbol": _set_symbol(source.get("set"), warnings),
        "warnings": warnings,
    }
    save_project_file(project)
    return project


def save_project_file(project: dict) -> str:
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    path = os.path.join(PROJECTS_DIR, "%s.json" % project["project_id"])
    atomic_write_json(path, project)
    return path


def load_project_file(project_id: str):
    name = os.path.basename(project_id)
    if name != project_id or not project_id:
        return None
    path = os.path.join(PROJECTS_DIR, "%s.json" % project_id)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def register_card_project(root_dir: str, project: dict) -> dict:
    state = load_project_from_dir(root_dir)
    entry = {
        "id": project["project_id"],
        "project_id": project["project_id"],
        "name": project.get("name"),
        "set": project.get("set"),
        "collector_number": project.get("collector_number"),
        "face_indexes": [f.get("face_index") for f in project.get("faces") or []],
    }
    cards = state["card_builder"].setdefault("cards", [])
    cards = [c for c in cards if not (isinstance(c, dict) and c.get("project_id") == project["project_id"])]
    cards.append(entry)
    state["card_builder"]["cards"] = cards
    save_project_state(root_dir, state)
    return entry
