#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    #[cfg(target_os = "linux")]
    {
        // Work around WebKitGTK DMA-BUF renderer deadlocks/blank windows on
        // Wayland + NVIDIA hybrid GPU setups (e.g. niri / Hyprland).
        let is_wayland = std::env::var_os("WAYLAND_DISPLAY").is_some();
        let has_nvidia = std::path::Path::new("/sys/module/nvidia").exists()
            || std::path::Path::new("/dev/nvidia0").exists();
        if is_wayland
            && has_nvidia
            && std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none()
        {
            std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
        }
    }

    ai_translator_app_lib::run();
}
