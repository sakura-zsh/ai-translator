//! Text-to-speech via Microsoft Edge neural voices (WebSocket + Sec-MS-GEC DRM)
//! with a flat on-disk MP3 cache compatible with the legacy cache directory.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use futures_util::{SinkExt, StreamExt};
use serde::Serialize;
use sha1::{Digest as Sha1Digest, Sha1};
use sha2::Sha256;
use thiserror::Error;
use tokio::time::timeout;
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::http::HeaderValue;
use tokio_tungstenite::tungstenite::Message;
use tracing::warn;
use uuid::Uuid;

pub const TTS_TIMEOUT_S: u64 = 30;
const CACHE_KEEP_FILES: usize = 200;

const TRUSTED_CLIENT_TOKEN: &str = "6A5AA1D4EAFF4E9FB37E23D68491D6F4";
const CHROMIUM_FULL_VERSION: &str = "143.0.3650.75";
const SEC_MS_GEC_VERSION: &str = "1-143.0.3650.75";
const WIN_EPOCH_SECS: i64 = 11_644_473_600;

#[derive(Debug, Clone, Copy, Serialize)]
pub struct VoiceChoice {
    pub label: &'static str,
    pub voice: &'static str,
}

pub const TTS_VOICE_CHOICES: &[VoiceChoice] = &[
    VoiceChoice { label: "晓晓 · 中文女声", voice: "zh-CN-XiaoxiaoNeural" },
    VoiceChoice { label: "云希 · 中文男声", voice: "zh-CN-YunxiNeural" },
    VoiceChoice { label: "云健 · 中文男声", voice: "zh-CN-YunjianNeural" },
    VoiceChoice { label: "Aria · 英语女声（美）", voice: "en-US-AriaNeural" },
    VoiceChoice { label: "Jenny · 英语女声（美）", voice: "en-US-JennyNeural" },
    VoiceChoice { label: "Guy · 英语男声（美）", voice: "en-US-GuyNeural" },
    VoiceChoice { label: "Sonia · 英语女声（英）", voice: "en-GB-SoniaNeural" },
];

#[derive(Debug, Error)]
pub enum TtsError {
    #[error("{0}")]
    Failed(String),
}

pub fn default_cache_dir() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        let base = env::var_os("LOCALAPPDATA")
            .filter(|v| !v.is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                let home = env::var_os("USERPROFILE")
                    .map(PathBuf::from)
                    .unwrap_or_else(|| PathBuf::from("."));
                home.join("AppData").join("Local")
            });
        base.join("ai-translator").join("cache").join("tts")
    }
    #[cfg(not(target_os = "windows"))]
    {
        let base = env::var_os("XDG_CACHE_HOME")
            .filter(|v| !v.is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                let home = env::var_os("HOME")
                    .map(PathBuf::from)
                    .unwrap_or_else(|| PathBuf::from("."));
                home.join(".cache")
            });
        base.join("ai-translator").join("tts")
    }
}

/// Generate Microsoft Edge TTS `Sec-MS-GEC` DRM token (5-minute quantized Windows FileTime).
pub fn generate_sec_ms_gec(unix_secs: i64) -> String {
    let mut ticks = unix_secs + WIN_EPOCH_SECS;
    ticks -= ticks.rem_euclid(300);
    let ticks_100ns = ticks as i128 * 10_000_000;
    let payload = format!("{ticks_100ns}{TRUSTED_CLIENT_TOKEN}");
    let hash = Sha256::digest(payload.as_bytes());
    hex::encode_upper(hash)
}

fn xml_escape(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for ch in text.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&apos;"),
            // Drop ASCII control chars invalid in XML 1.0 except tab/lf/cr
            c if (c as u32) < 0x20 && !matches!(c, '\t' | '\n' | '\r') => {}
            c => out.push(c),
        }
    }
    out
}

#[derive(Debug, Clone)]
pub struct TextToSpeech {
    cache_dir: PathBuf,
}

