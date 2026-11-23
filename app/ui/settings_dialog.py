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
    TTS_RATE_MAX,
    TTS_RATE_MIN,
    AppConfig,
    HotkeysConfig,
    JevConfig,
    LlmProfile,
    TranslationConfig,
    TtsConfig,
    UiConfig,
)
from app.core.jev_client import JevClient
from app.core.languages import TARGET_LANGUAGES
from app.core.llm_client import LlmClient
from app.core.presets import (
    AUTO_SCENE_ID,
    AUTO_SCENE_LABEL,
    SCENE_PRESETS,
    all_scene_presets,
    format_glossary,
    parse_glossary,
)
from app.core.providers import PROVIDER_TEMPLATES, ProviderTemplate, get_template
from app.core.tts import TextToSpeech, TtsPlayer
from app.ui.model_catalog import ModelCatalogDialog
from app.ui.model_editor import CandidateModelEditor, sentinel_rows
from app.workers.tasks import TaskRunner

# Curated edge-tts voices; arbitrary voice ids can be pasted into the combo.
TTS_VOICE_CHOICES: list[tuple[str, str]] = [
    ("晓晓 · 中文女声", "zh-CN-XiaoxiaoNeural"),
    ("云希 · 中文男声", "zh-CN-YunxiNeural"),
    ("云健 · 中文男声", "zh-CN-YunjianNeural"),
    ("Aria · 英语女声（美）", "en-US-AriaNeural"),
    ("Jenny · 英语女声（美）", "en-US-JennyNeural"),
    ("Guy · 英语男声（美）", "en-US-GuyNeural"),
    ("Sonia · 英语女声（英）", "en-GB-SoniaNeural"),
]

_TTS_PREVIEW_TEXT = "Hello, this is a voice preview. 你好，这是语音试听。"


