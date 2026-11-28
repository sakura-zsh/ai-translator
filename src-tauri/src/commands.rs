//! Tauri IPC commands bridging React UI and `ai-translator-core`.

use std::sync::Arc;

use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, State, WebviewUrl, WebviewWindowBuilder};
use tokio::sync::Mutex;
use tracing::{info, warn};

use ai_translator_core::config::{
    sanitize_reasoning_effort, AppConfig, ConfigStore, ImageMode, JevConfig, LlmProfile,
    ThemeMode, TranslationConfig,
};
use ai_translator_core::imaging::normalize_to_png;
use ai_translator_core::jev_client::JevClient;
use ai_translator_core::languages::{target_languages, LanguageItem, SOURCE_LANGUAGES};
use ai_translator_core::llm_client::LlmClient;
use ai_translator_core::ocr::OcrService;
#[cfg(not(target_os = "windows"))]
use ai_translator_core::platform::capture_region_wayland;
use ai_translator_core::platform::{
    read_clipboard_image_png, read_selected_text_for_quick, write_clipboard_text,
};
use ai_translator_core::presets::{
    all_scene_presets, format_glossary, parse_glossary, ScenePreset, AUTO_SCENE_ID,
    AUTO_SCENE_LABEL,
};
use ai_translator_core::providers::{ProviderTemplate, PROVIDER_TEMPLATES};
use ai_translator_core::translator::{TranslateResult, Translator};
use ai_translator_core::tts::{TextToSpeech, VoiceChoice, TTS_VOICE_CHOICES};
use ai_translator_core::APP_VERSION;

#[cfg(target_os = "windows")]
use crate::capture_win;

pub struct AppState {
    pub store: ConfigStore,
    pub config: Mutex<AppConfig>,
    pub tts: TextToSpeech,
    pub pending_screenshot_png: Mutex<Option<Vec<u8>>>,
    pub pending_quick_text: Mutex<Option<String>>,
}

impl AppState {
    pub fn new() -> Self {
        let store = ConfigStore::new(None);
        let config = store.load();
        Self {
            store,
            config: Mutex::new(config),
            tts: TextToSpeech::default(),
            pending_screenshot_png: Mutex::new(None),
            pending_quick_text: Mutex::new(None),
        }
    }
}

#[derive(Debug, Serialize)]
pub struct BootstrapData {
    pub version: &'static str,
    pub previous_version: String,
    pub is_windows: bool,
    pub tray_available: bool,
    pub config: AppConfig,
    pub needs_setup: bool,
    pub source_languages: &'static [LanguageItem],
    pub target_languages: Vec<LanguageItem>,
    pub provider_templates: &'static [ProviderTemplate],
    pub scenes: Vec<ScenePreset>,
    pub tts_voices: &'static [VoiceChoice],
}

#[tauri::command]
pub async fn get_bootstrap(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
) -> Result<BootstrapData, String> {
    let mut cfg = state.config.lock().await;
    #[cfg(target_os = "windows")]
    {
        cfg.ui.auto_start = crate::autostart_win::is_enabled();
    }
    let previous_version = cfg.last_run_version.clone();
    if cfg.last_run_version != APP_VERSION {
        cfg.last_run_version = APP_VERSION.to_string();
        let _ = state.store.save(&cfg);
    }
    let needs_setup = cfg.needs_setup();
    let scenes = all_scene_presets(&cfg.translation.custom_scenes);
    let tray_available = app.tray_by_id("main-tray").is_some();

    Ok(BootstrapData {
        version: APP_VERSION,
        previous_version,
        is_windows: cfg!(target_os = "windows"),
        tray_available,
        config: cfg.clone(),
        needs_setup,
        source_languages: SOURCE_LANGUAGES,
        target_languages: target_languages(),
        provider_templates: PROVIDER_TEMPLATES,
        scenes,
        tts_voices: TTS_VOICE_CHOICES,
    })
}