impl Default for TextToSpeech {
    fn default() -> Self {
        Self::new(None)
    }
}

impl TextToSpeech {
    pub fn new(cache_dir: Option<PathBuf>) -> Self {
        let dir = cache_dir.unwrap_or_else(default_cache_dir);
        if let Err(e) = fs::create_dir_all(&dir) {
            warn!("TTS cache dir unavailable ({:?}): {}", dir, e);
        }
        Self { cache_dir: dir }
    }

    pub fn cache_dir(&self) -> &Path {
        &self.cache_dir
    }

    /// Cache path matches Python `hashlib.sha1(f"{voice}|{rate}|{text}").hexdigest()[:20]`.
    pub fn cache_path(&self, text: &str, voice: &str, rate: i32) -> PathBuf {
        let mut hasher = Sha1::new();
        hasher.update(format!("{voice}|{rate}|{text}").as_bytes());
        let hex_str = hex::encode(hasher.finalize());
        self.cache_dir.join(format!("{}.mp3", &hex_str[..20]))
    }

    pub async fn speak(&self, text: &str, voice: &str, rate: i32) -> Result<PathBuf, TtsError> {
        let cleaned = text.trim();
        if cleaned.is_empty() {
            return Err(TtsError::Failed("没有可朗读的文本".to_string()));
        }
        let voice_clean = if voice.trim().is_empty() {
            "zh-CN-XiaoxiaoNeural"
        } else {
            voice.trim()
        };
        let path = self.cache_path(cleaned, voice_clean, rate);
        if let Ok(meta) = fs::metadata(&path) {
            if meta.len() > 0 {
                return Ok(path);
            }
        }

        let audio = timeout(
            Duration::from_secs(TTS_TIMEOUT_S),
            synthesize_edge_tts(cleaned, voice_clean, rate),
        )
        .await
        .map_err(|_| TtsError::Failed("语音合成超时".to_string()))??;

        if audio.is_empty() {
            return Err(TtsError::Failed("语音合成失败（空输出）".to_string()));
        }

        let _ = fs::create_dir_all(&self.cache_dir);
        tokio::fs::write(&path, &audio)
            .await
            .map_err(|e| TtsError::Failed(format!("写入语音缓存失败：{e}")))?;

        self.prune_cache(CACHE_KEEP_FILES);
        Ok(path)
    }

    pub fn prune_cache(&self, keep: usize) {
        let Ok(entries) = fs::read_dir(&self.cache_dir) else {
            return;
        };
        let mut files: Vec<(PathBuf, SystemTime)> = entries
            .filter_map(Result::ok)
            .map(|e| e.path())
            .filter(|p| p.extension().and_then(|e| e.to_str()) == Some("mp3") && p.is_file())
            .filter_map(|p| {
                let mtime = p.metadata().ok()?.modified().ok()?;
                Some((p, mtime))
            })
            .collect();
        files.sort_by_key(|a| std::cmp::Reverse(a.1));
        for (old, _) in files.into_iter().skip(keep) {
            let _ = fs::remove_file(old);
        }
    }
}

