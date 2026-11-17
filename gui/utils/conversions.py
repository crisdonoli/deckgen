from config import MM_TO_INCH


def mm_to_px(mm: float, dpi: int) -> int:
    return int(round(mm * dpi / MM_TO_INCH))


def pt_to_px(pt_val: float, dpi: int) -> int:
    return max(1, int(round(pt_val * dpi / 72.0)))


def parse_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("true", "1", "on", "yes")


def parse_hex(color: str, fallback: tuple = (255, 0, 0)) -> tuple:
    raw = (color or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(c * 2 for c in raw)
    if len(raw) != 6:
        return fallback
    try:
        return tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback
