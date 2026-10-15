"""Tests for §3.2: main-window config integration.

Covers scene combo wiring, translator rebuild, window-state persistence,
settings-dialog field preservation, and close-to-tray degradation.
Requires PySide6 (skipped automatically when unavailable).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config.schema import AppConfig, sanitize_custom_scenes  # noqa: E402
from app.config.store import ConfigStore  # noqa: E402
from app.core.hotkey_win import parse_hotkey  # noqa: E402
from app.core.presets import (  # noqa: E402
    all_scene_presets,
    effective_extra_prompt,
    format_glossary,
    get_scene,
    parse_glossary,
)
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.settings_dialog import SceneManageDialog, SettingsDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


@pytest.fixture()
def window(qapp: QApplication, tmp_path: Path):  # type: ignore[no-untyped-def]
    store = ConfigStore(tmp_path / "config.json")
    config = store.load()
    win = MainWindow(store, config)
    yield win
    win._force_quit = True
    win.close()


# ── Scene presets ──────────────────────────────────────────────────
def test_effective_extra_prompt_combines_scene_and_personal() -> None:
    cfg = AppConfig().translation
    cfg.scene = "technical"
    cfg.supplementary_prompt = "保持简洁"
    extra = effective_extra_prompt(cfg)
    assert "代码" in extra  # technical preset text
    assert extra.endswith("保持简洁")  # personal extra appended last


def test_effective_extra_prompt_general_no_scene_text() -> None:
    cfg = AppConfig().translation
    cfg.scene = "general"
    cfg.supplementary_prompt = ""
    assert effective_extra_prompt(cfg) == ""


def test_get_scene_unknown_falls_back_to_general() -> None:
    assert get_scene("no-such-id").id == "general"


# ── Scene combo wiring ─────────────────────────────────────────────
def test_scene_combo_reflects_config(window: MainWindow) -> None:
    window.config.translation.scene = "academic"
    window._apply_translation_defaults()
    assert window.scene_combo.currentData() == "academic"


def test_scene_change_updates_config_and_persists(
    window: MainWindow, tmp_path: Path
) -> None:
    idx = window.scene_combo.findData("formal")
    assert idx >= 0
    window.scene_combo.setCurrentIndex(idx)
    assert window.config.translation.scene == "formal"
    # Persisted to disk, not just in memory.
    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded.translation.scene == "formal"


def test_scene_combo_disabled_while_busy(window: MainWindow) -> None:
    window._set_busy(True)
    assert not window.scene_combo.isEnabled()
    window._set_busy(False)
    assert window.scene_combo.isEnabled()


# ── Translator rebuild ─────────────────────────────────────────────
def test_reload_config_rebuilds_translator_with_tesseract_path(
    window: MainWindow,
) -> None:
    window.config.translation.tesseract_path = "/opt/custom-tesseract"
    window.reload_config(window.config)
    assert window.translator.ocr.tesseract_bin == "/opt/custom-tesseract"


def test_default_translator_uses_tesseract_from_path(
    window: MainWindow,
) -> None:
    assert window.translator.ocr.tesseract_bin == "tesseract"


# ── Window state persistence ───────────────────────────────────────
def test_persist_writes_window_state(window: MainWindow) -> None:
    window.show()
    QApplication.processEvents()
    window._persist()
    assert window.config.ui.window_maximized == window.isMaximized()
    assert isinstance(window.config.ui.splitter_sizes, list)


def test_restore_splitter_applies_saved_sizes(window: MainWindow) -> None:
    window.show()
    QApplication.processEvents()
    window.config.ui.splitter_sizes = [300, 100]
    window._restore_splitter()
    sizes = window.splitter.sizes()
    # Qt redistributes to the widget's real width, so check the proportion
    # survived rather than exact pixel sums.
    assert sizes[0] > sizes[1] > 0


def test_restore_splitter_ignores_invalid_sizes(window: MainWindow) -> None:
    window.config.ui.splitter_sizes = [0, 0]
    window._restore_splitter()  # must not shrink panes to zero / raise


# ── Glossary serialization ─────────────────────────────────────────
def test_parse_glossary_supports_all_separators() -> None:
    text = "GPU = 显卡\nLLM → 大语言模型\nAPI->接口\tIO\nCPU\t处理器"
    assert parse_glossary(text) == {
        "GPU": "显卡",
        "LLM": "大语言模型",
        "API": "接口\tIO",  # earliest separator (->) wins; inner tab kept
        "CPU": "处理器",
    }


def test_parse_glossary_skips_invalid_lines_and_caps() -> None:
    assert parse_glossary("没有分隔符的行\n\n = 空 \nOK = 这个可以") == {"OK": "这个可以"}
    many = "\n".join(f"t{i} = v{i}" for i in range(150))
    assert len(parse_glossary(many)) == 100


def test_glossary_format_parse_roundtrip() -> None:
    glossary = {"GPU": "显卡", "transformer": "变换器"}
    assert parse_glossary(format_glossary(glossary)) == glossary
    assert format_glossary({}) == ""
    assert format_glossary(None) == ""


# ── Settings dialog: glossary / tesseract / tray / history ─────────
def test_settings_glossary_and_tesseract_roundtrip(qapp: QApplication) -> None:
    config = AppConfig()
    config.translation.glossary = {"GPU": "显卡"}
    config.translation.tesseract_path = "/usr/local/bin/tesseract"

    dlg = SettingsDialog(config)
    assert "GPU = 显卡" in dlg.t_glossary.toPlainText()
    dlg.t_glossary.setPlainText("GPU = 显卡\nLLM → 大语言模型")
    dlg.t_tesseract.setText(" /opt/bin/tesseract ")
    dlg._on_accept()
    result = dlg.result_config()
    assert result.translation.glossary == {"GPU": "显卡", "LLM": "大语言模型"}
    assert result.translation.tesseract_path == "/opt/bin/tesseract"


def test_settings_close_to_tray_control(qapp: QApplication) -> None:
    config = AppConfig()
    config.ui.close_to_tray = True
    dlg = SettingsDialog(config)
    assert dlg.u_tray.isChecked()
    dlg.u_tray.setChecked(False)
    dlg._on_accept()
    assert dlg.result_config().ui.close_to_tray is False


def test_settings_history_limit_truncates_history(qapp: QApplication) -> None:
    config = AppConfig()
    for i in range(5):
        config.push_history(
            source_lang="auto",
            target_lang="zh",
            mode="text",
            source_text=f"src {i}",
            result_text=f"dst {i}",
        )
    dlg = SettingsDialog(config)
    assert dlg.u_history.value() == config.history_limit
    dlg.u_history.setValue(3)
    dlg._on_accept()
    result = dlg.result_config()
    assert result.history_limit == 3
    assert len(result.history) == 3
    # Newest entries survive the truncation.
    assert result.history[0].source_text == "src 4"


def test_settings_accept_preserves_fields_without_controls(
    qapp: QApplication,
) -> None:
    """Fields with controls roundtrip via the widgets; fields without
    controls (window state, splitter) must be preserved verbatim."""
    config = AppConfig()
    config.translation.scene = "casual"
    config.translation.glossary = {"GPU": "显卡"}
    config.translation.tesseract_path = "/usr/bin/tesseract"
    config.ui.close_to_tray = False
    config.ui.window_maximized = True
    config.ui.splitter_sizes = [250, 250]

    dlg = SettingsDialog(config)
    dlg._on_accept()
    result = dlg.result_config()

    # Via controls (initialized from config).
    assert result.translation.scene == "casual"
    assert result.translation.glossary == {"GPU": "显卡"}
    assert result.translation.tesseract_path == "/usr/bin/tesseract"
    assert result.ui.close_to_tray is False
    # Preserved without controls.
    assert result.ui.window_maximized is True
    assert result.ui.splitter_sizes == [250, 250]


# ── Settings dialog: scene control on the translation tab ─────────
def test_settings_scene_control_roundtrip(qapp: QApplication) -> None:
    config = AppConfig()
    config.translation.scene = "casual"

    dlg = SettingsDialog(config)
    assert dlg.t_scene.currentData() == "casual"

    idx = dlg.t_scene.findData("formal")
    assert idx >= 0
    dlg.t_scene.setCurrentIndex(idx)
    dlg._on_accept()
    assert dlg.result_config().translation.scene == "formal"


def test_settings_prompt_box_stays_compact(qapp: QApplication) -> None:
    dlg = SettingsDialog(AppConfig())
    assert dlg.t_prompt.minimumHeight() <= 64
    assert dlg.t_prompt.maximumHeight() <= 96


# ── Single-instance summon ─────────────────────────────────────────
def test_summon_shows_hidden_window(window: MainWindow) -> None:
    window.show()
    QApplication.processEvents()
    window.hide()
    assert not window.isVisible()
    window.summon()
    assert window.isVisible()


def test_summon_keeps_visible_window_visible(window: MainWindow) -> None:
    window.show()
    QApplication.processEvents()
    assert window.isVisible()
    window.summon()  # must not toggle/hide
    assert window.isVisible()


# ── History panel: search filter + per-card copy (§3.4) ────────────
def _push_entries(config: AppConfig, n: int) -> None:
    for i in range(n):
        config.push_history(
            source_lang="auto",
            target_lang="zh",
            mode="text",
            source_text=f"hello world {i}",
            result_text=f"你好世界 {i}",
        )


def test_history_search_filters_cards(window: MainWindow) -> None:
    panel = window.history_panel
    _push_entries(window.config, 3)
    panel.set_entries(window.config.history)
    assert panel.list_layout.count() - 1 == 3  # minus trailing stretch

    panel.search_edit.setText("world 1")
    # Filtering is live: 1 matching card remains.
    assert panel.list_layout.count() - 1 == 1

    # Matches the result text too, case-insensitively.
    panel.search_edit.setText("你好世界")
    assert panel.list_layout.count() - 1 == 3

    # No match at all → empty hint, no cards.
    panel.search_edit.setText("no such needle")
    assert panel.list_layout.count() - 1 == 0
    assert panel.empty_label.isVisibleTo(panel) or not panel.scroll.isVisible()

    # Clearing the box restores the full list.
    panel.search_edit.setText("")
    assert panel.list_layout.count() - 1 == 3


def test_history_card_copy_button_emits_entry_id(window: MainWindow) -> None:
    panel = window.history_panel
    _push_entries(window.config, 2)
    panel.set_entries(window.config.history)

    copied: list[str] = []
    activated: list[str] = []
    panel.copy_requested.connect(copied.append)
    card = panel.list_layout.itemAt(0).widget()
    card.activated.connect(activated.append)
    card.btn_copy.click()

    assert copied == [card.entry_id]
    # The button click must not bubble up to card activation.
    assert activated == []


def test_main_window_history_copy_uses_clipboard(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    _push_entries(window.config, 1)
    entry = window.config.history[0]

    copied: list[str] = []
    monkeypatch.setattr(
        window, "_copy_text_to_clipboard", lambda text: copied.append(text) or True
    )
    window._on_history_copy(entry.id)
    assert copied == [entry.result_text]
    assert window.status_label.text().startswith("已复制")

    window._on_history_copy("no-such-id")
    assert window.status_label.text() == "历史记录不存在"


# ── Custom scenes (§ builtin + user-defined) ──────────────────────
_CUSTOM = [{"id": "c1", "label": "古风文言", "prompt": "用文言文翻译"}]


def test_parse_hotkey_sequences() -> None:
    mods, vk = parse_hotkey("Ctrl+Alt+T")  # type: ignore[misc]
    assert vk == ord("T")
    assert mods & 0x2 and mods & 0x1  # control | alt
    # F-keys and Win modifier parse; MOD_NOREPEAT (0x4000) always set.
    mods, vk = parse_hotkey("Win+F5")  # type: ignore[misc]
    assert vk == 0x70 + 4 and mods & 0x8 and mods & 0x4000
    # Invalid: missing modifier / unknown key / two keys / empty.
    assert parse_hotkey("T") is None
    assert parse_hotkey("Ctrl+Alt+按") is None
    assert parse_hotkey("Ctrl+T+F5") is None
    assert parse_hotkey("") is None


def test_hotkey_native_filter_inert_off_windows(qapp: QApplication) -> None:
    import sys as _sys

    from app.core.hotkey_win import HotkeyNativeFilter, install_native_filter

    called: list[object] = []
    flt = HotkeyNativeFilter(called.append)
    # Off-Windows (and Windows non-HOTKEY/null-pointer messages) must pass
    # through untouched — no summon, no swallow.
    for etype, msg in (("windows_generic_MSG", 0), ("unix_generic_MSG", 0)):
        assert flt.nativeEventFilter(etype, msg) == (False, 0)
    assert called == []

    if _sys.platform == "win32":
        # On Windows the filter is real and must be kept alive by the caller.
        installed = install_native_filter(called.append)
        assert isinstance(installed, HotkeyNativeFilter)
    else:
        # install_native_filter is a no-op off-Windows.
        assert install_native_filter(called.append) is None


# ── TTS speak buttons ───────────────────────────────────────────────
def test_speak_buttons_dispatch_to_their_own_pane(window: MainWindow) -> None:
    """Regression: both buttons used to read the result pane (string
    mismatch between the button label and _speak's dispatch key)."""
    window.source_edit.setPlainText("source text")
    window.result_edit.setPlainText("result text")

    captured: list[tuple[str, bool]] = []

    def fake_speak(what: str, slow: bool = False) -> None:
        captured.append((what, slow))

    window._speak = fake_speak  # type: ignore[method-assign]

    # Icon must be present (emoji rendered as tofu on some Windows fonts).
    assert not window.btn_speak_src.icon().isNull()
    assert not window.btn_speak_result.icon().isNull()

    window.btn_speak_src.click()
    window.btn_speak_result.click()
    window.btn_speak_src.customContextMenuRequested.emit(window.btn_speak_src.rect().center())

    assert captured == [("原文", False), ("译文", False), ("原文", True)]


def test_speak_unknown_target_is_a_noop(window: MainWindow) -> None:
    # Unknown keys must not silently fall through to the result pane.
    window._speak("朗读原文")  # legacy mislabeled key
    assert window.status_label.text() == "就绪"


def test_tts_playback_state_resets_status(window: MainWindow) -> None:
    window._set_status("朗读中…")
    window._on_tts_state("playing")
    assert window.status_label.text() == "朗读中…"
    window._on_tts_state("stopped")
    assert window.status_label.text() == "就绪"
    window._set_status("朗读中…")
    window._on_tts_state("error: device lost")
    assert "播放失败" in window.status_label.text()


# ── Version bump detection ──────────────────────────────────────────
def test_version_bump_detected_on_startup(window: MainWindow) -> None:
    from app import __version__

    window.config.last_run_version = "0.2.0"
    window._check_version_bump()
    assert "已更新" in window.status_label.text()
    assert __version__ in window.status_label.text()
    assert window.config.last_run_version == __version__


def test_version_unchanged_keeps_ready_status(window: MainWindow) -> None:
    from app import __version__

    window.config.last_run_version = __version__
    window._check_version_bump()
    assert window.status_label.text() == "就绪"


def test_version_first_run_stores_silently(window: MainWindow) -> None:
    window.config.last_run_version = ""
    window._check_version_bump()
    # First run records the version without an upgrade message.
    assert window.status_label.text() == "就绪"
    assert window.config.last_run_version != ""


def test_speak_icon_follows_theme(window: MainWindow) -> None:
    """Regression: standard style icon was white-on-white in light theme."""
    window.config.ui.theme = "dark"
    dark = window._make_speaker_icon(window._speak_icon_color())
    window.config.ui.theme = "light"
    window._refresh_speak_icons()
    light = window.btn_speak_src.icon()

    body_dark = dark.pixmap(64, 64).toImage().pixelColor(16, 32)
    body_light = light.pixmap(64, 64).toImage().pixelColor(16, 32)
    assert body_dark.isValid() and body_light.isValid()
    # Glyph colors must differ — same color as the background is invisible.
    assert body_dark != body_light


def test_custom_scenes_sanitized() -> None:
    raw = [
        {"id": " ok ", "label": "名称", "prompt": "p"},  # id whitespace-stripped
        {"id": "dup", "label": "A"},
        {"id": "dup", "label": "B"},  # duplicate dropped (first wins)
        {"id": "", "label": "无 id"},  # dropped
        {"id": "x"},  # missing label → dropped
        "junk",  # not a dict → dropped
    ]
    out = sanitize_custom_scenes(raw)
    assert [c["id"] for c in out] == ["ok", "dup"]
    assert out[0]["prompt"] == "p"
    assert sanitize_custom_scenes(None) == []
    assert sanitize_custom_scenes("nope") == []
    # Cap at 20.
    many = [{"id": f"s{i}", "label": f"L{i}"} for i in range(30)]
    assert len(sanitize_custom_scenes(many)) == 20


def test_custom_scene_lookup_and_extra_prompt() -> None:
    assert len(all_scene_presets(_CUSTOM)) == 6
    scene = get_scene("c1", _CUSTOM)
    assert scene.label == "古风文言"
    # Builtin wins on id conflict; unknown → general fallback.
    assert get_scene("academic", _CUSTOM).label == "学术论文"
    assert get_scene("no-such", _CUSTOM).id == "general"

    cfg = AppConfig().translation
    cfg.scene = "c1"
    cfg.custom_scenes = _CUSTOM
    cfg.supplementary_prompt = "额外要求"
    extra = effective_extra_prompt(cfg)
    assert "用文言文翻译" in extra
    assert extra.endswith("额外要求")


def test_toolbar_combo_shows_custom_scenes(window: MainWindow) -> None:
    window.config.translation.custom_scenes = _CUSTOM
    window.config.translation.scene = "c1"
    window._apply_translation_defaults()
    assert window.scene_combo.count() == 6
    assert window.scene_combo.currentData() == "c1"


def test_custom_scene_change_persists(window: MainWindow, tmp_path: Path) -> None:
    window.config.translation.custom_scenes = _CUSTOM
    window._apply_translation_defaults()
    idx = window.scene_combo.findData("c1")
    assert idx >= 0
    window.scene_combo.setCurrentIndex(idx)
    assert window.config.translation.scene == "c1"
    assert "古风文言" in window.status_label.text()
    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded.translation.scene == "c1"


def test_settings_scene_manage_and_roundtrip(qapp: QApplication) -> None:
    manager = SceneManageDialog([], None)
    manager._add_scene()
    assert len(manager.result_scenes()) == 1
    entry_id = manager.result_scenes()[0]["id"]
    # Select the new custom scene (last row) and edit it via the editors.
    item = manager.scene_list.item(manager.scene_list.count() - 1)
    manager.scene_list.setCurrentItem(item)
    manager.f_label.setText("我的场景")
    manager.f_prompt.setPlainText("使用轻小说语气")
    manager._apply_editors()
    scenes = manager.result_scenes()
    assert scenes[0]["label"] == "我的场景"
    assert scenes[0]["prompt"] == "使用轻小说语气"
    assert scenes[0]["id"] == entry_id

    # Builtin rows are read-only.
    dlg = SceneManageDialog([], None)
    dlg.scene_list.setCurrentRow(0)
    assert not dlg.f_label.isEnabled()
    assert not dlg.btn_del.isEnabled()

    # Settings dialog roundtrips custom scenes into the config.
    config = AppConfig()
    config.translation.custom_scenes = _CUSTOM
    dlg2 = SettingsDialog(config)
    assert dlg2.t_scene.count() == 6
    idx = dlg2.t_scene.findData("c1")
    dlg2.t_scene.setCurrentIndex(idx)
    dlg2._on_accept()
    result = dlg2.result_config()
    assert result.translation.scene == "c1"
    assert result.translation.custom_scenes == _CUSTOM


def test_settings_summon_hotkey_roundtrip(qapp: QApplication) -> None:
    config = AppConfig()
    dlg = SettingsDialog(config)
    assert dlg.h_summon.text() == "Ctrl+Alt+T"
    dlg.h_summon.setText("Win+Shift+D")
    dlg._on_accept()
    assert dlg.result_config().ui.hotkeys.summon == "Win+Shift+D"
    # Old configs without the field fall back to the default.
    assert AppConfig.from_dict({"ui": {"hotkeys": {}}}).ui.hotkeys.summon == "Ctrl+Alt+T"


# ── Force quit from tray (window hidden) ───────────────────────────
def test_quit_on_hidden_window_still_persists(
    window: MainWindow, tmp_path: Path
) -> None:
    """Tray「退出」with the window parked in the tray must run closeEvent
    (persist state) even though no visible window is being closed."""
    window.show()
    QApplication.processEvents()
    window.hide()  # close-to-tray style hidden state
    window._quit()
    assert window._force_quit is True
    assert not window.isVisible()
    # closeEvent must have run despite the window being hidden.
    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded.ui.window_width == window.config.ui.window_width


# ── Close-to-tray degradation ──────────────────────────────────────
def test_close_without_tray_saves_and_quits(
    window: MainWindow, tmp_path: Path
) -> None:
    window.config.ui.close_to_tray = True
    window._tray = None  # offscreen: no system tray
    window.close()
    assert not window.isVisible() or window._force_quit
    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded.ui.window_width == window.config.ui.window_width


# ── Jev integration ────────────────────────────────────────────────
def _enable_jev(window: MainWindow, **overrides: object) -> None:
    jev = window.config.jev
    jev.enabled = True
    jev.base_url = "https://relay.test/v1"
    for key, value in overrides.items():
        setattr(jev, key, value)


def _stub_jev(monkeypatch: pytest.MonkeyPatch, handler) -> None:  # type: ignore[no-untyped-def]
    from app.core import jev_client as module

    def fake_decide(self, state, questions, **kwargs):  # type: ignore[no-untyped-def]
        return handler(questions)

    monkeypatch.setattr(module.JevClient, "decide", fake_decide)


def _stub_translate(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    from app.core.translator import TranslateResult

    calls: list[dict] = []

    def fake_translate(text, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"text": text, **kwargs})
        return TranslateResult(text=f"译文{len(calls)}", model="demo")

    monkeypatch.setattr(window.translator, "translate_text", fake_translate)
    return calls


def test_scene_combo_offers_auto_only_when_jev_routing_is_on(
    window: MainWindow,
) -> None:
    assert window.scene_combo.findData("auto") == -1

    _enable_jev(window)
    window.reload_config(window.config)
    assert window.scene_combo.findData("auto") >= 0

    # Turning routing off removes the entry again.
    window.config.jev.route_scene = False
    window.reload_config(window.config)
    assert window.scene_combo.findData("auto") == -1


def test_jev_client_requires_enabled_and_configured(window: MainWindow) -> None:
    assert window._jev_client() is None  # disabled by default

    _enable_jev(window, base_url="")
    assert window._jev_client() is None  # enabled but no address

    _enable_jev(window)
    assert window._jev_client() is not None


def test_run_translation_applies_jev_language_scene_and_score(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_jev(window, score_quality=True)
    window.config.translation.scene = "auto"
    window.config.translation.custom_scenes = []

    def handler(questions: dict) -> dict:
        if "source_language" in questions:
            return {"source_language": {"choice": "ja"}}
        if "scene" in questions:
            return {"scene": {"choice": "technical"}}
        if "quality" in questions:
            return {"quality": {"score": 3.0}}  # 3/4 → 0.75
        return {}

    _stub_jev(monkeypatch, handler)
    calls = _stub_translate(window, monkeypatch)

    payload = window._run_translation(
        "こんにちは",
        source="auto",
        target="zh",
        profile=window.config.get_active_profile(),
        glossary=None,
    )

    assert calls[0]["source_lang"] == "ja"  # Jev resolved the language
    assert "代码" in calls[0]["supplementary_prompt"]  # technical preset applied
    assert payload["score"] == pytest.approx(0.75)
    assert any("语种" in note for note in payload["notes"])
    assert any("场景" in note for note in payload["notes"])
    assert len(calls) == 1  # no retry: the score is above the default threshold


def test_low_quality_triggers_exactly_one_retry(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_jev(window, score_quality=True, retry_on_low_quality=True, quality_threshold=0.9)
    window.config.translation.scene = "auto"

    def handler(questions: dict) -> dict:
        if "scene" in questions:
            return {"scene": {"choice": "general"}}
        if "quality" in questions:
            return {"quality": {"score": 0.0}}  # always "bad"
        return {}

    _stub_jev(monkeypatch, handler)
    calls = _stub_translate(window, monkeypatch)

    payload = window._run_translation(
        "text",
        source="en",
        target="zh",
        profile=window.config.get_active_profile(),
        glossary=None,
    )

    assert len(calls) == 2  # translated, then retried once
    assert "重新翻译" in calls[1]["supplementary_prompt"]
    assert any("重译" in note for note in payload["notes"])


def test_no_retry_when_score_is_acceptable(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_jev(window, score_quality=True, retry_on_low_quality=True, quality_threshold=0.5)

    def handler(questions: dict) -> dict:
        return {"quality": {"score": 4.0}}  # 1.0 → above 0.5

    _stub_jev(monkeypatch, handler)
    calls = _stub_translate(window, monkeypatch)

    window._run_translation(
        "text",
        source="en",
        target="zh",
        profile=window.config.get_active_profile(),
        glossary=None,
    )
    assert len(calls) == 1


def test_jev_failure_never_breaks_translation(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.llm_client import ApiError

    _enable_jev(window, score_quality=True)
    window.config.translation.scene = "auto"

    def boom(self, state, questions, **kwargs):  # type: ignore[no-untyped-def]
        raise ApiError("relay down")

    from app.core import jev_client as module

    monkeypatch.setattr(module.JevClient, "decide", boom)
    calls = _stub_translate(window, monkeypatch)

    payload = window._run_translation(
        "text",
        source="auto",
        target="zh",
        profile=window.config.get_active_profile(),
        glossary=None,
    )

    assert len(calls) == 1
    assert calls[0]["source_lang"] == "auto"  # unchanged on failure
    assert payload["score"] is None
    assert payload["notes"] == []


def test_disabled_jev_translates_without_any_calls(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import jev_client as module

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("Jev must not be called when disabled")

    monkeypatch.setattr(module.JevClient, "decide", boom)
    calls = _stub_translate(window, monkeypatch)

    window._run_translation(
        "text",
        source="auto",
        target="zh",
        profile=window.config.get_active_profile(),
        glossary=None,
    )
    assert len(calls) == 1


# ── Jev settings tab ───────────────────────────────────────────────
def test_settings_dialog_persists_jev_config(qapp: QApplication) -> None:
    dlg = SettingsDialog(AppConfig())
    assert dlg.tabs.tabText(dlg.tabs.count() - 2) == "Jev 判断"

    dlg.j_enabled.setChecked(True)
    dlg.j_base_url.setText("https://relay.test/v1/systemone")
    dlg.j_api_key.setText("jv_live_x")
    dlg.j_model.setText("jev-1.13.0")
    dlg.j_protocol.setCurrentIndex(dlg.j_protocol.findData("native"))
    dlg.j_detect.setChecked(False)
    dlg.j_score.setChecked(True)
    dlg.j_threshold.setValue(0.7)
    dlg.j_retry.setChecked(True)
    dlg._on_accept()

    jev = dlg.result_config().jev
    assert jev.enabled is True
    assert jev.base_url == "https://relay.test/v1/systemone"
    assert jev.api_key == "jv_live_x"
    assert jev.model == "jev-1.13.0"
    assert jev.api_protocol == "native"
    assert jev.detect_language is False
    assert jev.score_quality is True
    assert jev.quality_threshold == pytest.approx(0.7)
    assert jev.retry_on_low_quality is True


def test_settings_base_url_is_blank_by_default(qapp: QApplication) -> None:
    dlg = SettingsDialog(AppConfig())
    assert dlg.j_base_url.text() == ""
    assert "typesafe" in dlg.j_base_url.placeholderText().lower()


def test_settings_scene_auto_entry_follows_jev_switch(qapp: QApplication) -> None:
    dlg = SettingsDialog(AppConfig())
    assert dlg.t_scene.findData("auto") == -1

    dlg.j_enabled.setChecked(True)
    dlg.j_route.setChecked(True)
    assert dlg.t_scene.findData("auto") >= 0

    dlg.t_scene.setCurrentIndex(dlg.t_scene.findData("auto"))
    dlg._on_accept()
    assert dlg.result_config().translation.scene == "auto"

    # Disabling Jev drops the entry and falls back to a real preset.
    dlg2 = SettingsDialog(dlg.result_config())
    assert dlg2.t_scene.currentData() == "auto"
    dlg2.j_enabled.setChecked(False)
    assert dlg2.t_scene.findData("auto") == -1
    assert dlg2.t_scene.currentData() == "general"


def test_settings_jev_test_requires_base_url(qapp: QApplication) -> None:
    dlg = SettingsDialog(AppConfig())
    dlg.j_enabled.setChecked(True)
    dlg.j_base_url.setText("")
    dlg._test_jev()
    assert "Base URL" in dlg.j_status.text()


def test_jev_config_survives_settings_roundtrip(qapp: QApplication) -> None:
    """Opening settings twice must not silently reset the Jev block."""
    cfg = AppConfig()
    cfg.jev.enabled = True
    cfg.jev.base_url = "https://relay.test/v1"
    cfg.jev.model = "jev-1.13.0"
    cfg.jev.score_quality = True

    dlg = SettingsDialog(cfg)
    assert dlg.j_enabled.isChecked() is True
    assert dlg.j_base_url.text() == "https://relay.test/v1"
    assert dlg.j_model.text() == "jev-1.13.0"
    dlg._on_accept()

    jev = dlg.result_config().jev
    assert jev.enabled is True
    assert jev.base_url == "https://relay.test/v1"
    assert jev.model == "jev-1.13.0"
    assert jev.score_quality is True
