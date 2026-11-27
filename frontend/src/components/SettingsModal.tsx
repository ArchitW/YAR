import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertCircle,
  Brain,
  CheckCircle2,
  Cpu,
  Eye,
  EyeOff,
  Files,
  Globe,
  HardDrive,
  Loader2,
  RefreshCw,
  Settings,
  Shield,
  Sparkles,
  X,
} from "lucide-react";
import { ModelsStatus } from "./ModelSettingsPanel";
import DocumentList from "./DocumentList";
import { DocumentItem } from "../types";

export type SettingsTab = "models" | "retrieval" | "memory" | "security" | "system" | "master";

interface FullSettings {
  llm_base_url: string;
  llm_model: string;
  llm_timeout: string;
  has_api_key: boolean;
  ollama_base_url: string;
  ollama_autodiscover: boolean;
  ollama_timeout: number;
  query_rewrite_enabled: boolean;
  hyde_enabled: boolean;
  web_search_enabled: boolean;
  web_search_confidence_threshold: number;
  searxng_base_url: string;
  auth_enabled: boolean;
  has_jwt_secret: boolean;
  compute_device: string;
  gpu_name?: string | null;
  database_type: string;
  qdrant_mode: string;
  qdrant_location: string;
  upload_dir: string;
  upload_file_count: number;
  upload_total_bytes: number;
}

interface HealthData {
  status: string;
  services: Record<string, string>;
}

interface ConnectorItem {
  id: number;
  name: string;
  query: string;
  status: string;
  last_synced_at?: string | null;
}

interface AuditItem {
  id: number;
  trace_id: string;
  event_type: string;
  status: string;
  summary: string;
  created_at?: string | null;
}

interface DreamStatus {
  total_memories: number;
  active_nodes: number;
  invalidated_nodes: number;
  total_edges: number;
  counts_by_type: Record<string, number>;
}

interface SettingsModalProps {
  isOpen: boolean;
  initialTab: SettingsTab;
  onClose: () => void;
  apiBase: string;
  workspaceId: number | null;
  modelsStatus: ModelsStatus | null;
  onModelsUpdated: (updated: ModelsStatus) => void;
}