#[tauri::command]
pub async fn save_config(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
    mut new_config: AppConfig,
) -> Result<AppConfig, String> {
    new_config.sanitize();
    {
        let mut guard = state.config.lock().await;
        if new_config.last_run_version.is_empty() {
            new_config.last_run_version = guard.last_run_version.clone();
        }
        *guard = new_config.clone();
    }
    #[cfg(target_os = "windows")]
    {
        crate::autostart_win::set_enabled(new_config.ui.auto_start)?;
    }
    state.store.save(&new_config).map_err(|e| e.to_string())?;
    #[cfg(target_os = "windows")]
    {
        crate::register_windows_hotkeys(
            &app,
            &new_config.ui.hotkeys.summon,
            &new_config.ui.hotkeys.quick_translate,
        );
    }
    let _ = app.emit("config-updated", &new_config);
    Ok(new_config)
}

#[tauri::command]
pub async fn export_config_json(state: State<'_, Arc<AppState>>) -> Result<String, String> {
    let cfg = state.config.lock().await.clone();
    serde_json::to_string_pretty(&cfg).map_err(|e| format!("导出配置失败：{e}"))
}

#[tauri::command]
pub async fn import_config_json(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
    json_text: String,
) -> Result<AppConfig, String> {
    let val: serde_json::Value =
        serde_json::from_str(&json_text).map_err(|e| format!("JSON 格式无效：{e}"))?;
    if !val.is_object() {
        return Err("配置文件根节点必须是 JSON 对象".to_string());
    }
    let mut imported = AppConfig::from_json_value(&val);
    imported.last_run_version = APP_VERSION.to_string();
    imported.sanitize();
    {
        let mut guard = state.config.lock().await;
        *guard = imported.clone();
    }
    state.store.save(&imported).map_err(|e| e.to_string())?;
    #[cfg(target_os = "windows")]
    {
        if let Err(e) = crate::autostart_win::set_enabled(imported.ui.auto_start) {
            warn!("Failed to apply autostart on config import: {e}");
        }
        crate::register_windows_hotkeys(
            &app,
            &imported.ui.hotkeys.summon,
            &imported.ui.hotkeys.quick_translate,
        );
    }
    let _ = app.emit("config-updated", &imported);
    Ok(imported)
}

#[tauri::command]
pub async fn set_active_profile(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
    profile_id: String,
) -> Result<AppConfig, String> {
    let mut guard = state.config.lock().await;
    if guard.profiles.iter().any(|p| p.id == profile_id) {
        guard.active_profile_id = profile_id;
        let snapshot = guard.clone();
        drop(guard);
        state.store.save(&snapshot).map_err(|e| e.to_string())?;
        let _ = app.emit("config-updated", &snapshot);
        Ok(snapshot)
    } else {
        Err("Profile not found".to_string())
    }
}

#[tauri::command]
pub async fn update_profile_selection(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
    profile_id: String,
    model: Option<String>,
    reasoning_effort: Option<String>,
) -> Result<AppConfig, String> {
    let mut guard = state.config.lock().await;
    guard.active_profile_id = profile_id.clone();
    if let Some(p) = guard.profiles.iter_mut().find(|p| p.id == profile_id) {
        if let Some(m) = model {
            let trimmed = m.trim().to_string();
            if !trimmed.is_empty() {
                p.model = trimmed;
                p.sanitize();
            }
        }
        if let Some(effort) = reasoning_effort {
            p.reasoning_effort = sanitize_reasoning_effort(&effort);
        }
    }
    let snapshot = guard.clone();
    drop(guard);
    state.store.save(&snapshot).map_err(|e| e.to_string())?;
    let _ = app.emit("config-updated", &snapshot);
    Ok(snapshot)
}

#[tauri::command]
pub async fn update_translation_quick(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
    source_lang: Option<String>,
    target_lang: Option<String>,
    image_mode: Option<ImageMode>,
    scene: Option<String>,
    theme: Option<ThemeMode>,
) -> Result<AppConfig, String> {
    let mut guard = state.config.lock().await;
    if let Some(s) = source_lang {
        guard.translation.source_lang = s;
    }
    if let Some(t) = target_lang {
        guard.translation.target_lang = t;
    }
    if let Some(m) = image_mode {
        guard.translation.image_mode = m;
    }
    if let Some(sc) = scene {
        guard.translation.scene = sc;
    }
    if let Some(th) = theme {
        guard.ui.theme = th;
    }
    let snapshot = guard.clone();
    drop(guard);
    state.store.save(&snapshot).map_err(|e| e.to_string())?;
    let _ = app.emit("config-updated", &snapshot);
    Ok(snapshot)
}

