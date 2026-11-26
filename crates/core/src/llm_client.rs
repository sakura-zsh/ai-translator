//! OpenAI-compatible LLM client supporting Chat Completions & Responses APIs,
//! including real-time SSE streaming with chain-of-thought filtering.

use std::collections::BTreeSet;
use std::sync::OnceLock;
use std::time::Duration;

use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use futures_util::StreamExt;
use regex::Regex;
use reqwest::header::{HeaderMap, HeaderValue, ACCEPT, AUTHORIZATION, CONTENT_TYPE};
use serde_json::{json, Map, Value};
use thiserror::Error;
use tracing::warn;

use crate::config::schema::{resolve_model, ApiProtocol, LlmProfile};
use crate::imaging::sniff_image_mime;

#[derive(Debug, Error)]
pub enum LlmError {
    #[error("Authentication failed ({status}): {detail}")]
    Auth { status: u16, detail: String },
    #[error("Rate limited: {0}")]
    RateLimit(String),
    #[error("Request timed out after {0}s")]
    Timeout(f64),
    #[error("{message}")]
    Api {
        message: String,
        status_code: Option<u16>,
    },
}

impl LlmError {
    pub fn api(message: impl Into<String>, status_code: Option<u16>) -> Self {
        Self::Api {
            message: message.into(),
            status_code,
        }
    }
}

pub fn extract_tagged_final(text: &str) -> String {
    static PAIR_RE: OnceLock<Regex> = OnceLock::new();
    static UNCLOSED_RE: OnceLock<Regex> = OnceLock::new();

    let pair = PAIR_RE.get_or_init(|| {
        Regex::new(r"(?is)<final_translation>\s*(.*?)\s*</final_translation>").unwrap()
    });
    for cap in pair.captures_iter(text) {
        if let Some(m) = cap.get(1) {
            let trimmed = m.as_str().trim();
            if !trimmed.is_empty() {
                return trimmed.to_string();
            }
        }
    }

    let unclosed =
        UNCLOSED_RE.get_or_init(|| Regex::new(r"(?is)<final_translation>\s*(.+)$").unwrap());
    if let Some(cap) = unclosed.captures(text) {
        if let Some(m) = cap.get(1) {
            let trimmed = m.as_str().trim();
            if !trimmed.is_empty() {
                return trimmed.to_string();
            }
        }
    }
    String::new()
}

pub fn strip_reasoning(text: &str) -> String {
    static THINK_PAIR: OnceLock<Regex> = OnceLock::new();
    static THINKING_PAIR: OnceLock<Regex> = OnceLock::new();
    static REASONING_PAIR: OnceLock<Regex> = OnceLock::new();
    static UNCLOSED: OnceLock<Regex> = OnceLock::new();

    let r1 = THINK_PAIR.get_or_init(|| Regex::new(r"(?is)<think\b[^>]*>.*?</think\s*>").unwrap());
    let r2 = THINKING_PAIR
        .get_or_init(|| Regex::new(r"(?is)<thinking\b[^>]*>.*?</thinking\s*>").unwrap());
    let r3 = REASONING_PAIR
        .get_or_init(|| Regex::new(r"(?is)<reasoning\b[^>]*>.*?</reasoning\s*>").unwrap());
    let r4 = UNCLOSED
        .get_or_init(|| Regex::new(r"(?is)<(?:think|thinking|reasoning)\b[^>]*>.*$").unwrap());

    let s = r1.replace_all(text, "");
    let s = r2.replace_all(&s, "");
    let s = r3.replace_all(&s, "");
    let s = r4.replace_all(&s, "");
    s.trim().to_string()
}

/// Incremental SSE preview sanitizer: hides `<think>/<thinking>/<reasoning>` blocks
/// and strips `<final_translation>` wrapper tags while streaming tokens.
#[derive(Default)]
struct StreamSanitizer {
    raw: String,
    emitted: String,
}

