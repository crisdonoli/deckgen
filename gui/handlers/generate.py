import json
import os

import tornado.escape
import tornado.ioloop
import tornado.web

from core.pdf_build import build_pdf
from services.build_sheets import parse_and_build_sheets
from state import _progress_callback, _set_progress


class GenerateHandler(tornado.web.RequestHandler):
    async def post(self):
        _set_progress(0, "starting", False)
        try:
            face = self.get_body_argument("face")
            paper = self.get_body_argument("paper")
            source_files = self.request.files.get("source_files", [])
            export_dir = self.get_body_argument("export_dir", "").strip()
            use_browser_dir = self.get_body_argument("use_browser_dir", "false").lower() == "true"
            if not use_browser_dir and not os.path.isdir(export_dir):
                _set_progress(0, "error: missing export directory", True)
                self.set_status(400)
                self.set_header("Content-Type", "application/json")
                self.write(json.dumps({"error": f"export directory not found: {export_dir}"}))
                return

            loop = tornado.ioloop.IOLoop.current()
            sheets, error = await loop.run_in_executor(
                None, parse_and_build_sheets, self, False, _progress_callback, source_files or None
            )
            if error:
                _set_progress(0, f"error: {error}", True)
                self.set_status(400)
                self.set_header("Content-Type", "application/json")
                self.write(json.dumps({"error": error}))
                return

            _set_progress(95, "saving PDF", False)
            if use_browser_dir:
                dest_dir = os.path.join("/tmp", "deckgen_exports")
                os.makedirs(dest_dir, exist_ok=True)
            else:
                dest_dir = export_dir

            def save_pdf():
                built_path = build_pdf(sheets, dest_dir)
                pdf_name = f"deckgen_{face}_{paper}.pdf"
                final_path = os.path.join(dest_dir, pdf_name)
                os.rename(built_path, final_path)
                return final_path

            pdf_path = await loop.run_in_executor(None, save_pdf)
            _set_progress(100, "done", True)
            download_url = f"/download?path={tornado.escape.url_escape(pdf_path)}"
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"path": pdf_path, "download_url": download_url}))
        except Exception as exc:
            _set_progress(0, f"error: {exc}", True)
            raise
