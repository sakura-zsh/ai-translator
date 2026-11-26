export type ApiProtocol = "chat_completions" | "responses";
export type JevProtocol = "auto" | "native" | "openai";
export type ImageMode = "ocr" | "vision";
export type ThemeMode = "dark" | "light";

export const MODEL_AUTO = "__auto__";
export const MODEL_VISION = "__vision__";
export const AUTO_SCENE_ID = "auto";
export const AUTO_SCENE_LABEL = "自动判断（Jev）";

export const REASONING_EFFORTS = ["", "low", "medium", "high", "xhigh", "max"] as const;
export type ReasoningEffort = (typeof REASONING_EFFORTS)[number];

export const EFFORT_LABELS: Record<ReasoningEffort, string> = {
  "": "default",
  low: "low",
  medium: "medium",
  high: "high",
  xhigh: "xhigh",
  max: "max",
};

export const EFFORT_SHORT_LABELS: Record<ReasoningEffort, string> = {
  "": "default",
  low: "low",
  medium: "medium",
  high: "high",
  xhigh: "xhigh",
  max: "max",
};

export interface LlmProfile {
  id: string;
  name: string;
  base_url: string;
  api_key: string;
  api_protocol: ApiProtocol;
  model: string;
  models: string[];
  vision_model: string;
  temperature: number;
  timeout_s: number;
  max_tokens: number;
  reasoning_effort: string;
  model_options: string[];
}

export interface JevConfig {
  enabled: boolean;
  base_url: string;
  api_key: string;
  model: string;
  api_protocol: JevProtocol;
  timeout_s: number;
  route_scene: boolean;
  detect_language: boolean;
  score_quality: boolean;
  quality_threshold: number;
  retry_on_low_quality: boolean;
}

export interface CustomScene {
  id: string;
  label: string;
  prompt: string;
}

export interface TranslationConfig {
  source_lang: string;
  target_lang: string;
  image_mode: ImageMode;
  supplementary_prompt: string;
  ocr_langs: string;
  auto_copy_result: boolean;
  auto_dictionary: boolean;
  scene: string;
  glossary: Record<string, string>;
  tesseract_path: string;
  custom_scenes: CustomScene[];
}

export interface HotkeysConfig {
  translate: string;
  screenshot: string;
  paste_image: string;
  swap_langs: string;
  copy_result: string;
  extract_text: string;
  summon: string;
  quick_translate: string;
}

export interface TtsConfig {
  voice: string;
  rate: number;
  auto_pronounce: boolean;
}

export interface UiConfig {
  theme: ThemeMode;
  window_width: number;
  window_height: number;
  window_maximized: boolean;
  splitter_sizes: number[];
  close_to_tray: boolean;
  hotkeys: HotkeysConfig;
}

export interface HistoryEntry {
  id: string;
  ts: number;
  source_lang: string;
  target_lang: string;
  mode: string;
  source_text: string;
  result_text: string;
  model: string;
}

export type FavoriteEntry = HistoryEntry;

export interface AppConfig {
  version: number;
  active_profile_id: string;
  profiles: LlmProfile[];
  translation: TranslationConfig;
  ui: UiConfig;
  tts: TtsConfig;
  jev: JevConfig;
  history: HistoryEntry[];
  history_limit: number;
  favorites: FavoriteEntry[];
  last_run_version: string;
}

export interface TranslateStreamEvent {
  request_id: string;
  delta: string;
  reset: boolean;
}

export interface LoadInMainPayload {
  source_text: string;
  result_text: string;
}

export interface ToggleFavoriteOutput {
  favorited: boolean;
  config: AppConfig;
}

export interface LanguageItem {
  code: string;
  label: string;
}

export interface ProviderTemplate {
  id: string;
  name: string;
  base_url: string;
  text_model: string;
  vision_model: string;
  api_protocol: ApiProtocol;
  key_required: boolean;
  hint: string;
}

export interface ScenePreset {
  id: string;
  label: string;
  prompt: string;
  builtin: boolean;
}

export interface VoiceChoice {
  label: string;
  voice: string;
}

export interface BootstrapData {
  version: string;
  previous_version: string;
  is_windows: boolean;
  tray_available: boolean;
  config: AppConfig;
  needs_setup: boolean;
  source_languages: LanguageItem[];
  target_languages: LanguageItem[];
  provider_templates: ProviderTemplate[];
  scenes: ScenePreset[];
  tts_voices: VoiceChoice[];
}

export interface TranslateResult {
  text: string;
  ocr_text: string | null;
  model: string;
  mode: string;
  warnings: string[];
  notes: string[];
  quality_score: number | null;
  retried: boolean;
}

export interface TranslateCommandOutput {
  result: TranslateResult;
  config: AppConfig;
}

export interface ScreenshotSourcePayload {
  image_base64: string;
  width: number;
  height: number;
}

export interface CropRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function displayModelLabel(model: string): string {
  if (model === MODEL_AUTO) return "自动选择";
  if (model === MODEL_VISION) return "跟随视觉模型";
  return model || "未选择";
}

export function truncateLabel(text: string, maxLen = 30): string {
  if (text.length <= maxLen) return text;
  return `${text.slice(0, maxLen - 1)}…`;
}

export function likelyReasoningModel(name: string): boolean {
  return /reasoner|[-_]r1\b|qwq|o[134](-|$|\b)|thinking|deepseek-r\d/i.test(name);
}

export function newShortId(): string {
  return Math.random().toString(36).slice(2, 14).padEnd(12, "0");
}
