import hashlib
import os
import urllib.parse

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from config import CACHE_ROOT
from core.art_index import art_index

router = APIRouter(prefix="/api/art")
_IMG_CACHE_DIR = os.path.join(CACHE_ROOT, "img_proxy")


@router.get("/stats")
async def api_art_stats():
    return art_index.stats


@router.get("/lookup")
async def api_art_lookup(name: str = Query(...)):
    matches = art_index.lookup_exact(name)
    return {"name": name, "results": matches, "count": len(matches)}


@router.get("/search")
async def api_art_search(q: str = Query(default=""), limit: int = Query(default=40, ge=1, le=120)):
    results = art_index.search(q, limit=limit)
    return {"query": q, "results": results, "count": len(results)}


@router.get("/scryfall-prints")
async def api_art_scryfall_prints(name: str = Query(...)):
    if not name.strip():
        raise HTTPException(status_code=400, detail="Nombre de carta requerido.")
    prints = await art_index.fetch_scryfall_prints(name.strip())
    return {"name": name, "prints": prints, "count": len(prints)}


@router.get("/proxy")
async def api_art_proxy(url: str = Query(...)):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="URL inválida.")

    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    cache_path = os.path.join(_IMG_CACHE_DIR, key)
    meta_path = cache_path + ".mime"

    if os.path.isfile(cache_path) and os.path.isfile(meta_path):
        with open(meta_path, "r", encoding="utf-8") as mf:
            ctype = mf.read().strip() or "image/jpeg"
        with open(cache_path, "rb") as cf:
            return Response(
                content=cf.read(),
                media_type=ctype,
                headers={"Cache-Control": "public, max-age=86400"},
            )

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8",
                    "Referer": f"{parsed.scheme}://{parsed.netloc}/",
                },
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="No se pudo descargar la imagen.")
        ctype = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        os.makedirs(_IMG_CACHE_DIR, exist_ok=True)
        with open(cache_path, "wb") as cf:
            cf.write(resp.content)
        with open(meta_path, "w", encoding="utf-8") as mf:
            mf.write(ctype)
        return Response(
            content=resp.content,
            media_type=ctype,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error proxy de imagen: {exc}")
