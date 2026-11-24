"""Candidate model lists, provider switching, and reasoning effort (§4.1).

Covers three layers: config sanitisation and migration from the old
single-model schema, the wire format for both protocols (including a relay
that rejects the effort parameter), and the UI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from app.config.schema import (  # noqa: E402
    MODEL_AUTO,
    AppConfig,
    LlmProfile,
    resolve_model,
)
from app.config.store import ConfigStore  # noqa: E402
from app.core.llm_client import LlmClient  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.model_catalog import ModelCatalogDialog  # noqa: E402
from app.ui.model_editor import CandidateModelEditor  # noqa: E402
from app.ui.model_picker import (  # noqa: E402
    _ROLE_MODEL,
    _ROLE_PROFILE,
    ModelPickerPopup,
    effort_help,
    effort_label,
    model_display,
)


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


# ── transport helpers ────────────────────────────────────────────
class _SeqTransport(httpx.BaseTransport):
    """Replay a fixed sequence of (status, body) responses."""

    def __init__(self, steps: list[tuple[int, dict[str, Any] | str]]) -> None:
        self._steps = steps
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self._steps) - 1)
        status, body = self._steps[index]
        if isinstance(body, dict):
            content = json.dumps(body).encode()
            headers = {"content-type": "application/json"}
        else:
            content = str(body).encode()
            headers = {"content-type": "text/plain"}
        return httpx.Response(status, content=content, headers=headers, request=request)


def _send(transport: _SeqTransport, profile: LlmProfile) -> LlmClient:
    client = LlmClient(profile)
    real_client_cls = httpx.Client

    class _PatchedClient(real_client_cls):  # type: ignore[misc,valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    with patch("app.core.llm_client.httpx.Client", _PatchedClient):
        client.chat([{"role": "user", "content": "hi"}])
    return client


_OK = (200, {"choices": [{"message": {"role": "assistant", "content": "你好"}}]})


# ── schema: candidate lists ──────────────────────────────────────
def test_candidates_are_deduped_bounded_and_contain_selection() -> None:
    profile = LlmProfile.from_dict(
        {
            "model": "kept",
            "models": ["", "a", "a", " b ", "c"],
            "model_options": ["x", "x", "y"],
        }
    )
    # The selected model is never missing from its own list.
    assert profile.models[0] == "kept"
    assert profile.models == ["kept", "a", "b", "c"]
    assert profile.model_options == ["x", "y"]


def test_add_and_remove_candidate_keep_selection_valid() -> None:
    profile = LlmProfile(model="m1", models=["m1"])
    assert profile.add_model("m2") is True
    assert profile.add_model("m2") is False  # duplicate
    assert profile.add_model("   ") is False  # blank

    profile.model = "m2"
    assert profile.remove_model("m2") is True
    assert profile.model == "m1"  # fell back to the first remaining row
    assert profile.remove_model("m1") is False  # never empties the list


def test_legacy_single_model_config_migrates() -> None:
    legacy = {
        "id": "p",
        "model": "deepseek-flash",
        "vision_model": "deepseek-flash",  # old default mirrored model
        "model_options": ["deepseek-chat", "deepseek-flash"],
    }
    profile = LlmProfile.from_dict(legacy)
    assert profile.models == ["deepseek-flash"]
    assert profile.model == "deepseek-flash"
    # Mirroring the text model is now the implicit default, not a setting.
    assert profile.vision_model == ""
    assert profile.vision_model_effective == "deepseek-flash"


def test_legacy_dedicated_vision_model_migrates() -> None:
    profile = LlmProfile.from_dict({"model": "qwen-plus", "vision_model": "qwen-vl-plus"})
    assert profile.vision_model == "qwen-vl-plus"
    assert profile.vision_model_effective == "qwen-vl-plus"


def test_vision_follows_model_when_unset() -> None:
    profile = LlmProfile(model="qwen-plus", models=["qwen-plus"])
    assert profile.vision_model == ""
    assert resolve_model(profile, vision_mode=True) == "qwen-plus"


def test_auto_mode_avoids_reasoning_models() -> None:
    profile = LlmProfile(model=MODEL_AUTO, models=[MODEL_AUTO, "deepseek-r1", "qwen-plus"])
    assert resolve_model(profile) == "qwen-plus"

    only_reasoning = LlmProfile(model=MODEL_AUTO, models=[MODEL_AUTO, "deepseek-r1"])
    assert resolve_model(only_reasoning) == "deepseek-r1"  # better than nothing


def test_auto_mode_prefers_vision_model_for_images() -> None:
    profile = LlmProfile(
        model=MODEL_AUTO,
        models=[MODEL_AUTO, "text-a"],
        vision_model="vision-x",
    )
    assert resolve_model(profile) == "text-a"
    assert resolve_model(profile, vision_mode=True) == "vision-x"


def test_explicit_model_is_sent_verbatim() -> None:
    profile = LlmProfile(model="gpt-4o-mini", models=["gpt-4o-mini", "deepseek-r1"])
    assert resolve_model(profile) == "gpt-4o-mini"


def test_unknown_effort_and_model_options_are_sanitized_in_config() -> None:
    profile = LlmProfile.from_dict(
        {"reasoning_effort": "EXTREME", "model_options": ["a", "a", " b "]}
    )
    assert profile.reasoning_effort == ""
    assert profile.model_options == ["a", "b"]

    cfg = AppConfig()
    cfg.profiles[0].reasoning_effort = "low"
    cfg.profiles[0].model_options = ["x", "y"]
    restored = AppConfig.from_dict(cfg.to_dict())
    assert restored.profiles[0].reasoning_effort == "low"
    assert restored.profiles[0].model_options == ["x", "y"]


# ── wire format ──────────────────────────────────────────────────
def test_chat_completions_sends_flat_effort() -> None:
    transport = _SeqTransport([_OK])
    profile = LlmProfile(reasoning_effort="medium", api_protocol="chat_completions")
    _send(transport, profile)
    assert json.loads(transport.requests[0].content)["reasoning_effort"] == "medium"


def test_responses_sends_nested_reasoning() -> None:
    transport = _SeqTransport([(200, {"output_text": "你好", "output": []})])
    profile = LlmProfile(reasoning_effort="high", api_protocol="responses")
    _send(transport, profile)
    body = json.loads(transport.requests[0].content)
    assert body["reasoning"] == {"effort": "high"}
    assert "reasoning_effort" not in body


def test_empty_effort_sends_no_parameter() -> None:
    transport = _SeqTransport([_OK])
    _send(transport, LlmProfile())
    body = json.loads(transport.requests[0].content)
    assert "reasoning_effort" not in body
    assert "reasoning" not in body


def test_rejected_effort_retries_without_parameter() -> None:
    transport = _SeqTransport(
        [
            (400, {"error": {"message": "Unsupported parameter: reasoning_effort"}}),
            _OK,
        ]
    )
    profile = LlmProfile(reasoning_effort="medium", api_protocol="chat_completions")
    client = _send(transport, profile)

    assert len(transport.requests) == 2
    assert "reasoning_effort" not in json.loads(transport.requests[1].content)
    assert client.warnings and "推理强度" in client.warnings[0]


def test_unrelated_400_is_not_retried() -> None:
    transport = _SeqTransport([(400, {"error": {"message": "context length exceeded"}})])
    with pytest.raises(Exception):  # noqa: B017 — ApiError, re-raised unchanged
        _send(transport, LlmProfile(reasoning_effort="medium"))
    assert len(transport.requests) == 1


def test_sentinel_model_is_resolved_before_sending() -> None:
    transport = _SeqTransport([_OK])
    profile = LlmProfile(
        model=MODEL_AUTO,
        models=[MODEL_AUTO, "deepseek-r1", "qwen-plus"],
        api_protocol="chat_completions",
    )
    _send(transport, profile)
    assert json.loads(transport.requests[0].content)["model"] == "qwen-plus"


# ── UI: settings candidate editor ────────────────────────────────
def test_candidate_editor_add_remove_and_select(qapp: QApplication) -> None:
    profile = LlmProfile(model="m1", models=["m1", "m2"])
    editor = CandidateModelEditor()
    editor.set_profile(profile)
    # "自动选择" row + two candidates
    assert editor.tree.count() == 3

    editor.edit.setText("m3")
    editor.add_from_edit()
    assert "m3" in profile.models

    editor.tree.setCurrentItem(editor.tree.item(2))  # m2
    assert profile.model == "m2"

    editor.remove_current()
    assert "m2" not in profile.models
    assert profile.model == "m1"


def test_candidate_editor_switch_to_auto_row(qapp: QApplication) -> None:
    profile = LlmProfile(model="m1", models=["m1", "m2"])
    editor = CandidateModelEditor()
    editor.set_profile(profile)
    editor.tree.setCurrentItem(editor.tree.item(0))  # 自动选择
    assert profile.model == MODEL_AUTO


# ── UI: settings dialog wiring ───────────────────────────────────
def test_settings_dialog_edits_candidates_and_vision(qapp: QApplication) -> None:
    from app.ui.settings_dialog import SettingsDialog

    cfg = AppConfig()
    cfg.profiles[0].models = ["m1", "m2"]
    dlg = SettingsDialog(cfg)
    editor = dlg.model_editor

    editor.edit.setText("m3")
    editor.add_from_edit()
    assert "m3" in dlg._config.get_active_profile().models

    # The vision combo must list the new candidate too.
    idx = dlg.vision_combo.findData("m3")
    assert idx > 0
    dlg.vision_combo.setCurrentIndex(idx)
    assert dlg._config.get_active_profile().vision_model == "m3"


# ── UI: bottom-bar picker ────────────────────────────────────────
@pytest.fixture()
def window(qapp: QApplication, tmp_path: Path):  # type: ignore[no-untyped-def]
    store = ConfigStore(tmp_path / "config.json")
    win = MainWindow(store, store.load())
    win.show()
    yield win
    win._force_quit = True
    win.close()


def test_picker_button_shows_model_and_effort(window: MainWindow) -> None:
    profile = window.config.get_active_profile()
    profile.model = "qwen3.7-flash"
    profile.models = ["qwen3.7-flash"]
    profile.reasoning_effort = "high"
    window._refresh_model_picker()
    assert "qwen3.7-flash" in window.model_picker.text()
    assert effort_label("high") in window.model_picker.text()


def test_picker_lists_only_the_active_provider_candidates(
    window: MainWindow,
) -> None:
    window.config.get_active_profile().models = ["a1", "a2", "a3"]
    second = LlmProfile(id="second", name="第二家", model="b1", models=["b1", "b2"])
    window.config.profiles.append(second)

    popup = window.model_popup
    popup.reload(window.config.get_active_profile())

    # The active provider's three candidates (plus a "current model is not a
    # candidate" note) — no provider headers, no sibling provider's models.
    texts = [popup.list.item(i).text() for i in range(popup.list.count())]
    assert sum(1 for t in texts if "a1" in t or "a2" in t or "a3" in t) == 3
    assert all("第二家" not in t for t in texts)
    assert all("b1" not in t for t in texts)

    # The provider dropdown holds every provider, active one marked.
    assert popup.provider_list.count() == 2
    assert popup.btn_provider.text().startswith(window.config.get_active_profile().name)


def test_provider_header_expands_and_switches(
    window: MainWindow, tmp_path: Path
) -> None:
    second = LlmProfile(id="second", name="第二家", model="b1", models=["b1", "b2"])
    window.config.profiles.append(second)
    window._refresh_model_picker()
    popup = window.model_popup
    popup.reload(window.config.get_active_profile())
    assert not popup.providers_open

    popup.btn_provider.click()
    assert popup.providers_open
    assert popup.provider_list.isVisible() or not popup.isVisible()

    row = next(
        popup.provider_list.item(i)
        for i in range(popup.provider_list.count())
        if popup.provider_list.item(i).data(_ROLE_PROFILE) == "second"
    )
    popup._on_provider_clicked(row)

    # Provider switched, list re-rendered with the new provider's candidates.
    assert not popup.providers_open
    assert window.config.active_profile_id == "second"
    assert window.profile_combo.currentData() == "second"  # toolbar in sync
    assert second.model == "b1"  # untouched: switching provider is not a model pick
    texts = [popup.list.item(i).text() for i in range(popup.list.count())]
    assert any("b2" in t for t in texts)

    saved = ConfigStore(tmp_path / "config.json").load()
    assert saved.active_profile_id == "second"


def test_picker_switch_provider_then_pick_model(
    window: MainWindow, tmp_path: Path
) -> None:
    second = LlmProfile(id="second", name="第二家", model="b1", models=["b1", "b2"])
    window.config.profiles.append(second)
    window._refresh_model_picker()
    popup = window.model_popup
    popup.reload(window.config.get_active_profile())

    popup._on_provider_clicked(popup.provider_list.item(1))
    row = next(
        popup.list.item(i)
        for i in range(popup.list.count())
        if popup.list.item(i).data(_ROLE_MODEL) == "b2"
    )
    popup._on_item_clicked(row)

    assert window.config.active_profile_id == "second"
    assert second.model == "b2"
    assert "b2" in window.model_picker.text()

    saved = ConfigStore(tmp_path / "config.json").load()
    assert saved.get_active_profile().model == "b2"


def test_list_height_follows_candidate_count(window: MainWindow) -> None:
    """Switching to a provider with more candidates must grow the panel.

    Regression: the list height was pinned once, so a 4-candidate provider
    rendered inside a one-row-high viewport (and a 1-candidate provider left
    a blank stripe after a taller one).
    """
    from PySide6.QtWidgets import QWidget as _W

    host = _W()
    host.resize(600, 700)
    host.show()

    one = LlmProfile(id="one", name="单候选", model="m1", models=["m1"])
    many = LlmProfile(
        id="many", name="多候选", model="m2", models=["m2", "m3", "m4", "m5"]
    )
    profiles = [one, many]
    popup = ModelPickerPopup(host, lambda: profiles, lambda: "one")
    popup.show_above(host.rect().adjusted(0, 500, 0, 0))
    popup.reload(one)
    QApplication.processEvents()

    small_h = popup.list.height()
    bottom = popup.geometry().bottom()

    popup._on_provider_clicked(popup.provider_list.item(1))
    QApplication.processEvents()
    assert popup.list.count() == 4
    assert popup.list.height() > small_h * 2
    # Grows upward: the bottom edge (the trigger button side) stays put.
    assert popup.geometry().bottom() == bottom

    popup._on_provider_clicked(popup.provider_list.item(0))
    QApplication.processEvents()
    assert popup.list.count() == 1
    assert popup.list.height() == small_h
    assert popup.geometry().bottom() == bottom


def test_expanding_providers_grows_upward(window: MainWindow) -> None:
    from PySide6.QtWidgets import QWidget as _W

    host = _W()
    host.resize(600, 700)
    host.show()
    one = LlmProfile(id="one", name="单候选", model="m1", models=["m1"])
    popup = ModelPickerPopup(host, lambda: [one], lambda: "one")
    popup.show_above(host.rect().adjusted(0, 500, 0, 0))
    popup.reload(one)
    QApplication.processEvents()

    closed_h = popup.height()
    bottom = popup.geometry().bottom()

    popup._set_providers_open(True)
    QApplication.processEvents()
    assert popup.height() > closed_h
    assert popup.geometry().bottom() == bottom

    popup._set_providers_open(False)
    QApplication.processEvents()
    assert popup.height() == closed_h
    assert popup.geometry().bottom() == bottom


def test_provider_without_candidates_mutes_the_list(window: MainWindow) -> None:
    profile = window.config.get_active_profile()
    profile.models = []
    seen: list[bool] = []
    window.model_popup.disabled_changed.connect(seen.append)

    window.model_popup.reload(profile)

    assert window.model_popup.list.count() == 1  # a single hint row
    assert window.model_popup.list.isEnabled() is False
    assert seen == [True]


def test_effort_labels_match_api_values() -> None:
    # The visible label must be the exact value sent as reasoning_effort,
    # otherwise users cannot tell which level they actually selected.
    assert effort_label("") == "默认"
    for value in ("minimal", "low", "medium", "high"):
        assert effort_label(value) == value
        assert value in effort_help(value)
    assert "reasoning_effort" in effort_help("")


def test_effort_slider_writes_profile_and_reset(window: MainWindow) -> None:
    popup = window.model_popup
    popup.reload(window.config.get_active_profile())

    popup.slider.setValue(3)  # 0=不指定 1=minimal 2=low 3=medium 4=high
    assert window.config.get_active_profile().reasoning_effort == "medium"
    assert effort_label("medium") in window.model_picker.text()

    popup.slider.setValue(0)  # 不指定
    assert window.config.get_active_profile().reasoning_effort == ""


def test_popup_round_trip_through_main_window(
    window: MainWindow, qapp: QApplication
) -> None:
    profile = window.config.get_active_profile()
    profile.models = ["m1", "m2"]

    window._toggle_model_picker()
    qapp.processEvents()
    popup = window.model_popup
    assert popup.isVisible()

    row = next(
        popup.list.item(i)
        for i in range(popup.list.count())
        if popup.list.item(i).data(_ROLE_MODEL) == "m2"
    )
    popup._on_item_clicked(row)
    assert profile.model == "m2"

    popup.hide_panel()
    assert not popup.isVisible()


def test_popup_marks_current_row(qapp: QApplication) -> None:
    profile = LlmProfile(id="p", name="P", model="m2", models=["m1", "m2"])
    host = QWidget()
    popup = ModelPickerPopup(host, lambda: [profile], lambda: "p")
    popup.reload(profile)

    texts = [popup.list.item(i).text() for i in range(popup.list.count())]
    assert any(t.startswith("✓") and "m2" in t for t in texts)
    assert not any(t.startswith("✓") and "m1" in t for t in texts)


def test_model_display_labels_sentinels() -> None:
    assert model_display(MODEL_AUTO) == "自动选择"
    assert model_display("gpt-4o-mini") == "gpt-4o-mini"


# ── UI: catalog picker ───────────────────────────────────────────
def test_catalog_dialog_returns_checked_subset(qapp: QApplication) -> None:
    profile = LlmProfile(id="p", model="m1", models=["m1"])
    dlg = ModelCatalogDialog(lambda: profile, ["m1"])
    dlg.set_models(["m1", "m2", "m3"])
    # m1 arrives pre-checked because it is already a candidate.
    assert dlg.checked_models() == ["m1"]

    dlg.list.item(1).setCheckState(Qt.CheckState.Checked)
    assert dlg.checked_models() == ["m1", "m2"]

    dlg.search.setText("m3")
    assert dlg.list.item(0).isHidden() or dlg.list.item(0).text() != "m3"
