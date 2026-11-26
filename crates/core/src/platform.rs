//! Cross-platform desktop helpers: clipboard text/image, Wayland region screenshot, notifications.

use std::process::Stdio;
use std::time::Duration;

use thiserror::Error;
use tokio::io::AsyncWriteExt;
use tokio::process::Command;
use tokio::time::timeout;

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
