"""Editors for a provider's candidate model list.

``ModelCatalogDialog`` is the "从服务商可用列表勾选" picker: it pulls
``GET {base_url}/models`` once and lets the user tick the few models worth
keeping. Qwen-style providers expose 100+ ids, which is exactly why the
main window never shows this list directly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.llm_client import LlmClient
from app.workers.tasks import TaskRunner


class ModelCatalogDialog(QDialog):
    """Tick models from the provider catalog to add to the candidate list."""

    def __init__(
        self,
        profile_fn: Callable[[], Any],
        existing: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("从服务商列表选择模型")
        self.setMinimumSize(480, 520)
        self._profile_fn = profile_fn
        self._existing = set(existing)
        self._runner = TaskRunner(QThreadPool.globalInstance(), parent=self)

        root = QVBoxLayout(self)
        intro = QLabel(
            "勾选要加入候选列表的模型。列表来自服务方的 /models 接口，"
            "不勾选就不会出现在主页的切换面板里。"
        )
        intro.setObjectName("hintLabel")
        intro.setWordWrap(True)
        root.addWidget(intro)

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("过滤模型名…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.btn_fetch = QPushButton("获取列表")
        self.btn_fetch.clicked.connect(self.fetch)
        row.addWidget(self.search, 1)
        row.addWidget(self.btn_fetch)
        root.addLayout(row)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        root.addWidget(self.list, 1)

        self.status = QLabel("尚未获取；点「获取列表」从服务方拉取。")
        self.status.setObjectName("hintLabel")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ── fetch ─────────────────────────────────────────────────────
    def fetch(self) -> None:
        profile = self._profile_fn()
        if profile is None:
            return
        if not str(getattr(profile, "base_url", "") or "").strip():
            self.status.setText("先在设置里填写 Base URL")
            return
        if self._runner.busy:
            return
        self.btn_fetch.setEnabled(False)
        self.status.setText("获取中…")

        def work() -> list[str]:
            return LlmClient(profile).list_models()

        self._runner.run(work, self._on_ok, self._on_err)

    def _on_ok(self, names: object) -> None:
        self.btn_fetch.setEnabled(True)
        items = [str(n) for n in names] if isinstance(names, list) else []
        self.set_models(items)
        self.status.setText(f"共 {len(items)} 个模型，已勾选的会自动标注")

    def _on_err(self, exc: object) -> None:
        self.btn_fetch.setEnabled(True)
        self.status.setText(f"获取失败：{exc}")

    # ── list ──────────────────────────────────────────────────────
    def set_models(self, names: list[str]) -> None:
        self.list.clear()
        for name in names:
            item = QListWidgetItem(name)
            item.setToolTip(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            state = (
                Qt.CheckState.Checked
                if name in self._existing
                else Qt.CheckState.Unchecked
            )
            item.setCheckState(state)
            self.list.addItem(item)
        self._apply_filter(self.search.text())

    def _apply_filter(self, pattern: str) -> None:
        needle = (pattern or "").strip().lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def checked_models(self) -> list[str]:
        out: list[str] = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.text())
        return out
