"""Language codes and display names."""

from __future__ import annotations

# (code, display name) — source list includes auto
SOURCE_LANGUAGES: list[tuple[str, str]] = [
    ("auto", "自动检测"),
    ("zh", "中文"),
    ("en", "English"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("es", "Español"),
    ("ru", "Русский"),
    ("pt", "Português"),
    ("it", "Italiano"),
    ("vi", "Tiếng Việt"),
    ("th", "ไทย"),
    ("ar", "العربية"),
    ("hi", "हिन्दी"),
    ("id", "Bahasa Indonesia"),
    ("tr", "Türkçe"),
    ("nl", "Nederlands"),
    ("pl", "Polski"),
    ("uk", "Українська"),
]

TARGET_LANGUAGES: list[tuple[str, str]] = [
    item for item in SOURCE_LANGUAGES if item[0] != "auto"
]

_DISPLAY = {code: name for code, name in SOURCE_LANGUAGES}


def display_name(code: str) -> str:
    return _DISPLAY.get(code, code)


def language_name_for_prompt(code: str) -> str:
    """English-ish name for prompts so the model is unambiguous."""
    mapping = {
        "auto": "the language automatically detected from the text",
        "zh": "Simplified Chinese",
        "en": "English",
        "ja": "Japanese",
        "ko": "Korean",
        "fr": "French",
        "de": "German",
        "es": "Spanish",
        "ru": "Russian",
        "pt": "Portuguese",
        "it": "Italian",
        "vi": "Vietnamese",
        "th": "Thai",
        "ar": "Arabic",
        "hi": "Hindi",
        "id": "Indonesian",
        "tr": "Turkish",
        "nl": "Dutch",
        "pl": "Polish",
        "uk": "Ukrainian",
    }
    return mapping.get(code, code)