#[derive(Debug, Clone, Serialize)]
pub struct TranslateStreamEvent {
    pub request_id: String,
    pub delta: String,
    pub reset: bool,
}

#[derive(Debug, Serialize)]
pub struct TranslateCommandOutput {
    pub result: TranslateResult,
    pub config: AppConfig,
}

#[tauri::command]
#[allow(clippy::too_many_arguments)]
pub async fn translate_text_cmd(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
    text: String,
    source_lang: String,
    target_lang: String,
    scene: String,
    request_id: Option<String>,
    quick: Option<bool>,
) -> Result<TranslateCommandOutput, String> {
    let use_quick = quick == Some(true);
    let (profile, mut translation_cfg, jev_cfg) = {
        let mut guard = state.config.lock().await;
        guard.translation.source_lang = source_lang.clone();
        guard.translation.target_lang = target_lang.clone();
        guard.translation.scene = scene.clone();
        let mut prof = if use_quick && !guard.translation.quick_profile_id.trim().is_empty() {
            guard
                .get_profile(&guard.translation.quick_profile_id)
                .unwrap_or_else(|| guard.get_active_profile())
                .clone()
        } else {
            guard.get_active_profile().clone()
        };
        if use_quick {
            let qm = guard.translation.quick_model.trim();
            if !qm.is_empty() {
                prof.model = qm.to_string();
            }
            let qe = guard.translation.quick_reasoning_effort.trim();
            if qe != "__follow__" {
                prof.reasoning_effort = sanitize_reasoning_effort(qe);
            }
        }
        (prof, guard.translation.clone(), guard.jev.clone())
    };
    translation_cfg.scene = scene;

    let req_id = request_id.unwrap_or_default();
    let app_for_delta = app.clone();
    let app_for_reset = app.clone();
    let req_for_delta = req_id.clone();
    let req_for_reset = req_id.clone();

    let translator = Translator::new(OcrService::new(&translation_cfg.tesseract_path, 60.0));
    let result = translator
        .translate_text_with_jev_stream(
            &text,
            &source_lang,
            &target_lang,
            &profile,
            &translation_cfg,
            &jev_cfg,
            move |delta| {
                if !req_for_delta.is_empty() && !delta.is_empty() {
                    let _ = app_for_delta.emit(
                        "translate-stream",
                        TranslateStreamEvent {
                            request_id: req_for_delta.clone(),
                            delta: delta.to_string(),
                            reset: false,
                        },
                    );
                }
            },
            move || {
                if !req_for_reset.is_empty() {
                    let _ = app_for_reset.emit(
                        "translate-stream",
                        TranslateStreamEvent {
                            request_id: req_for_reset.clone(),
                            delta: String::new(),
                            reset: true,
                        },
                    );
                }
            },
        )
        .await
        .map_err(|e| e.to_string())?;

    if translation_cfg.auto_copy_result {
        let _ = write_clipboard_text(&result.text).await;
    }

    let updated = {
        let mut guard = state.config.lock().await;
        guard.push_history(
            &source_lang,
            &target_lang,
            &result.mode,
            &text,
            &result.text,
            &result.model,
            None,
        );
        let snapshot = guard.clone();
        let _ = state.store.save(&snapshot);
        snapshot
    };

    Ok(TranslateCommandOutput {
        result,
        config: updated,
    })
}

