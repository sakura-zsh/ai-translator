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

from app.config.schema import AppConfig  # noqa: E402
from app.config.store import ConfigStore  # noqa: E402
from app.core.presets import (  # noqa: E402
    effective_extra_prompt,
    format_glossary,
    get_scene,
    parse_glossary,
)
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.settings_dialog import SettingsDialog  # noqa: E402


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
