"""Tests for the TTS core (cache, failure paths) and TtsConfig schema.

No network access: edge-tts is replaced by stub modules where needed and
playback (QMediaPlayer) is only constructed lazily, never in these tests.
"""

from __future__ import annotations

import os
import sys
import types

import pytest
from PySide6.QtWidgets import QApplication

from app.config.schema import TTS_RATE_MAX, TTS_RATE_MIN, TtsConfig
from app.core.tts import TextToSpeech, TtsError, TtsPlayer


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


# ── Cache keys ───────────────────────────────────────────────────────
def test_cache_path_is_deterministic_and_distinct(tmp_path) -> None:
    tts = TextToSpeech(tmp_path)
    a = tts.cache_path("hello", "zh-CN-XiaoxiaoNeural", 0)
    assert a == tts.cache_path("hello", "zh-CN-XiaoxiaoNeural", 0)
    assert a.suffix == ".mp3"
    # Different text / voice / rate → different files.
    assert a != tts.cache_path("world", "zh-CN-XiaoxiaoNeural", 0)
    assert a != tts.cache_path("hello", "en-US-AriaNeural", 0)
    assert a != tts.cache_path("hello", "zh-CN-XiaoxiaoNeural", -50)


# ── Failure paths ────────────────────────────────────────────────────
def test_speak_empty_text_raises(tmp_path) -> None:
    tts = TextToSpeech(tmp_path)
    with pytest.raises(TtsError):
        tts.speak("   ", "zh-CN-XiaoxiaoNeural", 0)


def _install_edge_tts_stub(monkeypatch, save_error: Exception | None = None) -> None:
    """Provide an `edge_tts` module stub; save() raises if asked to run."""

    class FakeCommunicate:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def save(self, _path: str) -> None:
            if save_error is not None:
                raise save_error
            raise AssertionError("synthesis must not run when cache hits")

    fake = types.ModuleType("edge_tts")
    fake.Communicate = FakeCommunicate  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "edge_tts", fake)


def test_speak_serves_from_cache_without_synthesis(monkeypatch, tmp_path) -> None:
    tts = TextToSpeech(tmp_path)
    cached = tts.cache_path("hello", "zh-CN-XiaoxiaoNeural", 0)
    cached.write_bytes(b"ID3fake-audio")
    _install_edge_tts_stub(monkeypatch)  # synthesis would raise AssertionError
    assert tts.speak("hello", "zh-CN-XiaoxiaoNeural", 0) == cached


def test_speak_synthesis_failure_raises_and_cleans_up(monkeypatch, tmp_path) -> None:
    tts = TextToSpeech(tmp_path)
    _install_edge_tts_stub(monkeypatch, save_error=RuntimeError("network down"))
    with pytest.raises(TtsError, match="语音合成失败"):
        tts.speak("hello", "zh-CN-XiaoxiaoNeural", 0)
    # No half-written cache entry left behind.
    assert list(tmp_path.glob("*.mp3")) == []


def test_speak_missing_engine_raises(monkeypatch, tmp_path) -> None:
    monkeypatch.setitem(sys.modules, "edge_tts", None)  # ImportError on import
    tts = TextToSpeech(tmp_path)
    with pytest.raises(TtsError, match="edge-tts"):
        tts.speak("hello", "zh-CN-XiaoxiaoNeural", 0)


# ── Cache pruning ────────────────────────────────────────────────────
def test_prune_keeps_newest_entries(tmp_path) -> None:
    tts = TextToSpeech(tmp_path)
    paths = []
    for i in range(4):
        p = tmp_path / f"old{i}.mp3"
        p.write_bytes(b"x")
        os.utime(p, (1000 + i, 1000 + i))
        paths.append(p)
    tts._prune_cache(keep=2)
    remaining = sorted(p.name for p in tmp_path.glob("*.mp3"))
    assert remaining == ["old2.mp3", "old3.mp3"]


# ── Player is lazy (headless-safe) ──────────────────────────────────
def test_tts_player_constructs_without_media_backend(qapp) -> None:
    player = TtsPlayer()
    assert player._player is None  # QMediaPlayer not created until play()
    player.stop()  # no-op before first play()


# ── TtsConfig schema ─────────────────────────────────────────────────
def test_tts_config_defaults_and_clamps() -> None:
    cfg = TtsConfig.from_dict(None)
    assert cfg.voice == "zh-CN-XiaoxiaoNeural"
    assert cfg.rate == 0
    assert cfg.auto_pronounce is False

    cfg = TtsConfig.from_dict({"voice": "", "rate": 999, "auto_pronounce": 1})
    assert cfg.voice == "zh-CN-XiaoxiaoNeural"  # empty → default
    assert TTS_RATE_MIN <= cfg.rate <= TTS_RATE_MAX
    assert cfg.auto_pronounce is True

    cfg = TtsConfig.from_dict({"rate": "not-a-number", "voice": 42})
    assert cfg.rate == 0
    assert cfg.voice == "42"


def test_tts_config_roundtrip_via_app_config() -> None:
    from app.config.schema import AppConfig

    cfg = AppConfig()
    cfg.tts = TtsConfig.from_dict({"voice": "en-US-AriaNeural", "rate": -50, "auto_pronounce": True})
    restored = AppConfig.from_dict(cfg.to_dict())
    assert restored.tts.voice == "en-US-AriaNeural"
    assert restored.tts.rate == -50
    assert restored.tts.auto_pronounce is True
