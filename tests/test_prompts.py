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
    assert "automatically reverse" in p.lower()
    assert "translate it into English instead" in p


def test_auto_source_swaps_to_natural_counterpart() -> None:
    p = build_system_prompt("auto", "zh")
    assert "automatically reverse" in p.lower()
    assert "English if the text is Chinese" in p


def test_vision_prompt_also_swaps_direction() -> None:
    p = build_system_prompt("en", "zh", vision=True)
    assert "automatically reverse" in p.lower()
    assert "translate it into English instead" in p


def test_prompt_forbids_chain_of_thought() -> None:
    p = build_system_prompt("en", "zh")
    assert "never your reasoning" in p
    p_v = build_system_prompt("en", "zh", vision=True)
    assert "never your reasoning" in p_v


def test_prompt_handles_non_natural_language_input() -> None:
    """Terminal commands / code-only input returns unchanged, no agonizing."""
    p = build_system_prompt("zh", "en")
    assert "no translatable natural language" in p
    assert "shell commands" in p
    assert "return it" in p and "unchanged" in p


def test_prompt_requires_final_translation_tags() -> None:
    for vision in (False, True):
        p = build_system_prompt("en", "zh", vision=vision)
        assert "<final_translation>" in p
        assert "</final_translation>" in p
        assert "Only the text between these tags" in p
