import json
import os

import tornado.web


class BrowseDirsHandler(tornado.web.RequestHandler):
    def _default_dir(self):
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        return project_root if os.path.isdir(project_root) else os.path.expanduser("~")

    def get(self):
        req_path = self.get_argument("path", "").strip()
        if req_path and os.path.isdir(req_path):
            current = os.path.abspath(req_path)
        elif req_path and os.path.isdir(os.path.dirname(req_path)):
            current = os.path.abspath(os.path.dirname(req_path))
        else:
            current = self._default_dir()

        dirs = []
        try:
            for entry in os.scandir(current):
                if entry.is_dir() and not entry.name.startswith("."):
                    dirs.append(entry.name)
            dirs.sort(key=str.lower)
        except OSError as exc:
            self.set_status(400)
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"error": str(exc)}))
            return

        parent = os.path.dirname(current)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({
            "current": current,
            "parent": parent if parent != current else None,
            "dirs": dirs,
        }))

    def post(self):
        current = self.get_body_argument("current", "").strip()
        folder_name = self.get_body_argument("folder_name", "").strip()
        if not current or not os.path.isdir(current):
            self.set_status(400)
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"error": "Invalid current directory."}))
            return
        if not folder_name or "/" in folder_name or "\\" in folder_name or folder_name in (".", ".."):
            self.set_status(400)
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"error": "Invalid folder name."}))
            return

        new_dir = os.path.join(os.path.abspath(current), folder_name)
        try:
            os.makedirs(new_dir, exist_ok=True)
        except OSError as exc:
            self.set_status(400)
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"error": str(exc)}))
            return

        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"status": "ok", "created": new_dir}))