impl StreamSanitizer {
    fn push(&mut self, chunk: &str) -> Option<String> {
        self.raw.push_str(chunk);
        let visible = self.compute_visible();
        if visible.len() > self.emitted.len() && visible.starts_with(&self.emitted) {
            let delta = visible[self.emitted.len()..].to_string();
            self.emitted = visible;
            if delta.is_empty() {
                None
            } else {
                Some(delta)
            }
        } else {
            None
        }
    }

    fn compute_visible(&self) -> String {
        let mut s = strip_reasoning(&self.raw);
        if let Some(idx) = s.find("<final_translation>") {
            s = s[idx + "<final_translation>".len()..].to_string();
        }
        if let Some(end_idx) = s.find("</final_translation>") {
            s.truncate(end_idx);
        }
        // Hold back trailing incomplete tag prefix like "<final" or "</final_translation"
        if let Some(lt) = s.rfind('<') {
            if !s[lt..].contains('>') && s.len() - lt <= 24 {
                s.truncate(lt);
            }
        }
        s.trim_start().to_string()
    }
}

pub fn extract_model_ids(data: &Value) -> Vec<String> {
    let items: Option<&Vec<Value>> = if let Some(obj) = data.as_object() {
        obj.get("data")
            .and_then(Value::as_array)
            .or_else(|| obj.get("models").and_then(Value::as_array))
    } else {
        data.as_array()
    };

    let mut ids = BTreeSet::new();
    if let Some(list) = items {
        for item in list {
            if let Some(obj) = item.as_object() {
                let mid = obj
                    .get("id")
                    .or_else(|| obj.get("name"))
                    .or_else(|| obj.get("model"))
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .filter(|s| !s.is_empty());
                if let Some(id) = mid {
                    ids.insert(id.to_string());
                }
            } else if let Some(s) = item.as_str() {
                let trimmed = s.trim();
                if !trimmed.is_empty() {
                    ids.insert(trimmed.to_string());
                }
            }
        }
    }
    ids.into_iter().collect()
}

#[derive(Debug, Clone)]
pub struct ChatOutput {
    pub text: String,
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct LlmClient {
    profile: LlmProfile,
    http: reqwest::Client,
}

impl LlmClient {
    pub fn new(profile: LlmProfile) -> Result<Self, LlmError> {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs_f64(profile.timeout_s.max(1.0)))
            .build()
            .map_err(|e| LlmError::api(format!("HTTP client error: {e}"), None))?;
        Ok(Self { profile, http })
    }

    pub fn api_base(&self) -> String {
        let mut base = self.profile.base_url.trim().trim_end_matches('/').to_string();
        for suffix in ["/chat/completions", "/responses"] {
            if let Some(stripped) = base.strip_suffix(suffix) {
                base = stripped.to_string();
            }
        }
        base
    }

    pub fn endpoint(&self) -> String {
        let base = self.api_base();
        match self.profile.api_protocol {
            ApiProtocol::Responses => format!("{base}/responses"),
            ApiProtocol::ChatCompletions => format!("{base}/chat/completions"),
        }
    }

    pub fn models_endpoint(&self) -> String {
        format!("{}/models", self.api_base())
    }

