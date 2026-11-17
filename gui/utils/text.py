import re
import unicodedata


def normalize_card_name(name: str) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    # Remove variant suffixes like "(Variant)", "(Showcase)", etc.
    s = re.sub(r"\s*\([^)]*\)\s*", " ", s)
    # Use front face if MDFC/split "//"
    if "//" in s:
        s = s.split("//", 1)[0]
    s = re.sub(r"[^a-zA-Z0-9\s]", "", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def safe_card_filename(name: str) -> str:
    clean = re.sub(r"[^\w\s\-]", "", name or "card").strip()
    return re.sub(r"[\s]+", "_", clean).lower() or "card"
