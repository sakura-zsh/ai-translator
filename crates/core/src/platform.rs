//! Cross-platform desktop helpers: clipboard text/image, Wayland region screenshot, notifications.

#[cfg(not(target_os = "windows"))]
use std::process::Stdio;
use std::time::Duration;

use thiserror::Error;
#[cfg(not(target_os = "windows"))]
use tokio::io::AsyncWriteExt;
use tokio::process::Command;
use tokio::time::timeout;

#[cfg(not(target_os = "windows"))]
use crate::imaging::normalize_to_png;

#[derive(Debug, Error)]
pub enum PlatformError {
    #[error("截图已取消")]
    ScreenshotCancelled,
    #[error("{0}")]
    Failed(String),
}

// ── Wayland Screenshot (slurp + grim) ─────────────────────────────

pub async fn capture_region_wayland() -> Result<Vec<u8>, PlatformError> {
    if which::which("slurp").is_err() {
        return Err(PlatformError::Failed(
            "未找到 slurp。请安装：sudo pacman -S slurp grim".to_string(),
        ));
    }
    if which::which("grim").is_err() {
        return Err(PlatformError::Failed(
            "未找到 grim。请安装：sudo pacman -S slurp grim".to_string(),
        ));
    }

    let slurp = timeout(Duration::from_secs(120), Command::new("slurp").output())
        .await
        .map_err(|_| PlatformError::Failed("区域选择超时".to_string()))?
        .map_err(|e| PlatformError::Failed(format!("启动 slurp 失败：{e}")))?;

    let geometry = String::from_utf8_lossy(&slurp.stdout).trim().to_string();
    if !slurp.status.success() || geometry.is_empty() {
        return Err(PlatformError::ScreenshotCancelled);
    }

    let grim = timeout(
        Duration::from_secs(30),
        Command::new("grim").arg("-g").arg(&geometry).arg("-").output(),
    )
    .await
    .map_err(|_| PlatformError::Failed("截图捕获超时".to_string()))?
    .map_err(|e| PlatformError::Failed(format!("启动 grim 失败：{e}")))?;

    if !grim.status.success() || grim.stdout.is_empty() {
        let err = String::from_utf8_lossy(&grim.stderr);
        let preview: String = err.chars().take(300).collect();
        return Err(PlatformError::Failed(format!(
            "grim 失败：{}",
            if preview.is_empty() {
                "无图片数据"
            } else {
                &preview
            }
        )));
    }
    Ok(grim.stdout)
}

// ── Clipboard & Primary Selection Text ────────────────────────────

pub async fn read_primary_selection_text() -> Result<String, PlatformError> {
    #[cfg(not(target_os = "windows"))]
    {
        for (bin, args) in [
            ("wl-paste", &["--primary", "--no-newline"][..]),
            ("xclip", &["-selection", "primary", "-o"][..]),
        ] {
            if which::which(bin).is_err() {
                continue;
            }
            if let Ok(Ok(out)) =
                timeout(Duration::from_secs(5), Command::new(bin).args(args).output()).await
            {
                if out.status.success() {
                    let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
                    if !s.is_empty() {
                        return Ok(s);
                    }
                }
            }
        }
    }
    read_clipboard_text().await
}

/// Capture currently selected text for the quick-translate popup without ever
/// falling back to stale clipboard contents when nothing is selected.
pub async fn read_selected_text_for_quick() -> Result<String, PlatformError> {
    #[cfg(target_os = "windows")]
    {
        tokio::task::spawn_blocking(capture_selected_text_windows)
            .await
            .map_err(|e| PlatformError::Failed(format!("选区捕获线程异常：{e}")))?
    }
    #[cfg(not(target_os = "windows"))]
    {
        for (bin, args) in [
            ("wl-paste", &["--primary", "--no-newline"][..]),
            ("xclip", &["-selection", "primary", "-o"][..]),
        ] {
            if which::which(bin).is_err() {
                continue;
            }
            if let Ok(Ok(out)) =
                timeout(Duration::from_secs(3), Command::new(bin).args(args).output()).await
            {
                if out.status.success() {
                    let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
                    if !s.is_empty() {
                        return Ok(s);
                    }
                }
            }
        }
        Ok(String::new())
    }
}

