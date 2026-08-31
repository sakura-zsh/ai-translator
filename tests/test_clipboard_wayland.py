"""Regression tests for the Wayland clipboard fast-fail (text paste latency)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core.clipboard_image import ClipboardImageError
from app.core.clipboard_wayland import ClipboardImageService


def _png_1px() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


_PNG_1PX = _png_1px()


def test_read_png_fails_fast_when_no_image_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """Types known & non-image → single decision, zero wl-paste subprocesses."""
    svc = ClipboardImageService()
    calls: list[str] = []

    monkeypatch.setattr(
        svc, "list_types", lambda: ["text/plain;charset=utf-8", "text/html"]
    )

    def _boom(mime: str) -> bytes:
        calls.append(mime)
        raise AssertionError("must not spawn wl-paste for non-image clipboards")

    monkeypatch.setattr(svc, "_paste_type", _boom)
    with pytest.raises(ClipboardImageError):
        svc.read_png()
    assert calls == []


def test_read_png_uses_image_type_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = ClipboardImageService()
    monkeypatch.setattr(svc, "list_types", lambda: ["text/plain", "image/png"])

    def _paste(mime: str) -> bytes:
        assert mime == "image/png"
        return _PNG_1PX

    monkeypatch.setattr(svc, "_paste_type", _paste)
    assert svc.read_png() == _PNG_1PX


def test_read_png_falls_back_when_types_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty/odd type list still walks the candidate list (old behaviour)."""
    svc = ClipboardImageService()
    monkeypatch.setattr(svc, "list_types", lambda: [])

    tried: list[str] = []

    def _paste(mime: str) -> bytes:
        tried.append(mime)
        if mime == "image/png":
            return _PNG_1PX
        return b""

    monkeypatch.setattr(svc, "_paste_type", _paste)
    assert svc.read_png() == _PNG_1PX
    assert tried[0] == "image/png"
