"""Qt image helpers shared by the clipboard / screenshot backends and the UI.

This lives in ``core`` rather than ``ui`` because the platform backends need it
while core modules must not import from the ui package. QImage/QBuffer encode
operations do not require a QApplication instance, so importing this module is
safe in headless contexts.
"""

from __future__ import annotations

import io

from PySide6.QtCore import QBuffer, QByteArray
from PySide6.QtGui import QImage

# Channel layout both encoders below can handle without guesswork.
_CANONICAL_FORMAT = QImage.Format.Format_RGBA8888


def _pil_encode_qimage(image: QImage) -> bytes | None:
    """Encode via Pillow, reading QImage's raw bits.

    Qt's PNG encoder occasionally refuses exotic source formats; Pillow is more
    forgiving. Rows are padded to ``bytesPerLine`` (4-byte alignment), so the
    buffer cannot be handed to Pillow as-is when padding is present.
    """
    try:
        from PIL import Image

        img = image
        if img.format() != _CANONICAL_FORMAT:
            img = img.convertToFormat(_CANONICAL_FORMAT)
        w, h = img.width(), img.height()
        bpl = img.bytesPerLine()
        bits = img.bits()
        # PySide6 returns a memoryview already sized to the full buffer, while
        # PyQt/older bindings expose a voidptr that must be sized explicitly.
        # Calling setsize unconditionally breaks on PySide6 (AttributeError),
        # which silently disabled this fallback path in the original code.
        if hasattr(bits, "setsize"):
            bits.setsize(bpl * h)
        raw = bytes(bits)
        if bpl != w * 4:
            raw = b"".join(raw[y * bpl : y * bpl + w * 4] for y in range(h))
        if len(raw) < w * h * 4:
            return None
        out = io.BytesIO()
        Image.frombytes("RGBA", (w, h), raw).save(out, format="PNG")
        return out.getvalue()
    except Exception:  # noqa: BLE001 — caller decides how to report failure
        return None


def qimage_to_png_bytes(image: QImage | None) -> bytes | None:
    """Encode a QImage as PNG bytes.

    Qt's encoder is tried first; Pillow is the fallback. Returns ``None`` when
    both fail (or the image is null) so callers can fall back to another path
    instead of raising deep inside the backend.
    """
    if image is None or image.isNull():
        return None

    qba = QByteArray()
    qbuf = QBuffer(qba)
    qbuf.open(QBuffer.OpenModeFlag.WriteOnly)
    try:
        if image.save(qbuf, "PNG"):
            return bytes(qba)
    finally:
        qbuf.close()

    return _pil_encode_qimage(image)
