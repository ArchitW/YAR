import { useEffect, useState } from "react";
import { CheckCircle2, AlertCircle, Cpu, Eye, EyeOff, Loader2, RefreshCw, X } from "lucide-react";

export interface ModelsStatus {
  configured_provider: string | null;
  configured_model: string | null;
  base_url: string | null;
  timeout: string;
  has_api_key: boolean;
  ollama_online: boolean;
  local_models: string[];
  providers?: {
    id: number;
    name: string;
    base_url: string;
    model: string;
    timeout: string;
    enabled: boolean;
    is_active: boolean;
    has_api_key: boolean;
  }[];
  active_provider_id?: number | null;
}

interface ModelSettingsPanelProps {
  isOpen: boolean;
  onClose: () => void;
  apiBase: string;
  modelsStatus: ModelsStatus | null;
  onSaved: (updated: ModelsStatus) => void;
}

const PROVIDERS = [
  {
    id: "local",
    label: "Local (Ollama)",
    baseUrl: "http://localhost:11434/v1",
    defaultModel: "llama3.2",
  },
  {
    id: "gemini",
    label: "Google Gemini",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai",
    defaultModel: "gemini-2.5-flash",
  },
  {
    id: "qwen",
    label: "Qwen (DashScope)",
    baseUrl: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    defaultModel: "qwen-plus",
  },
  {
    id: "openai",
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    defaultModel: "gpt-4o-mini",
  },
  {
    id: "lmstudio",
    label: "LM Studio / vLLM",
    baseUrl: "http://localhost:1234/v1",
    defaultModel: "",
  },
  {
    id: "custom",
    label: "Custom Endpoint",
    baseUrl: "",
    defaultModel: "",
  },
];

function detectProviderId(url: string): string {
  const normalized = url.trim().replace(/\/+$/, "");
  const match = PROVIDERS.find((p) => p.baseUrl && p.baseUrl === normalized);
  return match ? match.id : normalized ? "custom" : "local";
}

