//! Jev (TypeSafe System One) auxiliary decision client:
//! scene routing, language detection, and translation quality scoring.

use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

use regex::Regex;
use reqwest::header::{HeaderMap, HeaderValue, ACCEPT, AUTHORIZATION, CONTENT_TYPE};
use serde_json::{json, Map, Value};
use tracing::{info, warn};

use crate::config::schema::{JevConfig, JevProtocol};
use crate::llm_client::{extract_model_ids, LlmError};

const NATIVE_PATHS: &[&str] = &[
    "/v1/systemone",
    "/api/v1/decide",
    "/v1/decide",
    "/api/v1/systemone",
];

const STRIPPABLE: &[&str] = &[
    "/chat/completions",
    "/responses",
    "/v1/systemone",
    "/api/v1/decide",
    "/v1/decide",
    "/api/v1/systemone",
    "/v1",
];

const MAX_STATE_CHARS: usize = 24_000;

const QUALITY_LEVELS: &[&str] = &[
    "严重错误：漏译、错译或与原文语义不符",
    "多处错误：基本意思可辨，但存在明显误译或生硬表达",
    "基本正确：意思准确，但有少量不自然或不够地道之处",
    "准确流畅：忠实原文且表达自然",
    "准确且地道：完全忠实原文，表达如同母语者撰写",
];

#[derive(Debug, Clone, PartialEq, Eq)]
enum RouteKind {
    Native,
    Openai,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct Route {
    kind: RouteKind,
    url: String,
}

fn route_cache() -> &'static Mutex<HashMap<String, Route>> {
    static CACHE: OnceLock<Mutex<HashMap<String, Route>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

pub fn base_root(base_url: &str) -> String {
    let mut raw = base_url.trim().trim_end_matches('/').to_string();
    let mut changed = true;
    while changed {
        changed = false;
        for suffix in STRIPPABLE {
            if let Some(stripped) = raw.strip_suffix(suffix) {
                raw = stripped.trim_end_matches('/').to_string();
                changed = true;
                break;
            }
        }
    }
    raw
}

pub fn native_candidates(base_url: &str) -> Vec<String> {
    let raw = base_url.trim().trim_end_matches('/');
    if raw.ends_with("/systemone") || raw.ends_with("/decide") {
        return vec![raw.to_string()];
    }
    let root = base_root(raw);
    if root.is_empty() {
        return Vec::new();
    }
    NATIVE_PATHS.iter().map(|p| format!("{root}{p}")).collect()
}

pub fn openai_endpoint(base_url: &str) -> String {
    let root = base_root(base_url);
    if root.is_empty() {
        String::new()
    } else {
        format!("{root}/v1/chat/completions")
    }
}

fn coerce_answer(raw: &Value, qtype: &str) -> Value {
    if raw.is_object() {
        return raw.clone();
    }
    match qtype {
        "choice" => {
            let s = raw
                .as_str()
                .map(String::from)
                .unwrap_or_else(|| raw.to_string());
            json!({ "choice": s })
        }
        "noul" => {
            let val = raw
                .as_f64()
                .or_else(|| raw.as_str().and_then(|s| s.trim().parse::<f64>().ok()))
                .unwrap_or_else(|| {
                    let s = raw.as_str().unwrap_or("").trim().to_ascii_lowercase();
                    if s == "yes" || s == "true" {
                        1.0
                    } else {
                        0.0
                    }
                });
            json!({ "noul": val })
        }
        "score" => {
            if let Some(n) = raw
                .as_f64()
                .or_else(|| raw.as_str().and_then(|s| s.trim().parse::<f64>().ok()))
            {
                json!({ "score": n })
            } else {
                json!({})
            }
        }
        _ => json!({ "value": raw }),
    }
}

fn extract_json_object(text: &str) -> Option<Map<String, Value>> {
    static FENCE_RE: OnceLock<Regex> = OnceLock::new();
    let mut cleaned = text.trim().to_string();
    if cleaned.is_empty() {
        return None;
    }
    let fence = FENCE_RE.get_or_init(|| Regex::new(r"(?is)```(?:json)?\s*(.*?)\s*```").unwrap());
    if let Some(cap) = fence.captures(&cleaned) {
        if let Some(m) = cap.get(1) {
            cleaned = m.as_str().trim().to_string();
        }
    }
    if let Ok(Value::Object(map)) = serde_json::from_str::<Value>(&cleaned) {
        return Some(map);
    }
    if let (Some(start), Some(end)) = (cleaned.find('{'), cleaned.rfind('}')) {
        if start < end {
            if let Ok(Value::Object(map)) = serde_json::from_str::<Value>(&cleaned[start..=end]) {
                return Some(map);
            }
        }
    }
    None
}

enum RouteAttemptError {
    Mismatch(String),
    HttpRetryable(String),
    Fatal(LlmError),
}

#[derive(Debug, Clone)]
pub struct JevClient {
    config: JevConfig,
    http: reqwest::Client,
}

impl JevClient {
    pub fn new(config: JevConfig) -> Result<Self, LlmError> {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs_f64(config.timeout_s.max(1.0)))
            .build()
            .map_err(|e| LlmError::api(format!("Jev HTTP client error: {e}"), None))?;
        Ok(Self { config, http })
    }

