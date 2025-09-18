# keying.py
import hashlib
from typing import Tuple

def canonical_pixel_width(wpt: float, scale: int) -> int:
    # MUST match iOS exactly
    return int(round(wpt * scale))

def compute_key(render_salt: str, token: str, scale: int, wpt: float, fpx: int, latex_utf8: bytes) -> Tuple[str, int]:
    """
    key = sha256(
      RENDER_SALT | token | scale | round(wpt*scale) | fpx | latex
    ).hexdigest()
    Returns (hex_key, pixel_width)
    """
    pw = canonical_pixel_width(wpt, scale)
    prefix = f"{render_salt}|{token}|{scale}|{pw}|{fpx}|".encode("utf-8")
    h = hashlib.sha256()
    h.update(prefix)
    h.update(latex_utf8)
    return h.hexdigest(), pw