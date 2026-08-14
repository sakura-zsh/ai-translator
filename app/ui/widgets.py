"""Small reusable UI helpers."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, Signal
from PySide6.QtGui import QImage, QKeySequence
from PySide6.QtWidgets import QApplication, QPlainTextEdit


def load_theme(theme: str) -> str:
    name = "dark.qss" if theme != "light" else "light.qss"
    try:
        ref = resources.files("app.ui.themes").joinpath(name)
        return ref.read_text(encoding="utf-8")
    except Exception:
        path = Path(__file__).resolve().parent / "themes" / name
        return path.read_text(encoding="utf-8")


def apply_theme(app: QApplication, theme: str) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(load_theme(theme))


def qimage_to_png_bytes(image: QImage) -> bytes | None:
    if image.isNull():
        return None
    qba = QByteArray()
    qbuf = QBuffer(qba)
    qbuf.open(QBuffer.OpenModeFlag.WriteOnly)
    if not image.save(qbuf, "PNG"):
        return None
    return bytes(qba)


class SourceEdit(QPlainTextEdit):
    """原文框：Ctrl+V / 拖放优先识别图片。"""

    image_pasted = Signal(bytes)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._image_probe = None  # optional callable () -> bytes | None

    def set_image_probe(self, probe) -> None:
        """probe() 返回 PNG bytes 或 None（例如走 wl-paste）。"""
        self._image_probe = probe

    def canInsertFromMimeData(self, source) -> bool:  # noqa: N802
        if source is None:
            return False
        if source.hasImage():
            return True
        if source.hasUrls():
            for url in source.urls():
                if url.isLocalFile() and self._is_image_path(url.toLocalFile()):
                    return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source) -> None:  # noqa: N802
        if source is None:
            return
        png = self._png_from_mime(source)
        if png:
            self.image_pasted.emit(png)
            return
        super().insertFromMimeData(source)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # Wayland 上 Qt 剪贴板经常 hasImage()=false，需主动用 wl-paste 探测
        if event.matches(QKeySequence.StandardKey.Paste):
            if self._try_clipboard_image():
                event.accept()
                return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        md = event.mimeData()
        if md and (md.hasImage() or self._mime_has_image_file(md)):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        md = event.mimeData()
        png = self._png_from_mime(md) if md else None
        if png:
            self.image_pasted.emit(png)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def _try_clipboard_image(self) -> bool:
        # 1) 外部 probe（wl-paste）
        if self._image_probe is not None:
            try:
                png = self._image_probe()
            except Exception:
                png = None
            if png:
                self.image_pasted.emit(png)
                return True
        # 2) Qt clipboard
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return False
        md = clipboard.mimeData()
        png = self._png_from_mime(md) if md else None
        if png:
            self.image_pasted.emit(png)
            return True
        return False

    def _png_from_mime(self, source) -> bytes | None:
        if source.hasImage():
            img = source.imageData()
            if isinstance(img, QImage):
                return qimage_to_png_bytes(img)
            # sometimes QPixmap
            try:
                from PySide6.QtGui import QPixmap

                if isinstance(img, QPixmap) and not img.isNull():
                    return qimage_to_png_bytes(img.toImage())
            except Exception:
                pass
        if source.hasUrls():
            for url in source.urls():
                if not url.isLocalFile():
                    continue
                path = url.toLocalFile()
                if self._is_image_path(path):
                    try:
                        data = Path(path).read_bytes()
                        # normalize via QImage
                        qimg = QImage.fromData(data)
                        if not qimg.isNull():
                            return qimage_to_png_bytes(qimg) or data
                    except OSError:
                        continue
        # raw image/* formats Qt may expose
        for fmt in ("image/png", "image/jpeg", "image/webp", "image/bmp", "image/gif"):
            if source.hasFormat(fmt):
                raw = bytes(source.data(fmt))
                if raw:
                    qimg = QImage.fromData(raw)
                    if not qimg.isNull():
                        return qimage_to_png_bytes(qimg) or raw
        return None

    @staticmethod
    def _mime_has_image_file(md) -> bool:
        if not md.hasUrls():
            return False
        for url in md.urls():
            if url.isLocalFile() and SourceEdit._is_image_path(url.toLocalFile()):
                return True
        return False

    @staticmethod
    def _is_image_path(path: str) -> bool:
        lower = path.lower()
        return lower.endswith(
            (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")
        )
