import { useState } from "react";
import { FileText, RefreshCw, Eye, X, CheckCircle, Clock, AlertTriangle } from "lucide-react";
import { DocumentItem } from "../types";

interface DocumentListProps {
  documents: DocumentItem[];
  isLoading: boolean;
  onRefresh: () => void;
  workspaceName: string;
}

export default function DocumentList({
  documents,
  isLoading,
  onRefresh,
  workspaceName,
}: DocumentListProps) {
  const [selectedDoc, setSelectedDoc] = useState<DocumentItem | null>(null);

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
        <div className="divide-y divide-slate-100 border border-slate-200 rounded-xl overflow-hidden bg-white shadow-sm">
          {documents.map((doc) => (
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
                {doc.content && (
                  <button
                    type="button"
                    onClick={() => setSelectedDoc(doc)}
                    aria-label={`Preview extracted text for ${doc.name}`}
                    title="Preview extracted text"
                    className="p-1 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
                  >
                    <Eye className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedDoc && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-sm"
        >
          <div className="w-full max-w-2xl max-h-[80vh] flex flex-col bg-white border border-slate-200 rounded-2xl shadow-2xl overflow-hidden animate-in fade-in duration-150">
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 bg-slate-50/50 shrink-0">
              <div className="min-w-0 pr-4">
                <h3 className="text-xs font-semibold text-slate-800 truncate">
                  Extracted Preview: {selectedDoc.name}
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

            <div className="p-5 overflow-y-auto font-mono text-xs text-slate-700 whitespace-pre-wrap leading-relaxed select-text bg-slate-50/50">
              {selectedDoc.content || "No extracted content available."}
            </div>

            <div className="px-5 py-3 border-t border-slate-100 bg-white text-right">
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
    </div>
  );
}
