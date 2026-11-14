import json

import tornado.web

from domain.custom_backs import (
    assign_custom_backs,
    auto_detect_custom_backs,
    inspect_custom_backs,
    remove_custom_backs,
)


class CustomBacksHandler(tornado.web.RequestHandler):
    def get(self):
        export_dir = self.get_argument("export_dir", "").strip()
        res = inspect_custom_backs(export_dir)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(res))

    def post(self):
        action = self.get_body_argument("action", "inspect").strip()
        export_dir = self.get_body_argument("export_dir", "").strip()

        if action == "inspect":
            res = inspect_custom_backs(export_dir)
        elif action == "assign":
            card_files_raw = self.get_body_argument("card_filenames", "[]")
            try:
                card_files = json.loads(card_files_raw)
            except Exception:
                card_files = [card_files_raw] if card_files_raw else []

            back_file_body = None
            original_filename = None
            if "back_pdf" in self.request.files:
                finfo = self.request.files["back_pdf"][0]
                back_file_body = finfo["body"]
                original_filename = finfo["filename"]

            back_filename = self.get_body_argument("back_filename", "").strip()

            res = assign_custom_backs(
                export_dir=export_dir,
                card_filenames=card_files,
                back_file_body=back_file_body,
                back_filename=back_filename or None,
                original_filename=original_filename,
            )
        elif action == "remove":
            card_files_raw = self.get_body_argument("card_filenames", "[]")
            try:
                card_files = json.loads(card_files_raw)
            except Exception:
                card_files = [card_files_raw] if card_files_raw else []
            res = remove_custom_backs(export_dir, card_files)
        elif action == "auto_detect":
            res = auto_detect_custom_backs(export_dir)
        else:
            res = {"error": f"Unknown action: '{action}'"}

        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(res))
