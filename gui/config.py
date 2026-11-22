import os

PORT = 8766
HOST = "127.0.0.1"
DPI = 300
PREVIEW_DPI = 100
CARD_W_MM = 63.5
CARD_H_MM = 88.9
MM_TO_INCH = 25.4
PAPER_SIZES = {
    "a3": (297.0, 420.0),
    "a4": (210.0, 297.0),
    "a4-3": (297.0, 420.0),
}

STANDARD_CARD_W_PX = 750
STANDARD_CARD_H_PX = 1050

MIN_EXPORT_DPI = 300
MAX_EXPORT_DPI = 2400
DEFAULT_EXPORT_DPI = 1200

_GUI_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_GUI_DIR, ".."))
_ROOT_ASSETS = os.path.join(_PROJECT_ROOT, "assets")
_GUI_ASSETS = os.path.join(_GUI_DIR, "assets")

if os.path.isdir(os.path.join(_ROOT_ASSETS, "resources")):
    ASSETS_DIR = _ROOT_ASSETS
elif os.path.isdir(_GUI_ASSETS):
    ASSETS_DIR = _GUI_ASSETS
else:
    ASSETS_DIR = _ROOT_ASSETS

RESOURCES_DIR = os.path.join(ASSETS_DIR, "resources")
ASSETS_DB_PATH = os.path.join(RESOURCES_DIR, "assets.db")
FRAMES_DIR = os.path.join(RESOURCES_DIR, "frames")
SHARED_DIR = os.path.join(RESOURCES_DIR, "_shared")
SCRYFALL_MAP_PATH = os.path.join(ASSETS_DIR, "scryfall-map.json")
TAXONOMY_PATH = os.path.join(ASSETS_DIR, "taxonomy.json")

DEFAULT_FRAME_PROFILE = "M15Regular"

DATA_DIR = os.path.join(_GUI_DIR, "data")
FRAME_LAYOUTS_PATH = os.path.join(DATA_DIR, "frame_layouts.json")
UNIFIED_ART_PATH = os.path.join(DATA_DIR, "unified_art.json")
WORKSPACES_DIR = os.path.join(DATA_DIR, "cache", "projects")

CACHE_ROOT = os.path.join(os.path.expanduser("~"), ".cache", "deckgen")
RENDER_CACHE_DIR = os.path.join(CACHE_ROOT, "render_cache")
PREVIEW_CACHE_DIR = os.path.join(CACHE_ROOT, "preview_cache")
SCRYFALL_CACHE_DIR = os.path.join(CACHE_ROOT, "scryfall_cache")

