"""Prompt builders for text and vision translation."""

from __future__ import annotations

from app.core.languages import language_name_for_prompt


def build_system_prompt(
    source_lang: str,
    target_lang: str,
    supplementary: str = "",
    *,
    vision: bool = False,
    glossary: dict[str, str] | None = None,
) -> str:
    source = language_name_for_prompt(source_lang)
    target = language_name_for_prompt(target_lang)

    swap_clause = _direction_swap_clause(source_lang, source, target)

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
            f"{swap_clause} "
            "Output only the final translation text, never your reasoning, "
            "analysis, or thinking process. "
            "Wrap the final translation in <final_translation> and "
            "</final_translation> tags. Only the text between these tags is "
            "delivered to the user; keep any reasoning outside them. "
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
            f"{swap_clause} "
            "Output only the final translation text, never your reasoning, "
            "analysis, or thinking process. "
            "Wrap the final translation in <final_translation> and "
            "</final_translation> tags. Only the text between these tags is "
            "delivered to the user; keep any reasoning outside them. "
            "Preserve meaning, tone, formatting, code blocks, URLs, and placeholders. "
            "Do not add explanations, notes, quotes, or labels."
        )

    extra = (supplementary or "").strip()
    if extra:
        base = f"{base}\n\nAdditional instructions from the user:\n{extra}"

    if glossary:
        pairs = "; ".join(
            f"{term} → {translation}"
            for term, translation in list(glossary.items())[:100]
        )
        base += (
            "\n\nGlossary — always render these terms exactly as given "
            "(never translate them differently):\n"
            f"{pairs}"
        )
    return base


def _direction_swap_clause(source_lang: str, source: str, target: str) -> str:
    """If the user forgot to swap languages, do not echo already-target text."""
    if source_lang == "auto":
        reverse_to = (
            "the most likely intended language "
            "(English if the text is Chinese; Simplified Chinese if the text is English; "
            f"otherwise a natural counterpart of {target})"
        )
    else:
        reverse_to = source
    return (
        f"If the input is already written in {target}, automatically reverse "
        f"the direction and translate it into {reverse_to} instead. "
        "If the input contains no translatable natural language (only code, "
        "shell commands, file paths, numbers, or identifiers), return it "
        "unchanged without commentary."
    )