    fn headers(&self) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
        headers.insert(ACCEPT, HeaderValue::from_static("application/json"));
        let key = self.profile.api_key.trim();
        if !key.is_empty() {
            if let Ok(val) = HeaderValue::from_str(&format!("Bearer {key}")) {
                headers.insert(AUTHORIZATION, val);
            }
        }
        headers
    }

    fn build_chat_body(
        &self,
        messages: &[Value],
        model_override: Option<&str>,
        temperature: Option<f64>,
        max_tokens: Option<u32>,
        stream: bool,
    ) -> Map<String, Value> {
        let model_name = model_override
            .map(String::from)
            .unwrap_or_else(|| resolve_model(&self.profile, false));
        let temp = temperature.unwrap_or(self.profile.temperature);
        let tokens = max_tokens.unwrap_or(self.profile.max_tokens);

        let mut body = match self.profile.api_protocol {
            ApiProtocol::Responses => {
                build_responses_body(messages, &model_name, temp, tokens, false, stream)
            }
            ApiProtocol::ChatCompletions => {
                let mut m = Map::new();
                m.insert("model".into(), json!(model_name));
                m.insert("messages".into(), Value::Array(messages.to_vec()));
                m.insert("temperature".into(), json!(temp));
                m.insert("max_tokens".into(), json!(tokens));
                m.insert("stream".into(), json!(stream));
                m
            }
        };

        self.apply_reasoning_effort(&mut body);
        body
    }

    pub async fn chat(
        &self,
        messages: &[Value],
        model_override: Option<&str>,
        temperature: Option<f64>,
        max_tokens: Option<u32>,
    ) -> Result<ChatOutput, LlmError> {
        let body = self.build_chat_body(messages, model_override, temperature, max_tokens, false);
        self.request_with_effort_fallback(body).await
    }

    pub async fn chat_stream<F, R>(
        &self,
        messages: &[Value],
        model_override: Option<&str>,
        mut on_delta: F,
        mut on_reset: R,
    ) -> Result<ChatOutput, LlmError>
    where
        F: FnMut(&str) + Send,
        R: FnMut() + Send,
    {
        let body = self.build_chat_body(messages, model_override, None, None, true);
        match self.send_stream_request(&body, &mut on_delta).await {
            Ok(text) => Ok(ChatOutput {
                text,
                warnings: Vec::new(),
            }),
            Err(LlmError::Api {
                message,
                status_code,
            }) => {
                let effort_set = !self.profile.reasoning_effort.trim().is_empty();
                let is_400_422 = matches!(status_code, Some(400 | 422));
                let lower = message.to_ascii_lowercase();
                if effort_set && is_400_422 && (lower.contains("reason") || lower.contains("effort"))
                {
                    warn!(
                        "API rejected reasoning_effort ({:?}); retrying stream without it",
                        status_code
                    );
                    on_reset();
                    let mut stripped = body;
                    stripped.remove("reasoning_effort");
                    stripped.remove("reasoning");
                    let text = self.send_stream_request(&stripped, &mut on_delta).await?;
                    return Ok(ChatOutput {
                        text,
                        warnings: vec!["网关不支持推理强度，本次已按默认强度发送".to_string()],
                    });
                }
                Err(LlmError::Api {
                    message,
                    status_code,
                })
            }
            Err(other) => Err(other),
        }
    }

    pub async fn chat_vision(
        &self,
        system_prompt: &str,
        user_text: &str,
        image_bytes: &[u8],
        model_override: Option<&str>,
    ) -> Result<ChatOutput, LlmError> {
        let mime = sniff_image_mime(image_bytes);
        let b64 = BASE64.encode(image_bytes);
        let data_url = format!("data:{mime};base64,{b64}");
        let model_name = model_override
            .map(String::from)
            .unwrap_or_else(|| resolve_model(&self.profile, true));
        let temp = self.profile.temperature;
        let tokens = self.profile.max_tokens;

        let mut body = match self.profile.api_protocol {
            ApiProtocol::Responses => {
                let messages = vec![
                    json!({ "role": "system", "content": system_prompt }),
                    json!({
                        "role": "user",
                        "content": [
                            { "type": "input_text", "text": user_text },
                            { "type": "input_image", "image_url": data_url }
                        ]
                    }),
                ];
                build_responses_body(&messages, &model_name, temp, tokens, true, false)
            }
            ApiProtocol::ChatCompletions => {
                let messages = vec![
                    json!({ "role": "system", "content": system_prompt }),
                    json!({
                        "role": "user",
                        "content": [
                            { "type": "text", "text": user_text },
                            { "type": "image_url", "image_url": { "url": data_url } }
                        ]
                    }),
                ];
                let mut m = Map::new();
                m.insert("model".into(), json!(model_name));
                m.insert("messages".into(), Value::Array(messages));
                m.insert("temperature".into(), json!(temp));
                m.insert("max_tokens".into(), json!(tokens));
                m.insert("stream".into(), json!(false));
                m
            }
        };

        self.apply_reasoning_effort(&mut body);
        self.request_with_effort_fallback(body).await
    }

    pub async fn test_connection(&self) -> Result<String, LlmError> {
        let msgs = vec![json!({ "role": "user", "content": "Reply with exactly: ok" })];
        let out = self.chat(&msgs, None, Some(0.0), Some(16)).await?;
        Ok(out.text)
    }

    pub async fn list_models(&self) -> Result<Vec<String>, LlmError> {
        let resp = self
            .http
            .get(self.models_endpoint())
            .headers(self.headers())
            .send()
            .await
            .map_err(|e| self.map_reqwest_err(e))?;

        let status = resp.status().as_u16();
        let body_text = resp.text().await.unwrap_or_default();
        check_http_status(status, &body_text)?;

        let data: Value = serde_json::from_str(&body_text)
            .map_err(|_| LlmError::api("Invalid JSON in models response", Some(status)))?;
        let models = extract_model_ids(&data);
        if models.is_empty() {
            return Err(LlmError::api(
                "Model list is empty or has an unexpected shape",
                Some(status),
            ));
        }
        Ok(models)
    }

    fn apply_reasoning_effort(&self, body: &mut Map<String, Value>) {
        let effort = self.profile.reasoning_effort.trim();
        if effort.is_empty() {
            return;
        }
        match self.profile.api_protocol {
            ApiProtocol::Responses => {
                body.insert("reasoning".into(), json!({ "effort": effort }));
            }
            ApiProtocol::ChatCompletions => {
                body.insert("reasoning_effort".into(), json!(effort));
            }
        }
    }

    async fn request_with_effort_fallback(
        &self,
        body: Map<String, Value>,
    ) -> Result<ChatOutput, LlmError> {
        match self.send_request(&body).await {
            Ok(text) => Ok(ChatOutput {
                text,
                warnings: Vec::new(),
            }),
            Err(LlmError::Api {
                message,
                status_code,
            }) => {
                let effort_set = !self.profile.reasoning_effort.trim().is_empty();
                let is_400_422 = matches!(status_code, Some(400 | 422));
                let lower = message.to_ascii_lowercase();
                if !effort_set
                    || !is_400_422
                    || (!lower.contains("reason") && !lower.contains("effort"))
                {
                    return Err(LlmError::Api {
                        message,
                        status_code,
                    });
                }
                warn!(
                    "API rejected reasoning_effort ({:?}); retrying without it",
                    status_code
                );
                let mut stripped = body;
                stripped.remove("reasoning_effort");
                stripped.remove("reasoning");
                let text = self.send_request(&stripped).await?;
                Ok(ChatOutput {
                    text,
                    warnings: vec!["网关不支持推理强度，本次已按默认强度发送".to_string()],
                })
            }
            Err(other) => Err(other),
        }
    }

    async fn send_stream_request<F>(
        &self,
        body: &Map<String, Value>,
        on_delta: &mut F,
    ) -> Result<String, LlmError>
    where
        F: FnMut(&str) + Send,
    {
        let mut headers = self.headers();
        headers.insert(ACCEPT, HeaderValue::from_static("text/event-stream"));

        let resp = self
            .http
            .post(self.endpoint())
            .headers(headers)
            .json(body)
            .send()
            .await
            .map_err(|e| self.map_reqwest_err(e))?;

        let status = resp.status().as_u16();
        if status >= 400 {
            let body_text = resp.text().await.unwrap_or_default();
            check_http_status(status, &body_text)?;
            return Err(LlmError::api(format!("API error {status}"), Some(status)));
        }

        let content_type = resp
            .headers()
            .get(CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .to_ascii_lowercase();

        // Some relays ignore `stream: true` and reply with plain `application/json`.
        if content_type.contains("application/json") {
            let text = resp.text().await.unwrap_or_default();
            let cleaned = parse_json_response_body(&text, status)?;
            on_delta(&cleaned);
            return Ok(cleaned);
        }

        let mut stream = resp.bytes_stream();
        let mut line_buf = String::new();
        let mut raw_full = String::new();
        let mut sanitizer = StreamSanitizer::default();
        let mut full_body_if_non_sse = String::new();

        while let Some(chunk_res) = stream.next().await {
            let chunk = chunk_res.map_err(|e| self.map_reqwest_err(e))?;
            let text_piece = String::from_utf8_lossy(&chunk);
            if full_body_if_non_sse.len() < 16384 {
                full_body_if_non_sse.push_str(&text_piece);
            }
            line_buf.push_str(&text_piece);

            while let Some(nl_idx) = line_buf.find('\n') {
                let line = line_buf[..nl_idx].trim_end_matches('\r').to_string();
                line_buf.drain(..=nl_idx);

                let trimmed = line.trim();
                if let Some(data_payload) = trimmed.strip_prefix("data:") {
                    let payload = data_payload.trim();
                    if payload.is_empty() || payload == "[DONE]" {
                        continue;
                    }
                    if let Ok(val) = serde_json::from_str::<Value>(payload) {
                        if let Some(delta) = extract_sse_delta(&val) {
                            raw_full.push_str(&delta);
                            if let Some(safe) = sanitizer.push(&delta) {
                                on_delta(&safe);
                            }
                        } else if raw_full.is_empty() {
                            if let Some(done_text) = extract_sse_completed_text(&val) {
                                raw_full.push_str(&done_text);
                                if let Some(safe) = sanitizer.push(&done_text) {
                                    on_delta(&safe);
                                }
                            }
                        }
                    }
                }
            }
        }

        // Flush any trailing line without newline
        if let Some(data_payload) = line_buf.trim().strip_prefix("data:") {
            let payload = data_payload.trim();
            if !payload.is_empty() && payload != "[DONE]" {
                if let Ok(val) = serde_json::from_str::<Value>(payload) {
                    if let Some(delta) = extract_sse_delta(&val) {
                        raw_full.push_str(&delta);
                        if let Some(safe) = sanitizer.push(&delta) {
                            on_delta(&safe);
                        }
                    }
                }
            }
        }

        // Fallback if server didn't send SSE frames at all (e.g., returned raw JSON without JSON header)
        if raw_full.is_empty() && !full_body_if_non_sse.trim().is_empty() {
            if let Ok(cleaned) = parse_json_response_body(&full_body_if_non_sse, status) {
                on_delta(&cleaned);
                return Ok(cleaned);
            }
        }

        finalize_reply(&raw_full, status)
    }

    async fn send_request(&self, body: &Map<String, Value>) -> Result<String, LlmError> {
        let resp = self
            .http
            .post(self.endpoint())
            .headers(self.headers())
            .json(body)
            .send()
            .await
            .map_err(|e| self.map_reqwest_err(e))?;

        let status = resp.status().as_u16();
        let body_text = resp.text().await.unwrap_or_default();
        check_http_status(status, &body_text)?;
        parse_json_response_body(&body_text, status)
    }

    fn map_reqwest_err(&self, err: reqwest::Error) -> LlmError {
        if err.is_timeout() {
            LlmError::Timeout(self.profile.timeout_s)
        } else {
            LlmError::api(format!("Network error: {err}"), None)
        }
    }
}

