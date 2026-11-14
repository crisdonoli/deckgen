import hashlib
import json
import os

import tornado.web

from domain.deck import duplicate_deck_cards, inspect_deck_file
from utils.conversions import parse_bool


class DeckCheckHandler(tornado.web.RequestHandler):
    def post(self):
        export_dir = self.get_body_argument("export_dir", "").strip()
        deck_path = self.get_body_argument("deck_path", self.get_body_argument("xml_path", "")).strip()
        file_content = None
        if "deck_file" in self.request.files:
            file_content = self.request.files["deck_file"][0]["body"]
        elif "xml_file" in self.request.files:
            file_content = self.request.files["xml_file"][0]["body"]
        res = inspect_deck_file(export_dir, deck_path or None, file_content)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(res))


def _dir_signature(export_dir):
    if not export_dir or not os.path.isdir(export_dir):
        return None
    hasher = hashlib.sha256()
    subdirs = [export_dir, os.path.join(export_dir, "pdfs"), os.path.join(export_dir, "backs")]
    for sub in subdirs:
        if not os.path.isdir(sub):
            continue
        entries = []
        try:
            for entry in os.scandir(sub):
                if entry.is_file() and (entry.name.lower().endswith(".pdf") or entry.name == "custom_backs.json"):
                    st = entry.stat()
                    entries.append((entry.name, st.st_mtime_ns, st.st_size))
        except OSError:
            continue
        entries.sort()
        hasher.update(sub.encode())
        for name, mtime_ns, size in entries:
            hasher.update(f"{name}\0{mtime_ns}\0{size}\n".encode())
    return hasher.hexdigest()


class DeckWatchHandler(tornado.web.RequestHandler):
    def get(self):
        export_dir = self.get_argument("export_dir", "").strip()
        sig = _dir_signature(export_dir)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"valid": sig is not None, "signature": sig}))


class DeckDuplicateHandler(tornado.web.RequestHandler):
    def post(self):
        export_dir = self.get_body_argument("export_dir", "").strip()
        target_file = self.get_body_argument("target_file", "").strip()
        copies_to_add = int(self.get_body_argument("copies_to_add", "1"))
        auto_deck = parse_bool(self.get_body_argument("auto_deck", self.get_body_argument("auto_xml", "false")))
        deck_path = self.get_body_argument("deck_path", self.get_body_argument("xml_path", "")).strip()
        file_content = None
        if "deck_file" in self.request.files:
            file_content = self.request.files["deck_file"][0]["body"]
        elif "xml_file" in self.request.files:
            file_content = self.request.files["xml_file"][0]["body"]
        res = duplicate_deck_cards(
            export_dir=export_dir,
            target_file=target_file or None,
            count=copies_to_add,
            auto_deck=auto_deck,
            deck_path=deck_path or None,
            file_content=file_content,
        )
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(res))


def _dir_signature(export_dir):
    if not export_dir or not os.path.isdir(export_dir):
        return None
    hasher = hashlib.sha256()
    subdirs = [export_dir, os.path.join(export_dir, "pdfs"), os.path.join(export_dir, "backs")]
    for sub in subdirs:
        if not os.path.isdir(sub):
            continue
        entries = []
        try:
            for entry in os.scandir(sub):
                if entry.is_file() and (entry.name.lower().endswith(".pdf") or entry.name == "custom_backs.json"):
                    st = entry.stat()
                    entries.append((entry.name, st.st_mtime_ns, st.st_size))
        except OSError:
            continue
        entries.sort()
        hasher.update(sub.encode())
        for name, mtime_ns, size in entries:
            hasher.update(f"{name}\0{mtime_ns}\0{size}\n".encode())
    return hasher.hexdigest()


class DeckWatchHandler(tornado.web.RequestHandler):
    def get(self):
        export_dir = self.get_argument("export_dir", "").strip()
        sig = _dir_signature(export_dir)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"valid": sig is not None, "signature": sig}))
