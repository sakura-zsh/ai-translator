//! Tauri v2 desktop shell: single-instance, quick popup, logging, tray, global hotkeys, and IPC.

mod autostart_win;
mod capture_win;
mod commands;
mod quick_win;

use std::env;
use std::path::PathBuf;
use std::sync::Arc;

use tauri::image::Image as TauriImage;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, LogicalSize, Manager, Size, WindowEvent};
use tracing::{info, warn};
use tracing_subscriber::EnvFilter;

use ai_translator_core::config::ConfigStore;
use commands::AppState;

fn default_log_dir() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        let base = env::var_os("LOCALAPPDATA")
            .filter(|v| !v.is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                env::var_os("USERPROFILE")
                    .map(PathBuf::from)
                    .unwrap_or_else(|| PathBuf::from("."))
                    .join("AppData")
                    .join("Local")
            });
        base.join("ai-translator").join("logs")
    }
    #[cfg(not(target_os = "windows"))]
    {
        let base = env::var_os("XDG_STATE_HOME")
            .filter(|v| !v.is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                env::var_os("HOME")
                    .map(PathBuf::from)
                    .unwrap_or_else(|| PathBuf::from("."))
                    .join(".local")
                    .join("state")
            });
        base.join("ai-translator")
    }
}

fn init_logging() -> Option<tracing_appender::non_blocking::WorkerGuard> {
    let dir = default_log_dir();
    let _ = std::fs::create_dir_all(&dir);
    let file_appender = tracing_appender::rolling::daily(&dir, "ai-translator.log");
    let (non_blocking, guard) = tracing_appender::non_blocking(file_appender);
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
    let _ = tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_writer(non_blocking)
        .with_ansi(false)
        .try_init();
    Some(guard)
}

pub fn summon_main_window(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.unminimize();
        let _ = win.set_focus();
    }
}

fn setup_tray(app: &AppHandle, state: Arc<AppState>) -> tauri::Result<()> {
    let show_item = MenuItem::with_id(app, "tray_show", "显示 / 隐藏", true, None::<&str>)?;
    let quick_item =
        MenuItem::with_id(app, "tray_quick", "划词 / 选区快翻", true, None::<&str>)?;
    let screenshot_item =
        MenuItem::with_id(app, "tray_screenshot", "截图翻译", true, None::<&str>)?;
    let extract_item =
        MenuItem::with_id(app, "tray_extract", "提取文字", true, None::<&str>)?;
    let paste_item =
        MenuItem::with_id(app, "tray_paste", "粘贴图片翻译", true, None::<&str>)?;
    let sep = PredefinedMenuItem::separator(app)?;
    let quit_item = MenuItem::with_id(app, "tray_quit", "退出", true, None::<&str>)?;

    let menu = Menu::with_items(
        app,
        &[
            &show_item,
            &quick_item,
            &screenshot_item,
            &extract_item,
            &paste_item,
            &sep,
            &quit_item,
        ],
    )?;

    let icon_bytes = include_bytes!("../icons/32x32.png");
    let icon = TauriImage::from_bytes(icon_bytes)?;

    TrayIconBuilder::with_id("main-tray")
        .icon(icon)
        .tooltip("AI Translator")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(move |app, event| match event.id().as_ref() {
            "tray_show" => {
                if let Some(win) = app.get_webview_window("main") {
                    if win.is_visible().unwrap_or(true) {
                        let _ = win.hide();
                    } else {
                        summon_main_window(app);
                    }
                }
            }
            "tray_quick" => {
                let handle = app.clone();
                let st = Arc::clone(&state);
                tauri::async_runtime::spawn(async move {
                    commands::trigger_quick_popup(&handle, &st).await;
                });
            }
            "tray_screenshot" => {
                summon_main_window(app);
                let _ = app.emit("tray-action", "screenshot");
            }
            "tray_extract" => {
                summon_main_window(app);
                let _ = app.emit("tray-action", "extract");
            }
            "tray_paste" => {
                summon_main_window(app);
                let _ = app.emit("tray-action", "paste_image");
            }
            "tray_quit" => {
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle();
                if let Some(win) = app.get_webview_window("main") {
                    if win.is_visible().unwrap_or(true) {
                        let _ = win.hide();
                    } else {
                        summon_main_window(app);
                    }
                }
            }
        })
        .build(app)?;

    Ok(())
}

