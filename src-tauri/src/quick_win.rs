//! Quick translation popup positioning (near cursor) and single native rounded corner on Windows.

use tauri::{AppHandle, LogicalSize, Size, WebviewWindow};

pub const QUICK_WIDTH_LOGICAL: f64 = 360.0;
pub const QUICK_HEIGHT_LOGICAL: f64 = 240.0;
pub const QUICK_MIN_WIDTH_LOGICAL: f64 = 280.0;
pub const QUICK_MIN_HEIGHT_LOGICAL: f64 = 180.0;

#[cfg(target_os = "windows")]
pub fn apply_single_rounded_corner(win: &WebviewWindow) {
    use windows_sys::Win32::Graphics::Dwm::{DwmSetWindowAttribute, DWMWA_WINDOW_CORNER_PREFERENCE};

    // DWMWCP_ROUND = 2: Windows 11 native single rounded corner & shadow.
    const DWMWCP_ROUND: u32 = 2;
    if let Ok(hwnd) = win.hwnd() {
        unsafe {
            let _ = DwmSetWindowAttribute(
                hwnd.0,
                DWMWA_WINDOW_CORNER_PREFERENCE as u32,
                &DWMWCP_ROUND as *const u32 as *const _,
                std::mem::size_of::<u32>() as u32,
            );
        }
    }
}

#[cfg(not(target_os = "windows"))]
pub fn apply_single_rounded_corner(_win: &WebviewWindow) {}

#[cfg(target_os = "windows")]
pub fn place_near_cursor(app: &AppHandle, win: &WebviewWindow) {
    use tauri::{PhysicalPosition, Position};
    use windows_sys::Win32::Foundation::POINT;
    use windows_sys::Win32::Graphics::Gdi::{
        GetMonitorInfoW, MonitorFromPoint, MONITORINFO, MONITOR_DEFAULTTONEAREST,
    };
    use windows_sys::Win32::UI::WindowsAndMessaging::GetCursorPos;

    let mut pt = POINT { x: 0, y: 0 };
    if unsafe { GetCursorPos(&mut pt) } == 0 {
        let _ = win.center();
        return;
    }

    let mut mi = MONITORINFO {
        cbSize: std::mem::size_of::<MONITORINFO>() as u32,
        ..unsafe { std::mem::zeroed() }
    };
    let hmon = unsafe { MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST) };
    if unsafe { GetMonitorInfoW(hmon, &mut mi) } == 0 {
        let _ = win.center();
        return;
    }

    let scale = monitor_scale_for_point(app, pt.x, pt.y)
        .or_else(|| win.scale_factor().ok())
        .unwrap_or(1.0)
        .max(0.5);

    let phys_w = (QUICK_WIDTH_LOGICAL * scale).round() as i32;
    let phys_h = (QUICK_HEIGHT_LOGICAL * scale).round() as i32;
    let offset_x = (12.0 * scale).round() as i32;
    let offset_y = (16.0 * scale).round() as i32;
    let margin = (8.0 * scale).round() as i32;

    let work = mi.rcWork;
    let (x, y) = compute_popup_origin(
        pt.x,
        pt.y,
        phys_w,
        phys_h,
        offset_x,
        offset_y,
        margin,
        work.left,
        work.top,
        work.right,
        work.bottom,
    );

    let _ = win.set_size(Size::Logical(LogicalSize {
        width: QUICK_WIDTH_LOGICAL,
        height: QUICK_HEIGHT_LOGICAL,
    }));
    let _ = win.set_position(Position::Physical(PhysicalPosition { x, y }));
    // Re-apply size in case crossing monitors with different DPI scales resized the window.
    let _ = win.set_size(Size::Logical(LogicalSize {
        width: QUICK_WIDTH_LOGICAL,
        height: QUICK_HEIGHT_LOGICAL,
    }));
}

#[cfg(not(target_os = "windows"))]
pub fn place_near_cursor(_app: &AppHandle, win: &WebviewWindow) {
    let _ = win.set_size(Size::Logical(LogicalSize {
        width: QUICK_WIDTH_LOGICAL,
        height: QUICK_HEIGHT_LOGICAL,
    }));
}

#[cfg(target_os = "windows")]
fn monitor_scale_for_point(app: &AppHandle, x: i32, y: i32) -> Option<f64> {
    let monitors = app.available_monitors().ok()?;
    for mon in monitors {
        let pos = mon.position();
        let size = mon.size();
        let right = pos.x + size.width as i32;
        let bottom = pos.y + size.height as i32;
        if x >= pos.x && x < right && y >= pos.y && y < bottom {
            return Some(mon.scale_factor());
        }
    }
    None
}

#[allow(clippy::too_many_arguments, dead_code)]
pub fn compute_popup_origin(
    cursor_x: i32,
    cursor_y: i32,
    win_w: i32,
    win_h: i32,
    offset_x: i32,
    offset_y: i32,
    margin: i32,
    work_left: i32,
    work_top: i32,
    work_right: i32,
    work_bottom: i32,
) -> (i32, i32) {
    let mut x = cursor_x + offset_x;
    if x + win_w > work_right - margin {
        x = cursor_x - win_w - offset_x;
    }
    let min_x = work_left + margin;
    let max_x = (work_right - win_w - margin).max(min_x);
    x = x.clamp(min_x, max_x);

    let mut y = cursor_y + offset_y;
    if y + win_h > work_bottom - margin {
        y = cursor_y - win_h - offset_y;
    }
    let min_y = work_top + margin;
    let max_y = (work_bottom - win_h - margin).max(min_y);
    y = y.clamp(min_y, max_y);

    (x, y)
}