const PROVIDERS = [
  { id: "local", label: "Local (Ollama)", baseUrl: "http://localhost:11434/v1", defaultModel: "llama3.2" },
  { id: "gemini", label: "Google Gemini", baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai", defaultModel: "gemini-2.5-flash" },
  { id: "qwen", label: "Qwen (DashScope)", baseUrl: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", defaultModel: "qwen-plus" },
  { id: "openai", label: "OpenAI", baseUrl: "https://api.openai.com/v1", defaultModel: "gpt-4o-mini" },
  { id: "lmstudio", label: "LM Studio / vLLM", baseUrl: "http://localhost:1234/v1", defaultModel: "" },
  { id: "custom", label: "Custom Endpoint", baseUrl: "", defaultModel: "" },
];

const TABS: { id: SettingsTab; label: string; icon: any }[] = [
  { id: "models", label: "Models & Providers", icon: Cpu },
  { id: "master", label: "Master Knowledge", icon: Files },
  { id: "retrieval", label: "Retrieval & Search", icon: Globe },
  { id: "memory", label: "Memory & Dreaming", icon: Brain },
  { id: "security", label: "Security & Audit", icon: Shield },
  { id: "system", label: "System & Storage", icon: HardDrive },
];

function detectProviderId(url: string): string {
  const normalized = url.trim().replace(/\/+$/, "");
  const match = PROVIDERS.find((p) => p.baseUrl && p.baseUrl === normalized);
  return match ? match.id : normalized ? "custom" : "local";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function SettingsModal({
  isOpen,
  initialTab,
  onClose,
  apiBase,
  workspaceId,
  modelsStatus,
  onModelsUpdated,
}: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>(initialTab);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  // Settings form state
  const [providerId, setProviderId] = useState("local");
  const [llmBaseUrl, setLlmBaseUrl] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [llmTimeout, setLlmTimeout] = useState("60");
  const [hasApiKey, setHasApiKey] = useState(false);

  const [ollamaBaseUrl, setOllamaBaseUrl] = useState("http://localhost:11434");
  const [ollamaAutodiscover, setOllamaAutodiscover] = useState(true);
  const [ollamaTimeout, setOllamaTimeout] = useState(3);

  const [queryRewrite, setQueryRewrite] = useState(true);
  const [hydeEnabled, setHydeEnabled] = useState(false);
  const [webSearchEnabled, setWebSearchEnabled] = useState(true);
  const [webThreshold, setWebThreshold] = useState(0.25);
  const [searxngUrl, setSearxngUrl] = useState("http://localhost:8080");

  const [authEnabled, setAuthEnabled] = useState(false);
  const [hasJwtSecret, setHasJwtSecret] = useState(false);
  const [newJwtSecret, setNewJwtSecret] = useState("");

  const [systemInfo, setSystemInfo] = useState<FullSettings | null>(null);
  const [health, setHealth] = useState<HealthData | null>(null);
  const [connectors, setConnectors] = useState<ConnectorItem[]>([]);
  const [syncingId, setSyncingId] = useState<number | null>(null);
  const [dreamStatus, setDreamStatus] = useState<DreamStatus | null>(null);
  const [dreaming, setDreaming] = useState(false);
  const [auditLogs, setAuditLogs] = useState<AuditItem[]>([]);
  const [discoveredModels, setDiscoveredModels] = useState<string[]>([]);
  const [masterDocs, setMasterDocs] = useState<DocumentItem[]>([]);
  const [masterLoading, setMasterLoading] = useState(false);

  const loadMasterDocs = useCallback(async () => {
    setMasterLoading(true);
    try {
      const res = await fetch(`${apiBase}/documents?master=true`);
      if (res.ok) setMasterDocs(await res.json());
      else setMasterDocs([]);
    } catch {
      setMasterDocs([]);
    } finally {
      setMasterLoading(false);
    }
  }, [apiBase]);

  const deleteMasterDoc = async (doc: DocumentItem) => {
    try {
      await fetch(`${apiBase}/documents/${doc.id}`, { method: "DELETE" });
      setMasterDocs((prev) => prev.filter((d) => d.id !== doc.id));
      setFeedback({ type: "success", message: `Removed "${doc.name}" from the Master Knowledge Base.` });
    } catch {
      setFeedback({ type: "error", message: `Failed to delete "${doc.name}".` });
    }
  };

  useEffect(() => {
    if (isOpen && activeTab === "master") loadMasterDocs();
  }, [isOpen, activeTab, loadMasterDocs]);

  useEffect(() => {
    if (isOpen) {
      setActiveTab(initialTab);
      setFeedback(null);
    }
  }, [isOpen, initialTab]);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [sRes, hRes, cRes, aRes] = await Promise.all([
        fetch(`${apiBase}/settings`),
        fetch(`${apiBase}/health`),
        workspaceId ? fetch(`${apiBase}/connectors?workspace_id=${workspaceId}`) : Promise.resolve(null),
        fetch(`${apiBase}/audit-logs?limit=15`),
      ]);

      if (sRes.ok) {
        const s: FullSettings = await sRes.json();
        setSystemInfo(s);
        const url = s.llm_base_url || "http://localhost:11434/v1";
        setProviderId(detectProviderId(url));
        setLlmBaseUrl(url);
        setLlmModel(s.llm_model || "");
        setLlmTimeout(s.llm_timeout || "60");
        setHasApiKey(s.has_api_key);
        setLlmApiKey("");
        setOllamaBaseUrl(s.ollama_base_url || "http://localhost:11434");
        setOllamaAutodiscover(s.ollama_autodiscover);
        setOllamaTimeout(s.ollama_timeout);
        setQueryRewrite(s.query_rewrite_enabled);
        setHydeEnabled(s.hyde_enabled);
        setWebSearchEnabled(s.web_search_enabled);
        setWebThreshold(s.web_search_confidence_threshold);
        setSearxngUrl(s.searxng_base_url || "http://localhost:8080");
        setAuthEnabled(s.auth_enabled);
        setHasJwtSecret(s.has_jwt_secret);
        setNewJwtSecret("");
      }
      if (hRes.ok) setHealth(await hRes.json());
      if (cRes && cRes.ok) setConnectors(await cRes.json());
      if (aRes.ok) {
        const data = await aRes.json();
        setAuditLogs(data.items || []);
      }
      if (workspaceId) {
        const dRes = await fetch(`${apiBase}/memory/dream/status?workspace_id=${workspaceId}`);
        if (dRes.ok) setDreamStatus(await dRes.json());
      }
    } catch {
      setFeedback({ type: "error", message: "Failed to load settings from backend." });
    } finally {
      setLoading(false);
    }
  }, [apiBase, workspaceId]);

  useEffect(() => {
    if (isOpen) {
      loadAll();
      setDiscoveredModels(modelsStatus?.local_models || []);
    }
  }, [isOpen, loadAll, modelsStatus]);

  if (!isOpen) return null;

  const handleSaveSettings = async (patch: Record<string, any>, successMsg = "Settings saved and applied.") => {
    setSaving(true);
    setFeedback(null);
    try {
      const res = await fetch(`${apiBase}/settings`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Failed with HTTP ${res.status}`);
      }
      const updated: FullSettings = await res.json();
      setSystemInfo(updated);
      setHasApiKey(updated.has_api_key);
      setHasJwtSecret(updated.has_jwt_secret);
      setLlmApiKey("");
      setNewJwtSecret("");
      setFeedback({ type: "success", message: successMsg });

      const mRes = await fetch(`${apiBase}/chat/models`);
      if (mRes.ok) onModelsUpdated(await mRes.json());
    } catch (err: any) {
      setFeedback({ type: "error", message: err?.message || "Failed to save settings." });
    } finally {
      setSaving(false);
    }
  };

  const handleTestConnection = async () => {
    setTesting(true);
    setFeedback(null);
    try {
      const res = await fetch(`${apiBase}/chat/models/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: llmBaseUrl.trim(),
          model: llmModel.trim(),
          api_key: llmApiKey.trim(),
          timeout: 5.0,
        }),
      });
      const data = await res.json();
      if (data.models?.length) setDiscoveredModels(data.models);
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

  const handleSyncConnector = async (id: number) => {
    setSyncingId(id);
    try {
      const res = await fetch(`${apiBase}/connectors/${id}/sync`, { method: "POST" });
      if (res.ok && workspaceId) {
        const cRes = await fetch(`${apiBase}/connectors?workspace_id=${workspaceId}`);
        if (cRes.ok) setConnectors(await cRes.json());
        setFeedback({ type: "success", message: "Connector sync completed." });
      }
    } catch {
      setFeedback({ type: "error", message: "Connector sync failed." });
    } finally {
      setSyncingId(null);
    }
  };

  const handleTriggerDream = async () => {
    if (!workspaceId) return;
    setDreaming(true);
    setFeedback(null);
    try {
      const res = await fetch(`${apiBase}/memory/dream?workspace_id=${workspaceId}`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const dRes = await fetch(`${apiBase}/memory/dream/status?workspace_id=${workspaceId}`);
      if (dRes.ok) setDreamStatus(await dRes.json());
      setFeedback({ type: "success", message: "NREM & REM memory consolidation completed." });
    } catch {
      setFeedback({ type: "error", message: "Failed to run memory dream cycle." });
    } finally {
      setDreaming(false);
    }
  };

  const allSuggestions = Array.from(new Set([...(modelsStatus?.local_models || []), ...discoveredModels]));

  return (
    <div className="fixed inset-0 z-50 bg-white flex items-stretch justify-center">
      <div className="w-full max-w-6xl h-full flex flex-col overflow-hidden border-x border-slate-200">
        {/* Modal Header */}
        <div className="h-14 px-5 border-b flex items-center justify-between bg-slate-50/80 shrink-0">
          <div className="flex items-center gap-2.5">
            <Settings className="w-4 h-4 text-blue-600" />
            <h2 className="font-semibold text-sm text-slate-800">YAR Settings</h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close settings"
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200/60"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body: Left Tabs + Right Content */}
        <div className="flex-1 flex min-h-0">
          <nav className="w-52 border-r bg-slate-50/50 p-3 space-y-1 shrink-0">
            {TABS.map((tab) => {
              const Icon = tab.icon;
              const active = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => {
                    setActiveTab(tab.id);
                    setFeedback(null);
                  }}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors text-left ${
                    active
                      ? "bg-blue-50 text-blue-700 border border-blue-200/70"
                      : "text-slate-600 hover:bg-slate-100"
                  }`}
                >
                  <Icon className="w-3.5 h-3.5 shrink-0" />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </nav>

          <div className="flex-1 overflow-y-auto p-6 space-y-5">
            {loading && !systemInfo ? (
              <div className="flex items-center justify-center py-12 text-xs text-slate-500 gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Loading settings...</span>
              </div>
            ) : (
              <>
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
                    <span className="break-words">{feedback.message}</span>
                  </div>
                )}

                {/* TAB 1: MODELS */}
                {activeTab === "models" && (
                  <div className="space-y-4">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-800">LLM Endpoint & Provider</h3>
                      <p className="text-xs text-slate-500 mt-0.5">
                        Connect any OpenAI-compatible provider or local router. Applies immediately.
                      </p>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div>
                        <label htmlFor="settings-provider" className="block text-xs font-medium text-slate-700 mb-1">
                          Provider
                        </label>
                        <select
                          id="settings-provider"
                          value={providerId}
                          onChange={(e) => {
                            const id = e.target.value;
                            setProviderId(id);
                            const p = PROVIDERS.find((x) => x.id === id);
                            if (p?.baseUrl) {
                              setLlmBaseUrl(p.baseUrl);
                              if (p.defaultModel) setLlmModel(p.defaultModel);
                            }
                          }}
                          className="w-full px-3 py-2 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                          {PROVIDERS.map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.label}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label htmlFor="settings-timeout" className="block text-xs font-medium text-slate-700 mb-1">
                          Request Timeout (seconds)
                        </label>
                        <input
                          id="settings-timeout"
                          type="number"
                          min={5}
                          max={600}
                          value={llmTimeout}
                          onChange={(e) => setLlmTimeout(e.target.value)}
                          className="w-full px-3 py-2 text-xs font-mono tabular-nums bg-slate-50 border border-slate-200 rounded-lg"
                        />
                      </div>
                    </div>

                    <div>
                      <label htmlFor="settings-base-url" className="block text-xs font-medium text-slate-700 mb-1">
                        Endpoint Base URL
                      </label>
                      <input
                        id="settings-base-url"
                        type="url"
                        value={llmBaseUrl}
                        onChange={(e) => {
                          setLlmBaseUrl(e.target.value);
                          setProviderId(detectProviderId(e.target.value));
                        }}
                        placeholder="http://localhost:11434/v1"
                        className="w-full px-3 py-2 text-xs font-mono bg-slate-50 border border-slate-200 rounded-lg"
                      />
                    </div>

                    <div>
                      <label htmlFor="settings-model" className="block text-xs font-medium text-slate-700 mb-1">
                        Model Name
                      </label>
                      <input
                        id="settings-model"
                        type="text"
                        value={llmModel}
                        onChange={(e) => setLlmModel(e.target.value)}
                        placeholder="llama3.2"
                        className="w-full px-3 py-2 text-xs font-mono bg-slate-50 border border-slate-200 rounded-lg"
                      />
                      {allSuggestions.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {allSuggestions.map((m) => (
                            <button
                              key={m}
                              type="button"
                              onClick={() => setLlmModel(m)}
                              className={`px-2 py-0.5 text-[11px] font-mono rounded border ${
                                llmModel === m
                                  ? "bg-blue-600 text-white border-blue-600"
                                  : "bg-white text-slate-600 border-slate-200 hover:border-blue-300"
                              }`}
                            >
                              {m}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>

                    <div>
                      <label htmlFor="settings-api-key" className="block text-xs font-medium text-slate-700 mb-1">
                        API Key{" "}
                        <span className="text-slate-400 font-normal">
                          {hasApiKey ? "(saved — leave blank to keep)" : "(optional for local)"}
                        </span>
                      </label>
                      <div className="relative">
                        <input
                          id="settings-api-key"
                          type={showKey ? "text" : "password"}
                          value={llmApiKey}
                          onChange={(e) => setLlmApiKey(e.target.value)}
                          placeholder={hasApiKey ? "••••••••••••" : "sk-..."}
                          className="w-full pr-9 pl-3 py-2 text-xs font-mono bg-slate-50 border border-slate-200 rounded-lg"
                        />
                        <button
                          type="button"
                          onClick={() => setShowKey(!showKey)}
                          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                        >
                          {showKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                        </button>
                      </div>
                    </div>

                    <div className="pt-3 border-t border-slate-100 space-y-3">
                      <h4 className="text-xs font-semibold text-slate-700">Local Ollama Autodiscovery</h4>
                      <label className="flex items-center gap-2 text-xs text-slate-700 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={ollamaAutodiscover}
                          onChange={(e) => setOllamaAutodiscover(e.target.checked)}
                          className="rounded border-slate-300 text-blue-600"
                        />
                        <span>Automatically probe local Ollama daemon for installed models</span>
                      </label>
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div className="sm:col-span-2">
                          <input
                            type="url"
                            value={ollamaBaseUrl}
                            onChange={(e) => setOllamaBaseUrl(e.target.value)}
                            placeholder="http://localhost:11434"
                            className="w-full px-3 py-1.5 text-xs font-mono bg-slate-50 border border-slate-200 rounded-lg"
                          />
                        </div>
                        <input
                          type="number"
                          step="0.5"
                          min={0.5}
                          max={30}
                          value={ollamaTimeout}
                          onChange={(e) => setOllamaTimeout(Number(e.target.value))}
                          className="w-full px-3 py-1.5 text-xs font-mono tabular-nums bg-slate-50 border border-slate-200 rounded-lg"
                        />
                      </div>
                    </div>

                    <div className="flex items-center justify-end gap-2 pt-3 border-t">
                      <button
                        type="button"
                        onClick={handleTestConnection}
                        disabled={testing || !llmBaseUrl.trim()}
                        className="px-3.5 py-2 text-xs font-medium rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-50 disabled:opacity-50 flex items-center gap-1.5"
                      >
                        {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                        <span>Test Connection</span>
                      </button>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={() =>
                          handleSaveSettings({
                            llm_base_url: llmBaseUrl,
                            llm_model: llmModel,
                            llm_api_key: llmApiKey || undefined,
                            llm_timeout: llmTimeout,
                            ollama_base_url: ollamaBaseUrl,
                            ollama_autodiscover: ollamaAutodiscover,
                            ollama_timeout: ollamaTimeout,
                          })
                        }
                        className="px-4 py-2 text-xs font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5"
                      >
                        {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                        <span>Save Models</span>
                      </button>
                    </div>
                  </div>
                )}

                {/* TAB 2: RETRIEVAL & WEB SEARCH */}
                {/* TAB: MASTER KNOWLEDGE */}
                {activeTab === "master" && (
                  <div className="space-y-4">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-800">Master Knowledge Base</h3>
                      <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                        Documents here are shared across <span className="font-medium">every</span> workspace.
                        Upload with “Also add to Master Knowledge Base” checked, or manage the shared set below.
                      </p>
                    </div>

                    <div className="p-4 rounded-xl border border-blue-100 bg-blue-50/40 flex items-start gap-3">
                      <Files className="w-5 h-5 text-blue-600 shrink-0" />
                      <div className="text-xs text-slate-600">
                        <div className="font-medium text-slate-800">
                          {masterDocs.length} master document(s)
                        </div>
                        <div className="mt-0.5">
                          Searchable from any workspace, in addition to that workspace’s own files.
                        </div>
                      </div>
                    </div>

                    <DocumentList
                      documents={masterDocs}
                      isLoading={masterLoading}
                      onRefresh={loadMasterDocs}
                      workspaceName="Master Knowledge Base"
                      onDelete={deleteMasterDoc}
                    />
                  </div>
                )}

                {/* TAB 2: RETRIEVAL */}
                {activeTab === "retrieval" && (
                  <div className="space-y-5">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-800">Retrieval & Agentic Web Search</h3>
                      <p className="text-xs text-slate-500 mt-0.5">
                        Tune query rewriting, HyDE expansion, and automatic SearXNG fallback.
                      </p>
                    </div>

                    <div className="space-y-3">
                      <label className="flex items-start gap-2.5 text-xs cursor-pointer p-3 rounded-lg border border-slate-200 bg-slate-50/50">
                        <input
                          type="checkbox"
                          checked={queryRewrite}
                          onChange={(e) => setQueryRewrite(e.target.checked)}
                          className="mt-0.5 rounded border-slate-300 text-blue-600"
                        />
                        <div>
                          <div className="font-medium text-slate-800">Conversational Query Rewriting</div>
                          <div className="text-slate-500 mt-0.5">Resolves pronouns using the last 4 chat turns before vector search.</div>
                        </div>
                      </label>

                      <label className="flex items-start gap-2.5 text-xs cursor-pointer p-3 rounded-lg border border-slate-200 bg-slate-50/50">
                        <input
                          type="checkbox"
                          checked={hydeEnabled}
                          onChange={(e) => setHydeEnabled(e.target.checked)}
                          className="mt-0.5 rounded border-slate-300 text-blue-600"
                        />
                        <div>
                          <div className="font-medium text-slate-800">HyDE (Hypothetical Document Embeddings)</div>
                          <div className="text-slate-500 mt-0.5">Generates a synthetic passage to bridge vocabulary gaps (uses extra LLM call).</div>
                        </div>
                      </label>

                      <label className="flex items-start gap-2.5 text-xs cursor-pointer p-3 rounded-lg border border-slate-200 bg-slate-50/50">
                        <input
                          type="checkbox"
                          checked={webSearchEnabled}
                          onChange={(e) => setWebSearchEnabled(e.target.checked)}
                          className="mt-0.5 rounded border-slate-300 text-blue-600"
                        />
                        <div>
                          <div className="font-medium text-slate-800">Autonomous Web Search Fallback</div>
                          <div className="text-slate-500 mt-0.5">Queries SearXNG when local retrieval confidence falls below threshold.</div>
                        </div>
                      </label>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-xs font-medium text-slate-700 mb-1">
                          Web Fallback Threshold ({webThreshold.toFixed(2)})
                        </label>
                        <input
                          type="range"
                          min={0}
                          max={1}
                          step={0.05}
                          value={webThreshold}
                          onChange={(e) => setWebThreshold(Number(e.target.value))}
                          className="w-full"
                        />
                      </div>
                      <div>
                        <label htmlFor="settings-searxng" className="block text-xs font-medium text-slate-700 mb-1">
                          SearXNG Base URL
                        </label>
                        <input
                          id="settings-searxng"
                          type="url"
                          value={searxngUrl}
                          onChange={(e) => setSearxngUrl(e.target.value)}
                          className="w-full px-3 py-1.5 text-xs font-mono bg-slate-50 border border-slate-200 rounded-lg"
                        />
                      </div>
                    </div>

                    {connectors.length > 0 && (
                      <div className="pt-3 border-t space-y-2">
                        <h4 className="text-xs font-semibold text-slate-700">Workspace Web Connectors</h4>
                        <div className="space-y-1.5">
                          {connectors.map((c) => (
                            <div key={c.id} className="flex items-center justify-between p-2.5 rounded-lg border border-slate-200 text-xs">
                              <div>
                                <div className="font-medium text-slate-800">{c.name}</div>
                                <div className="text-[11px] text-slate-500 font-mono">{c.query}</div>
                              </div>
                              <button
                                type="button"
                                onClick={() => handleSyncConnector(c.id)}
                                disabled={syncingId === c.id}
                                className="px-2.5 py-1 rounded border border-slate-200 hover:bg-slate-50 text-[11px] font-medium flex items-center gap-1"
                              >
                                {syncingId === c.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                                <span>Sync</span>
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="flex justify-end pt-3 border-t">
                      <button
                        type="button"
                        disabled={saving}
                        onClick={() =>
                          handleSaveSettings({
                            query_rewrite_enabled: queryRewrite,
                            hyde_enabled: hydeEnabled,
                            web_search_enabled: webSearchEnabled,
                            web_search_confidence_threshold: webThreshold,
                            searxng_base_url: searxngUrl,
                          })
                        }
                        className="px-4 py-2 text-xs font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                      >
                        Save Retrieval
                      </button>
                    </div>
                  </div>
                )}

                {/* TAB 3: MEMORY & DREAMING */}
                {activeTab === "memory" && (
                  <div className="space-y-5">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-800">Cognitive Memory & Sleep Consolidation</h3>
                      <p className="text-xs text-slate-500 mt-0.5">
                        Inspect episodic/entity graph health and run NREM pruning + REM associative dreaming.
                      </p>
                    </div>

                    {dreamStatus ? (
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                        <div className="p-3 rounded-xl border bg-slate-50/70">
                          <div className="text-[11px] text-slate-500">Total Memories</div>
                          <div className="text-lg font-semibold font-mono tabular-nums text-slate-800">{dreamStatus.total_memories}</div>
                        </div>
                        <div className="p-3 rounded-xl border bg-slate-50/70">
                          <div className="text-[11px] text-slate-500">Active Nodes</div>
                          <div className="text-lg font-semibold font-mono tabular-nums text-emerald-700">{dreamStatus.active_nodes}</div>
                        </div>
                        <div className="p-3 rounded-xl border bg-slate-50/70">
                          <div className="text-[11px] text-slate-500">Pruned Nodes</div>
                          <div className="text-lg font-semibold font-mono tabular-nums text-slate-600">{dreamStatus.invalidated_nodes}</div>
                        </div>
                        <div className="p-3 rounded-xl border bg-slate-50/70">
                          <div className="text-[11px] text-slate-500">Graph Edges</div>
                          <div className="text-lg font-semibold font-mono tabular-nums text-blue-700">{dreamStatus.total_edges}</div>
                        </div>
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500">Select a workspace to view memory metrics.</p>
                    )}

                    <div className="p-4 rounded-xl border border-slate-200 bg-slate-50/60 flex items-center justify-between gap-4">
                      <div>
                        <div className="text-xs font-semibold text-slate-800">On-Demand Sleep Cycle (NREM + REM)</div>
                        <div className="text-xs text-slate-500 mt-0.5">
                          Deduplicates noisy memories, resolves contradictions, and synthesizes cross-document dream insights.
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={handleTriggerDream}
                        disabled={dreaming || !workspaceId}
                        className="px-3.5 py-2 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5 shrink-0"
                      >
                        {dreaming ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                        <span>Run Dream Cycle</span>
                      </button>
                    </div>
                  </div>
                )}

                {/* TAB 4: SECURITY & AUDIT */}
                {activeTab === "security" && (
                  <div className="space-y-5">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-800">Authentication & Audit Trail</h3>
                      <p className="text-xs text-slate-500 mt-0.5">
                        Configure JWT authentication and review recent system audit events.
                      </p>
                    </div>

                    <div className="p-4 rounded-xl border border-slate-200 space-y-3">
                      <label className="flex items-center gap-2 text-xs font-medium text-slate-800 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={authEnabled}
                          onChange={(e) => setAuthEnabled(e.target.checked)}
                          className="rounded border-slate-300 text-blue-600"
                        />
                        <span>Require JWT Authentication (`AUTH_ENABLED`)</span>
                      </label>

                      <div className="flex items-center gap-2 text-xs text-slate-600">
                        <span>JWT Secret:</span>
                        <span className={`px-2 py-0.5 rounded font-mono text-[11px] ${hasJwtSecret ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
                          {hasJwtSecret ? "Configured" : "Not set"}
                        </span>
                      </div>

                      <div className="flex items-center gap-2">
                        <input
                          type="password"
                          value={newJwtSecret}
                          onChange={(e) => setNewJwtSecret(e.target.value)}
                          placeholder="Set new JWT secret (leave blank to keep)"
                          className="flex-1 px-3 py-1.5 text-xs font-mono bg-slate-50 border border-slate-200 rounded-lg"
                        />
                        <button
                          type="button"
                          disabled={saving}
                          onClick={() => handleSaveSettings({ generate_jwt_secret: true }, "Generated and saved new JWT secret.")}
                          className="px-3 py-1.5 text-xs rounded-lg border border-slate-200 hover:bg-slate-50"
                        >
                          Generate Secret
                        </button>
                        <button
                          type="button"
                          disabled={saving}
                          onClick={() =>
                            handleSaveSettings({
                              auth_enabled: authEnabled,
                              jwt_secret: newJwtSecret || undefined,
                            })
                          }
                          className="px-3.5 py-1.5 text-xs font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700"
                        >
                          Save Auth
                        </button>
                      </div>
                    </div>

                    <div className="space-y-2">
                      <h4 className="text-xs font-semibold text-slate-700">Recent Audit Log (Last 15)</h4>
                      <div className="border rounded-xl overflow-hidden">
                        <div className="max-h-56 overflow-y-auto divide-y divide-slate-100 text-[11px]">
                          {auditLogs.length === 0 ? (
                            <div className="p-4 text-center text-slate-400">No audit events recorded yet.</div>
                          ) : (
                            auditLogs.map((log) => (
                              <div key={log.id} className="p-2.5 flex items-center justify-between gap-3 hover:bg-slate-50">
                                <div className="min-w-0">
                                  <div className="font-medium text-slate-800 truncate">{log.summary}</div>
                                  <div className="text-slate-400 font-mono">
                                    {log.event_type} · trace:{log.trace_id.slice(0, 8)}
                                  </div>
                                </div>
                                <span className={`px-1.5 py-0.5 rounded font-mono shrink-0 ${log.status === "success" ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"}`}>
                                  {log.status}
                                </span>
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* TAB 5: SYSTEM & STORAGE */}
                {activeTab === "system" && systemInfo && (
                  <div className="space-y-5">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-800">System Health, Compute & Storage</h3>
                      <p className="text-xs text-slate-500 mt-0.5">
                        Live runtime diagnostics for compute device, databases, and uploaded files.
                      </p>
                    </div>

                    {/* Service Health */}
                    {health && (
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        {Object.entries(health.services).map(([svc, state]) => {
                          const ok = state === "ok";
                          return (
                            <div key={svc} className="p-3 rounded-xl border bg-slate-50/70">
                              <div className="flex items-center justify-between">
                                <span className="text-xs font-medium text-slate-700 capitalize">{svc}</span>
                                <span className={`px-2 py-0.5 rounded text-[10px] font-mono ${ok ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
                                  {ok ? "OK" : "OFFLINE"}
                                </span>
                              </div>
                              {!ok && (
                                <div className="text-[11px] text-slate-500 mt-1 truncate" title={state}>
                                  {state}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Compute & Storage */}
                    <div className="border rounded-xl divide-y text-xs">
                      <div className="p-3 flex items-center justify-between">
                        <span className="text-slate-500 flex items-center gap-1.5">
                          <Activity className="w-3.5 h-3.5" /> Compute Device
                        </span>
                        <span className="font-mono text-slate-800">
                          {systemInfo.compute_device.toUpperCase()}
                          {systemInfo.gpu_name ? ` (${systemInfo.gpu_name})` : ""}
                        </span>
                      </div>
                      <div className="p-3 flex items-center justify-between">
                        <span className="text-slate-500">Embedding / Reranker</span>
                        <span className="font-mono text-slate-800">BAAI/bge-m3 · BAAI/bge-reranker-base</span>
                      </div>
                      <div className="p-3 flex items-center justify-between">
                        <span className="text-slate-500">Database</span>
                        <span className="font-mono text-slate-800 uppercase">{systemInfo.database_type}</span>
                      </div>
                      <div className="p-3 flex items-center justify-between gap-4">
                        <span className="text-slate-500 shrink-0">Qdrant ({systemInfo.qdrant_mode})</span>
                        <span className="font-mono text-slate-800 truncate">{systemInfo.qdrant_location}</span>
                      </div>
                      <div className="p-3 flex items-center justify-between gap-4">
                        <span className="text-slate-500 shrink-0">Uploads ({systemInfo.upload_file_count} files · {formatBytes(systemInfo.upload_total_bytes)})</span>
                        <span className="font-mono text-slate-800 truncate">{systemInfo.upload_dir}</span>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
