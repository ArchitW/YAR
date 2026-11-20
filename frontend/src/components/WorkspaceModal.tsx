import { useState, useEffect } from "react";
import { X, Trash2 } from "lucide-react";
import { Workspace } from "../types";

interface WorkspaceModalProps {
  mode: "create" | "edit";
  isOpen: boolean;
  onClose: () => void;
  activeWorkspace?: Workspace | null;
  onSave: (name: string, description: string) => Promise<void>;
  onDelete?: (id: number) => Promise<void>;
}

export default function WorkspaceModal({
  mode,
  isOpen,
  onClose,
  activeWorkspace,
  onSave,
  onDelete,
}: WorkspaceModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (mode === "edit" && activeWorkspace) {
      setName(activeWorkspace.name);
      setDescription(activeWorkspace.description || "");
    } else {
      setName("");
      setDescription("");
    }
    setError(null);
  }, [mode, activeWorkspace, isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError("Workspace name is required");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      await onSave(name.trim(), description.trim());
      onClose();
    } catch (err: any) {
      setError(err.message || "Failed to save workspace");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!activeWorkspace || !onDelete) return;
    if (!window.confirm(`Are you sure you want to delete workspace "${activeWorkspace.name}"?`)) {
      return;
    }
    setIsDeleting(true);
    try {
      await onDelete(activeWorkspace.id);
      onClose();
    } catch (err: any) {
      setError(err.message || "Failed to delete workspace");
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-sm"
    >
      <div className="w-full max-w-md bg-white border border-slate-200 rounded-2xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 bg-slate-50/50">
          <h2 className="text-sm font-semibold text-slate-800">
            {mode === "create" ? "Create New Workspace" : "Workspace Settings"}
          </h2>
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

          <div>
            <label htmlFor="ws-name" className="block text-xs font-semibold text-slate-700 mb-1.5">
              Workspace Name *
            </label>
            <input
              id="ws-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Project Apollo, Financial Audits"
              autoFocus
              className="w-full px-3 py-2 bg-slate-50/50 border border-slate-200 rounded-lg text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white transition-all"
            />
          </div>

          <div>
            <label htmlFor="ws-desc" className="block text-xs font-semibold text-slate-700 mb-1.5">
              Description (optional)
            </label>
            <textarea
              id="ws-desc"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Notes on workspace scope and contents..."
              className="w-full px-3 py-2 bg-slate-50/50 border border-slate-200 rounded-lg text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white transition-all resize-none"
            />
          </div>

          <div className="flex items-center justify-between pt-3 border-t border-slate-100">
            {mode === "edit" && onDelete && activeWorkspace ? (
              <button
                type="button"
                onClick={handleDelete}
                disabled={isDeleting || isSubmitting}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-red-600 hover:text-red-700 hover:bg-red-50 rounded-lg transition-colors disabled:opacity-50"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>{isDeleting ? "Deleting..." : "Delete Workspace"}</span>
              </button>
            ) : (
              <div />
            )}

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-3.5 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting || isDeleting}
                className="px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg shadow-sm transition-colors disabled:opacity-50"
              >
                {isSubmitting ? "Saving..." : mode === "create" ? "Create Workspace" : "Save Changes"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
