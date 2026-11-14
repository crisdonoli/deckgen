import json
import os

import tornado.web

from core.pdf_build import image_to_standard_pdf


class ConvertImagesHandler(tornado.web.RequestHandler):
    def post(self):
        images = self.request.files.get("images", [])
        export_dir = self.get_body_argument("export_dir", "").strip()
        if not os.path.isdir(export_dir):
            self.set_status(400)
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"error": f"export directory not found: {export_dir}"}))
            return
        pdfs_dir = os.path.join(export_dir, "pdfs")
        os.makedirs(pdfs_dir, exist_ok=True)
        for idx, file_info in enumerate(images):
            stem = os.path.splitext(os.path.basename(file_info["filename"]))[0]
            name = stem or f"image_{idx:03d}"
            image_to_standard_pdf(file_info["body"], os.path.join(pdfs_dir, f"{name}.pdf"))
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"path": pdfs_dir, "count": len(images)}))