    pub fn is_configured(&self) -> bool {
        !self.config.base_url.trim().is_empty()
    }

    fn cache_key(&self) -> String {
        let proto = match self.config.api_protocol {
            JevProtocol::Auto => "auto",
            JevProtocol::Native => "native",
            JevProtocol::Openai => "openai",
        };
        format!(
            "{proto}|{}",
            self.config.base_url.trim().trim_end_matches('/')
        )
    }

    fn routes(&self) -> Vec<Route> {
        let base = &self.config.base_url;
        match self.config.api_protocol {
            JevProtocol::Native => native_candidates(base)
                .into_iter()
                .map(|url| Route {
                    kind: RouteKind::Native,
                    url,
                })
                .collect(),
            JevProtocol::Openai => {
                let u = openai_endpoint(base);
                if u.is_empty() {
                    Vec::new()
                } else {
                    vec![Route {
                        kind: RouteKind::Openai,
                        url: u,
                    }]
                }
            }
            JevProtocol::Auto => {
                let mut routes: Vec<Route> = native_candidates(base)
                    .into_iter()
                    .map(|url| Route {
                        kind: RouteKind::Native,
                        url,
                    })
                    .collect();
                let u = openai_endpoint(base);
                if !u.is_empty() {
                    routes.push(Route {
                        kind: RouteKind::Openai,
                        url: u,
                    });
                }
                routes
            }
        }
    }

    fn candidate_routes(&self) -> Vec<Route> {
        let routes = self.routes();
        let cached = route_cache()
            .lock()
            .ok()
            .and_then(|guard| guard.get(&self.cache_key()).cloned());
        if let Some(c) = cached {
            if routes.contains(&c) {
                let mut ordered = vec![c.clone()];
                ordered.extend(routes.into_iter().filter(|r| r != &c));
                return ordered;
            }
        }
        routes
    }

