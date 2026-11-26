//! Configuration types, defaults, sanitization, and legacy v0.x JSON compatibility.

use std::collections::HashSet;
use std::sync::OnceLock;
use std::time::{SystemTime, UNIX_EPOCH};

use indexmap::IndexMap;
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

pub const MODEL_AUTO: &str = "__auto__";
pub const MODEL_VISION: &str = "__vision__";

pub const REASONING_EFFORTS: &[&str] = &["", "low", "medium", "high", "xhigh", "max"];
pub const MODEL_OPTIONS_MAX: usize = 500;
pub const MODEL_CANDIDATES_MAX: usize = 50;
pub const CUSTOM_SCENES_MAX: usize = 20;
pub const GLOSSARY_MAX: usize = 100;
pub const JEV_QUALITY_THRESHOLD_DEFAULT: f64 = 0.6;
pub const TTS_RATE_MIN: i32 = -50;
pub const TTS_RATE_MAX: i32 = 100;
pub const HISTORY_LIMIT_DEFAULT: usize = 10;
pub const HISTORY_LIMIT_MAX: usize = 100;
const HISTORY_TEXT_MAX: usize = 4000;

pub fn new_id() -> String {
    Uuid::new_v4().simple().to_string()[..12].to_string()
}

pub fn is_sentinel_model(model: &str) -> bool {
    matches!(model, MODEL_AUTO | MODEL_VISION)
}

pub fn likely_reasoning_model(name: &str) -> bool {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| {
        Regex::new(r"(?i)reasoner|[-_]r1\b|qwq|o[134](-|$|\b)|thinking|deepseek-r\d").unwrap()
    });
    re.is_match(name)
}

pub fn sanitize_reasoning_effort(raw: &str) -> String {
    let val = raw.trim().to_ascii_lowercase();
    let normalized = if val == "minimal" {
        "low".to_string()
    } else {
        val
    };
    if REASONING_EFFORTS.contains(&normalized.as_str()) {
        normalized
    } else {
        String::new()
    }
}

pub fn sanitize_model_options(raw: &[String]) -> Vec<String> {
    let mut out = Vec::new();
    let mut seen = HashSet::new();
    for item in raw.iter().take(MODEL_OPTIONS_MAX) {
        let name = item.trim().to_string();
        if !name.is_empty() && seen.insert(name.clone()) {
            out.push(name);
        }
    }
    out
}

pub fn sanitize_model_candidates(raw: &[String], current: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut seen = HashSet::new();
    for item in raw.iter().take(MODEL_CANDIDATES_MAX) {
        let name = item.trim().to_string();
        if !name.is_empty() && seen.insert(name.clone()) {
            out.push(name);
        }
    }
    let cur = current.trim();
    if !cur.is_empty() && !seen.contains(cur) {
        out.insert(0, cur.to_string());
    }
    out
}

fn auto_pick(profile: &LlmProfile) -> String {
    let candidates: Vec<&str> = profile
        .models
        .iter()
        .map(String::as_str)
        .filter(|m| !m.is_empty() && !is_sentinel_model(m))
        .collect();
    if candidates.is_empty() {
        return String::new();
    }
    for name in &candidates {
        if !likely_reasoning_model(name) {
            return (*name).to_string();
        }
    }
    candidates[0].to_string()
}

