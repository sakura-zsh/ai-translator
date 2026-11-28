import { useEffect, useMemo, useState } from "react";
import {
  Check,
  CheckCircle2,
  Download,
  ListPlus,
  Loader2,
  Plus,
  Search,
  Trash2,
  Upload,
  Volume2,
  X,
} from "lucide-react";
import { api } from "../lib/tauri";
import {
  AUTO_SCENE_ID,
  AUTO_SCENE_LABEL,
  MODEL_AUTO,
  likelyReasoningModel,
  newShortId,
  type ApiProtocol,
  type AppConfig,
  type CustomScene,
  type JevProtocol,
  type LanguageItem,
  type LlmProfile,
  type ProviderTemplate,
  type ScenePreset,
  type ThemeMode,
  type VoiceChoice,
} from "../lib/types";

export type SettingsTab = "llm" | "translation" | "jev" | "appearance";

interface SettingsModalProps {
  open: boolean;
  initialTab?: SettingsTab;
  initialProfileId?: string;
  config: AppConfig;
  templates: ProviderTemplate[];
  targetLanguages: LanguageItem[];
  builtinScenes: ScenePreset[];
  ttsVoices: VoiceChoice[];
  isWindows: boolean;
  onClose: () => void;
  onSave: (nextConfig: AppConfig) => Promise<void>;
}

const TTS_PREVIEW_TEXT = "Hello, this is a voice preview. 你好，这是语音试听。";

