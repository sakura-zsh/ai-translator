//! Load and atomically save `config.json` (Windows: %APPDATA%, Linux/Unix: XDG).

use std::env;
use std::fs::{self, File};
use std::io::{self, Write};
use std::path::{Path, PathBuf};

use serde_json::Value;

use crate::config::schema::AppConfig;

pub fn default_config_path() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        let base = env::var_os("APPDATA")
            .filter(|v| !v.is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                let home = env::var_os("USERPROFILE")
                    .map(PathBuf::from)
                    .unwrap_or_else(|| PathBuf::from("."));
                home.join("AppData").join("Roaming")
            });
        base.join("ai-translator").join("config.json")
    }
    #[cfg(not(target_os = "windows"))]
    {
        let base = env::var_os("XDG_CONFIG_HOME")
            .filter(|v| !v.is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                let home = env::var_os("HOME")
                    .map(PathBuf::from)
                    .unwrap_or_else(|| PathBuf::from("."));
                home.join(".config")
            });
        base.join("ai-translator").join("config.json")
    }
}

#[derive(Debug, Clone)]
pub struct ConfigStore {
    path: PathBuf,
}

impl ConfigStore {
    pub fn new(path: Option<PathBuf>) -> Self {
        Self {
            path: path.unwrap_or_else(default_config_path),
        }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn load(&self) -> AppConfig {
        if !self.path.exists() {
            let cfg = AppConfig::default();
            // Best-effort first-run write; read-only HOME must not crash startup.
            let _ = self.save(&cfg);
            return cfg;
        }
        let Ok(raw) = fs::read_to_string(&self.path) else {
            return AppConfig::default();
        };
        if raw.trim().is_empty() {
            return AppConfig::default();
        }
        match serde_json::from_str::<Value>(&raw) {
            Ok(val) if val.is_object() => AppConfig::from_json_value(&val),
            _ => AppConfig::default(),
        }
    }

    pub fn save(&self, config: &AppConfig) -> io::Result<()> {
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent)?;
        }
        let parent = self
            .path
            .parent()
            .unwrap_or_else(|| Path::new("."));
        let mut payload = serde_json::to_string_pretty(config)
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
        payload.push('\n');

        let mut tmp = tempfile::Builder::new()
            .prefix(".config.")
            .suffix(".tmp")
            .tempfile_in(parent)?;
        tmp.write_all(payload.as_bytes())?;
        tmp.flush()?;
        tmp.as_file().sync_all()?;

        tmp.persist(&self.path).map_err(|e| e.error)?;

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = fs::set_permissions(&self.path, fs::Permissions::from_mode(0o600));
        }

        // Verify readable handle on Windows / Unix isn't needed; persist is atomic.
        let _ = File::open(&self.path);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn roundtrip_save_and_load() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("config.json");
        let store = ConfigStore::new(Some(path.clone()));
        let mut cfg = store.load();
        assert!(path.exists());
        assert!(cfg.needs_setup());

        cfg.profiles[0].api_key = "sk-abc".into();
        cfg.translation.glossary.insert("LLM".into(), "大语言模型".into());
        store.save(&cfg).unwrap();

        let loaded = store.load();
        assert_eq!(loaded.profiles[0].api_key, "sk-abc");
        assert_eq!(
            loaded.translation.glossary.get("LLM").map(String::as_str),
            Some("大语言模型")
        );
    }

    #[test]
    fn corrupt_json_falls_back_to_default() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("config.json");
        fs::write(&path, "{not valid json").unwrap();
        let store = ConfigStore::new(Some(path));
        let cfg = store.load();
        assert_eq!(cfg.active_profile_id, "default");
    }
}
