import { useState, useEffect } from "react";
import { X, Sparkles } from "lucide-react";
import { MemoryNodeItem } from "../types";

interface EditEntityModalProps {
  entity: MemoryNodeItem | null;
  isOpen: boolean;
  onClose: () => void;
  onSave: (nodeId: string, patch: { name: string; content: string; importance_score: number }) => Promise<void>;
}

export default function EditEntityModal({
  entity,
  isOpen,
  onClose,
  onSave,
}: EditEntityModalProps) {
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [importance, setImportance] = useState(0.8);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (entity) {
      setName(entity.name);
      setContent(entity.content);
      setImportance(entity.importance_score);
    }
    setError(null);
  }, [entity, isOpen]);

  if (!isOpen || !entity) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !content.trim()) {
      setError("Name and content cannot be blank");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      await onSave(entity.id, {
        name: name.trim(),
        content: content.trim(),
        importance_score: importance,
      });
      onClose();
    } catch (err: any) {
      setError(err.message || "Failed to update memory node");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-sm"
    >
      <div className="w-full max-w-lg bg-white border border-slate-200 rounded-2xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 bg-slate-50/50">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-purple-600" />
            <h2 className="text-sm font-semibold text-slate-800">
              Edit Living Dossier Fact
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="p-1 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-200/60 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-600">
              {error}
            </div>
          )}

          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-purple-50 text-purple-700 border border-purple-200 font-semibold">
              {entity.node_type}
            </span>
            <span className="text-[11px] text-slate-400 font-mono">
              ID: {entity.id.slice(0, 8)}...
            </span>
          </div>

          <div>
            <label htmlFor="entity-name" className="block text-xs font-semibold text-slate-700 mb-1.5">
              Title / Subject *
            </label>
            <input
              id="entity-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 bg-slate-50/50 border border-slate-200 rounded-lg text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:bg-white transition-all"
            />
          </div>

          <div>
            <label htmlFor="entity-content" className="block text-xs font-semibold text-slate-700 mb-1.5">
              Fact / Invariant / Directive *
            </label>
            <textarea
              id="entity-content"
              rows={4}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="w-full px-3 py-2 bg-slate-50/50 border border-slate-200 rounded-lg text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:bg-white transition-all resize-none font-mono"
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label htmlFor="entity-importance" className="text-xs font-semibold text-slate-700">
                Importance / Salience
              </label>
              <span className="text-xs font-mono font-medium text-purple-700 bg-purple-50 px-2 py-0.5 rounded">
                {(importance * 100).toFixed(0)}%
              </span>
            </div>
            <input
              id="entity-importance"
              type="range"
              min="0.1"
              max="1.0"
              step="0.05"
              value={importance}
              onChange={(e) => setImportance(parseFloat(e.target.value))}
              className="w-full accent-purple-600 cursor-pointer"
            />
            <p className="text-[10px] text-slate-400 mt-1">
              Higher salience ensures this preference is prioritized in prompt assembly and shielded from noise pruning.
            </p>
          </div>

          <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-4 py-1.5 text-xs font-semibold text-white bg-purple-600 hover:bg-purple-700 rounded-lg shadow-sm transition-colors disabled:opacity-50"
            >
              {isSubmitting ? "Saving..." : "Save Changes"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