#[cfg(target_os = "windows")]
fn try_uia_selected_text_windows() -> Option<String> {
    use windows::Win32::System::Com::{
        CoCreateInstance, CoInitializeEx, CoUninitialize, CLSCTX_INPROC_SERVER,
        COINIT_APARTMENTTHREADED,
    };
    use windows::Win32::UI::Accessibility::{
        CUIAutomation, IUIAutomation, IUIAutomationTextPattern, UIA_TextPatternId,
    };

    struct ComGuard(bool);
    impl Drop for ComGuard {
        fn drop(&mut self) {
            if self.0 {
                unsafe { CoUninitialize() };
            }
        }
    }

    unsafe {
        let hr = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
        let _com_guard = ComGuard(hr.is_ok());

        let uia: IUIAutomation =
            CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER).ok()?;
        let mut current = uia.GetFocusedElement().ok()?;
        let walker = uia.ControlViewWalker().ok();

        for _ in 0..8 {
            if let Ok(pattern) =
                current.GetCurrentPatternAs::<IUIAutomationTextPattern>(UIA_TextPatternId)
            {
                if let Ok(ranges) = pattern.GetSelection() {
                    let count = ranges.Length().unwrap_or(0);
                    let mut parts = Vec::new();
                    for idx in 0..count {
                        if let Ok(range) = ranges.GetElement(idx) {
                            if let Ok(bstr) = range.GetText(-1) {
                                let s = bstr.to_string();
                                let trimmed = s.trim();
                                if !trimmed.is_empty() {
                                    parts.push(trimmed.to_string());
                                }
                            }
                        }
                    }
                    if !parts.is_empty() {
                        return Some(parts.join("\n"));
                    }
                }
            }
            let Some(ref w) = walker else {
                break;
            };
            match w.GetParentElement(&current) {
                Ok(parent) => current = parent,
                Err(_) => break,
            }
        }
    }
    None
}

