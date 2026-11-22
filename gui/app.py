import logging
import os
import sys

_GUI_DIR = os.path.dirname(os.path.abspath(__file__))
if _GUI_DIR not in sys.path:
    sys.path.insert(0, _GUI_DIR)

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from config import ASSETS_DIR
from core.art_index import art_index
from routes import art, card_builder, deck_generator, pages, workspace


def create_app() -> FastAPI:
    app = FastAPI(title="DeckGen Studio", version="2.0.0")

    static_dir = os.path.join(_GUI_DIR, "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    if os.path.isdir(ASSETS_DIR):
        app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
    else:
        logging.warning("ASSETS_DIR does not exist, /assets not mounted: %s", ASSETS_DIR)

    app.include_router(pages.router)
    app.include_router(workspace.router)
    app.include_router(art.router)
    app.include_router(card_builder.router)
    app.include_router(deck_generator.router)

    @app.on_event("startup")
    async def _warm_art_index():
        art_index.ensure_loaded()

    @app.middleware("http")
    async def _no_cache_static(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/") or request.url.path in ("/", "/card-builder", "/deck-generator", "/tutorial"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    return app


app = create_app()
