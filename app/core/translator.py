"""Translation orchestrator: text, OCR, and vision paths."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.config.schema import LlmProfile, resolve_model
from app.core.imaging import downscale_for_vision
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
    # Non-fatal notes from the API layer (e.g. "relay ignored reasoning
    # effort"). Surfaced in the status bar, never treated as an error.
    warnings: list[str] = field(default_factory=list)


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
        glossary: dict[str, str] | None = None,
    ) -> TranslateResult:
        cleaned = (text or "").strip()
        if not cleaned:
            raise ValueError("Nothing to translate")

        system = build_system_prompt(
            source_lang,
            target_lang,
            supplementary_prompt,
            vision=False,
            glossary=glossary,
        )
        client = LlmClient(profile)
        out = client.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": cleaned},
            ],
            # ``model`` may be a sentinel (auto / vision) — resolve it to a
            # concrete id here so LlmClient only ever talks to real models.
            model=resolve_model(profile),
        )
        return TranslateResult(
            text=out,
            model=resolve_model(profile),
            mode="text",
            warnings=list(client.warnings),
        )

    def translate_image(
        self,
        image_png: bytes,
        *,
        mode: ImageMode,
        source_lang: str,
        target_lang: str,
        profile: LlmProfile,
        supplementary_prompt: str = "",
        glossary: dict[str, str] | None = None,
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
                glossary=glossary,
            )
            result.ocr_text = ocr_text
            result.mode = "ocr"
            return result

        # vision — downscale/compress the payload first: full-res PNG
        # screenshots cost far more tokens and upload time than they buy.
        system = build_system_prompt(
            source_lang,
            target_lang,
            supplementary_prompt,
            vision=True,
            glossary=glossary,
        )
        client = LlmClient(profile)
        model = resolve_model(profile, vision_mode=True)
        out = client.chat_vision(
            system,
            "Translate the text visible in this image.",
            downscale_for_vision(image_png),
            model=model,
        )
        return TranslateResult(
            text=out,
            model=model,
            mode="vision",
            warnings=list(client.warnings),
        )