    fn headers(&self) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
        headers.insert(ACCEPT, HeaderValue::from_static("application/json"));
        let key = self.config.api_key.trim();
        if !key.is_empty() {
            if let Ok(val) = HeaderValue::from_str(&format!("Bearer {key}")) {
                headers.insert(AUTHORIZATION, val);
            }
        }
        headers
    }

    async fn post(&self, url: &str, body: &Value) -> Result<Value, RouteAttemptError> {
        let resp = self
            .http
            .post(url)
            .headers(self.headers())
            .json(body)
            .send()
            .await
            .map_err(|e| {
                if e.is_timeout() {
                    warn!("jev request timed out after {}s", self.config.timeout_s);
                    RouteAttemptError::Fatal(LlmError::Timeout(self.config.timeout_s))
                } else {
                    RouteAttemptError::Fatal(LlmError::api(format!("Jev 网络错误：{e}"), None))
                }
            })?;

        let status = resp.status().as_u16();
        let text = resp.text().await.unwrap_or_default();
        if status == 401 || status == 403 {
            let preview: String = text.chars().take(200).collect();
            return Err(RouteAttemptError::Fatal(LlmError::Auth {
                status,
                detail: preview,
            }));
        }
        if status == 429 {
            let preview: String = text.chars().take(200).collect();
            return Err(RouteAttemptError::Fatal(LlmError::RateLimit(preview)));
        }
        if matches!(status, 400 | 404 | 405 | 422) {
            let preview: String = text.chars().take(300).collect();
            return Err(RouteAttemptError::HttpRetryable(format!(
                "Jev 接口错误 {status}：{preview}"
            )));
        }
        if status >= 400 {
            let preview: String = text.chars().take(300).collect();
            return Err(RouteAttemptError::Fatal(LlmError::api(
                format!("Jev 接口错误 {status}：{preview}"),
                Some(status),
            )));
        }
        serde_json::from_str::<Value>(&text)
            .map_err(|_| RouteAttemptError::Fatal(LlmError::api("Jev 返回的不是合法 JSON", Some(status))))
    }

    pub async fn decide(
        &self,
        state: &str,
        questions: &Map<String, Value>,
    ) -> Result<Map<String, Value>, LlmError> {
        if questions.is_empty() {
            return Ok(Map::new());
        }
        let state_trimmed = if state.chars().count() > MAX_STATE_CHARS {
            let prefix: String = state.chars().take(MAX_STATE_CHARS).collect();
            format!("{prefix}…[truncated]")
        } else {
            state.to_string()
        };

        let model_name = if self.config.model.trim().is_empty() {
            "jev-latest"
        } else {
            self.config.model.trim()
        };
        let routes = self.candidate_routes();
        if routes.is_empty() {
            return Err(LlmError::api("Jev Base URL 未配置", None));
        }

        let mut errors = Vec::new();
        for route in routes {
            let attempt = match route.kind {
                RouteKind::Native => {
                    self.decide_native(&route.url, &state_trimmed, questions, model_name)
                        .await
                }
                RouteKind::Openai => {
                    self.decide_openai(&route.url, &state_trimmed, questions, model_name)
                        .await
                }
            };
            match attempt {
                Ok(answers) => {
                    if let Ok(mut guard) = route_cache().lock() {
                        guard.insert(self.cache_key(), route);
                    }
                    return Ok(answers);
                }
                Err(RouteAttemptError::Fatal(err)) => return Err(err),
                Err(RouteAttemptError::Mismatch(msg) | RouteAttemptError::HttpRetryable(msg)) => {
                    info!("jev route failed ({}): {}", route.url, msg);
                    errors.push(format!("{} → {msg}", route.url));
                }
            }
        }
        let detail = if errors.is_empty() {
            "无可用端点".to_string()
        } else {
            errors.join("；")
        };
        Err(LlmError::api(format!("Jev 无可用的接口地址：{detail}"), None))
    }

    async fn decide_native(
        &self,
        url: &str,
        state: &str,
        questions: &Map<String, Value>,
        model: &str,
    ) -> Result<Map<String, Value>, RouteAttemptError> {
        let data = self
            .post(
                url,
                &json!({ "state": state, "model": model, "questions": questions }),
            )
            .await?;

        if let Some(answers) = extract_native_answers(&data) {
            return Ok(answers);
        }
        if let Some(salvaged) = answers_from_text_envelope(&data, questions) {
            return Ok(salvaged);
        }
        let preview: String = data.to_string().chars().take(200).collect();
        Err(RouteAttemptError::Mismatch(format!(
            "Jev 响应缺少 answers：{preview}"
        )))
    }

    async fn decide_openai(
        &self,
        url: &str,
        state: &str,
        questions: &Map<String, Value>,
        model: &str,
    ) -> Result<Map<String, Value>, RouteAttemptError> {
        let system = "You are a structured decision engine. You never write prose or \
explain yourself. Given a state and a map of typed questions, \
reply with ONLY a JSON object that maps each question id to its \
answer: choice → {\"choice\": \"<one of the criteria keys>\"}, \
score → {\"score\": <number>}, \
noul → {\"noul\": <probability between 0 and 1>}. \
Use exactly the question ids given. No markdown, no code fences, no commentary.";
        let user = json!({ "state": state, "questions": questions }).to_string();
        let data = self
            .post(
                url,
                &json!({
                    "model": model,
                    "messages": [
                        { "role": "system", "content": system },
                        { "role": "user", "content": user }
                    ],
                    "temperature": 0,
                    "stream": false
                }),
            )
            .await?;

        if let Some(answers) = extract_native_answers(&data) {
            return Ok(answers);
        }
        if let Some(salvaged) = answers_from_text_envelope(&data, questions) {
            return Ok(salvaged);
        }
        let preview: String = data.to_string().chars().take(200).collect();
        Err(RouteAttemptError::Mismatch(format!(
            "Jev 未返回可解析的答案：{preview}"
        )))
    }

    pub async fn detect_language(
        &self,
        text: &str,
        languages: &[(&str, &str)],
    ) -> Result<Option<String>, LlmError> {
        let snippet = text.trim();
        if snippet.is_empty() || languages.is_empty() {
            return Ok(None);
        }
        let mut criteria = Map::new();
        for (code, label) in languages {
            criteria.insert((*code).to_string(), json!(label));
        }
        let mut questions = Map::new();
        questions.insert(
            "source_language".into(),
            json!({
                "type": "choice",
                "instructions": "Which language is this text written in? Choose the single best match. Ignore code, URLs and numbers when deciding.",
                "criteria": criteria
            }),
        );
        let answers = self.decide(snippet, &questions).await?;
        let picked = answers
            .get("source_language")
            .and_then(|v| v.get("choice"))
            .and_then(Value::as_str)
            .map(str::trim)
            .unwrap_or("");
        if languages.iter().any(|(code, _)| *code == picked) {
            return Ok(Some(picked.to_string()));
        }
        for (code, label) in languages {
            if !picked.is_empty() && picked == *label {
                return Ok(Some((*code).to_string()));
            }
        }
        Ok(None)
    }

    pub async fn route_scene(
        &self,
        text: &str,
        scenes: &[(String, String, String)],
    ) -> Result<Option<String>, LlmError> {
        let snippet = text.trim();
        if snippet.is_empty() || scenes.is_empty() {
            return Ok(None);
        }
        let mut criteria = Map::new();
        for (sid, label, hint) in scenes {
            let desc = if hint.trim().is_empty() {
                label.clone()
            } else {
                format!("{label}：{}", hint.trim())
            };
            criteria.insert(sid.clone(), json!(desc));
        }
        let mut questions = Map::new();
        questions.insert(
            "scene".into(),
            json!({
                "type": "choice",
                "instructions": "Which translation style fits this text best? Judge by the domain, register and intended audience.",
                "criteria": criteria
            }),
        );
        let answers = self.decide(snippet, &questions).await?;
        let picked = answers
            .get("scene")
            .and_then(|v| v.get("choice"))
            .and_then(Value::as_str)
            .map(str::trim)
            .unwrap_or("");
        if scenes.iter().any(|(sid, _, _)| sid == picked) {
            Ok(Some(picked.to_string()))
        } else {
            Ok(None)
        }
    }

    pub async fn score_quality(
        &self,
        source: &str,
        translation: &str,
    ) -> Result<Option<f64>, LlmError> {
        let src = source.trim();
        let dst = translation.trim();
        if src.is_empty() || dst.is_empty() {
            return Ok(None);
        }
        let src_cut: String = src.chars().take(12_000).collect();
        let dst_cut: String = dst.chars().take(12_000).collect();
        let state = json!({ "source": src_cut, "translation": dst_cut }).to_string();
        let mut questions = Map::new();
        questions.insert(
            "quality".into(),
            json!({
                "type": "score",
                "instructions": "Rate the translation against the source. Consider faithfulness, completeness, fluency and naturalness.",
                "criteria": QUALITY_LEVELS
            }),
        );
        let answers = self.decide(&state, &questions).await?;
        let raw = answers.get("quality").and_then(|v| v.get("score"));
        let val = raw.and_then(|v| {
            v.as_f64()
                .or_else(|| v.as_str().and_then(|s| s.trim().parse::<f64>().ok()))
        });
        let Some(score) = val else {
            return Ok(None);
        };
        let top = (QUALITY_LEVELS.len() - 1) as f64;
        Ok(Some((score / top).clamp(0.0, 1.0)))
    }

    pub async fn test_connection(&self) -> Result<String, LlmError> {
        let mut questions = Map::new();
        questions.insert(
            "english".into(),
            json!({
                "type": "noul",
                "instructions": "Is this text written in English?"
            }),
        );
        let answers = self.decide("Hello, world.", &questions).await?;
        let noul = answers
            .get("english")
            .and_then(|v| v.get("noul"))
            .and_then(|v| v.as_f64().or_else(|| v.as_str().and_then(|s| s.parse().ok())));
        let Some(prob) = noul else {
            return Err(LlmError::api("Jev 已响应，但未返回预期字段", None));
        };
        Ok(format!(
            "Jev 连接正常 · 模型 {} · 置信度 {:.2}",
            self.config.model, prob
        ))
    }

    pub async fn list_models(&self) -> Result<Vec<String>, LlmError> {
        let root = base_root(&self.config.base_url);
        if root.is_empty() {
            return Err(LlmError::api("Jev Base URL 未配置", None));
        }
        let mut last_err = None;
        for url in [format!("{root}/v1/models"), format!("{root}/models")] {
            let resp = self
                .http
                .get(&url)
                .headers(self.headers())
                .send()
                .await
                .map_err(|e| {
                    if e.is_timeout() {
                        LlmError::Timeout(self.config.timeout_s)
                    } else {
                        LlmError::api(format!("Jev 网络错误：{e}"), None)
                    }
                })?;
            let status = resp.status().as_u16();
            let text = resp.text().await.unwrap_or_default();
            if status == 401 || status == 403 {
                let preview: String = text.chars().take(200).collect();
                return Err(LlmError::Auth {
                    status,
                    detail: preview,
                });
            }
            if status >= 400 {
                let preview: String = text.chars().take(200).collect();
                last_err = Some(LlmError::api(
                    format!("Jev 接口错误 {status}：{preview}"),
                    Some(status),
                ));
                continue;
            }
            let Ok(data) = serde_json::from_str::<Value>(&text) else {
                return Err(LlmError::api("Jev 返回的不是合法 JSON", Some(status)));
            };
            let models = extract_model_ids(&data);
            if !models.is_empty() {
                return Ok(models);
            }
            last_err = Some(LlmError::api("Jev 模型列表为空", Some(status)));
        }
        Err(last_err.unwrap_or_else(|| LlmError::api("Jev 模型列表不可用", None)))
    }
}