#[cfg(target_os = "windows")]
fn capture_selected_text_windows() -> Result<String, PlatformError> {
    use std::thread;
    use windows_sys::Win32::System::DataExchange::GetClipboardSequenceNumber;
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
        GetAsyncKeyState, MapVirtualKeyW, SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT,
        KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, MAPVK_VK_TO_VSC, VK_CONTROL, VK_LCONTROL,
        VK_LMENU, VK_LSHIFT, VK_LWIN, VK_MENU, VK_RCONTROL, VK_RMENU, VK_RSHIFT, VK_RWIN,
        VK_SHIFT,
    };
    use windows_sys::Win32::UI::WindowsAndMessaging::{GetForegroundWindow, GetWindowTextW};

    let fg_title = unsafe {
        let hwnd = GetForegroundWindow();
        if hwnd.is_null() {
            String::new()
        } else {
            let mut buf = [0u16; 128];
            let n = GetWindowTextW(hwnd, buf.as_mut_ptr(), buf.len() as i32);
            if n > 0 {
                String::from_utf16_lossy(&buf[..n as usize])
            } else {
                String::new()
            }
        }
    };

    if let Some(uia_text) = try_uia_selected_text_windows() {
        tracing::info!(
            "Quick selection captured via UIA ({} chars, fg={:?})",
            uia_text.chars().count(),
            fg_title
        );
        return Ok(uia_text);
    }

    enum SavedClipboard {
        Text(String),
        Image {
            width: usize,
            height: usize,
            bytes: Vec<u8>,
        },
        None,
    }

    let mut cb = arboard::Clipboard::new()
        .map_err(|e| PlatformError::Failed(format!("无法访问剪贴板：{e}")))?;

    let saved = if let Ok(t) = cb.get_text() {
        SavedClipboard::Text(t)
    } else if let Ok(img) = cb.get_image() {
        SavedClipboard::Image {
            width: img.width,
            height: img.height,
            bytes: img.bytes.into_owned(),
        }
    } else {
        SavedClipboard::None
    };

    let seq_before = unsafe { GetClipboardSequenceNumber() };

    let is_pressed = |vk: u16| -> bool {
        (unsafe { GetAsyncKeyState(vk as i32) } as u16 & 0x8000) != 0
    };

    let key_input = |vk: u16, flags: u32| -> INPUT {
        let scan = unsafe { MapVirtualKeyW(vk as u32, MAPVK_VK_TO_VSC) } as u16;
        let ext = if matches!(vk, VK_RMENU | VK_RCONTROL | VK_LWIN | VK_RWIN) {
            KEYEVENTF_EXTENDEDKEY
        } else {
            0
        };
        INPUT {
            r#type: INPUT_KEYBOARD,
            Anonymous: INPUT_0 {
                ki: KEYBDINPUT {
                    wVk: vk,
                    wScan: scan,
                    dwFlags: flags | ext,
                    time: 0,
                    dwExtraInfo: 0,
                },
            },
        }
    };

    let send_inputs = |inputs: &[INPUT]| {
        if inputs.is_empty() {
            return;
        }
        unsafe {
            SendInput(
                inputs.len() as u32,
                inputs.as_ptr(),
                std::mem::size_of::<INPUT>() as i32,
            );
        }
    };

    // Wait briefly for the user to finish releasing the trigger key (e.g. S/Q) and modifiers.
    for _ in 0..25 {
        let any_trigger_down = (0x30u16..=0x5A).any(is_pressed) || (0x70u16..=0x87).any(is_pressed);
        let any_mod_down = is_pressed(VK_MENU)
            || is_pressed(VK_LMENU)
            || is_pressed(VK_RMENU)
            || is_pressed(VK_SHIFT)
            || is_pressed(VK_LSHIFT)
            || is_pressed(VK_RSHIFT)
            || is_pressed(VK_LWIN)
            || is_pressed(VK_RWIN)
            || is_pressed(VK_CONTROL)
            || is_pressed(VK_LCONTROL)
            || is_pressed(VK_RCONTROL);
        if !any_trigger_down && !any_mod_down {
            break;
        }
        thread::sleep(Duration::from_millis(12));
    }

    // If Alt is still held, press Ctrl before releasing Alt so browsers (Chrome/Edge)
    // do not treat Alt release as a single-Alt menu bar focus trigger (SC_KEYMENU).
    let alt_held = is_pressed(VK_MENU) || is_pressed(VK_LMENU) || is_pressed(VK_RMENU);
    let mut pre_release: Vec<INPUT> = Vec::new();
    let mut ctrl_already_down = false;
    if alt_held {
        pre_release.push(key_input(VK_CONTROL, 0));
        ctrl_already_down = true;
    }
    for vk in [
        VK_LMENU,
        VK_RMENU,
        VK_MENU,
        VK_LSHIFT,
        VK_RSHIFT,
        VK_SHIFT,
        VK_LWIN,
        VK_RWIN,
    ] {
        if is_pressed(vk) {
            pre_release.push(key_input(vk, KEYEVENTF_KEYUP));
        }
    }
    if !ctrl_already_down {
        for vk in [VK_LCONTROL, VK_RCONTROL, VK_CONTROL] {
            if is_pressed(vk) {
                pre_release.push(key_input(vk, KEYEVENTF_KEYUP));
            }
        }
    }
    if !pre_release.is_empty() {
        send_inputs(&pre_release);
        thread::sleep(Duration::from_millis(20));
    }

    const VK_C: u16 = 0x43;
    let mut copy_inputs: Vec<INPUT> = Vec::with_capacity(4);
    if !ctrl_already_down {
        copy_inputs.push(key_input(VK_CONTROL, 0));
    }
    copy_inputs.push(key_input(VK_C, 0));
    copy_inputs.push(key_input(VK_C, KEYEVENTF_KEYUP));
    copy_inputs.push(key_input(VK_CONTROL, KEYEVENTF_KEYUP));
    send_inputs(&copy_inputs);

    let mut copied = false;
    for _ in 0..20 {
        thread::sleep(Duration::from_millis(15));
        let seq_now = unsafe { GetClipboardSequenceNumber() };
        if seq_now != seq_before {
            copied = true;
            break;
        }
    }

    if !copied {
        tracing::info!(
            "Quick selection Ctrl+C produced no clipboard change (fg={:?})",
            fg_title
        );
        return Ok(String::new());
    }

    thread::sleep(Duration::from_millis(15));
    let mut selected = String::new();
    for _ in 0..3 {
        if let Ok(t) = cb.get_text() {
            selected = t.trim().to_string();
            break;
        }
        thread::sleep(Duration::from_millis(10));
    }

    // Restore user's previous clipboard contents so quick-translate doesn't clobber it.
    match saved {
        SavedClipboard::Text(prev) => {
            let _ = cb.set_text(prev);
        }
        SavedClipboard::Image {
            width,
            height,
            bytes,
        } => {
            let _ = cb.set_image(arboard::ImageData {
                width,
                height,
                bytes: std::borrow::Cow::Owned(bytes),
            });
        }
        SavedClipboard::None => {
            let _ = cb.clear();
        }
    }

    tracing::info!(
        "Quick selection captured via Ctrl+C ({} chars, fg={:?})",
        selected.chars().count(),
        fg_title
    );
    Ok(selected)
}