fn parse_json_response_body(body_text: &str, status: u16) -> Result<String, LlmError> {
    let data: Value = serde_json::from_str(body_text)
        .map_err(|_| LlmError::api("Invalid JSON in API response", Some(status)))?;
    let Some(content) = extract_response_text(&data) else {
        let preview: String = body_text.chars().take(300).collect();
        return Err(LlmError::api(
            format!("Unexpected response shape: {preview}"),
            Some(status),
        ));
    };
    finalize_reply(&content, status)
}

fn finalize_reply(raw: &str, status: u16) -> Result<String, LlmError> {
    let tagged = extract_tagged_final(raw);
    let cleaned = if !tagged.is_empty() {
        strip_reasoning(&tagged)
    } else {
        strip_reasoning(raw)
    };
    if cleaned.is_empty() {
        return Err(LlmError::api(
            "Model returned only reasoning/thinking with no final answer. A non-reasoning model is recommended for translation.",
            Some(status),
        ));
    }
    Ok(cleaned)
}

fn extract_sse_delta(val: &Value) -> Option<String> {
    // Chat Completions: choices[0].delta.content
    if let Some(delta) = val
        .get("choices")
        .and_then(Value::as_array)
        .and_then(|arr| arr.first())
        .and_then(|c| c.get("delta"))
        .and_then(|d| d.get("content"))
    {
        if let Some(s) = delta.as_str() {
            return Some(s.to_string());
        }
    }
    // Responses API: {"type": "response.output_text.delta", "delta": "..."}
    let ev_type = val.get("type").and_then(Value::as_str).unwrap_or("");
    if ev_type == "response.output_text.delta" {
        if let Some(s) = val.get("delta").and_then(Value::as_str) {
            return Some(s.to_string());
        }
    }
    None
}

