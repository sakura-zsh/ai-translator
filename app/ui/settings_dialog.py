"""Settings dialog: profiles, translation defaults, theme & hotkeys."""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.config.schema import (
    HISTORY_LIMIT_MAX,
    AppConfig,
    HotkeysConfig,
    LlmProfile,
    TranslationConfig,
    UiConfig,
)
from app.core.languages import TARGET_LANGUAGES
from app.core.llm_client import LlmClient
from app.core.presets import SCENE_PRESETS, format_glossary, parse_glossary
from app.core.providers import PROVIDER_TEMPLATES, ProviderTemplate, get_template
from app.ui.widgets import ModelSelector
from app.workers.tasks import FunctionWorker


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        # +40px headroom: the two ModelSelector status lines are always
        # reserved now so fetching models never squeezes the combo boxes;
        # +50px more for the scene/glossary rows on the translation tab.
        self.setMinimumSize(640, 620)
        self._config = deepcopy(config)
        self._pool = QThreadPool.globalInstance()
        self._testing = False

        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self._build_profiles_tab()
        self._build_translation_tab()
        self._build_appearance_tab()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._reload_profile_list(select_id=self._config.active_profile_id)

    # ── Profiles tab ──────────────────────────────────────────────
    def _build_profiles_tab(self) -> None:
        page = QWidget()
        layout = QHBoxLayout(page)

        left = QVBoxLayout()
        self.profile_list = QListWidget()
        self.profile_list.currentItemChanged.connect(self._on_profile_selected)
        left.addWidget(self.profile_list)

        row = QHBoxLayout()
        self.btn_add = QPushButton("新增")
        self.btn_add.clicked.connect(self._add_profile)
        self.btn_dup = QPushButton("复制")
        self.btn_dup.clicked.connect(self._dup_profile)
        self.btn_del = QPushButton("删除")
        self.btn_del.setObjectName("dangerButton")
        self.btn_del.clicked.connect(self._del_profile)
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_dup)
        row.addWidget(self.btn_del)
        left.addLayout(row)
        layout.addLayout(left, 1)

        form_box = QGroupBox("配置详情")
        form = QFormLayout(form_box)
        self.f_name = QLineEdit()
        self.f_base_url = QLineEdit()
        self.f_base_url.setPlaceholderText("https://api.openai.com/v1")
        self.f_api_key = QLineEdit()
        self.f_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.f_api_key.setPlaceholderText("sk-…")
        self.f_protocol = QComboBox()
        self.f_protocol.addItem("Chat Completions（/chat/completions）", "chat_completions")
        self.f_protocol.addItem("Responses（/responses）", "responses")
        self.f_protocol.setToolTip(
            "Chat Completions：经典 OpenAI 兼容接口。\n"
            "Responses：OpenAI Responses API，部分中转站仅支持此协议。"
        )
        self.f_template = QComboBox()
        self.f_template.addItem("自定义（不更改）", "")
        for t in PROVIDER_TEMPLATES:
            self.f_template.addItem(t.name, t.id)
        self.f_template.setToolTip(
            "选择常用服务商可自动填入地址与推荐模型；随后用「获取模型」拉取真实列表。"
        )
        self.model_text = ModelSelector(lambda: self._profile_for_fetch())
        self.model_vision = ModelSelector(lambda: self._profile_for_fetch())
        self.f_temperature = QDoubleSpinBox()
        self.f_temperature.setRange(0.0, 2.0)
        self.f_temperature.setSingleStep(0.1)
        self.f_temperature.setDecimals(2)
        self.f_timeout = QDoubleSpinBox()
        self.f_timeout.setRange(5.0, 600.0)
        self.f_timeout.setSuffix(" s")
        self.f_max_tokens = QSpinBox()
        self.f_max_tokens.setRange(64, 128000)
        self.f_max_tokens.setSingleStep(256)

        form.addRow("服务商模板", self.f_template)
        form.addRow("名称", self.f_name)
        form.addRow("Base URL", self.f_base_url)
        form.addRow("API Key", self.f_api_key)
        form.addRow("API 协议", self.f_protocol)
        form.addRow("文本模型", self.model_text)
        form.addRow("视觉模型", self.model_vision)
        form.addRow("Temperature", self.f_temperature)
        form.addRow("超时", self.f_timeout)
        form.addRow("Max tokens", self.f_max_tokens)

        for w in (
            self.f_name,
            self.f_base_url,
            self.f_api_key,
        ):
            w.editingFinished.connect(self._apply_form_to_current)
        self.f_protocol.currentIndexChanged.connect(lambda _i: self._apply_form_to_current())
        self.model_text.combo.currentTextChanged.connect(lambda _t: self._apply_form_to_current())
        self.model_vision.combo.currentTextChanged.connect(lambda _t: self._apply_form_to_current())
        self.f_temperature.valueChanged.connect(lambda _v: self._apply_form_to_current())
        self.f_timeout.valueChanged.connect(lambda _v: self._apply_form_to_current())
        self.f_max_tokens.valueChanged.connect(lambda _v: self._apply_form_to_current())
        self.f_template.currentIndexChanged.connect(self._on_template_selected)

        test_row = QHBoxLayout()
        self.btn_test = QPushButton("测试连接")
        self.btn_test.setObjectName("primaryButton")
        self.btn_test.clicked.connect(self._test_connection)
        self.test_status = QLabel("")
        self.test_status.setObjectName("hintLabel")
        self.test_status.setWordWrap(True)
        test_row.addWidget(self.btn_test)
        test_row.addWidget(self.test_status, 1)
        form.addRow(test_row)

        layout.addWidget(form_box, 2)
        self.tabs.addTab(page, "LLM 配置")

    def _reload_profile_list(self, select_id: str | None = None) -> None:
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        select_row = 0
        for i, p in enumerate(self._config.profiles):
            item = QListWidgetItem(p.name)
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            self.profile_list.addItem(item)
            if select_id and p.id == select_id:
                select_row = i
        self.profile_list.blockSignals(False)
        if self.profile_list.count():
            self.profile_list.setCurrentRow(select_row)

    def _current_profile(self) -> LlmProfile | None:
        item = self.profile_list.currentItem()
        if not item:
            return None
        pid = item.data(Qt.ItemDataRole.UserRole)
        return self._config.get_profile(pid)

    def _on_profile_selected(
        self, current: QListWidgetItem | None, prev: QListWidgetItem | None
    ) -> None:
        if prev is not None:
            # currentItem already changed — write form fields back to previous profile
            prev_profile = self._config.get_profile(prev.data(Qt.ItemDataRole.UserRole))
            if prev_profile is not None:
                prev_profile.name = self.f_name.text().strip() or "未命名"
                prev_profile.base_url = self.f_base_url.text().strip() or prev_profile.base_url
                prev_profile.api_key = self.f_api_key.text()
                prev_profile.api_protocol = (
                    self.f_protocol.currentData() or "chat_completions"
                )
                prev_profile.model = (
                    self.model_text.current_text() or prev_profile.model
                )
                prev_profile.vision_model = (
                    self.model_vision.current_text() or prev_profile.model
                )
                prev_profile.temperature = float(self.f_temperature.value())
                prev_profile.timeout_s = float(self.f_timeout.value())
                prev_profile.max_tokens = int(self.f_max_tokens.value())
                prev.setText(prev_profile.name)
        if current is None:
            return
        self._fill_form(self._config.get_profile(current.data(Qt.ItemDataRole.UserRole)))

    def _fill_form(self, profile: LlmProfile | None) -> None:
        if profile is None:
            return
        widgets = [
            self.f_name,
            self.f_base_url,
            self.f_api_key,
            self.f_protocol,
            self.f_temperature,
            self.f_timeout,
            self.f_max_tokens,
        ]
        for w in widgets:
            w.blockSignals(True)
        for sel in (self.model_text, self.model_vision):
            sel.combo.blockSignals(True)
        self.f_name.setText(profile.name)
        self.f_base_url.setText(profile.base_url)
        self.f_api_key.setText(profile.api_key)
        idx = self.f_protocol.findData(profile.api_protocol or "chat_completions")
        self.f_protocol.setCurrentIndex(max(0, idx))
        self.model_text.set_current_text(profile.model)
        self.model_vision.set_current_text(profile.vision_model)
        self.f_temperature.setValue(profile.temperature)
        self.f_timeout.setValue(profile.timeout_s)
        self.f_max_tokens.setValue(profile.max_tokens)
        for sel in (self.model_text, self.model_vision):
            sel.combo.blockSignals(False)
        for w in widgets:
            w.blockSignals(False)
        self._reset_template_combo()
        self.test_status.setText("")

    def _apply_form_to_current(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        profile.name = self.f_name.text().strip() or "未命名"
        profile.base_url = self.f_base_url.text().strip() or profile.base_url
        profile.api_key = self.f_api_key.text()
        profile.api_protocol = self.f_protocol.currentData() or "chat_completions"
        profile.model = self.model_text.current_text() or profile.model
        profile.vision_model = self.model_vision.current_text() or profile.model
        profile.temperature = float(self.f_temperature.value())
        profile.timeout_s = float(self.f_timeout.value())
        profile.max_tokens = int(self.f_max_tokens.value())
        item = self.profile_list.currentItem()
        if item:
            item.setText(profile.name)

    def _profile_for_fetch(self) -> LlmProfile | None:
        """Current profile with unsaved form edits applied (for /models)."""
        self._apply_form_to_current()
        return self._current_profile()

    def _reset_template_combo(self) -> None:
        self.f_template.blockSignals(True)
        self.f_template.setCurrentIndex(0)
        self.f_template.blockSignals(False)

    def _on_template_selected(self, _index: int) -> None:
        template_id = self.f_template.currentData()
        template: ProviderTemplate | None = (
            get_template(template_id) if template_id else None
        )
        if template is None:
            return
        self._apply_form_to_current()
        profile = self._current_profile()
        if profile is None:
            return
        profile.base_url = template.base_url
        profile.api_protocol = template.api_protocol  # type: ignore[assignment]
        profile.name = template.name
        if template.text_model:
            profile.model = template.text_model
        if template.vision_model:
            profile.vision_model = template.vision_model
        self._fill_form(profile)
        item = self.profile_list.currentItem()
        if item:
            item.setText(profile.name)

    def _add_profile(self) -> None:
        self._apply_form_to_current()
        profile = LlmProfile(id=uuid4().hex[:12], name=f"配置 {len(self._config.profiles) + 1}")
        self._config.profiles.append(profile)
        self._reload_profile_list(select_id=profile.id)

    def _dup_profile(self) -> None:
        self._apply_form_to_current()
        current = self._current_profile()
        if current is None:
            return
        clone = deepcopy(current)
        clone.id = uuid4().hex[:12]
        clone.name = f"{current.name} 副本"
        self._config.profiles.append(clone)
        self._reload_profile_list(select_id=clone.id)

    def _del_profile(self) -> None:
        current = self._current_profile()
        if current is None:
            return
        if len(self._config.profiles) <= 1:
            QMessageBox.information(self, "无法删除", "至少保留一个 LLM 配置。")
            return
        if (
            QMessageBox.question(self, "删除配置", f"删除「{current.name}」？")
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._config.remove_profile(current.id)
        self._reload_profile_list(select_id=self._config.active_profile_id)

    def _test_connection(self) -> None:
        if self._testing:
            return
        self._apply_form_to_current()
        profile = self._current_profile()
        if profile is None:
            return
        self._testing = True
        self.btn_test.setEnabled(False)
        self.test_status.setText("测试中…")

        def work() -> str:
            return LlmClient(profile).test_connection()

        worker = FunctionWorker(work)
        worker.signals.finished.connect(self._on_test_ok)
        worker.signals.error.connect(self._on_test_err)
        self._pool.start(worker)

    def _on_test_ok(self, reply: object) -> None:
        self._testing = False
        self.btn_test.setEnabled(True)
        text = str(reply)[:80]
        self.test_status.setText(f"成功：{text}")

    def _on_test_err(self, exc: object) -> None:
        self._testing = False
        self.btn_test.setEnabled(True)
        self.test_status.setText(f"失败：{exc}")

    # ── Translation tab ───────────────────────────────────────────
    def _build_translation_tab(self) -> None:
        page = QWidget()
        form = QFormLayout(page)

        self.t_target = QComboBox()
        for code, name in TARGET_LANGUAGES:
            self.t_target.addItem(name, code)
        idx = self.t_target.findData(self._config.translation.target_lang)
        self.t_target.setCurrentIndex(max(0, idx))

        self.t_image_mode = QComboBox()
        self.t_image_mode.addItem("OCR（本地识别 + 文本模型）", "ocr")
        self.t_image_mode.addItem("Vision（视觉模型直接翻译）", "vision")
        idx = self.t_image_mode.findData(self._config.translation.image_mode)
        self.t_image_mode.setCurrentIndex(max(0, idx))

        self.t_ocr_langs = QLineEdit(self._config.translation.ocr_langs)
        self.t_ocr_langs.setPlaceholderText("eng+chi_sim")

        self.t_tesseract = QLineEdit(self._config.translation.tesseract_path)
        self.t_tesseract.setPlaceholderText("tesseract（留空用 PATH）")
        self.t_tesseract.setToolTip("OCR 引擎 tesseract 可执行文件的路径，修改后立即生效")

        self.t_autocopy = QCheckBox("翻译完成后自动复制结果到剪贴板")
        self.t_autocopy.setChecked(self._config.translation.auto_copy_result)

        self.t_scene = QComboBox()
        for preset in SCENE_PRESETS:
            self.t_scene.addItem(preset.label, preset.id)
        idx = self.t_scene.findData(self._config.translation.scene)
        self.t_scene.setCurrentIndex(max(0, idx))
        self.t_scene.setToolTip("主窗口工具栏也可随时切换；场景预设与下方补充提示词叠加生效")

        self.t_prompt = QPlainTextEdit()
        self.t_prompt.setPlaceholderText(
            "可选：补充提示词，例如「使用正式书面语」「保留术语英文原文」"
        )
        self.t_prompt.setPlainText(self._config.translation.supplementary_prompt)
        # Kept compact: it sits right under the scene combo as a secondary input.
        self.t_prompt.setMinimumHeight(56)
        self.t_prompt.setMaximumHeight(96)

        self.t_glossary = QPlainTextEdit()
        self.t_glossary.setPlaceholderText(
            "每行一条术语，分隔符支持 = 、→、-> 或 Tab，最多 100 条：\n"
            "GPU = 显卡\n"
            "LLM = 大语言模型"
        )
        self.t_glossary.setPlainText(format_glossary(self._config.translation.glossary))
        self.t_glossary.setMinimumHeight(72)
        self.t_glossary.setMaximumHeight(120)

        form.addRow("默认目标语言", self.t_target)
        form.addRow("图片翻译模式", self.t_image_mode)
        form.addRow("OCR 语言包", self.t_ocr_langs)
        form.addRow("Tesseract 路径", self.t_tesseract)
        form.addRow("", self.t_autocopy)
        form.addRow("翻译场景", self.t_scene)
        form.addRow("补充提示词", self.t_prompt)
        form.addRow("术语表", self.t_glossary)

        hint = QLabel(
            "翻译时场景预设在前、个人补充提示词在后，两者叠加生效；"
            "术语表中的术语将严格按指定译法渲染。主窗口工具栏也可随时切换场景。"
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        form.addRow(hint)

        self.tabs.addTab(page, "翻译")

    # ── Appearance / hotkeys ──────────────────────────────────────
    def _build_appearance_tab(self) -> None:
        page = QWidget()
        form = QFormLayout(page)

        self.u_theme = QComboBox()
        self.u_theme.addItem("深色", "dark")
        self.u_theme.addItem("浅色", "light")
        idx = self.u_theme.findData(self._config.ui.theme)
        self.u_theme.setCurrentIndex(max(0, idx))
        form.addRow("主题", self.u_theme)

        self.u_tray = QCheckBox("关闭时最小化到托盘")
        self.u_tray.setChecked(self._config.ui.close_to_tray)
        self.u_tray.setToolTip("需要系统支持托盘；不支持托盘的桌面（部分 Wayland）会自动忽略")
        form.addRow("", self.u_tray)

        self.u_history = QSpinBox()
        self.u_history.setRange(0, HISTORY_LIMIT_MAX)
        self.u_history.setSuffix(" 条")
        self.u_history.setValue(self._config.history_limit)
        self.u_history.setToolTip("历史面板保留的记录条数（0 为不记录历史）")
        form.addRow("历史条数", self.u_history)

        hk = self._config.ui.hotkeys
        self.h_translate = QLineEdit(hk.translate)
        self.h_screenshot = QLineEdit(hk.screenshot)
        self.h_extract = QLineEdit(hk.extract_text)
        self.h_paste = QLineEdit(hk.paste_image)
        self.h_swap = QLineEdit(hk.swap_langs)
        self.h_copy = QLineEdit(hk.copy_result)

        form.addRow("翻译", self.h_translate)
        form.addRow("截图翻译", self.h_screenshot)
        form.addRow("提取文字", self.h_extract)
        form.addRow("粘贴图片", self.h_paste)
        form.addRow("交换语种", self.h_swap)
        form.addRow("复制结果", self.h_copy)

        hint = QLabel("快捷键仅在应用窗口内生效（Qt 格式，如 Ctrl+Return、Ctrl+Shift+S）。")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        form.addRow(hint)

        self.tabs.addTab(page, "外观与快捷键")

    # ── Accept ────────────────────────────────────────────────────
    def _on_accept(self) -> None:
        self._apply_form_to_current()

        item = self.profile_list.currentItem()
        if item:
            self._config.active_profile_id = item.data(Qt.ItemDataRole.UserRole)

        old_t = self._config.translation
        self._config.translation = TranslationConfig(
            source_lang=old_t.source_lang,
            target_lang=self.t_target.currentData() or "zh",
            image_mode=self.t_image_mode.currentData() or "ocr",
            supplementary_prompt=self.t_prompt.toPlainText().strip(),
            ocr_langs=self.t_ocr_langs.text().strip() or "eng+chi_sim",
            auto_copy_result=self.t_autocopy.isChecked(),
            scene=self.t_scene.currentData() or old_t.scene,
            glossary=parse_glossary(self.t_glossary.toPlainText()),
            tesseract_path=self.t_tesseract.text().strip(),
        )
        old_ui = self._config.ui
        self._config.ui = UiConfig(
            theme=self.u_theme.currentData() or "dark",
            window_width=old_ui.window_width,
            window_height=old_ui.window_height,
            hotkeys=HotkeysConfig(
                translate=self.h_translate.text().strip() or "Ctrl+Return",
                screenshot=self.h_screenshot.text().strip() or "Ctrl+Shift+S",
                paste_image=self.h_paste.text().strip() or "Ctrl+Shift+V",
                swap_langs=self.h_swap.text().strip() or "Ctrl+Shift+X",
                copy_result=self.h_copy.text().strip() or "Ctrl+Shift+C",
                extract_text=self.h_extract.text().strip() or "Ctrl+Shift+T",
            ),
            # Fields without a control on this dialog: preserve as-is.
            window_maximized=old_ui.window_maximized,
            splitter_sizes=old_ui.splitter_sizes,
            close_to_tray=self.u_tray.isChecked(),
        )
        # History limit lives on AppConfig (not UiConfig); shrinking it also
        # truncates the in-memory history so the panel matches immediately.
        limit = int(self.u_history.value())
        self._config.history_limit = limit
        if len(self._config.history) > limit:
            self._config.history = self._config.history[:limit]
        self.accept()

    def result_config(self) -> AppConfig:
        return self._config