fn extract_native_answers(data: &Value) -> Option<Map<String, Value>> {
    let obj = data.as_object()?;
    let direct = obj.get("answers").and_then(Value::as_object);
    let answers = direct.or_else(|| {
        ["result", "data", "output"].iter().find_map(|key| {
            obj.get(*key)
                .and_then(Value::as_object)
                .and_then(|inner| inner.get("answers"))
                .and_then(Value::as_object)
        })
    })?;
    let mut out = Map::new();
    for (k, v) in answers {
        if v.is_object() {
            out.insert(k.clone(), v.clone());
        }
    }
    Some(out)
}

fn openai_content(data: &Value) -> Option<String> {
    let obj = data.as_object()?;
    if let Some(choices) = obj.get("choices").and_then(Value::as_array) {
        if let Some(msg) = choices.first().and_then(|c| c.get("message")) {
            if let Some(s) = msg.get("content").and_then(Value::as_str) {
                return Some(s.to_string());
            }
            if let Some(arr) = msg.get("content").and_then(Value::as_array) {
                let joined: String = arr
                    .iter()
                    .filter_map(|p| p.get("text").and_then(Value::as_str))
                    .collect();
                return Some(joined);
            }
        }
    }
    obj.get("output_text")
        .and_then(Value::as_str)
        .map(String::from)
}

fn answers_from_text_envelope(
    data: &Value,
    questions: &Map<String, Value>,
) -> Option<Map<String, Value>> {
    let content = openai_content(data)?;
    let parsed = extract_json_object(&content)?;
    let answers_raw = parsed
        .get("answers")
        .and_then(Value::as_object)
        .unwrap_or(&parsed);
    let mut out = Map::new();
    for (qid, spec) in questions {
        if let Some(raw_val) = answers_raw.get(qid) {
            let qtype = spec.get("type").and_then(Value::as_str).unwrap_or("");
            out.insert(qid.clone(), coerce_answer(raw_val, qtype));
        }
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base_root_unwinds_endpoints() {
        assert_eq!(
            base_root("https://api.typesafe.ai/v1/systemone/"),
            "https://api.typesafe.ai"
        );
        assert_eq!(
            base_root("https://relay.example.com/v1/chat/completions"),
            "https://relay.example.com"
        );
    }

    #[test]
    fn extracts_fenced_json_answers() {
        let obj = extract_json_object("```json\n{\"scene\": \"technical\"}\n```").unwrap();
        assert_eq!(obj.get("scene").and_then(Value::as_str), Some("technical"));
    }
}
