"""Screenshot capture via fullscreen region selector (Windows / Qt)."""

from __future__ import annotations

from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from app.core.qtimage import qimage_to_png_bytes
from app.core.screenshot import ScreenshotCancelled, ScreenshotError


def _virtual_geometry() -> QRect:
    screens = QGuiApplication.screens()
    if not screens:
        raise ScreenshotError("No screens available")
    geo = screens[0].geometry()
    for screen in screens[1:]:
        geo = geo.united(screen.geometry())
    return geo


def _grab_virtual_desktop() -> QPixmap:
    """Capture the full virtual desktop (all monitors)."""
    screens = QGuiApplication.screens()
    if not screens:
        raise ScreenshotError("No screens available")

    virtual = _virtual_geometry()
    canvas = QPixmap(virtual.size())
    canvas.fill(Qt.GlobalColor.black)
    painter = QPainter(canvas)
    try:
        for screen in screens:
            geo = screen.geometry()
            # grabWindow(0) grabs the whole screen in screen-local coords
            part = screen.grabWindow(0)
            if part.isNull():
                continue
            # Map screen geometry into virtual-desktop coordinates
            top_left = geo.topLeft() - virtual.topLeft()
            painter.drawPixmap(top_left, part)
    finally:
        painter.end()

    if canvas.isNull():
        raise ScreenshotError("Failed to capture desktop")
    return canvas


def _pixmap_to_png_bytes(pix: QPixmap) -> bytes:
    image = pix.toImage()
    if image.isNull():
        raise ScreenshotError("Empty capture")
    # Ensure a stable channel layout for downstream OCR / Vision
    if image.format() not in (
        QImage.Format.Format_RGB32,
        QImage.Format.Format_ARGB32,
        QImage.Format.Format_ARGB32_Premultiplied,
        QImage.Format.Format_RGBA8888,
    ):
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)

    encoded = qimage_to_png_bytes(image)
    if not encoded:
        raise ScreenshotError("Failed to encode PNG")
    return encoded


class _RegionSelector(QWidget):
    """Fullscreen dim overlay; drag to select a region. Esc cancels."""

    finished = Signal(object)  # QRect | None in virtual-desktop coords

    def __init__(self, background: QPixmap, virtual_geo: QRect) -> None:
        super().__init__(None)
        self._bg = background
        self._virtual = virtual_geo
        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._selected: QRect | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(virtual_geo)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.drawPixmap(0, 0, self._bg)

        # Dim whole desktop
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

        sel = self._selection_rect()
        if sel is not None and sel.width() > 0 and sel.height() > 0:
            # Punch a clear hole by re-drawing the background in the selection
            painter.drawPixmap(sel, self._bg, sel)
            pen = QPen(QColor(137, 180, 250), 2)  # catppuccin blue
            painter.setPen(pen)
            painter.drawRect(sel.adjusted(0, 0, -1, -1))

            # Size label
            label = f"{sel.width()} × {sel.height()}"
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(sel.left() + 6, max(sel.top() - 6, 14), label)

        painter.end()

    def _selection_rect(self) -> QRect | None:
        if self._origin is None or self._current is None:
            return self._selected
        return QRect(self._origin, self._current).normalized()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self._selected = None
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self._cancel()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._origin is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        self._current = event.position().toPoint()
        rect = QRect(self._origin, self._current).normalized()
        self._origin = None
        self._current = None
        if rect.width() < 3 or rect.height() < 3:
            self._cancel()
            return
        self._selected = rect
        self._accept(rect)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            rect = self._selection_rect()
            if rect is not None and rect.width() >= 3 and rect.height() >= 3:
                self._accept(rect)
                return
        super().keyPressEvent(event)

    def _accept(self, rect: QRect) -> None:
        self.finished.emit(rect)
        self.close()

    def _cancel(self) -> None:
        self.finished.emit(None)
        self.close()


class ScreenshotService:
    """Interactive region screenshot for Windows.

    ``capture_region`` must be called from the Qt GUI thread (uses a modal
    overlay). Always available when a QApplication exists.
    """

    requires_gui_thread = True

    def available(self) -> bool:
        return QApplication.instance() is not None

    def capture_region(self) -> bytes:
        """Interactive region select → PNG bytes. Raises ScreenshotCancelled on Esc."""
        app = QApplication.instance()
        if app is None:
            raise ScreenshotError("QApplication is not running")

        virtual = _virtual_geometry()
        background = _grab_virtual_desktop()

        result: dict[str, QRect | None] = {"rect": None}
        selector = _RegionSelector(background, virtual)
        loop = QEventLoop()

        def on_finished(rect: object) -> None:
            result["rect"] = rect if isinstance(rect, QRect) else None
            loop.quit()

        selector.finished.connect(on_finished)
        selector.destroyed.connect(loop.quit)
        selector.show()
        selector.raise_()
        selector.activateWindow()
        selector.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        loop.exec()

        rect = result["rect"]
        if rect is None:
            raise ScreenshotCancelled("Screenshot cancelled")

        # Clamp to pixmap bounds
        pix_rect = QRect(0, 0, background.width(), background.height())
        crop = rect.intersected(pix_rect)
        if crop.width() < 1 or crop.height() < 1:
            raise ScreenshotCancelled("Screenshot cancelled")

        cropped = background.copy(crop)
        return _pixmap_to_png_bytes(cropped)
