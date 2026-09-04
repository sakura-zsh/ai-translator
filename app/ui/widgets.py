"""Small reusable UI helpers."""

from __future__ import annotations

import re
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtGui import QImage, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.llm_client import LlmClient
from app.core.qtimage import qimage_to_png_bytes
from app.workers.tasks import TaskRunner

# Re-exported: main_window and older code paths import it from here.
__all__ = ["qimage_to_png_bytes", "apply_theme", "load_theme", "ModelSelector", "SourceEdit"]

# Reasoning models are slow and tend to leak chain-of-thought into the
# answer — warn when the user picks one for translation.
_REASONING_MODEL_RE = re.compile(
    r"reasoner|[-_]r1\b|qwq|o[134](-|$|\b)|thinking|deepseek-r\d",
    re.IGNORECASE,
)


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


class ModelSelector(QWidget):
    """Editable model combo + a button that pulls the live list from
    ``GET {base_url}/models``.

    ``profile_fn`` must return the *current* LlmProfile (with unsaved form
    edits applied) so the fetch uses what the user actually typed.
    """

    models_fetched = Signal(list)

    def __init__(
        self,
        profile_fn: Callable[[], Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._profile_fn = profile_fn
        self._pool = QThreadPool.globalInstance()
        self._runner = TaskRunner(self._pool, parent=self)
        self._busy = False
        self._fetch_active = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.btn_fetch = QPushButton("获取模型")
        self.btn_fetch.setToolTip("从服务方 /models 接口拉取可用模型列表")
        row.addWidget(self.combo, 1)
        row.addWidget(self.btn_fetch)
        layout.addLayout(row)

        # One-line status area, ALWAYS reserved (empty when idle). A label
        # that appears on demand changes the row height mid-dialog and
        # squeezes the combo — so the space is claimed up front instead.
        # Full text (long errors etc.) is available via tooltip.
        self.status = QLabel("")
        self.status.setObjectName("hintLabel")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.status.setFixedHeight(self.status.fontMetrics().lineSpacing() + 2)
        layout.addWidget(self.status)

        self.btn_fetch.clicked.connect(self.fetch_models)
        self.combo.currentTextChanged.connect(self._update_reasoning_hint)

    # ── public API ────────────────────────────────────────────────
    def current_text(self) -> str:
        return self.combo.currentText().strip()

    def set_current_text(self, text: str) -> None:
        self.combo.setCurrentText(text)

    def _set_status(self, text: str) -> None:
        self.status.setText(text)
        self.status.setToolTip(text)

    def _update_reasoning_hint(self, text: str) -> None:
        if self._fetch_active:
            return  # fetch status text takes priority
        if _REASONING_MODEL_RE.search(text or ""):
            self._set_status(
                "⚠ 推理模型（R1/QwQ…）思维链易混入译文，翻译建议用普通模型"
            )
        else:
            self._set_status("")

    def set_items(self, names: list[str], *, keep_current: bool = True) -> None:
        current = self.current_text() if keep_current else ""
        self.combo.blockSignals(True)
        self.combo.clear()
        if current:
            self.combo.addItem(current)
        for name in names:
            if self.combo.findText(name) < 0:
                self.combo.addItem(name)
        self.combo.blockSignals(False)
        if not current and names:
            self.combo.setCurrentIndex(0)
        self._update_reasoning_hint(self.current_text())

    # ── fetch flow ────────────────────────────────────────────────
    def fetch_models(self) -> None:
        if self._busy:
            return
        profile = self._profile_fn()
        if profile is None:
            return
        self._busy = True
        self._fetch_active = True
        self.btn_fetch.setEnabled(False)
        self._set_status("获取模型列表中…")

        def work() -> list[str]:
            return LlmClient(profile).list_models()

        self._runner.run(work, self._on_fetch_ok, self._on_fetch_err)

    def _on_fetch_ok(self, names: object) -> None:
        self._busy = False
        self._fetch_active = False
        self.btn_fetch.setEnabled(True)
        items = [str(n) for n in names] if isinstance(names, list) else []
        self.set_items(items)
        self._set_status(
            f"已获取 {len(items)} 个模型"
            if items
            else "服务方返回了空列表"
        )

    def _on_fetch_err(self, exc: object) -> None:
        self._busy = False
        self._fetch_active = False
        self.btn_fetch.setEnabled(True)
        self._set_status(f"获取失败：{exc}")


class SourceEdit(QPlainTextEdit):
    """原文框：Ctrl+V / 拖放优先识别图片。"""

    image_pasted = Signal(bytes)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._image_probe = None  # optional callable () -> bytes | None

    def set_image_probe(self, probe) -> None:
        """probe() 返回 PNG bytes 或 None（剪贴板图片探测）。"""
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
        # Prefer image paste when clipboard holds an image
        if event.matches(QKeySequence.StandardKey.Paste) and self._try_clipboard_image():
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
        # 1) external probe (clipboard service)
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
