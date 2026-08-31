"""Tests for the translation orchestrator (OCR / vision paths)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.config.schema import LlmProfile
from app.core.imaging import sniff_image_mime
from app.core.translator import Translator


class _StubClient:
    """Stands in for LlmClient; captures what the vision path sends."""

    payload: bytes = b""

    def __init__(self, profile: LlmProfile) -> None:
        self.profile = profile

    def chat(self, messages: list[dict[str, str]], **_kwargs: object) -> str:
        return "译文"

    def chat_vision(
        self,
        system_prompt: str,
        user_text: str,
        image: bytes,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        _StubClient.payload = image
        return "译文"


def _screenshot_png(w: int = 3200, h: int = 1600) -> bytes:
    """Incompressible pseudo-screenshot (gradient) larger than VISION_MAX_DIM."""
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(0, h, 5):
        for x in range(0, w, 5):
            px[x, y] = (x % 256, y % 256, (x ^ y) % 256)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def stub_llm(monkeypatch: pytest.MonkeyPatch) -> type[_StubClient]:
    monkeypatch.setattr("app.core.translator.LlmClient", _StubClient)
    return _StubClient


def test_vision_payload_is_compacted(stub_llm: type[_StubClient]) -> None:
    png = _screenshot_png()
    result = Translator().translate_image(
        png,
        mode="vision",
        source_lang="auto",
        target_lang="zh",
        profile=LlmProfile(),
    )
    assert result.text == "译文"
    assert result.mode == "vision"
    # Contract: resolution capped and re-encoded (byte-size reduction is a
    # heuristic, not guaranteed for pathological inputs).
    with Image.open(io.BytesIO(stub_llm.payload)) as sent:
        assert max(sent.size) <= 2000
    assert sniff_image_mime(stub_llm.payload) == "image/jpeg"


def test_ocr_passes_original_image_to_ocr(
    stub_llm: type[_StubClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    received: dict[str, object] = {}

    class _StubOcr:
        def extract_text(self, image: bytes, langs: str = "eng+chi_sim") -> str:
            received["image"] = image
            received["langs"] = langs
            return "hello"

    translator = Translator(ocr=_StubOcr())  # type: ignore[arg-type]
    png = _screenshot_png()
    result = translator.translate_image(
        png,
        mode="ocr",
        source_lang="en",
        target_lang="zh",
        profile=LlmProfile(),
        ocr_langs="eng",
    )
    assert result.mode == "ocr"
    assert result.ocr_text == "hello"
    # OCR gets the lossless original, not the compacted payload
    assert received["image"] == png
    assert received["langs"] == "eng"


def test_empty_image_rejected(stub_llm: type[_StubClient]) -> None:
    with pytest.raises(ValueError):
        Translator().translate_image(
            b"",
            mode="vision",
            source_lang="auto",
            target_lang="zh",
            profile=LlmProfile(),
        )