#[tauri::command]
pub async fn translate_image_cmd(
    state: State<'_, Arc<AppState>>,
    image_base64: String,
    mode: ImageMode,
    source_lang: String,
    target_lang: String,
    scene: String,
) -> Result<TranslateCommandOutput, String> {
    let raw = BASE64
        .decode(image_base64.trim())
        .map_err(|e| format!("图片编码无效：{e}"))?;
    let png = normalize_to_png(&raw).map_err(|e| e.to_string())?;

    let (profile, mut translation_cfg, jev_cfg) = {
        let mut guard = state.config.lock().await;
        guard.translation.source_lang = source_lang.clone();
        guard.translation.target_lang = target_lang.clone();
        guard.translation.image_mode = mode.clone();
        guard.translation.scene = scene.clone();
        (
            guard.get_active_profile().clone(),
            guard.translation.clone(),
            guard.jev.clone(),
        )
    };
    translation_cfg.scene = scene;

    let translator = Translator::new(OcrService::new(&translation_cfg.tesseract_path, 60.0));
    let result = translator
        .translate_image_with_jev(
            &png,
            &mode,
            &source_lang,
            &target_lang,
            &profile,
            &translation_cfg,
            &jev_cfg,
        )
        .await
        .map_err(|e| e.to_string())?;

    if translation_cfg.auto_copy_result {
        let _ = write_clipboard_text(&result.text).await;
    }

    let history_src = result
        .ocr_text
        .clone()
        .unwrap_or_else(|| "[图片翻译]".to_string());

    let updated = {
        let mut guard = state.config.lock().await;
        guard.push_history(
            &source_lang,
            &target_lang,
            &result.mode,
            &history_src,
            &result.text,
            &result.model,
            None,
        );
        let snapshot = guard.clone();
        let _ = state.store.save(&snapshot);
        snapshot
    };

    Ok(TranslateCommandOutput {
        result,
        config: updated,
    })
}

#[tauri::command]
pub async fn extract_ocr_text_cmd(
    state: State<'_, Arc<AppState>>,
    image_base64: String,
) -> Result<String, String> {
    let raw = BASE64
        .decode(image_base64.trim())
        .map_err(|e| format!("图片编码无效：{e}"))?;
    let png = normalize_to_png(&raw).map_err(|e| e.to_string())?;
    let (tess_path, ocr_langs) = {
        let guard = state.config.lock().await;
        (
            guard.translation.tesseract_path.clone(),
            guard.translation.ocr_langs.clone(),
        )
    };
    let ocr = OcrService::new(&tess_path, 60.0);
    let text = ocr
        .extract_text(&png, &ocr_langs)
        .await
        .map_err(|e| e.to_string())?;
    let _ = write_clipboard_text(&text).await;
    Ok(text)
}

#[tauri::command]
pub async fn read_clipboard_image_cmd() -> Result<String, String> {
    let png = read_clipboard_image_png()
        .await
        .map_err(|e| e.to_string())?;
    Ok(BASE64.encode(png))
}

#[tauri::command]
pub async fn copy_text_cmd(text: String) -> Result<(), String> {
    write_clipboard_text(&text).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn capture_screenshot_cmd(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
) -> Result<Option<String>, String> {
    #[cfg(not(target_os = "windows"))]
    {
        let _ = (app, state);
        match capture_region_wayland().await {
            Ok(png) => Ok(Some(BASE64.encode(png))),
            Err(ai_translator_core::platform::PlatformError::ScreenshotCancelled) => Ok(None),
            Err(e) => Err(e.to_string()),
        }
    }
    #[cfg(target_os = "windows")]
    {
        capture_win::start_region_capture(app, state).await
    }
}

#[derive(Debug, Serialize)]
pub struct ScreenshotSourcePayload {
    pub image_base64: String,
    pub width: u32,
    pub height: u32,
}

#[tauri::command]
pub async fn get_pending_screenshot(
    state: State<'_, Arc<AppState>>,
) -> Result<Option<ScreenshotSourcePayload>, String> {
    let guard = state.pending_screenshot_png.lock().await;
    let Some(ref png) = *guard else {
        return Ok(None);
    };
    let dim = image::load_from_memory(png)
        .map(|i| (i.width(), i.height()))
        .unwrap_or((1920, 1080));
    Ok(Some(ScreenshotSourcePayload {
        image_base64: BASE64.encode(png),
        width: dim.0,
        height: dim.1,
    }))
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
pub struct CropRect {
    pub x: u32,
    pub y: u32,
    pub width: u32,
    pub height: u32,
}

#[tauri::command]
pub async fn complete_windows_screenshot(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
    crop: Option<CropRect>,
) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        capture_win::finish_region_capture(app, state, crop).await
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = (app, state, crop);
        Ok(())
    }
}

