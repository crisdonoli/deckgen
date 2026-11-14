import os

import tornado.web


class DownloadHandler(tornado.web.RequestHandler):
    def get(self):
        path = self.get_argument("path", "")
        if not path or not os.path.isfile(path):
            self.set_status(404)
            self.set_header("Content-Type", "text/plain; charset=utf-8")
            self.write("file not found")
            return
        self.set_header("Content-Type", "application/pdf")
        self.set_header(
            "Content-Disposition",
            f'attachment; filename="{os.path.basename(path)}"',
        )
        with open(path, "rb") as f:
            self.write(f.read())
