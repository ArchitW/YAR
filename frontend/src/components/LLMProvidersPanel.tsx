import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Check,
  CheckCircle2,
  Cpu,
  Eye,
  EyeOff,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { LLMEndpoint } from "../types";
import { ModelsStatus } from "./ModelSettingsPanel";

interface Props {
  apiBase: string;
  modelsStatus: ModelsStatus | null;
  onModelsUpdated: (updated: ModelsStatus) => void;
}

const PROVIDERS = [
  { id: "local", label: "Local (Ollama)", baseUrl: "http://localhost:11434/v1", defaultModel: "llama3.2" },
  { id: "openrouter", label: "OpenRouter", baseUrl: "https://openrouter.ai/api/v1", defaultModel: "openai/gpt-4o-mini" },
  { id: "gemini", label: "Google Gemini", baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai", defaultModel: "gemini-2.5-flash" },
  { id: "qwen", label: "Qwen (DashScope)", baseUrl: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", defaultModel: "qwen-plus" },
  { id: "openai", label: "OpenAI", baseUrl: "https://api.openai.com/v1", defaultModel: "gpt-4o-mini" },
  { id: "lmstudio", label: "LM Studio / vLLM", baseUrl: "http://localhost:1234/v1", defaultModel: "" },
  { id: "custom", label: "Custom Endpoint", baseUrl: "", defaultModel: "" },
];

const inputClass =
  "w-full px-3 py-2 text-sm bg-white border border-slate-200 rounded-lg text-slate-800 placeholder:text-slate-400 transition-shadow focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 focus-visible:border-blue-400";
const primaryBtn =
  "inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 focus-visible:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none";
const ghostBtn =
  "inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 focus-visible:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none";

type FormState = {
  id: number | null;
  name: string;
  base_url: string;
  model: string;
  api_key: string;
  timeout: string;
  enabled: boolean;
};

const emptyForm: FormState = { id: null, name: "", base_url: "", model: "", api_key: "", timeout: "60", enabled: true };

export default function LLMProvidersPanel({ apiBase, modelsStatus, onModelsUpdated }: Props) {
  const [endpoints, setEndpoints] = useState<LLMEndpoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [showKey, setShowKey] = useState(false);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelListOpen, setModelListOpen] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${apiBase}/settings/llm-endpoints`);
      if (res.ok) setEndpoints(await res.json());
      else setEndpoints([]);
    } catch {
      setEndpoints([]);
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!feedback) return;
    const t = setTimeout(() => setFeedback(null), 4000);
    return () => clearTimeout(t);
  }, [feedback]);

  const refreshModels = async () => {
    try {
      const mRes = await fetch(`${apiBase}/chat/models`);
      if (mRes.ok) onModelsUpdated(await mRes.json());
    } catch {
      // ignore
    }
  };

  const openAdd = () => {
    setForm(emptyForm);
    setShowKey(false);
    setAvailableModels([]);
    setModelListOpen(false);
    setShowForm(true);
    setFeedback(null);
  };

  const openEdit = (ep: LLMEndpoint) => {
    setForm({
      id: ep.id,
      name: ep.name,
      base_url: ep.base_url,
      model: ep.model,
      api_key: "",
      timeout: ep.timeout || "60",
      enabled: ep.enabled,
    });
    setShowKey(false);
    setAvailableModels([]);
    setModelListOpen(false);
    setShowForm(true);
    setFeedback(null);
    // Best-effort: public model lists (e.g. OpenRouter) load without a key.
    fetchModels(ep.base_url, "");
  };

  // Fetch the model list for a base URL via the backend test endpoint.
  const fetchModels = async (baseUrl: string, apiKey: string) => {
    const url = baseUrl.trim();
    if (!url) return;
    setModelsLoading(true);
    try {
      const res = await fetch(`${apiBase}/chat/models/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base_url: url, model: "", api_key: apiKey.trim(), timeout: 8.0 }),
      });
      const data = await res.json();
      setAvailableModels(Array.isArray(data.models) ? data.models : []);
    } catch {
      setAvailableModels([]);
    } finally {
      setModelsLoading(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setFeedback(null);
    try {
      const res = await fetch(`${apiBase}/chat/models/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: form.base_url.trim(),
          model: form.model.trim(),
          api_key: form.api_key.trim(),
          timeout: 5.0,
        }),
      });
      const data = await res.json();
      setFeedback({
        type: data.ok ? "success" : "error",
        message: data.detail || (data.ok ? "Connection succeeded." : "Connection failed."),
      });
    } catch {
      setFeedback({ type: "error", message: "Could not reach backend to test connection." });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setFeedback(null);
    try {
      const editing = form.id != null;
      const body: Record<string, any> = {
        name: form.name.trim(),
        base_url: form.base_url.trim(),
        model: form.model.trim(),
        timeout: form.timeout.trim() || "60",
        enabled: form.enabled,
      };
      if (form.api_key.trim() !== "") body.api_key = form.api_key.trim();

      const res = await fetch(
        editing ? `${apiBase}/settings/llm-endpoints/${form.id}` : `${apiBase}/settings/llm-endpoints`,
        {
          method: editing ? "PATCH" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Failed with HTTP ${res.status}`);
      }
      await load();
      await refreshModels();
      setShowForm(false);
      setForm(emptyForm);
      setFeedback({ type: "success", message: editing ? "Endpoint updated." : "Endpoint added." });
    } catch (err: any) {
      setFeedback({ type: "error", message: err?.message || "Failed to save endpoint." });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (ep: LLMEndpoint) => {
    setBusyId(ep.id);
    setFeedback(null);
    try {
      const res = await fetch(`${apiBase}/settings/llm-endpoints/${ep.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await load();
      await refreshModels();
      setFeedback({ type: "success", message: `Deleted "${ep.name}".` });
    } catch {
      setFeedback({ type: "error", message: `Failed to delete "${ep.name}".` });
    } finally {
      setBusyId(null);
    }
  };

  const handleActivate = async (ep: LLMEndpoint) => {
    setBusyId(ep.id);
    setFeedback(null);
    try {
      const res = await fetch(`${apiBase}/settings/llm-endpoints/${ep.id}/activate`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await load();
      await refreshModels();
      setFeedback({ type: "success", message: `"${ep.name}" is now the active model.` });
    } catch {
      setFeedback({ type: "error", message: `Failed to activate "${ep.name}".` });
    } finally {
      setBusyId(null);
    }
  };

  const handleToggleEnabled = async (ep: LLMEndpoint) => {
    setBusyId(ep.id);
    try {
      const res = await fetch(`${apiBase}/settings/llm-endpoints/${ep.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !ep.enabled }),
      });
      if (res.ok) {
        await load();
        await refreshModels();
      }
    } catch {
      // ignore
    } finally {
      setBusyId(null);
    }
  };

  const suggestions = Array.from(new Set(modelsStatus?.local_models || []));
  const filteredModels = (
    form.model.trim()
      ? availableModels.filter((m) => m.toLowerCase().includes(form.model.trim().toLowerCase()))
      : availableModels
  ).slice(0, 300);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
            <Cpu className="w-4 h-4 text-blue-600" aria-hidden="true" />
            LLM Endpoints
          </h3>
          <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">
            Register multiple providers, then pick which one to use from the top bar.
          </p>
        </div>
        {!showForm && (
          <button type="button" onClick={openAdd} className={primaryBtn}>
            <Plus className="w-3.5 h-3.5" />
            <span>Add endpoint</span>
          </button>
        )}
      </div>

      {feedback && (
        <div
          role={feedback.type === "error" ? "alert" : "status"}
          className={cn(
            "p-3 rounded-lg text-xs flex items-start gap-2 border",
            feedback.type === "success"
              ? "bg-emerald-50 text-emerald-800 border-emerald-200"
              : "bg-rose-50 text-rose-800 border-rose-200"
          )}
        >
          {feedback.type === "success" ? (
            <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5 text-emerald-600" aria-hidden="true" />
          ) : (
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-rose-600" aria-hidden="true" />
          )}
          <span className="leading-snug break-words">{feedback.message}</span>
        </div>
      )}

      {/* Add / Edit form */}
      {showForm && (
        <div className="rounded-2xl border border-blue-200 bg-blue-50/30 p-4 space-y-3.5">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-semibold text-slate-800">
              {form.id != null ? "Edit endpoint" : "New endpoint"}
            </h4>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              aria-label="Cancel"
              className="p-1 rounded text-slate-400 hover:text-slate-700"
            >
              <X className="w-4 h-4" aria-hidden="true" />
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            <div>
              <label htmlFor="ep-preset" className="block text-xs font-medium text-slate-700 mb-1.5">
                Provider preset
              </label>
              <select
                id="ep-preset"
                value={PROVIDERS.find((p) => p.baseUrl === form.base_url)?.id || "custom"}
                onChange={(e) => {
                  const p = PROVIDERS.find((x) => x.id === e.target.value);
                  if (p && p.baseUrl) {
                    setForm((f) => ({
                      ...f,
                      base_url: p.baseUrl,
                      model: f.model || p.defaultModel,
                      name: f.name || (p.id === "custom" ? "" : p.label),
                    }));
                    setAvailableModels([]);
                    fetchModels(p.baseUrl, form.api_key);
                  }
                }}
                className={inputClass}
              >
                {PROVIDERS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="ep-name" className="block text-xs font-medium text-slate-700 mb-1.5">
                Display name
              </label>
              <input
                id="ep-name"
                type="text"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Local Llama, OpenRouter"
                className={inputClass}
              />
            </div>
          </div>

          <div>
            <label htmlFor="ep-url" className="block text-xs font-medium text-slate-700 mb-1.5">
              Endpoint Base URL
            </label>
            <input
              id="ep-url"
              type="url"
              value={form.base_url}
              onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
              placeholder="http://localhost:11434/v1"
              className={cn(inputClass, "font-mono")}
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label htmlFor="ep-model" className="block text-xs font-medium text-slate-700">
                Model
              </label>
              <button
                type="button"
                onClick={() => fetchModels(form.base_url, form.api_key)}
                disabled={modelsLoading || !form.base_url.trim()}
                className="inline-flex items-center gap-1 text-[11px] font-medium text-blue-600 hover:text-blue-700 disabled:opacity-50 disabled:pointer-events-none"
              >
                {modelsLoading ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <RefreshCw className="w-3 h-3" />
                )}
                <span>{modelsLoading ? "Loading…" : "Load models"}</span>
              </button>
            </div>

            <div className="relative">
              <input
                id="ep-model"
                type="text"
                role="combobox"
                aria-expanded={modelListOpen && availableModels.length > 0}
                aria-controls="ep-model-list"
                aria-autocomplete="list"
                autoComplete="off"
                value={form.model}
                onFocus={() => setModelListOpen(true)}
                onBlur={() => setTimeout(() => setModelListOpen(false), 120)}
                onChange={(e) => {
                  setForm((f) => ({ ...f, model: e.target.value }));
                  setModelListOpen(true);
                }}
                placeholder={availableModels.length > 0 ? "Search or type a model…" : "llama3.2"}
                className={cn(inputClass, "font-mono")}
              />
              {modelListOpen && availableModels.length > 0 && (
                <ul
                  id="ep-model-list"
                  role="listbox"
                  className="absolute z-20 mt-1 w-full max-h-60 overflow-y-auto bg-white border border-slate-200 rounded-lg shadow-lg py-1 text-xs"
                >
                  {filteredModels.length === 0 ? (
                    <li className="px-3 py-2 text-slate-400">No models match “{form.model}”</li>
                  ) : (
                    filteredModels.map((m) => (
                      <li
                        key={m}
                        role="option"
                        aria-selected={form.model === m}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          setForm((f) => ({ ...f, model: m }));
                          setModelListOpen(false);
                        }}
                        className={cn(
                          "px-3 py-1.5 font-mono truncate cursor-pointer hover:bg-blue-50",
                          form.model === m ? "bg-blue-50 text-blue-700" : "text-slate-700"
                        )}
                      >
                        {m}
                      </li>
                    ))
                  )}
                </ul>
              )}
            </div>
            {suggestions.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {suggestions.map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setForm((f) => ({ ...f, model: m }))}
                    className={cn(
                      "px-2 py-0.5 text-[11px] font-mono rounded border transition-colors",
                      form.model === m
                        ? "bg-blue-600 text-white border-blue-600"
                        : "bg-white text-slate-600 border-slate-200 hover:border-blue-300"
                    )}
                  >
                    {m}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            <div>
              <label htmlFor="ep-key" className="block text-xs font-medium text-slate-700 mb-1.5">
                API Key{" "}
                <span className="text-slate-400 font-normal">
                  {form.id != null ? "(leave blank to keep)" : "(optional for local)"}
                </span>
              </label>
              <div className="relative">
                <input
                  id="ep-key"
                  type={showKey ? "text" : "password"}
                  value={form.api_key}
                  onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
                  placeholder="sk-..."
                  className={cn(inputClass, "pr-10 font-mono")}
                />
                <button
                  type="button"
                  onClick={() => setShowKey(!showKey)}
                  aria-label={showKey ? "Hide API key" : "Show API key"}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                >
                  {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
            <div>
              <label htmlFor="ep-timeout" className="block text-xs font-medium text-slate-700 mb-1.5">
                Request Timeout (seconds)
              </label>
              <input
                id="ep-timeout"
                type="number"
                min={5}
                max={600}
                value={form.timeout}
                onChange={(e) => setForm((f) => ({ ...f, timeout: e.target.value }))}
                className={cn(inputClass, "font-mono tabular-nums")}
              />
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 pt-1">
            <button type="button" onClick={handleTest} disabled={testing || !form.base_url.trim()} className={ghostBtn}>
              {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              <span>Test</span>
            </button>
            <button type="button" onClick={() => setShowForm(false)} className={ghostBtn}>
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || !form.name.trim() || !form.base_url.trim() || !form.model.trim()}
              className={primaryBtn}
            >
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              <span>{form.id != null ? "Save changes" : "Add endpoint"}</span>
            </button>
          </div>
        </div>
      )}

      {/* Endpoint list */}
      {loading ? (
        <div className="space-y-2" aria-busy="true">
          <div className="h-16 rounded-xl bg-white border border-slate-200 animate-pulse" />
          <div className="h-16 rounded-xl bg-white border border-slate-200 animate-pulse" />
        </div>
      ) : endpoints.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center">
          <Cpu className="w-8 h-8 mx-auto text-slate-300 mb-2" aria-hidden="true" />
          <p className="text-sm font-medium text-slate-600">No LLM endpoints yet</p>
          <p className="text-xs text-slate-500 mt-1">Add a local model or a hosted provider to get started.</p>
        </div>
      ) : (
        <ul className="space-y-2">
          {endpoints.map((ep) => (
            <li
              key={ep.id}
              className={cn(
                "rounded-xl border bg-white p-3.5 flex items-center gap-3 transition-colors",
                ep.is_active && ep.enabled ? "border-blue-300 ring-1 ring-blue-200" : "border-slate-200",
                !ep.enabled && "opacity-60"
              )}
            >
              <span
                className={cn(
                  "inline-flex h-9 w-9 items-center justify-center rounded-lg shrink-0",
                  ep.is_active && ep.enabled ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-500"
                )}
              >
                <Cpu className="h-4 w-4" aria-hidden="true" />
              </span>

              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-800 truncate">{ep.name}</span>
                  {ep.is_active && ep.enabled && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-50 text-blue-700 ring-1 ring-blue-200 shrink-0">
                      Active
                    </span>
                  )}
                  {!ep.enabled && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-500 shrink-0">
                      Disabled
                    </span>
                  )}
                </div>
                <div className="text-[11px] text-slate-500 font-mono truncate">
                  {ep.model} · {ep.base_url}
                </div>
              </div>

              <div className="flex items-center gap-1 shrink-0">
                {!ep.is_active && ep.enabled && (
                  <button
                    type="button"
                    onClick={() => handleActivate(ep)}
                    disabled={busyId === ep.id}
                    className={ghostBtn}
                    title="Use this model"
                  >
                    {busyId === ep.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                    <span className="hidden sm:inline">Use</span>
                  </button>
                )}
                <button
                  type="button"
                  role="switch"
                  aria-checked={ep.enabled}
                  aria-label={ep.enabled ? `Disable ${ep.name}` : `Enable ${ep.name}`}
                  onClick={() => handleToggleEnabled(ep)}
                  disabled={busyId === ep.id}
                  className={cn(
                    "relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 focus-visible:ring-offset-2",
                    ep.enabled ? "bg-blue-600" : "bg-slate-300"
                  )}
                >
                  <span
                    className={cn(
                      "inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform",
                      ep.enabled ? "translate-x-[18px]" : "translate-x-0.5"
                    )}
                  />
                </button>
                <button
                  type="button"
                  onClick={() => openEdit(ep)}
                  aria-label={`Edit ${ep.name}`}
                  className="p-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70"
                >
                  <Pencil className="w-3.5 h-3.5" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(ep)}
                  disabled={busyId === ep.id}
                  aria-label={`Delete ${ep.name}`}
                  className="p-2 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-500/70 disabled:opacity-50"
                >
                  <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}