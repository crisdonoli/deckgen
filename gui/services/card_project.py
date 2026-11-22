import datetime
import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
import uuid

import httpx

from config import DATA_DIR, WORKSPACES_DIR
from core.asset_paths import frame_url
from core.card_layouts import get_template_layout
from core.frame_resolver import _infer_template_name, build_recipe
from core.workspace import atomic_write_json, load_project_from_dir, save_project_state

CACHE_DIR = os.path.join(DATA_DIR, "cache", "scryfall")
PROJECTS_DIR = WORKSPACES_DIR
USER_AGENT = "DeckGenStudio/2.0 (https://github.com/cridonoso/deckgen)"
_TIMEOUT = 20.0
_MIN_INTERVAL = 0.11
_RATE_LOCK = threading.Lock()
_LAST_SCRYFALL_TS = 0.0
_SCRYFALL_ID_RE = re.compile(r"[0-9a-fA-F-]{36}")
_CARD_URL_RE = re.compile(r"scryfall\.com/(?:card|cards)/([^/]+)/([^/?#]+)")


def _throttle_scryfall() -> None:
    global _LAST_SCRYFALL_TS
    with _RATE_LOCK:
        now = time.monotonic()
        wait = _MIN_INTERVAL - (now - _LAST_SCRYFALL_TS)
        if wait > 0:
            time.sleep(wait)
        _LAST_SCRYFALL_TS = time.monotonic()


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
    _throttle_scryfall()
    with httpx.Client(headers=_headers(json_accept=False), timeout=_TIMEOUT, follow_redirects=True, transport=httpx.HTTPTransport(local_address="0.0.0.0", retries=2)) as client:
        response = client.get(url)
    response.raise_for_status()
    with open(target + ".tmp", "wb") as f:
        f.write(response.content)
    os.replace(target + ".tmp", target)
    return target


def cached(url: str):
    target = os.path.join(CACHE_DIR, cache_name(url))
    return target if os.path.isfile(target) and os.path.getsize(target) > 0 else None


def resolve_card(card=None, url=None, name=None, set_code=None, scryfall_id=None) -> dict:
    if isinstance(card, dict):
        return card
    if scryfall_id:
        if not _SCRYFALL_ID_RE.fullmatch(scryfall_id):
            raise ScryfallError(400, "ID de Scryfall inválido.")
        endpoint = "https://api.scryfall.com/cards/%s" % scryfall_id
    elif url:
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

    _throttle_scryfall()
    try:
        with httpx.Client(headers=_headers(), timeout=_TIMEOUT, follow_redirects=True, transport=httpx.HTTPTransport(local_address="0.0.0.0", retries=2)) as client:
            response = client.get(endpoint)
    except httpx.HTTPError as exc:
        raise ScryfallError(502, "Scryfall no respondió: %s" % exc.__class__.__name__)

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After") or "60"
        raise ScryfallError(429, "Rate limit de Scryfall excedido (Retry-After: %ss)." % retry_after)
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
        return {
            "url": None,
            "local_path": None,
            "transform": (recipe.get("art_layer") or {}).get("transform"),
            "bounds": (recipe.get("art_layer") or {}).get("bounds"),
            "source_original": None,
        }
    try:
        local = download(source)
        url = asset_url(local)
    except httpx.HTTPError:
        local = cached(source)
        url = asset_url(local) if local else None
        if not local:
            warnings.append("art_offline_no_cache")
            warnings.append("art_fetch_failed")
    if local and isinstance(recipe.get("art_layer"), dict):
        recipe["art_layer"]["local_path"] = local
    return {
        "url": url,
        "local_path": local,
        "transform": (recipe.get("art_layer") or {}).get("transform"),
        "bounds": (recipe.get("art_layer") or {}).get("bounds"),
        "source_original": source,
    }


_MASK_BASE_FRAME_IDS = {
    "593cd9c24e530877",
    "27d4e6274a8cea10",
    "022b10c6c4de8967",
    "eef4db0db1ceef43",
    "855a6a84640944a1",
    "ca3f06c86b33ad67",
    "e778beb13913ec0f",
    "cdfa437cbfcd5f23",
}