pub async fn read_clipboard_text() -> Result<String, PlatformError> {
    #[cfg(target_os = "windows")]
    {
        let mut cb = arboard::Clipboard::new()
            .map_err(|e| PlatformError::Failed(format!("无法访问剪贴板：{e}")))?;
        let text = cb
            .get_text()
            .map_err(|e| PlatformError::Failed(format!("剪贴板无文本：{e}")))?;
        Ok(text.trim().to_string())
    }
    #[cfg(not(target_os = "windows"))]
    {
        for (bin, args) in [
            ("wl-paste", &["--no-newline"][..]),
            ("xclip", &["-selection", "clipboard", "-o"][..]),
            ("pbpaste", &[][..]),
        ] {
            if which::which(bin).is_err() {
                continue;
            }
            if let Ok(Ok(out)) =
                timeout(Duration::from_secs(10), Command::new(bin).args(args).output()).await
            {
                if out.status.success() {
                    let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
                    if !s.is_empty() {
                        return Ok(s);
                    }
                }
            }
        }
        Err(PlatformError::Failed(
            "未找到 wl-paste 或 xclip，或剪贴板为空".to_string(),
        ))
    }
}

pub async fn write_clipboard_text(text: &str) -> Result<(), PlatformError> {
    if text.is_empty() {
        return Ok(());
    }
    #[cfg(target_os = "windows")]
    {
        let mut cb = arboard::Clipboard::new()
            .map_err(|e| PlatformError::Failed(format!("无法访问剪贴板：{e}")))?;
        cb.set_text(text.to_string())
            .map_err(|e| PlatformError::Failed(format!("写入剪贴板失败：{e}")))?;
        Ok(())
    }
    #[cfg(not(target_os = "windows"))]
    {
        for (bin, args) in [
            ("wl-copy", &[][..]),
            ("xclip", &["-selection", "clipboard"][..]),
            ("pbcopy", &[][..]),
        ] {
            if which::which(bin).is_err() {
                continue;
            }
            let Ok(mut child) = Command::new(bin)
                .args(args)
                .stdin(Stdio::piped())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
            else {
                continue;
            };
            if let Some(mut stdin) = child.stdin.take() {
                let _ = stdin.write_all(text.as_bytes()).await;
            }
            if let Ok(Ok(status)) = timeout(Duration::from_secs(5), child.wait()).await {
                if status.success() {
                    return Ok(());
                }
            }
        }
        Err(PlatformError::Failed("无可用剪贴板写入工具".to_string()))
    }
}

// ── Clipboard Image ───────────────────────────────────────────────

