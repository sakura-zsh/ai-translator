//! Language codes and display names.

use serde::Serialize;

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
pub struct LanguageItem {
    pub code: &'static str,
    pub label: &'static str,
}

pub const SOURCE_LANGUAGES: &[LanguageItem] = &[
    LanguageItem { code: "auto", label: "自动检测" },
    LanguageItem { code: "zh", label: "中文" },
    LanguageItem { code: "en", label: "English" },
    LanguageItem { code: "ja", label: "日本語" },
    LanguageItem { code: "ko", label: "한국어" },
    LanguageItem { code: "fr", label: "Français" },
    LanguageItem { code: "de", label: "Deutsch" },
    LanguageItem { code: "es", label: "Español" },
    LanguageItem { code: "ru", label: "Русский" },
    LanguageItem { code: "pt", label: "Português" },
    LanguageItem { code: "it", label: "Italiano" },
    LanguageItem { code: "vi", label: "Tiếng Việt" },
    LanguageItem { code: "th", label: "ไทย" },
    LanguageItem { code: "ar", label: "العربية" },
    LanguageItem { code: "hi", label: "हिन्दी" },
    LanguageItem { code: "id", label: "Bahasa Indonesia" },
    LanguageItem { code: "tr", label: "Türkçe" },
    LanguageItem { code: "nl", label: "Nederlands" },
    LanguageItem { code: "pl", label: "Polski" },
    LanguageItem { code: "uk", label: "Українська" },
];

pub fn target_languages() -> Vec<LanguageItem> {
    SOURCE_LANGUAGES
        .iter()
        .copied()
        .filter(|l| l.code != "auto")
        .collect()
}

pub fn display_name(code: &str) -> &str {
    SOURCE_LANGUAGES
        .iter()
        .find(|l| l.code == code)
        .map(|l| l.label)
        .unwrap_or(code)
}

pub fn language_name_for_prompt(code: &str) -> &str {
    match code {
        "auto" => "the language automatically detected from the text",
        "zh" => "Simplified Chinese",
        "en" => "English",
        "ja" => "Japanese",
        "ko" => "Korean",
        "fr" => "French",
        "de" => "German",
        "es" => "Spanish",
        "ru" => "Russian",
        "pt" => "Portuguese",
        "it" => "Italian",
        "vi" => "Vietnamese",
        "th" => "Thai",
        "ar" => "Arabic",
        "hi" => "Hindi",
        "id" => "Indonesian",
        "tr" => "Turkish",
        "nl" => "Dutch",
        "pl" => "Polish",
        "uk" => "Ukrainian",
        other => other,
    }
}
