//! Windows virtual-desktop capture + transparent full-screen overlay window for region crop.

#[cfg(target_os = "windows")]
use std::io::Cursor;
#[cfg(target_os = "windows")]
use std::sync::Arc;

#[cfg(target_os = "windows")]
use base64::engine::general_purpose::STANDARD as BASE64;
#[cfg(target_os = "windows")]
use base64::Engine;
#[cfg(target_os = "windows")]
use image::{DynamicImage, ImageFormat, RgbaImage};
#[cfg(target_os = "windows")]
use tauri::{
    AppHandle, Emitter, Manager, PhysicalPosition, PhysicalSize, Position, Size, State, WebviewUrl,
    WebviewWindowBuilder,
};

#[cfg(target_os = "windows")]
use crate::commands::{AppState, CropRect};

#[cfg(target_os = "windows")]
struct CapturedDesktop {
    min_x: i32,
    min_y: i32,
    total_w: u32,
    total_h: u32,
    png_bytes: Vec<u8>,
}

#[cfg(target_os = "windows")]
fn capture_virtual_desktop() -> Result<CapturedDesktop, String> {
    let monitors = xcap::Monitor::all().map_err(|e| format!("枚举显示器失败：{e}"))?;
    if monitors.is_empty() {
        return Err("未检测到可用显示器".to_string());
    }

    let mut min_x = i32::MAX;
    let mut min_y = i32::MAX;
    let mut max_x = i32::MIN;
    let mut max_y = i32::MIN;

    struct Shot {
        x: i32,
        y: i32,
        img: RgbaImage,
    }
    let mut shots = Vec::new();
    for mon in monitors {
        let x = mon.x().map_err(|e| format!("获取显示器位置失败：{e}"))?;
        let y = mon.y().map_err(|e| format!("获取显示器位置失败：{e}"))?;
        let img = mon.capture_image().map_err(|e| format!("屏幕捕获失败：{e}"))?;
        min_x = min_x.min(x);
        min_y = min_y.min(y);
        max_x = max_x.max(x + img.width() as i32);
        max_y = max_y.max(y + img.height() as i32);
        shots.push(Shot { x, y, img });
    }

    let total_w = (max_x - min_x).max(1) as u32;
    let total_h = (max_y - min_y).max(1) as u32;
    let mut canvas = RgbaImage::new(total_w, total_h);
    for shot in shots {
        let ox = (shot.x - min_x) as i64;
        let oy = (shot.y - min_y) as i64;
        image::imageops::overlay(&mut canvas, &shot.img, ox, oy);
    }

    let mut png = Cursor::new(Vec::new());
    DynamicImage::ImageRgba8(canvas)
        .write_to(&mut png, ImageFormat::Png)
        .map_err(|e| format!("编码屏幕截图失败：{e}"))?;

    Ok(CapturedDesktop {
        min_x,
        min_y,
        total_w,
        total_h,
        png_bytes: png.into_inner(),
    })
}

#[cfg(target_os = "windows")]
pub async fn start_region_capture(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
) -> Result<Option<String>, String> {
    if let Some(main_win) = app.get_webview_window("main") {
        let _ = main_win.hide();
        tokio::time::sleep(std::time::Duration::from_millis(160)).await;
    }

    let captured = match tokio::task::spawn_blocking(capture_virtual_desktop).await {
        Ok(Ok(c)) => c,
        Ok(Err(e)) => {
            restore_main(&app);
            return Err(e);
        }
        Err(e) => {
            restore_main(&app);
            return Err(format!("屏幕捕获线程异常：{e}"));
        }
    };

    *state.pending_screenshot_png.lock().await = Some(captured.png_bytes);

    if let Some(old) = app.get_webview_window("screenshot") {
        let _ = old.close();
    }

    let win = WebviewWindowBuilder::new(
        &app,
        "screenshot",
        WebviewUrl::App("index.html?mode=screenshot".into()),
    )
    .title("截图框选")
    .decorations(false)
    .always_on_top(true)
    .skip_taskbar(true)
    .visible(false)
    .build()
    .map_err(|e| {
        restore_main(&app);
        format!("创建截图框选窗口失败：{e}")
    })?;
    let _ = win.set_position(Position::Physical(PhysicalPosition {
        x: captured.min_x,
        y: captured.min_y,
    }));
    let _ = win.set_size(Size::Physical(PhysicalSize {
        width: captured.total_w,
        height: captured.total_h,
    }));
    let _ = win.set_position(Position::Physical(PhysicalPosition {
        x: captured.min_x,
        y: captured.min_y,
    }));
    let _ = win.show();
    let _ = win.set_focus();
    Ok(None)
}

#[cfg(target_os = "windows")]
pub async fn finish_region_capture(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
    crop: Option<CropRect>,
) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("screenshot") {
        let _ = win.close();
    }
    let raw_opt = state.pending_screenshot_png.lock().await.take();
    restore_main(&app);

    let Some(crop_rect) = crop else {
        let _ = app.emit("screenshot-result", Option::<String>::None);
        return Ok(());
    };
    let Some(raw) = raw_opt else {
        return Err("没有待裁切的屏幕截图".to_string());
    };

    let img = image::load_from_memory(&raw).map_err(|e| format!("解析截图失败：{e}"))?;
    let x = crop_rect.x.min(img.width().saturating_sub(1));
    let y = crop_rect.y.min(img.height().saturating_sub(1));
    let w = crop_rect.width.min(img.width().saturating_sub(x)).max(1);
    let h = crop_rect.height.min(img.height().saturating_sub(y)).max(1);
    let cropped = img.crop_imm(x, y, w, h);

    let mut out = Cursor::new(Vec::new());
    cropped
        .write_to(&mut out, ImageFormat::Png)
        .map_err(|e| format!("编码裁切图失败：{e}"))?;
    let _ = app.emit("screenshot-result", Some(BASE64.encode(out.into_inner())));
    Ok(())
}

#[cfg(target_os = "windows")]
fn restore_main(app: &AppHandle) {
    if let Some(main_win) = app.get_webview_window("main") {
        let _ = main_win.show();
        let _ = main_win.unminimize();
        let _ = main_win.set_focus();
    }
}
