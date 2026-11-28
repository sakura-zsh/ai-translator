import { invoke } from "@tauri-apps/api/core";
import type {
  AppConfig,
  BootstrapData,
  CropRect,
  ImageMode,
  JevConfig,
  LlmProfile,
  ScreenshotSourcePayload,
  ThemeMode,
  ToggleFavoriteOutput,
  TranslateCommandOutput,
} from "./types";

export const api = {
  getBootstrap: () => invoke<BootstrapData>("get_bootstrap"),

  saveConfig: (newConfig: AppConfig) =>
    invoke<AppConfig>("save_config", { newConfig }),

  exportConfigJson: () => invoke<string>("export_config_json"),

  importConfigJson: (jsonText: string) =>
    invoke<AppConfig>("import_config_json", { jsonText }),

  setActiveProfile: (profileId: string) =>
    invoke<AppConfig>("set_active_profile", { profileId }),

  updateProfileSelection: (
    profileId: string,
    model?: string,
    reasoningEffort?: string,
  ) =>
    invoke<AppConfig>("update_profile_selection", {
      profileId,
      model: model ?? null,
      reasoningEffort: reasoningEffort ?? null,
    }),

  updateTranslationQuick: (params: {
    sourceLang?: string;
    targetLang?: string;
    imageMode?: ImageMode;
    scene?: string;
    theme?: ThemeMode;
  }) =>
    invoke<AppConfig>("update_translation_quick", {
      sourceLang: params.sourceLang ?? null,
      targetLang: params.targetLang ?? null,
      imageMode: params.imageMode ?? null,
      scene: params.scene ?? null,
      theme: params.theme ?? null,
    }),

  translateText: (
    text: string,
    sourceLang: string,
    targetLang: string,
    scene: string,
    requestId?: string,
    quick?: boolean,
  ) =>
    invoke<TranslateCommandOutput>("translate_text_cmd", {
      text,
      sourceLang,
      targetLang,
      scene,
      requestId: requestId ?? null,
      quick: quick ?? null,
    }),

  translateImage: (
    imageBase64: string,
    mode: ImageMode,
    sourceLang: string,
    targetLang: string,
    scene: string,
  ) =>
    invoke<TranslateCommandOutput>("translate_image_cmd", {
      imageBase64,
      mode,
      sourceLang,
      targetLang,
      scene,
    }),

  extractOcrText: (imageBase64: string) =>
    invoke<string>("extract_ocr_text_cmd", { imageBase64 }),

  readClipboardImage: () => invoke<string>("read_clipboard_image_cmd"),

  copyText: (text: string) => invoke<void>("copy_text_cmd", { text }),

  captureScreenshot: () => invoke<string | null>("capture_screenshot_cmd"),

  getPendingScreenshot: () =>
    invoke<ScreenshotSourcePayload | null>("get_pending_screenshot"),

  completeWindowsScreenshot: (crop: CropRect | null) =>
    invoke<void>("complete_windows_screenshot", { crop }),

  getPendingQuickText: () => invoke<string>("get_pending_quick_text"),

  closeQuickWindow: () => invoke<void>("close_quick_window"),

  openInMainWindow: (sourceText: string, resultText: string) =>
    invoke<void>("open_in_main_window", { sourceText, resultText }),

  toggleFavorite: (params: {
    sourceLang: string;
    targetLang: string;
    mode: string;
    sourceText: string;
    resultText: string;
    model: string;
  }) => invoke<ToggleFavoriteOutput>("toggle_favorite_cmd", params),

  removeFavorite: (id: string) =>
    invoke<AppConfig>("remove_favorite_cmd", { id }),

  exportFavorites: (format: "markdown" | "anki_tsv") =>
    invoke<string>("export_favorites_cmd", { format }),

  fetchProfileModels: (profile: LlmProfile, persistCache: boolean) =>
    invoke<string[]>("fetch_profile_models", { profile, persistCache }),

  testProfileConnection: (profile: LlmProfile) =>
    invoke<string>("test_profile_connection", { profile }),

  testJevConnection: (jev: JevConfig) =>
    invoke<string>("test_jev_connection", { jev }),

  fetchJevModels: (jev: JevConfig) =>
    invoke<string[]>("fetch_jev_models", { jev }),

  synthesizeTts: (text: string, voice: string, rate: number) =>
    invoke<string>("synthesize_tts", { text, voice, rate }),

  parseGlossaryText: (text: string) =>
    invoke<Record<string, string>>("parse_glossary_text", { text }),

  formatGlossaryText: (glossary: Record<string, string>) =>
    invoke<string>("format_glossary_text", { glossary }),

  clearHistory: () => invoke<AppConfig>("clear_history_cmd"),

  saveWindowGeometry: (params: {
    width?: number;
    height?: number;
    maximized?: boolean;
    splitterSizes?: number[];
  }) =>
    invoke<void>("save_window_geometry", {
      width: params.width ?? null,
      height: params.height ?? null,
      maximized: params.maximized ?? null,
      splitterSizes: params.splitterSizes ?? null,
    }),

  quitApp: () => invoke<void>("quit_app"),
};