class SceneManageDialog(QDialog):
    """Add / edit / delete custom translation scenes (builtins read-only)."""

    def __init__(
        self,
        custom_scenes: list[dict[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("管理翻译场景")
        self.setMinimumSize(460, 420)
        self._custom: list[dict[str, str]] = [dict(c) for c in custom_scenes]
        self._builtin_ids = {p.id for p in SCENE_PRESETS}
        self._loading = False

        root = QVBoxLayout(self)

        self.scene_list = QListWidget()
        self.scene_list.currentItemChanged.connect(self._on_selected)
        root.addWidget(self.scene_list, 2)

        form = QFormLayout()
        self.f_label = QLineEdit()
        self.f_prompt = QPlainTextEdit()
        self.f_prompt.setPlaceholderText("此场景生效时附加到系统提示之后的指令（可留空）")
        self.f_prompt.setMinimumHeight(110)
        form.addRow("名称", self.f_label)
        form.addRow("提示词", self.f_prompt)
        root.addLayout(form, 2)

        self.builtin_hint = QLabel("内置场景不可修改；自定义场景可在此增删改。")
        self.builtin_hint.setObjectName("hintLabel")
        root.addWidget(self.builtin_hint)

        row = QHBoxLayout()
        self.btn_add = QPushButton("新增")
        self.btn_add.clicked.connect(self._add_scene)
        self.btn_del = QPushButton("删除")
        self.btn_del.setObjectName("dangerButton")
        self.btn_del.clicked.connect(self._del_scene)
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_del)
        row.addStretch(1)
        root.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.f_label.editingFinished.connect(self._apply_editors)
        self.f_prompt.textChanged.connect(self._apply_editors)

        self._reload_list()
        if self.scene_list.count():
            self.scene_list.setCurrentRow(0)

    # The builtin ids come straight from presets; derive without hardcoding.
    def _reload_list(self, select_key: str | None = None) -> None:
        self._loading = True
        self.scene_list.clear()
        for p in all_scene_presets(self._custom):
            item = QListWidgetItem(p.label + ("　（内置）" if p.id in self._builtin_ids else ""))
            item.setData(
                Qt.ItemDataRole.UserRole,
                ("builtin", p.id) if p.id in self._builtin_ids else ("custom", p.id),
            )
            self.scene_list.addItem(item)
            if select_key and p.id == select_key:
                self.scene_list.setCurrentItem(item)
        self._loading = False

    def _selected(self) -> tuple[str, str] | None:
        item = self.scene_list.currentItem()
        if item is None:
            return None
        kind, sid = item.data(Qt.ItemDataRole.UserRole)
        return kind, sid

    def _on_selected(self, current, _prev) -> None:
        if current is None:
            self.f_label.setEnabled(False)
            self.f_prompt.setEnabled(False)
            self.f_label.clear()
            self.f_prompt.clear()
            return
        kind, sid = current.data(Qt.ItemDataRole.UserRole)
        is_builtin = kind == "builtin"
        self.f_label.setEnabled(not is_builtin)
        self.f_prompt.setEnabled(not is_builtin)
        self.btn_del.setEnabled(not is_builtin)
        self._loading = True
        scene = next((p for p in all_scene_presets(self._custom) if p.id == sid), None)
        self.f_label.setText(scene.label if scene else "")
        self.f_prompt.setPlainText(scene.prompt if scene else "")
        self._loading = False

    def _apply_editors(self) -> None:
        if self._loading:
            return
        sel = self._selected()
        if sel is None or sel[0] != "custom":
            return
        _, sid = sel
        for entry in self._custom:
            if entry["id"] == sid:
                entry["label"] = self.f_label.text().strip() or entry["label"]
                entry["prompt"] = self.f_prompt.toPlainText()
                break
        item = self.scene_list.currentItem()
        if item is not None:
            item.setText(self.f_label.text().strip() or item.text())

    def _add_scene(self) -> None:
        entry = {
            "id": uuid4().hex[:12],
            "label": f"自定义场景 {len(self._custom) + 1}",
            "prompt": "",
        }
        self._custom.append(entry)
        self._reload_list(select_key=entry["id"])
        self.scene_list.setFocus()

    def _del_scene(self) -> None:
        sel = self._selected()
        if sel is None or sel[0] != "custom":
            return
        _, sid = sel
        self._custom = [c for c in self._custom if c["id"] != sid]
        self._reload_list()
        if self.scene_list.count():
            self.scene_list.setCurrentRow(0)

    def _on_accept(self) -> None:
        self._apply_editors()
        self.accept()

    def result_scenes(self) -> list[dict[str, str]]:
        return [dict(c) for c in self._custom]


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        # +40px headroom: the candidate list and the status hints underneath
        # would otherwise squeeze the form rows; +50px more for the
        # scene/glossary rows on the translation tab; +40px more for the TTS
        # rows (voice/rate/auto/preview).
        self.setMinimumSize(680, 720)
        self._config = deepcopy(config)
        self._pool = QThreadPool.globalInstance()
        self._runner = TaskRunner(self._pool, parent=self)
        self._tts_runner = TaskRunner(self._pool, parent=self)  # preview synth
        self._tts = TextToSpeech()
        self._tts_player = TtsPlayer(self)
        self._testing = False

        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self._build_profiles_tab()
        self._build_translation_tab()
        self._build_jev_tab()
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
        # FixAtCurrentSize keeps tall widgets (the candidate list) at their
        # sizeHint instead of letting the form squeeze every row to fit.
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
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
            "选择常用服务商可自动填入地址与推荐模型；随后用「从服务商列表…」挑候选。"
        )
        # Candidate list (hand-curated per provider) + vision fallback.
        self.model_editor = CandidateModelEditor()
        self.model_editor.changed.connect(self._apply_form_to_current)
        self.model_editor.list_changed.connect(self._refresh_vision_rows)
        self.model_editor.catalog_requested.connect(self._open_model_catalog)
        self.vision_combo = QComboBox()
        self.vision_combo.setToolTip(
            "大多数模型已原生支持图片，默认「跟随当前模型」。\n"
            "只有当服务商的文本模型不支持图片时，才在这里指定专用视觉模型。"
        )
        self.vision_combo.currentIndexChanged.connect(
            lambda _i: self._on_vision_changed()
        )
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
        form.addRow("候选模型", self.model_editor)  # tall: see sizeHint
        form.addRow("视觉模型", self.vision_combo)
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

    # ── public helpers (used by the bottom-bar picker) ────────────
    def select_profile(self, profile_id: str) -> None:
        """Focus a provider by id; silently keeps the current one if gone."""
        for row in range(self.profile_list.count()):
            item = self.profile_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == profile_id:
                self.profile_list.setCurrentRow(row)
                return

    def show_tab(self, index: int) -> None:
        if 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)

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
                prev_profile.temperature = float(self.f_temperature.value())
                prev_profile.timeout_s = float(self.f_timeout.value())
                prev_profile.max_tokens = int(self.f_max_tokens.value())
                prev.setText(prev_profile.name)
        if current is None:
            return
        self._fill_form(self._config.get_profile(current.data(Qt.ItemDataRole.UserRole)))

    def _fill_form(self, profile: LlmProfile | None) -> None:
        if profile is None:
            self.model_editor.set_profile(None)
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
        self.f_name.setText(profile.name)
        self.f_base_url.setText(profile.base_url)
        self.f_api_key.setText(profile.api_key)
        idx = self.f_protocol.findData(profile.api_protocol or "chat_completions")
        self.f_protocol.setCurrentIndex(max(0, idx))
        self.f_temperature.setValue(profile.temperature)
        self.f_timeout.setValue(profile.timeout_s)
        self.f_max_tokens.setValue(profile.max_tokens)
        for w in widgets:
            w.blockSignals(False)
        self.model_editor.set_profile(profile)
        self._reload_vision_combo(profile)
        self._reset_template_combo()
        self.test_status.setText("")

    def _reload_vision_combo(self, profile: LlmProfile) -> None:
        combo = self.vision_combo
        combo.blockSignals(True)
        combo.clear()
        for value, label in sentinel_rows(profile):
            combo.addItem(label, value)
        idx = combo.findData(profile.vision_model or "")
        if idx < 0:
            # A vision model that is no longer a candidate: keep it visible
            # instead of silently dropping the user's choice.
            combo.addItem(profile.vision_model, profile.vision_model)
            idx = combo.count() - 1
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _refresh_vision_rows(self) -> None:
        """Candidate list changed → the vision combo must follow."""
        profile = self._current_profile()
        if profile is not None:
            self._reload_vision_combo(profile)

    def _on_vision_changed(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        profile.vision_model = str(self.vision_combo.currentData() or "")
        self.model_editor.reload()
        item = self.profile_list.currentItem()
        if item is not None:
            item.setText(profile.name)

    def _open_model_catalog(self) -> None:
        """Pull /models and let the user tick the ones to keep."""
        self._apply_form_to_current()
        profile = self._current_profile()
        if profile is None:
            return
        dlg = ModelCatalogDialog(
            self._profile_for_fetch, list(profile.models), self
        )
        dlg.set_models(list(profile.model_options))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dlg.checked_models()
        self.model_editor.add_models(chosen)

    def _apply_form_to_current(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        profile.name = self.f_name.text().strip() or "未命名"
        profile.base_url = self.f_base_url.text().strip() or profile.base_url
        profile.api_key = self.f_api_key.text()
        profile.api_protocol = self.f_protocol.currentData() or "chat_completions"
        profile.temperature = float(self.f_temperature.value())
        profile.timeout_s = float(self.f_timeout.value())
        profile.max_tokens = int(self.f_max_tokens.value())
        # ``models`` / ``model`` / ``vision_model`` are mutated in place by
        # CandidateModelEditor and the vision combo, which re-sanitises via
        # LlmProfile helpers on every add/remove.
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
            profile.add_model(template.text_model)
            profile.model = template.text_model
        if template.vision_model and template.vision_model != template.text_model:
            profile.add_model(template.vision_model)
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

        self._runner.run(work, self._on_test_ok, self._on_test_err)

    def _on_test_ok(self, reply: object) -> None:
        self._testing = False
        self.btn_test.setEnabled(True)
        text = str(reply)[:80]
        self.test_status.setText(f"成功：{text}")

    def _on_test_err(self, exc: object) -> None:
        self._testing = False
        self.btn_test.setEnabled(True)
        self.test_status.setText(f"失败：{exc}")

    # ── TTS preview ───────────────────────────────────────────────
    def _preview_tts(self) -> None:
        """Synthesize + play a sample with the currently selected voice."""
        if getattr(self, "_tts_busy", False):
            return
        voice = self.t_voice.currentData() or self.t_voice.currentText().strip()
        if not voice:
            return
        rate = self.t_tts_rate.value()
        self._tts_busy = True
        self.btn_tts_preview.setEnabled(False)
        self.btn_tts_preview.setText("合成中…")
        self._tts_runner.run(
            lambda: self._tts.speak(_TTS_PREVIEW_TEXT, voice, rate),
            on_ok=self._on_tts_preview_ok,
            on_err=self._on_tts_preview_err,
        )

    def _on_tts_preview_ok(self, path: object) -> None:
        self._tts_busy = False
        self.btn_tts_preview.setEnabled(True)
        self.btn_tts_preview.setText("试听")
        self._tts_player.play(path)  # type: ignore[arg-type]

    def _on_tts_preview_err(self, exc: object) -> None:
        self._tts_busy = False
        self.btn_tts_preview.setEnabled(True)
        self.btn_tts_preview.setText("试听")
        self.test_status.setText(f"语音试听失败：{exc}")

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
        self._custom_scenes = deepcopy(self._config.translation.custom_scenes)
        self._reload_scene_combo()
        self.t_scene.setToolTip("主窗口工具栏也可随时切换；场景预设与下方补充提示词叠加生效")
        self.btn_scene_manage = QPushButton("管理…")
        self.btn_scene_manage.setToolTip("新增 / 修改 / 删除自定义翻译场景")
        self.btn_scene_manage.clicked.connect(self._manage_scenes)
        scene_row = QHBoxLayout()
        scene_row.addWidget(self.t_scene, 1)
        scene_row.addWidget(self.btn_scene_manage)

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

        # ── Text-to-speech (edge-tts) ─────────────────────────────
        self.t_voice = QComboBox()
        self.t_voice.setEditable(True)
        for label, voice_id in TTS_VOICE_CHOICES:
            self.t_voice.addItem(label, voice_id)
        current_voice = self._config.tts.voice
        idx = self.t_voice.findData(current_voice)
        if idx < 0:  # a custom voice id from config → keep it visible
            self.t_voice.addItem(current_voice, current_voice)
            idx = self.t_voice.count() - 1
        self.t_voice.setCurrentIndex(idx)
        self.t_voice.setToolTip(
            "edge-tts 音色；可手动粘贴任意音色名（如 en-GB-SoniaNeural）"
        )

        self.t_tts_rate = QSpinBox()
        self.t_tts_rate.setRange(TTS_RATE_MIN, TTS_RATE_MAX)
        self.t_tts_rate.setSuffix("%")
        self.t_tts_rate.setValue(self._config.tts.rate)
        self.t_tts_rate.setToolTip("语速偏移：负值慢速（学习单词时常用 -50）")

        self.t_tts_auto = QCheckBox("翻译完成后自动朗读译文")
        self.t_tts_auto.setChecked(self._config.tts.auto_pronounce)

        self.btn_tts_preview = QPushButton("试听")
        self.btn_tts_preview.setToolTip("用当前音色和语速合成一句示例并播放（需联网）")
        self.btn_tts_preview.clicked.connect(self._preview_tts)
        preview_row = QHBoxLayout()
        preview_row.addWidget(self.btn_tts_preview)
        preview_row.addStretch(1)

        form.addRow("发音音色", self.t_voice)
        form.addRow("语速偏移", self.t_tts_rate)
        form.addRow("", self.t_tts_auto)
        form.addRow("语音试听", preview_row)

        form.addRow("默认目标语言", self.t_target)
        form.addRow("图片翻译模式", self.t_image_mode)
        form.addRow("OCR 语言包", self.t_ocr_langs)
        form.addRow("Tesseract 路径", self.t_tesseract)
        form.addRow("", self.t_autocopy)
        form.addRow("翻译场景", scene_row)
        form.addRow("补充提示词", self.t_prompt)
        form.addRow("术语表", self.t_glossary)

        tts_hint = QLabel("朗读使用微软 Edge 语音（edge-tts），合成时需联网；音频会缓存到本地。")
        tts_hint.setObjectName("hintLabel")
        tts_hint.setWordWrap(True)
        form.addRow(tts_hint)

        hint = QLabel(
            "翻译时场景预设在前、个人补充提示词在后，两者叠加生效；"
            "术语表中的术语将严格按指定译法渲染。主窗口工具栏也可随时切换场景。"
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        form.addRow(hint)

        self.tabs.addTab(page, "翻译")

    # ── Scene management ─────────────────────────────────────────
    def _reload_scene_combo(self, select_id: str | None = None) -> None:
        self.t_scene.blockSignals(True)
        self.t_scene.clear()
        for preset in all_scene_presets(self._custom_scenes):
            self.t_scene.addItem(preset.label, preset.id)
        if self._jev_scene_auto_available():
            self.t_scene.addItem(AUTO_SCENE_LABEL, AUTO_SCENE_ID)
        key = select_id or self._config.translation.scene
        idx = self.t_scene.findData(key)
        self.t_scene.setCurrentIndex(max(0, idx))  # -1 → general
        self.t_scene.blockSignals(False)

    def _manage_scenes(self) -> None:
        dlg = SceneManageDialog(self._custom_scenes, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._custom_scenes = dlg.result_scenes()
        self._refresh_scene_auto_entry()

    # ── Jev (System One decision model) ───────────────────────────
    def _build_jev_tab(self) -> None:
        page = QWidget()
        form = QFormLayout(page)
        j = self._config.jev

        self.j_enabled = QCheckBox("启用 Jev 判断")
        self.j_enabled.setChecked(j.enabled)
        self.j_enabled.setToolTip(
            "Jev 是 TypeSafe 的 System One 决策模型：它不生成文本，只接收一段 state\n"
            "和若干带类型的问题，返回带置信概率的结构化判定。\n"
            "本应用用它做场景路由、语种检测与译文质量评分；属于可选增强，\n"
            "不可用时自动退回原有翻译流程。"
        )
        form.addRow("", self.j_enabled)

        self.j_base_url = QLineEdit(j.base_url)
        self.j_base_url.setPlaceholderText("https://api.typesafe.ai")
        self.j_base_url.setToolTip(
            "官方或中转站地址均可：填到 /v1、填完整地址、或直接粘贴 /v1/systemone 都能识别。\n"
            "留空则不启用。"
        )
        form.addRow("Base URL", self.j_base_url)

        self.j_api_key = QLineEdit(j.api_key)
        self.j_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.j_api_key.setPlaceholderText("jv_live_… 或中转站 Key")
        form.addRow("API Key", self.j_api_key)

        self.j_model = QLineEdit(j.model)
        self.j_model.setPlaceholderText("jev-latest")
        self.j_model.setToolTip("如 jev-latest、jev-1.13.0；中转站的模型名以其文档为准。")
        form.addRow("模型", self.j_model)

        self.j_protocol = QComboBox()
        self.j_protocol.addItem("自动探测（原生优先，失败回退 OpenAI 兼容）", "auto")
        self.j_protocol.addItem("原生 /v1/systemone（state + questions）", "native")
        self.j_protocol.addItem("OpenAI 兼容 /chat/completions（要 JSON）", "openai")
        idx = self.j_protocol.findData(j.api_protocol)
        self.j_protocol.setCurrentIndex(max(0, idx))
        self.j_protocol.setToolTip(
            "不确定就留「自动探测」：会按候选端点依次尝试，命中后缓存，\n"
            "两种请求体与两种响应结构都能兼容。"
        )
        form.addRow("接口协议", self.j_protocol)

        self.j_timeout = QDoubleSpinBox()
        self.j_timeout.setRange(5.0, 600.0)
        self.j_timeout.setSuffix(" s")
        self.j_timeout.setValue(float(j.timeout_s))
        form.addRow("超时", self.j_timeout)

        feature_box = QGroupBox("功能开关")
        feature_form = QFormLayout(feature_box)

        self.j_route = QCheckBox("场景自动路由")
        self.j_route.setChecked(j.route_scene)
        self.j_route.setToolTip(
            "翻译前由 Jev 判断这段文本该用哪个场景。\n"
            "需在主窗口把「场景」切换为「自动判断（Jev）」才会触发。"
        )
        feature_form.addRow(self.j_route)

        self.j_detect = QCheckBox("语种自动检测")
        self.j_detect.setChecked(j.detect_language)
        self.j_detect.setToolTip("源语言为「自动检测」时，由 Jev 判定源语言后再翻译。")
        feature_form.addRow(self.j_detect)

        self.j_score = QCheckBox("译文质量评分")
        self.j_score.setChecked(j.score_quality)
        self.j_score.setToolTip("翻译完成后由 Jev 给译文打分（0–1），结果显示在状态栏。")
        feature_form.addRow(self.j_score)

        self.j_threshold = QDoubleSpinBox()
        self.j_threshold.setRange(0.0, 1.0)
        self.j_threshold.setSingleStep(0.05)
        self.j_threshold.setDecimals(2)
        self.j_threshold.setValue(float(j.quality_threshold))
        self.j_threshold.setToolTip("低于该分数视为不达标（需开启「译文质量评分」）")
        feature_form.addRow("质量阈值", self.j_threshold)

        self.j_retry = QCheckBox("低于阈值时自动重译一次")
        self.j_retry.setChecked(j.retry_on_low_quality)
        feature_form.addRow(self.j_retry)

        form.addRow(feature_box)

        self.btn_jev_test = QPushButton("测试连接")
        self.btn_jev_test.setToolTip("用当前填写的内容发一个最小判定请求，验证地址、Key 与协议")
        self.btn_jev_test.clicked.connect(self._test_jev)
        self.j_status = QLabel("")
        self.j_status.setObjectName("hintLabel")
        self.j_status.setWordWrap(True)
        test_row = QHBoxLayout()
        test_row.addWidget(self.btn_jev_test)
        test_row.addWidget(self.j_status, 1)
        form.addRow("连通性", test_row)

        hint = QLabel(
            "Jev 不会替你做翻译——它只做判断。三项功能彼此独立，可只开其中一项。\n"
            "任何 Jev 调用失败都不会中断翻译，只会记录日志并退回默认行为。"
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        form.addRow(hint)

        # Keep the main-window scene combo semantics identical to this dialog.
        # The initial rebuild selects the *configured* scene (the combo was
        # first filled before this tab existed, when "auto" was not yet
        # offered); later toggles preserve whatever the user has selected.
        self.j_enabled.toggled.connect(self._refresh_scene_auto_entry)
        self.j_route.toggled.connect(self._refresh_scene_auto_entry)
        self._reload_scene_combo()

        self.tabs.addTab(page, "Jev 判断")

    def _jev_config_from_form(self) -> JevConfig:
        return JevConfig(
            enabled=self.j_enabled.isChecked(),
            base_url=self.j_base_url.text().strip(),
            api_key=self.j_api_key.text().strip(),
            model=self.j_model.text().strip() or "jev-latest",
            api_protocol=self.j_protocol.currentData() or "auto",
            timeout_s=float(self.j_timeout.value()),
            route_scene=self.j_route.isChecked(),
            detect_language=self.j_detect.isChecked(),
            score_quality=self.j_score.isChecked(),
            quality_threshold=float(self.j_threshold.value()),
            retry_on_low_quality=self.j_retry.isChecked(),
        )

    def _jev_scene_auto_available(self) -> bool:
        """Mirror the main window: offer 「自动判断」 only when it can work."""
        enabled = getattr(self, "j_enabled", None)
        route = getattr(self, "j_route", None)
        return bool(
            enabled is not None
            and route is not None
            and enabled.isChecked()
            and route.isChecked()
        )

    def _refresh_scene_auto_entry(self) -> None:
        current = self.t_scene.currentData()
        self._reload_scene_combo(select_id=current or None)

    def _test_jev(self) -> None:
        cfg = self._jev_config_from_form()
        if not cfg.base_url:
            self.j_status.setText("请先填写 Base URL")
            return
        self.btn_jev_test.setEnabled(False)
        self.j_status.setText("测试中…")
        client = JevClient(cfg)

        def work() -> str:
            return client.test_connection()

        self._runner.run(work, self._on_jev_test_ok, self._on_jev_test_err)

    def _on_jev_test_ok(self, message: object) -> None:
        self.btn_jev_test.setEnabled(True)
        self.j_status.setText(str(message))

    def _on_jev_test_err(self, exc: object) -> None:
        self.btn_jev_test.setEnabled(True)
        self.j_status.setText(f"失败：{exc}")

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
        self.h_summon = QLineEdit(hk.summon)
        self.h_summon.setToolTip(
            "系统级热键，任何界面下按下即唤起主窗口。仅 Windows 生效；\n"
            "Linux 请在桌面环境/合成器中把快捷键绑定到启动命令（重复启动会唤起已运行实例）。"
        )

        form.addRow("翻译", self.h_translate)
        form.addRow("截图翻译", self.h_screenshot)
        form.addRow("提取文字", self.h_extract)
        form.addRow("粘贴图片", self.h_paste)
        form.addRow("交换语种", self.h_swap)
        form.addRow("复制结果", self.h_copy)
        form.addRow("全局呼出", self.h_summon)

        hint = QLabel(
            "应用内快捷键仅在窗口聚焦时生效（Qt 格式，如 Ctrl+Return）。\n"
            "「全局呼出」为系统级热键，仅 Windows 生效；格式如 Ctrl+Alt+T，"
            "至少含一个修饰键，支持字母/数字/F1–F24。"
        )
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
            custom_scenes=self._custom_scenes,
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
                summon=self.h_summon.text().strip() or "Ctrl+Alt+T",
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

        old_tts = self._config.tts
        voice = self.t_voice.currentData() or self.t_voice.currentText().strip()
        self._config.tts = TtsConfig(
            voice=voice or old_tts.voice,
            rate=self.t_tts_rate.value(),
            auto_pronounce=self.t_tts_auto.isChecked(),
        )

        self._config.jev = self._jev_config_from_form()
        self.accept()

    def result_config(self) -> AppConfig:
        return self._config