fn extract_sse_completed_text(val: &Value) -> Option<String> {
    let ev_type = val.get("type").and_then(Value::as_str).unwrap_or("");
    if ev_type == "response.output_text.done" {
        return val.get("text").and_then(Value::as_str).map(String::from);
    }
    if ev_type == "response.completed" {
        if let Some(resp) = val.get("response") {
            return extract_response_text(resp);
        }
    }
    None
}

fn check_http_status(status: u16, body: &str) -> Result<(), LlmError> {
    if status == 401 || status == 403 {
        let detail: String = body.chars().take(300).collect();
        return Err(LlmError::Auth { status, detail });
    }
    if status == 429 {
        let detail: String = body.chars().take(300).collect();
        return Err(LlmError::RateLimit(detail));
    }
    if status >= 400 {
        let detail: String = body.chars().take(500).collect();
        return Err(LlmError::api(
            format!("API error {status}: {detail}"),
            Some(status),
        ));
    }
    Ok(())
}

pub fn build_responses_body(
    messages: &[Value],
    model: &str,
    temperature: f64,
    max_tokens: u32,
    already_responses_content: bool,
    stream: bool,
) -> Map<String, Value> {
    let mut instructions_parts: Vec<String> = Vec::new();
    let mut input_items: Vec<Value> = Vec::new();

    for msg in messages {
        let role = msg.get("role").and_then(Value::as_str).unwrap_or("user");
        let content = msg.get("content").cloned().unwrap_or(Value::String(String::new()));

        if role == "system" {
            match &content {
                Value::String(s) if !s.trim().is_empty() => instructions_parts.push(s.clone()),
                Value::Array(arr) => {
                    for part in arr {
                        if let Some(t) = part.get("text").and_then(Value::as_str) {
                            instructions_parts.push(t.to_string());
                        } else if let Some(s) = part.as_str() {
                            instructions_parts.push(s.to_string());
                        }
                    }
                }
                _ => {}
            }
            continue;
        }

        if already_responses_content && content.is_array() {
            input_items.push(json!({ "role": role, "content": content }));
            continue;
        }

        input_items.push(json!({
            "role": role,
            "content": to_responses_content(&content),
        }));
    }

    let mut body = Map::new();
    body.insert("model".into(), json!(model));
    body.insert("input".into(), Value::Array(input_items));
    body.insert("temperature".into(), json!(temperature));
    body.insert("max_output_tokens".into(), json!(max_tokens));
    body.insert("stream".into(), json!(stream));
    if !instructions_parts.is_empty() {
        body.insert("instructions".into(), json!(instructions_parts.join("\n\n")));
    }
    body
}

