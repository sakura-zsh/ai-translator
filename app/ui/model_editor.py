"""Model candidate editor used by the settings dialog.

The settings form edits the *working copy* directly, but each keystroke in
an add-model box would otherwise write through on every character. This
widget coalesces all edits into one signal, emitted when the user is done
(press Enter / leave the field), so the profile is only saved on intent.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config.schema import MODEL_AUTO, MODEL_CANDIDATES_MAX, is_sentinel_model
from app.ui.model_picker import model_display

_ROLE_MODEL = int(Qt.ItemDataRole.UserRole) + 1


class CandidateModelEditor(QWidget):
    """列表 + 添加 + 删除 + 「从服务商列表选择」。"""

    changed = Signal()
    catalog_requested = Signal()
    list_changed = Signal()  # candidate rows added/removed (vision combo stale)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profile: Any = None
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # A flat QListWidget (not QTreeWidget): candidate rows are strings,
        # and QListWidgetItem keeps text and payload strictly separate.
        self.tree = QListWidget()
        self.tree.setObjectName("candidateTree")
        self.tree.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.tree.setIconSize(QSize(0, 0))
        font = QFont(self.tree.font())
        font.setPointSizeF(max(9.0, font.pointSizeF() + 0.5))
        self.tree.setFont(font)
        self.tree.setFrameShape(QFrame.Shape.NoFrame)
        self.tree.setMinimumHeight(self._TREE_HEIGHT)
        self.tree.currentItemChanged.connect(self._sync_selection)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("添加模型 id，回车确认（可粘贴）")
        self.edit.returnPressed.connect(self.add_from_edit)
        self.edit.editingFinished.connect(self.add_from_edit)
        self.btn_add = QPushButton("添加")
        self.btn_add.clicked.connect(self.add_from_edit)
        self.btn_catalog = QPushButton("从服务商列表…")
        self.btn_catalog.setToolTip("拉取该服务商的 /models 列表，勾选要保留的模型")
        self.btn_catalog.clicked.connect(self.catalog_requested.emit)
        self.btn_del = QPushButton("删除")
        self.btn_del.setObjectName("dangerButton")
        self.btn_del.setToolTip("从候选列表移除（当前选中的模型会自动改选第一个）")
        self.btn_del.clicked.connect(self.remove_current)
        row.addWidget(self.edit, 1)
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_catalog)
        row.addWidget(self.btn_del)
        root.addLayout(row)

        self.status = QLabel("")
        self.status.setObjectName("hintLabel")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        # The list goes last: with the add row on top the tree keeps a
        # fixed height and never gets pushed behind the buttons.
        root.addWidget(self.tree, 1)

    # A QFormLayout row only gives a QAbstractScrollArea its minimumSizeHint,
    # which for QListWidget is a couple of rows tall — the list then collapses
    # to a 3-line stripe. Claim the real height here instead.
    _TREE_HEIGHT = 150

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(hint.width(), self._TREE_HEIGHT + 100)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = super().minimumSizeHint()
        return QSize(hint.width(), self._TREE_HEIGHT + 100)

    # ── loading ───────────────────────────────────────────────────
    def set_profile(self, profile: Any) -> None:
        """Load a profile (may be None when no provider is selected)."""
        self._profile = profile
        self.setEnabled(profile is not None)
        self.edit.setText("")
        self._set_status("")
        self.reload()

    def reload(self) -> None:
        """Re-render rows from the current profile."""
        profile = self._profile
        self._loading = True
        self.tree.clear()
        if profile is None:
            self._loading = False
            return
        selected = str(getattr(profile, "model", "") or "")
        vision = str(getattr(profile, "vision_model", "") or "")
        selected_item: QListWidgetItem | None = None
        # "自动选择" is a real row: it is a selectable mode, not a missing
        # model, and the settings list must be able to switch back to it.
        auto_item = QListWidgetItem(self._auto_label(selected))
        auto_item.setData(_ROLE_MODEL, MODEL_AUTO)
        auto_item.setToolTip("从下面的候选中自动挑一个（跳过推理模型），不想逐个试的时候用它")
        self.tree.addItem(auto_item)
        for model in list(getattr(profile, "models", []) or []):
            if is_sentinel_model(model):
                continue
            item = QListWidgetItem(self._row_label(model, selected, vision))
            item.setData(_ROLE_MODEL, model)
            item.setToolTip(model)
            self.tree.addItem(item)
            if model == selected:
                selected_item = item
        self._loading = False
        if selected == MODEL_AUTO:
            selected_item = auto_item
        if selected_item is not None:
            self.tree.setCurrentItem(selected_item)
        self._update_buttons()
        self._update_status()

    @staticmethod
    def _auto_label(selected: str) -> str:
        label = model_display(MODEL_AUTO)
        if selected == MODEL_AUTO:
            label = f"● {label}"
        return f"{label}    （按顺序挑第一个可用模型）"

    @staticmethod
    def _row_label(model: str, selected: str, vision: str) -> str:
        label = model_display(model)
        marks: list[str] = []
        if model == selected:
            label = f"● {label}"
            marks.append("当前")
        if model and model == vision:
            marks.append("图片翻译")
        if marks:
            label += f"    （{'、'.join(marks)}）"
        return label

    def _update_status(self) -> None:
        profile = self._profile
        if profile is None:
            self._set_status("")
            return
        count = len(getattr(profile, "models", []) or [])
        vision = str(getattr(profile, "vision_model", "") or "")
        tail = (
            f"图片翻译使用专用模型 {vision}"
            if vision
            else "图片翻译跟随当前模型（多数模型原生支持图片）"
        )
        self._set_status(f"候选 {count}/{MODEL_CANDIDATES_MAX} · {tail}")

    def _set_status(self, text: str) -> None:
        self.status.setText(text)
        self.status.setToolTip(text)

    def _update_buttons(self) -> None:
        item = self.tree.currentItem()
        model = str(item.data(_ROLE_MODEL)) if item is not None else ""
        self.btn_del.setEnabled(
            bool(model)
            and not is_sentinel_model(model)
            and len(getattr(self._profile, "models", []) or []) > 1
        )

    # ── mutations ─────────────────────────────────────────────────
    def _current_value(self) -> str:
        item = self.tree.currentItem()
        return str(item.data(_ROLE_MODEL)) if item is not None else ""

    def _sync_selection(self, current, _prev) -> None:
        # Single click on a row selects it as the active model — that is the
        # whole point of the list in settings.
        if self._loading or self._profile is None or current is None:
            return
        model = str(current.data(_ROLE_MODEL))
        if not model or model == getattr(self._profile, "model", ""):
            return
        self._profile.model = model
        self.reload()
        self.refresh_vision_rows()
        self.changed.emit()

    def add_from_edit(self) -> None:
        name = self.edit.text().strip()
        if not name or self._profile is None:
            return
        if name in (getattr(self._profile, "models", []) or []):
            self._set_status(f"「{name}」已在候选列表中")
            return
        if not self._profile.add_model(name):
            self._set_status(f"候选列表已满（上限 {MODEL_CANDIDATES_MAX}）")
            return
        self.edit.clear()
        self.reload()
        self.changed.emit()
        self.list_changed.emit()

    def remove_current(self) -> None:
        model = self._current_value()
        if not model or self._profile is None:
            return
        if not self._profile.remove_model(model):
            return
        self.reload()
        self.changed.emit()
        self.list_changed.emit()

    def add_models(self, names: list[str]) -> None:
        """Bulk add (used by the catalog picker); returns silently on dupes."""
        if self._profile is None:
            return
        added = 0
        for name in names:
            if self._profile.add_model(name):
                added += 1
        if added:
            self.reload()
            self.changed.emit()
            self.list_changed.emit()
            self._set_status(f"已添加 {added} 个模型")

    def set_vision_model(self, value: str) -> None:
        if self._profile is None:
            return
        self._profile.vision_model = (value or "").strip()
        self.reload()
        self.changed.emit()


def sentinel_rows(profile: Any) -> list[tuple[str, str]]:
    """(value, label) pairs for the vision-model combo, "follow" first."""
    rows: list[tuple[str, str]] = [("", "跟随当前模型（多数模型原生支持图片）")]
    for model in list(getattr(profile, "models", []) or []):
        if is_sentinel_model(model):
            continue
        rows.append((model, model))
    return rows
