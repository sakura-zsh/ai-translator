//! Scene presets and glossary parsing/formatting.

use indexmap::IndexMap;
use serde::Serialize;

use crate::config::schema::{CustomScene, TranslationConfig, GLOSSARY_MAX};

pub const AUTO_SCENE_ID: &str = "auto";
pub const AUTO_SCENE_LABEL: &str = "自动判断（Jev）";

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct ScenePreset {
    pub id: String,
    pub label: String,
    pub prompt: String,
    pub builtin: bool,
}

const BUILTIN_SCENES: &[(&str, &str, &str)] = &[
    ("general", "通用", ""),
    (
        "academic",
        "学术论文",
        "使用严谨的学术书面语；专业术语采用学界通用译法，首次出现时在括号内保留英文原词；长句可按中文习惯断句，但不得增删信息。",
    ),
    (
        "technical",
        "技术文档",
        "面向工程师的技术文档风格：代码、命令、API 名称、文件路径、配置键名一律保留原文不翻译；术语采用业界通用译法；语言简洁准确，步骤清晰。",
    ),
    (
        "casual",
        "口语化",
        "使用自然流畅的口语化表达，像母语者日常说话一样翻译；避免书面腔和翻译腔，可适当拆分长句。",
    ),
    (
        "formal",
        "正式书面",
        "使用正式书面语，语法严谨、措辞得体，适合新闻、公文、商务信函等场景。",
    ),
];

pub fn builtin_scene_presets() -> Vec<ScenePreset> {
    BUILTIN_SCENES
        .iter()
        .map(|(id, label, prompt)| ScenePreset {
            id: (*id).to_string(),
            label: (*label).to_string(),
            prompt: (*prompt).to_string(),
            builtin: true,
        })
        .collect()
}

pub fn all_scene_presets(custom_scenes: &[CustomScene]) -> Vec<ScenePreset> {
    let mut out = builtin_scene_presets();
    for c in custom_scenes {
        out.push(ScenePreset {
            id: c.id.clone(),
            label: c.label.clone(),
            prompt: c.prompt.clone(),
            builtin: false,
        });
    }
    out
}

pub fn get_scene(scene_id: &str, custom_scenes: &[CustomScene]) -> ScenePreset {
    if let Some((id, label, prompt)) = BUILTIN_SCENES.iter().find(|(id, _, _)| *id == scene_id) {
        return ScenePreset {
            id: (*id).to_string(),
            label: (*label).to_string(),
            prompt: (*prompt).to_string(),
            builtin: true,
        };
    }
    if let Some(c) = custom_scenes.iter().find(|c| c.id == scene_id) {
        return ScenePreset {
            id: c.id.clone(),
            label: c.label.clone(),
            prompt: c.prompt.clone(),
            builtin: false,
        };
    }
    let (id, label, prompt) = BUILTIN_SCENES[0];
    ScenePreset {
        id: id.to_string(),
        label: label.to_string(),
        prompt: prompt.to_string(),
        builtin: true,
    }
}

pub fn combine_extra_prompt(
    scene_id: &str,
    custom_scenes: &[CustomScene],
    supplementary: &str,
) -> String {
    let scene_text = get_scene(scene_id, custom_scenes).prompt;
    let mut parts = Vec::new();
    if !scene_text.trim().is_empty() {
        parts.push(scene_text.trim().to_string());
    }
    if !supplementary.trim().is_empty() {
        parts.push(supplementary.trim().to_string());
    }
    parts.join("\n")
}

pub fn effective_extra_prompt(cfg: &TranslationConfig) -> String {
    combine_extra_prompt(&cfg.scene, &cfg.custom_scenes, &cfg.supplementary_prompt)
}

const GLOSSARY_SEPARATORS: &[&str] = &["→", "->", "=", "\t"];

pub fn parse_glossary(text: &str) -> IndexMap<String, String> {
    let mut result = IndexMap::new();
    for raw in text.lines() {
        let line = raw.trim();
        if line.is_empty() {
            continue;
        }
        let earliest = GLOSSARY_SEPARATORS
            .iter()
            .filter_map(|sep| line.find(sep).map(|pos| (pos, *sep)))
            .min_by_key(|(pos, _)| *pos);
        let Some((pos, sep)) = earliest else {
            continue;
        };
        let term = line[..pos].trim();
        let value = line[pos + sep.len()..].trim();
        if !term.is_empty() && !value.is_empty() {
            result.insert(term.to_string(), value.to_string());
        }
        if result.len() >= GLOSSARY_MAX {
            break;
        }
    }
    result
}

pub fn format_glossary(glossary: &IndexMap<String, String>) -> String {
    glossary
        .iter()
        .map(|(k, v)| format!("{k} = {v}"))
        .collect::<Vec<_>>()
        .join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn glossary_parse_and_format() {
        let input = "API -> 接口\nToken = 令牌\nPrompt → 提示词\nCLI\t命令行\ninvalid line\n";
        let g = parse_glossary(input);
        assert_eq!(g.len(), 4);
        assert_eq!(g.get("API").map(String::as_str), Some("接口"));
        assert_eq!(g.get("Token").map(String::as_str), Some("令牌"));
        assert_eq!(g.get("Prompt").map(String::as_str), Some("提示词"));
        assert_eq!(g.get("CLI").map(String::as_str), Some("命令行"));
        assert!(format_glossary(&g).contains("API = 接口"));
    }

    #[test]
    fn unknown_scene_falls_back_to_general() {
        let s = get_scene("nonexistent", &[]);
        assert_eq!(s.id, "general");
    }
}