// ── Quick Selection Popup ─────────────────────────────────────────

pub async fn trigger_quick_popup(app: &AppHandle, state: &Arc<AppState>) {
    let text = read_selected_text_for_quick().await.unwrap_or_default();
    *state.pending_quick_text.lock().await = Some(text.clone());

    if let Some(win) = app.get_webview_window("quick") {
        crate::quick_win::apply_single_rounded_corner(&win);
        crate::quick_win::place_near_cursor(app, &win);
        let _ = win.show();
        let _ = win.unminimize();
        let _ = win.set_focus();
        let _ = app.emit_to("quick", "quick-payload", text);
        return;
    }

    match WebviewWindowBuilder::new(
        app,
        "quick",
        WebviewUrl::App("index.html?mode=quick".into()),
    )
    .title("AI Translator Quick")
    .decorations(false)
    .always_on_top(true)
    .skip_taskbar(true)
    .inner_size(
        crate::quick_win::QUICK_WIDTH_LOGICAL,
        crate::quick_win::QUICK_HEIGHT_LOGICAL,
    )
    .min_inner_size(
        crate::quick_win::QUICK_MIN_WIDTH_LOGICAL,
        crate::quick_win::QUICK_MIN_HEIGHT_LOGICAL,
    )
    .visible(false)
    .build()
    {
        Ok(win) => {
            crate::quick_win::apply_single_rounded_corner(&win);
            crate::quick_win::place_near_cursor(app, &win);
            let _ = win.show();
            let _ = win.set_focus();
        }
        Err(e) => warn!("Failed to open quick window: {e}"),
    }
}

#[tauri::command]
pub async fn get_pending_quick_text(
    state: State<'_, Arc<AppState>>,
) -> Result<String, String> {
    let text = state
        .pending_quick_text
        .lock()
        .await
        .clone()
        .unwrap_or_default();
    Ok(text)
}