#[cfg(target_os = "windows")]
pub fn register_windows_hotkeys(app: &AppHandle, summon_str: &str, quick_str: &str) {
    use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

    let gs = app.global_shortcut();
    let _ = gs.unregister_all();

    let summon_trimmed = summon_str.trim();
    if !summon_trimmed.is_empty() {
        let normalized = summon_trimmed.replace("Return", "Enter");
        match gs.on_shortcut(normalized.as_str(), |app, _shortcut, event| {
            if event.state() == ShortcutState::Pressed {
                summon_main_window(app);
            }
        }) {
            Ok(()) => info!("Registered Windows summon hotkey: {normalized}"),
            Err(e) => {
                warn!("Failed to register summon hotkey {normalized}: {e}");
                let _ = app.emit(
                    "status-toast",
                    format!("全局热键 {summon_trimmed} 注册失败，可能被占用"),
                );
            }
        }
    }

    let quick_trimmed = quick_str.trim();
    if !quick_trimmed.is_empty() && quick_trimmed != summon_trimmed {
        let normalized = quick_trimmed.replace("Return", "Enter");
        match gs.on_shortcut(normalized.as_str(), |app, _shortcut, event| {
            if event.state() == ShortcutState::Pressed {
                let handle = app.clone();
                let st = Arc::clone(&*app.state::<Arc<AppState>>());
                tauri::async_runtime::spawn(async move {
                    commands::trigger_quick_popup(&handle, &st).await;
                });
            }
        }) {
            Ok(()) => info!("Registered Windows quick hotkey: {normalized}"),
            Err(e) => warn!("Failed to register quick hotkey {normalized}: {e}"),
        }
    }
}

pub fn run() {
    let _log_guard = init_logging();
    info!("Starting AI Translator v{}", ai_translator_core::APP_VERSION);
    let state = Arc::new(AppState::new());
    let initial_cfg = ConfigStore::new(None).load();
    let start_quick = env::args().any(|a| a == "--quick");

    let state_for_single = Arc::clone(&state);

    #[allow(unused_mut)]
    let mut builder = tauri::Builder::default().plugin(tauri_plugin_single_instance::init(
        move |app, args, _cwd| {
            if args.iter().any(|a| a == "--quick") {
                info!("Second instance --quick detected; opening quick popup");
                let handle = app.clone();
                let st = Arc::clone(&state_for_single);
                tauri::async_runtime::spawn(async move {
                    commands::trigger_quick_popup(&handle, &st).await;
                });
            } else {
                info!("Second instance detected; summoning existing window");
                summon_main_window(app);
            }
        },
    ));

    #[cfg(target_os = "windows")]
    {
        builder = builder.plugin(tauri_plugin_global_shortcut::Builder::new().build());
    }

    let state_for_setup = Arc::clone(&state);
    let state_for_events = Arc::clone(&state);

    builder
        .manage(state)
        .setup(move |app| {
            if let Some(win) = app.get_webview_window("main") {
                let w = initial_cfg.ui.window_width.max(800) as f64;
                let h = initial_cfg.ui.window_height.max(560) as f64;
                let _ = win.set_size(Size::Logical(LogicalSize { width: w, height: h }));
                if start_quick {
                    let _ = win.hide();
                } else {
                    let _ = win.show();
                    if initial_cfg.ui.window_maximized {
                        let _ = win.maximize();
                    }
                }
            }

            if start_quick {
                let handle = app.handle().clone();
                let st = Arc::clone(&state_for_setup);
                tauri::async_runtime::spawn(async move {
                    commands::trigger_quick_popup(&handle, &st).await;
                });
            }

            if let Err(e) = setup_tray(app.handle(), Arc::clone(&state_for_setup)) {
                warn!("System tray unavailable (degrading to normal close): {e}");
            }

            #[cfg(target_os = "windows")]
            {
                register_windows_hotkeys(
                    app.handle(),
                    &initial_cfg.ui.hotkeys.summon,
                    &initial_cfg.ui.hotkeys.quick_translate,
                );
            }

            Ok(())
        })
        .on_window_event(move |window, event| {
            if window.label() == "quick" {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                }
                return;
            }
            if window.label() != "main" {
                return;
            }
            if let WindowEvent::CloseRequested { api, .. } = event {
                let app = window.app_handle();
                let tray_ok = app.tray_by_id("main-tray").is_some();
                let close_to_tray = state_for_events
                    .config
                    .try_lock()
                    .map(|g| g.ui.close_to_tray)
                    .unwrap_or(true);
                if tray_ok && close_to_tray {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_bootstrap,
            commands::save_config,
            commands::export_config_json,
            commands::import_config_json,
            commands::set_active_profile,
            commands::update_profile_selection,
            commands::update_translation_quick,
            commands::translate_text_cmd,
            commands::translate_image_cmd,
            commands::extract_ocr_text_cmd,
            commands::read_clipboard_image_cmd,
            commands::copy_text_cmd,
            commands::capture_screenshot_cmd,
            commands::get_pending_screenshot,
            commands::complete_windows_screenshot,
            commands::get_pending_quick_text,
            commands::close_quick_window,
            commands::open_in_main_window,
            commands::toggle_favorite_cmd,
            commands::remove_favorite_cmd,
            commands::export_favorites_cmd,
            commands::fetch_profile_models,
            commands::test_profile_connection,
            commands::test_jev_connection,
            commands::fetch_jev_models,
            commands::synthesize_tts,
            commands::parse_glossary_text,
            commands::format_glossary_text,
            commands::clear_history_cmd,
            commands::save_window_geometry,
            commands::quit_app,
            commands::log_frontend_warn,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
