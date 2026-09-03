"""Read image bytes from the Windows clipboard via Qt."""

from __future__ import annotations

from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication

from app.core.clipboard_image import ClipboardImageError
from app.core.imaging import normalize_to_png
from app.core.qtimage import qimage_to_png_bytes


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
                return self._encode(img)
            if isinstance(img, QPixmap) and not img.isNull():
                return self._encode(img.toImage())

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
                        return normalize_to_png(raw)
                    except ValueError:
                        # PIL could not decode it; give Qt's decoder a chance.
                        encoded = qimage_to_png_bytes(QImage.fromData(raw))
                        if encoded:
                            return encoded

        raise ClipboardImageError("Clipboard has no image data")

    @staticmethod
    def _encode(image: QImage) -> bytes:
        encoded = qimage_to_png_bytes(image)
        if not encoded:
            raise ClipboardImageError("Failed to encode clipboard image as PNG")
        return encoded