_M15_NEW_BY_MATERIAL = {
    "white_marble": "395aed1af6531672.png",
    "blue_water": "34a8f7f37be62b9c.png",
    "black_swamp": "1825fd687e4e4cb8.png",
    "red_volcanic": "84dec089a510dfcc.png",
    "green_bark": "bac9acf84e6c4aa5.png",
    "gold_metallic": "ea4d8934f024fb24.png",
    "artifact_steel_modern": "ecd32ddac9e38e46.png",
    "colorless_stone": "bf33044819dd1e81.png",
    "land_neutral": "ea65d710556959f8.png",
    "vehicle_bronze_riveted": "74122ed056da295d.png",
}


def _frame_stack(recipe: dict, warnings: list):
    stack = []
    for layer in recipe.get("layers") or []:
        filename = layer.get("filename")
        if not filename:
            continue
        role = layer.get("asset_role")
        if role in ("mask", "pinline"):
            continue
        lid = str(layer.get("id") or os.path.splitext(os.path.basename(filename))[0])
        orig_path = str(layer.get("original_path") or "")
        if lid == "4d82f3272976dc05" or "cornerCutout" in orig_path:
            continue
        if lid in _MASK_BASE_FRAME_IDS:
            continue
        if lid == "92ebe7cad4167abb" or "margins/blackBorderExtension" in orig_path:
            filename = "m15/new/border.png"
        elif lid == "d3b30c8398f6fae1" or "holoStamps/acorn.png" in orig_path:
            filename = "m15/holoStamps/stamp.png"
        stack.append({
            "z_index": layer.get("z_index"),
            "asset_role": role,
            "id": lid,
            "filename": filename,
            "url": frame_url(filename),
        })
    if not stack:
        warnings.append("no_frame_layers")
    return stack


def _set_symbol(set_code, warnings: list):
    if not set_code:
        return {"url": None, "path": None}
    url = "https://svgs.scryfall.io/sets/%s.svg" % set_code.lower()
    try:
        local = download(url)
    except httpx.HTTPStatusError as exc:
        warnings.append("set_symbol_%s" % exc.response.status_code)
        return {"url": None, "path": None}
    except httpx.HTTPError:
        local = cached(url)
        if not local:
            warnings.append("set_symbol_offline_no_cache")
            return {"url": None, "path": None}
    return {"url": asset_url(local), "path": local}


