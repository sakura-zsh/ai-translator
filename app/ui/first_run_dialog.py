"""First-run wizard: pick a provider template, paste the key, pick a model."""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config.schema import LlmProfile
from app.core.llm_client import LlmClient
from app.core.providers import PROVIDER_TEMPLATES, get_template
from app.ui.widgets import ModelSelector
from app.workers.tasks import TaskRunner


class FirstRunDialog(QDialog):
    """Shown once when the app still runs on the untouched default profile."""

    def __init__(self, profile: LlmProfile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("欢迎使用 AI Translator")
        self.setMinimumWidth(560)
        self._profile = deepcopy(profile)
        self._pool = QThreadPool.globalInstance()
        self._runner = TaskRunner(self._pool, parent=self)
        self._testing = False

        root = QVBoxLayout(self)
        root.setSpacing(10)

        intro = QLabel(
            "选择一个 AI 服务商，填入 API Key 即可开始。\n"
            "所有选项之后都可以在「设置」中修改。"
        )
        intro.setObjectName("hintLabel")
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()

        self.c_template = QComboBox()
        for t in PROVIDER_TEMPLATES:
            self.c_template.addItem(t.name, t.id)
        self.c_template.currentIndexChanged.connect(self._on_template_changed)
        form.addRow("服务商", self.c_template)

        self.f_key = QLineEdit()
        self.f_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.f_key.setPlaceholderText("sk-…（本地服务可留空）")
        form.addRow("API Key", self.f_key)

        self.model_text = ModelSelector(self._applied_profile)
        form.addRow("文本模型", self.model_text)
        self.model_vision = ModelSelector(self._applied_profile)
        form.addRow("视觉模型", self.model_vision)

        root.addLayout(form)

        self.hint = QLabel("")
        self.hint.setObjectName("hintLabel")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        test_row = QHBoxLayout()
        self.btn_test = QPushButton("测试连接")
        self.btn_test.clicked.connect(self._test_connection)
        self.test_status = QLabel("")
        self.test_status.setObjectName("hintLabel")
        self.test_status.setWordWrap(True)
        test_row.addWidget(self.btn_test)
        test_row.addWidget(self.test_status, 1)
        root.addLayout(test_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setText("保存并开始")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        # Pre-select a sane default provider (OpenAI-compatible entry point).
        self._on_template_changed(self.c_template.currentIndex())

    # ── template handling ─────────────────────────────────────────
    def _on_template_changed(self, _index: int) -> None:
        template_id = self.c_template.currentData()
        template = get_template(template_id) if template_id else None
        if template is None:
            return
        self._profile.base_url = template.base_url
        self._profile.api_protocol = template.api_protocol  # type: ignore[assignment]
        self._profile.name = template.name
        if template.text_model:
            self._profile.model = template.text_model
        if template.vision_model:
            self._profile.vision_model = template.vision_model
        self.f_key.setText("")
        self.f_key.setPlaceholderText(
            "无需 API Key" if not template.key_required else "sk-…"
        )
        self.model_text.set_current_text(self._profile.model)
        self.model_vision.set_current_text(self._profile.vision_model)
        self.hint.setText(template.hint)
        self.test_status.setText("")

    def _applied_profile(self) -> LlmProfile:
        """Fold current form values into the profile (for fetch / test)."""
        self._profile.api_key = self.f_key.text().strip()
        self._profile.model = self.model_text.current_text() or self._profile.model
        self._profile.vision_model = (
            self.model_vision.current_text() or self._profile.model
        )
        return self._profile

    def _on_accept(self) -> None:
        self._applied_profile()
        self.accept()

    def result_profile(self) -> LlmProfile:
        return self._profile

    # ── connection test ───────────────────────────────────────────
    def _test_connection(self) -> None:
        if self._testing:
            return
        profile = self._applied_profile()
        self._testing = True
        self.btn_test.setEnabled(False)
        self.test_status.setText("测试中…")

        def work() -> str:
            return LlmClient(profile).test_connection()

        self._runner.run(work, self._on_test_ok, self._on_test_err)

    def _on_test_ok(self, reply: object) -> None:
        self._testing = False
        self.btn_test.setEnabled(True)
        self.test_status.setText(f"连接成功：{str(reply)[:80]}")

    def _on_test_err(self, exc: object) -> None:
        self._testing = False
        self.btn_test.setEnabled(True)
        self.test_status.setText(f"连接失败：{exc}")
