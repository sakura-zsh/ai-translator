"""Tests for config schema and store."""

from __future__ import annotations

import sys
from pathlib import Path

from app.config.schema import AppConfig, LlmProfile
from app.config.store import ConfigStore, default_config_path


def test_default_config_has_profile() -> None:
    cfg = AppConfig.default()
    assert cfg.profiles
    assert cfg.get_active_profile().id == cfg.active_profile_id


def test_roundtrip_dict() -> None:
    cfg = AppConfig.default()
    cfg.profiles.append(
        LlmProfile(
            id="p2",
            name="DeepSeek",
            base_url="https://api.deepseek.com/v1",
            api_protocol="responses",
        )
    )
    cfg.active_profile_id = "p2"
    cfg.translation.supplementary_prompt = "正式语气"
    restored = AppConfig.from_dict(cfg.to_dict())
    assert restored.active_profile_id == "p2"
    assert restored.get_active_profile().name == "DeepSeek"
    assert restored.get_active_profile().api_protocol == "responses"
    assert restored.translation.supplementary_prompt == "正式语气"


def test_store_save_load(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    cfg = store.load()
    assert path.exists()
    if sys.platform != "win32":
        assert oct(path.stat().st_mode)[-3:] == "600"
    cfg.translation.target_lang = "en"
    store.save(cfg)
    again = store.load()
    assert again.translation.target_lang == "en"


def test_default_config_path_platform() -> None:
    path = default_config_path()
    assert path.name == "config.json"
    assert path.parent.name == "ai-translator"


def test_remove_last_profile_blocked() -> None:
    cfg = AppConfig.default()
    only_id = cfg.profiles[0].id
    assert cfg.remove_profile(only_id) is False
    assert len(cfg.profiles) == 1


def test_corrupt_config_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    store = ConfigStore(path)
    cfg = store.load()
    assert cfg.profiles


def test_load_survives_unwritable_location(tmp_path: Path) -> None:
    # Parent "directory" is actually a regular file → first-run save raises
    # OSError. load() must degrade to in-memory defaults instead of crashing.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    store = ConfigStore(blocker / "config.json")
    cfg = store.load()
    assert cfg.profiles
    assert cfg.get_active_profile().id == "default"
    assert not (blocker / "config.json").exists()


# ── new v0.2 fields & first-run detection ─────────────────────────
def test_new_fields_defaults_and_roundtrip() -> None:
    cfg = AppConfig.default()
    assert cfg.translation.auto_copy_result is False
    assert cfg.ui.hotkeys.extract_text == "Ctrl+Shift+T"

    cfg.translation.auto_copy_result = True
    cfg.ui.hotkeys.extract_text = "Ctrl+Shift+E"
    restored = AppConfig.from_dict(cfg.to_dict())
    assert restored.translation.auto_copy_result is True
    assert restored.ui.hotkeys.extract_text == "Ctrl+Shift+E"


def test_legacy_config_gets_new_defaults() -> None:
    # Old config JSON without the new fields must load cleanly.
    legacy = {
        "version": 1,
        "active_profile_id": "default",
        "profiles": [
            {
                "id": "default",
                "name": "OpenAI-compatible",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-old",
                "model": "gpt-4o-mini",
                "vision_model": "gpt-4o-mini",
                "temperature": 0.2,
                "timeout_s": 60.0,
                "max_tokens": 4096,
            }
        ],
        "translation": {"source_lang": "auto", "target_lang": "zh"},
        "ui": {"theme": "dark"},
        "history": [],
    }
    cfg = AppConfig.from_dict(legacy)
    assert cfg.translation.auto_copy_result is False
    assert cfg.ui.hotkeys.extract_text == "Ctrl+Shift+T"


def test_needs_setup_flags_untouched_default() -> None:
    assert AppConfig.default().needs_setup() is True

    cfg = AppConfig.default()
    cfg.profiles[0].api_key = "sk-something"
    assert cfg.needs_setup() is False

    cfg = AppConfig.default()
    cfg.profiles[0].base_url = "https://api.deepseek.com/v1"
    assert cfg.needs_setup() is False

    cfg = AppConfig.default()
    cfg.profiles.append(LlmProfile(id="p2", name="second"))
    assert cfg.needs_setup() is False


def test_history_keeps_ten_newest() -> None:
    cfg = AppConfig.default()
    for i in range(12):
        cfg.push_history(
            source_lang="en",
            target_lang="zh",
            mode="text",
            source_text=f"src-{i}",
            result_text=f"dst-{i}",
            model="m",
            ts=float(i),
        )
    assert len(cfg.history) == 10
    assert cfg.history[0].source_text == "src-11"
    assert cfg.history[-1].source_text == "src-2"


def test_history_roundtrip() -> None:
    cfg = AppConfig.default()
    cfg.push_history(
        source_lang="ja",
        target_lang="zh",
        mode="ocr",
        source_text="こんにちは",
        result_text="你好",
        model="gpt",
        ts=123.0,
    )
    restored = AppConfig.from_dict(cfg.to_dict())
    assert len(restored.history) == 1
    assert restored.history[0].source_text == "こんにちは"
    assert restored.history[0].mode == "ocr"


# ── v0.2 field sanitization roundtrips ────────────────────────────
def test_glossary_cleaning_on_load() -> None:
    raw = {
        "translation": {
            "glossary": {
                "GPU": "显卡",
                "  ": "空白键丢弃",
                "空值丢弃": "   ",
                "  LLM ": "  大语言模型  ",
            }
        }
    }
    t = AppConfig.from_dict(raw).translation
    assert t.glossary == {"GPU": "显卡", "LLM": "大语言模型"}
    assert "  " not in t.glossary


def test_history_limit_clamped() -> None:
    assert AppConfig.from_dict({"history_limit": 500}).history_limit == 100
    assert AppConfig.from_dict({"history_limit": -3}).history_limit == 0
    assert AppConfig.from_dict({"history_limit": "25"}).history_limit == 25
    # Pushing beyond the limit truncates the list (newest kept).
    cfg = AppConfig.from_dict({"history_limit": 2})
    for i in range(5):
        cfg.push_history(
            source_lang="en",
            target_lang="zh",
            mode="text",
            source_text=f"s{i}",
            result_text=f"d{i}",
        )
    assert len(cfg.history) == 2
    assert cfg.history[0].source_text == "s4"


def test_splitter_sizes_type_filtering() -> None:
    cfg = AppConfig.from_dict(
        {"ui": {"splitter_sizes": [300, "250", None, 4.0, "bad", True, [1]]}}
    )
    # bool is an int subclass → included; strings/None/lists dropped.
    assert cfg.ui.splitter_sizes == [300, 4, 1]
    assert AppConfig.from_dict({"ui": {"splitter_sizes": "junk"}}).ui.splitter_sizes == []
