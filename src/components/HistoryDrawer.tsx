import { useMemo, useState } from "react";
import { Copy, Download, Search, Star, Trash2, Volume2, X } from "lucide-react";
import type { FavoriteEntry, HistoryEntry } from "../lib/types";

interface HistoryDrawerProps {
  open: boolean;
  entries: HistoryEntry[];
  favorites: FavoriteEntry[];
  targetLang: string;
  onClose: () => void;
  onSelectEntry: (entry: HistoryEntry) => void;
  onCopyResult: (entry: HistoryEntry) => void;
  onToggleFavorite: (entry: HistoryEntry) => void;
  onRemoveFavorite: (id: string) => void;
  onSpeakText: (text: string) => void;
  onExportFavorites: (format: "markdown" | "anki_tsv") => void;
  onClearAll: () => void;
}

function formatTs(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function HistoryDrawer({
  open,
  entries,
  favorites,
  targetLang,
  onClose,
  onSelectEntry,
  onCopyResult,
  onToggleFavorite,
  onRemoveFavorite,
  onSpeakText,
  onExportFavorites,
  onClearAll,
}: HistoryDrawerProps) {
  const [tab, setTab] = useState<"history" | "favorites">("history");
  const [query, setQuery] = useState("");

  const activeList = tab === "history" ? entries : favorites;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return activeList;
    return activeList.filter(
      (e) =>
        e.source_text.toLowerCase().includes(q) ||
        e.result_text.toLowerCase().includes(q),
    );
  }, [activeList, query]);

  if (!open) return null;

  const isStarred = (entry: HistoryEntry) =>
    favorites.some(
      (f) => f.source_text === entry.source_text && f.target_lang === (entry.target_lang || targetLang),
    );

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/40"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="flex h-full w-[460px] max-w-[94vw] flex-col rounded-l-[28px] border-l border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)]"
        style={{ boxShadow: "var(--md-elevation-3)" }}
      >
        <div className="flex items-center justify-between border-b border-[var(--md-sys-color-outline-variant)]/70 px-5 py-3.5">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setTab("history")}
              className={`m3-state flex h-9 items-center gap-1.5 rounded-full px-3.5 text-sm font-medium ${
                tab === "history"
                  ? "bg-[var(--md-sys-color-secondary-container)] text-[var(--md-sys-color-on-secondary-container)]"
                  : "text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-high)]"
              }`}
            >
              <span>历史</span>
              <span className="text-xs opacity-80">{entries.length}</span>
            </button>
            <button
              type="button"
              onClick={() => setTab("favorites")}
              className={`m3-state flex h-9 items-center gap-1.5 rounded-full px-3.5 text-sm font-medium ${
                tab === "favorites"
                  ? "bg-[var(--md-sys-color-secondary-container)] text-[var(--md-sys-color-on-secondary-container)]"
                  : "text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-high)]"
              }`}
            >
              <Star size={14} />
              <span>生词本</span>
              <span className="text-xs opacity-80">{favorites.length}</span>
            </button>
          </div>

          <div className="flex items-center gap-1">
            {tab === "history" && entries.length > 0 && (
              <button
                type="button"
                onClick={onClearAll}
                className="m3-state flex h-9 items-center gap-1 rounded-full px-3 text-sm font-medium text-[var(--md-sys-color-error)] hover:bg-[var(--md-sys-color-error-container)]/40"
                title="清空所有历史记录"
              >
                <Trash2 size={15} />
                <span>清空</span>
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="m3-state flex h-9 w-9 items-center justify-center rounded-full text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-highest)]"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="space-y-2.5 p-4 pb-2">
          <div className="relative">
            <Search
              size={18}
              className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-[var(--md-sys-color-on-surface-variant)]"
            />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={tab === "history" ? "搜索原文或译文…" : "搜索生词或释义…"}
              className="h-11 w-full rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] pr-4 pl-10 text-sm text-[var(--md-sys-color-on-surface)] outline-none focus:border-[var(--md-sys-color-primary)]"
            />
          </div>

          {tab === "favorites" && favorites.length > 0 && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onExportFavorites("markdown")}
                className="m3-state flex h-8 flex-1 items-center justify-center gap-1.5 rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container)] text-xs font-medium hover:bg-[var(--md-sys-color-surface-container-high)]"
              >
                <Download size={13} />
                <span>导出 Markdown</span>
              </button>
              <button
                type="button"
                onClick={() => onExportFavorites("anki_tsv")}
                className="m3-state flex h-8 flex-1 items-center justify-center gap-1.5 rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container)] text-xs font-medium hover:bg-[var(--md-sys-color-surface-container-high)]"
              >
                <Download size={13} />
                <span>导出 Anki TSV</span>
              </button>
            </div>
          )}
        </div>

        <div className="flex-1 space-y-2.5 overflow-y-auto p-4 pt-2">
          {filtered.length === 0 ? (
            <div className="py-16 text-center text-sm text-[var(--md-sys-color-on-surface-variant)]">
              {activeList.length === 0
                ? tab === "history"
                  ? "暂无翻译历史"
                  : "生词本为空，点击译文卡片或历史记录上的 ★ 即可收藏"
                : "无匹配记录"}
            </div>
          ) : (
            filtered.map((entry) => {
              const starred = tab === "favorites" || isStarred(entry);
              return (
                <div
                  key={entry.id}
                  onClick={() => {
                    onSelectEntry(entry);
                    onClose();
                  }}
                  className="m3-state cursor-pointer rounded-[20px] border border-[var(--md-sys-color-outline-variant)]/60 bg-[var(--md-sys-color-surface-container)] p-3.5 hover:border-[var(--md-sys-color-primary)] hover:bg-[var(--md-sys-color-surface-container-high)]"
                >
                  <div className="mb-2 flex items-center justify-between gap-2 text-xs text-[var(--md-sys-color-on-surface-variant)]">
                    <div className="flex items-center gap-2 truncate">
                      <span className="rounded-full bg-[var(--md-sys-color-tertiary-container)] px-2 py-0.5 text-[11px] font-medium uppercase text-[var(--md-sys-color-on-tertiary-container)]">
                        {entry.mode === "dict" ? "词典" : entry.mode}
                      </span>
                      <span>
                        {entry.source_lang} → {entry.target_lang}
                      </span>
                      {entry.ts > 0 && <span>· {formatTs(entry.ts)}</span>}
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSpeakText(entry.source_text);
                        }}
                        className="m3-state flex h-7 w-7 items-center justify-center rounded-full text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-highest)] hover:text-[var(--md-sys-color-primary)]"
                        title="朗读原文"
                      >
                        <Volume2 size={14} />
                      </button>
                      {tab === "history" ? (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onToggleFavorite(entry);
                          }}
                          className={`m3-state flex h-7 w-7 items-center justify-center rounded-full ${
                            starred
                              ? "text-[var(--md-sys-color-warning)]"
                              : "text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-highest)]"
                          }`}
                          title={starred ? "取消收藏" : "收藏到生词本"}
                        >
                          <Star size={14} fill={starred ? "currentColor" : "none"} />
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onRemoveFavorite(entry.id);
                          }}
                          className="m3-state flex h-7 w-7 items-center justify-center rounded-full text-[var(--md-sys-color-on-surface-variant)] hover:text-[var(--md-sys-color-error)]"
                          title="移出生词本"
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onCopyResult(entry);
                        }}
                        className="m3-state flex items-center gap-1 rounded-full bg-[var(--md-sys-color-secondary-container)] px-2.5 py-1 text-xs font-medium text-[var(--md-sys-color-on-secondary-container)] hover:brightness-105"
                        title="复制译文"
                      >
                        <Copy size={12} />
                        <span>复制</span>
                      </button>
                    </div>
                  </div>

                  <div className="line-clamp-2 text-sm text-[var(--md-sys-color-on-surface-variant)]">
                    {entry.source_text}
                  </div>
                  <div className="mt-2 line-clamp-3 border-t border-[var(--md-sys-color-outline-variant)]/40 pt-2 text-sm font-medium text-[var(--md-sys-color-on-surface)]">
                    {entry.result_text}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