#[tauri::command]
pub async fn close_quick_window(app: AppHandle) {
    if let Some(win) = app.get_webview_window("quick") {
        let _ = win.hide();
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct LoadInMainPayload {
    pub source_text: String,
    pub result_text: String,
}

#[tauri::command]
pub async fn open_in_main_window(
    app: AppHandle,
    source_text: String,
    result_text: String,
) {
    if let Some(qwin) = app.get_webview_window("quick") {
        let _ = qwin.hide();
    }
    crate::summon_main_window(&app);
    let _ = app.emit_to(
        "main",
        "load-in-main",
        LoadInMainPayload {
            source_text,
            result_text,
        },
    );
}

// ── Favorites / Vocabulary Book ───────────────────────────────────

#[derive(Debug, Serialize)]
pub struct ToggleFavoriteOutput {
    pub favorited: bool,
    pub config: AppConfig,
}

#[tauri::command]
#[allow(clippy::too_many_arguments)]
pub async fn toggle_favorite_cmd(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
    source_lang: String,
    target_lang: String,
    mode: String,
    source_text: String,
    result_text: String,
    model: String,
) -> Result<ToggleFavoriteOutput, String> {
    let mut guard = state.config.lock().await;
    let favorited = guard.toggle_favorite(
        &source_lang,
        &target_lang,
        &mode,
        &source_text,
        &result_text,
        &model,
    );
    let snapshot = guard.clone();
    drop(guard);
    state.store.save(&snapshot).map_err(|e| e.to_string())?;
    let _ = app.emit("config-updated", &snapshot);
    Ok(ToggleFavoriteOutput {
        favorited,
        config: snapshot,
    })
}

#[tauri::command]
pub async fn remove_favorite_cmd(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
    id: String,
) -> Result<AppConfig, String> {
    let mut guard = state.config.lock().await;
    guard.remove_favorite(&id);
    let snapshot = guard.clone();
    drop(guard);
    state.store.save(&snapshot).map_err(|e| e.to_string())?;
    let _ = app.emit("config-updated", &snapshot);
    Ok(snapshot)
}

#[tauri::command]
pub async fn export_favorites_cmd(
    state: State<'_, Arc<AppState>>,
    format: String,
) -> Result<String, String> {
    let guard = state.config.lock().await;
    match format.as_str() {
        "anki_tsv" => Ok(guard.export_favorites_anki_tsv()),
        _ => Ok(guard.export_favorites_markdown()),
    }
}

// ── Models, Tests, TTS, History, Geometry ─────────────────────────

#[tauri::command]
pub async fn fetch_profile_models(
    state: State<'_, Arc<AppState>>,
    profile: LlmProfile,
    persist_cache: bool,
) -> Result<Vec<String>, String> {
    let client = LlmClient::new(profile.clone()).map_err(|e| e.to_string())?;
    let models = client.list_models().await.map_err(|e| e.to_string())?;
    if persist_cache {
        let mut guard = state.config.lock().await;
        if let Some(p) = guard.profiles.iter_mut().find(|p| p.id == profile.id) {
            p.model_options = models.clone();
            p.sanitize();
            let snapshot = guard.clone();
            drop(guard);
            let _ = state.store.save(&snapshot);
        }
    }
    Ok(models)
}

#[tauri::command]
pub async fn test_profile_connection(profile: LlmProfile) -> Result<String, String> {
    let client = LlmClient::new(profile).map_err(|e| e.to_string())?;
    client.test_connection().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn test_jev_connection(jev: JevConfig) -> Result<String, String> {
    let client = JevClient::new(jev).map_err(|e| e.to_string())?;
    client.test_connection().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn fetch_jev_models(jev: JevConfig) -> Result<Vec<String>, String> {
    let client = JevClient::new(jev).map_err(|e| e.to_string())?;
    client.list_models().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn synthesize_tts(
    state: State<'_, Arc<AppState>>,
    text: String,
    voice: String,
    rate: i32,
) -> Result<String, String> {
    let path = state
        .tts
        .speak(&text, &voice, rate)
        .await
        .map_err(|e| e.to_string())?;
    let bytes = tokio::fs::read(&path)
        .await
        .map_err(|e| format!("读取语音缓存失败：{e}"))?;
    Ok(format!("data:audio/mpeg;base64,{}", BASE64.encode(bytes)))
}

#[tauri::command]
pub async fn parse_glossary_text(text: String) -> indexmap::IndexMap<String, String> {
    parse_glossary(&text)
}

#[tauri::command]
pub async fn format_glossary_text(glossary: indexmap::IndexMap<String, String>) -> String {
    format_glossary(&glossary)
}

#[tauri::command]
pub async fn clear_history_cmd(state: State<'_, Arc<AppState>>) -> Result<AppConfig, String> {
    let mut guard = state.config.lock().await;
    guard.clear_history();
    let snapshot = guard.clone();
    drop(guard);
    state.store.save(&snapshot).map_err(|e| e.to_string())?;
    Ok(snapshot)
}

#[tauri::command]
pub async fn save_window_geometry(
    state: State<'_, Arc<AppState>>,
    width: Option<u32>,
    height: Option<u32>,
    maximized: Option<bool>,
    splitter_sizes: Option<Vec<i32>>,
) -> Result<(), String> {
    let mut guard = state.config.lock().await;
    if let Some(w) = width {
        guard.ui.window_width = w.max(400);
    }
    if let Some(h) = height {
        guard.ui.window_height = h.max(320);
    }
    if let Some(m) = maximized {
        guard.ui.window_maximized = m;
    }
    if let Some(s) = splitter_sizes {
        guard.ui.splitter_sizes = s;
    }
    let snapshot = guard.clone();
    drop(guard);
    let _ = state.store.save(&snapshot);
    Ok(())
}

#[tauri::command]
pub async fn quit_app(app: AppHandle) {
    info!("Quitting application via command");
    app.exit(0);
}

#[tauri::command]
pub async fn log_frontend_warn(msg: String) {
    warn!("frontend: {msg}");
}

#[allow(dead_code)]
fn _unused_ref() {
    let _ = (AUTO_SCENE_ID, AUTO_SCENE_LABEL, std::mem::size_of::<TranslationConfig>());
}
