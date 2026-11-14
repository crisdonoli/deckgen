import os

PORT = 8766
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
PREVIEW_CACHE_DIR = "/tmp/opencode"
STANDARD_CARD_W_PX = 750
STANDARD_CARD_H_PX = 1050

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_ASSETS = os.path.abspath(os.path.join(_BASE_DIR, "..", "assets"))
_GUI_ASSETS = os.path.join(_BASE_DIR, "assets")

# Priorizar el assets/ de la raíz que contiene keyrune-master y mana-master
ASSETS_DIR = _ROOT_ASSETS if os.path.isdir(os.path.join(_ROOT_ASSETS, "mana-master")) else _GUI_ASSETS
