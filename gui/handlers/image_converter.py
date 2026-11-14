import string
from pathlib import Path

import tornado.web

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
NAVBAR = (TEMPLATES / "components" / "navbar.html").read_text(encoding="utf-8")
PAGE_TEMPLATE = string.Template(
    (TEMPLATES / "image_converter.html").read_text(encoding="utf-8")
)


class ImageConverterHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(PAGE_TEMPLATE.safe_substitute(navbar=NAVBAR))
