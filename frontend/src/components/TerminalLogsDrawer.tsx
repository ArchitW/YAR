import { useEffect, useRef, useState } from "react";
import { Pause, Play, Terminal, Trash2, X } from "lucide-react";

interface LogEntry {
  ts: string;
  level: string;
  logger: string;
  message: string;
}

interface TerminalLogsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  apiBase: string;
}

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: "text-slate-400",
  INFO: "text-sky-400",
  WARNING: "text-amber-400",
  ERROR: "text-rose-400",
  CRITICAL: "text-rose-300 font-bold",
};

export default function TerminalLogsDrawer({
  isOpen,
  onClose,
  apiBase,
}: TerminalLogsDrawerProps) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [paused, setPaused] = useState(false);
  const [levelFilter, setLevelFilter] = useState<"ALL" | "INFO" | "WARNING" | "ERROR">("ALL");
  const [connected, setConnected] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen || paused) return;

    const es = new EventSource(`${apiBase}/health/logs/stream`);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (event) => {
      try {
        const entry = JSON.parse(event.data) as LogEntry;
        setLogs((prev) => {
          const next = [...prev, entry];
          return next.length > 400 ? next.slice(next.length - 400) : next;
        });
      } catch {
        // Ignore malformed events
      }
    };

    return () => {
      es.close();
      setConnected(false);
    };
  }, [isOpen, paused, apiBase]);

  useEffect(() => {
    if (isOpen && !paused) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, isOpen, paused]);

  if (!isOpen) return null;

  const filtered = logs.filter((entry) => {
    if (levelFilter === "ALL") return true;
    if (levelFilter === "ERROR") return entry.level === "ERROR" || entry.level === "CRITICAL";
    return entry.level === levelFilter;
  });

  return (
    <aside className="w-96 sm:w-[460px] border-l border-slate-800 bg-slate-950 text-slate-200 flex flex-col h-full shadow-xl z-20 animate-in slide-in-from-right-4 duration-150">
      <div className="h-14 px-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/90">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-emerald-400" />
          <h3 className="font-semibold text-sm text-slate-100">Backend Terminal</h3>
          <span
            className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${
              paused
                ? "bg-amber-500/15 text-amber-300"
                : connected
                ? "bg-emerald-500/15 text-emerald-300"
                : "bg-slate-800 text-slate-400"
            }`}
          >
            {paused ? "PAUSED" : connected ? "LIVE" : "CONNECTING"}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <select
            aria-label="Filter log level"
            value={levelFilter}
            onChange={(e) => setLevelFilter(e.target.value as any)}
            className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-[11px] text-slate-200 focus:outline-none"
          >
            <option value="ALL">All</option>
            <option value="INFO">Info</option>
            <option value="WARNING">Warnings</option>
            <option value="ERROR">Errors</option>
          </select>

          <button
            type="button"
            onClick={() => setPaused(!paused)}
            title={paused ? "Resume stream" : "Pause stream"}
            className="p-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800"
          >
            {paused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
          </button>

          <button
            type="button"
            onClick={() => setLogs([])}
            title="Clear logs"
            className="p-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close terminal logs"
            className="p-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3 font-mono text-[11px] leading-relaxed space-y-1">
        {filtered.length === 0 ? (
          <div className="text-slate-500 text-center py-8">
            Waiting for backend logs...
          </div>
        ) : (
          filtered.map((entry, idx) => (
            <div
              key={`${entry.ts}-${idx}`}
              className="flex items-start gap-2 break-words hover:bg-slate-900/70 px-1.5 py-0.5 rounded"
            >
              <span className="text-slate-500 shrink-0 tabular-nums">{entry.ts}</span>
              <span className={`shrink-0 w-14 ${LEVEL_COLORS[entry.level] || "text-slate-300"}`}>
                {entry.level}
              </span>
              <span className="text-slate-400 shrink-0 max-w-[110px] truncate" title={entry.logger}>
                {entry.logger}
              </span>
              <span className="text-slate-200 whitespace-pre-wrap break-all flex-1">
                {entry.message}
              </span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </aside>
  );
}
