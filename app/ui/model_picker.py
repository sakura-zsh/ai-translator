"""Bottom-bar provider / model / reasoning-effort picker.

A compact button shows the active model and effort; clicking it opens an
overlay panel with three stacked layers:

1. **Provider header** — the active provider's name, doubling as a dropdown
   toggle. Clicking it expands a one-column provider list *above* the model
   list (the panel grows upward; its bottom edge stays put).
2. **Model list** — the curated candidate models of the *current* provider
   only. The provider's full catalog is never shown here (Qwen alone
   exposes 100+ ids); it lives in settings.
3. **Footer** — an inline reasoning-effort slider row plus one action link
   that jumps straight to the picker's settings page.

The panel is a *child* widget of the central widget, not a system window —
the same approach as HistoryPanel. On Wayland compositors a frameless
top-level window would need explicit placement support; an overlay avoids
that entirely and keeps the panel clipped to the window.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.config.schema import MODEL_AUTO, MODEL_VISION

log = logging.getLogger(__name__)

# (value sent to the API, visible label). Labels intentionally use the
# canonical OpenAI-style effort names so what the user sees is exactly what
# goes into ``reasoning_effort``. "" = do not send the parameter: relays that
# do not implement it reject the whole request, so the neutral default must
# be "give the provider nothing extra".
EFFORT_CHOICES: tuple[tuple[str, str], ...] = (
    ("", "默认"),
    ("minimal", "minimal"),
    ("low", "low"),
    ("medium", "medium"),
    ("high", "high"),
)
_EFFORT_HELP = {
    "": "默认：不发送 reasoning_effort，兼容所有接口",
    "minimal": "minimal：最省推理，速度最快",
    "low": "low：少量推理",
    "medium": "medium：均衡（推荐）",
    "high": "high：最充分推理，耗时最长",
}
_EFFORT_LABELS = dict(EFFORT_CHOICES)
_EFFORT_ORDER: list[str] = [value for value, _ in EFFORT_CHOICES]

# Item roles: which (provider, model) a row stands for.
_ROLE_PROFILE = Qt.ItemDataRole.UserRole
_ROLE_MODEL = Qt.ItemDataRole.UserRole + 1
_ROLE_KIND = Qt.ItemDataRole.UserRole + 2  # "provider" | "model" | "hint"

_PANEL_WIDTH = 380
_HEADER_HEIGHT = 34
_PROVIDER_ROW_HEIGHT = 30
_PROVIDER_ROW_PADDING = 3
_MAX_PROVIDER_ROWS = 5
_MODEL_ROW_HEIGHT = 34
_MAX_MODEL_ROWS = 6


def effort_label(value: str) -> str:
    """Label for an effort value; the name matches the API parameter value."""
    return _EFFORT_LABELS.get((value or "").strip().lower(), "默认")


def effort_help(value: str) -> str:
    """One-line explanation of what an effort value actually does."""
    return _EFFORT_HELP.get((value or "").strip().lower(), _EFFORT_HELP[""])


def _shorten(text: str, limit: int = 30) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ModelPickerButton(QPushButton):
    """Shows "模型 · 强度 ▾" and opens the picker panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("modelPickerButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._model = ""
        self._effort = ""
        self._provider = ""
        self._render()

    def set_summary(self, model: str, effort: str, provider: str = "") -> None:
        self._model = (model or "").strip()
        self._effort = (effort or "").strip()
        self._provider = (provider or "").strip()
        self._render()

    @property
    def model(self) -> str:
        return self._model

    @property
    def effort(self) -> str:
        return self._effort

    def _render(self) -> None:
        model = _shorten(self._model) or "未选择模型"
        self.setText(f"{model}  ·  {effort_label(self._effort)}  ▾")
        provider = f"\n服务商：{self._provider}" if self._provider else ""
        self.setToolTip(
            f"切换服务商 / 模型，调整推理强度{provider}\n"
            f"模型：{self._model or '（未设置）'}\n"
            f"推理强度：{effort_help(self._effort)}\n"
            + (f"请求参数：reasoning_effort={self._effort}" if self._effort else "请求参数：无")
        )


class ModelPickerPopup(QFrame):
    """Overlay panel: provider dropdown → candidate models → effort row."""

    model_selected = Signal(str, str)  # (profile id, model id or sentinel)
    provider_selected = Signal(str)  # provider switch without a model change
    effort_selected = Signal(str)
    disabled_changed = Signal(bool)  # a provider has no candidates → picker mute
    settings_requested = Signal(str)  # profile id to open in settings
    closed = Signal()

    def __init__(
        self,
        parent: QWidget,
        profiles_fn: Callable[[], list[Any]],
        active_id_fn: Callable[[], str],
    ) -> None:
        super().__init__(parent)
        self._profiles_fn = profiles_fn
        self._active_id_fn = active_id_fn
        self._active_id = ""
        self._current_model = ""
        self._effort = ""
        self._providers_open = False
        self._anchor: QRect | None = None
        self._disabled = False

        self.setObjectName("modelPickerPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedWidth(_PANEL_WIDTH)
        self.hide()

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        root.addWidget(self._build_header())
        self.provider_panel = self._build_provider_panel()
        root.addWidget(self.provider_panel)
        root.addWidget(self._build_models_page(), 1)
        root.addWidget(self._build_footer())

        self.btn_settings_link.clicked.connect(self._on_settings_link)

    # ── header ────────────────────────────────────────────────────
    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("modelPickerHeader")
        header.setFixedHeight(_HEADER_HEIGHT)
        row = QHBoxLayout(header)
        row.setContentsMargins(10, 0, 6, 0)
        row.setSpacing(6)

        self.btn_provider = QPushButton("")
        self.btn_provider.setObjectName("modelPickerProvider")
        self.btn_provider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_provider.setToolTip("切换服务商")
        self.btn_provider.clicked.connect(self._toggle_providers)
        row.addWidget(self.btn_provider, 1)

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("historyMiniButton")
        self.btn_close.setFixedWidth(26)
        self.btn_close.setToolTip("关闭 (Esc)")
        self.btn_close.clicked.connect(self.hide_panel)
        row.addWidget(self.btn_close)
        return header

    def _build_provider_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("modelPickerProviders")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.provider_list = QListWidget()
        self.provider_list.setObjectName("modelPickerProviderList")
        self.provider_list.setFrameShape(QFrame.Shape.NoFrame)
        self.provider_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.provider_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.provider_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.provider_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.provider_list.itemClicked.connect(self._on_provider_clicked)
        layout.addWidget(self.provider_list)

        panel.hide()
        return panel

    def _build_models_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.list = QListWidget()
        self.list.setObjectName("modelPickerList")
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list.setMinimumHeight(120)
        self.list.setMaximumHeight(260)
        self.list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list, 1)

        self.status = QLabel("")
        self.status.setObjectName("modelPickerStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.status.hide()
        return page

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        layout = QVBoxLayout(footer)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(6)

        line = QHBoxLayout()
        line.setSpacing(8)
        caption = QLabel("推理强度")
        caption.setObjectName("modelPickerStatus")
        caption.setFixedWidth(52)
        line.addWidget(caption)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("modelPickerSlider")
        self.slider.setRange(0, len(_EFFORT_ORDER) - 1)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(1)
        self.slider.setTracking(True)
        self.slider.setToolTip(
            "档位名与 API 参数 reasoning_effort 的取值一致：\n"
            "默认（不发送参数） / minimal / low / medium / high\n"
            "仅对支持该参数的模型生效；网关不支持时会自动去掉重试。"
        )
        self.slider.valueChanged.connect(self._on_slider_value)
        line.addWidget(self.slider, 1)

        self.effort_name = QLabel(effort_label(""))
        self.effort_name.setObjectName("modelPickerEffortValue")
        self.effort_name.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.effort_name.setFixedWidth(56)
        self.effort_name.setToolTip(effort_help(""))
        line.addWidget(self.effort_name)
        layout.addLayout(line)

        link_row = QHBoxLayout()
        link_row.setContentsMargins(0, 0, 0, 0)
        self.btn_settings_link = QPushButton("管理候选模型…")
        self.btn_settings_link.setObjectName("pickerLink")
        self.btn_settings_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings_link.setToolTip("打开设置 → LLM 配置，维护候选模型与视觉模型")
        link_row.addWidget(self.btn_settings_link)
        link_row.addStretch(1)
        layout.addLayout(link_row)
        return footer

    # ── provider dropdown ─────────────────────────────────────────
    def _toggle_providers(self) -> None:
        self._set_providers_open(not self._providers_open)

    def _set_providers_open(self, opened: bool) -> None:
        if opened == self._providers_open:
            return
        self._providers_open = opened
        self.provider_panel.setVisible(opened)
        self.btn_provider.setProperty("expanded", "true" if opened else "false")
        self.btn_provider.style().unpolish(self.btn_provider)
        self.btn_provider.style().polish(self.btn_provider)
        self._relayout_growing_up()
        if opened:
            self.provider_list.setFocus(Qt.FocusReason.PopupFocusReason)

    def _relayout_growing_up(self) -> None:
        """Grow/shrink upward: the bottom edge stays put.

        The panel must *not* get a fixed height here — later content changes
        (a provider with more candidates) have to be able to resize it again.
        `adjustSize()` alone is unreliable for a styled frame, so the new
        height is taken from the layout's size hint and applied via
        `resize()`, while the top edge is recomputed from the kept bottom.
        """
        self.ensurePolished()
        layout = self.layout()
        if layout is None:
            return
        # `setFixedHeight()` on a child does not invalidate the parent layout
        # by itself, so `totalSizeHint()` keeps reporting the old height.
        # Drop the cached hints for every child, layout included.
        for child in self.findChildren(QWidget):
            child.updateGeometry()
        layout.invalidate()
        layout.activate()
        height = max(layout.totalSizeHint().height(), self.minimumSizeHint().height())
        bottom = self.geometry().bottom() if self.isVisible() else None
        if bottom is None or bottom <= 0:
            bottom = self.y() + self.height() - 1
        parent = self.parentWidget()
        y = bottom - height + 1
        if parent is not None:
            y = max(8, min(y, parent.height() - height - 8))
        self.resize(_PANEL_WIDTH, height)
        self.move(self.x(), y)

    def _refit(self) -> None:
        """Content changed while visible → re-measure and grow upward."""
        if self.isVisible():
            self._relayout_growing_up()

    def _rebuild_providers(self, profiles: list[Any], active_id: str) -> None:
        self.provider_list.blockSignals(True)
        self.provider_list.clear()
        active_name = ""
        for profile in profiles:
            pid = str(getattr(profile, "id", "") or "")
            name = str(getattr(profile, "name", "") or "未命名")
            count = len([m for m in (getattr(profile, "models", []) or []) if m])
            active = pid == active_id
            if active:
                active_name = name
            label = f"{'✓  ' if active else '    '}{name}"
            item = QListWidgetItem(label)
            item.setData(_ROLE_KIND, "provider")
            item.setData(_ROLE_PROFILE, pid)
            item.setToolTip(f"{name} · {count} 个候选模型" if count else f"{name} · 尚无候选模型")
            font = QFont(item.font())
            font.setBold(active)
            item.setFont(font)
            item.setForeground(QColor("#1e66f5" if active else "#6c6f85"))
            item.setSizeHint(QSize(0, _PROVIDER_ROW_HEIGHT))
            self.provider_list.addItem(item)
        self.provider_list.blockSignals(False)

        rows = min(max(1, self.provider_list.count()), _MAX_PROVIDER_ROWS)
        # 2px padding per side (0,2,0,2) + a little slack: the row size hints
        # come from QSS padding, so an exact rows*h number would clip the last
        # row and force a scrollbar.
        self.provider_list.setFixedHeight(
            rows * _PROVIDER_ROW_HEIGHT + 2 * _PROVIDER_ROW_PADDING + 2
        )
        self.btn_provider.setText(f"{active_name or '选择服务商'}  ▾")

    def _on_provider_clicked(self, item: QListWidgetItem) -> None:
        pid = str(item.data(_ROLE_PROFILE) or "")
        if not pid:
            return
        self._set_providers_open(False)
        if pid == self._active_id:
            return
        self._active_id = pid
        self._rebuild_providers(self._profiles_fn(), pid)
        self.rebuild_list(self._profiles_fn(), pid, "")
        self.provider_selected.emit(pid)

    # ── content ───────────────────────────────────────────────────
    def reload(self, profile: Any) -> None:
        """Load the active profile into the panel (before each show)."""
        self._current_model = str(getattr(profile, "model", "") or "")
        self._effort = str(getattr(profile, "reasoning_effort", "") or "")
        self.set_effort(self._effort)
        self.rebuild_list(
            self._profiles_fn(),
            self._active_id_fn(),
            self._current_model,
        )

    def rebuild_list(
        self, profiles: list[Any], active_id: str, current_model: str
    ) -> None:
        """Render the active provider's candidates (only that provider's)."""
        self._active_id = active_id
        self._current_model = current_model
        active = next(
            (p for p in profiles if str(getattr(p, "id", "") or "") == active_id),
            None,
        )
        self._rebuild_providers(profiles, active_id)

        self.list.blockSignals(True)
        self.list.clear()
        models = [m for m in (getattr(active, "models", []) or []) if m] if active else []
        progress = _stored_progress(active, current_model)
        if not models:
            self.list.addItem(
                self._hint_item("这个服务商还没有候选模型，去设置里挑几个")
            )
            self._set_disabled(True)
        else:
            if progress:
                self.list.addItem(self._hint_item(progress))
            for model in models:
                self.list.addItem(self._model_item(model, current_model))
            self._set_disabled(False)
        self.list.blockSignals(False)

        # Size from the rows' *real* size hints, not a hard-coded row height:
        # the QSS item padding and the platform font both shift it, and a
        # mismatch either clips rows or leaves a blank stripe. The +2 is the
        # frame border of the (styled) list viewport.
        rows = max(1, self.list.count())
        rows = min(rows, _MAX_MODEL_ROWS)
        # Prefer the measured row height when the view has one; QSS padding
        # lands on the delegate, so a plain constant can be a pixel or two off.
        measured = 0
        if self.list.count():
            hint = self.list.item(0).sizeHint()
            if hint.isValid() and hint.height() > 0:
                measured = hint.height()
        row_height = measured or _MODEL_ROW_HEIGHT
        self.list.setFixedHeight(rows * row_height + 2)
        self._set_status("")
        self._refit()

    def _set_status(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _model_item(self, model: str, current: str) -> QListWidgetItem:
        checked = model == current
        label = model_display(model)
        item = QListWidgetItem(self._row_text(checked, label))
        item.setData(_ROLE_KIND, "model")
        item.setData(_ROLE_MODEL, model)
        if model == MODEL_AUTO:
            item.setToolTip("从候选中挑一个非推理模型：推理模型思维链易混入译文")
            item.setForeground(QColor("#8c8fa1"))
        else:
            item.setToolTip(f"{self._provider_name(self._active_id)} · {model}")
        item.setSizeHint(QSize(0, 34))
        return item

    @staticmethod
    def _hint_item(text: str) -> QListWidgetItem:
        item = QListWidgetItem(text)
        item.setData(_ROLE_KIND, "hint")
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        item.setForeground(QColor("#9ca0b0"))
        item.setSizeHint(QSize(0, 34))
        return item

    @staticmethod
    def _row_text(checked: bool, label: str) -> str:
        return ("✓  " if checked else "    ") + label

    def set_effort(self, value: str) -> None:
        self._effort = (value or "").strip().lower()
        if self._effort not in _EFFORT_ORDER:
            self._effort = ""
        self.effort_name.setText(effort_label(self._effort))
        self.effort_name.setToolTip(effort_help(self._effort))
        self.slider.blockSignals(True)
        self.slider.setValue(_EFFORT_ORDER.index(self._effort))
        self.slider.blockSignals(False)

    def _set_disabled(self, disabled: bool) -> None:
        """Mute the model list when the provider has no candidates."""
        if disabled == self._disabled:
            return
        self._disabled = disabled
        self.list.setDisabled(disabled)
        self.disabled_changed.emit(disabled)

    @property
    def providers_open(self) -> bool:
        return self._providers_open

    # ── interaction ───────────────────────────────────────────────
    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        if item.data(_ROLE_KIND) != "model":
            return
        model = str(item.data(_ROLE_MODEL) or "")
        if not model or not self._active_id:
            return
        if model == self._current_model:
            return
        self._current_model = model
        self.rebuild_list(
            self._profiles_fn(), self._active_id, self._current_model
        )
        self.model_selected.emit(self._active_id, model)

    def _on_settings_link(self) -> None:
        pid = self._active_id or self._active_id_fn()
        self.hide_panel()
        self.settings_requested.emit(pid)

    def _provider_name(self, pid: str) -> str:
        for profile in self._profiles_fn():
            if str(getattr(profile, "id", "") or "") == pid:
                return str(getattr(profile, "name", "") or "")
        return ""

    def _on_slider_value(self, index: int) -> None:
        self._select_effort(_EFFORT_ORDER[max(0, min(index, len(_EFFORT_ORDER) - 1))])

    def _select_effort(self, value: str) -> None:
        if value == self._effort:
            return
        self.set_effort(value)
        self.effort_selected.emit(self._effort)

    # ── placement ─────────────────────────────────────────────────
    def show_above(self, anchor: QRect) -> None:
        """Position above `anchor` (rect in parent coordinates), clamped."""
        parent = self.parentWidget()
        if parent is None:
            return
        self._anchor = QRect(anchor)
        self._set_providers_open(False)
        self.adjustSize()
        height = self.height() or self.sizeHint().height()
        width = self.width()
        x = anchor.center().x() - width // 2
        y = anchor.top() - height - 8
        if y < 8:  # no room above → fall below the button
            y = anchor.bottom() + 8
        x = max(8, min(x, parent.width() - width - 8))
        y = max(8, min(y, parent.height() - height - 8))
        self.move(QPoint(x, y))
        self.raise_()
        self.show()
        self.setFocus(Qt.FocusReason.PopupFocusReason)

    def hide_panel(self) -> None:
        if self.isVisible():
            self._set_providers_open(False)
            self.hide()
            self.closed.emit()

    def hides_click_at(self, global_pos: QPoint, anchor: QRect) -> bool:
        """True when a click at `global_pos` lands outside panel *and* anchor.

        The anchor is the trigger button: clicking it must toggle (and is
        handled by the button itself), never count as an outside click.
        """
        panel_rect = QRect(self.mapToGlobal(QPoint(0, 0)), self.size())
        if panel_rect.contains(global_pos):
            return False
        parent = self.parentWidget()
        if parent is None:
            return True
        anchor_rect = QRect(parent.mapToGlobal(anchor.topLeft()), anchor.size())
        return not anchor_rect.contains(global_pos)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            if self._providers_open:
                self._set_providers_open(False)
            else:
                self.hide_panel()
            event.accept()
            return
        super().keyPressEvent(event)


def _stored_progress(profile: Any, current: str) -> str:
    """One-line progress hint for a provider that exposes the API key name."""
    if profile is None or not current:
        return ""
    models = [m for m in (getattr(profile, "models", []) or []) if m]
    if current in models:
        return ""
    if any(m == MODEL_VISION for m in models):
        return ""
    return f"当前使用的 {model_display(current)} 不在候选里"


def model_display(model: str) -> str:
    """Human label for a stored model value (sentinels included)."""
    if model == MODEL_AUTO:
        return "自动选择"
    if model == MODEL_VISION:
        return "图片翻译模型"  # legacy value; kept for old configs
    return (model or "").strip() or "未选择"
