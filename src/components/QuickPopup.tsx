import { useCallback, useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import {
  Copy,
  ExternalLink,
  Languages,
  Loader2,
  Send,
  Star,
  Volume2,
  X,
} from "lucide-react";
import { api } from "../lib/tauri";
import {
  newShortId,
  type AppConfig,
  type TranslateStreamEvent,
} from "../lib/types";

export function QuickPopup() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [sourceText, setSourceText] = useState("");
  const [resultText, setResultText] = useState("");
  const [modeLabel, setModeLabel] = useState("text");
  const [modelName, setModelName] = useState("");
  const [busy, setBusy] = useState(false);
  const [ttsBusy, setTtsBusy] = useState(false);
  const [status, setStatus] = useState("就绪");
  const activeReqRef = useRef<string>("");

  const runQuickTranslate = useCallback(
    async (text: string, cfgOverride?: AppConfig) => {
      const cfg = cfgOverride ?? config;
      const cleaned = text.trim();
      if (!cfg || !cleaned) return;
      const reqId = newShortId();
      activeReqRef.current = reqId;
      setBusy(true);
      setResultText("");
      setStatus("翻译中…");
      try {
        const out = await api.translateText(
          cleaned,
          cfg.translation.source_lang,
          cfg.translation.target_lang,
          cfg.translation.scene,
          reqId,
        );
        if (activeReqRef.current === reqId) {
          setConfig(out.config);
          setResultText(out.result.text);
          setModeLabel(out.result.mode);
          setModelName(out.result.model);
          setStatus(
            out.result.mode === "dict"
              ? `词典 · ${out.result.model}`
              : `完成 · ${out.result.model}`,
          );
        }
      } catch (e) {
        if (activeReqRef.current === reqId) {
          setStatus(`失败：${String(e)}`);
        }
      } finally {
        if (activeReqRef.current === reqId) {
          setBusy(false);
        }
      }
    },
    [config],
  );

  useEffect(() => {
    Promise.all([api.getBootstrap(), api.getPendingQuickText()])
      .then(([boot, initialText]) => {
        setConfig(boot.config);
        document.documentElement.setAttribute("data-theme", boot.config.ui.theme);
        if (initialText.trim()) {
          setSourceText(initialText);
          void runQuickTranslate(initialText, boot.config);
        }
      })
      .catch((e) => setStatus(String(e)));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const unlisteners = [
      listen<string>("quick-payload", (ev) => {
        const next = (ev.payload || "").trim();
        setSourceText(next);
        if (next) {
          void runQuickTranslate(next);
        } else {
          setResultText("");
          setStatus("输入文本后按 Enter 翻译");
        }
      }),
      listen<TranslateStreamEvent>("translate-stream", (ev) => {
        if (ev.payload.request_id !== activeReqRef.current) return;
        if (ev.payload.reset) {
          setResultText("");
        } else if (ev.payload.delta) {
          setResultText((prev) => prev + ev.payload.delta);
        }
      }),
      listen<AppConfig>("config-updated", (ev) => {
        setConfig(ev.payload);
        document.documentElement.setAttribute("data-theme", ev.payload.ui.theme);
      }),
    ];
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        void api.closeQuickWindow();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      for (const p of unlisteners) {
        p.then((fn) => fn()).catch(() => {});
      }
    };
  }, [runQuickTranslate]);

  const isFavorited = Boolean(
    config &&
      sourceText.trim() &&
      resultText.trim() &&
      config.favorites.some(
        (f) =>
          f.source_text === sourceText.trim() &&
          f.target_lang === config.translation.target_lang,
      ),
  );

  const handleSpeak = async () => {
    if (!config || ttsBusy || !resultText.trim()) return;
    setTtsBusy(true);
    try {
      const dataUrl = await api.synthesizeTts(
        resultText,
        config.tts.voice,
        config.tts.rate,
      );
      const audio = new Audio(dataUrl);
      await audio.play();
    } catch (e) {
      setStatus(`朗读失败：${String(e)}`);
    } finally {
      setTtsBusy(false);
    }
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden rounded-[22px] border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)] text-[var(--md-sys-color-on-surface)]">
      {/* Draggable Title Bar */}
      <div
        data-tauri-drag-region
        className="flex items-center justify-between border-b border-[var(--md-sys-color-outline-variant)]/60 bg-[var(--md-sys-color-surface-container)] px-3.5 py-2.5"
      >
        <div data-tauri-drag-region className="flex items-center gap-2">
          <Languages size={16} className="text-[var(--md-sys-color-primary)]" />
          <span data-tauri-drag-region className="text-sm font-medium">
            快速翻译
          </span>
          {modeLabel === "dict" && (
            <span className="rounded-full bg-[var(--md-sys-color-tertiary-container)] px-2 py-0.5 text-[11px] font-medium text-[var(--md-sys-color-on-tertiary-container)]">
              词典
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => void api.openInMainWindow(sourceText, resultText)}
            title="在主窗口打开"
            className="m3-state flex h-8 items-center gap-1 rounded-full px-2.5 text-xs text-[var(--md-sys-color-primary)] hover:bg-[var(--md-sys-color-primary)]/12"
          >
            <ExternalLink size={14} />
            <span>主窗口</span>
          </button>
          <button
            type="button"
            onClick={() => void api.closeQuickWindow()}
            title="关闭 (Esc)"
            className="m3-state flex h-8 w-8 items-center justify-center rounded-full text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-highest)]"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Source Input */}
      <div className="border-b border-[var(--md-sys-color-outline-variant)]/50 p-3">
        <div className="flex gap-2">
          <textarea
            rows={2}
            value={sourceText}
            onChange={(e) => setSourceText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void runQuickTranslate(sourceText);
              }
            }}
            placeholder="选中文本或输入后按 Enter 翻译…"
            className="font-mono-editor min-h-[54px] flex-1 resize-none rounded-2xl border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] p-2.5 text-sm outline-none focus:border-[var(--md-sys-color-primary)]"
          />
          <button
            type="button"
            disabled={busy || !sourceText.trim()}
            onClick={() => void runQuickTranslate(sourceText)}
            className="m3-state flex h-auto items-center justify-center rounded-2xl bg-[var(--md-sys-color-primary)] px-3.5 text-[var(--md-sys-color-on-primary)] disabled:opacity-50"
            title="翻译 (Enter)"
          >
            {busy ? <Loader2 size={17} className="animate-spin" /> : <Send size={17} />}
          </button>
        </div>
      </div>

      {/* Streaming Result */}
      <div className="min-h-0 flex-1 overflow-y-auto p-3.5">
        <div className="selectable font-mono-editor whitespace-pre-wrap text-[14.5px] leading-relaxed text-[var(--md-sys-color-on-surface)]">
          {resultText || (
            <span className="text-[var(--md-sys-color-outline)]">
              {busy ? "正在生成译文…" : "译文将显示在此处…"}
            </span>
          )}
        </div>
      </div>

      {/* Bottom Bar */}
      <div className="flex items-center justify-between border-t border-[var(--md-sys-color-outline-variant)]/50 bg-[var(--md-sys-color-surface-container)] px-3.5 py-2">
        <span className="truncate text-xs text-[var(--md-sys-color-on-surface-variant)]">
          {status}
        </span>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            disabled={!config || !sourceText.trim() || !resultText.trim()}
            onClick={async () => {
              if (!config) return;
              const res = await api.toggleFavorite({
                sourceLang: config.translation.source_lang,
                targetLang: config.translation.target_lang,
                mode: modeLabel,
                sourceText,
                resultText,
                model: modelName,
              });
              setConfig(res.config);
              setStatus(res.favorited ? "已收藏到生词本" : "已取消收藏");
            }}
            title={isFavorited ? "从生词本移除" : "收藏到生词本"}
            className={`m3-state flex h-8 w-8 items-center justify-center rounded-full ${
              isFavorited
                ? "text-[var(--md-sys-color-warning)]"
                : "text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-highest)]"
            }`}
          >
            <Star size={16} fill={isFavorited ? "currentColor" : "none"} />
          </button>
          <button
            type="button"
            disabled={ttsBusy || !resultText.trim()}
            onClick={() => void handleSpeak()}
            title="朗读译文"
            className="m3-state flex h-8 w-8 items-center justify-center rounded-full text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-highest)] disabled:opacity-40"
          >
            {ttsBusy ? <Loader2 size={15} className="animate-spin" /> : <Volume2 size={16} />}
          </button>
          <button
            type="button"
            disabled={!resultText.trim()}
            onClick={async () => {
              await api.copyText(resultText);
              setStatus("已复制译文");
            }}
            className="m3-state flex h-8 items-center gap-1 rounded-full bg-[var(--md-sys-color-secondary-container)] px-3 text-xs font-medium text-[var(--md-sys-color-on-secondary-container)] disabled:opacity-40"
          >
            <Copy size={13} />
            <span>复制</span>
          </button>
        </div>
      </div>
    </div>
  );
}