def build_card_project(card: dict, face_index=None, showcase_style_override=None, db_path=None) -> dict:
    source = dict(card)
    if showcase_style_override:
        source["showcase_style_override"] = showcase_style_override
    resolved = build_recipe(source, db_path=db_path)
    recipes = resolved.get("recipes") or []
    if face_index is not None:
        recipes = [r for r in recipes if r.get("face_index") == face_index]

    warnings = list((resolved.get("meta") or {}).get("notes") or [])
    set_sym = _set_symbol(source.get("set"), warnings)
    faces = []
    for recipe in recipes:
        face_warnings = list(recipe.get("warnings") or [])
        art_info = _face_art(recipe, face_warnings)
        recipe["set_symbol"] = dict(set_sym)
        faces.append({
            "face_index": recipe.get("face_index"),
            "face_ref": recipe.get("face_ref"),
            "template": recipe.get("template"),
            "taxonomy": recipe.get("taxonomy"),
            "frame_stack": _frame_stack(recipe, face_warnings),
            "art_layer": art_info,
            "text_layers": recipe.get("text_layers") or {},
            "set_symbol": dict(set_sym),
            "set_symbol_bounds": recipe.get("set_symbol_bounds"),
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
        "set_symbol": set_sym,
        "recipe": resolved,
        "warnings": warnings,
    }
    save_project_file(project)
    return project


def save_project_file(project: dict) -> str:
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    path = os.path.join(PROJECTS_DIR, "%s.json" % project["project_id"])
    atomic_write_json(path, project)
    return path


def _normalize_loaded_project(project: dict) -> dict:
    if not isinstance(project, dict):
        return project
    proj_set_sym = project.get("set_symbol") or {}
    if not proj_set_sym.get("url") and project.get("set"):
        proj_set_sym = _set_symbol(project.get("set"), [])
        project["set_symbol"] = proj_set_sym

    recipe_faces = (project.get("recipe") or {}).get("recipes") or []
    for idx, face in enumerate(project.get("faces") or []):
        rec = recipe_faces[idx] if idx < len(recipe_faces) else {}
        tax = face.get("taxonomy") or rec.get("taxonomy") or {}
        if isinstance(face.get("frame_stack"), list):
            cleaned_stack = []
            for lyr in face["frame_stack"]:
                role = lyr.get("asset_role")
                if role in ("mask", "pinline"):
                    continue
                fn = lyr.get("filename") or ""
                fid = os.path.splitext(fn)[0] or lyr.get("id") or ""
                if fn == "4d82f3272976dc05.png" or fid == "4d82f3272976dc05":
                    continue
                if fid in _MASK_BASE_FRAME_IDS:
                    mat = tax.get("frame_texture_material") or "white_marble"
                    repl = _M15_NEW_BY_MATERIAL.get(mat, "395aed1af6531672.png")
                    lyr = {**lyr, "id": os.path.splitext(repl)[0], "filename": repl, "url": frame_url(repl)}
                elif fn == "92ebe7cad4167abb.png":
                    lyr = {**lyr, "id": "dd37f7af9151e955", "filename": "dd37f7af9151e955.png", "url": frame_url("dd37f7af9151e955.png")}
                elif fn == "d3b30c8398f6fae1.png":
                    lyr = {**lyr, "id": "b79464e8c6d77c87", "filename": "b79464e8c6d77c87.png", "url": frame_url("b79464e8c6d77c87.png")}
                cleaned_stack.append(lyr)
            face["frame_stack"] = cleaned_stack
        layers = rec.get("layers") or face.get("frame_stack") or []
        inferred_tpl = _infer_template_name(tax, layers)
        cur_tpl = face.get("template")
        if not cur_tpl or (cur_tpl == "ModalShort" and inferred_tpl == "ModalRegular"):
            face["template"] = inferred_tpl
            if rec:
                rec["template"] = inferred_tpl
        tpl_layout = get_template_layout(face.get("template") or "M15Regular")
        if not face.get("set_symbol") or not (face.get("set_symbol") or {}).get("url"):
            face["set_symbol"] = dict(proj_set_sym)
        if rec and not (rec.get("set_symbol") or {}).get("url"):
            rec["set_symbol"] = dict(face["set_symbol"])
        if not face.get("set_symbol_bounds") or cur_tpl == "ModalShort" and face.get("template") == "ModalRegular":
            face["set_symbol_bounds"] = tpl_layout.get("set_symbol_bounds")
            if rec:
                rec["set_symbol_bounds"] = tpl_layout.get("set_symbol_bounds")
        ab = tpl_layout.get("art_bounds")
        if ab and ab.get("width") and ab.get("height") and cur_tpl == "ModalShort" and face.get("template") == "ModalRegular":
            new_ab = {"x": int(ab.get("x", 0)), "y": int(ab.get("y", 0)), "w": int(ab["width"]), "h": int(ab["height"])}
            if isinstance(face.get("art_layer"), dict):
                face["art_layer"]["bounds"] = new_ab
                face["art_layer"]["transform"] = {"x": new_ab["x"], "y": new_ab["y"], "scale": 1.0, "rotation": 0}
            if rec and isinstance(rec.get("art_layer"), dict):
                rec["art_layer"]["bounds"] = new_ab
                rec["art_layer"]["transform"] = {"x": new_ab["x"], "y": new_ab["y"], "scale": 1.0, "rotation": 0}
        tb = tpl_layout.get("text_bounds") or {}
        if tb and isinstance(face.get("text_layers"), dict):
            key_map = {
                "title": "title",
                "mana_cost": "mana",
                "type_line": "type",
                "oracle_text": "rules",
                "flavor_text": "rules",
                "pt": "pt",
            }
            for t_key, b_key in key_map.items():
                entry = face["text_layers"].get(t_key)
                if isinstance(entry, dict) and b_key in tb:
                    if not entry.get("bounds") or (cur_tpl == "ModalShort" and face.get("template") == "ModalRegular"):
                        b_copy = dict(tb[b_key])
                        if "width" in b_copy and "w" not in b_copy:
                            b_copy["w"] = b_copy["width"]
                        if "height" in b_copy and "h" not in b_copy:
                            b_copy["h"] = b_copy["height"]
                        entry["bounds"] = b_copy
                        if rec and isinstance((rec.get("text_layers") or {}).get(t_key), dict):
                            rec["text_layers"][t_key]["bounds"] = dict(b_copy)
    return project


def load_project_file(project_id: str):
    name = os.path.basename(project_id)
    if name != project_id or not project_id:
        return None
    path = os.path.join(PROJECTS_DIR, "%s.json" % project_id)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        project = json.load(f)
    return _normalize_loaded_project(project)


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
