"""Read image bytes from the Windows clipboard via Qt."""

from __future__ import annotations

import io

from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication

from app.core.clipboard_image import ClipboardImageError


class ClipboardImageService:
    """Clipboard image reader for Windows (Qt clipboard)."""

    def available(self) -> bool:
        return QApplication.instance() is not None

    def list_types(self) -> list[str]:
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return []
        md = clipboard.mimeData()
        if md is None:
            return []
        return list(md.formats())

    def read_png(self) -> bytes:
        clipboard = QApplication.clipboard()
        if clipboard is None:
            raise ClipboardImageError("Clipboard is not available")

        md = clipboard.mimeData()
        if md is None:
            raise ClipboardImageError("Clipboard has no data")

        # 1) QImage / QPixmap
        if md.hasImage():
            img = md.imageData()
            if isinstance(img, QImage) and not img.isNull():
                return self._qimage_to_png(img)
            if isinstance(img, QPixmap) and not img.isNull():
                return self._qimage_to_png(img.toImage())

        # 2) Raw image/* mime payloads
        for fmt in (
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/webp",
            "image/bmp",
            "image/gif",
            "application/x-qt-image",
        ):
            if md.hasFormat(fmt):
                raw = bytes(md.data(fmt))
                if raw:
                    try:
                        return self._to_png(raw)
                    except ClipboardImageError:
                        qimg = QImage.fromData(raw)
                        if not qimg.isNull():
                            return self._qimage_to_png(qimg)

        raise ClipboardImageError("Clipboard has no image data")

    @staticmethod
    def _qimage_to_png(image: QImage) -> bytes:
        if image.isNull():
            raise ClipboardImageError("Empty image")
        qba = QByteArray()
        buf = QBuffer(qba)
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        if image.save(buf, "PNG"):
            return bytes(qba)
        raise ClipboardImageError("Failed to encode clipboard image as PNG")

    @staticmethod
    def _to_png(raw: bytes) -> bytes:
        try:
            with Image.open(io.BytesIO(raw)) as img:
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue()
        except Exception as exc:  # PIL.UnidentifiedImageError etc.
            raise ClipboardImageError(f"Invalid image data: {exc}") from exc