function M3Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 rounded-2xl bg-[var(--md-sys-color-surface-container)] px-4 py-3 text-sm">
      <span className="text-[var(--md-sys-color-on-surface)]">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border-2 transition-colors ${
          checked
            ? "border-[var(--md-sys-color-primary)] bg-[var(--md-sys-color-primary)]"
            : "border-[var(--md-sys-color-outline)] bg-[var(--md-sys-color-surface-container-highest)]"
        }`}
      >
        <span
          className={`flex h-5 w-5 items-center justify-center rounded-full transition-transform ${
            checked
              ? "translate-x-5 bg-[var(--md-sys-color-on-primary)] text-[var(--md-sys-color-primary)]"
              : "translate-x-0.5 bg-[var(--md-sys-color-outline)]"
          }`}
        >
          {checked && <Check size={12} strokeWidth={3} />}
        </span>
      </button>
    </label>
  );
}

export function SettingsModal({
  open,
  initialTab = "llm",
  initialProfileId,
  config,
  templates,
  targetLanguages,
  builtinScenes,
  ttsVoices,
  isWindows,
  onClose,
  onSave,
}: SettingsModalProps) {
  const [tab, setTab] = useState<SettingsTab>(initialTab);
  const [draft, setDraft] = useState<AppConfig>(config);
  const [selectedPid, setSelectedPid] = useState<string>(
    initialProfileId || config.active_profile_id,
  );
  const [glossaryText, setGlossaryText] = useState("");
  const [newModelInput, setNewModelInput] = useState("");
  const [templateChoice, setTemplateChoice] = useState("");

  const [catalogOpen, setCatalogOpen] = useState(false);
  const [catalogModels, setCatalogModels] = useState<string[]>([]);
  const [catalogSearch, setCatalogSearch] = useState("");
  const [catalogChecked, setCatalogChecked] = useState<Set<string>>(new Set());
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogErr, setCatalogErr] = useState("");

  const [sceneModalOpen, setSceneModalOpen] = useState(false);
  const [selectedSceneId, setSelectedSceneId] = useState<string>("general");

  const [llmStatus, setLlmStatus] = useState<{ text: string; ok: boolean } | null>(null);
  const [llmTesting, setLlmTesting] = useState(false);
  const [jevStatus, setJevStatus] = useState<{ text: string; ok: boolean } | null>(null);
  const [jevTesting, setJevTesting] = useState(false);
  const [jevFetching, setJevFetching] = useState(false);
  const [jevFetchedModels, setJevFetchedModels] = useState<string[]>([]);
  const [ttsPreviewing, setTtsPreviewing] = useState(false);
  const [ttsStatus, setTtsStatus] = useState<{ text: string; ok: boolean } | null>(null);
  const [cfgIoStatus, setCfgIoStatus] = useState<{ text: string; ok: boolean } | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    const cloned: AppConfig = JSON.parse(JSON.stringify(config));
    setDraft(cloned);
    setTab(initialTab);
    setSelectedPid(
      initialProfileId && cloned.profiles.some((p) => p.id === initialProfileId)
        ? initialProfileId
        : cloned.active_profile_id,
    );
    setTemplateChoice("");
    setNewModelInput("");
    setLlmStatus(null);
    setJevStatus(null);
    setTtsStatus(null);
    api.formatGlossaryText(cloned.translation.glossary).then(setGlossaryText).catch(() => {
      const lines = Object.entries(cloned.translation.glossary).map(
        ([k, v]) => `${k} = ${v}`,
      );
      setGlossaryText(lines.join("\n"));
    });
  }, [open, config, initialTab, initialProfileId]);

  const activeProfile = useMemo(
    () => draft.profiles.find((p) => p.id === selectedPid) ?? draft.profiles[0],
    [draft.profiles, selectedPid],
  );

  const allScenes = useMemo<ScenePreset[]>(() => {
    return [
      ...builtinScenes,
      ...draft.translation.custom_scenes.map((c) => ({
        id: c.id,
        label: c.label,
        prompt: c.prompt,
        builtin: false,
      })),
    ];
  }, [builtinScenes, draft.translation.custom_scenes]);

  if (!open || !activeProfile) return null;

  const updateProfile = (updater: (p: LlmProfile) => LlmProfile) => {
    setDraft((prev) => ({
      ...prev,
      profiles: prev.profiles.map((p) => (p.id === activeProfile.id ? updater(p) : p)),
    }));
  };

  const addProfile = () => {
    const p: LlmProfile = {
      id: newShortId(),
      name: `新配置 ${draft.profiles.length + 1}`,
      base_url: "https://api.openai.com/v1",
      api_key: "",
      api_protocol: "chat_completions",
      model: "gpt-4o-mini",
      models: ["gpt-4o-mini"],
      vision_model: "",
      temperature: 0.2,
      timeout_s: 60,
      max_tokens: 4096,
      reasoning_effort: "",
      model_options: [],
    };
    setDraft((prev) => ({ ...prev, profiles: [...prev.profiles, p] }));
    setSelectedPid(p.id);
    setLlmStatus(null);
  };

  const deleteProfile = () => {
    if (draft.profiles.length <= 1) return;
    const remaining = draft.profiles.filter((p) => p.id !== activeProfile.id);
    setDraft((prev) => ({
      ...prev,
      profiles: remaining,
      active_profile_id:
        prev.active_profile_id === activeProfile.id
          ? remaining[0].id
          : prev.active_profile_id,
    }));
    setSelectedPid(remaining[0].id);
  };

  const applyTemplate = (tplId: string) => {
    setTemplateChoice(tplId);
    const tpl = templates.find((t) => t.id === tplId);
    if (!tpl) return;
    updateProfile((p) => {
      const models = [...p.models];
      for (const m of [tpl.text_model, tpl.vision_model]) {
        if (m && !models.includes(m) && models.length < 50) {
          models.push(m);
        }
      }
      return {
        ...p,
        name: tpl.name,
        base_url: tpl.base_url,
        api_protocol: tpl.api_protocol,
        models,
        model: tpl.text_model || p.model,
        vision_model:
          tpl.vision_model && tpl.vision_model !== tpl.text_model
            ? tpl.vision_model
            : "",
      };
    });
  };

  const addCandidateModel = () => {
    const val = newModelInput.trim();
    if (!val) return;
    updateProfile((p) => {
      if (p.models.includes(val) || p.models.length >= 50) return p;
      return { ...p, models: [...p.models, val] };
    });
    setNewModelInput("");
  };

  const removeCandidateModel = (name: string) => {
    updateProfile((p) => {
      if (p.models.length <= 1) return p;
      const models = p.models.filter((m) => m !== name);
      return {
        ...p,
        models,
        model: p.model === name ? models[0] : p.model,
        vision_model: p.vision_model === name ? "" : p.vision_model,
      };
    });
  };

  const openCatalog = async () => {
    setCatalogOpen(true);
    setCatalogSearch("");
    setCatalogErr("");
    setCatalogChecked(new Set(activeProfile.models));
    setCatalogModels(activeProfile.model_options);
    setCatalogLoading(true);
    try {
      const list = await api.fetchProfileModels(activeProfile, false);
      setCatalogModels(list);
      updateProfile((p) => ({ ...p, model_options: list.slice(0, 500) }));
    } catch (e) {
      setCatalogErr(String(e));
    } finally {
      setCatalogLoading(false);
    }
  };

  const commitCatalog = () => {
    updateProfile((p) => {
      const merged = [...p.models];
      for (const id of catalogChecked) {
        if (!merged.includes(id) && merged.length < 50) {
          merged.push(id);
        }
      }
      return { ...p, models: merged };
    });
    setCatalogOpen(false);
  };

  const handleTestLlm = async () => {
    setLlmTesting(true);
    setLlmStatus(null);
    try {
      const reply = await api.testProfileConnection(activeProfile);
      setLlmStatus({ text: `连接成功：${reply}`, ok: true });
    } catch (e) {
      setLlmStatus({ text: String(e), ok: false });
    } finally {
      setLlmTesting(false);
    }
  };

  const handleTestJev = async () => {
    setJevTesting(true);
    setJevStatus(null);
    try {
      const reply = await api.testJevConnection(draft.jev);
      setJevStatus({ text: reply, ok: true });
    } catch (e) {
      setJevStatus({ text: String(e), ok: false });
    } finally {
      setJevTesting(false);
    }
  };

  const handleFetchJevModels = async () => {
    setJevFetching(true);
    setJevStatus(null);
    try {
      const list = await api.fetchJevModels(draft.jev);
      setJevFetchedModels(list);
      if (list.length > 0 && !list.includes(draft.jev.model)) {
        setDraft((prev) => ({
          ...prev,
          jev: { ...prev.jev, model: list[0] },
        }));
      }
      setJevStatus({ text: `已获取 ${list.length} 个 Jev 模型`, ok: true });
    } catch (e) {
      setJevStatus({ text: String(e), ok: false });
    } finally {
      setJevFetching(false);
    }
  };

  const handleTtsPreview = async () => {
    setTtsPreviewing(true);
    setTtsStatus(null);
    try {
      const dataUrl = await api.synthesizeTts(
        TTS_PREVIEW_TEXT,
        draft.tts.voice,
        draft.tts.rate,
      );
      const audio = new Audio(dataUrl);
      await audio.play();
      setTtsStatus({ text: "试听播放中", ok: true });
    } catch (e) {
      setTtsStatus({ text: String(e), ok: false });
    } finally {
      setTtsPreviewing(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const parsedGlossary = await api.parseGlossaryText(glossaryText);
      const limit = Math.max(0, Math.min(100, draft.history_limit));
      const next: AppConfig = {
        ...draft,
        history_limit: limit,
        history: draft.history.slice(0, limit),
        translation: {
          ...draft.translation,
          glossary: parsedGlossary,
        },
      };
      await onSave(next);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  const selectedScene = allScenes.find((s) => s.id === selectedSceneId) ?? allScenes[0];

  const updateCustomScene = (id: string, patch: Partial<CustomScene>) => {
    setDraft((prev) => ({
      ...prev,
      translation: {
        ...prev.translation,
        custom_scenes: prev.translation.custom_scenes.map((c) =>
          c.id === id ? { ...c, ...patch } : c,
        ),
      },
    }));
  };

  const addCustomScene = () => {
    if (draft.translation.custom_scenes.length >= 20) return;
    const item: CustomScene = {
      id: `custom_${newShortId()}`,
      label: `自定义场景 ${draft.translation.custom_scenes.length + 1}`,
      prompt: "",
    };
    setDraft((prev) => ({
      ...prev,
      translation: {
        ...prev.translation,
        custom_scenes: [...prev.translation.custom_scenes, item],
      },
    }));
    setSelectedSceneId(item.id);
  };

  const deleteCustomScene = (id: string) => {
    setDraft((prev) => ({
      ...prev,
      translation: {
        ...prev.translation,
        scene: prev.translation.scene === id ? "general" : prev.translation.scene,
        custom_scenes: prev.translation.custom_scenes.filter((c) => c.id !== id),
      },
    }));
    setSelectedSceneId("general");
  };

  const filteredCatalog = catalogModels.filter((m) =>
    m.toLowerCase().includes(catalogSearch.trim().toLowerCase()),
  );

  const inputCls =
    "h-10 w-full rounded-xl border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] px-3.5 text-sm text-[var(--md-sys-color-on-surface)] outline-none focus:border-[var(--md-sys-color-primary)]";

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/55 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="flex h-[700px] max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-[28px] border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)]"
        style={{ boxShadow: "var(--md-elevation-3)" }}
      >
        {/* Header with M3 Pill Tabs */}
        <div className="flex items-center justify-between border-b border-[var(--md-sys-color-outline-variant)]/70 bg-[var(--md-sys-color-surface-container)] px-6 py-3.5">
          <div className="flex flex-wrap items-center gap-2">
            {(
              [
                ["llm", "LLM 配置"],
                ["translation", "翻译与朗读"],
                ["jev", "Jev 判断"],
                ["appearance", "外观与快捷键"],
              ] as [SettingsTab, string][]
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={`m3-state h-9 rounded-full px-4 text-sm font-medium ${
                  tab === id
                    ? "bg-[var(--md-sys-color-secondary-container)] text-[var(--md-sys-color-on-secondary-container)]"
                    : "text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-high)]"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="m3-state flex h-9 w-9 items-center justify-center rounded-full text-[var(--md-sys-color-on-surface-variant)] hover:bg-[var(--md-sys-color-surface-container-highest)]"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6">
          {tab === "llm" && (
            <div className="grid grid-cols-1 gap-6 md:grid-cols-12">
              <div className="space-y-3 md:col-span-4">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold tracking-wide text-[var(--md-sys-color-on-surface-variant)] uppercase">
                    服务商配置
                  </span>
                  <div className="flex gap-1.5">
                    <button
                      type="button"
                      onClick={addProfile}
                      className="m3-state flex h-8 items-center gap-1 rounded-full bg-[var(--md-sys-color-secondary-container)] px-3 text-xs font-medium text-[var(--md-sys-color-on-secondary-container)]"
                    >
                      <Plus size={14} />
                      <span>新增</span>
                    </button>
                    <button
                      type="button"
                      onClick={deleteProfile}
                      disabled={draft.profiles.length <= 1}
                      className="m3-state flex h-8 w-8 items-center justify-center rounded-full bg-[var(--md-sys-color-surface-container-high)] text-[var(--md-sys-color-error)] disabled:opacity-40"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>

                <div className="max-h-[470px] space-y-1.5 overflow-y-auto pr-1">
                  {draft.profiles.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => {
                        setSelectedPid(p.id);
                        setLlmStatus(null);
                      }}
                      className={`m3-state flex w-full items-center justify-between rounded-full px-4 py-2.5 text-left text-sm ${
                        p.id === activeProfile.id
                          ? "bg-[var(--md-sys-color-primary-container)] font-medium text-[var(--md-sys-color-on-primary-container)]"
                          : "bg-transparent hover:bg-[var(--md-sys-color-surface-container-high)]"
                      }`}
                    >
                      <span className="truncate">{p.name}</span>
                      <span className="ml-2 rounded-full bg-[var(--md-sys-color-surface-container-highest)] px-2 py-0.5 text-xs text-[var(--md-sys-color-on-surface-variant)]">
                        {p.models.length}
                      </span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-4 md:col-span-8">
                <div className="grid grid-cols-2 gap-3.5">
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      套用服务商模板
                    </label>
                    <select
                      value={templateChoice}
                      onChange={(e) => applyTemplate(e.target.value)}
                      className={inputCls}
                    >
                      <option value="">自定义（选择模板以填充）</option>
                      {templates.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      配置名称
                    </label>
                    <input
                      type="text"
                      value={activeProfile.name}
                      onChange={(e) =>
                        updateProfile((p) => ({ ...p, name: e.target.value }))
                      }
                      className={inputCls}
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3.5">
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      Base URL
                    </label>
                    <input
                      type="text"
                      value={activeProfile.base_url}
                      onChange={(e) =>
                        updateProfile((p) => ({ ...p, base_url: e.target.value }))
                      }
                      className={`${inputCls} font-mono-editor`}
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      API Key
                    </label>
                    <input
                      type="password"
                      value={activeProfile.api_key}
                      onChange={(e) =>
                        updateProfile((p) => ({ ...p, api_key: e.target.value }))
                      }
                      placeholder="sk-..."
                      className={`${inputCls} font-mono-editor`}
                    />
                  </div>
                </div>

                <div className="grid grid-cols-4 gap-3">
                  <div className="col-span-2">
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      API 协议
                    </label>
                    <select
                      value={activeProfile.api_protocol}
                      onChange={(e) =>
                        updateProfile((p) => ({
                          ...p,
                          api_protocol: e.target.value as ApiProtocol,
                        }))
                      }
                      className={inputCls}
                    >
                      <option value="chat_completions">Chat Completions (/chat/completions)</option>
                      <option value="responses">Responses API (/responses)</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      Temperature
                    </label>
                    <input
                      type="number"
                      step={0.1}
                      min={0}
                      max={2}
                      value={activeProfile.temperature}
                      onChange={(e) =>
                        updateProfile((p) => ({
                          ...p,
                          temperature: Number(e.target.value) || 0,
                        }))
                      }
                      className={inputCls}
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      超时 (s)
                    </label>
                    <input
                      type="number"
                      min={5}
                      max={600}
                      value={activeProfile.timeout_s}
                      onChange={(e) =>
                        updateProfile((p) => ({
                          ...p,
                          timeout_s: Math.max(5, Number(e.target.value) || 60),
                        }))
                      }
                      className={inputCls}
                    />
                  </div>
                </div>

                {/* Candidate models card */}
                <div className="rounded-[20px] border border-[var(--md-sys-color-outline-variant)]/60 bg-[var(--md-sys-color-surface-container)] p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="text-sm font-medium">
                      候选模型（{activeProfile.models.length}/50）
                    </span>
                    <button
                      type="button"
                      onClick={openCatalog}
                      className="m3-state flex h-9 items-center gap-1.5 rounded-full bg-[var(--md-sys-color-secondary-container)] px-3.5 text-xs font-medium text-[var(--md-sys-color-on-secondary-container)]"
                    >
                      <ListPlus size={15} />
                      <span>从服务商列表…</span>
                    </button>
                  </div>

                  <div className="mb-3 flex gap-2">
                    <input
                      type="text"
                      value={newModelInput}
                      onChange={(e) => setNewModelInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          addCandidateModel();
                        }
                      }}
                      placeholder="输入模型 ID 后回车或点添加…"
                      className="h-10 min-w-0 flex-1 rounded-xl border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] px-3.5 font-mono-editor text-sm outline-none focus:border-[var(--md-sys-color-primary)]"
                    />
                    <button
                      type="button"
                      onClick={addCandidateModel}
                      className="m3-state h-10 rounded-full bg-[var(--md-sys-color-primary-container)] px-4 text-sm font-medium text-[var(--md-sys-color-on-primary-container)]"
                    >
                      添加
                    </button>
                  </div>

                  <div className="max-h-40 space-y-1 overflow-y-auto pr-1">
                    <button
                      type="button"
                      onClick={() =>
                        updateProfile((p) => ({ ...p, model: MODEL_AUTO }))
                      }
                      className={`m3-state flex w-full items-center gap-2.5 rounded-full px-3.5 py-2 text-left text-sm ${
                        activeProfile.model === MODEL_AUTO
                          ? "bg-[var(--md-sys-color-primary-container)] font-medium text-[var(--md-sys-color-on-primary-container)]"
                          : "hover:bg-[var(--md-sys-color-surface-container-high)]"
                      }`}
                    >
                      <span className="w-4 text-center">
                        {activeProfile.model === MODEL_AUTO && <Check size={15} />}
                      </span>
                      <span>自动选择（优先非推理模型）</span>
                    </button>

                    {activeProfile.models.map((m) => {
                      const isCur = activeProfile.model === m;
                      return (
                        <div
                          key={m}
                          className={`flex items-center justify-between rounded-full px-3.5 py-1.5 text-sm ${
                            isCur
                              ? "bg-[var(--md-sys-color-primary-container)] text-[var(--md-sys-color-on-primary-container)]"
                              : "hover:bg-[var(--md-sys-color-surface-container-high)]"
                          }`}
                        >
                          <button
                            type="button"
                            onClick={() => updateProfile((p) => ({ ...p, model: m }))}
                            className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
                          >
                            <span className="w-4 shrink-0 text-center">
                              {isCur && <Check size={15} />}
                            </span>
                            <span className="truncate font-mono-editor">{m}</span>
                            {likelyReasoningModel(m) && (
                              <span className="shrink-0 rounded-full bg-[var(--md-sys-color-tertiary-container)] px-2 py-0.5 text-[11px] font-medium text-[var(--md-sys-color-on-tertiary-container)]">
                                推理
                              </span>
                            )}
                          </button>
                          <button
                            type="button"
                            disabled={activeProfile.models.length <= 1}
                            onClick={() => removeCandidateModel(m)}
                            className="ml-2 flex h-7 w-7 items-center justify-center rounded-full text-[var(--md-sys-color-on-surface-variant)] hover:text-[var(--md-sys-color-error)] disabled:opacity-30"
                            title="移除此候选"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="grid grid-cols-2 items-end gap-3.5">
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      专用视觉模型（留空跟随当前模型）
                    </label>
                    <select
                      value={activeProfile.vision_model}
                      onChange={(e) =>
                        updateProfile((p) => ({ ...p, vision_model: e.target.value }))
                      }
                      className={inputCls}
                    >
                      <option value="">跟随当前模型</option>
                      {activeProfile.models.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={handleTestLlm}
                      disabled={llmTesting}
                      className="m3-state flex h-10 items-center gap-2 rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] px-4 text-sm font-medium hover:bg-[var(--md-sys-color-surface-container-highest)] disabled:opacity-50"
                    >
                      {llmTesting ? (
                        <Loader2 size={16} className="animate-spin" />
                      ) : (
                        <CheckCircle2 size={16} />
                      )}
                      <span>测试连接</span>
                    </button>
                  </div>
                </div>

                {llmStatus && (
                  <div
                    className={`rounded-2xl px-4 py-2.5 text-sm ${
                      llmStatus.ok
                        ? "bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-success)]"
                        : "bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)]"
                    }`}
                  >
                    {llmStatus.text}
                  </div>
                )}
              </div>
            </div>
          )}

          {tab === "translation" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                    默认目标语言
                  </label>
                  <select
                    value={draft.translation.target_lang}
                    onChange={(e) =>
                      setDraft((prev) => ({
                        ...prev,
                        translation: {
                          ...prev.translation,
                          target_lang: e.target.value,
                        },
                      }))
                    }
                    className={inputCls}
                  >
                    {targetLanguages.map((l) => (
                      <option key={l.code} value={l.code}>
                        {l.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                    翻译场景
                  </label>
                  <div className="flex gap-2">
                    <select
                      value={draft.translation.scene}
                      onChange={(e) =>
                        setDraft((prev) => ({
                          ...prev,
                          translation: { ...prev.translation, scene: e.target.value },
                        }))
                      }
                      className={`${inputCls} min-w-0 flex-1`}
                    >
                      <option value={AUTO_SCENE_ID}>{AUTO_SCENE_LABEL}</option>
                      {allScenes.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => setSceneModalOpen(true)}
                      className="m3-state h-10 rounded-full bg-[var(--md-sys-color-secondary-container)] px-4 text-sm font-medium text-[var(--md-sys-color-on-secondary-container)]"
                    >
                      管理…
                    </button>
                  </div>
                </div>
              </div>

              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                  个人补充提示词（与所选场景叠加生效）
                </label>
                <textarea
                  rows={2}
                  value={draft.translation.supplementary_prompt}
                  onChange={(e) =>
                    setDraft((prev) => ({
                      ...prev,
                      translation: {
                        ...prev.translation,
                        supplementary_prompt: e.target.value,
                      },
                    }))
                  }
                  placeholder="如：使用正式书面中文，保留专业术语英文原文，不要意译品牌名。"
                  className="w-full rounded-2xl border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] p-3.5 text-sm outline-none focus:border-[var(--md-sys-color-primary)]"
                />
              </div>

              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                  术语表（每行一条 `术语 = 译文`，支持 = / → / -&gt; / Tab，上限 100 条）
                </label>
                <textarea
                  rows={4}
                  value={glossaryText}
                  onChange={(e) => setGlossaryText(e.target.value)}
                  placeholder="API = 接口&#10;Token -> 令牌"
                  className="w-full rounded-2xl border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] p-3.5 font-mono-editor text-sm outline-none focus:border-[var(--md-sys-color-primary)]"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                    OCR 语言包（tesseract -l）
                  </label>
                  <input
                    type="text"
                    value={draft.translation.ocr_langs}
                    onChange={(e) =>
                      setDraft((prev) => ({
                        ...prev,
                        translation: { ...prev.translation, ocr_langs: e.target.value },
                      }))
                    }
                    className={`${inputCls} font-mono-editor`}
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                    Tesseract 路径（留空使用 PATH）
                  </label>
                  <input
                    type="text"
                    value={draft.translation.tesseract_path}
                    onChange={(e) =>
                      setDraft((prev) => ({
                        ...prev,
                        translation: {
                          ...prev.translation,
                          tesseract_path: e.target.value,
                        },
                      }))
                    }
                    placeholder="tesseract"
                    className={`${inputCls} font-mono-editor`}
                  />
                </div>
              </div>

              <M3Switch
                checked={draft.translation.auto_copy_result}
                onChange={(v) =>
                  setDraft((prev) => ({
                    ...prev,
                    translation: { ...prev.translation, auto_copy_result: v },
                  }))
                }
                label="翻译完成后自动复制译文到剪贴板"
              />

              <M3Switch
                checked={draft.translation.auto_dictionary}
                onChange={(v) =>
                  setDraft((prev) => ({
                    ...prev,
                    translation: { ...prev.translation, auto_dictionary: v },
                  }))
                }
                label="单词 / 短语自动切换词典模式（音标、词性、释义、例句）"
              />

              <div className="space-y-3 rounded-[20px] border border-[var(--md-sys-color-outline-variant)]/60 bg-[var(--md-sys-color-surface-container)] p-4">
                <div className="text-sm font-medium">朗读（Edge 神经语音 TTS）</div>
                <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
                  <div className="sm:col-span-2">
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      发音音色（可选预设或输入任意 edge-tts 音色 ID）
                    </label>
                    <input
                      type="text"
                      list="tts-voice-list"
                      value={draft.tts.voice}
                      onChange={(e) =>
                        setDraft((prev) => ({
                          ...prev,
                          tts: { ...prev.tts, voice: e.target.value },
                        }))
                      }
                      className={inputCls}
                    />
                    <datalist id="tts-voice-list">
                      {ttsVoices.map((v) => (
                        <option key={v.voice} value={v.voice}>
                          {v.label}
                        </option>
                      ))}
                    </datalist>
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      语速偏移（-50% ~ +100%）
                    </label>
                    <input
                      type="number"
                      min={-50}
                      max={100}
                      value={draft.tts.rate}
                      onChange={(e) =>
                        setDraft((prev) => ({
                          ...prev,
                          tts: {
                            ...prev.tts,
                            rate: Math.max(-50, Math.min(100, Number(e.target.value) || 0)),
                          },
                        }))
                      }
                      className={inputCls}
                    />
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <label className="flex cursor-pointer items-center gap-2.5 text-sm">
                    <input
                      type="checkbox"
                      checked={draft.tts.auto_pronounce}
                      onChange={(e) =>
                        setDraft((prev) => ({
                          ...prev,
                          tts: { ...prev.tts, auto_pronounce: e.target.checked },
                        }))
                      }
                      className="h-4 w-4 accent-[var(--md-sys-color-primary)]"
                    />
                    <span>翻译完成后自动朗读译文</span>
                  </label>
                  <button
                    type="button"
                    onClick={handleTtsPreview}
                    disabled={ttsPreviewing}
                    className="m3-state flex h-9 items-center gap-1.5 rounded-full bg-[var(--md-sys-color-secondary-container)] px-4 text-sm font-medium text-[var(--md-sys-color-on-secondary-container)] disabled:opacity-50"
                  >
                    {ttsPreviewing ? (
                      <Loader2 size={15} className="animate-spin" />
                    ) : (
                      <Volume2 size={15} />
                    )}
                    <span>试听</span>
                  </button>
                </div>
                {ttsStatus && (
                  <div
                    className={`rounded-xl px-3.5 py-2 text-sm ${
                      ttsStatus.ok
                        ? "bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-success)]"
                        : "bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)]"
                    }`}
                  >
                    {ttsStatus.text}
                  </div>
                )}
              </div>

              <div className="space-y-3 rounded-[20px] border border-[var(--md-sys-color-outline-variant)]/60 bg-[var(--md-sys-color-surface-container)] p-4">
                <div>
                  <div className="text-sm font-medium">划词 / 快速翻译专用模型（可选）</div>
                  <p className="mt-0.5 text-xs text-[var(--md-sys-color-on-surface-variant)]">
                    为小窗划词翻译单独指定低延迟服务商与模型；留空则跟随主窗口当前服务商与模型。
                  </p>
                </div>
                <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      划词服务商
                    </label>
                    <select
                      value={draft.translation.quick_profile_id}
                      onChange={(e) =>
                        setDraft((prev) => ({
                          ...prev,
                          translation: {
                            ...prev.translation,
                            quick_profile_id: e.target.value,
                            quick_model: "",
                          },
                        }))
                      }
                      className={inputCls}
                    >
                      <option value="">跟随主窗口当前服务商</option>
                      {draft.profiles.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      划词模型（留空跟随服务商当前模型）
                    </label>
                    {(() => {
                      const qProf =
                        draft.profiles.find((p) => p.id === draft.translation.quick_profile_id) ??
                        draft.profiles.find((p) => p.id === draft.active_profile_id) ??
                        draft.profiles[0];
                      const quickCandidates = Array.from(
                        new Set([...(qProf?.models ?? []), ...(qProf?.model_options ?? [])]),
                      ).slice(0, 200);
                      return (
                        <>
                          <input
                            type="text"
                            list="quick-model-list"
                            value={draft.translation.quick_model}
                            onChange={(e) =>
                              setDraft((prev) => ({
                                ...prev,
                                translation: {
                                  ...prev.translation,
                                  quick_model: e.target.value,
                                },
                              }))
                            }
                            placeholder={qProf?.model || "跟随服务商默认模型"}
                            className={`${inputCls} font-mono-editor`}
                          />
                          <datalist id="quick-model-list">
                            {quickCandidates.map((m) => (
                              <option key={m} value={m} />
                            ))}
                          </datalist>
                        </>
                      );
                    })()}
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      划词推理强度
                    </label>
                    <select
                      value={draft.translation.quick_reasoning_effort}
                      onChange={(e) =>
                        setDraft((prev) => ({
                          ...prev,
                          translation: {
                            ...prev.translation,
                            quick_reasoning_effort: e.target.value,
                          },
                        }))
                      }
                      className={inputCls}
                    >
                      <option value="">不开启 / 默认（最低延迟）</option>
                      <option value="low">low</option>
                      <option value="medium">medium</option>
                      <option value="high">high</option>
                      <option value="xhigh">xhigh</option>
                      <option value="max">max</option>
                      <option value="__follow__">跟随服务商当前档位</option>
                    </select>
                  </div>
                </div>
              </div>
            </div>
          )}

          {tab === "jev" && (
            <div className="space-y-4">
              <div className="rounded-2xl bg-[var(--md-sys-color-surface-container)] p-4 text-sm text-[var(--md-sys-color-on-surface-variant)]">
                Jev（TypeSafe System One）是辅助决策裁判模型：只做场景自动路由、语种检测与译文质量评分，永远不会参与生成译文；任何调用失败均自动回退默认行为。
              </div>

              <M3Switch
                checked={draft.jev.enabled}
                onChange={(v) =>
                  setDraft((prev) => ({ ...prev, jev: { ...prev.jev, enabled: v } }))
                }
                label="启用 Jev 智能判断"
              />

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                    Base URL（留空则不生效）
                  </label>
                  <input
                    type="text"
                    value={draft.jev.base_url}
                    onChange={(e) =>
                      setDraft((prev) => ({
                        ...prev,
                        jev: { ...prev.jev, base_url: e.target.value },
                      }))
                    }
                    placeholder="https://api.typesafe.ai"
                    className={`${inputCls} font-mono-editor`}
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                    API Key
                  </label>
                  <input
                    type="password"
                    value={draft.jev.api_key}
                    onChange={(e) =>
                      setDraft((prev) => ({
                        ...prev,
                        jev: { ...prev.jev, api_key: e.target.value },
                      }))
                    }
                    className={`${inputCls} font-mono-editor`}
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3.5">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                    模型
                  </label>
                  <div className="flex gap-1.5">
                    <input
                      type="text"
                      list="jev-model-list"
                      value={draft.jev.model}
                      onChange={(e) =>
                        setDraft((prev) => ({
                          ...prev,
                          jev: { ...prev.jev, model: e.target.value },
                        }))
                      }
                      className={`${inputCls} min-w-0 flex-1 font-mono-editor`}
                    />
                    <datalist id="jev-model-list">
                      {jevFetchedModels.map((m) => (
                        <option key={m} value={m} />
                      ))}
                    </datalist>
                    <button
                      type="button"
                      onClick={handleFetchJevModels}
                      disabled={jevFetching}
                      className="m3-state h-10 rounded-full bg-[var(--md-sys-color-secondary-container)] px-3.5 text-sm font-medium text-[var(--md-sys-color-on-secondary-container)]"
                    >
                      {jevFetching ? <Loader2 size={14} className="animate-spin" /> : "拉取"}
                    </button>
                  </div>
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                    接口协议
                  </label>
                  <select
                    value={draft.jev.api_protocol}
                    onChange={(e) =>
                      setDraft((prev) => ({
                        ...prev,
                        jev: { ...prev.jev, api_protocol: e.target.value as JevProtocol },
                      }))
                    }
                    className={inputCls}
                  >
                    <option value="auto">自动探测（推荐）</option>
                    <option value="native">原生 SystemOne</option>
                    <option value="openai">OpenAI Chat Completions</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                    超时 (s)
                  </label>
                  <input
                    type="number"
                    min={5}
                    max={600}
                    value={draft.jev.timeout_s}
                    onChange={(e) =>
                      setDraft((prev) => ({
                        ...prev,
                        jev: {
                          ...prev.jev,
                          timeout_s: Math.max(5, Number(e.target.value) || 30),
                        },
                      }))
                    }
                    className={inputCls}
                  />
                </div>
              </div>

              <div className="space-y-2.5">
                <M3Switch
                  checked={draft.jev.route_scene}
                  onChange={(v) =>
                    setDraft((prev) => ({
                      ...prev,
                      jev: { ...prev.jev, route_scene: v },
                    }))
                  }
                  label="场景自动路由（主窗口场景选「自动判断（Jev）」时生效）"
                />
                <M3Switch
                  checked={draft.jev.detect_language}
                  onChange={(v) =>
                    setDraft((prev) => ({
                      ...prev,
                      jev: { ...prev.jev, detect_language: v },
                    }))
                  }
                  label="语种自动检测（源语言选「自动检测」时先由 Jev 判定）"
                />
                <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl bg-[var(--md-sys-color-surface-container)] px-4 py-3 text-sm">
                  <div className="flex flex-wrap items-center gap-5">
                    <label className="flex cursor-pointer items-center gap-2">
                      <input
                        type="checkbox"
                        checked={draft.jev.score_quality}
                        onChange={(e) =>
                          setDraft((prev) => ({
                            ...prev,
                            jev: { ...prev.jev, score_quality: e.target.checked },
                          }))
                        }
                        className="h-4 w-4 accent-[var(--md-sys-color-primary)]"
                      />
                      <span>译文质量评分</span>
                    </label>
                    <label className="flex cursor-pointer items-center gap-2">
                      <input
                        type="checkbox"
                        checked={draft.jev.retry_on_low_quality}
                        onChange={(e) =>
                          setDraft((prev) => ({
                            ...prev,
                            jev: { ...prev.jev, retry_on_low_quality: e.target.checked },
                          }))
                        }
                        className="h-4 w-4 accent-[var(--md-sys-color-primary)]"
                      />
                      <span>低于阈值自动重译一次</span>
                    </label>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[var(--md-sys-color-on-surface-variant)]">阈值:</span>
                    <input
                      type="number"
                      step={0.05}
                      min={0}
                      max={1}
                      value={draft.jev.quality_threshold}
                      onChange={(e) =>
                        setDraft((prev) => ({
                          ...prev,
                          jev: {
                            ...prev.jev,
                            quality_threshold: Math.max(
                              0,
                              Math.min(1, Number(e.target.value) || 0.6),
                            ),
                          },
                        }))
                      }
                      className="h-9 w-24 rounded-xl border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] px-2.5 text-sm outline-none"
                    />
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={handleTestJev}
                  disabled={jevTesting}
                  className="m3-state flex h-10 items-center gap-2 rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] px-4 text-sm font-medium"
                >
                  {jevTesting ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <CheckCircle2 size={16} />
                  )}
                  <span>测试 Jev 连接</span>
                </button>
                {jevStatus && (
                  <span
                    className={`text-sm ${
                      jevStatus.ok ? "text-[var(--md-sys-color-success)]" : "text-[var(--md-sys-color-error)]"
                    }`}
                  >
                    {jevStatus.text}
                  </span>
                )}
              </div>
            </div>
          )}

          {tab === "appearance" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                    Material 3 主题外观
                  </label>
                  <select
                    value={draft.ui.theme}
                    onChange={(e) =>
                      setDraft((prev) => ({
                        ...prev,
                        ui: { ...prev.ui, theme: e.target.value as ThemeMode },
                      }))
                    }
                    className={inputCls}
                  >
                    <option value="dark">深色（Material 3 Dark）</option>
                    <option value="light">浅色（Material 3 Light）</option>
                  </select>
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                    历史保留条数（0–100）
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={draft.history_limit}
                    onChange={(e) =>
                      setDraft((prev) => ({
                        ...prev,
                        history_limit: Math.max(
                          0,
                          Math.min(100, Number(e.target.value) || 0),
                        ),
                      }))
                    }
                    className={inputCls}
                  />
                </div>
              </div>

              <M3Switch
                checked={draft.ui.close_to_tray}
                onChange={(v) =>
                  setDraft((prev) => ({
                    ...prev,
                    ui: { ...prev.ui, close_to_tray: v },
                  }))
                }
                label="关闭窗口时最小化到系统托盘（无托盘环境自动降级为正常退出）"
              />

              {isWindows && (
                <M3Switch
                  checked={draft.ui.auto_start}
                  onChange={(v) =>
                    setDraft((prev) => ({
                      ...prev,
                      ui: { ...prev.ui, auto_start: v },
                    }))
                  }
                  label="开机自启（Windows 登录后自动启动）"
                />
              )}

              <div className="rounded-[20px] border border-[var(--md-sys-color-outline-variant)]/60 bg-[var(--md-sys-color-surface-container)] p-4">
                <div className="mb-3 text-sm font-medium">快捷键配置</div>
                <div className="grid grid-cols-2 gap-3.5 text-sm">
                  {(
                    [
                      ["translate", "翻译"],
                      ["screenshot", "截图翻译"],
                      ["extract_text", "提取文字"],
                      ["paste_image", "粘贴图片"],
                      ["swap_langs", "交换语种"],
                      ["copy_result", "复制译文"],
                    ] as const
                  ).map(([field, label]) => (
                    <div key={field}>
                      <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                        {label}
                      </label>
                      <input
                        type="text"
                        value={draft.ui.hotkeys[field]}
                        onChange={(e) =>
                          setDraft((prev) => ({
                            ...prev,
                            ui: {
                              ...prev.ui,
                              hotkeys: { ...prev.ui.hotkeys, [field]: e.target.value },
                            },
                          }))
                        }
                        className={`${inputCls} font-mono-editor`}
                      />
                    </div>
                  ))}
                  <div className="col-span-2">
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      全局呼出热键（{isWindows ? "Windows 全局生效" : "Linux Wayland 请在合成器配置绑定 ai-translator 启动命令"}）
                    </label>
                    <input
                      type="text"
                      value={draft.ui.hotkeys.summon}
                      disabled={!isWindows}
                      onChange={(e) =>
                        setDraft((prev) => ({
                          ...prev,
                          ui: {
                            ...prev.ui,
                            hotkeys: { ...prev.ui.hotkeys, summon: e.target.value },
                          },
                        }))
                      }
                      className={`${inputCls} font-mono-editor disabled:opacity-50`}
                    />
                  </div>
                  <div className="col-span-2">
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      划词 / 选区快翻小窗（{isWindows ? "Windows 全局生效" : "Linux Wayland 可绑定 ai-translator --quick"}）
                    </label>
                    <input
                      type="text"
                      value={draft.ui.hotkeys.quick_translate}
                      disabled={!isWindows}
                      onChange={(e) =>
                        setDraft((prev) => ({
                          ...prev,
                          ui: {
                            ...prev.ui,
                            hotkeys: { ...prev.ui.hotkeys, quick_translate: e.target.value },
                          },
                        }))
                      }
                      className={`${inputCls} font-mono-editor disabled:opacity-50`}
                    />
                  </div>
                </div>
              </div>

              <div className="rounded-[20px] border border-[var(--md-sys-color-outline-variant)]/60 bg-[var(--md-sys-color-surface-container)] p-4">
                <div className="mb-2 text-sm font-medium">配置备份与迁移（config.json）</div>
                <p className="mb-3 text-xs text-[var(--md-sys-color-on-surface-variant)]">
                  可导出当前完整配置（含服务商、场景、术语表、生词本）用于备份或跨设备迁移；导入后立即生效。
                </p>
                <div className="flex flex-wrap items-center gap-2.5">
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        const json = await api.exportConfigJson();
                        const blob = new Blob([json], { type: "application/json" });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = "ai-translator-config.json";
                        a.click();
                        URL.revokeObjectURL(url);
                        setCfgIoStatus({ text: "已导出配置 JSON", ok: true });
                      } catch (e) {
                        setCfgIoStatus({ text: String(e), ok: false });
                      }
                    }}
                    className="m3-state flex h-9 items-center gap-1.5 rounded-full bg-[var(--md-sys-color-secondary-container)] px-4 text-sm font-medium text-[var(--md-sys-color-on-secondary-container)]"
                  >
                    <Download size={15} />
                    <span>导出配置</span>
                  </button>

                  <label className="m3-state flex h-9 cursor-pointer items-center gap-1.5 rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] px-4 text-sm font-medium hover:bg-[var(--md-sys-color-surface-container-highest)]">
                    <Upload size={15} />
                    <span>导入配置…</span>
                    <input
                      type="file"
                      accept=".json,application/json"
                      className="hidden"
                      onChange={async (e) => {
                        const file = e.target.files?.[0];
                        e.target.value = "";
                        if (!file) return;
                        try {
                          const text = await file.text();
                          const imported = await api.importConfigJson(text);
                          setDraft(imported);
                          setSelectedPid(imported.active_profile_id);
                          const formatted = await api.formatGlossaryText(
                            imported.translation.glossary,
                          );
                          setGlossaryText(formatted);
                          setCfgIoStatus({
                            text: "配置已导入并应用（含历史与生词本）",
                            ok: true,
                          });
                        } catch (err) {
                          setCfgIoStatus({ text: String(err), ok: false });
                        }
                      }}
                    />
                  </label>
                </div>
                {cfgIoStatus && (
                  <div
                    className={`mt-2.5 rounded-xl px-3.5 py-2 text-xs ${
                      cfgIoStatus.ok
                        ? "bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-success)]"
                        : "bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)]"
                    }`}
                  >
                    {cfgIoStatus.text}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-[var(--md-sys-color-outline-variant)]/70 bg-[var(--md-sys-color-surface-container)] px-6 py-3.5">
          <button
            type="button"
            onClick={onClose}
            className="m3-state h-10 rounded-full px-5 text-sm font-medium text-[var(--md-sys-color-primary)] hover:bg-[var(--md-sys-color-primary)]/12"
          >
            取消
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={handleSave}
            className="m3-state h-10 rounded-full bg-[var(--md-sys-color-primary)] px-6 text-sm font-medium text-[var(--md-sys-color-on-primary)] hover:brightness-105 disabled:opacity-50"
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>

      {/* Model Catalog Modal */}
      {catalogOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setCatalogOpen(false);
          }}
        >
          <div
            className="flex h-[540px] w-full max-w-xl flex-col overflow-hidden rounded-[28px] border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)]"
            style={{ boxShadow: "var(--md-elevation-3)" }}
          >
            <div className="flex items-center justify-between border-b border-[var(--md-sys-color-outline-variant)]/70 bg-[var(--md-sys-color-surface-container)] px-5 py-3.5">
              <span className="text-base font-medium">
                选择候选模型 — {activeProfile.name}
              </span>
              <button
                type="button"
                onClick={() => setCatalogOpen(false)}
                className="m3-state flex h-9 w-9 items-center justify-center rounded-full hover:bg-[var(--md-sys-color-surface-container-highest)]"
              >
                <X size={18} />
              </button>
            </div>
            <div className="border-b border-[var(--md-sys-color-outline-variant)]/60 p-4">
              <div className="relative">
                <Search
                  size={17}
                  className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-[var(--md-sys-color-on-surface-variant)]"
                />
                <input
                  type="text"
                  value={catalogSearch}
                  onChange={(e) => setCatalogSearch(e.target.value)}
                  placeholder="搜索模型 ID…"
                  className="h-10 w-full rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] pr-4 pl-10 text-sm outline-none focus:border-[var(--md-sys-color-primary)]"
                />
              </div>
              {catalogLoading && (
                <div className="mt-2 flex items-center gap-2 text-xs text-[var(--md-sys-color-on-surface-variant)]">
                  <Loader2 size={14} className="animate-spin" />
                  <span>正在拉取服务商 /models…</span>
                </div>
              )}
              {catalogErr && (
                <div className="mt-2 text-xs text-[var(--md-sys-color-error)]">
                  {catalogErr}
                </div>
              )}
            </div>
            <div className="flex-1 space-y-1 overflow-y-auto p-3">
              {filteredCatalog.map((id) => {
                const checked = catalogChecked.has(id);
                return (
                  <label
                    key={id}
                    className="flex cursor-pointer items-center gap-3 rounded-full px-3.5 py-2 text-sm hover:bg-[var(--md-sys-color-surface-container-high)]"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        setCatalogChecked((prev) => {
                          const next = new Set(prev);
                          if (e.target.checked) next.add(id);
                          else next.delete(id);
                          return next;
                        });
                      }}
                      className="h-4 w-4 accent-[var(--md-sys-color-primary)]"
                    />
                    <span className="truncate font-mono-editor">{id}</span>
                  </label>
                );
              })}
              {filteredCatalog.length === 0 && !catalogLoading && (
                <div className="py-12 text-center text-sm text-[var(--md-sys-color-on-surface-variant)]">
                  无匹配模型
                </div>
              )}
            </div>
            <div className="flex items-center justify-between border-t border-[var(--md-sys-color-outline-variant)]/70 bg-[var(--md-sys-color-surface-container)] px-5 py-3">
              <span className="text-xs text-[var(--md-sys-color-on-surface-variant)]">
                已勾选 {catalogChecked.size} 个（每个服务商上限 50）
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setCatalogOpen(false)}
                  className="m3-state h-9 rounded-full px-4 text-sm font-medium text-[var(--md-sys-color-primary)] hover:bg-[var(--md-sys-color-primary)]/12"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={commitCatalog}
                  className="m3-state h-9 rounded-full bg-[var(--md-sys-color-primary)] px-5 text-sm font-medium text-[var(--md-sys-color-on-primary)]"
                >
                  加入候选
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Custom Scene Manager Modal */}
      {sceneModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setSceneModalOpen(false);
          }}
        >
          <div
            className="flex h-[480px] w-full max-w-xl flex-col overflow-hidden rounded-[28px] border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)]"
            style={{ boxShadow: "var(--md-elevation-3)" }}
          >
            <div className="flex items-center justify-between border-b border-[var(--md-sys-color-outline-variant)]/70 bg-[var(--md-sys-color-surface-container)] px-5 py-3.5">
              <span className="text-base font-medium">管理翻译场景</span>
              <button
                type="button"
                onClick={() => setSceneModalOpen(false)}
                className="m3-state flex h-9 w-9 items-center justify-center rounded-full hover:bg-[var(--md-sys-color-surface-container-highest)]"
              >
                <X size={18} />
              </button>
            </div>
            <div className="flex flex-1 flex-col gap-3.5 overflow-y-auto p-5">
              <div className="max-h-40 space-y-1 overflow-y-auto rounded-2xl border border-[var(--md-sys-color-outline-variant)]/60 bg-[var(--md-sys-color-surface-container)] p-2">
                {allScenes.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => setSelectedSceneId(s.id)}
                    className={`m3-state flex w-full items-center justify-between rounded-full px-3.5 py-1.5 text-left text-sm ${
                      selectedScene?.id === s.id
                        ? "bg-[var(--md-sys-color-primary-container)] font-medium text-[var(--md-sys-color-on-primary-container)]"
                        : "hover:bg-[var(--md-sys-color-surface-container-high)]"
                    }`}
                  >
                    <span>{s.label}</span>
                    {s.builtin && (
                      <span className="text-xs text-[var(--md-sys-color-on-surface-variant)]">
                        内置只读
                      </span>
                    )}
                  </button>
                ))}
              </div>
              {selectedScene && (
                <div className="space-y-3">
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      名称
                    </label>
                    <input
                      type="text"
                      disabled={selectedScene.builtin}
                      value={selectedScene.label}
                      onChange={(e) =>
                        updateCustomScene(selectedScene.id, { label: e.target.value })
                      }
                      className={`${inputCls} disabled:opacity-60`}
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                      提示词
                    </label>
                    <textarea
                      rows={4}
                      disabled={selectedScene.builtin}
                      value={selectedScene.prompt}
                      onChange={(e) =>
                        updateCustomScene(selectedScene.id, { prompt: e.target.value })
                      }
                      className="w-full rounded-2xl border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] p-3 text-sm outline-none disabled:opacity-60"
                    />
                  </div>
                </div>
              )}
            </div>
            <div className="flex items-center justify-between border-t border-[var(--md-sys-color-outline-variant)]/70 bg-[var(--md-sys-color-surface-container)] px-5 py-3">
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={addCustomScene}
                  className="m3-state h-9 rounded-full bg-[var(--md-sys-color-secondary-container)] px-4 text-sm font-medium text-[var(--md-sys-color-on-secondary-container)]"
                >
                  新增
                </button>
                <button
                  type="button"
                  disabled={!selectedScene || selectedScene.builtin}
                  onClick={() => selectedScene && deleteCustomScene(selectedScene.id)}
                  className="m3-state h-9 rounded-full bg-[var(--md-sys-color-error-container)] px-4 text-sm font-medium text-[var(--md-sys-color-on-error-container)] disabled:opacity-40"
                >
                  删除
                </button>
              </div>
              <button
                type="button"
                onClick={() => setSceneModalOpen(false)}
                className="m3-state h-9 rounded-full bg-[var(--md-sys-color-primary)] px-5 text-sm font-medium text-[var(--md-sys-color-on-primary)]"
              >
                完成
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