fn to_responses_content(content: &Value) -> Value {
    if let Value::String(_) = content {
        return content.clone();
    }
    let Some(arr) = content.as_array() else {
        return Value::String(content.to_string());
    };
    let mut parts = Vec::new();
    for part in arr {
        if let Some(obj) = part.as_object() {
            let ptype = obj.get("type").and_then(Value::as_str).unwrap_or("");
            if ptype == "text" || ptype == "input_text" {
                let text = obj.get("text").and_then(Value::as_str).unwrap_or("");
                parts.push(json!({ "type": "input_text", "text": text }));
            } else if ptype == "image_url" || ptype == "input_image" {
                let url = obj
                    .get("image_url")
                    .and_then(|v| {
                        v.as_object()
                            .and_then(|m| m.get("url").and_then(Value::as_str))
                            .or_else(|| v.as_str())
                    })
                    .or_else(|| obj.get("url").and_then(Value::as_str))
                    .unwrap_or("");
                parts.push(json!({ "type": "input_image", "image_url": url }));
            } else if let Some(t) = obj.get("text").and_then(Value::as_str) {
                parts.push(json!({ "type": "input_text", "text": t }));
            } else {
                parts.push(part.clone());
            }
        } else if !part.is_null() {
            parts.push(json!({ "type": "input_text", "text": part.to_string() }));
        }
    }
    Value::Array(parts)
}

