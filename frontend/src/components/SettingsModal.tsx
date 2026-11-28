import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Brain,
  CheckCircle2,
  Cpu,
  Files,
  Globe,
  HardDrive,
  Loader2,
  RefreshCw,
  Settings,
  Shield,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ModelsStatus } from "./ModelSettingsPanel";
import LLMProvidersPanel from "./LLMProvidersPanel";
import DocumentList from "./DocumentList";
import DocumentDropzone from "./DocumentDropzone";
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
  embedding_model: string;
  reranker_model: string;
  rerank_enabled: boolean;
  rerank_top_k: number;
  hf_offline: boolean;
  async_ingest: boolean;
  router_enabled: boolean;
  router_base_url: string;
  router_model: string;
  router_timeout: number;
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

const TABS: { id: SettingsTab; label: string; icon: any }[] = [
  { id: "models", label: "Models & Providers", icon: Cpu },
  { id: "master", label: "Master Knowledge", icon: Files },
  { id: "retrieval", label: "Retrieval & Search", icon: Globe },
  { id: "memory", label: "Memory & Dreaming", icon: Brain },
  { id: "security", label: "Security & Audit", icon: Shield },
  { id: "system", label: "System & Storage", icon: HardDrive },
];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/* ---------- Presentational primitives ---------- */

const inputClass =
  "w-full px-3 py-2 text-sm bg-white border border-slate-200 rounded-lg text-slate-800 placeholder:text-slate-400 transition-shadow focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 focus-visible:border-blue-400";

function Field({
  label,
  htmlFor,
  hint,
  children,
  className,
}: {
  label: string;
  htmlFor?: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <label htmlFor={htmlFor} className="block text-xs font-medium text-slate-700 mb-1.5">
        {label}
      </label>
      {children}
      {hint && <p className="mt-1.5 text-[11px] leading-snug text-slate-500">{hint}</p>}
    </div>
  );
}

function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 focus-visible:ring-offset-2",
        checked ? "bg-blue-600" : "bg-slate-300"
      )}
    >
      <span
        className={cn(
          "inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform",
          checked ? "translate-x-[18px]" : "translate-x-0.5"
        )}
      />
    </button>
  );
}

function ToggleRow({
  checked,
  onChange,
  title,
  description,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  title: string;
  description: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4 p-3.5 rounded-xl border border-slate-200 bg-white hover:border-slate-300 transition-colors">
      <div className="min-w-0">
        <div className="text-sm font-medium text-slate-800">{title}</div>
        <div className="text-xs text-slate-500 mt-0.5 leading-snug">{description}</div>
      </div>
      <Switch checked={checked} onChange={onChange} label={title} />
    </div>
  );
}

function SectionCard({
  title,
  description,
  icon: Icon,
  children,
  footer,
}: {
  title: string;
  description?: string;
  icon?: any;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <section className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
      <header className="flex items-start gap-3 px-5 pt-5 pb-4">
        {Icon && (
          <span className="mt-0.5 inline-flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50 text-blue-600 ring-1 ring-blue-100 shrink-0">
            <Icon className="h-4 w-4" aria-hidden="true" />
          </span>
        )}
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
          {description && <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{description}</p>}
        </div>
      </header>
      <div className="px-5 pb-5 space-y-4">{children}</div>
      {footer && (
        <footer className="flex items-center justify-end gap-2 px-5 py-3.5 bg-slate-50/70 border-t border-slate-100">
          {footer}
        </footer>
      )}
    </section>
  );
}

function StatCard({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="p-3.5 rounded-xl border border-slate-200 bg-slate-50/60">
      <div className="text-[11px] font-medium text-slate-500">{label}</div>
      <div className={cn("text-xl font-semibold font-mono tabular-nums mt-1", tone)}>{value}</div>
    </div>
  );
}

const primaryBtn =
  "inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 focus-visible:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none";
