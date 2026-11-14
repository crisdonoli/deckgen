import string
from pathlib import Path

import tornado.escape
import tornado.web

from utils.conversions import parse_bool

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
NAVBAR = (TEMPLATES / "components" / "navbar.html").read_text(encoding="utf-8")
FORM_TEMPLATE = string.Template(
    (TEMPLATES / "deck_generator.html").read_text(encoding="utf-8")
)


class DeckGeneratorHandler(tornado.web.RequestHandler):
    def get(self):
        defaults = {
            "navbar": NAVBAR,
            "export_dir": self.get_argument("export_dir", ""),
            "face": self.get_argument("face", "fronts"),
            "paper": self.get_argument("paper", "a3"),
            "landscape": self.get_argument("landscape", "false"),
            "card_spacing": self.get_argument("card_spacing", "0"),
            "cut": self.get_argument("cut", "none"),
            "color": self.get_argument("color", "#000000"),
            "thickness": self.get_argument("thickness", "0.5"),
            "mark_len": self.get_argument("mark_len", "5"),
            "duplex_flip": self.get_argument("duplex_flip", "true"),
            "error": "",
        }
        error = self.get_argument("error", "")
        if error:
            defaults["error"] = f'<p class="error">{tornado.escape.xhtml_escape(error)}</p>'
        defaults["face_fronts_selected"] = "selected" if defaults["face"] == "fronts" else ""
        defaults["face_backs_selected"] = "selected" if defaults["face"] == "backs" else ""
        defaults["paper_a3_selected"] = "selected" if defaults["paper"] == "a3" else ""
        defaults["paper_a4_selected"] = "selected" if defaults["paper"] == "a4" else ""
        defaults["paper_a4_3_selected"] = "selected" if defaults["paper"] == "a4-3" else ""
        defaults["landscape_checked"] = "checked" if parse_bool(defaults["landscape"]) else ""
        defaults["duplex_flip_checked"] = "checked" if parse_bool(defaults["duplex_flip"]) else ""
        defaults["cut_none_selected"] = "selected" if defaults["cut"] == "none" else ""
        defaults["cut_full_selected"] = "selected" if defaults["cut"] == "full" else ""
        defaults["cut_corners_selected"] = "selected" if defaults["cut"] == "corners" else ""
        self.write(FORM_TEMPLATE.safe_substitute(defaults))
