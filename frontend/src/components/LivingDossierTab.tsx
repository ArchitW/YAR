import { Sparkles, Edit3, Trash2 } from "lucide-react";
import { MemoryNodeItem } from "../types";

interface LivingDossierTabProps {
  entities: MemoryNodeItem[];
  onEdit: (entity: MemoryNodeItem) => void;
  onDelete: (nodeId: string) => void;
}

export default function LivingDossierTab({
  entities,
  onEdit,
  onDelete,
}: LivingDossierTabProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-xs text-slate-500 pb-1">
        <span>Active invariants, concepts & preferences ({entities.length})</span>
        <span className="text-[10px] text-purple-600 bg-purple-50 px-2 py-0.5 rounded font-mono font-medium">
          Persists across sessions
        </span>
      </div>

      {entities.length === 0 ? (
        <div className="text-center py-12 px-4 bg-slate-50 border border-dashed border-slate-200 rounded-xl">
          <Sparkles className="w-8 h-8 text-slate-300 mx-auto mb-2" />
          <p className="text-xs font-semibold text-slate-700">No dossier facts extracted yet</p>
          <p className="text-[11px] text-slate-400 mt-1 max-w-xs mx-auto">
            Preferences, architectural rules, and key concepts are automatically distilled from documents and interactions.
          </p>
        </div>
      ) : (
        entities.map((entity) => (
          <div
            key={entity.id}
            className="p-3 bg-white border border-slate-200 rounded-xl shadow-sm hover:border-slate-300 transition-all space-y-2"
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <span className="text-[10px] font-mono uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-purple-50 text-purple-700 border border-purple-100">
                  {entity.node_type}
                </span>
                <h4 className="text-xs font-semibold text-slate-800 mt-1">
                  {entity.name}
                </h4>
              </div>
              <div className="flex items-center gap-1">
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 font-medium">
                  {(entity.importance_score * 100).toFixed(0)}%
                </span>
                <button
                  onClick={() => onEdit(entity)}
                  title="Edit attribute"
                  className="p-1 text-slate-400 hover:text-purple-600 rounded hover:bg-slate-100"
                >
                  <Edit3 className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => onDelete(entity.id)}
                  title="Enforce Right-to-Forget"
                  className="p-1 text-slate-400 hover:text-red-600 rounded hover:bg-slate-100"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
            <p className="text-xs text-slate-600 bg-slate-50/70 p-2 rounded-lg font-mono leading-relaxed whitespace-pre-wrap">
              {entity.content}
            </p>
          </div>
        ))
      )}
    </div>
  );
}
