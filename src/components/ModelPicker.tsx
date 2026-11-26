import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, ChevronUp, RotateCcw, Settings2, SlidersHorizontal, X } from "lucide-react";
import {
  EFFORT_LABELS,
  EFFORT_SHORT_LABELS,
  MODEL_AUTO,
  REASONING_EFFORTS,
  displayModelLabel,
  truncateLabel,
  type LlmProfile,
  type ReasoningEffort,
} from "../lib/types";

interface ModelPickerProps {
  profiles: LlmProfile[];
  activeProfile: LlmProfile;
  disabled?: boolean;
  onSelectProvider: (profileId: string) => void;
  onSelectModel: (profileId: string, model: string) => void;
  onChangeEffort: (profileId: string, effort: ReasoningEffort) => void;
  onOpenSettingsForProfile: (profileId: string) => void;
}

export function ModelPicker({
  profiles,
  activeProfile,
  disabled,
  onSelectProvider,
  onSelectModel,
  onChangeEffort,
  onOpenSettingsForProfile,
}: ModelPickerProps) {
  const [open, setOpen] = useState(false);
  const [providersOpen, setProvidersOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const rawEffort = activeProfile.reasoning_effort === "minimal" ? "low" : activeProfile.reasoning_effort;
  const effort = (REASONING_EFFORTS.includes(rawEffort as ReasoningEffort)
    ? rawEffort
    : "") as ReasoningEffort;
  const effortIdx = Math.max(0, REASONING_EFFORTS.indexOf(effort));
  const sliderPct = (effortIdx / (REASONING_EFFORTS.length - 1)) * 100;

  const buttonText = `${truncateLabel(displayModelLabel(activeProfile.model), 28)} · ${EFFORT_SHORT_LABELS[effort]}`;

  useEffect(() => {
    if (disabled && open) {
      setOpen(false);
      setProvidersOpen(false);
    }
  }, [disabled, open]);

  useEffect(() => {
    if (!open) return;
    const onMouseDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setProvidersOpen(false);
        setOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        if (providersOpen) {
          setProvidersOpen(false);
        } else {
          setOpen(false);
        }
      }
    };
    window.addEventListener("mousedown", onMouseDown);
    window.addEventListener("keydown", onKeyDown, true);
    return () => {
      window.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("keydown", onKeyDown, true);
    };
  }, [open, providersOpen]);

  const candidates = activeProfile.models.length > 0 ? activeProfile.models : [];

  return (
    <div ref={containerRef} className="relative flex items-center justify-center">
      {open && (
        <div
          className="absolute bottom-full left-1/2 z-50 mb-3 w-[380px] max-w-[92vw] -translate-x-1/2 overflow-hidden rounded-[24px] border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)]"
          style={{ boxShadow: "var(--md-elevation-3)" }}
        >
          {/* Header: Provider selector pill + close */}
          <div className="flex items-center justify-between border-b border-[var(--md-sys-color-outline-variant)]/70 bg-[var(--md-sys-color-surface-container)] px-4 py-3">
            <button
              type="button"
              onClick={() => setProvidersOpen((v) => !v)}
              className="m3-state flex max-w-[280px] items-center gap-2 rounded-full bg-[var(--md-sys-color-secondary-container)] px-3.5 py-1.5 text-left text-sm font-medium text-[var(--md-sys-color-on-secondary-container)] hover:brightness-105"
              title="切换服务商"
            >
              <span className="truncate">{activeProfile.name}</span>
              {providersOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
            <button
              type="button"
              onClick={() => {
                setProvidersOpen(false);
                setOpen(false);
              }}
              className="m3-state flex h-9 w-9 items-center justify-center rounded-full text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-highest)]"
              title="关闭"
            >
              <X size={18} />
            </button>
          </div>

          {/* Expandable Provider list */}
          {providersOpen && (
            <div className="max-h-48 space-y-1 overflow-y-auto border-b border-[var(--md-sys-color-outline-variant)]/70 bg-[var(--md-sys-color-surface-container)] p-2">
              {profiles.map((p) => {
                const isCurrent = p.id === activeProfile.id;
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => {
                      onSelectProvider(p.id);
                      setProvidersOpen(false);
                    }}
                    title={`${p.name}（${p.models.length} 个候选模型）`}
                    className={`m3-state flex w-full items-center justify-between rounded-full px-3.5 py-2 text-left text-sm ${
                      isCurrent
                        ? "bg-[var(--md-sys-color-primary-container)] font-medium text-[var(--md-sys-color-on-primary-container)]"
                        : "text-[var(--md-sys-color-on-surface)] hover:bg-[var(--md-sys-color-surface-container-highest)]"
                    }`}
                  >
                    <span className="flex items-center gap-2.5 truncate">
                      <span className="w-4 shrink-0 text-center">
                        {isCurrent && <Check size={16} />}
                      </span>
                      <span className="truncate">{p.name}</span>
                    </span>
                    <span className="ml-2 shrink-0 rounded-full bg-[var(--md-sys-color-surface-container-highest)] px-2 py-0.5 text-xs text-[var(--md-sys-color-on-surface-variant)]">
                      {p.models.length}
                    </span>
                  </button>
                );
              })}
            </div>
          )}

          {/* Candidate models */}
          <div className="max-h-60 space-y-1 overflow-y-auto p-2">
            <button
              type="button"
              onClick={() => onSelectModel(activeProfile.id, MODEL_AUTO)}
              className={`m3-state flex w-full items-center gap-2.5 rounded-full px-3.5 py-2 text-left text-sm ${
                activeProfile.model === MODEL_AUTO
                  ? "bg-[var(--md-sys-color-primary-container)] font-medium text-[var(--md-sys-color-on-primary-container)]"
                  : "text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-highest)] hover:text-[var(--md-sys-color-on-surface)]"
              }`}
            >
              <span className="w-4 shrink-0 text-center">
                {activeProfile.model === MODEL_AUTO && <Check size={16} />}
              </span>
              <span className="truncate">自动选择（优先非推理模型）</span>
            </button>

            {candidates.length === 0 ? (
              <div className="px-4 py-4 text-center text-sm text-[var(--md-sys-color-on-surface-variant)]">
                暂无候选模型，请点击下方「管理候选模型…」添加
              </div>
            ) : (
              candidates.map((m) => {
                if (m === MODEL_AUTO) return null;
                const isSelected = activeProfile.model === m;
                return (
                  <button
                    key={m}
                    type="button"
                    onClick={() => onSelectModel(activeProfile.id, m)}
                    className={`m3-state flex w-full items-center gap-2.5 rounded-full px-3.5 py-2 text-left text-sm ${
                      isSelected
                        ? "bg-[var(--md-sys-color-primary-container)] font-medium text-[var(--md-sys-color-on-primary-container)]"
                        : "text-[var(--md-sys-color-on-surface)] hover:bg-[var(--md-sys-color-surface-container-highest)]"
                    }`}
                  >
                    <span className="w-4 shrink-0 text-center">
                      {isSelected && <Check size={16} />}
                    </span>
                    <span className="truncate font-mono-editor text-[13.5px]">{m}</span>
                  </button>
                );
              })
            )}
          </div>

          {/* Reasoning effort M3 Slider */}
          <div className="border-t border-[var(--md-sys-color-outline-variant)]/70 bg-[var(--md-sys-color-surface-container)] px-4 py-3.5">
            <div className="mb-2 flex items-center justify-between text-sm">
              <span className="font-medium text-[var(--md-sys-color-on-surface-variant)]">
                Reasoning Effort
              </span>
              <div className="flex items-center gap-2">
                <span className="rounded-full bg-[var(--md-sys-color-tertiary-container)] px-2.5 py-0.5 font-mono-editor text-xs font-semibold text-[var(--md-sys-color-on-tertiary-container)]">
                  {EFFORT_LABELS[effort]}
                </span>
                {effort !== "" && (
                  <button
                    type="button"
                    onClick={() => onChangeEffort(activeProfile.id, "")}
                    className="m3-state flex h-7 w-7 items-center justify-center rounded-full text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-highest)]"
                    title="Reset to default"
                  >
                    <RotateCcw size={14} />
                  </button>
                )}
              </div>
            </div>

            <input
              type="range"
              min={0}
              max={REASONING_EFFORTS.length - 1}
              step={1}
              value={effortIdx}
              onChange={(e) => {
                const next = REASONING_EFFORTS[Number(e.target.value)] ?? "";
                onChangeEffort(activeProfile.id, next);
              }}
              style={{
                background: `linear-gradient(to right, var(--md-sys-color-primary) 0%, var(--md-sys-color-primary) ${sliderPct}%, var(--md-sys-color-surface-container-highest) ${sliderPct}%, var(--md-sys-color-surface-container-highest) 100%)`,
              }}
              className="m3-slider w-full"
            />

            <div className="mt-2 grid grid-cols-6 gap-1">
              {REASONING_EFFORTS.map((item) => {
                const active = item === effort;
                return (
                  <button
                    key={item || "default"}
                    type="button"
                    onClick={() => onChangeEffort(activeProfile.id, item)}
                    className={`rounded-full py-1 text-center font-mono-editor text-[11px] transition ${
                      active
                        ? "bg-[var(--md-sys-color-primary)] font-semibold text-[var(--md-sys-color-on-primary)]"
                        : "text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-highest)]"
                    }`}
                  >
                    {EFFORT_SHORT_LABELS[item]}
                  </button>
                );
              })}
            </div>

            <div className="mt-3 flex justify-end border-t border-[var(--md-sys-color-outline-variant)]/50 pt-2.5">
              <button
                type="button"
                onClick={() => {
                  setProvidersOpen(false);
                  setOpen(false);
                  onOpenSettingsForProfile(activeProfile.id);
                }}
                className="m3-state flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium text-[var(--md-sys-color-primary)] hover:bg-[var(--md-sys-color-primary)]/12"
              >
                <Settings2 size={16} />
                <span>管理候选模型…</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* M3 Tonal Trigger Pill */}
      <button
        type="button"
        disabled={disabled}
        onClick={() => {
          setOpen((v) => !v);
          setProvidersOpen(false);
        }}
        className="m3-state flex h-10 items-center gap-2 rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-secondary-container)] px-4 text-sm font-medium text-[var(--md-sys-color-on-secondary-container)] hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-50"
        title="切换模型与思考强度 (Reasoning Effort)"
      >
        <SlidersHorizontal size={16} className="shrink-0" />
        <span className="max-w-[300px] truncate">{buttonText}</span>
        <ChevronDown size={16} className="shrink-0" />
      </button>
    </div>
  );
}
