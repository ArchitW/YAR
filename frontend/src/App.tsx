import { useEffect, useState, useCallback } from "react";
import {
  AlertCircle,
  BookOpen,
  Brain,
  Eye,
  EyeOff,
  FileText,
  Files,
  Layers,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { Citation, DocumentItem, Message, Workspace } from "./types";
import WorkspaceSelector from "./components/WorkspaceSelector";
import WorkspaceModal from "./components/WorkspaceModal";
import DocumentDropzone from "./components/DocumentDropzone";
import DocumentList from "./components/DocumentList";
import MemoryInspector from "./components/MemoryInspector";

const API_BASE = "http://localhost:8000";

export default function App() {
  // Workspace state
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeWorkspace, setActiveWorkspace] = useState<Workspace | null>(null);
  const [workspaceModalMode, setWorkspaceModalMode] = useState<"create" | "edit" | null>(null);

  // Chat & Retrieval state
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<"auto" | "hybrid" | "semantic" | "keyword">("auto");
  const [showCitations, setShowCitations] = useState(true);
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);

  // Document Management Drawer state
  const [isDocumentsOpen, setIsDocumentsOpen] = useState(false);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [isLoadingDocs, setIsLoadingDocs] = useState(false);

  // Cognitive Memory & Dossier Drawer state
  const [isMemoryOpen, setIsMemoryOpen] = useState(false);

  // 1. Fetch or initialize workspaces on mount
  useEffect(() => {
    fetchWorkspaces();
  }, []);

  const fetchWorkspaces = async () => {
    try {
      const res = await fetch(`${API_BASE}/workspaces`);
      if (!res.ok) throw new Error("Failed to load workspaces");
      const data: Workspace[] = await res.json();

      if (data.length === 0) {
        // Initialize default workspace
        const initRes = await fetch(`${API_BASE}/workspaces?name=Default%20Workspace&description=Default%20knowledge%20workspace`, {
          method: "POST",
        });
        if (initRes.ok) {
          const defaultWs = await initRes.json();
          setWorkspaces([defaultWs]);
          setActiveWorkspace(defaultWs);
          localStorage.setItem("yar_active_ws", String(defaultWs.id));
        }
      } else {
        setWorkspaces(data);
        const savedWsId = localStorage.getItem("yar_active_ws");
        const found = data.find((w) => String(w.id) === savedWsId);
        const selected = found || data[0];
        setActiveWorkspace(selected);
      }
    } catch {
      // Backend starting or offline
    }
  };

  // 2. Load scoped chat history & documents whenever active workspace changes
  const loadWorkspaceData = useCallback(async (wsId: number) => {
    setActiveCitation(null);

    // Load chat history
    try {
      const res = await fetch(`${API_BASE}/chat/history?workspace_id=${wsId}`);
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) {
          setMessages(
            data.map((item: any) => ({
              id: item.id,
              role: item.role as "user" | "assistant",
              text: item.content,
              citations: item.citations,
              provider: item.provider,
              model: item.model,
              degraded: item.degraded,
            }))
          );
        }
      } else {
        setMessages([]);
      }
    } catch {
      setMessages([]);
    }

    // Load documents
    setIsLoadingDocs(true);
    try {
      const docRes = await fetch(`${API_BASE}/documents?workspace_id=${wsId}`);
      if (docRes.ok) {
        const docData = await docRes.json();
        setDocuments(docData);
      } else {
        setDocuments([]);
      }
    } catch {
      setDocuments([]);
    } finally {
      setIsLoadingDocs(false);
    }
  }, []);

  useEffect(() => {
    if (activeWorkspace) {
      localStorage.setItem("yar_active_ws", String(activeWorkspace.id));
      loadWorkspaceData(activeWorkspace.id);
    }
  }, [activeWorkspace, loadWorkspaceData]);

  // Workspace CRUD handlers
  const handleSaveWorkspace = async (name: string, description: string) => {
    if (workspaceModalMode === "create") {
      const params = new URLSearchParams({ name, description });
      const res = await fetch(`${API_BASE}/workspaces?${params.toString()}`, { method: "POST" });
      if (!res.ok) throw new Error("Failed to create workspace");
      const created: Workspace = await res.json();
      setWorkspaces((prev) => [...prev, created]);
      setActiveWorkspace(created);
    } else if (workspaceModalMode === "edit" && activeWorkspace) {
      const params = new URLSearchParams({ name, description });
      const res = await fetch(`${API_BASE}/workspaces/${activeWorkspace.id}?${params.toString()}`, {
        method: "PATCH",
      });
      if (!res.ok) throw new Error("Failed to update workspace");
      const updated: Workspace = await res.json();
      setWorkspaces((prev) => prev.map((w) => (w.id === updated.id ? updated : w)));
      setActiveWorkspace(updated);
    }
  };

  const handleDeleteWorkspace = async (id: number) => {
    const res = await fetch(`${API_BASE}/workspaces/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error("Failed to delete workspace");
    const remaining = workspaces.filter((w) => w.id !== id);
    setWorkspaces(remaining);
    if (remaining.length > 0) {
      setActiveWorkspace(remaining[0]);
    } else {
      await fetchWorkspaces();
    }
  };

  // Send message
  const send = async () => {
    if (!input.trim() || loading || !activeWorkspace) return;
    const userQuery = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: userQuery }]);
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace_id: activeWorkspace.id,
          message: userQuery,
          mode,
        }),
      });

      if (!res.ok) {
        // Fallback to unary /chat if stream endpoint fails
        const unaryRes = await fetch(`${API_BASE}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            workspace_id: activeWorkspace.id,
            message: userQuery,
            mode,
          }),
        });
        if (!unaryRes.ok) throw new Error(`HTTP ${unaryRes.status}`);
        const data = await unaryRes.json();
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            text: data.answer,
            citations: data.citations || [],
            provider: data.provider,
            model: data.model,
            degraded: data.degraded,
          },
        ]);
        return;
      }

      if (!res.body) throw new Error("No readable stream in response");

      // Append initial assistant placeholder
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: "",
          citations: [],
          provider: "",
          model: "",
          degraded: false,
        },
      ]);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";

        for (const part of parts) {
          const trimmed = part.trim();
          if (trimmed.startsWith("data: ")) {
            try {
              const event = JSON.parse(trimmed.slice(6));
              if (event.type === "init") {
                setMessages((prev) => {
                  const next = [...prev];
                  const last = next[next.length - 1];
                  if (last && last.role === "assistant") {
                    next[next.length - 1] = {
                      ...last,
                      citations: event.citations || [],
                      provider: event.provider,
                      model: event.model,
                      degraded: event.degraded,
                    };
                  }
                  return next;
                });
              } else if (event.type === "token") {
                setMessages((prev) => {
                  const next = [...prev];
                  const last = next[next.length - 1];
                  if (last && last.role === "assistant") {
                    next[next.length - 1] = {
                      ...last,
                      text: last.text + event.token,
                    };
                  }
                  return next;
                });
              } else if (event.type === "done") {
                setMessages((prev) => {
                  const next = [...prev];
                  const last = next[next.length - 1];
                  if (last && last.role === "assistant") {
                    next[next.length - 1] = {
                      ...last,
                      text: event.answer || last.text,
                      citations: event.citations || last.citations,
                      provider: event.provider || last.provider,
                      model: event.model || last.model,
                      degraded: event.degraded ?? last.degraded,
                    };
                  }
                  return next;
                });
              }
            } catch {
              // Ignore partial JSON parse errors
            }
          }
        }
      }
    } catch {
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last && last.role === "assistant" && !last.text) {
          next[next.length - 1] = {
            ...last,
            text: "Error contacting backend service. Please ensure the API is running.",
          };
          return next;
        } else if (last && last.role === "user") {
          return [
            ...next,
            {
              role: "assistant",
              text: "Error contacting backend service. Please ensure the API is running.",
            },
          ];
        }
        return next;
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-screen bg-slate-50 text-slate-900 font-sans">
      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="h-14 px-4 border-b bg-white flex items-center justify-between shadow-sm">
          <div className="flex items-center gap-3">
            <span className="font-bold text-lg text-slate-800 tracking-tight">YAR</span>
            {/* Workspace Selector */}
            <WorkspaceSelector
              workspaces={workspaces}
              activeWorkspace={activeWorkspace}
              onSelectWorkspace={setActiveWorkspace}
              onOpenCreateModal={() => setWorkspaceModalMode("create")}
              onOpenEditModal={() => setWorkspaceModalMode("edit")}
            />
          </div>

          <div className="flex items-center gap-2 sm:gap-3">
            {/* Cognitive Memory & Living Dossier Drawer Toggle */}
            <button
              onClick={() => {
                setIsMemoryOpen(!isMemoryOpen);
                if (!isMemoryOpen) {
                  setIsDocumentsOpen(false);
                  setActiveCitation(null);
                }
              }}
              className={`px-2.5 py-1.5 rounded-lg border text-xs font-medium flex items-center gap-1.5 transition-colors ${
                isMemoryOpen
                  ? "bg-purple-50 text-purple-700 border-purple-200"
                  : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
              }`}
              aria-label="Toggle memory and dossier panel"
            >
              <Brain className="w-3.5 h-3.5 text-purple-600" />
              <span>Memory</span>
            </button>

            {/* Documents Drawer Toggle */}
            <button
              onClick={() => {
                setIsDocumentsOpen(!isDocumentsOpen);
                if (!isDocumentsOpen) {
                  setIsMemoryOpen(false);
                  setActiveCitation(null);
                }
              }}
              className={`px-2.5 py-1.5 rounded-lg border text-xs font-medium flex items-center gap-1.5 transition-colors ${
                isDocumentsOpen
                  ? "bg-blue-50 text-blue-700 border-blue-200"
                  : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
              }`}
              aria-label="Toggle documents panel"
            >
              <Files className="w-3.5 h-3.5" />
              <span>Documents</span>
              <span className="px-1.5 py-0.2 rounded-full bg-slate-100 text-[10px] font-mono text-slate-600">
                {documents.length}
              </span>
            </button>

            {/* Retrieval Mode Selector */}
            <div className="hidden sm:flex items-center gap-1.5 text-xs text-slate-600">
              <Layers className="w-3.5 h-3.5 text-slate-400" />
              <select
                id="mode-select"
                aria-label="Retrieval Mode"
                value={mode}
                onChange={(e) => setMode(e.target.value as any)}
                className="bg-slate-50 border border-slate-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="auto">Auto (Hybrid)</option>
                <option value="hybrid">Hybrid</option>
                <option value="semantic">Semantic</option>
                <option value="keyword">Keyword</option>
              </select>
            </div>

            {/* Citation Visibility Toggle */}
            <button
              onClick={() => setShowCitations(!showCitations)}
              title={showCitations ? "Hide Citations" : "Show Citations"}
              className={`p-1.5 rounded border text-xs flex items-center gap-1 ${
                showCitations
                  ? "bg-slate-100 text-slate-700 border-slate-300"
                  : "bg-white text-slate-400 border-slate-200 hover:text-slate-600"
              }`}
            >
              {showCitations ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
              <span className="hidden md:inline">
                {showCitations ? "Citations On" : "Citations Off"}
              </span>
            </button>
          </div>
        </header>

        {/* Message History */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4">
          {messages.length === 0 && (
            <div className="h-full flex flex-col items-center justify-center text-center p-6 text-slate-400">
              <BookOpen className="w-12 h-12 stroke-[1.5] mb-3 text-slate-300" />
              <p className="text-sm font-medium text-slate-600">
                {activeWorkspace ? `Ready in "${activeWorkspace.name}"` : "No conversation yet"}
              </p>
              <p className="text-xs max-w-sm mt-1">
                Upload files to this workspace via the Documents drawer to get grounded answers with citations.
              </p>
            </div>
          )}

          {messages.map((m, idx) => (
            <div
              key={idx}
              className={`flex flex-col ${m.role === "user" ? "items-end" : "items-start"}`}
            >
              <div
                className={`max-w-2xl px-4 py-3 rounded-2xl shadow-sm text-sm leading-relaxed ${
                  m.role === "user"
                    ? "bg-blue-600 text-white rounded-br-none"
                    : "bg-white border border-slate-200 text-slate-800 rounded-bl-none"
                }`}
              >
                {/* Assistant Metadata / Badges */}
                {m.role === "assistant" && m.degraded && (
                  <div className="flex items-center gap-1 text-xs text-amber-600 mb-2 font-medium bg-amber-50 px-2 py-0.5 rounded border border-amber-200 w-fit">
                    <AlertCircle className="w-3 h-3" />
                    <span>Extractive Fallback</span>
                  </div>
                )}

                <div className="whitespace-pre-wrap">
                  {m.text}
                  {loading && idx === messages.length - 1 && m.role === "assistant" && (
                    <span className="inline-block w-1.5 h-4 ml-0.5 bg-blue-500 animate-pulse align-middle" />
                  )}
                </div>

                {/* Citations List */}
                {m.role === "assistant" &&
                  showCitations &&
                  m.citations &&
                  m.citations.length > 0 && (
                    <div className="mt-3 pt-2.5 border-t border-slate-100 flex flex-wrap gap-1.5 items-center">
                      <span className="text-[11px] font-semibold text-slate-400 mr-1 flex items-center gap-1">
                        <Sparkles className="w-3 h-3 text-blue-500" />
                        Sources:
                      </span>
                      {m.citations.map((c) => {
                        const isSelected = activeCitation?.index === c.index;
                        const labelParts = [c.file_name || "Doc"];
                        if (c.page_number != null) labelParts.push(`p.${c.page_number}`);
                        else if (c.section) labelParts.push(`§ ${c.section}`);

                        return (
                          <button
                            key={c.index}
                            onClick={() => setActiveCitation(c)}
                            className={`px-2 py-0.5 rounded text-xs font-mono transition-all flex items-center gap-1 border ${
                              isSelected
                                ? "bg-blue-600 text-white border-blue-600 shadow-sm"
                                : "bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100 hover:border-slate-300"
                            }`}
                          >
                            <span className="font-bold text-[10px]">[{c.index}]</span>
                            <span className="max-w-[140px] truncate">{labelParts.join(" ")}</span>
                          </button>
                        );
                      })}
                    </div>
                  )}
              </div>
            </div>
          ))}

          {loading && messages.length > 0 && messages[messages.length - 1].role === "user" && (
            <div className="flex items-center gap-2 text-xs text-slate-400 py-2">
              <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
              <span>Searching workspace documents & synthesizing response...</span>
            </div>
          )}
        </main>

        {/* Input Bar */}
        <footer className="p-4 border-t bg-white">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
            className="flex gap-2 max-w-4xl mx-auto"
          >
            <input
              className="flex-1 border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-slate-50/50"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={activeWorkspace ? `Ask a question in "${activeWorkspace.name}"...` : "Ask a question..."}
              disabled={loading || !activeWorkspace}
            />
            <button
              type="submit"
              disabled={loading || !input.trim() || !activeWorkspace}
              className="px-4 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-xl hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5 shadow-sm"
            >
              <Send className="w-4 h-4" />
              <span className="hidden sm:inline">Ask</span>
            </button>
          </form>
        </footer>
      </div>

      {/* Memory & Living Dossier Side Panel */}
      {activeWorkspace && (
        <MemoryInspector
          workspaceId={activeWorkspace.id}
          workspaceName={activeWorkspace.name}
          isOpen={isMemoryOpen}
          onClose={() => setIsMemoryOpen(false)}
          apiBase={API_BASE}
        />
      )}

      {/* Documents Drawer Side Panel */}
      {isDocumentsOpen && activeWorkspace && (
        <aside className="w-80 sm:w-96 border-l bg-white flex flex-col h-full shadow-lg z-20 animate-in slide-in-from-right-4 duration-150">
          <div className="h-14 px-4 border-b flex items-center justify-between bg-slate-50/70">
            <div className="flex items-center gap-2">
              <Files className="w-4 h-4 text-blue-600" />
              <h3 className="font-semibold text-sm text-slate-800">
                Workspace Knowledge
              </h3>
            </div>
            <button
              onClick={() => setIsDocumentsOpen(false)}
              aria-label="Close documents panel"
              className="p-1 rounded text-slate-400 hover:text-slate-600 hover:bg-slate-200/60"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-5">
            {/* Upload Dropzone */}
            <div>
              <h4 className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
                Upload New Files
              </h4>
              <DocumentDropzone
                workspaceId={activeWorkspace.id}
                onUploadSuccess={() => loadWorkspaceData(activeWorkspace.id)}
              />
            </div>

            {/* Document List */}
            <DocumentList
              documents={documents}
              isLoading={isLoadingDocs}
              onRefresh={() => loadWorkspaceData(activeWorkspace.id)}
              workspaceName={activeWorkspace.name}
            />
          </div>
        </aside>
      )}

      {/* Citation Inspector Side Panel */}
      {activeCitation && (
        <aside className="w-80 sm:w-96 border-l bg-white flex flex-col h-full shadow-lg z-10 transition-all">
          <div className="h-14 px-4 border-b flex items-center justify-between bg-slate-50">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-blue-600" />
              <h3 className="font-semibold text-sm text-slate-800">
                Citation [{activeCitation.index}]
              </h3>
            </div>
            <button
              onClick={() => setActiveCitation(null)}
              aria-label="Close citation details"
              className="p-1 rounded text-slate-400 hover:text-slate-600 hover:bg-slate-200/60"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
            {/* Metadata Card */}
            <div className="bg-slate-50 p-3 rounded-lg border border-slate-100 space-y-2">
              <div>
                <span className="text-slate-400 uppercase tracking-wider text-[10px] font-semibold block">
                  Document
                </span>
                <span className="font-medium text-slate-800 text-sm break-all">
                  {activeCitation.file_name || "Unknown"}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2 pt-1 border-t border-slate-200/60">
                {activeCitation.page_number != null && (
                  <div>
                    <span className="text-slate-400 text-[10px] uppercase font-semibold block">
                      Page
                    </span>
                    <span className="font-mono text-slate-700 font-medium">
                      {activeCitation.page_number}
                    </span>
                  </div>
                )}

                {activeCitation.section && (
                  <div>
                    <span className="text-slate-400 text-[10px] uppercase font-semibold block">
                      Section
                    </span>
                    <span className="text-slate-700 font-medium break-all">
                      {activeCitation.section}
                    </span>
                  </div>
                )}

                {activeCitation.chunk_index != null && (
                  <div>
                    <span className="text-slate-400 text-[10px] uppercase font-semibold block">
                      Chunk Index
                    </span>
                    <span className="font-mono text-slate-700">
                      {activeCitation.chunk_index}
                      {activeCitation.total_chunks ? ` / ${activeCitation.total_chunks}` : ""}
                    </span>
                  </div>
                )}

                {activeCitation.score != null && (
                  <div>
                    <span className="text-slate-400 text-[10px] uppercase font-semibold block">
                      Relevance Score
                    </span>
                    <span className="font-mono text-slate-700">
                      {typeof activeCitation.score === "number"
                        ? activeCitation.score.toFixed(3)
                        : activeCitation.score}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Source Content Preview */}
            <div>
              <span className="text-slate-400 uppercase tracking-wider text-[10px] font-semibold block mb-1.5">
                Supporting Text Excerpt
              </span>
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-slate-700 leading-relaxed font-sans whitespace-pre-wrap select-text max-h-[400px] overflow-y-auto">
                {activeCitation.text || activeCitation.chunk_text || "No preview text available"}
              </div>
            </div>
          </div>
        </aside>
      )}

      {/* Workspace Create / Edit Modal */}
      <WorkspaceModal
        mode={workspaceModalMode || "create"}
        isOpen={workspaceModalMode !== null}
        onClose={() => setWorkspaceModalMode(null)}
        activeWorkspace={workspaceModalMode === "edit" ? activeWorkspace : null}
        onSave={handleSaveWorkspace}
        onDelete={handleDeleteWorkspace}
      />
    </div>
  );
}
