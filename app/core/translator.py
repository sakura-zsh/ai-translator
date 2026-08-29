"""Translation orchestrator: text, OCR, and vision paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.config.schema import LlmProfile
from app.core.llm_client import LlmClient
from app.core.ocr import OcrService
from app.core.prompts import build_system_prompt


ImageMode = Literal["ocr", "vision"]


@dataclass
class TranslateResult:
    text: str
    ocr_text: str | None = None
    model: str = ""
    mode: str = "text"


class Translator:
    def __init__(self, ocr: OcrService | None = None) -> None:
        self.ocr = ocr or OcrService()

    def translate_text(
        self,
        text: str,
        *,
        source_lang: str,
        target_lang: str,
        profile: LlmProfile,
        supplementary_prompt: str = "",
    ) -> TranslateResult:
        cleaned = (text or "").strip()
        if not cleaned:
            raise ValueError("Nothing to translate")

        system = build_system_prompt(
            source_lang,
            target_lang,
            supplementary_prompt,
            vision=False,
        )
        client = LlmClient(profile)
        out = client.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": cleaned},
            ]
        )
        return TranslateResult(text=out, model=profile.model, mode="text")

    def translate_image(
        self,
        image_png: bytes,
        *,
        mode: ImageMode,
        source_lang: str,
        target_lang: str,
        profile: LlmProfile,
        supplementary_prompt: str = "",
        ocr_langs: str = "eng+chi_sim",
    ) -> TranslateResult:
        if not image_png:
            raise ValueError("Empty image")

        if mode == "ocr":
            ocr_text = self.ocr.extract_text(image_png, langs=ocr_langs)
            result = self.translate_text(
                ocr_text,
                source_lang=source_lang,
                target_lang=target_lang,
                profile=profile,
                supplementary_prompt=supplementary_prompt,
            )
            result.ocr_text = ocr_text
            result.mode = "ocr"
            return result

        # vision
        system = build_system_prompt(
            source_lang,
            target_lang,
            supplementary_prompt,
            vision=True,
        )
        client = LlmClient(profile)
        model = profile.vision_model or profile.model
        out = client.chat_vision(
            system,
            "Translate the text visible in this image.",
            image_png,
            model=model,
        )
        return TranslateResult(text=out, model=model, mode="vision")
