import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import {
  ArrowLeftRight,
  Camera,
  Check,
  ClipboardPaste,
  Copy,
  Eraser,
  FileText,
  History,
  ImageIcon,
  Languages,
  Loader2,
  Moon,
  Settings,
  Sparkles,
  Star,
  Sun,
  Volume2,
  X,
} from "lucide-react";
import { FirstRunWizard } from "./components/FirstRunWizard";
import { HistoryDrawer } from "./components/HistoryDrawer";
import { ModelPicker } from "./components/ModelPicker";
import { QuickPopup } from "./components/QuickPopup";
import { ScreenshotOverlay } from "./components/ScreenshotOverlay";
import { SettingsModal, type SettingsTab } from "./components/SettingsModal";
import { matchesShortcut } from "./lib/shortcuts";
import { api } from "./lib/tauri";
import {
  AUTO_SCENE_ID,
  AUTO_SCENE_LABEL,
  EFFORT_SHORT_LABELS,
  newShortId,
  type AppConfig,
  type BootstrapData,
  type ImageMode,
  type LoadInMainPayload,
  type ReasoningEffort,
  type TranslateStreamEvent,
} from "./lib/types";

export function App() {
  const mode =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("mode")
      : null;

  if (mode === "screenshot") {
    return <ScreenshotOverlay />;
  }
  if (mode === "quick") {
    return <QuickPopup />;
  }

  return <MainApp />;
}