pub fn extract_response_text(data: &Value) -> Option<String> {
    let obj = data.as_object()?;

    if let Some(s) = obj.get("output_text").and_then(Value::as_str) {
        if !s.trim().is_empty() {
            return Some(s.trim().to_string());
        }
    }

    if let Some(output) = obj.get("output").and_then(Value::as_array) {
        let mut texts = Vec::new();
        for item in output {
            let Some(item_obj) = item.as_object() else {
                continue;
            };
            if let Some(content) = item_obj.get("content") {
                match content {
                    Value::String(s) => texts.push(s.clone()),
                    Value::Array(parts) => {
                        for part in parts {
                            if let Some(pobj) = part.as_object() {
                                if let Some(t) = pobj.get("text").and_then(Value::as_str) {
                                    texts.push(t.to_string());
                                }
                            } else if let Some(s) = part.as_str() {
                                texts.push(s.to_string());
                            }
                        }
                    }
                    _ => {}
                }
            } else if let Some(t) = item_obj.get("text").and_then(Value::as_str) {
                texts.push(t.to_string());
            }
        }
        let joined = texts.concat();
        if !joined.trim().is_empty() {
            return Some(joined.trim().to_string());
        }
    }

    let first = obj.get("choices").and_then(Value::as_array)?.first()?;
    let content = first
        .get("message")
        .and_then(|m| m.get("content"))
        .or_else(|| first.get("text"))?;

    match content {
        Value::Null => None,
        Value::String(s) => Some(s.clone()),
        Value::Array(parts) => {
            let mut out = String::new();
            for part in parts {
                if let Some(pobj) = part.as_object() {
                    let pt = pobj.get("type").and_then(Value::as_str).unwrap_or("");
                    if pt == "text" || pt == "output_text" {
                        if let Some(t) = pobj.get("text").and_then(Value::as_str) {
                            out.push_str(t);
                        }
                    }
                } else if let Some(s) = part.as_str() {
                    out.push_str(s);
                }
            }
            Some(out)
        }
        other => Some(other.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpListener;

    #[test]
    fn extracts_tags_and_strips_reasoning() {
        let raw = "<think>let me analyze</think>\n<final_translation>你好世界</final_translation>";
        assert_eq!(extract_tagged_final(raw), "你好世界");
        assert_eq!(strip_reasoning("<think>abc</think> Hello"), "Hello");
        assert_eq!(strip_reasoning("Hello <reasoning>unclosed..."), "Hello");
    }

    #[test]
    fn stream_sanitizer_hides_reasoning_and_tags() {
        let mut sf = StreamSanitizer::default();
        let mut collected = String::new();
        for piece in [
            "<think>plan",
            "</think><final_",
            "translation>你",
            "好世界</final_trans",
            "lation>",
        ] {
            if let Some(d) = sf.push(piece) {
                collected.push_str(&d);
            }
        }
        assert_eq!(collected, "你好世界");
    }

    #[test]
    fn parses_openai_and_ollama_model_lists() {
        let openai = json!({ "data": [{ "id": "b" }, { "id": "a" }, { "id": "a" }] });
        assert_eq!(extract_model_ids(&openai), vec!["a", "b"]);
        let ollama = json!({ "models": [{ "name": "qwen2.5" }] });
        assert_eq!(extract_model_ids(&ollama), vec!["qwen2.5"]);
    }

    #[tokio::test]
    async fn effort_fallback_retries_without_effort_and_warns() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();

        let server = tokio::spawn(async move {
            for attempt in 0..2 {
                let (mut socket, _) = listener.accept().await.unwrap();
                let mut buf = vec![0u8; 4096];
                let n = socket.read(&mut buf).await.unwrap();
                let req = String::from_utf8_lossy(&buf[..n]).to_string();
                let (status, body) = if attempt == 0 {
                    assert!(req.contains("reasoning_effort"));
                    (
                        "400 Bad Request",
                        r#"{"error":{"message":"Unsupported parameter: reasoning_effort"}}"#,
                    )
                } else {
                    assert!(!req.contains("reasoning_effort"));
                    (
                        "200 OK",
                        r#"{"choices":[{"message":{"content":"<final_translation>你好</final_translation>"}}]}"#,
                    )
                };
                let resp = format!(
                    "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                socket.write_all(resp.as_bytes()).await.unwrap();
            }
        });

        let mut profile = LlmProfile::default();
        profile.base_url = format!("http://{addr}/v1");
        profile.reasoning_effort = "xhigh".into();
        let client = LlmClient::new(profile).unwrap();
        let out = client
            .chat(&[json!({ "role": "user", "content": "hi" })], None, None, None)
            .await
            .unwrap();
        assert_eq!(out.text, "你好");
        assert_eq!(out.warnings.len(), 1);
        server.await.unwrap();
    }

    #[tokio::test]
    async fn chat_stream_delivers_sse_deltas() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();

        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buf = vec![0u8; 4096];
            let _ = socket.read(&mut buf).await.unwrap();
            let sse = concat!(
                "data: {\"choices\":[{\"delta\":{\"content\":\"<final_translation>Hello \"}}]}\n\n",
                "data: {\"choices\":[{\"delta\":{\"content\":\"world</final_translation>\"}}]}\n\n",
                "data: [DONE]\n\n",
            );
            let resp = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{sse}",
                sse.len()
            );
            socket.write_all(resp.as_bytes()).await.unwrap();
        });

        let mut profile = LlmProfile::default();
        profile.base_url = format!("http://{addr}/v1");
        let client = LlmClient::new(profile).unwrap();
        let mut streamed = String::new();
        let out = client
            .chat_stream(
                &[json!({ "role": "user", "content": "hi" })],
                None,
                |d| streamed.push_str(d),
                || {},
            )
            .await
            .unwrap();
        assert_eq!(streamed, "Hello world");
        assert_eq!(out.text, "Hello world");
        server.await.unwrap();
    }
}
