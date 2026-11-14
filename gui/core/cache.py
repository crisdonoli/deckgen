import hashlib
import os

from config import CARD_H_MM, CARD_W_MM, PREVIEW_CACHE_DIR


def _first_sheet_hash(pdfs):
    hasher = hashlib.sha256()
    for pdf in pdfs:
        if pdf is None:
            hasher.update(b"__BLANK_BACK__")
            continue
        hasher.update(os.path.basename(pdf).encode())
        with open(pdf, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
    return hasher.hexdigest()


def _preview_cache_key(source_name, face, paper, landscape, card_spacing, pdfs, duplex_flip=True):
    content_hash = _first_sheet_hash(pdfs)
    raw = (
        f"{CARD_W_MM}\x00{CARD_H_MM}\x00{source_name}\x00{face}\x00{paper}\x00{landscape}\x00"
        f"{card_spacing}\x00{duplex_flip}\x00{content_hash}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _preview_cache_path(cache_key):
    return os.path.join(PREVIEW_CACHE_DIR, f"deckgen_preview_{cache_key}.png")