function MainApp() {
  const [boot, setBoot] = useState<BootstrapData | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [sourceText, setSourceText] = useState("");
  const [resultText, setResultText] = useState("");
  const [lastResultMode, setLastResultMode] = useState("text");
  const [lastResultModel, setLastResultModel] = useState("");
  const [pendingImageB64, setPendingImageB64] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ttsBusySide, setTtsBusySide] = useState<"source" | "result" | null>(null);
  const [status, setStatus] = useState("就绪");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("llm");
  const [settingsProfileId, setSettingsProfileId] = useState<string | undefined>(undefined);
  const [wizardOpen, setWizardOpen] = useState(false);

  const [leftRatio, setLeftRatio] = useState(50);
  const splitContainerRef = useRef<HTMLDivElement>(null);
  const draggingSplit = useRef(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const activeReqRef = useRef<string>("");

  useEffect(() => {
    if (!config) return;
    document.documentElement.setAttribute("data-theme", config.ui.theme);
  }, [config]);

  useEffect(() => {
    api
      .getBootstrap()
      .then((data) => {
        setBoot(data);
        setConfig(data.config);
        if (data.config.ui.splitter_sizes.length === 2) {
          const [a, b] = data.config.ui.splitter_sizes;
          if (a + b > 0) {
            setLeftRatio(Math.max(25, Math.min(75, Math.round((a / (a + b)) * 100))));
          }
        }
        if (data.previous_version && data.previous_version !== data.version) {
          setStatus(`已更新到 v${data.version}`);
        }
        if (data.needs_setup) {
          setWizardOpen(true);
        }
      })
      .catch((e) => setStatus(`初始化失败：${String(e)}`));
  }, []);

  const activeProfile = useMemo(() => {
    if (!config) return null;
    return (
      config.profiles.find((p) => p.id === config.active_profile_id) ??
      config.profiles[0]
    );
  }, [config]);

  const allScenes = useMemo(() => {
    if (!boot || !config) return [];
    return [
      ...boot.scenes.filter((s) => s.builtin),
      ...config.translation.custom_scenes.map((c) => ({
        id: c.id,
        label: c.label,
        prompt: c.prompt,
        builtin: false,
      })),
    ];
  }, [boot, config]);

  const isCurrentFavorited = useMemo(() => {
    if (!config) return false;
    const src = sourceText.trim();
    const dst = resultText.trim();
    if (!src || !dst) return false;
    return config.favorites.some(
      (f) => f.source_text === src && f.target_lang === config.translation.target_lang,
    );
  }, [config, sourceText, resultText]);

  const stopAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      audioRef.current = null;
    }
  }, []);

  const speakSide = useCallback(
    async (side: "source" | "result", slow: boolean, overrideText?: string) => {
      if (!config || ttsBusySide) return;
      const text = (overrideText ?? (side === "source" ? sourceText : resultText)).trim();
      if (!text) {
        setStatus("没有可朗读的文本");
        return;
      }
      stopAudio();
      const baseRate = config.tts.rate;
      const rate = slow ? Math.max(-50, baseRate - 50) : baseRate;
      setTtsBusySide(side);
      setStatus(slow ? "正在合成慢速语音…" : "正在合成语音…");
      try {
        const dataUrl = await api.synthesizeTts(text, config.tts.voice, rate);
        const audio = new Audio(dataUrl);
        audioRef.current = audio;
        audio.onended = () => {
          setStatus("就绪");
          audioRef.current = null;
        };
        audio.onerror = () => {
          setStatus("语音播放失败");
          audioRef.current = null;
        };
        setStatus(slow ? "慢速朗读中…" : "朗读中…");
        await audio.play();
      } catch (e) {
        setStatus(`朗读失败：${String(e)}`);
      } finally {
        setTtsBusySide(null);
      }
    },
    [config, ttsBusySide, sourceText, resultText, stopAudio],
  );

  const runTranslateText = useCallback(async () => {
    if (!config || busy) return;
    if (pendingImageB64) {
      setBusy(true);
      setStatus(
        config.translation.image_mode === "vision"
          ? "正在调用视觉模型翻译图片…"
          : "正在 OCR 识别并翻译…",
      );
      try {
        const out = await api.translateImage(
          pendingImageB64,
          config.translation.image_mode,
          config.translation.source_lang,
          config.translation.target_lang,
          config.translation.scene,
        );
        setConfig(out.config);
        if (out.result.ocr_text) {
          setSourceText(out.result.ocr_text);
        }
        setResultText(out.result.text);
        setLastResultMode(out.result.mode);
        setLastResultModel(out.result.model);
        const parts = [`完成 · ${out.result.model} (${out.result.mode})`];
        if (out.result.quality_score !== null) {
          parts.push(`评分 ${Math.round(out.result.quality_score * 100)}%`);
        }
        parts.push(...out.result.notes, ...out.result.warnings);
        setStatus(parts.join(" · "));
        if (out.config.tts.auto_pronounce && out.result.text.trim()) {
          void speakSide("result", false, out.result.text);
        }
      } catch (e) {
        setStatus(`翻译失败：${String(e)}`);
      } finally {
        setBusy(false);
      }
      return;
    }

    const cleaned = sourceText.trim();
    if (!cleaned) {
      setStatus("请输入需要翻译的文本或粘贴/截取图片");
      return;
    }
    const reqId = newShortId();
    activeReqRef.current = reqId;
    setBusy(true);
    setResultText("");
    setStatus("正在翻译…");
    try {
      const out = await api.translateText(
        cleaned,
        config.translation.source_lang,
        config.translation.target_lang,
        config.translation.scene,
        reqId,
      );
      setConfig(out.config);
      setResultText(out.result.text);
      setLastResultMode(out.result.mode);
      setLastResultModel(out.result.model);
      const parts = [`完成 · ${out.result.model}`];
      const rawEff =
        activeProfile?.reasoning_effort === "minimal"
          ? "low"
          : activeProfile?.reasoning_effort;
      const eff = rawEff as ReasoningEffort | undefined;
      if (eff) parts.push(`effort: ${EFFORT_SHORT_LABELS[eff] ?? eff}`);
      if (out.result.quality_score !== null) {
        parts.push(`评分 ${Math.round(out.result.quality_score * 100)}%`);
      }
      parts.push(...out.result.notes, ...out.result.warnings);
      setStatus(parts.join(" · "));
      if (out.config.tts.auto_pronounce && out.result.text.trim()) {
        void speakSide("result", false, out.result.text);
      }
    } catch (e) {
      setStatus(`翻译失败：${String(e)}`);
    } finally {
      activeReqRef.current = "";
      setBusy(false);
    }
  }, [config, busy, pendingImageB64, sourceText, activeProfile, speakSide]);

  const translateCapturedImage = useCallback(
    async (b64: string, cfgOverride?: AppConfig) => {
      const curCfg = cfgOverride ?? config;
      if (!curCfg) return;
      setPendingImageB64(b64);
      setBusy(true);
      setStatus(
        curCfg.translation.image_mode === "vision"
          ? "正在视觉翻译图片…"
          : "正在 OCR 识别并翻译…",
      );
      try {
        const out = await api.translateImage(
          b64,
          curCfg.translation.image_mode,
          curCfg.translation.source_lang,
          curCfg.translation.target_lang,
          curCfg.translation.scene,
        );
        setConfig(out.config);
        if (out.result.ocr_text) setSourceText(out.result.ocr_text);
        setResultText(out.result.text);
        setLastResultMode(out.result.mode);
        setLastResultModel(out.result.model);
        const parts = [`完成 · ${out.result.model} (${out.result.mode})`];
        if (out.result.quality_score !== null) {
          parts.push(`评分 ${Math.round(out.result.quality_score * 100)}%`);
        }
        parts.push(...out.result.notes, ...out.result.warnings);
        setStatus(parts.join(" · "));
        if (out.config.tts.auto_pronounce && out.result.text.trim()) {
          void speakSide("result", false, out.result.text);
        }
      } catch (e) {
        setStatus(`图片翻译失败：${String(e)}`);
      } finally {
        setBusy(false);
      }
    },
    [config, speakSide],
  );

  const handleScreenshot = useCallback(async () => {
    if (!config || busy) return;
    setStatus("请选择截图区域…");
    try {
      const b64 = await api.captureScreenshot();
      if (b64) {
        await translateCapturedImage(b64);
      } else if (!boot?.is_windows) {
        setStatus("截图已取消");
      }
    } catch (e) {
      setStatus(`截图失败：${String(e)}`);
    }
  }, [config, busy, boot?.is_windows, translateCapturedImage]);

  const handlePasteImage = useCallback(async () => {
    if (!config || busy) return;
    try {
      const b64 = await api.readClipboardImage();
      await translateCapturedImage(b64);
    } catch (e) {
      setStatus(String(e));
    }
  }, [config, busy, translateCapturedImage]);

  const handleExtractText = useCallback(async () => {
    if (!config || busy) return;
    setBusy(true);
    try {
      let b64 = pendingImageB64;
      if (!b64) {
        setStatus("请选择要提取文字的截图区域…");
        b64 = await api.captureScreenshot();
        if (!b64) {
          setStatus("已取消");
          setBusy(false);
          return;
        }
        setPendingImageB64(b64);
      }
      setStatus("正在 OCR 提取文字…");
      const text = await api.extractOcrText(b64);
      setSourceText(text);
      setStatus("已提取文字并复制到剪贴板");
    } catch (e) {
      setStatus(`提取失败：${String(e)}`);
    } finally {
      setBusy(false);
    }
  }, [config, busy, pendingImageB64]);

  const handleSwapLangs = useCallback(async () => {
    if (!config || config.translation.source_lang === "auto") return;
    const nextSource = config.translation.target_lang;
    const nextTarget = config.translation.source_lang;
    const updated = await api.updateTranslationQuick({
      sourceLang: nextSource,
      targetLang: nextTarget,
    });
    setConfig(updated);
    if (resultText.trim()) {
      setSourceText(resultText);
      setResultText("");
      setPendingImageB64(null);
    }
  }, [config, resultText]);

  const handleCopyResult = useCallback(async () => {
    if (!resultText.trim()) return;
    await api.copyText(resultText);
    setStatus("已复制译文到剪贴板");
  }, [resultText]);

  useEffect(() => {
    if (!config) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "q") {
        e.preventDefault();
        void api.quitApp();
        return;
      }
      if (settingsOpen || wizardOpen) return;
      const hk = config.ui.hotkeys;
      if (matchesShortcut(e, hk.translate)) {
        e.preventDefault();
        void runTranslateText();
      } else if (matchesShortcut(e, hk.screenshot)) {
        e.preventDefault();
        void handleScreenshot();
      } else if (matchesShortcut(e, hk.extract_text)) {
        e.preventDefault();
        void handleExtractText();
      } else if (matchesShortcut(e, hk.paste_image)) {
        e.preventDefault();
        void handlePasteImage();
      } else if (matchesShortcut(e, hk.swap_langs)) {
        e.preventDefault();
        void handleSwapLangs();
      } else if (matchesShortcut(e, hk.copy_result)) {
        e.preventDefault();
        void handleCopyResult();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    config,
    settingsOpen,
    wizardOpen,
    runTranslateText,
    handleScreenshot,
    handleExtractText,
    handlePasteImage,
    handleSwapLangs,
    handleCopyResult,
  ]);

  useEffect(() => {
    const unlistenPromises = [
      listen<TranslateStreamEvent>("translate-stream", (event) => {
        if (!activeReqRef.current || event.payload.request_id !== activeReqRef.current) {
          return;
        }
        if (event.payload.reset) {
          setResultText("");
        } else if (event.payload.delta) {
          setResultText((prev) => prev + event.payload.delta);
        }
      }),
      listen<AppConfig>("config-updated", (event) => {
        setConfig(event.payload);
      }),
      listen<LoadInMainPayload>("load-in-main", (event) => {
        setPendingImageB64(null);
        setSourceText(event.payload.source_text);
        setResultText(event.payload.result_text);
        setStatus("已从划词小窗载入");
      }),
      listen<string>("tray-action", (event) => {
        if (event.payload === "screenshot") void handleScreenshot();
        else if (event.payload === "extract") void handleExtractText();
        else if (event.payload === "paste_image") void handlePasteImage();
      }),
      listen<string | null>("screenshot-result", (event) => {
        if (event.payload) {
          void translateCapturedImage(event.payload);
        } else {
          setStatus("截图已取消");
        }
      }),
      listen<string>("status-toast", (event) => {
        setStatus(event.payload);
      }),
    ];
    return () => {
      for (const p of unlistenPromises) {
        p.then((fn) => fn()).catch(() => {});
      }
    };
  }, [handleScreenshot, handleExtractText, handlePasteImage, translateCapturedImage]);

  useEffect(() => {
    const win = getCurrentWindow();
    let timer: number | undefined;
    const unlisten = win.onResized(() => {
      window.clearTimeout(timer);
      timer = window.setTimeout(async () => {
        try {
          const maximized = await win.isMaximized();
          const size = await win.innerSize();
          await api.saveWindowGeometry({
            width: size.width,
            height: size.height,
            maximized,
          });
        } catch {
          // ignore
        }
      }, 400);
    });
    return () => {
      window.clearTimeout(timer);
      unlisten.then((fn) => fn()).catch(() => {});
    };
  }, []);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingSplit.current || !splitContainerRef.current) return;
      const rect = splitContainerRef.current.getBoundingClientRect();
      if (rect.width <= 0) return;
      const pct = ((e.clientX - rect.left) / rect.width) * 100;
      setLeftRatio(Math.max(25, Math.min(75, pct)));
    };
    const onUp = () => {
      if (!draggingSplit.current) return;
      draggingSplit.current = false;
      const a = Math.round(leftRatio * 10);
      const b = Math.round((100 - leftRatio) * 10);
      void api.saveWindowGeometry({ splitterSizes: [a, b] });
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [leftRatio]);

  if (!boot || !config || !activeProfile) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-[var(--md-sys-color-on-surface-variant)]">
        <Loader2 size={20} className="mr-2.5 animate-spin text-[var(--md-sys-color-primary)]" />
        <span>正在加载 AI Translator…</span>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col bg-[var(--md-sys-color-background)] text-[var(--md-sys-color-on-surface)]">
      {/* Material 3 Top App Bar */}
      <header className="flex flex-wrap items-center gap-3 bg-[var(--md-sys-color-surface-container)] px-4 py-3">
        <div className="flex items-center gap-2.5 pr-1">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[var(--md-sys-color-primary-container)] text-[var(--md-sys-color-on-primary-container)]">
            <Languages size={19} />
          </div>
          <span className="text-[17px] font-medium tracking-tight text-[var(--md-sys-color-on-surface)]">
            AI Translator
          </span>
        </div>

        <select
          disabled={busy}
          value={activeProfile.id}
          onChange={async (e) => {
            const next = await api.setActiveProfile(e.target.value);
            setConfig(next);
          }}
          title="当前服务商配置"
          className="h-9 max-w-[180px] rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] px-3.5 text-sm outline-none focus:border-[var(--md-sys-color-primary)] disabled:opacity-50"
        >
          {config.profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>

        {/* M3 Segmented Button (OCR / Vision) */}
        <div className="inline-flex h-9 overflow-hidden rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)]">
          {(["ocr", "vision"] as ImageMode[]).map((m, idx) => {
            const active = config.translation.image_mode === m;
            return (
              <button
                key={m}
                type="button"
                disabled={busy}
                onClick={async () => {
                  const next = await api.updateTranslationQuick({ imageMode: m });
                  setConfig(next);
                }}
                className={`m3-state flex items-center gap-1.5 px-3.5 text-sm font-medium uppercase ${
                  idx > 0 ? "border-l border-[var(--md-sys-color-outline-variant)]" : ""
                } ${
                  active
                    ? "bg-[var(--md-sys-color-secondary-container)] text-[var(--md-sys-color-on-secondary-container)]"
                    : "text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-high)]"
                }`}
              >
                {active && <Check size={14} />}
                <span>{m}</span>
              </button>
            );
          })}
        </div>

        <select
          disabled={busy}
          value={config.translation.scene}
          onChange={async (e) => {
            const next = await api.updateTranslationQuick({ scene: e.target.value });
            setConfig(next);
          }}
          title="翻译场景"
          className="h-9 rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] px-3.5 text-sm outline-none focus:border-[var(--md-sys-color-primary)] disabled:opacity-50"
        >
          <option value={AUTO_SCENE_ID}>{AUTO_SCENE_LABEL}</option>
          {allScenes.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>

        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={async () => {
              const nextTheme = config.ui.theme === "dark" ? "light" : "dark";
              const next = await api.updateTranslationQuick({ theme: nextTheme });
              setConfig(next);
            }}
            className="m3-state flex h-9 w-9 items-center justify-center rounded-full bg-[var(--md-sys-color-surface-container-high)] text-[var(--md-sys-color-on-surface-variant)] hover:text-[var(--md-sys-color-on-surface)]"
            title="切换深/浅色主题"
          >
            {config.ui.theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>

          <button
            type="button"
            onClick={() => setHistoryOpen(true)}
            className="m3-state flex h-9 items-center gap-1.5 rounded-full bg-[var(--md-sys-color-surface-container-high)] px-4 text-sm font-medium hover:bg-[var(--md-sys-color-surface-container-highest)]"
          >
            <History size={16} />
            <span>历史 / 生词本</span>
          </button>

          <button
            type="button"
            onClick={() => {
              setSettingsTab("llm");
              setSettingsProfileId(undefined);
              setSettingsOpen(true);
            }}
            className="m3-state flex h-9 items-center gap-1.5 rounded-full bg-[var(--md-sys-color-surface-container-high)] px-4 text-sm font-medium hover:bg-[var(--md-sys-color-surface-container-highest)]"
          >
            <Settings size={16} />
            <span>设置</span>
          </button>
        </div>
      </header>

      {/* Language + Action Chips Bar */}
      <div className="flex flex-wrap items-center gap-2.5 px-4 pt-3 pb-2">
        <select
          disabled={busy}
          value={config.translation.source_lang}
          onChange={async (e) => {
            const next = await api.updateTranslationQuick({
              sourceLang: e.target.value,
            });
            setConfig(next);
          }}
          className="h-10 rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)] px-4 text-sm font-medium outline-none focus:border-[var(--md-sys-color-primary)]"
        >
          {boot.source_languages.map((l) => (
            <option key={l.code} value={l.code}>
              {l.label}
            </option>
          ))}
        </select>

        <button
          type="button"
          disabled={busy || config.translation.source_lang === "auto"}
          onClick={handleSwapLangs}
          title="交换源语言与目标语言"
          className="m3-state flex h-10 w-10 items-center justify-center rounded-full bg-[var(--md-sys-color-secondary-container)] text-[var(--md-sys-color-on-secondary-container)] hover:brightness-105 disabled:opacity-40"
        >
          <ArrowLeftRight size={17} />
        </button>

        <select
          disabled={busy}
          value={config.translation.target_lang}
          onChange={async (e) => {
            const next = await api.updateTranslationQuick({
              targetLang: e.target.value,
            });
            setConfig(next);
          }}
          className="h-10 rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)] px-4 text-sm font-medium outline-none focus:border-[var(--md-sys-color-primary)]"
        >
          {boot.target_languages.map((l) => (
            <option key={l.code} value={l.code}>
              {l.label}
            </option>
          ))}
        </select>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={handleScreenshot}
            title={`截图翻译 (${config.ui.hotkeys.screenshot})`}
            className="m3-state flex h-10 items-center gap-2 rounded-full bg-[var(--md-sys-color-secondary-container)] px-4 text-sm font-medium text-[var(--md-sys-color-on-secondary-container)] hover:brightness-105 disabled:opacity-50"
          >
            <Camera size={17} />
            <span>截图翻译</span>
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={handleExtractText}
            title={`OCR 提取文字 (${config.ui.hotkeys.extract_text})`}
            className="m3-state flex h-10 items-center gap-2 rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)] px-4 text-sm font-medium hover:bg-[var(--md-sys-color-surface-container-high)] disabled:opacity-50"
          >
            <FileText size={17} />
            <span>提取文字</span>
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={handlePasteImage}
            title={`粘贴图片翻译 (${config.ui.hotkeys.paste_image})`}
            className="m3-state flex h-10 items-center gap-2 rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)] px-4 text-sm font-medium hover:bg-[var(--md-sys-color-surface-container-high)] disabled:opacity-50"
          >
            <ClipboardPaste size={17} />
            <span>粘贴图片</span>
          </button>
        </div>
      </div>

      {/* Material 3 Dual Surface Cards */}
      <main
        ref={splitContainerRef}
        className="flex min-h-0 flex-1 gap-0 px-4 py-1.5"
      >
        {/* Source Card */}
        <section
          style={{ width: `${leftRatio}%` }}
          className="flex min-w-[220px] flex-col overflow-hidden rounded-[24px] border border-[var(--md-sys-color-outline-variant)]/55 bg-[var(--md-sys-color-surface-container-low)]"
        >
          <div className="flex items-center justify-between border-b border-[var(--md-sys-color-outline-variant)]/40 px-4 py-2.5">
            <span className="text-sm font-medium text-[var(--md-sys-color-on-surface-variant)]">
              原文
            </span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                disabled={ttsBusySide !== null}
                onClick={() => void speakSide("source", false)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  void speakSide("source", true);
                }}
                title="左键正常朗读 / 右键慢速跟读 (-50%)"
                className="m3-state flex h-9 w-9 items-center justify-center rounded-full text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-high)] hover:text-[var(--md-sys-color-primary)] disabled:opacity-40"
              >
                {ttsBusySide === "source" ? (
                  <Loader2 size={17} className="animate-spin" />
                ) : (
                  <Volume2 size={17} />
                )}
              </button>
              <button
                type="button"
                onClick={() => {
                  setSourceText("");
                  setPendingImageB64(null);
                }}
                title="清空原文与待翻译图片"
                className="m3-state flex h-9 w-9 items-center justify-center rounded-full text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-error-container)]/40 hover:text-[var(--md-sys-color-error)]"
              >
                <Eraser size={17} />
              </button>
            </div>
          </div>

          {pendingImageB64 && (
            <div className="flex items-center justify-between border-b border-[var(--md-sys-color-outline-variant)]/40 bg-[var(--md-sys-color-surface-container)] px-4 py-2">
              <div className="flex items-center gap-2 text-sm text-[var(--md-sys-color-primary)]">
                <ImageIcon size={16} />
                <span>已附带截图 / 图片（{config.translation.image_mode.toUpperCase()} 模式）</span>
              </div>
              <div className="flex items-center gap-2">
                <img
                  src={`data:image/png;base64,${pendingImageB64}`}
                  alt="preview"
                  className="h-9 max-w-[100px] rounded-lg border border-[var(--md-sys-color-outline-variant)] object-contain"
                />
                <button
                  type="button"
                  onClick={() => setPendingImageB64(null)}
                  className="flex h-7 w-7 items-center justify-center rounded-full hover:bg-[var(--md-sys-color-error-container)]/40 hover:text-[var(--md-sys-color-error)]"
                  title="移除图片"
                >
                  <X size={15} />
                </button>
              </div>
            </div>
          )}

          <textarea
            value={sourceText}
            onChange={(e) => setSourceText(e.target.value)}
            placeholder={`输入要翻译的文本（${config.ui.hotkeys.translate} 翻译），或使用截图 / 粘贴图片…`}
            className="font-mono-editor min-h-0 flex-1 resize-none bg-transparent p-4 text-[15px] leading-[1.65] text-[var(--md-sys-color-on-surface)] outline-none placeholder:text-[var(--md-sys-color-outline)]"
          />
        </section>

        {/* Splitter handle */}
        <div
          onMouseDown={() => {
            draggingSplit.current = true;
          }}
          className="mx-1.5 w-1.5 shrink-0 cursor-col-resize rounded-full transition hover:bg-[var(--md-sys-color-primary)]/70"
        />

        {/* Result Card */}
        <section
          style={{ width: `${100 - leftRatio}%` }}
          className="flex min-w-[220px] flex-col overflow-hidden rounded-[24px] border border-[var(--md-sys-color-outline-variant)]/55 bg-[var(--md-sys-color-surface-container-low)]"
        >
          <div className="flex items-center justify-between border-b border-[var(--md-sys-color-outline-variant)]/40 px-4 py-2.5">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-[var(--md-sys-color-on-surface-variant)]">
                译文
              </span>
              {lastResultMode === "dict" && resultText.trim() && (
                <span className="rounded-full bg-[var(--md-sys-color-tertiary-container)] px-2 py-0.5 text-[11px] font-medium text-[var(--md-sys-color-on-tertiary-container)]">
                  词典
                </span>
              )}
            </div>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                disabled={!sourceText.trim() || !resultText.trim()}
                onClick={async () => {
                  const res = await api.toggleFavorite({
                    sourceLang: config.translation.source_lang,
                    targetLang: config.translation.target_lang,
                    mode: lastResultMode,
                    sourceText,
                    resultText,
                    model: lastResultModel,
                  });
                  setConfig(res.config);
                  setStatus(res.favorited ? "已收藏到生词本" : "已从生词本移除");
                }}
                title={isCurrentFavorited ? "从生词本移除" : "收藏到生词本"}
                className={`m3-state flex h-9 w-9 items-center justify-center rounded-full disabled:opacity-40 ${
                  isCurrentFavorited
                    ? "text-[var(--md-sys-color-warning)]"
                    : "text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-high)]"
                }`}
              >
                <Star size={17} fill={isCurrentFavorited ? "currentColor" : "none"} />
              </button>
              <button
                type="button"
                disabled={ttsBusySide !== null}
                onClick={() => void speakSide("result", false)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  void speakSide("result", true);
                }}
                title="左键正常朗读 / 右键慢速跟读 (-50%)"
                className="m3-state flex h-9 w-9 items-center justify-center rounded-full text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-high)] hover:text-[var(--md-sys-color-primary)] disabled:opacity-40"
              >
                {ttsBusySide === "result" ? (
                  <Loader2 size={17} className="animate-spin" />
                ) : (
                  <Volume2 size={17} />
                )}
              </button>
              <button
                type="button"
                onClick={() => void handleCopyResult()}
                title={`复制译文 (${config.ui.hotkeys.copy_result})`}
                className="m3-state flex h-9 items-center gap-1.5 rounded-full bg-[var(--md-sys-color-surface-container-high)] px-3.5 text-sm font-medium text-[var(--md-sys-color-on-surface)] hover:bg-[var(--md-sys-color-surface-container-highest)]"
              >
                <Copy size={15} />
                <span>复制</span>
              </button>
            </div>
          </div>

          <textarea
            readOnly
            value={resultText}
            placeholder="译文将显示在此处…"
            className="font-mono-editor min-h-0 flex-1 resize-none bg-transparent p-4 text-[15px] leading-[1.65] text-[var(--md-sys-color-on-surface)] outline-none placeholder:text-[var(--md-sys-color-outline)]"
          />
        </section>
      </main>

      {/* Bottom Action Bar */}
      <div className="grid grid-cols-3 items-center px-4 py-3">
        <div className="text-sm text-[var(--md-sys-color-on-surface-variant)]">
          {sourceText.trim() ? `${sourceText.trim().length} 字` : ""}
        </div>

        <div className="flex justify-center">
          <ModelPicker
            profiles={config.profiles}
            activeProfile={activeProfile}
            disabled={busy}
            onSelectProvider={async (pid) => {
              const next = await api.setActiveProfile(pid);
              setConfig(next);
              const prof = next.profiles.find((p) => p.id === pid);
              if (prof) {
                setStatus(
                  prof.models.length === 0
                    ? `已切换到 ${prof.name}（暂无候选模型，请点「管理候选模型…」添加）`
                    : `已切换服务商：${prof.name} · ${prof.model}`,
                );
              }
            }}
            onSelectModel={async (pid, model) => {
              const prevVision = activeProfile.vision_model;
              const next = await api.updateProfileSelection(pid, model);
              setConfig(next);
              setStatus(
                prevVision
                  ? `已切换模型：${model}（图片翻译仍用 ${prevVision}）`
                  : `已切换模型：${model}`,
              );
            }}
            onChangeEffort={async (pid, effort) => {
              const next = await api.updateProfileSelection(pid, undefined, effort);
              setConfig(next);
            }}
            onOpenSettingsForProfile={(pid) => {
              setSettingsTab("llm");
              setSettingsProfileId(pid);
              setSettingsOpen(true);
            }}
          />
        </div>

        <div className="flex justify-end">
          <button
            type="button"
            disabled={busy}
            onClick={() => void runTranslateText()}
            className="m3-state flex h-11 items-center gap-2 rounded-[16px] bg-[var(--md-sys-color-primary)] px-6 text-[15px] font-medium text-[var(--md-sys-color-on-primary)] hover:brightness-105 disabled:opacity-60"
            style={{ boxShadow: "var(--md-elevation-2)" }}
          >
            {busy ? (
              <Loader2 size={18} className="animate-spin" />
            ) : (
              <Sparkles size={18} />
            )}
            <span>{busy ? "翻译中…" : "翻译"}</span>
          </button>
        </div>
      </div>

      {/* Status Bar */}
      <footer
        className="truncate border-t border-[var(--md-sys-color-outline-variant)]/50 bg-[var(--md-sys-color-surface-container)] px-4 py-1.5 text-[13px] text-[var(--md-sys-color-on-surface-variant)]"
        title={status}
      >
        {status}
      </footer>

      <HistoryDrawer
        open={historyOpen}
        entries={config.history}
        favorites={config.favorites}
        targetLang={config.translation.target_lang}
        onClose={() => setHistoryOpen(false)}
        onSelectEntry={(entry) => {
          setPendingImageB64(null);
          setSourceText(entry.source_text);
          setResultText(entry.result_text);
          setLastResultMode(entry.mode);
          setLastResultModel(entry.model);
          setStatus(`已载入记录（${entry.model || entry.mode}）`);
        }}
        onCopyResult={async (entry) => {
          await api.copyText(entry.result_text);
          setStatus("已复制译文到剪贴板");
        }}
        onToggleFavorite={async (entry) => {
          const res = await api.toggleFavorite({
            sourceLang: entry.source_lang,
            targetLang: entry.target_lang,
            mode: entry.mode,
            sourceText: entry.source_text,
            resultText: entry.result_text,
            model: entry.model,
          });
          setConfig(res.config);
          setStatus(res.favorited ? "已收藏到生词本" : "已从生词本移除");
        }}
        onRemoveFavorite={async (id) => {
          const next = await api.removeFavorite(id);
          setConfig(next);
          setStatus("已移出生词本");
        }}
        onSpeakText={(text) => {
          void speakSide("source", false, text);
        }}
        onExportFavorites={async (format) => {
          const content = await api.exportFavorites(format);
          const ext = format === "anki_tsv" ? "tsv" : "md";
          const mime = format === "anki_tsv" ? "text/tab-separated-values" : "text/markdown";
          const blob = new Blob([content], { type: mime });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `ai-translator-favorites.${ext}`;
          a.click();
          URL.revokeObjectURL(url);
          setStatus(`已导出 ${format === "anki_tsv" ? "Anki TSV" : "Markdown"}`);
        }}
        onClearAll={async () => {
          const next = await api.clearHistory();
          setConfig(next);
          setStatus("已清空历史记录");
        }}
      />

      <SettingsModal
        open={settingsOpen}
        initialTab={settingsTab}
        initialProfileId={settingsProfileId}
        config={config}
        templates={boot.provider_templates}
        targetLanguages={boot.target_languages}
        builtinScenes={boot.scenes.filter((s) => s.builtin)}
        ttsVoices={boot.tts_voices}
        isWindows={boot.is_windows}
        onClose={() => setSettingsOpen(false)}
        onSave={async (nextCfg) => {
          const saved = await api.saveConfig(nextCfg);
          setConfig(saved);
          setStatus("设置已保存");
        }}
      />

      <FirstRunWizard
        open={wizardOpen}
        templates={boot.provider_templates}
        config={config}
        onComplete={async (nextCfg) => {
          const saved = await api.saveConfig(nextCfg);
          setConfig(saved);
          setWizardOpen(false);
          setStatus("已完成初始配置");
        }}
        onSkip={() => setWizardOpen(false)}
      />
    </div>
  );
}
