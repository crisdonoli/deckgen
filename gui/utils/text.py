import os
import re


def normalize_card_text(text):
    if not text:
        return ""
    t = os.path.splitext(text)[0].lower()
    t = re.sub(r"\(copia \d+\)", "", t)
    t = re.sub(r"\([a-zA-Z0-9_\-]{20,}\)", "", t)
    t = re.sub(r"\[.*?\]|\{.*?\}", "", t)
    return re.sub(r"[^a-z0-9]", "", t)
