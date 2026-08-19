"""Tests for prompt builders."""

from app.core.prompts import build_system_prompt


def test_auto_source_text_prompt() -> None:
    p = build_system_prompt("auto", "zh")
    assert "Auto-detect" in p
    assert "Simplified Chinese" in p
    assert "only the translation" in p.lower() or "Output only" in p


def test_fixed_source_prompt() -> None:
    p = build_system_prompt("en", "ja")
    assert "English" in p
    assert "Japanese" in p


def test_supplementary_appended() -> None:
    p = build_system_prompt("auto", "zh", "使用口语")
    assert "使用口语" in p
    assert "Additional instructions" in p


def test_vision_prompt() -> None:
    p = build_system_prompt("auto", "en", vision=True)
    assert "vision" in p.lower() or "image" in p.lower()
    assert "English" in p


def test_swaps_when_input_already_target_language() -> None:
    p = build_system_prompt("en", "zh")
    assert "already written in Simplified Chinese" in p
    assert "Automatically reverse" in p
    assert "translate it into English instead" in p


def test_auto_source_swaps_to_natural_counterpart() -> None:
    p = build_system_prompt("auto", "zh")
    assert "Automatically reverse" in p
    assert "English if the text is Chinese" in p


def test_vision_prompt_also_swaps_direction() -> None:
    p = build_system_prompt("en", "zh", vision=True)
    assert "Automatically reverse" in p
    assert "translate it into English instead" in p
