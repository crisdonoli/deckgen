import json
import os

import tornado.web

from config import PREVIEW_CACHE_DIR


class ClearCacheHandler(tornado.web.RequestHandler):
    def post(self):
        cleared_count = 0
        if os.path.exists(PREVIEW_CACHE_DIR):
            for f in os.listdir(PREVIEW_CACHE_DIR):
                if f.startswith("deckgen_preview_"):
                    try:
                        os.remove(os.path.join(PREVIEW_CACHE_DIR, f))
                        cleared_count += 1
                    except OSError:
                        pass
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"status": "ok", "cleared": cleared_count}))
