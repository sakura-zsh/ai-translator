//! System prompt builders for text, dictionary, and vision translation.

use indexmap::IndexMap;

use crate::config::schema::GLOSSARY_MAX;
use crate::languages::language_name_for_prompt;

/// Heuristic check for short word / phrase dictionary queries (1–3 words, no sentence punctuation).
pub fn is_dictionary_query(text: &str, source_lang: &str, target_lang: &str) -> bool {
    let trimmed = text.trim();
    if trimmed.is_empty() || trimmed.contains('\n') || trimmed.chars().count() > 42 {
        return false;
    }
    if target_lang == source_lang {
        return false;
    }
    if trimmed.contains("://") || trimmed.contains('/') || trimmed.contains('\\') || trimmed.contains('=') {
        return false;
    }
    // Sentence punctuation or code symbols disqualify dictionary mode
    if trimmed.chars().any(|c| {
        matches!(
            c,
            '.' | ',' | '!' | '?' | ';' | ':' | '"' | '(' | ')' | '[' | ']' | '{' | '}' | '。' | '，' | '！' | '？'
        )
    }) {
        return false;
    }

    let words: Vec<&str> = trimmed.split_whitespace().collect();
    if words.is_empty() || words.len() > 3 {
        return false;
    }
    // Must contain at least one ASCII alphabetic letter and mostly word characters (letters, '-', '\'')
    let has_ascii_alpha = trimmed.chars().any(|c| c.is_ascii_alphabetic());
    let all_word_like = words.iter().all(|w| {
        w.chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '\'')
    });
    has_ascii_alpha && all_word_like
}

pub fn build_dictionary_prompt(
    source_lang: &str,
    target_lang: &str,
    supplementary: &str,
    glossary: Option<&IndexMap<String, String>>,
) -> String {
    let source = language_name_for_prompt(source_lang);
    let target = language_name_for_prompt(target_lang);
    let source_clause = if source_lang == "auto" {
        "Auto-detect the source language of the word/phrase.".to_string()
    } else {
        format!("The source language is {source}.")
    };

    let mut base = format!(
        "You are a concise, authoritative bilingual dictionary assistant. \
{source_clause} Explain the user's word or short phrase in {target}. \
Format the answer cleanly in plain text with:\n\
1. Headword & IPA pronunciation (e.g. /.../)\n\
2. Part(s) of speech & concise definitions\n\
3. 1-2 natural example sentences with {target} translations\n\
4. Common collocations or usage notes (if helpful, keep brief).\n\
Output only the final dictionary entry wrapped in <final_translation> and </final_translation> tags. \
Keep any reasoning outside those tags."
    );

    let extra = supplementary.trim();
    if !extra.is_empty() {
        base.push_str("\n\nAdditional instructions from the user:\n");
        base.push_str(extra);
    }
    if let Some(map) = glossary {
        if !map.is_empty() {
            let pairs = map
                .iter()
                .take(GLOSSARY_MAX)
                .map(|(k, v)| format!("{k} → {v}"))
                .collect::<Vec<_>>()
                .join("; ");
            base.push_str("\n\nGlossary — honor these fixed translations:\n");
            base.push_str(&pairs);
        }
    }
    base
}

pub fn build_system_prompt(
    source_lang: &str,
    target_lang: &str,
    supplementary: &str,
    vision: bool,
    glossary: Option<&IndexMap<String, String>>,
) -> String {
    let source = language_name_for_prompt(source_lang);
    let target = language_name_for_prompt(target_lang);
    let swap_clause = direction_swap_clause(source_lang, source, target);

    let mut base = if vision {
        let src_part = if source_lang != "auto" {
            format!(" (expected source language: {source})")
        } else {
            ", auto-detect the source language".to_string()
        };
        format!(
            "You are a professional translator with vision capabilities. \
Read all readable text in the provided image{src_part}, then translate it into {target}. \
{swap_clause} \
Output only the final translation text, never your reasoning, \
analysis, or thinking process. \
Wrap the final translation in <final_translation> and \
</final_translation> tags. Only the text between these tags is \
delivered to the user; keep any reasoning outside them. \
Preserve structure, line breaks, numbers, code, URLs, and proper nouns when appropriate. \
Do not add explanations, notes, quotes, or labels."
        )
    } else {
        let source_clause = if source_lang == "auto" {
            "Auto-detect the source language of the input.".to_string()
        } else {
            format!("The source language is {source}.")
        };
        format!(
            "You are a professional translator. \
{source_clause} Translate the user's text into {target}. \
{swap_clause} \
Output only the final translation text, never your reasoning, \
analysis, or thinking process. \
Wrap the final translation in <final_translation> and \
</final_translation> tags. Only the text between these tags is \
delivered to the user; keep any reasoning outside them. \
Preserve meaning, tone, formatting, code blocks, URLs, and placeholders. \
Do not add explanations, notes, quotes, or labels."
        )
    };

    let extra = supplementary.trim();
    if !extra.is_empty() {
        base.push_str("\n\nAdditional instructions from the user:\n");
        base.push_str(extra);
    }

    if let Some(map) = glossary {
        if !map.is_empty() {
            let pairs = map
                .iter()
                .take(GLOSSARY_MAX)
                .map(|(k, v)| format!("{k} → {v}"))
                .collect::<Vec<_>>()
                .join("; ");
            base.push_str(
                "\n\nGlossary — always render these terms exactly as given \
(never translate them differently):\n",
            );
            base.push_str(&pairs);
        }
    }

    base
}

fn direction_swap_clause(source_lang: &str, source: &str, target: &str) -> String {
    let reverse_to = if source_lang == "auto" {
        format!(
            "the most likely intended language \
(English if the text is Chinese; Simplified Chinese if the text is English; \
otherwise a natural counterpart of {target})"
        )
    } else {
        source.to_string()
    };
    format!(
        "If the input is already written in {target}, automatically reverse \
the direction and translate it into {reverse_to} instead. \
If the input contains no translatable natural language (only code, \
shell commands, file paths, numbers, or identifiers), return it \
unchanged without commentary."
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prompt_includes_tags_and_glossary() {
        let mut g = IndexMap::new();
        g.insert("Rust".into(), "Rust".into());
        let p = build_system_prompt("auto", "zh", "保持简洁", false, Some(&g));
        assert!(p.contains("<final_translation>"));
        assert!(p.contains("Simplified Chinese"));
        assert!(p.contains("保持简洁"));
        assert!(p.contains("Rust → Rust"));
    }

    #[test]
    fn dictionary_heuristic_matches_short_words_only() {
        assert!(is_dictionary_query("ephemeral", "auto", "zh"));
        assert!(is_dictionary_query("take off", "en", "zh"));
        assert!(is_dictionary_query("state-of-the-art", "auto", "zh"));
        assert!(!is_dictionary_query("Hello, world!", "auto", "zh"));
        assert!(!is_dictionary_query("This is a complete sentence.", "auto", "zh"));
        assert!(!is_dictionary_query("https://example.com", "auto", "zh"));
        assert!(!is_dictionary_query("你好世界", "auto", "en"));
    }
}
