//! Windows auto-start management via HKCU\Software\Microsoft\Windows\CurrentVersion\Run.

#[cfg(target_os = "windows")]
use std::path::{Path, PathBuf};

#[cfg(target_os = "windows")]
const RUN_SUBKEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Run";
#[cfg(target_os = "windows")]
const VALUE_NAME: &str = "AI Translator";

#[cfg(target_os = "windows")]
fn normalize_command_path(raw: &str) -> String {
    let trimmed = raw.trim();
    let unquoted = if trimmed.starts_with('"') {
        trimmed
            .strip_prefix('"')
            .and_then(|rest| rest.split('"').next())
            .unwrap_or(trimmed)
    } else {
        trimmed
    };
    unquoted.trim().to_ascii_lowercase()
}

#[cfg(target_os = "windows")]
fn format_run_command(exe_path: &Path) -> String {
    format!("\"{}\"", exe_path.display())
}

#[cfg(target_os = "windows")]
fn current_exe_normalized() -> Option<String> {
    let exe: PathBuf = std::env::current_exe().ok()?;
    Some(exe.to_string_lossy().trim().to_ascii_lowercase())
}

#[cfg(target_os = "windows")]
pub fn is_enabled() -> bool {
    use winreg::enums::HKEY_CURRENT_USER;
    use winreg::RegKey;

    let hkcu = RegKey::predef(HKEY_CURRENT_USER);
    let Ok(run_key) = hkcu.open_subkey(RUN_SUBKEY) else {
        return false;
    };
    let Ok(val) = run_key.get_value::<String, _>(VALUE_NAME) else {
        return false;
    };
    let normalized = normalize_command_path(&val);
    if normalized.is_empty() {
        return false;
    }
    match current_exe_normalized() {
        Some(cur) => normalized == cur,
        None => true,
    }
}

#[cfg(target_os = "windows")]
pub fn set_enabled(enabled: bool) -> Result<(), String> {
    use std::io::ErrorKind;
    use winreg::enums::{HKEY_CURRENT_USER, KEY_SET_VALUE};
    use winreg::RegKey;

    let hkcu = RegKey::predef(HKEY_CURRENT_USER);
    if enabled {
        let exe = std::env::current_exe()
            .map_err(|e| format!("无法获取当前程序路径：{e}"))?;
        let (run_key, _) = hkcu
            .create_subkey(RUN_SUBKEY)
            .map_err(|e| format!("无法打开注册表启动项：{e}"))?;
        let cmd = format_run_command(&exe);
        run_key
            .set_value(VALUE_NAME, &cmd)
            .map_err(|e| format!("写入开机自启注册表失败：{e}"))?;
    } else {
        match hkcu.open_subkey_with_flags(RUN_SUBKEY, KEY_SET_VALUE) {
            Ok(run_key) => {
                if let Err(e) = run_key.delete_value(VALUE_NAME) {
                    if e.kind() != ErrorKind::NotFound {
                        return Err(format!("移除开机自启注册表失败：{e}"));
                    }
                }
            }
            Err(e) if e.kind() == ErrorKind::NotFound => {}
            Err(e) => return Err(format!("无法访问注册表启动项：{e}")),
        }
    }
    Ok(())
}

#[cfg(all(test, target_os = "windows"))]
mod tests {
    use super::*;

    #[test]
    fn command_formatting_and_normalization() {
        let p = PathBuf::from(r"C:\Program Files\AI Translator\ai-translator.exe");
        let cmd = format_run_command(&p);
        assert_eq!(cmd, r#""C:\Program Files\AI Translator\ai-translator.exe""#);
        assert_eq!(
            normalize_command_path(&cmd),
            r"c:\program files\ai translator\ai-translator.exe"
        );
        assert_eq!(
            normalize_command_path(r"  C:\Tools\AI-Translator.exe  "),
            r"c:\tools\ai-translator.exe"
        );
    }
}
