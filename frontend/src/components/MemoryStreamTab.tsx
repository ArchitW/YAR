import { Clock, Trash2 } from "lucide-react";
import { MemoryNodeItem } from "../types";

interface MemoryStreamTabProps {
  memories: MemoryNodeItem[];
  filter: string;
  onFilterChange: (filter: string) => void;
  onDelete: (nodeId: string) => void;
}

const FILTER_OPTIONS = ["all", "episodic_memory", "dream_insight", "concept", "entity"];

export default function MemoryStreamTab({
  memories,
  filter,
  onFilterChange,
  onDelete,
}: MemoryStreamTabProps) {
  return (
    <div className="space-y-3">
      {/* Type Filter Pills */}
      <div className="flex items-center gap-1.5 pb-1 overflow-x-auto text-[11px]">
        {FILTER_OPTIONS.map((f) => (
          <button
            key={f}
            onClick={() => onFilterChange(f)}
            className={`px-2.5 py-1 rounded-full font-medium transition-all capitalize whitespace-nowrap ${
              filter === f
                ? "bg-purple-600 text-white shadow-sm"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            {f.replace("_", " ")}
          </button>
        ))}
      </div>

      {memories.length === 0 ? (
        <div className="text-center py-12 px-4 bg-slate-50 border border-dashed border-slate-200 rounded-xl">
          <Clock className="w-8 h-8 text-slate-300 mx-auto mb-2" />
          <p className="text-xs font-semibold text-slate-700">No memories match filter</p>
        </div>
      ) : (
        memories.map((mem) => (
          <div
            key={mem.id}
            className="p-3 bg-white border border-slate-200 rounded-xl shadow-sm text-xs space-y-2 hover:border-slate-300 transition-all"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-1.5">
                <span
                  className={`text-[9px] font-mono uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded border ${
                    mem.node_type === "dream_insight"
                      ? "bg-indigo-50 text-indigo-700 border-indigo-200"
                      : "bg-slate-50 text-slate-600 border-slate-200"
                  }`}
                >
                  {mem.node_type}
                </span>
                <span className="font-semibold text-slate-800 truncate max-w-[200px]">
                  {mem.name}
                </span>
              </div>
              <button
                onClick={() => onDelete(mem.id)}
                title="Delete memory"
                className="p-1 text-slate-400 hover:text-red-600 rounded hover:bg-slate-100"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
            <p className="text-slate-600 leading-relaxed font-sans line-clamp-3">
              {mem.summary || mem.content}
            </p>
            <div className="flex items-center justify-between text-[10px] text-slate-400 font-mono pt-1 border-t border-slate-100">
              <span>Salience: {(mem.importance_score * 100).toFixed(0)}%</span>
              <span>{mem.created_at ? new Date(mem.created_at).toLocaleDateString() : ""}</span>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