pub async fn read_clipboard_image_png() -> Result<Vec<u8>, PlatformError> {
    #[cfg(target_os = "windows")]
    {
        use image::{DynamicImage, ImageBuffer, ImageFormat, Rgba};
        use std::io::Cursor;

        let mut cb = arboard::Clipboard::new()
            .map_err(|e| PlatformError::Failed(format!("无法访问剪贴板：{e}")))?;
        let img_data = cb
            .get_image()
            .map_err(|e| PlatformError::Failed(format!("剪贴板中没有图片：{e}")))?;
        let buf: ImageBuffer<Rgba<u8>, Vec<u8>> = ImageBuffer::from_raw(
            img_data.width as u32,
            img_data.height as u32,
            img_data.bytes.into_owned(),
        )
        .ok_or_else(|| PlatformError::Failed("剪贴板图片像素缓冲区异常".to_string()))?;
        let mut out = Cursor::new(Vec::new());
        DynamicImage::ImageRgba8(buf)
            .write_to(&mut out, ImageFormat::Png)
            .map_err(|e| PlatformError::Failed(format!("编码剪贴板图片失败：{e}")))?;
        Ok(out.into_inner())
    }
    #[cfg(not(target_os = "windows"))]
    {
        read_clipboard_image_wayland().await
    }
}

#[cfg(not(target_os = "windows"))]
async fn read_clipboard_image_wayland() -> Result<Vec<u8>, PlatformError> {
    if which::which("wl-paste").is_err() {
        return Err(PlatformError::Failed(
            "未找到 wl-paste。请安装 wl-clipboard".to_string(),
        ));
    }

    let list_out = timeout(
        Duration::from_secs(10),
        Command::new("wl-paste").arg("--list-types").output(),
    )
    .await
    .map_err(|_| PlatformError::Failed("读取剪贴板类型超时".to_string()))?
    .map_err(|e| PlatformError::Failed(format!("执行 wl-paste 失败：{e}")))?;

    let types: Vec<String> = if list_out.status.success() {
        String::from_utf8_lossy(&list_out.stdout)
            .lines()
            .map(|l| l.trim().to_string())
            .filter(|l| !l.is_empty())
            .collect()
    } else {
        Vec::new()
    };

    let image_types: Vec<String> = types
        .iter()
        .filter(|t| t.starts_with("image/"))
        .cloned()
        .collect();

    if !types.is_empty() && image_types.is_empty() {
        return Err(PlatformError::Failed("剪贴板中没有图片数据".to_string()));
    }

    let preferred = [
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/bmp",
        "image/gif",
    ];
    let candidates: Vec<String> = if image_types.is_empty() {
        preferred.iter().map(|s| (*s).to_string()).collect()
    } else {
        let mut ordered: Vec<String> = preferred
            .iter()
            .filter(|m| image_types.iter().any(|t| t == *m))
            .map(|s| (*s).to_string())
            .collect();
        for t in image_types {
            if !ordered.contains(&t) {
                ordered.push(t);
            }
        }
        ordered
    };

    let mut last_err = String::new();
    for mime in candidates {
        let res = timeout(
            Duration::from_secs(10),
            Command::new("wl-paste")
                .args(["--type", &mime, "--no-newline"])
                .output(),
        )
        .await;
        if let Ok(Ok(out)) = res {
            if out.status.success() && !out.stdout.is_empty() {
                match normalize_to_png(&out.stdout) {
                    Ok(png) => return Ok(png),
                    Err(e) => last_err = e.to_string(),
                }
            } else {
                last_err = String::from_utf8_lossy(&out.stderr).trim().to_string();
            }
        }
    }

    if !last_err.is_empty() {
        Err(PlatformError::Failed(format!(
            "剪贴板图片不可用：{last_err}"
        )))
    } else {
        Err(PlatformError::Failed("剪贴板中没有图片数据".to_string()))
    }
}

// ── Desktop Notification (CLI) ────────────────────────────────────

pub async fn send_notification(title: &str, body: &str) {
    let mut clean = body.trim().replace('\n', " ");
    if clean.chars().count() > 200 {
        clean = clean.chars().take(199).collect::<String>() + "…";
    }
    #[cfg(not(target_os = "windows"))]
    {
        if which::which("notify-send").is_ok() {
            let _ = timeout(
                Duration::from_secs(5),
                Command::new("notify-send").args([title, &clean]).output(),
            )
            .await;
        }
    }
    #[cfg(target_os = "windows")]
    {
        let _ = (title, clean);
    }
}
