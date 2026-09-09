"""Text-to-speech: Microsoft Edge online voices via `edge-tts`.

Design:
- `TextToSpeech.speak()` is blocking (network + disk) and must run off the
  GUI thread — callers go through a TaskRunner worker.
- Synthesized audio is cached on disk keyed by (voice, rate, text), so
  repeated pronunciation of the same word is instant and offline.
- `TtsPlayer` wraps QMediaPlayer for playback on the GUI thread; the media
  player object is created lazily on first play to keep headless test
  environments (offscreen, no audio stack) safe.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal

log = logging.getLogger(__name__)

TTS_TIMEOUT_S = 30.0
_CACHE_KEEP_FILES = 200


class TtsError(RuntimeError):
    """Raised when speech synthesis fails (network, engine, empty text)."""


def default_cache_dir() -> Path:
    """Per-platform audio cache dir (mirrors logsetup's conventions)."""
    import os
    import sys

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(
            Path.home() / "AppData" / "Local"
        )
        return Path(base) / "ai-translator" / "cache" / "tts"
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "ai-translator" / "tts"


class TextToSpeech:
    """Blocking edge-tts synthesizer with a flat on-disk mp3 cache."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._cache_dir = cache_dir if cache_dir is not None else default_cache_dir()
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.warning("TTS cache dir unavailable: %s", self._cache_dir)

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def cache_path(self, text: str, voice: str, rate: int) -> Path:
        key = hashlib.sha1(f"{voice}|{rate}|{text}".encode()).hexdigest()[:20]
        return self._cache_dir / f"{key}.mp3"

    def speak(self, text: str, voice: str, rate: int) -> Path:
        """Synthesize `text` (cache-first); blocking; raises TtsError."""
        text = (text or "").strip()
        if not text:
            raise TtsError("没有可朗读的文本")
        path = self.cache_path(text, voice, rate)
        if path.exists() and path.stat().st_size > 0:
            return path

        try:
            import edge_tts
        except ImportError as exc:  # packaging missed the dependency
            raise TtsError("语音引擎不可用（缺少 edge-tts）") from exc

        try:
            communicate = edge_tts.Communicate(text, voice=voice, rate=f"{rate:+d}%")
            asyncio.run(asyncio.wait_for(communicate.save(str(path)), TTS_TIMEOUT_S))
        except Exception as exc:  # noqa: BLE001 — surface any failure to UI
            log.warning("TTS synthesis failed: %s", exc)
            path.unlink(missing_ok=True)
            raise TtsError(f"语音合成失败：{exc}") from exc

        if not path.exists() or path.stat().st_size == 0:
            path.unlink(missing_ok=True)
            raise TtsError("语音合成失败（空输出）")
        self._prune_cache()
        return path

    def _prune_cache(self, keep: int = _CACHE_KEEP_FILES) -> None:
        """Drop oldest cached clips beyond `keep` so the cache stays small."""
        try:
            files = sorted(
                (p for p in self._cache_dir.glob("*.mp3") if p.is_file()),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return
        for old in files[keep:]:
            old.unlink(missing_ok=True)


class TtsPlayer(QObject):
    """Plays synthesized audio on the GUI thread (lazy QMediaPlayer)."""

    state_changed = Signal(str)  # "playing" | "stopped" | "error: <msg>"

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._player: object | None = None
        self._audio: object | None = None

    def _ensure_player(self) -> None:
        if self._player is not None:
            return
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        player = QMediaPlayer(self)
        audio = QAudioOutput(self)
        player.setAudioOutput(audio)
        audio.setVolume(1.0)
        player.errorOccurred.connect(self._on_error)
        player.mediaStatusChanged.connect(self._on_media_status)
        self._player = player
        self._audio = audio

    def _on_media_status(self, status: object) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.state_changed.emit("stopped")

    def play(self, path: Path | str) -> None:
        self._ensure_player()
        player = self._player
        assert player is not None
        player.stop()
        player.setSource(QUrl.fromLocalFile(str(path)))
        player.play()
        self.state_changed.emit("playing")

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()
            self.state_changed.emit("stopped")

    def _on_error(self, error: object, error_string: str) -> None:
        log.warning("TTS playback error: %s", error_string)
        self.state_changed.emit(f"error: {error_string}")