async fn synthesize_edge_tts(text: &str, voice: &str, rate: i32) -> Result<Vec<u8>, TtsError> {
    let conn_id = Uuid::new_v4().simple().to_string();
    let now_secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let gec = generate_sec_ms_gec(now_secs);
    let url = format!(
        "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1\
?TrustedClientToken={TRUSTED_CLIENT_TOKEN}&ConnectionId={conn_id}&Sec-MS-GEC={gec}&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}"
    );

    let mut req = url
        .into_client_request()
        .map_err(|e| TtsError::Failed(format!("语音请求构造失败：{e}")))?;
    let headers = req.headers_mut();
    headers.insert(
        "Origin",
        HeaderValue::from_static("chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold"),
    );
    headers.insert("Pragma", HeaderValue::from_static("no-cache"));
    headers.insert("Cache-Control", HeaderValue::from_static("no-cache"));
    let ua = format!(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{CHROMIUM_FULL_VERSION} Safari/537.36 Edg/{CHROMIUM_FULL_VERSION}"
    );
    if let Ok(val) = HeaderValue::from_str(&ua) {
        headers.insert("User-Agent", val);
    }

    let (mut ws, _) = connect_async(req)
        .await
        .map_err(|e| TtsError::Failed(format!("语音合成失败：{e}")))?;

    let config_msg = "Content-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n\
{\"context\":{\"synthesis\":{\"audio\":{\"metadataoptions\":{\"sentenceBoundaryEnabled\":\"false\",\"wordBoundaryEnabled\":\"false\"},\
\"outputFormat\":\"audio-24khz-48kbitrate-mono-mp3\"}}}}";
    ws.send(Message::Text(config_msg.into()))
        .await
        .map_err(|e| TtsError::Failed(format!("发送语音配置失败：{e}")))?;

    let req_id = Uuid::new_v4().simple().to_string();
    let rate_str = format!("{rate:+}%");
    let escaped = xml_escape(text);
    let ssml_msg = format!(
        "X-RequestId:{req_id}\r\nContent-Type:application/ssml+xml\r\nPath:ssml\r\n\r\n\
<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>\
<voice name='{voice}'><prosody pitch='+0Hz' rate='{rate_str}' volume='+0%'>{escaped}</prosody></voice></speak>"
    );
    ws.send(Message::Text(ssml_msg.into()))
        .await
        .map_err(|e| TtsError::Failed(format!("发送朗读内容失败：{e}")))?;

    let mut audio = Vec::new();
    while let Some(frame) = ws.next().await {
        let msg = frame.map_err(|e| TtsError::Failed(format!("接收语音流失败：{e}")))?;
        match msg {
            Message::Text(txt) => {
                if txt.contains("Path:turn.end") {
                    break;
                }
            }
            Message::Binary(bin) => {
                if bin.len() >= 2 {
                    let header_len = u16::from_be_bytes([bin[0], bin[1]]) as usize;
                    let data_start = 2 + header_len;
                    if data_start <= bin.len() {
                        let header_str = String::from_utf8_lossy(&bin[2..data_start]);
                        if header_str.contains("Path:audio") {
                            audio.extend_from_slice(&bin[data_start..]);
                        }
                    }
                }
            }
            Message::Close(_) => break,
            _ => {}
        }
    }
    let _ = ws.close(None).await;
    Ok(audio)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn cache_key_is_deterministic_and_20_hex_chars() {
        let dir = TempDir::new().unwrap();
        let tts = TextToSpeech::new(Some(dir.path().to_path_buf()));
        let p1 = tts.cache_path("hello", "zh-CN-XiaoxiaoNeural", 0);
        let p2 = tts.cache_path("hello", "zh-CN-XiaoxiaoNeural", 0);
        let p3 = tts.cache_path("hello", "zh-CN-XiaoxiaoNeural", -50);
        assert_eq!(p1, p2);
        assert_ne!(p1, p3);
        assert_eq!(p1.file_stem().unwrap().to_str().unwrap().len(), 20);
    }

    #[test]
    fn sec_ms_gec_produces_64_char_uppercase_hex() {
        let tok = generate_sec_ms_gec(1_700_000_000);
        assert_eq!(tok.len(), 64);
        assert!(tok.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_lowercase()));
    }

    #[test]
    fn prune_cache_keeps_newest() {
        let dir = TempDir::new().unwrap();
        let tts = TextToSpeech::new(Some(dir.path().to_path_buf()));
        for i in 0..5 {
            fs::write(dir.path().join(format!("clip_{i}.mp3")), b"mp3").unwrap();
        }
        tts.prune_cache(2);
        let remaining = fs::read_dir(dir.path()).unwrap().count();
        assert_eq!(remaining, 2);
    }
}
