import { useEffect, useMemo, useState } from "react";
import {
  FileText,
  RefreshCw,
  Eye,
  X,
  CheckCircle,
  Clock,
  AlertTriangle,
  Trash2,
  Save,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Search,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { DocumentItem } from "../types";

interface DocumentListProps {
  documents: DocumentItem[];
  isLoading: boolean;
  onRefresh: () => void;
  workspaceName: string;
  onDelete?: (doc: DocumentItem) => void;
  apiBase?: string;
  editable?: boolean;
}

export default function DocumentList({
  documents,
  isLoading,
  onRefresh,
  workspaceName,
  onDelete,
  apiBase,
  editable = false,
}: DocumentListProps) {
  const [selectedDoc, setSelectedDoc] = useState<DocumentItem | null>(null);
  const [editContent, setEditContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<DocumentItem | null>(null);
  const [reindexDoc, setReindexDoc] = useState<DocumentItem | null>(null);
  const [reindexStatus, setReindexStatus] = useState<"running" | "success" | "error">("running");
  const [reindexStage, setReindexStage] = useState(0);
  const [reindexChunks, setReindexChunks] = useState<number | null>(null);
  const [reindexError, setReindexError] = useState("");
  const [toast, setToast] = useState<{ type: "info" | "success" | "error"; message: string } | null>(null);

  useEffect(() => {
    if (!toast || toast.type === "info") return;
    const t = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(t);
  }, [toast]);
  const [actionFeedback, setActionFeedback] = useState<{ type: "success" | "error"; message: string } | null>(
    null
  );

  const canEdit = editable && !!apiBase;

  const REINDEX_STAGES = ["Purging old vectors", "Re-chunking text", "Embedding chunks", "Upserting to index"];

  useEffect(() => {
    if (!reindexDoc || reindexStatus !== "running") return;
    const t = setInterval(
      () => setReindexStage((s) => Math.min(s + 1, REINDEX_STAGES.length - 2)),
      1200
    );
    return () => clearInterval(t);
  }, [reindexDoc, reindexStatus]);

  const startReindex = async (doc: DocumentItem) => {
    if (!apiBase) return;
    setReindexDoc(doc);
    setReindexStatus("running");
    setReindexStage(0);
    setReindexChunks(null);
    setReindexError("");
    try {
      const res = await fetch(`${apiBase}/documents/${doc.id}/reindex`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setReindexChunks(data.chunks);
      setReindexStage(REINDEX_STAGES.length - 1);
      setReindexStatus("success");
      onRefresh();
    } catch (err: any) {
      setReindexError(err?.message || "Reindex failed");
      setReindexStatus("error");
    }
  };

  const PAGE_SIZE = 10;
  const [searchQuery, setSearchQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, documents.length]);

  const filtered = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return documents;
    return documents.filter((d) => d.name.toLowerCase().includes(q));
  }, [documents, searchQuery]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const page = Math.min(currentPage, totalPages);
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const openPreview = (doc: DocumentItem) => {
    setSelectedDoc(doc);
    setEditContent(doc.content || "");
    setActionFeedback(null);
  };

  const handleSave = async () => {
    if (!selectedDoc || !apiBase) return;
    setSaving(true);
    setActionFeedback(null);
    try {
      const res = await fetch(`${apiBase}/documents/${selectedDoc.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: editContent }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated: DocumentItem = await res.json();
      setSelectedDoc(updated);
      setEditContent(updated.content || "");
      setActionFeedback({ type: "success", message: "Saved. Reindex to apply changes to search." });
      onRefresh();
    } catch {
      setActionFeedback({ type: "error", message: "Failed to save changes." });
    } finally {
      setSaving(false);
    }
  };

  const handleReindex = async () => {
    if (!selectedDoc || !apiBase) return;
    setReindexing(true);
    setActionFeedback(null);
    try {
      const res = await fetch(`${apiBase}/documents/${selectedDoc.id}/reindex`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setActionFeedback({
        type: "success",
        message: `Reindexed ${data.chunks} chunk${data.chunks === 1 ? "" : "s"}.`,
      });
      onRefresh();
    } catch {
      setActionFeedback({ type: "error", message: "Failed to reindex document." });
    } finally {
      setReindexing(false);
    }
  };

  const confirmDelete = async (doc: DocumentItem) => {
    setPendingDelete(null);
    if (!apiBase) {
      onDelete?.(doc);
      return;
    }
    setToast({ type: "info", message: `Deleting “${doc.name}”…` });
    try {
      const res = await fetch(`${apiBase}/documents/${doc.id}?background=true`, { method: "DELETE" });
      if (!res.ok && res.status !== 404) throw new Error(`HTTP ${res.status}`);
      // Poll until the document row is gone (background purge may take a moment).
      let gone = res.status === 404;
      for (let i = 0; i < 20 && !gone; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        const check = await fetch(`${apiBase}/documents/${doc.id}`);
        if (check.status === 404) gone = true;
      }
      setToast({
        type: gone ? "success" : "info",
        message: gone ? `“${doc.name}” deleted.` : `“${doc.name}” deletion in progress…`,
      });
      onRefresh();
    } catch {
      setToast({ type: "error", message: `Failed to delete “${doc.name}”.` });
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  };

  const renderStatusBadge = (status: string) => {
    switch (status) {
      case "indexed":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
            <CheckCircle className="w-2.5 h-2.5 text-emerald-600" />
            indexed
          </span>
        );
      case "queued":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
            <Clock className="w-2.5 h-2.5 text-amber-600" />
            queued
          </span>
        );
      case "error":
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-red-50 text-red-700 border border-red-200">
            <AlertTriangle className="w-2.5 h-2.5 text-red-600" />
            {status}
          </span>
        );
    }
  };

  return (
    <div className="w-full space-y-2.5">
      <div className="flex items-center justify-between">
        <h3 className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
          Workspace Documents ({documents.length})
        </h3>
        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          aria-label="Refresh document list"
          className="p-1 text-slate-400 hover:text-slate-700 rounded-md hover:bg-slate-100 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {documents.length === 0 ? (
        <div className="text-center py-6 px-4 bg-slate-50 border border-dashed border-slate-200 rounded-xl">
          <FileText className="w-6 h-6 text-slate-300 mx-auto mb-1.5" />
          <p className="text-xs font-medium text-slate-600">No documents indexed yet</p>
          <p className="text-[11px] text-slate-400 mt-0.5">
            Drop files above to index into "{workspaceName}".
          </p>
        </div>
      ) : (
        <>
          {/* Search bar */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" aria-hidden="true" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search documents by name…"
              aria-label="Search documents"
              className="w-full pl-8 pr-8 py-1.5 text-xs bg-white border border-slate-200 rounded-lg text-slate-700 placeholder:text-slate-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                aria-label="Clear search"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {filtered.length === 0 ? (
            <div className="text-center py-6 px-4 bg-slate-50 border border-dashed border-slate-200 rounded-xl">
              <Search className="w-5 h-5 text-slate-300 mx-auto mb-1.5" />
              <p className="text-xs font-medium text-slate-600">No matches for “{searchQuery}”</p>
            </div>
          ) : (
            <div className="divide-y divide-slate-100 border border-slate-200 rounded-xl overflow-hidden bg-white shadow-sm">
              {paged.map((doc) => (
                <div
                  key={doc.id}
                  className="flex items-center justify-between p-2.5 hover:bg-slate-50 transition-colors"
                >
                  <div className="flex items-center gap-2.5 min-w-0 pr-2">
                    <div className="w-7 h-7 rounded bg-blue-50 flex items-center justify-center text-blue-600 shrink-0">
                      <FileText className="w-3.5 h-3.5" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-slate-800 truncate">{doc.name}</p>
                      <div className="flex items-center gap-1.5 text-[10px] text-slate-400">
                        <span>{formatBytes(doc.size_bytes)}</span>
                        {doc.file_type && <span>• {doc.file_type}</span>}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {renderStatusBadge(doc.status)}
                    {apiBase && (
                      <button
                        type="button"
                        onClick={() => startReindex(doc)}
                        aria-label={`Reindex ${doc.name}`}
                        title="Reindex document"
                        className="p-1 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
                      >
                        <RefreshCw className="w-3.5 h-3.5" />
                      </button>
                    )}
                    {doc.content && (
                      <button
                        type="button"
                        onClick={() => openPreview(doc)}
                        aria-label={`Preview extracted text for ${doc.name}`}
                        title={canEdit ? "View & edit extracted text" : "Preview extracted text"}
                        className="p-1 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
                      >
                        <Eye className="w-3.5 h-3.5" />
                      </button>
                    )}
                    {onDelete && (
                      <button
                        type="button"
                        onClick={() => setPendingDelete(doc)}
                        aria-label={`Delete ${doc.name}`}
                        title="Delete document"
                        className="p-1 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded transition-colors"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Pagination */}
          {filtered.length > PAGE_SIZE && (
            <div className="flex items-center justify-between pt-0.5">
              <span className="text-[11px] text-slate-400">
                {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filtered.length)} of {filtered.length}
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  aria-label="Previous page"
                  className="p-1 rounded-md border border-slate-200 text-slate-500 hover:bg-slate-100 disabled:opacity-40 disabled:pointer-events-none"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                </button>
                <span className="text-[11px] font-mono text-slate-500 px-1">
                  {page} / {totalPages}
                </span>
                <button
                  type="button"
                  onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  aria-label="Next page"
                  className="p-1 rounded-md border border-slate-200 text-slate-500 hover:bg-slate-100 disabled:opacity-40 disabled:pointer-events-none"
                >
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {selectedDoc && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-sm"
        >
          <div className="w-full max-w-3xl h-[85vh] max-h-[92vh] flex flex-col bg-white border border-slate-200 rounded-2xl shadow-2xl overflow-hidden animate-in fade-in duration-150">
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 bg-slate-50/50 shrink-0">
              <div className="min-w-0 pr-4">
                <h3 className="text-xs font-semibold text-slate-800 truncate">
                  {canEdit ? "Edit extracted text" : "Extracted Preview"}: {selectedDoc.name}
                </h3>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  Status: {selectedDoc.status} • Size: {formatBytes(selectedDoc.size_bytes)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSelectedDoc(null)}
                aria-label="Close preview"
                className="p-1 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-200/60 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {actionFeedback && (
              <div
                role={actionFeedback.type === "error" ? "alert" : "status"}
                className={`mx-5 mt-4 p-2.5 rounded-lg text-[11px] flex items-start gap-2 border ${
                  actionFeedback.type === "success"
                    ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                    : "bg-rose-50 text-rose-800 border-rose-200"
                }`}
              >
                {actionFeedback.type === "success" ? (
                  <CheckCircle2 className="w-3.5 h-3.5 shrink-0 mt-0.5 text-emerald-600" />
                ) : (
                  <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-rose-600" />
                )}
                <span className="leading-snug">{actionFeedback.message}</span>
              </div>
            )}

            {canEdit ? (
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                spellCheck={false}
                aria-label="Extracted document text"
                className="flex-1 m-5 p-3 overflow-y-auto font-mono text-xs text-slate-700 leading-relaxed bg-slate-50/50 border border-slate-200 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 resize-none"
              />
            ) : (
              <div className="flex-1 p-5 overflow-y-auto font-mono text-xs text-slate-700 whitespace-pre-wrap leading-relaxed select-text bg-slate-50/50">
                {selectedDoc.content || "No extracted content available."}
              </div>
            )}

            <div className="px-5 py-3 border-t border-slate-100 bg-white flex items-center justify-end gap-2">
              {canEdit && (
                <>
                  <button
                    type="button"
                    onClick={handleReindex}
                    disabled={reindexing || saving}
                    className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    {reindexing ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <RefreshCw className="w-3.5 h-3.5" />
                    )}
                    <span>{reindexing ? "Reindexing…" : "Reindex"}</span>
                  </button>
                  <button
                    type="button"
                    onClick={handleSave}
                    disabled={saving || reindexing}
                    className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                  >
                    {saving ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Save className="w-3.5 h-3.5" />
                    )}
                    <span>Save</span>
                  </button>
                </>
              )}
              <button
                type="button"
                onClick={() => setSelectedDoc(null)}
                className="px-3.5 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
      {reindexDoc && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="reindex-title"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-sm"
        >
          <div className="w-full max-w-sm bg-white border border-slate-200 rounded-2xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="px-5 pt-5 pb-4">
              <div className="flex items-start gap-3">
                <span
                  className={`inline-flex h-9 w-9 items-center justify-center rounded-full shrink-0 ${
                    reindexStatus === "success"
                      ? "bg-emerald-50 text-emerald-600"
                      : reindexStatus === "error"
                      ? "bg-rose-50 text-rose-600"
                      : "bg-blue-50 text-blue-600"
                  }`}
                >
                  {reindexStatus === "running" ? (
                    <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
                  ) : reindexStatus === "success" ? (
                    <CheckCircle2 className="w-4 h-4" aria-hidden="true" />
                  ) : (
                    <AlertCircle className="w-4 h-4" aria-hidden="true" />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <h3 id="reindex-title" className="text-sm font-semibold text-slate-900">
                    {reindexStatus === "running"
                      ? "Reindexing document"
                      : reindexStatus === "success"
                      ? "Reindex complete"
                      : "Reindex failed"}
                  </h3>
                  <p className="text-[11px] text-slate-500 mt-0.5 truncate">{reindexDoc.name}</p>
                </div>
                {reindexStatus !== "running" && (
                  <button
                    type="button"
                    onClick={() => setReindexDoc(null)}
                    aria-label="Close"
                    className="p-1 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100"
                  >
                    <X className="w-4 h-4" />
                  </button>
                )}
              </div>

              {reindexStatus === "running" ? (
                <div className="mt-4 space-y-2">
                  <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-blue-500 to-indigo-500 transition-all duration-500"
                      style={{ width: `${((reindexStage + 1) / REINDEX_STAGES.length) * 100}%` }}
                    />
                  </div>
                  <ul className="space-y-1.5">
                    {REINDEX_STAGES.map((stage, i) => {
                      const done = i < reindexStage;
                      const active = i === reindexStage;
                      return (
                        <li key={stage} className="flex items-center gap-2 text-[11px]">
                          {done ? (
                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" aria-hidden="true" />
                          ) : active ? (
                            <Loader2 className="w-3.5 h-3.5 text-blue-600 animate-spin shrink-0" aria-hidden="true" />
                          ) : (
                            <span className="w-3.5 h-3.5 rounded-full border border-slate-300 inline-block shrink-0" />
                          )}
                          <span
                            className={
                              done
                                ? "text-slate-700"
                                : active
                                ? "text-blue-700 font-medium"
                                : "text-slate-400"
                            }
                          >
                            {stage}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ) : reindexStatus === "success" ? (
                <p className="mt-4 text-xs text-emerald-700">
                  Rebuilt {reindexChunks ?? 0} chunk{reindexChunks === 1 ? "" : "s"} for search.
                </p>
              ) : (
                <p className="mt-4 text-xs text-rose-700 break-words">{reindexError}</p>
              )}
            </div>
            {reindexStatus !== "running" && (
              <div className="px-5 py-3 border-t border-slate-100 bg-slate-50/60 flex justify-end">
                <button
                  type="button"
                  onClick={() => setReindexDoc(null)}
                  className="px-3.5 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-colors"
                >
                  Close
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {pendingDelete && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-delete-title"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-sm"
        >
          <div className="w-full max-w-sm bg-white border border-slate-200 rounded-2xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="p-5">
              <div className="flex items-start gap-3">
                <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-rose-50 text-rose-600 shrink-0">
                  <Trash2 className="w-4 h-4" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <h3 id="confirm-delete-title" className="text-sm font-semibold text-slate-900">
                    Delete document?
                  </h3>
                  <p className="text-xs text-slate-500 mt-1 leading-snug break-words">
                    “{pendingDelete.name}” will be permanently removed along with its indexed vectors. This cannot be
                    undone.
                  </p>
                </div>
              </div>
            </div>
            <div className="px-5 py-3 border-t border-slate-100 bg-slate-50/60 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setPendingDelete(null)}
                className="px-3.5 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  const doc = pendingDelete;
                  if (doc) confirmDelete(doc);
                }}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-lg bg-rose-600 text-white hover:bg-rose-700 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-500/70"
              >
                <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Delete</span>
              </button>
            </div>
          </div>
        </div>
      )}
      {toast && (
        <div
          role={toast.type === "error" ? "alert" : "status"}
          aria-live={toast.type === "error" ? "assertive" : "polite"}
          className={`fixed bottom-6 right-6 z-[60] max-w-sm flex items-start gap-2.5 rounded-xl border px-4 py-3 text-xs shadow-lg ${
            toast.type === "success"
              ? "bg-white text-emerald-800 border-emerald-200"
              : toast.type === "error"
              ? "bg-white text-rose-800 border-rose-200"
              : "bg-white text-slate-700 border-slate-200"
          }`}
        >
          {toast.type === "success" ? (
            <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5 text-emerald-600" aria-hidden="true" />
          ) : toast.type === "error" ? (
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-rose-600" aria-hidden="true" />
          ) : (
            <Loader2 className="w-4 h-4 shrink-0 mt-0.5 text-blue-600 animate-spin" aria-hidden="true" />
          )}
          <span className="break-words leading-snug">{toast.message}</span>
          <button
            onClick={() => setToast(null)}
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
