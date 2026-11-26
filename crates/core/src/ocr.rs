//! OCR via tesseract CLI.

use std::time::Duration;

use tempfile::TempDir;
use thiserror::Error;
use tokio::process::Command;
use tokio::time::timeout;

use crate::imaging::prepare_for_ocr;

#[derive(Debug, Error)]
pub enum OcrError {
    #[error("{0}")]
    Failed(String),
}

pub fn install_hint() -> &'static str {
    #[cfg(target_os = "windows")]
    {
        "Install Tesseract for Windows from https://github.com/UB-Mannheim/tesseract/wiki \
and ensure tesseract.exe is on PATH (or set full path). Also install eng + chi_sim language data."
    }
    #[cfg(not(target_os = "windows"))]
    {
        "Install with: sudo pacman -S tesseract tesseract-data-eng tesseract-data-chi_sim"
    }
}

#[derive(Debug, Clone)]
pub struct OcrService {
    tesseract_bin: String,
    timeout_s: f64,
}

impl Default for OcrService {
    fn default() -> Self {
        Self::new("tesseract", 60.0)
    }
}

impl OcrService {
    pub fn new(tesseract_bin: impl Into<String>, timeout_s: f64) -> Self {
        let bin = tesseract_bin.into();
        let bin = if bin.trim().is_empty() {
            "tesseract".to_string()
        } else {
            bin.trim().to_string()
        };
        Self {
            tesseract_bin: bin,
            timeout_s,
        }
    }

    pub fn available(&self) -> bool {
        which::which(&self.tesseract_bin).is_ok()
    }

    pub async fn extract_text(&self, image_png: &[u8], langs: &str) -> Result<String, OcrError> {
        if !self.available() {
            return Err(OcrError::Failed(format!(
                "tesseract not found. {}",
                install_hint()
            )));
        }
        if image_png.is_empty() {
            return Err(OcrError::Failed("Empty image".to_string()));
        }

        let prepared = prepare_for_ocr(image_png, 1000, 2400);
        let tmp = TempDir::new().map_err(|e| OcrError::Failed(e.to_string()))?;
        let img_path = tmp.path().join("input.png");
        tokio::fs::write(&img_path, &prepared)
            .await
            .map_err(|e| OcrError::Failed(e.to_string()))?;

        let langs_arg = if langs.trim().is_empty() {
            "eng"
        } else {
            langs.trim()
        };

        let mut cmd = Command::new(&self.tesseract_bin);
        cmd.arg(&img_path)
            .arg("stdout")
            .arg("-l")
            .arg(langs_arg)
            .arg("--psm")
            .arg("6");
        #[cfg(target_os = "windows")]
        {
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        let output = timeout(Duration::from_secs_f64(self.timeout_s), cmd.output())
            .await
            .map_err(|_| OcrError::Failed("OCR timed out".to_string()))?
            .map_err(|e| OcrError::Failed(format!("Failed to run tesseract: {e}")))?;

        if !output.status.success() {
            let err = String::from_utf8_lossy(&output.stderr);
            if err.contains("Error opening data file") || err.contains("Failed loading language") {
                let preview: String = err.chars().take(300).collect();
                return Err(OcrError::Failed(format!(
                    "Missing tesseract language data for '{langs_arg}'. Install eng + chi_sim traineddata.\n{preview}"
                )));
            }
            let preview: String = err.chars().take(400).collect();
            return Err(OcrError::Failed(format!("tesseract failed: {preview}")));
        }

        let text = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if text.is_empty() {
            return Err(OcrError::Failed("OCR produced no text".to_string()));
        }
        Ok(text)
    }
}
