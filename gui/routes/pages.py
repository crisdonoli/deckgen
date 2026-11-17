import os
from string import Template
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()
_GUI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATES_DIR = os.path.join(_GUI_DIR, "templates")


def _render_page(template_name: str, active_nav: str) -> HTMLResponse:
    nav_path = os.path.join(_TEMPLATES_DIR, "components", "navbar.html")
    tpl_path = os.path.join(_TEMPLATES_DIR, template_name)
    with open(nav_path, "r", encoding="utf-8") as f:
        navbar = f.read()
    with open(tpl_path, "r", encoding="utf-8") as f:
        tpl = Template(f.read())
    html = tpl.safe_substitute(navbar=navbar, active_nav=active_nav)
    return HTMLResponse(content=html)


@router.get("/", response_class=HTMLResponse)
async def landing_page():
    return _render_page("landing.html", "home")


@router.get("/card-builder", response_class=HTMLResponse)
async def card_builder_page():
    return _render_page("card_builder.html", "card-builder")


@router.get("/deck-generator", response_class=HTMLResponse)
async def deck_generator_page():
    return _render_page("deck_generator.html", "deck-generator")


@router.get("/tutorial", response_class=HTMLResponse)
async def tutorial_page():
    return _render_page("tutorial.html", "tutorial")
