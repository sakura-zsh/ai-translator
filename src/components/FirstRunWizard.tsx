import { useState } from "react";
import { CheckCircle2, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { api } from "../lib/tauri";
import {
  newShortId,
  type ApiProtocol,
  type AppConfig,
  type LlmProfile,
  type ProviderTemplate,
} from "../lib/types";

interface FirstRunWizardProps {
  open: boolean;
  templates: ProviderTemplate[];
  config: AppConfig;
  onComplete: (nextConfig: AppConfig) => Promise<void>;
  onSkip: () => void;
}

export function FirstRunWizard({
  open,
  templates,
  config,
  onComplete,
  onSkip,
}: FirstRunWizardProps) {
  const initialTpl = templates[0];
  const [selectedId, setSelectedId] = useState(initialTpl?.id ?? "openai");
  const [name, setName] = useState(initialTpl?.name ?? "OpenAI");
  const [baseUrl, setBaseUrl] = useState(
    initialTpl?.base_url ?? "https://api.openai.com/v1",
  );
  const [apiKey, setApiKey] = useState("");
  const [apiProtocol, setApiProtocol] = useState<ApiProtocol>(
    initialTpl?.api_protocol ?? "chat_completions",
  );
  const [model, setModel] = useState(initialTpl?.text_model || "gpt-4o-mini");
  const [visionModel, setVisionModel] = useState(initialTpl?.vision_model || "");
  const [fetchedModels, setFetchedModels] = useState<string[]>([]);
  const [busyFetch, setBusyFetch] = useState(false);
  const [busyTest, setBusyTest] = useState(false);
  const [statusMsg, setStatusMsg] = useState("");
  const [statusOk, setStatusOk] = useState<boolean | null>(null);

  if (!open) return null;

  const activeTemplate = templates.find((t) => t.id === selectedId);

  const pickTemplate = (tpl: ProviderTemplate) => {
    setSelectedId(tpl.id);
    setName(tpl.name);
    setBaseUrl(tpl.base_url);
    setApiProtocol(tpl.api_protocol);
    setModel(tpl.text_model || "");
    setVisionModel(tpl.vision_model || "");
    setFetchedModels([]);
    setStatusMsg("");
    setStatusOk(null);
  };

  const buildDraftProfile = (): LlmProfile => {
    const existing = config.profiles[0];
    const cleanModel = model.trim() || "gpt-4o-mini";
    const candidates = Array.from(
      new Set([cleanModel, ...(visionModel.trim() ? [visionModel.trim()] : [])]),
    );
    return {
      ...existing,
      id: existing?.id || newShortId(),
      name: name.trim() || "OpenAI-compatible",
      base_url: baseUrl.trim(),
      api_key: apiKey.trim(),
      api_protocol: apiProtocol,
      model: cleanModel,
      models: candidates,
      vision_model: visionModel.trim() === cleanModel ? "" : visionModel.trim(),
      model_options: fetchedModels,
    };
  };

  const handleFetchModels = async () => {
    setBusyFetch(true);
    setStatusMsg("");
    setStatusOk(null);
    try {
      const ids = await api.fetchProfileModels(buildDraftProfile(), false);
      setFetchedModels(ids);
      if (ids.length > 0 && !ids.includes(model.trim())) {
        setModel(ids[0]);
      }
      setStatusMsg(`已获取 ${ids.length} 个模型`);
      setStatusOk(true);
    } catch (e) {
      setStatusMsg(String(e));
      setStatusOk(false);
    } finally {
      setBusyFetch(false);
    }
  };

  const handleTest = async () => {
    setBusyTest(true);
    setStatusMsg("");
    setStatusOk(null);
    try {
      const reply = await api.testProfileConnection(buildDraftProfile());
      setStatusMsg(`连接成功：${reply}`);
      setStatusOk(true);
    } catch (e) {
      setStatusMsg(String(e));
      setStatusOk(false);
    } finally {
      setBusyTest(false);
    }
  };

  const handleFinish = async () => {
    const draft = buildDraftProfile();
    const next: AppConfig = {
      ...config,
      active_profile_id: draft.id,
      profiles: [draft, ...config.profiles.slice(1)],
    };
    await onComplete(next);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4">
      <div
        className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-[28px] border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)]"
        style={{ boxShadow: "var(--md-elevation-3)" }}
      >
        <div className="flex items-center gap-3 border-b border-[var(--md-sys-color-outline-variant)]/70 bg-[var(--md-sys-color-surface-container)] px-6 py-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--md-sys-color-primary-container)] text-[var(--md-sys-color-on-primary-container)]">
            <Sparkles size={20} />
          </div>
          <div>
            <h2 className="text-lg font-medium">欢迎使用 AI Translator</h2>
            <p className="text-sm text-[var(--md-sys-color-on-surface-variant)]">
              选择一个服务商模板并填入 API Key，即可开始翻译。
            </p>
          </div>
        </div>

        <div className="grid flex-1 grid-cols-1 gap-5 overflow-y-auto p-6 sm:grid-cols-5">
          <div className="space-y-1.5 sm:col-span-2">
            <div className="mb-2 text-xs font-semibold tracking-wide text-[var(--md-sys-color-on-surface-variant)] uppercase">
              服务商模板
            </div>
            <div className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
              {templates.map((tpl) => (
                <button
                  key={tpl.id}
                  type="button"
                  onClick={() => pickTemplate(tpl)}
                  className={`m3-state w-full rounded-full px-4 py-2.5 text-left text-sm transition ${
                    tpl.id === selectedId
                      ? "bg-[var(--md-sys-color-secondary-container)] font-semibold text-[var(--md-sys-color-on-secondary-container)]"
                      : "bg-transparent text-[var(--md-sys-color-on-surface)] hover:bg-[var(--md-sys-color-surface-container-high)]"
                  }`}
                >
                  {tpl.name}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-3.5 sm:col-span-3">
            {activeTemplate?.hint && (
              <div className="rounded-2xl bg-[var(--md-sys-color-surface-container)] px-4 py-3 text-sm text-[var(--md-sys-color-on-surface-variant)]">
                {activeTemplate.hint}
              </div>
            )}

            <div>
              <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                名称
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="h-10 w-full rounded-xl border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] px-3.5 text-sm outline-none focus:border-[var(--md-sys-color-primary)]"
              />
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                Base URL
              </label>
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                className="h-10 w-full rounded-xl border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] px-3.5 font-mono-editor text-sm outline-none focus:border-[var(--md-sys-color-primary)]"
              />
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                API Key {activeTemplate && !activeTemplate.key_required ? "（本地服务可留空）" : ""}
              </label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                className="h-10 w-full rounded-xl border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] px-3.5 font-mono-editor text-sm outline-none focus:border-[var(--md-sys-color-primary)]"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                  协议
                </label>
                <select
                  value={apiProtocol}
                  onChange={(e) => setApiProtocol(e.target.value as ApiProtocol)}
                  className="h-10 w-full rounded-xl border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] px-3 text-sm outline-none focus:border-[var(--md-sys-color-primary)]"
                >
                  <option value="chat_completions">Chat Completions</option>
                  <option value="responses">Responses API</option>
                </select>
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--md-sys-color-on-surface-variant)]">
                  默认模型
                </label>
                <div className="flex gap-1.5">
                  <input
                    type="text"
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    list="wizard-model-options"
                    placeholder="模型 ID"
                    className="h-10 min-w-0 flex-1 rounded-xl border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] px-3 font-mono-editor text-sm outline-none focus:border-[var(--md-sys-color-primary)]"
                  />
                  <datalist id="wizard-model-options">
                    {fetchedModels.map((m) => (
                      <option key={m} value={m} />
                    ))}
                  </datalist>
                  <button
                    type="button"
                    onClick={handleFetchModels}
                    disabled={busyFetch}
                    title="拉取服务商模型列表"
                    className="m3-state flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] hover:bg-[var(--md-sys-color-surface-container-highest)] disabled:opacity-50"
                  >
                    {busyFetch ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <RefreshCw size={16} />
                    )}
                  </button>
                </div>
              </div>
            </div>

            {statusMsg && (
              <div
                className={`rounded-2xl px-4 py-2.5 text-sm ${
                  statusOk
                    ? "bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-success)]"
                    : "bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)]"
                }`}
              >
                {statusMsg}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-[var(--md-sys-color-outline-variant)]/70 bg-[var(--md-sys-color-surface-container)] px-6 py-3.5">
          <button
            type="button"
            onClick={handleTest}
            disabled={busyTest}
            className="m3-state flex h-10 items-center gap-2 rounded-full border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-high)] px-4 text-sm font-medium hover:bg-[var(--md-sys-color-surface-container-highest)] disabled:opacity-50"
          >
            {busyTest ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}
            <span>测试连接</span>
          </button>

          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={onSkip}
              className="m3-state h-10 rounded-full px-4 text-sm font-medium text-[var(--md-sys-color-primary)] hover:bg-[var(--md-sys-color-primary)]/12"
            >
              跳过
            </button>
            <button
              type="button"
              onClick={handleFinish}
              className="m3-state h-10 rounded-full bg-[var(--md-sys-color-primary)] px-5 text-sm font-medium text-[var(--md-sys-color-on-primary)] hover:brightness-105"
            >
              保存并开始
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
