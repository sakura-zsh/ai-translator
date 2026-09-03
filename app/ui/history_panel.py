"""Floating history panel (child of main window, not a system window)."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.config.schema import HistoryEntry
from app.core.languages import display_name


def _clip(text: str, limit: int = 280) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"


class HistoryCard(QFrame):
    """One history entry: meta + source + result."""

    activated = Signal(str)  # entry id
    copy_requested = Signal(str)  # entry id

    def __init__(self, entry: HistoryEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry_id = entry.id
        self.setObjectName("historyCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        meta = QHBoxLayout()
        when = ""
        if entry.ts:
            try:
                when = datetime.fromtimestamp(entry.ts).strftime("%m-%d %H:%M")
            except (OverflowError, OSError, ValueError):
                when = ""
        src = display_name(entry.source_lang)
        dst = display_name(entry.target_lang)
        mode = entry.mode or "text"
        title = QLabel(f"{when}  ·  {src} → {dst}  ·  {mode}")
        title.setObjectName("historyMeta")
        meta.addWidget(title, 1)
        self.btn_copy = QPushButton("复制")
        self.btn_copy.setObjectName("historyMiniButton")
        self.btn_copy.setToolTip("复制译文到剪贴板")
        # QPushButton consumes its own mouse events, so this click will not
        # bubble up to HistoryCard.mouseReleaseEvent (no card activation).
        self.btn_copy.clicked.connect(
            lambda _=False: self.copy_requested.emit(self.entry_id)
        )
        meta.addWidget(self.btn_copy)
        root.addLayout(meta)

        src_label = QLabel("原文")
        src_label.setObjectName("historyFieldLabel")
        root.addWidget(src_label)
        self.src_body = QLabel(_clip(entry.source_text) or "（空）")
        self.src_body.setObjectName("historySource")
        self.src_body.setWordWrap(True)
        self.src_body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.src_body)

        dst_label = QLabel("译文")
        dst_label.setObjectName("historyFieldLabel")
        root.addWidget(dst_label)
        self.dst_body = QLabel(_clip(entry.result_text) or "（空）")
        self.dst_body.setObjectName("historyResult")
        self.dst_body.setWordWrap(True)
        self.dst_body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.dst_body)

        # Keep card height roughly stable so ~2 fit in the panel
        fm = QFontMetrics(self.src_body.font())
        line = fm.lineSpacing()
        self.src_body.setMaximumHeight(line * 3 + 4)
        self.dst_body.setMaximumHeight(line * 3 + 4)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.entry_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class HistoryPanel(QFrame):
    """Overlay panel anchored under the history button (not a top-level window)."""

    entry_selected = Signal(str)
    copy_requested = Signal(str)  # entry id
    clear_requested = Signal()
    closed = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("historyPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._all_entries: list[HistoryEntry] = []
        self.hide()

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("历史记录")
        title.setObjectName("historyPanelTitle")
        header.addWidget(title, 1)
        self.btn_clear = QPushButton("清空")
        self.btn_clear.setObjectName("historyMiniButton")
        self.btn_clear.clicked.connect(self.clear_requested.emit)
        self.btn_close = QPushButton("关闭")
        self.btn_close.setObjectName("historyMiniButton")
        self.btn_close.clicked.connect(self.hide_panel)
        header.addWidget(self.btn_clear)
        header.addWidget(self.btn_close)
        root.addLayout(header)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索原文或译文…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filter)
        root.addWidget(self.search_edit)

        self.empty_label = QLabel("暂无翻译记录")
        self.empty_label.setObjectName("hintLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.empty_label)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("historyScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list_host)
        root.addWidget(self.scroll, 1)

        hint = QLabel("滚轮查看更多 · 点击卡片载入")
        hint.setObjectName("hintLabel")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(hint)

        # ~2 cards visible + search row: card ~150–170px + gaps
        self.setFixedWidth(380)
        self.setFixedHeight(430)

    def set_entries(self, entries: list[HistoryEntry]) -> None:
        """Replace the full entry list, then re-apply the active filter."""
        self._all_entries = list(entries)
        self._apply_filter(self.search_edit.text())

    def _apply_filter(self, pattern: str) -> None:
        needle = (pattern or "").strip().lower()
        if needle:
            shown = [
                e
                for e in self._all_entries
                if needle in (e.source_text or "").lower()
                or needle in (e.result_text or "").lower()
            ]
        else:
            shown = self._all_entries
        self._render(shown)

    def _render(self, entries: list[HistoryEntry]) -> None:
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not self._all_entries:
            self.empty_label.setText("暂无翻译记录")
            self.empty_label.setVisible(True)
            self.scroll.setVisible(False)
            self.btn_clear.setEnabled(False)
            return

        self.btn_clear.setEnabled(True)
        if not entries:
            self.empty_label.setText("无匹配记录")
            self.empty_label.setVisible(True)
            self.scroll.setVisible(False)
            return

        self.empty_label.setVisible(False)
        self.scroll.setVisible(True)

        for entry in entries:
            card = HistoryCard(entry, self.list_host)
            card.activated.connect(self._on_card)
            card.copy_requested.connect(self.copy_requested)
            # insert before trailing stretch
            self.list_layout.insertWidget(self.list_layout.count() - 1, card)

        self.scroll.verticalScrollBar().setValue(0)

    def show_at(self, global_anchor_bottom_right) -> None:
        """Position under/near the history button, within parent bounds."""
        parent = self.parentWidget()
        if parent is None:
            return
        local = parent.mapFromGlobal(global_anchor_bottom_right)
        x = local.x() - self.width()
        y = local.y() + 6
        # clamp inside parent
        x = max(8, min(x, parent.width() - self.width() - 8))
        y = max(8, min(y, parent.height() - self.height() - 8))
        self.move(x, y)
        self.raise_()
        self.show()
        self.setFocus(Qt.FocusReason.PopupFocusReason)

    def hide_panel(self) -> None:
        if self.isVisible():
            self.hide()
            self.closed.emit()

    def toggle_at(self, global_anchor_bottom_right) -> None:
        if self.isVisible():
            self.hide_panel()
        else:
            self.show_at(global_anchor_bottom_right)

    def _on_card(self, entry_id: str) -> None:
        self.entry_selected.emit(entry_id)
        self.hide_panel()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide_panel()
            event.accept()
            return
        super().keyPressEvent(event)
