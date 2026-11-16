import logging
import os
import sys
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tornado.httpserver
import tornado.httputil
import tornado.ioloop
import tornado.web

from config import PORT, ASSETS_DIR
from handlers.card_builder import CardBuilderArtPrintsHandler, CardBuilderHandler
from handlers.browse_dirs import BrowseDirsHandler
from handlers.clear_cache import ClearCacheHandler
from handlers.convert import ConvertImagesHandler
from handlers.custom_backs import CustomBacksHandler
from handlers.deck import DeckCheckHandler, DeckDuplicateHandler, DeckWatchHandler
from handlers.deck_generator import DeckGeneratorHandler
from handlers.download import DownloadHandler
from handlers.generate import GenerateHandler
from handlers.image_converter import ImageConverterHandler
from handlers.landing import LandingHandler
from handlers.preview import PreviewHandler
from handlers.progress import ProgressHandler
from handlers.card_builder import (
    CardBuilderHandler,
    CardBuilderSearchHandler,
    CardBuilderUploadTxtHandler,
    CardBuilderTemplatesHandler,
    CardBuilderSaveCardHandler,
    CardBuilderExportPdfHandler,
)

def make_app():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return tornado.web.Application(
        [
            (r"/", LandingHandler),
            (r"/card-builder", CardBuilderHandler),
            (r"/api/card-builder/search", CardBuilderSearchHandler),
            (r"/api/card-builder/art-prints", CardBuilderArtPrintsHandler),
            (r"/api/card-builder/upload-txt", CardBuilderUploadTxtHandler),
            (r"/api/card-builder/templates", CardBuilderTemplatesHandler),
            (r"/api/card-builder/save-card", CardBuilderSaveCardHandler),
            (r"/api/card-builder/export-pdf", CardBuilderExportPdfHandler),
            (r"/assets/(.*)", tornado.web.StaticFileHandler, {"path": ASSETS_DIR}),
            (r"/deck-generator", DeckGeneratorHandler),
            (r"/image-converter", ImageConverterHandler),
            (r"/generate", GenerateHandler),
            (r"/download", DownloadHandler),
            (r"/progress", ProgressHandler),
            (r"/preview", PreviewHandler),
            (r"/convert", ConvertImagesHandler),
            (r"/clear-cache", ClearCacheHandler),
            (r"/deck/check", DeckCheckHandler),
            (r"/deck/duplicate", DeckDuplicateHandler),
            (r"/deck/watch", DeckWatchHandler),
            (r"/deck/custom_backs", CustomBacksHandler),
            (r"/browse-dirs", BrowseDirsHandler),
        ],
        static_path=os.path.join(base_dir, "static"),
    )


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = make_app()
    tornado.httputil.set_parse_body_config(
        tornado.httputil.ParseBodyConfig(
            multipart=tornado.httputil.ParseMultipartConfig(max_parts=100000)
        )
    )
    server = tornado.httpserver.HTTPServer(
        app,
        max_body_size=2 * 1024 ** 3,
        max_buffer_size=2 * 1024 ** 3,
    )
    port = PORT
    for offset in range(10):
        try:
            server.listen(port)
            break
        except OSError as e:
            if e.errno == 98 and offset < 9:
                port += 1
                continue
            raise
    url = f"http://127.0.0.1:{port}/"
    print(f"Listening on {url}")
    webbrowser.open(url)
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
