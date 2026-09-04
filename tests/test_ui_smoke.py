"""Offscreen UI smoke tests (§3.6).

Key assertions ported from the earlier manual smoke runs; everything runs
against a session-scoped offscreen QApplication. QMessageBox is stubbed so
no test can ever block on a modal dialog.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.config.schema import AppConfig  # noqa: E402
from app.config.store import ConfigStore  # noqa: E402
from app.core.providers import PROVIDER_TEMPLATES  # noqa: E402
from app.ui.first_run_dialog import FirstRunDialog  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.settings_dialog import SettingsDialog  # noqa: E402
from app.ui.widgets import ModelSelector  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


@pytest.fixture(autouse=True)
def _no_modal_boxes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never block the offscreen test run on a modal message box."""
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)


@pytest.fixture()
def window(qapp: QApplication, tmp_path: Path):  # type: ignore[no-untyped-def]
    store = ConfigStore(tmp_path / "config.json")
    win = MainWindow(store, store.load())
    win.show()
    yield win
    win._force_quit = True
    win.close()


# ① ModelSelector status text must never change row heights
def test_model_selector_status_height_stable(qapp: QApplication) -> None:
    sel = ModelSelector(lambda: AppConfig().get_active_profile())
    sel.show()
    qapp.processEvents()
    h_before = (sel.status.height(), sel.combo.height())
    sel._set_status("获取失败：超长错误信息" * 12)
    qapp.processEvents()
    assert (sel.status.height(), sel.combo.height()) == h_before


# ② Reasoning-model reminder toggles with the selected model name
def test_model_selector_reasoning_hint(qapp: QApplication) -> None:
    sel = ModelSelector(lambda: AppConfig().get_active_profile())
    sel.set_current_text("deepseek-r1:32b")
    assert "推理模型" in sel.status.text()
    sel.set_current_text("gpt-4o-mini")
    assert sel.status.text() == ""


# ③ Provider template fills base_url / model into the current profile
def test_template_selection_fills_profile(qapp: QApplication) -> None:
    config = AppConfig()
    config.profiles[0].base_url = "https://custom.example/v1"
    dlg = SettingsDialog(config)
    template = next(t for t in PROVIDER_TEMPLATES if t.base_url and t.text_model)
    idx = dlg.f_template.findData(template.id)
    assert idx > 0
    dlg.f_template.setCurrentIndex(idx)
    profile = dlg._config.get_active_profile()
    assert profile.base_url == template.base_url
    assert profile.model == template.text_model


# ④ Profile switch on the toolbar persists to disk
def test_profile_switch_persists(
    window: MainWindow, tmp_path: Path
) -> None:
    from app.config.schema import LlmProfile

    window.config.profiles.append(LlmProfile(id="p2", name="第二配置"))
    window._reload_profiles()
    idx = window.profile_combo.findData("p2")
    assert idx >= 0
    window.profile_combo.setCurrentIndex(idx)
    assert window.config.active_profile_id == "p2"
    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded.active_profile_id == "p2"


# ⑤ Extract-text handler fills source + auto-copies (Qt clipboard fallback)
def test_extract_ok_fills_and_copies(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Disable wl-copy so _copy_text_to_clipboard falls back to Qt clipboard.
    monkeypatch.setattr("shutil.which", lambda name: None)
    clipboard = QApplication.clipboard()
    assert clipboard is not None
    clipboard.clear()

    window._on_extract_ok("  提取的文字  ")
    assert window.source_edit.toPlainText() == "提取的文字"
    assert clipboard.text() == "提取的文字"
    assert "已提取" in window.status_label.text()


# ⑥ First-run wizard constructs
def test_first_run_dialog_builds(qapp: QApplication) -> None:
    dlg = FirstRunDialog(AppConfig().get_active_profile())
    assert dlg.result_profile() is not None
    dlg.show()
    qapp.processEvents()
    dlg.close()
