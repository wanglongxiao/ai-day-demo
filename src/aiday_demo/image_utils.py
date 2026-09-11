"""Portrait image normalization for the asset library.

The Private Virtual Portrait Library rejects images whose aspect ratio
(width/height) is outside (0.4, 2.5) or whose side length is outside
(300, 6000) px. We pad (letterbox) and resize to keep the full portrait while
guaranteeing the constraints, so user uploads never fail CreateAsset.
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps

# Stay comfortably inside the documented open interval (0.4, 2.5).
MIN_RATIO = 0.5
MAX_RATIO = 2.0
MIN_SIDE = 320
MAX_SIDE = 5800
PAD_COLOR = (0, 0, 0)


def normalize_portrait(data: bytes) -> tuple[bytes, str]:
    """Return (jpeg_bytes, ".jpg") normalized to satisfy asset constraints.

    Idempotent for already-valid images (only re-encodes to JPEG).
    """
    img = Image.open(io.BytesIO(data))
    # Honor EXIF orientation, then drop alpha for JPEG output.
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB",):
        img = img.convert("RGB")

    w, h = img.size

    # 1) Pad to bring aspect ratio into [MIN_RATIO, MAX_RATIO].
    ratio = w / h
    if ratio > MAX_RATIO:
        # too wide -> add top/bottom padding
        new_h = int(round(w / MAX_RATIO))
        pad = new_h - h
        img = ImageOps.expand(
            img, border=(0, pad // 2, 0, pad - pad // 2), fill=PAD_COLOR
        )
    elif ratio < MIN_RATIO:
        # too tall -> add left/right padding
        new_w = int(round(h * MIN_RATIO))
        pad = new_w - w
        img = ImageOps.expand(
            img, border=(pad // 2, 0, pad - pad // 2, 0), fill=PAD_COLOR
        )

    w, h = img.size

    # 2) Clamp side lengths into [MIN_SIDE, MAX_SIDE] (preserve ratio).
    scale = 1.0
    longest, shortest = max(w, h), min(w, h)
    if longest > MAX_SIDE:
        scale = MAX_SIDE / longest
    elif shortest < MIN_SIDE:
        scale = MIN_SIDE / shortest
    if scale != 1.0:
        img = img.resize(
            (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
            Image.LANCZOS,
        )

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue(), ".jpg"