const ghostBtn =
  "inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 focus-visible:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none";

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
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const [ollamaBaseUrl, setOllamaBaseUrl] = useState("http://localhost:11434");
  const [ollamaAutodiscover, setOllamaAutodiscover] = useState(true);
  const [ollamaTimeout, setOllamaTimeout] = useState(3);
  const [embModel, setEmbModel] = useState("BAAI/bge-small-en-v1.5");
  const [rrModel, setRrModel] = useState("cross-encoder/ettin-reranker-17m-v1");
  const [rerankEnabled, setRerankEnabled] = useState(false);
  const [rerankTopK, setRerankTopK] = useState(10);
  const [hfOffline, setHfOffline] = useState(true);
  const [asyncIngest, setAsyncIngest] = useState(false);
  const [routerEnabled, setRouterEnabled] = useState(false);
  const [routerBaseUrl, setRouterBaseUrl] = useState("http://127.0.0.1:8008");
  const [routerModel, setRouterModel] = useState("kev-latest");
  const [routerTimeout, setRouterTimeout] = useState(5);
  const [reindexing, setReindexing] = useState(false);
  const [reindexProgress, setReindexProgress] = useState<{ done: number; total: number } | null>(null);

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
  const [masterDocs, setMasterDocs] = useState<DocumentItem[]>([]);
  const [masterLoading, setMasterLoading] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);

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

  useEffect(() => {
    if (!feedback) return;
    const t = setTimeout(() => setFeedback(null), 4000);
    return () => clearTimeout(t);
  }, [feedback]);

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
        setOllamaBaseUrl(s.ollama_base_url || "http://localhost:11434");
        setOllamaAutodiscover(s.ollama_autodiscover);
        setOllamaTimeout(s.ollama_timeout);
        setEmbModel(s.embedding_model || "BAAI/bge-small-en-v1.5");
        setRrModel(s.reranker_model || "cross-encoder/ettin-reranker-17m-v1");
        setRerankEnabled(s.rerank_enabled);
        setRerankTopK(s.rerank_top_k);
        setHfOffline(s.hf_offline);
        setAsyncIngest(s.async_ingest);
        setRouterEnabled(s.router_enabled);
        setRouterBaseUrl(s.router_base_url || "http://127.0.0.1:8008");
        setRouterModel(s.router_model || "kev-latest");
        setRouterTimeout(s.router_timeout);
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
    if (isOpen) loadAll();
  }, [isOpen, loadAll]);

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
      setHasJwtSecret(updated.has_jwt_secret);
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

  const handleReindexAll = async () => {
    setReindexing(true);
    setReindexProgress(null);
    setFeedback(null);
    try {
      const res = await fetch(`${apiBase}/settings/reindex-all`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      for (let i = 0; i < 600; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        const s = await fetch(`${apiBase}/settings/reindex-status`);
        if (s.ok) {
          const st = await s.json();
          setReindexProgress({ done: st.done, total: st.total });
          if (!st.running) {
            setReindexing(false);
            setFeedback({ type: "success", message: `Reindexed ${st.done} document(s).` });
            return;
          }
        }
      }
      setReindexing(false);
      setFeedback({ type: "success", message: "Reindex still running in the background." });
    } catch {
      setReindexing(false);
      setFeedback({ type: "error", message: "Failed to start reindex." });
    }
  };

  const handleResetEverything = async () => {
    setResetting(true);
    setFeedback(null);
    try {
      const res = await fetch(`${apiBase}/settings/reset`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setFeedback({ type: "success", message: "Reset complete. Reloading…" });
      setTimeout(() => window.location.assign("/"), 800);
    } catch {
      setResetting(false);
      setConfirmReset(false);
      setFeedback({ type: "error", message: "Failed to reset. Please try again." });
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-100 flex items-stretch justify-center">
      <div className="w-full h-full flex flex-col overflow-hidden bg-slate-50 border-x border-slate-200 shadow-xl">
        {/* Header */}
        <header className="h-16 px-5 border-b border-slate-200 bg-white flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-blue-600 text-white shadow-sm">
              <Settings className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <h2 className="text-sm font-semibold text-slate-900 leading-tight">Settings</h2>
              <p className="text-[11px] text-slate-500 leading-tight">Configure YAR models, retrieval, and system</p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close settings"
            className="p-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </header>

        {/* Body: Sidebar + Content */}
        <div className="flex-1 flex min-h-0">
          <nav
            aria-label="Settings sections"
            className="w-60 border-r border-slate-200 bg-white p-3 space-y-1 shrink-0 overflow-y-auto"
          >
            <div className="px-3 pt-1 pb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              Configuration
            </div>
            {TABS.map((tab) => {
              const Icon = tab.icon;
              const active = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  aria-current={active ? "page" : undefined}
                  onClick={() => {
                    setActiveTab(tab.id);
                    setFeedback(null);
                  }}
                  className={cn(
                    "w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70",
                    active
                      ? "bg-blue-50 text-blue-700 ring-1 ring-blue-200/70"
                      : "text-slate-600 hover:bg-slate-100"
                  )}
                >
                  <Icon className="w-4 h-4 shrink-0" aria-hidden="true" />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </nav>

          <div className="flex-1 overflow-y-auto">
            <div className="max-w-5xl mx-auto p-6 lg:p-8 space-y-6">
              {loading && !systemInfo ? (
                <div className="space-y-4" aria-busy="true" aria-live="polite">
                  <div className="h-28 rounded-2xl bg-white border border-slate-200 animate-pulse" />
                  <div className="h-40 rounded-2xl bg-white border border-slate-200 animate-pulse" />
                  <span className="sr-only">Loading settings…</span>
                </div>
              ) : (
                <>
                  {/* TAB: MODELS */}
                  {activeTab === "models" && (
                    <div className="space-y-6">
                      <LLMProvidersPanel
                        apiBase={apiBase}
                        modelsStatus={modelsStatus}
                        onModelsUpdated={onModelsUpdated}
                      />

                      <SectionCard
                        icon={Cpu}
                        title="Embedding & Reranker Models"
                        description="Small, fast models by default. Changing the embedding model rebuilds the vector index — you'll need to reindex documents."
                        footer={
                          <button
                            type="button"
                            disabled={saving}
                            onClick={() =>
                              handleSaveSettings(
                                { embedding_model: embModel, reranker_model: rrModel },
                                "Model settings saved. Reindex documents if you changed the embedding model."
                              )
                            }
                            className={primaryBtn}
                          >
                            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                            <span>Save Models</span>
                          </button>
                        }
                      >
                        <Field
                          label="Embedding Model"
                          htmlFor="emb-model"
                          hint="384-dim small models are fast but English-only (512 tokens). Use bge-m3 for multilingual / 8k context."
                        >
                          <input
                            id="emb-model"
                            list="emb-presets"
                            type="text"
                            value={embModel}
                            onChange={(e) => setEmbModel(e.target.value)}
                            className={cn(inputClass, "font-mono")}
                          />
                          <datalist id="emb-presets">
                            {[
                              "BAAI/bge-small-en-v1.5",
                              "BAAI/bge-m3",
                              "Snowflake/snowflake-arctic-embed-xs",
                              "sentence-transformers/all-MiniLM-L6-v2",
                              "Alibaba-NLP/gte-multilingual-base",
                            ].map((m) => (
                              <option key={m} value={m} />
                            ))}
                          </datalist>
                        </Field>
                        <Field
                          label="Reranker Model"
                          htmlFor="rr-model"
                          hint="Cross-encoder used to re-rank retrieved candidates. Smaller = faster."
                        >
                          <input
                            id="rr-model"
                            list="rr-presets"
                            type="text"
                            value={rrModel}
                            onChange={(e) => setRrModel(e.target.value)}
                            className={cn(inputClass, "font-mono")}
                          />
                          <datalist id="rr-presets">
                            {[
                              "cross-encoder/ettin-reranker-17m-v1",
                              "cross-encoder/ms-marco-MiniLM-L-6-v2",
                              "BAAI/bge-reranker-base",
                              "jinaai/jina-reranker-v1-tiny-en",
                              "Horizon-Labs/multilingual-reranker-small",
                            ].map((m) => (
                              <option key={m} value={m} />
                            ))}
                          </datalist>
                        </Field>
                      </SectionCard>

                      <SectionCard
                        icon={RefreshCw}
                        title="Reindex Documents"
                        description="Rebuild the vector index for every document. Required after changing the embedding model."
                        footer={
                          <button
                            type="button"
                            onClick={handleReindexAll}
                            disabled={reindexing}
                            className={primaryBtn}
                          >
                            {reindexing ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <RefreshCw className="w-3.5 h-3.5" />
                            )}
                            <span>{reindexing ? "Reindexing…" : "Reindex all"}</span>
                          </button>
                        }
                      >
                        {reindexProgress && (
                          <div>
                            <div className="flex justify-between text-[11px] text-slate-500 mb-1">
                              <span>
                                {reindexProgress.done} / {reindexProgress.total} documents
                              </span>
                              <span className="font-mono">
                                {reindexProgress.total
                                  ? Math.round((reindexProgress.done / reindexProgress.total) * 100)
                                  : 0}
                                %
                              </span>
                            </div>
                            <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                              <div
                                className="h-full bg-blue-600 transition-all"
                                style={{
                                  width: `${
                                    reindexProgress.total
                                      ? (reindexProgress.done / reindexProgress.total) * 100
                                      : 0
                                  }%`,
                                }}
                              />
                            </div>
                          </div>
                        )}
                        <p className="text-[11px] text-slate-500 leading-snug">
                          Changing the embedding model downloads it (if not cached) on save, then reindex here.
                        </p>
                      </SectionCard>

                      <SectionCard
                        icon={Cpu}
                        title="Local Ollama Autodiscovery"
                        description="Probe a local Ollama daemon for installed models when no endpoint is active."
                        footer={
                          <button
                            type="button"
                            disabled={saving}
                            onClick={() =>
                              handleSaveSettings(
                                {
                                  ollama_base_url: ollamaBaseUrl,
                                  ollama_autodiscover: ollamaAutodiscover,
                                  ollama_timeout: ollamaTimeout,
                                },
                                "Ollama autodiscovery settings saved."
                              )
                            }
                            className={primaryBtn}
                          >
                            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                            <span>Save Ollama Settings</span>
                          </button>
                        }
                      >
                        <ToggleRow
                          checked={ollamaAutodiscover}
                          onChange={setOllamaAutodiscover}
                          title="Probe local Ollama daemon"
                          description="Automatically discover installed models from the local daemon."
                        />
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                          <Field label="Ollama Base URL" className="sm:col-span-2" htmlFor="ollama-url">
                            <input
                              id="ollama-url"
                              type="url"
                              value={ollamaBaseUrl}
                              onChange={(e) => setOllamaBaseUrl(e.target.value)}
                              placeholder="http://localhost:11434"
                              className={cn(inputClass, "font-mono")}
                            />
                          </Field>
                          <Field label="Timeout (s)" htmlFor="ollama-timeout">
                            <input
                              id="ollama-timeout"
                              type="number"
                              step="0.5"
                              min={0.5}
                              max={30}
                              value={ollamaTimeout}
                              onChange={(e) => setOllamaTimeout(Number(e.target.value))}
                              className={cn(inputClass, "font-mono tabular-nums")}
                            />
                          </Field>
                        </div>
                      </SectionCard>
                    </div>
                  )}

                  {/* TAB: MASTER KNOWLEDGE */}
                  {activeTab === "master" && (
                    <SectionCard
                      icon={Files}
                      title="Master Knowledge Base"
                      description="Documents here are shared across every workspace."
                    >
                      <div className="p-4 rounded-xl border border-blue-100 bg-blue-50/50 flex items-start gap-3">
                        <Files className="w-5 h-5 text-blue-600 shrink-0" aria-hidden="true" />
                        <div className="text-xs text-slate-600">
                          <div className="font-medium text-slate-800">{masterDocs.length} master document(s)</div>
                          <div className="mt-0.5">
                            Searchable from any workspace, in addition to that workspace’s own files. Upload below, or
                            edit the extracted text of any document and reindex it.
                          </div>
                        </div>
                      </div>

                      {workspaceId != null && (
                        <div>
                          <h4 className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
                            Add to Master Knowledge
                          </h4>
                          <DocumentDropzone
                            workspaceId={workspaceId}
                            indexToMaster
                            onUploadSuccess={loadMasterDocs}
                          />
                        </div>
                      )}

                      <DocumentList
                        documents={masterDocs}
                        isLoading={masterLoading}
                        onRefresh={loadMasterDocs}
                        workspaceName="Master Knowledge Base"
                        onDelete={deleteMasterDoc}
                        apiBase={apiBase}
                        editable
                      />
                    </SectionCard>
                  )}

                  {/* TAB: RETRIEVAL */}
                  {activeTab === "retrieval" && (
                    <SectionCard
                      icon={Globe}
                      title="Retrieval & Agentic Web Search"
                      description="Tune query rewriting, HyDE expansion, and automatic SearXNG fallback."
                      footer={
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
                              rerank_enabled: rerankEnabled,
                              rerank_top_k: rerankTopK,
                            })
                          }
                          className={primaryBtn}
                        >
                          <span>Save Retrieval</span>
                        </button>
                      }
                    >
                      <div className="space-y-3">
                        <ToggleRow
                          checked={queryRewrite}
                          onChange={setQueryRewrite}
                          title="Conversational Query Rewriting"
                          description="Resolves pronouns using the last 4 chat turns before vector search."
                        />
                        <ToggleRow
                          checked={hydeEnabled}
                          onChange={setHydeEnabled}
                          title="HyDE (Hypothetical Document Embeddings)"
                          description="Generates a synthetic passage to bridge vocabulary gaps (uses an extra LLM call)."
                        />
                        <ToggleRow
                          checked={webSearchEnabled}
                          onChange={setWebSearchEnabled}
                          title="Autonomous Web Search Fallback"
                          description="Queries SearXNG when local retrieval confidence falls below the threshold."
                        />
                        <ToggleRow
                          checked={rerankEnabled}
                          onChange={setRerankEnabled}
                          title="Cross-Encoder Reranking"
                          description="Re-rank retrieved candidates with the reranker model for higher precision (adds latency)."
                        />
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <Field label={`Web Fallback Threshold (${webThreshold.toFixed(2)})`}>
                          <input
                            type="range"
                            min={0}
                            max={1}
                            step={0.05}
                            value={webThreshold}
                            onChange={(e) => setWebThreshold(Number(e.target.value))}
                            className="w-full accent-blue-600"
                          />
                        </Field>
                        <Field label="SearXNG Base URL" htmlFor="settings-searxng">
                          <input
                            id="settings-searxng"
                            type="url"
                            value={searxngUrl}
                            onChange={(e) => setSearxngUrl(e.target.value)}
                            className={cn(inputClass, "font-mono")}
                          />
                        </Field>
                        <Field label="Rerank Top-K (candidates)" htmlFor="settings-rerank-topk">
                          <input
                            id="settings-rerank-topk"
                            type="number"
                            min={1}
                            max={100}
                            value={rerankTopK}
                            onChange={(e) => setRerankTopK(Number(e.target.value))}
                            className={cn(inputClass, "font-mono tabular-nums")}
                          />
                        </Field>
                      </div>

                      {connectors.length > 0 && (
                        <div className="pt-4 border-t border-slate-100 space-y-2">
                          <h4 className="text-xs font-semibold text-slate-700">Workspace Web Connectors</h4>
                          <div className="space-y-1.5">
                            {connectors.map((c) => (
                              <div
                                key={c.id}
                                className="flex items-center justify-between gap-3 p-3 rounded-lg border border-slate-200 bg-white"
                              >
                                <div className="min-w-0">
                                  <div className="text-sm font-medium text-slate-800 truncate">{c.name}</div>
                                  <div className="text-[11px] text-slate-500 font-mono truncate">{c.query}</div>
                                </div>
                                <button
                                  type="button"
                                  onClick={() => handleSyncConnector(c.id)}
                                  disabled={syncingId === c.id}
                                  className={ghostBtn}
                                >
                                  {syncingId === c.id ? (
                                    <Loader2 className="w-3 h-3 animate-spin" />
                                  ) : (
                                    <RefreshCw className="w-3 h-3" />
                                  )}
                                  <span>Sync</span>
                                </button>
                              </div>
                            ))}
                        </div>
                      </div>
                      )}
                        </SectionCard>
                      )}

                  {/* TAB: MEMORY */}
                  {activeTab === "memory" && (
                    <SectionCard
                      icon={Brain}
                      title="Cognitive Memory & Sleep Consolidation"
                      description="Inspect episodic/entity graph health and run NREM pruning + REM associative dreaming."
                    >
                      {dreamStatus ? (
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                          <StatCard label="Total Memories" value={dreamStatus.total_memories} tone="text-slate-800" />
                          <StatCard label="Active Nodes" value={dreamStatus.active_nodes} tone="text-emerald-700" />
                          <StatCard label="Pruned Nodes" value={dreamStatus.invalidated_nodes} tone="text-slate-600" />
                          <StatCard label="Graph Edges" value={dreamStatus.total_edges} tone="text-blue-700" />
                        </div>
                      ) : (
                        <p className="text-xs text-slate-500">Select a workspace to view memory metrics.</p>
                      )}

                      <div className="p-4 rounded-xl border border-slate-200 bg-slate-50/60 flex items-center justify-between gap-4">
                        <div className="min-w-0">
                          <div className="text-sm font-semibold text-slate-800">On-Demand Sleep Cycle (NREM + REM)</div>
                          <div className="text-xs text-slate-500 mt-0.5 leading-snug">
                            Deduplicates noisy memories, resolves contradictions, and synthesizes cross-document dream
                            insights.
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={handleTriggerDream}
                          disabled={dreaming || !workspaceId}
                          className={cn(primaryBtn, "shrink-0")}
                        >
                          {dreaming ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                          <span>Run Dream Cycle</span>
                        </button>
                      </div>
                    </SectionCard>
                  )}

                  {/* TAB: SECURITY */}
                  {activeTab === "security" && (
                    <SectionCard
                      icon={Shield}
                      title="Authentication & Audit Trail"
                      description="Configure JWT authentication and review recent system audit events."
                    >
                      <div className="p-4 rounded-xl border border-slate-200 bg-white space-y-3">
                        <div className="flex items-center justify-between gap-4">
                          <div className="min-w-0">
                            <div className="text-sm font-medium text-slate-800">Require JWT Authentication</div>
                            <div className="text-xs text-slate-500 mt-0.5">
                              <code className="font-mono">AUTH_ENABLED</code> gate for all protected routes.
                            </div>
                          </div>
                          <Switch checked={authEnabled} onChange={setAuthEnabled} label="Require JWT Authentication" />
                        </div>

                        <div className="flex items-center gap-2 text-xs text-slate-600">
                          <span>JWT Secret:</span>
                          <span
                            className={cn(
                              "px-2 py-0.5 rounded font-mono text-[11px]",
                              hasJwtSecret ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"
                            )}
                          >
                            {hasJwtSecret ? "Configured" : "Not set"}
                          </span>
                        </div>

                        <div className="flex flex-wrap items-center gap-2">
                          <input
                            type="password"
                            value={newJwtSecret}
                            onChange={(e) => setNewJwtSecret(e.target.value)}
                            placeholder="Set new JWT secret (leave blank to keep)"
                            className={cn(inputClass, "flex-1 min-w-[12rem] font-mono")}
                          />
                          <button
                            type="button"
                            disabled={saving}
                            onClick={() => handleSaveSettings({ generate_jwt_secret: true }, "Generated and saved new JWT secret.")}
                            className={ghostBtn}
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
                            className={primaryBtn}
                          >
                            Save Auth
                          </button>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <h4 className="text-xs font-semibold text-slate-700">Recent Audit Log (Last 15)</h4>
                        <div className="border border-slate-200 rounded-xl overflow-hidden bg-white">
                          <div className="max-h-64 overflow-y-auto divide-y divide-slate-100 text-[11px]">
                            {auditLogs.length === 0 ? (
                              <div className="p-6 text-center text-slate-400">No audit events recorded yet.</div>
                            ) : (
                              auditLogs.map((log) => (
                                <div
                                  key={log.id}
                                  className="p-3 flex items-center justify-between gap-3 hover:bg-slate-50 transition-colors"
                                >
                                  <div className="min-w-0">
                                    <div className="font-medium text-slate-800 truncate">{log.summary}</div>
                                    <div className="text-slate-400 font-mono truncate">
                                      {log.event_type} · trace:{log.trace_id.slice(0, 8)}
                                    </div>
                                  </div>
                                  <span
                                    className={cn(
                                      "px-1.5 py-0.5 rounded font-mono shrink-0",
                                      log.status === "success"
                                        ? "bg-emerald-50 text-emerald-700"
                                        : "bg-rose-50 text-rose-700"
                                    )}
                                  >
                                    {log.status}
                                  </span>
                                </div>
                              ))
                            )}
                          </div>
                        </div>
                      </div>
                    </SectionCard>
                  )}

                  {/* TAB: SYSTEM */}
                  {activeTab === "system" && (
                    <>
                      {systemInfo && (
                        <SectionCard
                          icon={HardDrive}
                          title="System Health, Compute & Storage"
                          description="Live runtime diagnostics for compute device, databases, and uploaded files."
                        >
                      {health && (
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                          {Object.entries(health.services).map(([svc, state]) => {
                            const ok = state === "ok";
                            return (
                              <div key={svc} className="p-3.5 rounded-xl border border-slate-200 bg-slate-50/60">
                                <div className="flex items-center justify-between">
                                  <span className="text-xs font-medium text-slate-700 capitalize">{svc}</span>
                                  <span
                                    className={cn(
                                      "px-2 py-0.5 rounded text-[10px] font-mono",
                                      ok ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"
                                    )}
                                  >
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

                      <div className="border border-slate-200 rounded-xl divide-y divide-slate-100 text-xs bg-white">
                        <div className="p-3 flex items-center justify-between">
                          <span className="text-slate-500 flex items-center gap-1.5">
                            <Activity className="w-3.5 h-3.5" aria-hidden="true" /> Compute Device
                          </span>
                          <span className="font-mono text-slate-800">
                            {systemInfo.compute_device.toUpperCase()}
                            {systemInfo.gpu_name ? ` (${systemInfo.gpu_name})` : ""}
                          </span>
                        </div>
                        <div className="p-3 flex items-center justify-between gap-4">
                          <span className="text-slate-500 shrink-0">Embedding / Reranker</span>
                          <span className="font-mono text-slate-800 truncate text-right">
                            {systemInfo.embedding_model} · {systemInfo.reranker_model}
                          </span>
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
                          <span className="text-slate-500 shrink-0">
                            Uploads ({systemInfo.upload_file_count} files · {formatBytes(systemInfo.upload_total_bytes)})
                          </span>
                          <span className="font-mono text-slate-800 truncate">{systemInfo.upload_dir}</span>
                        </div>
                      </div>
                    </SectionCard>
                  )}
                      <SectionCard
                        icon={Settings}
                        title="Advanced"
                        description="Low-level runtime toggles. Changes apply immediately (HF offline applies on next model load)."
                        footer={
                          <button
                            type="button"
                            disabled={saving}
                            onClick={() =>
                              handleSaveSettings(
                                {
                                  hf_offline: hfOffline,
                                  async_ingest: asyncIngest,
                                  router_enabled: routerEnabled,
                                  router_base_url: routerBaseUrl,
                                  router_model: routerModel,
                                  router_timeout: routerTimeout,
                                },
                                "Advanced settings saved."
                              )
                            }
                            className={primaryBtn}
                          >
                            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                            <span>Save Advanced</span>
                          </button>
                        }
                      >
                        <div className="space-y-3">
                          <ToggleRow
                            checked={hfOffline}
                            onChange={setHfOffline}
                            title="Hugging Face offline mode"
                            description="Load embedding/reranker models from the local cache without contacting the hub."
                          />
                          <ToggleRow
                            checked={asyncIngest}
                            onChange={setAsyncIngest}
                            title="Asynchronous document ingestion"
                            description="Index uploads in the background instead of blocking the request."
                          />
                        </div>
                        <div className="pt-4 border-t border-slate-100 space-y-3">
                          <ToggleRow
                            checked={routerEnabled}
                            onChange={setRouterEnabled}
                            title="Decision router"
                            description="Classify queries with a small local router model before retrieval."
                          />
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            <Field label="Router Base URL" htmlFor="router-url">
                              <input
                                id="router-url"
                                type="url"
                                value={routerBaseUrl}
                                onChange={(e) => setRouterBaseUrl(e.target.value)}
                                className={cn(inputClass, "font-mono")}
                              />
                            </Field>
                            <Field label="Router Model" htmlFor="router-model">
                              <input
                                id="router-model"
                                type="text"
                                value={routerModel}
                                onChange={(e) => setRouterModel(e.target.value)}
                                className={cn(inputClass, "font-mono")}
                              />
                            </Field>
                            <Field label="Router Timeout (s)" htmlFor="router-timeout">
                              <input
                                id="router-timeout"
                                type="number"
                                step="0.5"
                                min={0.5}
                                max={60}
                                value={routerTimeout}
                                onChange={(e) => setRouterTimeout(Number(e.target.value))}
                                className={cn(inputClass, "font-mono tabular-nums")}
                              />
                            </Field>
                          </div>
                        </div>
                      </SectionCard>
                      <SectionCard
                        icon={AlertTriangle}
                        title="Danger zone"
                    description="Permanently wipe all workspaces, documents, chats, memory, vectors, and uploaded files."
                    footer={
                      confirmReset ? (
                        <>
                          <button
                            type="button"
                            onClick={() => setConfirmReset(false)}
                            disabled={resetting}
                            className={ghostBtn}
                          >
                            Cancel
                          </button>
                          <button
                            type="button"
                            onClick={handleResetEverything}
                            disabled={resetting}
                            className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-lg bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-50"
                          >
                            {resetting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                            <span>Yes, wipe everything</span>
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setConfirmReset(true)}
                          className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-lg border border-rose-200 bg-white text-rose-700 hover:bg-rose-50"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                          <span>Reset everything</span>
                        </button>
                      )
                    }
                  >
                    <div className="p-3 rounded-xl border border-rose-200 bg-rose-50/50 text-[11px] text-rose-700 leading-snug">
                      This cannot be undone. The app will reload and you’ll need to re-add LLM endpoints and re-upload
                      documents.
                    </div>
                  </SectionCard>
                </>
              )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Toast feedback */}
      {feedback && (
        <div
          role={feedback.type === "error" ? "alert" : "status"}
          aria-live={feedback.type === "error" ? "assertive" : "polite"}
          className={cn(
            "fixed bottom-6 right-6 z-[60] max-w-sm flex items-start gap-2.5 rounded-xl border px-4 py-3 text-xs shadow-lg animate-in slide-in-from-bottom-2",
            feedback.type === "success"
              ? "bg-white text-emerald-800 border-emerald-200"
              : "bg-white text-rose-800 border-rose-200"
          )}
        >
          {feedback.type === "success" ? (
            <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5 text-emerald-600" aria-hidden="true" />
          ) : (
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-rose-600" aria-hidden="true" />
          )}
          <span className="break-words leading-snug">{feedback.message}</span>
          <button
            onClick={() => setFeedback(null)}
            aria-label="Dismiss notification"
            className="ml-1 text-slate-400 hover:text-slate-600"
          >
            <X className="w-3.5 h-3.5" aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
}