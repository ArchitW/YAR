import { useEffect, useState } from "react";
import {
  AlertCircle,
  BookOpen,
  Eye,
  EyeOff,
  FileText,
  Layers,
  Send,
  Sparkles,
  X,
} from "lucide-react";

interface Citation {
  index: number;
  document_id?: number;
  file_name?: string;
  page_number?: number | null;
  section?: string | null;
  chunk_index?: number | null;
  total_chunks?: number | null;
  text?: string;
  chunk_text?: string;
  score?: number;
}

interface Message {
  id?: number;
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
  provider?: string;
  model?: string;
  degraded?: boolean;
}

const API_BASE = "http://localhost:8000";

export default function App() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<"auto" | "hybrid" | "semantic" | "keyword">("auto");
  const [showCitations, setShowCitations] = useState(true);
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);

  // Load chat history on mount
  useEffect(() => {
    fetch(`${API_BASE}/chat/history?workspace_id=1`)
      .then((res) => (res.ok ? res.json() : []))
      .then((data: any[]) => {
        if (Array.isArray(data)) {
          setMessages(
            data.map((item) => ({
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
      })
      .catch(() => {
        // Backend might be offline or starting up
      });
  }, []);

  const send = async () => {
    if (!input.trim() || loading) return;
    const userQuery = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: userQuery }]);
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace_id: 1,
          message: userQuery,
          mode,
        }),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data = await res.json();
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
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: "Error contacting backend service. Please ensure the API is running.",
        },
      ]);
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
          <div className="flex items-center gap-2">
            <span className="font-bold text-lg text-slate-800 tracking-tight">YAR</span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 font-medium">
              Retrieval Chat
            </span>
          </div>

          <div className="flex items-center gap-3">
            {/* Retrieval Mode Selector */}
            <div className="flex items-center gap-1.5 text-xs text-slate-600">
              <Layers className="w-3.5 h-3.5 text-slate-400" />
              <label htmlFor="mode-select" className="hidden sm:inline">
                Mode:
              </label>
              <select
                id="mode-select"
                value={mode}
                onChange={(e) => setMode(e.target.value as any)}
                className="bg-slate-50 border border-slate-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="auto">Auto (Hybrid)</option>
                <option value="hybrid">Hybrid (Dense + Sparse)</option>
                <option value="semantic">Semantic (Dense)</option>
                <option value="keyword">Keyword (Sparse)</option>
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
              <p className="text-sm font-medium text-slate-600">No conversation yet</p>
              <p className="text-xs max-w-sm mt-1">
                Upload documents to workspace and ask questions to get grounded answers with
                citations.
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

                <div className="whitespace-pre-wrap">{m.text}</div>

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

          {loading && (
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
              placeholder="Ask a question about your documents..."
              disabled={loading}
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="px-4 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-xl hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5 shadow-sm"
            >
              <Send className="w-4 h-4" />
              <span className="hidden sm:inline">Ask</span>
            </button>
          </form>
        </footer>
      </div>

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
    </div>
  );
}
