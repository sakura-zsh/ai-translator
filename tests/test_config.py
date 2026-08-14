"""Tests for config schema and store."""

from __future__ import annotations

import json
from pathlib import Path

from app.config.schema import AppConfig, LlmProfile
from app.config.store import ConfigStore


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
    assert oct(path.stat().st_mode)[-3:] == "600"
    cfg.translation.target_lang = "en"
    store.save(cfg)
    again = store.load()
    assert again.translation.target_lang == "en"


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
