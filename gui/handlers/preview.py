import io
import logging

import tornado.web

from services.build_sheets import parse_and_build_sheets


class PreviewHandler(tornado.web.RequestHandler):
    def post(self):
        meta = {}
        sheets, error = parse_and_build_sheets(self, preview=True, preview_meta=meta)
        if error:
            logging.error("preview error: %s", error)
            self.set_status(400)
            self.set_header("Content-Type", "text/plain; charset=utf-8")
            self.write(error)
            return

        buf = io.BytesIO()
        sheets[0].save(buf, format="PNG")
        buf.seek(0)
        self.set_header("Content-Type", "image/png")
        self.set_header("X-Total-Pages", str(meta.get("total_pages", 1)))
        self.set_header("X-Current-Page", str(meta.get("page", 0)))
        self.write(buf.read())