export default function ModelSettingsPanel({
  isOpen,
  onClose,
  apiBase,
  modelsStatus,
  onSaved,
}: ModelSettingsPanelProps) {
  const [providerId, setProviderId] = useState("local");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [timeout, setTimeoutVal] = useState("60");
  const [showKey, setShowKey] = useState(false);

  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);
  const [discoveredModels, setDiscoveredModels] = useState<string[]>([]);

  useEffect(() => {
    if (isOpen && modelsStatus) {
      const url = modelsStatus.base_url || "http://localhost:11434/v1";
      setProviderId(detectProviderId(url));
      setBaseUrl(url);
      setModel(modelsStatus.configured_model || "");
      setTimeoutVal(modelsStatus.timeout || "60");
      setApiKey("");
      setFeedback(null);
      setDiscoveredModels(modelsStatus.local_models || []);
    }
  }, [isOpen, modelsStatus]);

  const handleProviderChange = (nextId: string) => {
    setProviderId(nextId);
    setFeedback(null);
    const selected = PROVIDERS.find((p) => p.id === nextId);
    if (selected && selected.baseUrl) {
      setBaseUrl(selected.baseUrl);
      if (selected.defaultModel) {
        setModel(selected.defaultModel);
      }
    }
  };

  if (!isOpen) return null;

  const handleTest = async () => {
    setTesting(true);
    setFeedback(null);
    try {
      const res = await fetch(`${apiBase}/chat/models/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: baseUrl.trim(),
          model: model.trim(),
          api_key: apiKey.trim(),
          timeout: 5.0,
        }),
      });
      const data = await res.json();
      if (data.models && Array.isArray(data.models) && data.models.length > 0) {
        setDiscoveredModels(data.models);
      }
      setFeedback({
        type: data.ok ? "success" : "error",
        message: data.detail || (data.ok ? "Connection succeeded." : "Connection failed."),
      });
    } catch {
      setFeedback({
        type: "error",
        message: "Could not reach YAR backend to test endpoint.",
      });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setFeedback(null);
    try {
      const payload: Record<string, string> = {
        base_url: baseUrl.trim(),
        model: model.trim(),
        timeout: timeout.trim() || "60",
      };
      if (apiKey.trim() !== "") {
        payload.api_key = apiKey.trim();
      }
      const res = await fetch(`${apiBase}/chat/models/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Failed with HTTP ${res.status}`);
      }
      const updated: ModelsStatus = await res.json();
      onSaved(updated);
      setApiKey("");
      setFeedback({
        type: "success",
        message: "Endpoint configuration saved and applied.",
      });
    } catch (err: any) {
      setFeedback({
        type: "error",
        message: err?.message || "Failed to save configuration.",
      });
    } finally {
      setSaving(false);
    }
  };

  const allSuggestions = Array.from(
    new Set([...(modelsStatus?.local_models || []), ...discoveredModels])
  );

  return (
    <aside className="w-80 sm:w-96 border-l bg-white flex flex-col h-full shadow-lg z-20 animate-in slide-in-from-right-4 duration-150">
      <div className="h-14 px-4 border-b flex items-center justify-between bg-slate-50/70">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-blue-600" />
          <h3 className="font-semibold text-sm text-slate-800">
            Model & Provider Settings
          </h3>
        </div>
        <button
          onClick={onClose}
          aria-label="Close model settings"
          className="p-1 rounded text-slate-400 hover:text-slate-600 hover:bg-slate-200/60"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <form onSubmit={handleSave} className="flex-1 overflow-y-auto p-4 space-y-4">
        <p className="text-xs text-slate-500 leading-relaxed">
          Connect any OpenAI-compatible endpoint (Ollama, OpenAI, vLLM, or LM Studio). Changes apply immediately without restarting.
        </p>

        {/* Provider Dropdown */}
        <div>
          <label htmlFor="llm-provider" className="block text-xs font-medium text-slate-700 mb-1">
            Provider
          </label>
          <select
            id="llm-provider"
            value={providerId}
            onChange={(e) => handleProviderChange(e.target.value)}
            className="w-full px-3 py-2 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white"
          >
            {PROVIDERS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </div>

        {/* Base URL */}
        <div>
          <label htmlFor="llm-base-url" className="block text-xs font-medium text-slate-700 mb-1">
            Endpoint Base URL
          </label>
          <input
            id="llm-base-url"
            type="url"
            value={baseUrl}
            onChange={(e) => {
              const val = e.target.value;
              setBaseUrl(val);
              setProviderId(detectProviderId(val));
            }}
            placeholder="http://localhost:11434/v1"
            className="w-full px-3 py-2 text-xs font-mono bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white"
          />
        </div>

        {/* Model Name */}
        <div>
          <label htmlFor="llm-model" className="block text-xs font-medium text-slate-700 mb-1">
            Model Name
          </label>
          <input
            id="llm-model"
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="llama3.2"
            className="w-full px-3 py-2 text-xs font-mono bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white"
          />

          {allSuggestions.length > 0 && (
            <div className="mt-2">
              <span className="text-[11px] text-slate-400 block mb-1">
                Available models:
              </span>
              <div className="flex flex-wrap gap-1">
                {allSuggestions.map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setModel(m)}
                    className={`px-2 py-0.5 text-[11px] font-mono rounded border transition-colors ${
                      model === m
                        ? "bg-blue-600 text-white border-blue-600"
                        : "bg-white text-slate-600 border-slate-200 hover:border-blue-300"
                    }`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* API Key */}
        <div>
          <label htmlFor="llm-api-key" className="block text-xs font-medium text-slate-700 mb-1">
            API Key{" "}
            <span className="text-slate-400 font-normal">
              {modelsStatus?.has_api_key ? "(saved — leave blank to keep)" : "(optional for local)"}
            </span>
          </label>
          <div className="relative">
            <input
              id="llm-api-key"
              type={showKey ? "text" : "password"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={modelsStatus?.has_api_key ? "••••••••••••" : "sk-..."}
              className="w-full pr-9 pl-3 py-2 text-xs font-mono bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white"
            />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              aria-label={showKey ? "Hide API key" : "Show API key"}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
            >
              {showKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
            </button>
          </div>
        </div>

        {/* Timeout */}
        <div>
          <label htmlFor="llm-timeout" className="block text-xs font-medium text-slate-700 mb-1">
            Request Timeout (seconds)
          </label>
          <input
            id="llm-timeout"
            type="number"
            min={5}
            max={600}
            value={timeout}
            onChange={(e) => setTimeoutVal(e.target.value)}
            className="w-28 px-3 py-1.5 text-xs font-mono tabular-nums bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white"
          />
        </div>

        {/* Inline Feedback Banner */}
        {feedback && (
          <div
            className={`p-3 rounded-lg text-xs flex items-start gap-2 border ${
              feedback.type === "success"
                ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                : "bg-rose-50 text-rose-800 border-rose-200"
            }`}
          >
            {feedback.type === "success" ? (
              <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5 text-emerald-600" />
            ) : (
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-rose-600" />
            )}
            <span className="leading-relaxed break-words">{feedback.message}</span>
          </div>
        )}

        {/* Actions */}
        <div className="pt-2 flex items-center gap-2 border-t border-slate-100">
          <button
            type="button"
            onClick={handleTest}
            disabled={testing || !baseUrl.trim()}
            className="flex-1 px-3 py-2 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-50 flex items-center justify-center gap-1.5 transition-colors"
          >
            {testing ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <RefreshCw className="w-3.5 h-3.5" />
            )}
            <span>Test Connection</span>
          </button>

          <button
            type="submit"
            disabled={saving}
            className="flex-1 px-3 py-2 text-xs font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-1.5 transition-colors shadow-sm"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            <span>Save & Apply</span>
          </button>
        </div>
      </form>
    </aside>
  );
}
