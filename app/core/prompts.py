"""Prompt builders for text and vision translation."""

from __future__ import annotations

from app.core.languages import language_name_for_prompt


def build_system_prompt(
    source_lang: str,
    target_lang: str,
    supplementary: str = "",
    *,
    vision: bool = False,
) -> str:
    source = language_name_for_prompt(source_lang)
    target = language_name_for_prompt(target_lang)

    if vision:
        base = (
            "You are a professional translator with vision capabilities. "
            "Read all readable text in the provided image"
            + (
                f" (expected source language: {source})"
                if source_lang != "auto"
                else ", auto-detect the source language"
            )
            + f", then translate it into {target}. "
            "Output only the translation. "
            "Preserve structure, line breaks, numbers, code, URLs, and proper nouns when appropriate. "
            "Do not add explanations, notes, quotes, or labels."
        )
    else:
        if source_lang == "auto":
            source_clause = "Auto-detect the source language of the input."
        else:
            source_clause = f"The source language is {source}."
        base = (
            "You are a professional translator. "
            f"{source_clause} Translate the user's text into {target}. "
            "Output only the translation. "
            "Preserve meaning, tone, formatting, code blocks, URLs, and placeholders. "
            "Do not add explanations, notes, quotes, or labels."
        )

    extra = (supplementary or "").strip()
    if extra:
        base = f"{base}\n\nAdditional instructions from the user:\n{extra}"
    return base


def build_user_text_message(text: str) -> str:
    return text
