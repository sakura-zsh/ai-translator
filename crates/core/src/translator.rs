//! Translation orchestrator: text, dictionary, OCR, vision, streaming, and Jev judging.

use indexmap::IndexMap;
use serde::Serialize;
use serde_json::json;
use thiserror::Error;
use tracing::warn;

use crate::config::schema::{
    resolve_model, ImageMode, JevConfig, LlmProfile, TranslationConfig,
};
use crate::imaging::{downscale_for_vision, VISION_JPEG_QUALITY, VISION_MAX_DIM};
use crate::jev_client::JevClient;
use crate::languages::{display_name, target_languages};
use crate::llm_client::{LlmClient, LlmError};
use crate::ocr::{OcrError, OcrService};
use crate::presets::{all_scene_presets, combine_extra_prompt, get_scene, AUTO_SCENE_ID};
use crate::prompts::{build_dictionary_prompt, build_system_prompt, is_dictionary_query};

#[derive(Debug, Error)]
pub enum TranslateError {
    #[error("{0}")]
    Validation(String),
    #[error(transparent)]
    Ocr(#[from] OcrError),
    #[error(transparent)]
    Llm(#[from] LlmError),
}

#[derive(Debug, Clone, Serialize)]
pub struct TranslateResult {
    pub text: String,
    pub ocr_text: Option<String>,
    pub model: String,
    pub mode: String,
    pub warnings: Vec<String>,
    pub notes: Vec<String>,
    pub quality_score: Option<f64>,
    pub retried: bool,
}

#[derive(Debug, Clone)]
pub struct Translator {
    ocr: OcrService,
}

impl Default for Translator {
    fn default() -> Self {
        Self::new(OcrService::default())
    }
}

impl Translator {
    pub fn new(ocr: OcrService) -> Self {
        Self { ocr }
    }

    pub fn ocr(&self) -> &OcrService {
        &self.ocr
    }

    pub async fn translate_text(
        &self,
        text: &str,
        source_lang: &str,
        target_lang: &str,
        profile: &LlmProfile,
        supplementary_prompt: &str,
        glossary: Option<&IndexMap<String, String>>,
    ) -> Result<TranslateResult, TranslateError> {
        self.translate_text_with_options(
            text,
            source_lang,
            target_lang,
            profile,
            supplementary_prompt,
            glossary,
            false,
        )
        .await
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn translate_text_with_options(
        &self,
        text: &str,
        source_lang: &str,
        target_lang: &str,
        profile: &LlmProfile,
        supplementary_prompt: &str,
        glossary: Option<&IndexMap<String, String>>,
        allow_dictionary: bool,
    ) -> Result<TranslateResult, TranslateError> {
        let cleaned = text.trim();
        if cleaned.is_empty() {
            return Err(TranslateError::Validation(
                "Nothing to translate".to_string(),
            ));
        }

        let dict_mode = allow_dictionary && is_dictionary_query(cleaned, source_lang, target_lang);
        let system = if dict_mode {
            build_dictionary_prompt(source_lang, target_lang, supplementary_prompt, glossary)
        } else {
            build_system_prompt(source_lang, target_lang, supplementary_prompt, false, glossary)
        };
        let model = resolve_model(profile, false);
        let client = LlmClient::new(profile.clone())?;
        let out = client
            .chat(
                &[
                    json!({ "role": "system", "content": system }),
                    json!({ "role": "user", "content": cleaned }),
                ],
                Some(&model),
                None,
                None,
            )
            .await?;

        Ok(TranslateResult {
            text: out.text,
            ocr_text: None,
            model,
            mode: if dict_mode { "dict" } else { "text" }.to_string(),
            warnings: out.warnings,
            notes: if dict_mode {
                vec!["词典模式".to_string()]
            } else {
                Vec::new()
            },
            quality_score: None,
            retried: false,
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn translate_image(
        &self,
        image_png: &[u8],
        mode: &ImageMode,
        source_lang: &str,
        target_lang: &str,
        profile: &LlmProfile,
        supplementary_prompt: &str,
        glossary: Option<&IndexMap<String, String>>,
        ocr_langs: &str,
    ) -> Result<TranslateResult, TranslateError> {
        if image_png.is_empty() {
            return Err(TranslateError::Validation("Empty image".to_string()));
        }

        if matches!(mode, ImageMode::Ocr) {
            let ocr_text = self.ocr.extract_text(image_png, ocr_langs).await?;
            let mut result = self
                .translate_text(
                    &ocr_text,
                    source_lang,
                    target_lang,
                    profile,
                    supplementary_prompt,
                    glossary,
                )
                .await?;
            result.ocr_text = Some(ocr_text);
            result.mode = "ocr".to_string();
            return Ok(result);
        }

        let system = build_system_prompt(
            source_lang,
            target_lang,
            supplementary_prompt,
            true,
            glossary,
        );
        let model = resolve_model(profile, true);
        let client = LlmClient::new(profile.clone())?;
        let payload = downscale_for_vision(image_png, VISION_MAX_DIM, VISION_JPEG_QUALITY);
        let out = client
            .chat_vision(
                &system,
                "Translate the text visible in this image.",
                &payload,
                Some(&model),
            )
            .await?;

        Ok(TranslateResult {
            text: out.text,
            ocr_text: None,
            model,
            mode: "vision".to_string(),
            warnings: out.warnings,
            notes: Vec::new(),
            quality_score: None,
            retried: false,
        })
    }

    /// Streaming text translation with optional dictionary mode, Jev routing,
    /// language detection, quality scoring, and automatic retry.
    #[allow(clippy::too_many_arguments)]
    pub async fn translate_text_with_jev_stream<F, R>(
        &self,
        text: &str,
        source_lang: &str,
        target_lang: &str,
        profile: &LlmProfile,
        translation_cfg: &TranslationConfig,
        jev_cfg: &JevConfig,
        mut on_delta: F,
        mut on_reset: R,
    ) -> Result<TranslateResult, TranslateError>
    where
        F: FnMut(&str) + Send,
        R: FnMut() + Send,
    {
        let cleaned = text.trim();
        if cleaned.is_empty() {
            return Err(TranslateError::Validation(
                "Nothing to translate".to_string(),
            ));
        }

        let dict_mode = translation_cfg.auto_dictionary
            && is_dictionary_query(cleaned, source_lang, target_lang);

        let jev_client = if jev_cfg.enabled {
            JevClient::new(jev_cfg.clone())
                .ok()
                .filter(|c| c.is_configured())
        } else {
            None
        };

        let mut eff_source = source_lang.to_string();
        let mut eff_scene = translation_cfg.scene.clone();
        let mut notes = Vec::new();
        if dict_mode {
            notes.push("词典模式".to_string());
        }

        if let Some(ref jev) = jev_client {
            if jev_cfg.detect_language && eff_source == "auto" {
                let langs = target_languages();
                let pairs: Vec<(&str, &str)> = langs.iter().map(|l| (l.code, l.label)).collect();
                match jev.detect_language(cleaned, &pairs).await {
                    Ok(Some(code)) => {
                        notes.push(format!("Jev 语种 {}", display_name(&code)));
                        eff_source = code;
                    }
                    Ok(None) => {}
                    Err(e) => warn!("jev language detection failed: {e}"),
                }
            }

            if !dict_mode && jev_cfg.route_scene && eff_scene == AUTO_SCENE_ID {
                let scenes: Vec<(String, String, String)> =
                    all_scene_presets(&translation_cfg.custom_scenes)
                        .into_iter()
                        .map(|s| (s.id, s.label, s.prompt))
                        .collect();
                match jev.route_scene(cleaned, &scenes).await {
                    Ok(Some(picked)) => {
                        let label = get_scene(&picked, &translation_cfg.custom_scenes).label;
                        notes.push(format!("Jev 场景 {label}"));
                        eff_scene = picked;
                    }
                    Ok(None) => {}
                    Err(e) => warn!("jev scene routing failed: {e}"),
                }
            }
        }

        let extra = combine_extra_prompt(
            &eff_scene,
            &translation_cfg.custom_scenes,
            &translation_cfg.supplementary_prompt,
        );
        let glossary = if translation_cfg.glossary.is_empty() {
            None
        } else {
            Some(&translation_cfg.glossary)
        };

        let system = if dict_mode {
            build_dictionary_prompt(&eff_source, target_lang, &extra, glossary)
        } else {
            build_system_prompt(&eff_source, target_lang, &extra, false, glossary)
        };
        let model = resolve_model(profile, false);
        let client = LlmClient::new(profile.clone())?;
        let out = client
            .chat_stream(
                &[
                    json!({ "role": "system", "content": system }),
                    json!({ "role": "user", "content": cleaned }),
                ],
                Some(&model),
                &mut on_delta,
                &mut on_reset,
            )
            .await?;

        let mut result = TranslateResult {
            text: out.text,
            ocr_text: None,
            model,
            mode: if dict_mode { "dict" } else { "text" }.to_string(),
            warnings: out.warnings,
            notes: Vec::new(),
            quality_score: None,
            retried: false,
        };

        if let Some(ref jev) = jev_client {
            if !dict_mode && jev_cfg.score_quality {
                match jev.score_quality(cleaned, &result.text).await {
                    Ok(Some(score)) => {
                        result.quality_score = Some(score);
                        if jev_cfg.retry_on_low_quality && score < jev_cfg.quality_threshold {
                            let retry_extra = if extra.is_empty() {
                                "请特别注意忠实原文、不要漏译或误译，确保译文准确自然。".to_string()
                            } else {
                                format!(
                                    "{extra}\n请特别注意忠实原文、不要漏译或误译，确保译文准确自然。"
                                )
                            };
                            on_reset();
                            let retry_sys = build_system_prompt(
                                &eff_source,
                                target_lang,
                                &retry_extra,
                                false,
                                glossary,
                            );
                            if let Ok(retried) = client
                                .chat_stream(
                                    &[
                                        json!({ "role": "system", "content": retry_sys }),
                                        json!({ "role": "user", "content": cleaned }),
                                    ],
                                    Some(&result.model),
                                    &mut on_delta,
                                    &mut on_reset,
                                )
                                .await
                            {
                                let new_score = jev
                                    .score_quality(cleaned, &retried.text)
                                    .await
                                    .ok()
                                    .flatten();
                                if new_score.unwrap_or(score) >= score {
                                    result.text = retried.text;
                                    result.warnings.extend(retried.warnings);
                                    result.quality_score = new_score.or(Some(score));
                                    result.retried = true;
                                    notes.push("低分自动重译".to_string());
                                }
                            }
                        }
                    }
                    Ok(None) => {}
                    Err(e) => warn!("jev quality scoring failed: {e}"),
                }
            }
        }

        result.notes = notes;
        Ok(result)
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn translate_image_with_jev(
        &self,
        image_png: &[u8],
        mode: &ImageMode,
        source_lang: &str,
        target_lang: &str,
        profile: &LlmProfile,
        translation_cfg: &TranslationConfig,
        jev_cfg: &JevConfig,
    ) -> Result<TranslateResult, TranslateError> {
        if image_png.is_empty() {
            return Err(TranslateError::Validation("Empty image".to_string()));
        }
        if matches!(mode, ImageMode::Ocr) {
            let ocr_text = self
                .ocr
                .extract_text(image_png, &translation_cfg.ocr_langs)
                .await?;
            let mut result = self
                .translate_text_with_jev_stream(
                    &ocr_text,
                    source_lang,
                    target_lang,
                    profile,
                    translation_cfg,
                    jev_cfg,
                    |_| {},
                    || {},
                )
                .await?;
            result.ocr_text = Some(ocr_text);
            result.mode = "ocr".to_string();
            return Ok(result);
        }

        let extra = combine_extra_prompt(
            &translation_cfg.scene,
            &translation_cfg.custom_scenes,
            &translation_cfg.supplementary_prompt,
        );
        let glossary = if translation_cfg.glossary.is_empty() {
            None
        } else {
            Some(&translation_cfg.glossary)
        };
        self.translate_image(
            image_png,
            mode,
            source_lang,
            target_lang,
            profile,
            &extra,
            glossary,
            &translation_cfg.ocr_langs,
        )
        .await
    }
}