pub fn resolve_model(profile: &LlmProfile, vision_mode: bool) -> String {
    let model = profile.model.trim();
    if model == MODEL_VISION {
        return profile.vision_model_effective();
    }
    if !model.is_empty() && model != MODEL_AUTO {
        return model.to_string();
    }
    let dedicated = profile.vision_model.trim();
    if vision_mode && !dedicated.is_empty() && !is_sentinel_model(dedicated) {
        return dedicated.to_string();
    }
    let picked = auto_pick(profile);
    if !picked.is_empty() {
        return picked;
    }
    let eff = profile.vision_model_effective();
    if !eff.is_empty() {
        return eff;
    }
    model.to_string()
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ApiProtocol {
    #[default]
    ChatCompletions,
    Responses,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum JevProtocol {
    #[default]
    Auto,
    Native,
    Openai,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ImageMode {
    #[default]
    Ocr,
    Vision,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ThemeMode {
    #[default]
    Dark,
    Light,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct LlmProfile {
    pub id: String,
    pub name: String,
    pub base_url: String,
    pub api_key: String,
    pub api_protocol: ApiProtocol,
    pub model: String,
    pub models: Vec<String>,
    pub vision_model: String,
    pub temperature: f64,
    pub timeout_s: f64,
    pub max_tokens: u32,
    pub reasoning_effort: String,
    pub model_options: Vec<String>,
}

impl Default for LlmProfile {
    fn default() -> Self {
        Self {
            id: new_id(),
            name: "OpenAI-compatible".to_string(),
            base_url: "https://api.openai.com/v1".to_string(),
            api_key: String::new(),
            api_protocol: ApiProtocol::ChatCompletions,
            model: "gpt-4o-mini".to_string(),
            models: vec!["gpt-4o-mini".to_string()],
            vision_model: String::new(),
            temperature: 0.2,
            timeout_s: 60.0,
            max_tokens: 4096,
            reasoning_effort: String::new(),
            model_options: Vec::new(),
        }
    }
}

impl LlmProfile {
    pub fn default_named() -> Self {
        Self {
            id: "default".to_string(),
            ..Self::default()
        }
    }

    pub fn sanitize(&mut self) {
        self.id = self.id.trim().to_string();
        if self.id.is_empty() {
            self.id = new_id();
        }
        self.reasoning_effort = sanitize_reasoning_effort(&self.reasoning_effort);
        self.model_options = sanitize_model_options(&self.model_options);
        self.model = self.model.trim().to_string();
        self.vision_model = self.vision_model.trim().to_string();
        self.models = sanitize_model_candidates(&self.models, &self.model);
        if self.model.is_empty() {
            self.model = self
                .models
                .first()
                .cloned()
                .unwrap_or_else(|| "gpt-4o-mini".to_string());
        }
        if !self.timeout_s.is_finite() || self.timeout_s <= 0.0 {
            self.timeout_s = 60.0;
        }
        if self.max_tokens == 0 {
            self.max_tokens = 4096;
        }
    }

    /// Parse from raw JSON Value with full legacy single-model migration.
    pub fn from_json_value(val: &Value) -> Option<Self> {
        let obj = val.as_object()?;
        let mut p = Self::default();
        if let Some(s) = obj.get("id").and_then(Value::as_str) {
            p.id = s.to_string();
        }
        if let Some(s) = obj.get("name").and_then(Value::as_str) {
            p.name = s.to_string();
        }
        if let Some(s) = obj.get("base_url").and_then(Value::as_str) {
            p.base_url = s.to_string();
        }
        if let Some(s) = obj.get("api_key").and_then(Value::as_str) {
            p.api_key = s.to_string();
        }
        p.api_protocol = match obj.get("api_protocol").and_then(Value::as_str) {
            Some("responses") => ApiProtocol::Responses,
            _ => ApiProtocol::ChatCompletions,
        };
        let model_raw = obj
            .get("model")
            .and_then(Value::as_str)
            .map(|s| s.trim().to_string());
        if let Some(ref m) = model_raw {
            p.model = m.clone();
        }
        if let Some(arr) = obj.get("models").and_then(Value::as_array) {
            p.models = arr
                .iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect();
        } else {
            // Migration from single-model schema
            p.models = if p.model.is_empty() {
                Vec::new()
            } else {
                vec![p.model.clone()]
            };
        }
        let vision = obj
            .get("vision_model")
            .and_then(Value::as_str)
            .map(|s| s.trim().to_string())
            .unwrap_or_default();
        // Legacy default mirrored `model`; drop when identical so it follows `model` implicitly.
        p.vision_model = if !vision.is_empty() && !p.model.is_empty() && vision == p.model {
            String::new()
        } else {
            vision
        };
        if let Some(n) = obj.get("temperature").and_then(Value::as_f64) {
            p.temperature = n;
        }
        if let Some(n) = obj.get("timeout_s").and_then(Value::as_f64) {
            p.timeout_s = n;
        }
        if let Some(n) = obj.get("max_tokens").and_then(Value::as_u64) {
            p.max_tokens = n as u32;
        }
        if let Some(s) = obj.get("reasoning_effort").and_then(Value::as_str) {
            p.reasoning_effort = s.to_string();
        }
        if let Some(arr) = obj.get("model_options").and_then(Value::as_array) {
            p.model_options = arr
                .iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect();
        }
        p.sanitize();
        Some(p)
    }

    pub fn vision_model_effective(&self) -> String {
        let vision = self.vision_model.trim();
        if !vision.is_empty() && !is_sentinel_model(vision) {
            return vision.to_string();
        }
        let auto = auto_pick(self);
        if !auto.is_empty() {
            auto
        } else {
            MODEL_AUTO.to_string()
        }
    }

    pub fn add_model(&mut self, name: &str) -> bool {
        let clean = name.trim();
        if clean.is_empty()
            || self.models.iter().any(|m| m == clean)
            || self.models.len() >= MODEL_CANDIDATES_MAX
        {
            return false;
        }
        self.models.push(clean.to_string());
        true
    }

    pub fn remove_model(&mut self, name: &str) -> bool {
        if self.models.len() <= 1 {
            return false;
        }
        let Some(pos) = self.models.iter().position(|m| m == name) else {
            return false;
        };
        self.models.remove(pos);
        if self.model == name {
            self.model = self.models[0].clone();
        }
        if self.vision_model == name {
            self.vision_model.clear();
        }
        true
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct JevConfig {
    pub enabled: bool,
    pub base_url: String,
    pub api_key: String,
    pub model: String,
    pub api_protocol: JevProtocol,
    pub timeout_s: f64,
    pub route_scene: bool,
    pub detect_language: bool,
    pub score_quality: bool,
    pub quality_threshold: f64,
    pub retry_on_low_quality: bool,
}

impl Default for JevConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            base_url: String::new(),
            api_key: String::new(),
            model: "jev-latest".to_string(),
            api_protocol: JevProtocol::Auto,
            timeout_s: 30.0,
            route_scene: true,
            detect_language: true,
            score_quality: false,
            quality_threshold: JEV_QUALITY_THRESHOLD_DEFAULT,
            retry_on_low_quality: false,
        }
    }
}

impl JevConfig {
    pub fn sanitize(&mut self) {
        self.base_url = self.base_url.trim().to_string();
        self.api_key = self.api_key.trim().to_string();
        let m = self.model.trim();
        self.model = if m.is_empty() {
            "jev-latest".to_string()
        } else {
            m.to_string()
        };
        if !self.timeout_s.is_finite() {
            self.timeout_s = 30.0;
        }
        self.timeout_s = self.timeout_s.clamp(5.0, 600.0);
        if !self.quality_threshold.is_finite() {
            self.quality_threshold = JEV_QUALITY_THRESHOLD_DEFAULT;
        }
        self.quality_threshold = self.quality_threshold.clamp(0.0, 1.0);
    }

    pub fn from_json_value(val: &Value) -> Self {
        let Some(obj) = val.as_object() else {
            return Self::default();
        };
        let mut c = Self::default();
        if let Some(b) = obj.get("enabled").and_then(Value::as_bool) {
            c.enabled = b;
        }
        if let Some(s) = obj.get("base_url").and_then(Value::as_str) {
            c.base_url = s.to_string();
        }
        if let Some(s) = obj.get("api_key").and_then(Value::as_str) {
            c.api_key = s.to_string();
        }
        if let Some(s) = obj.get("model").and_then(Value::as_str) {
            c.model = s.to_string();
        }
        c.api_protocol = match obj.get("api_protocol").and_then(Value::as_str) {
            Some("native") => JevProtocol::Native,
            Some("openai") => JevProtocol::Openai,
            _ => JevProtocol::Auto,
        };
        if let Some(n) = obj.get("timeout_s").and_then(Value::as_f64) {
            c.timeout_s = n;
        }
        if let Some(b) = obj.get("route_scene").and_then(Value::as_bool) {
            c.route_scene = b;
        }
        if let Some(b) = obj.get("detect_language").and_then(Value::as_bool) {
            c.detect_language = b;
        }
        if let Some(b) = obj.get("score_quality").and_then(Value::as_bool) {
            c.score_quality = b;
        }
        if let Some(n) = obj.get("quality_threshold").and_then(Value::as_f64) {
            c.quality_threshold = n;
        }
        if let Some(b) = obj.get("retry_on_low_quality").and_then(Value::as_bool) {
            c.retry_on_low_quality = b;
        }
        c.sanitize();
        c
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CustomScene {
    pub id: String,
    pub label: String,
    #[serde(default)]
    pub prompt: String,
}

pub fn sanitize_custom_scenes(raw: &[CustomScene]) -> Vec<CustomScene> {
    let mut out = Vec::new();
    let mut seen = HashSet::new();
    for item in raw.iter().take(CUSTOM_SCENES_MAX) {
        let id = item.id.trim().to_string();
        let label = item.label.trim().to_string();
        if id.is_empty() || label.is_empty() || !seen.insert(id.clone()) {
            continue;
        }
        out.push(CustomScene {
            id,
            label,
            prompt: item.prompt.clone(),
        });
    }
    out
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct TranslationConfig {
    pub source_lang: String,
    pub target_lang: String,
    pub image_mode: ImageMode,
    pub supplementary_prompt: String,
    pub ocr_langs: String,
    pub auto_copy_result: bool,
    pub auto_dictionary: bool,
    pub scene: String,
    pub glossary: IndexMap<String, String>,
    pub tesseract_path: String,
    pub custom_scenes: Vec<CustomScene>,
}

impl Default for TranslationConfig {
    fn default() -> Self {
        Self {
            source_lang: "auto".to_string(),
            target_lang: "zh".to_string(),
            image_mode: ImageMode::Ocr,
            supplementary_prompt: String::new(),
            ocr_langs: "eng+chi_sim".to_string(),
            auto_copy_result: false,
            auto_dictionary: true,
            scene: "general".to_string(),
            glossary: IndexMap::new(),
            tesseract_path: String::new(),
            custom_scenes: Vec::new(),
        }
    }
}

impl TranslationConfig {
    pub fn sanitize(&mut self) {
        self.custom_scenes = sanitize_custom_scenes(&self.custom_scenes);
        let mut clean_glossary = IndexMap::new();
        for (k, v) in self.glossary.iter().take(GLOSSARY_MAX) {
            let ks = k.trim();
            let vs = v.trim();
            if !ks.is_empty() && !vs.is_empty() {
                clean_glossary.insert(ks.to_string(), vs.to_string());
            }
        }
        self.glossary = clean_glossary;
    }

    pub fn from_json_value(val: &Value) -> Self {
        let Some(obj) = val.as_object() else {
            return Self::default();
        };
        let mut c = Self::default();
        if let Some(s) = obj.get("source_lang").and_then(Value::as_str) {
            c.source_lang = s.to_string();
        }
        if let Some(s) = obj.get("target_lang").and_then(Value::as_str) {
            c.target_lang = s.to_string();
        }
        c.image_mode = match obj.get("image_mode").and_then(Value::as_str) {
            Some("vision") => ImageMode::Vision,
            _ => ImageMode::Ocr,
        };
        if let Some(s) = obj.get("supplementary_prompt").and_then(Value::as_str) {
            c.supplementary_prompt = s.to_string();
        }
        if let Some(s) = obj.get("ocr_langs").and_then(Value::as_str) {
            c.ocr_langs = s.to_string();
        }
        if let Some(b) = obj.get("auto_copy_result").and_then(Value::as_bool) {
            c.auto_copy_result = b;
        }
        if let Some(b) = obj.get("auto_dictionary").and_then(Value::as_bool) {
            c.auto_dictionary = b;
        }
        if let Some(s) = obj.get("scene").and_then(Value::as_str) {
            c.scene = s.to_string();
        }
        if let Some(s) = obj.get("tesseract_path").and_then(Value::as_str) {
            c.tesseract_path = s.to_string();
        }
        if let Some(map) = obj.get("glossary").and_then(Value::as_object) {
            for (k, v) in map.iter().take(GLOSSARY_MAX) {
                let ks = k.trim();
                let vs = match v {
                    Value::String(s) => s.trim().to_string(),
                    other => other.to_string().trim().to_string(),
                };
                if !ks.is_empty() && !vs.is_empty() {
                    c.glossary.insert(ks.to_string(), vs);
                }
            }
        }
        if let Some(arr) = obj.get("custom_scenes").and_then(Value::as_array) {
            for item in arr {
                if let Some(m) = item.as_object() {
                    let id = m
                        .get("id")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_string();
                    let label = m
                        .get("label")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_string();
                    let prompt = m
                        .get("prompt")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_string();
                    c.custom_scenes.push(CustomScene { id, label, prompt });
                }
            }
        }
        c.sanitize();
        c
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(default)]
pub struct HotkeysConfig {
    pub translate: String,
    pub screenshot: String,
    pub paste_image: String,
    pub swap_langs: String,
    pub copy_result: String,
    pub extract_text: String,
    pub summon: String,
    pub quick_translate: String,
}

impl Default for HotkeysConfig {
    fn default() -> Self {
        Self {
            translate: "Ctrl+Return".to_string(),
            screenshot: "Ctrl+Shift+S".to_string(),
            paste_image: "Ctrl+Shift+V".to_string(),
            swap_langs: "Ctrl+Shift+X".to_string(),
            copy_result: "Ctrl+Shift+C".to_string(),
            extract_text: "Ctrl+Shift+T".to_string(),
            summon: "Ctrl+Alt+T".to_string(),
            quick_translate: "Ctrl+Alt+Q".to_string(),
        }
    }
}

impl HotkeysConfig {
    pub fn from_json_value(val: &Value) -> Self {
        let Some(obj) = val.as_object() else {
            return Self::default();
        };
        let mut h = Self::default();
        if let Some(s) = obj.get("translate").and_then(Value::as_str) {
            h.translate = s.to_string();
        }
        if let Some(s) = obj.get("screenshot").and_then(Value::as_str) {
            h.screenshot = s.to_string();
        }
        if let Some(s) = obj.get("paste_image").and_then(Value::as_str) {
            h.paste_image = s.to_string();
        }
        if let Some(s) = obj.get("swap_langs").and_then(Value::as_str) {
            h.swap_langs = s.to_string();
        }
        if let Some(s) = obj.get("copy_result").and_then(Value::as_str) {
            h.copy_result = s.to_string();
        }
        if let Some(s) = obj.get("extract_text").and_then(Value::as_str) {
            h.extract_text = s.to_string();
        }
        if let Some(s) = obj.get("summon").and_then(Value::as_str) {
            h.summon = s.to_string();
        }
        if let Some(s) = obj.get("quick_translate").and_then(Value::as_str) {
            h.quick_translate = s.to_string();
        }
        h
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(default)]
pub struct TtsConfig {
    pub voice: String,
    pub rate: i32,
    pub auto_pronounce: bool,
}

impl Default for TtsConfig {
    fn default() -> Self {
        Self {
            voice: "zh-CN-XiaoxiaoNeural".to_string(),
            rate: 0,
            auto_pronounce: false,
        }
    }
}

impl TtsConfig {
    pub fn sanitize(&mut self) {
        let v = self.voice.trim();
        self.voice = if v.is_empty() {
            "zh-CN-XiaoxiaoNeural".to_string()
        } else {
            v.to_string()
        };
        self.rate = self.rate.clamp(TTS_RATE_MIN, TTS_RATE_MAX);
    }

    pub fn from_json_value(val: &Value) -> Self {
        let Some(obj) = val.as_object() else {
            return Self::default();
        };
        let mut t = Self::default();
        if let Some(s) = obj.get("voice").and_then(Value::as_str) {
            t.voice = s.to_string();
        }
        if let Some(n) = obj.get("rate").and_then(Value::as_i64) {
            t.rate = n as i32;
        } else if let Some(n) = obj.get("rate").and_then(Value::as_f64) {
            t.rate = n as i32;
        }
        if let Some(b) = obj.get("auto_pronounce").and_then(Value::as_bool) {
            t.auto_pronounce = b;
        }
        t.sanitize();
        t
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(default)]
pub struct UiConfig {
    pub theme: ThemeMode,
    pub window_width: u32,
    pub window_height: u32,
    pub window_maximized: bool,
    pub splitter_sizes: Vec<i32>,
    pub close_to_tray: bool,
    pub hotkeys: HotkeysConfig,
}

impl Default for UiConfig {
    fn default() -> Self {
        Self {
            theme: ThemeMode::Dark,
            window_width: 920,
            window_height: 640,
            window_maximized: false,
            splitter_sizes: Vec::new(),
            close_to_tray: true,
            hotkeys: HotkeysConfig::default(),
        }
    }
}

impl UiConfig {
    pub fn from_json_value(val: &Value) -> Self {
        let Some(obj) = val.as_object() else {
            return Self::default();
        };
        let mut u = Self {
            theme: match obj.get("theme").and_then(Value::as_str) {
                Some("light") => ThemeMode::Light,
                _ => ThemeMode::Dark,
            },
            ..Self::default()
        };
        if let Some(n) = obj.get("window_width").and_then(Value::as_u64) {
            u.window_width = (n as u32).max(400);
        }
        if let Some(n) = obj.get("window_height").and_then(Value::as_u64) {
            u.window_height = (n as u32).max(320);
        }
        if let Some(b) = obj.get("window_maximized").and_then(Value::as_bool) {
            u.window_maximized = b;
        }
        if let Some(b) = obj.get("close_to_tray").and_then(Value::as_bool) {
            u.close_to_tray = b;
        }
        if let Some(arr) = obj.get("splitter_sizes").and_then(Value::as_array) {
            u.splitter_sizes = arr
                .iter()
                .filter_map(|v| v.as_f64().map(|n| n as i32))
                .collect();
        }
        if let Some(hk) = obj.get("hotkeys") {
            u.hotkeys = HotkeysConfig::from_json_value(hk);
        }
        u
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct HistoryEntry {
    pub id: String,
    pub ts: f64,
    pub source_lang: String,
    pub target_lang: String,
    pub mode: String,
    pub source_text: String,
    pub result_text: String,
    pub model: String,
}

impl Default for HistoryEntry {
    fn default() -> Self {
        Self {
            id: new_id(),
            ts: 0.0,
            source_lang: "auto".to_string(),
            target_lang: "zh".to_string(),
            mode: "text".to_string(),
            source_text: String::new(),
            result_text: String::new(),
            model: String::new(),
        }
    }
}

impl HistoryEntry {
    pub fn from_json_value(val: &Value) -> Option<Self> {
        let obj = val.as_object()?;
        let mut e = Self::default();
        if let Some(s) = obj.get("id").and_then(Value::as_str) {
            if !s.is_empty() {
                e.id = s.to_string();
            }
        }
        if let Some(n) = obj.get("ts").and_then(Value::as_f64) {
            e.ts = n;
        }
        if let Some(s) = obj.get("source_lang").and_then(Value::as_str) {
            e.source_lang = s.to_string();
        }
        if let Some(s) = obj.get("target_lang").and_then(Value::as_str) {
            e.target_lang = s.to_string();
        }
        if let Some(s) = obj.get("mode").and_then(Value::as_str) {
            e.mode = s.to_string();
        }
        if let Some(s) = obj.get("source_text").and_then(Value::as_str) {
            e.source_text = s.to_string();
        }
        if let Some(s) = obj.get("result_text").and_then(Value::as_str) {
            e.result_text = s.to_string();
        }
        if let Some(s) = obj.get("model").and_then(Value::as_str) {
            e.model = s.to_string();
        }
        Some(e)
    }
}

pub const FAVORITES_MAX: usize = 500;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct FavoriteEntry {
    pub id: String,
    pub ts: f64,
    pub source_lang: String,
    pub target_lang: String,
    pub mode: String,
    pub source_text: String,
    pub result_text: String,
    pub model: String,
}

impl Default for FavoriteEntry {
    fn default() -> Self {
        Self {
            id: new_id(),
            ts: 0.0,
            source_lang: "auto".to_string(),
            target_lang: "zh".to_string(),
            mode: "text".to_string(),
            source_text: String::new(),
            result_text: String::new(),
            model: String::new(),
        }
    }
}

impl FavoriteEntry {
    pub fn from_json_value(val: &Value) -> Option<Self> {
        let obj = val.as_object()?;
        let source_text = obj
            .get("source_text")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim()
            .to_string();
        let result_text = obj
            .get("result_text")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim()
            .to_string();
        if source_text.is_empty() || result_text.is_empty() {
            return None;
        }
        Some(Self {
            id: obj
                .get("id")
                .and_then(Value::as_str)
                .filter(|s| !s.is_empty())
                .map(String::from)
                .unwrap_or_else(new_id),
            ts: obj.get("ts").and_then(Value::as_f64).unwrap_or(0.0),
            source_lang: obj
                .get("source_lang")
                .and_then(Value::as_str)
                .unwrap_or("auto")
                .to_string(),
            target_lang: obj
                .get("target_lang")
                .and_then(Value::as_str)
                .unwrap_or("zh")
                .to_string(),
            mode: obj
                .get("mode")
                .and_then(Value::as_str)
                .unwrap_or("text")
                .to_string(),
            source_text,
            result_text,
            model: obj
                .get("model")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string(),
        })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct AppConfig {
    pub version: u32,
    pub active_profile_id: String,
    pub profiles: Vec<LlmProfile>,
    pub translation: TranslationConfig,
    pub ui: UiConfig,
    pub tts: TtsConfig,
    pub jev: JevConfig,
    pub history: Vec<HistoryEntry>,
    pub history_limit: usize,
    pub favorites: Vec<FavoriteEntry>,
    pub last_run_version: String,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            version: 1,
            active_profile_id: "default".to_string(),
            profiles: vec![LlmProfile::default_named()],
            translation: TranslationConfig::default(),
            ui: UiConfig::default(),
            tts: TtsConfig::default(),
            jev: JevConfig::default(),
            history: Vec::new(),
            history_limit: HISTORY_LIMIT_DEFAULT,
            favorites: Vec::new(),
            last_run_version: String::new(),
        }
    }
}

impl AppConfig {
    pub fn sanitize(&mut self) {
        if self.profiles.is_empty() {
            self.profiles.push(LlmProfile::default_named());
            self.active_profile_id = "default".to_string();
        }
        for p in &mut self.profiles {
            p.sanitize();
        }
        if !self.profiles.iter().any(|p| p.id == self.active_profile_id) {
            self.active_profile_id = self.profiles[0].id.clone();
        }
        self.translation.sanitize();
        self.tts.sanitize();
        self.jev.sanitize();
        self.history_limit = self.history_limit.min(HISTORY_LIMIT_MAX);
        if self.history.len() > self.history_limit {
            self.history.truncate(self.history_limit);
        }
        if self.favorites.len() > FAVORITES_MAX {
            self.favorites.truncate(FAVORITES_MAX);
        }
    }

    pub fn from_json_value(val: &Value) -> Self {
        let Some(obj) = val.as_object() else {
            return Self::default();
        };
        let mut profiles: Vec<LlmProfile> = obj
            .get("profiles")
            .and_then(Value::as_array)
            .map(|arr| arr.iter().filter_map(LlmProfile::from_json_value).collect())
            .unwrap_or_default();
        if profiles.is_empty() {
            profiles.push(LlmProfile::default_named());
        }
        let mut active = obj
            .get("active_profile_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        if !profiles.iter().any(|p| p.id == active) {
            active = profiles[0].id.clone();
        }
        let history_limit = obj
            .get("history_limit")
            .and_then(Value::as_i64)
            .map(|n| n.clamp(0, HISTORY_LIMIT_MAX as i64) as usize)
            .unwrap_or(HISTORY_LIMIT_DEFAULT);
        let mut history: Vec<HistoryEntry> = obj
            .get("history")
            .and_then(Value::as_array)
            .map(|arr| {
                arr.iter()
                    .filter_map(HistoryEntry::from_json_value)
                    .take(history_limit)
                    .collect()
            })
            .unwrap_or_default();
        history.truncate(history_limit);

        let favorites: Vec<FavoriteEntry> = obj
            .get("favorites")
            .and_then(Value::as_array)
            .map(|arr| {
                arr.iter()
                    .filter_map(FavoriteEntry::from_json_value)
                    .take(FAVORITES_MAX)
                    .collect()
            })
            .unwrap_or_default();

        let mut cfg = Self {
            version: obj.get("version").and_then(Value::as_u64).unwrap_or(1) as u32,
            active_profile_id: active,
            profiles,
            translation: obj
                .get("translation")
                .map(TranslationConfig::from_json_value)
                .unwrap_or_default(),
            ui: obj.get("ui").map(UiConfig::from_json_value).unwrap_or_default(),
            tts: obj.get("tts").map(TtsConfig::from_json_value).unwrap_or_default(),
            jev: obj.get("jev").map(JevConfig::from_json_value).unwrap_or_default(),
            history,
            history_limit,
            favorites,
            last_run_version: obj
                .get("last_run_version")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string(),
        };
        cfg.sanitize();
        cfg
    }

    pub fn needs_setup(&self) -> bool {
        if self.profiles.len() != 1 {
            return false;
        }
        let p = &self.profiles[0];
        let def = LlmProfile::default_named();
        p.id == "default"
            && p.api_key.is_empty()
            && p.base_url == def.base_url
            && p.model == def.model
    }

    #[allow(clippy::too_many_arguments)]
    pub fn push_history(
        &mut self,
        source_lang: &str,
        target_lang: &str,
        mode: &str,
        source_text: &str,
        result_text: &str,
        model: &str,
        ts: Option<f64>,
    ) -> HistoryEntry {
        let now = ts.unwrap_or_else(|| {
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_secs_f64())
                .unwrap_or(0.0)
        });
        let entry = HistoryEntry {
            id: new_id(),
            ts: now,
            source_lang: if source_lang.is_empty() {
                "auto".to_string()
            } else {
                source_lang.to_string()
            },
            target_lang: if target_lang.is_empty() {
                "zh".to_string()
            } else {
                target_lang.to_string()
            },
            mode: if mode.is_empty() {
                "text".to_string()
            } else {
                mode.to_string()
            },
            source_text: truncate_chars(source_text, HISTORY_TEXT_MAX),
            result_text: truncate_chars(result_text, HISTORY_TEXT_MAX),
            model: model.to_string(),
        };

        if let Some(last) = self.history.first_mut() {
            if last.source_text == entry.source_text
                && last.result_text == entry.result_text
                && last.source_lang == entry.source_lang
                && last.target_lang == entry.target_lang
            {
                *last = entry.clone();
                return entry;
            }
        }
        self.history.insert(0, entry.clone());
        if self.history.len() > self.history_limit {
            self.history.truncate(self.history_limit);
        }
        if self.favorites.len() > FAVORITES_MAX {
            self.favorites.truncate(FAVORITES_MAX);
        }
        entry
    }

    pub fn clear_history(&mut self) {
        self.history.clear();
    }

    pub fn toggle_favorite(
        &mut self,
        source_lang: &str,
        target_lang: &str,
        mode: &str,
        source_text: &str,
        result_text: &str,
        model: &str,
    ) -> bool {
        let src = source_text.trim();
        let dst = result_text.trim();
        if src.is_empty() || dst.is_empty() {
            return false;
        }
        if let Some(pos) = self
            .favorites
            .iter()
            .position(|f| f.source_text == src && f.target_lang == target_lang)
        {
            self.favorites.remove(pos);
            return false;
        }
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);
        let entry = FavoriteEntry {
            id: new_id(),
            ts: now,
            source_lang: if source_lang.is_empty() {
                "auto".to_string()
            } else {
                source_lang.to_string()
            },
            target_lang: if target_lang.is_empty() {
                "zh".to_string()
            } else {
                target_lang.to_string()
            },
            mode: if mode.is_empty() {
                "text".to_string()
            } else {
                mode.to_string()
            },
            source_text: truncate_chars(src, HISTORY_TEXT_MAX),
            result_text: truncate_chars(dst, HISTORY_TEXT_MAX),
            model: model.to_string(),
        };
        self.favorites.insert(0, entry);
        if self.favorites.len() > FAVORITES_MAX {
            self.favorites.truncate(FAVORITES_MAX);
        }
        true
    }

    pub fn remove_favorite(&mut self, id: &str) {
        self.favorites.retain(|f| f.id != id);
    }

    pub fn export_favorites_markdown(&self) -> String {
        let mut out = String::from("# AI Translator 生词本 / 收藏夹\n\n");
        for item in &self.favorites {
            out.push_str(&format!(
                "## {}\n\n- 方向：`{} → {}`（{}）\n\n{}\n\n---\n\n",
                item.source_text.replace('\n', " "),
                item.source_lang,
                item.target_lang,
                item.mode,
                item.result_text
            ));
        }
        out
    }

    pub fn export_favorites_anki_tsv(&self) -> String {
        self.favorites
            .iter()
            .map(|f| {
                let front = f.source_text.replace(['\t', '\r'], " ").replace('\n', "<br>");
                let back = f.result_text.replace(['\t', '\r'], " ").replace('\n', "<br>");
                format!("{front}\t{back}")
            })
            .collect::<Vec<_>>()
            .join("\n")
    }

    pub fn get_active_profile(&self) -> &LlmProfile {
        self.profiles
            .iter()
            .find(|p| p.id == self.active_profile_id)
            .unwrap_or(&self.profiles[0])
    }

    pub fn get_active_profile_mut(&mut self) -> &mut LlmProfile {
        if let Some(idx) = self
            .profiles
            .iter()
            .position(|p| p.id == self.active_profile_id)
        {
            &mut self.profiles[idx]
        } else {
            &mut self.profiles[0]
        }
    }

    pub fn get_profile(&self, id: &str) -> Option<&LlmProfile> {
        self.profiles.iter().find(|p| p.id == id)
    }

    pub fn upsert_profile(&mut self, mut profile: LlmProfile) {
        profile.sanitize();
        if let Some(existing) = self.profiles.iter_mut().find(|p| p.id == profile.id) {
            *existing = profile;
        } else {
            self.profiles.push(profile);
        }
    }

    pub fn remove_profile(&mut self, id: &str) -> bool {
        if self.profiles.len() <= 1 {
            return false;
        }
        let before = self.profiles.len();
        self.profiles.retain(|p| p.id != id);
        if self.profiles.len() == before {
            return false;
        }
        if self.active_profile_id == id {
            self.active_profile_id = self.profiles[0].id.clone();
        }
        true
    }
}

fn truncate_chars(s: &str, max_chars: usize) -> String {
    s.chars().take(max_chars).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn legacy_single_model_migration() {
        let raw = json!({
            "version": 1,
            "active_profile_id": "p1",
            "profiles": [{
                "id": "p1",
                "name": "DeepSeek",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "sk-test",
                "model": "deepseek-chat",
                "vision_model": "deepseek-chat"
            }],
            "history_limit": 200,
            "tts": { "voice": " ", "rate": -999, "auto_pronounce": true }
        });
        let cfg = AppConfig::from_json_value(&raw);
        assert_eq!(cfg.profiles[0].models, vec!["deepseek-chat"]);
        assert_eq!(cfg.profiles[0].vision_model, "");
        assert_eq!(cfg.history_limit, HISTORY_LIMIT_MAX);
        assert_eq!(cfg.tts.voice, "zh-CN-XiaoxiaoNeural");
        assert_eq!(cfg.tts.rate, TTS_RATE_MIN);
        assert!(cfg.tts.auto_pronounce);
        assert!(!cfg.needs_setup());
    }

    #[test]
    fn auto_resolve_skips_reasoning_models() {
        let mut p = LlmProfile::default();
        p.models = vec![
            "deepseek-r1".to_string(),
            "o3-mini".to_string(),
            "gpt-4o-mini".to_string(),
        ];
        p.model = MODEL_AUTO.to_string();
        assert_eq!(resolve_model(&p, false), "gpt-4o-mini");

        p.vision_model = "qwen-vl-max".to_string();
        assert_eq!(resolve_model(&p, true), "qwen-vl-max");
        assert_eq!(resolve_model(&p, false), "gpt-4o-mini");
    }

    #[test]
    fn history_dedup_and_limit() {
        let mut cfg = AppConfig::default();
        cfg.history_limit = 2;
        cfg.push_history("en", "zh", "text", "hi", "你好", "m1", Some(1.0));
        cfg.push_history("en", "zh", "text", "hi", "你好", "m1", Some(2.0));
        assert_eq!(cfg.history.len(), 1);
        assert_eq!(cfg.history[0].ts, 2.0);
        cfg.push_history("en", "zh", "text", "a", "甲", "m1", Some(3.0));
        cfg.push_history("en", "zh", "text", "b", "乙", "m1", Some(4.0));
        assert_eq!(cfg.history.len(), 2);
        assert_eq!(cfg.history[0].source_text, "b");
    }

    #[test]
    fn reasoning_effort_sanitization_supports_xhigh_max_and_legacy_minimal() {
        assert_eq!(sanitize_reasoning_effort("xhigh"), "xhigh");
        assert_eq!(sanitize_reasoning_effort("MAX"), "max");
        assert_eq!(sanitize_reasoning_effort("minimal"), "low");
        assert_eq!(sanitize_reasoning_effort("unknown"), "");
    }

    #[test]
    fn remove_model_preserves_at_least_one() {
        let mut p = LlmProfile::default();
        p.models = vec!["a".into(), "b".into()];
        p.model = "a".into();
        p.vision_model = "a".into();
        assert!(p.remove_model("a"));
        assert_eq!(p.model, "b");
        assert_eq!(p.vision_model, "");
        assert!(!p.remove_model("b"));
    }
}
