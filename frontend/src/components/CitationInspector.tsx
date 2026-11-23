import { useState } from "react";
import {
  ExternalLink,
  FileText,
  Globe,
  Maximize2,
  Minimize2,
  Sparkles,
  X,
  Crosshair,
  Layers,
} from "lucide-react";
import { Citation } from "../types";

interface CitationInspectorProps {
  activeCitation: Citation | null;
  onClose: () => void;
  apiBase?: string;
}

export default function CitationInspector({
  activeCitation,
  onClose,
  apiBase = "http://localhost:8000",
}: CitationInspectorProps) {
  const [isSplitView, setIsSplitView] = useState(true);

  if (!activeCitation) return null;

  const isPdf = Boolean(
    activeCitation.file_name?.toLowerCase().endsWith(".pdf") &&
    activeCitation.document_id
  );

  const hasBbox = Boolean(
    activeCitation.bbox &&
    activeCitation.bbox.length === 4
  );

  // Compute percentage coordinates for visual canvas overlay
  let leftPct = 10;
  let topPct = 15;
  let widthPct = 80;
  let heightPct = 12;

  if (hasBbox && activeCitation.bbox) {
    const pw = activeCitation.page_width || 612;
    const ph = activeCitation.page_height || 792;
    const [x0, y0, x1, y1] = activeCitation.bbox;

    leftPct = Math.max(0, Math.min(100, (x0 / pw) * 100));
    // PDF coordinate system origin is bottom-left; web is top-left
    const maxY = Math.max(y0, y1);
    topPct = Math.max(0, Math.min(100, ((ph - maxY) / ph) * 100));
    widthPct = Math.max(4, Math.min(100 - leftPct, (Math.abs(x1 - x0) / pw) * 100));
    heightPct = Math.max(3, Math.min(100 - topPct, (Math.abs(y1 - y0) / ph) * 100));
  }

  const pdfUrl = isPdf
    ? `${apiBase}/documents/${activeCitation.document_id}/file#page=${activeCitation.page_number || 1}&view=FitH`
    : "";

  return (
    <aside
      className={`border-l bg-white flex flex-col h-full shadow-2xl z-20 transition-all duration-300 ease-in-out ${
        isPdf && isSplitView
          ? "w-[720px] lg:w-[840px] xl:w-[920px]"
          : "w-80 sm:w-96"
      }`}
    >
      {/* Drawer Header */}
      <div className="h-14 px-4 border-b flex items-center justify-between bg-slate-50 shrink-0">
        <div className="flex items-center gap-2 overflow-hidden">
          <FileText className="w-4 h-4 text-blue-600 shrink-0" />
          <h3 className="font-semibold text-sm text-slate-800 truncate">
            Citation [{activeCitation.index}]
          </h3>
          {isPdf && (
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 font-semibold uppercase tracking-wider">
              PDF
            </span>
          )}
          {activeCitation.is_web && (
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 font-semibold uppercase tracking-wider">
              WEB
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          {isPdf && (
            <button
              onClick={() => setIsSplitView((prev) => !prev)}
              aria-label={isSplitView ? "Switch to compact view" : "Switch to split canvas view"}
              title={isSplitView ? "Compact view" : "Split-screen canvas"}
              className="p-1.5 rounded text-slate-500 hover:text-slate-700 hover:bg-slate-200/70 transition-colors flex items-center gap-1 text-xs font-medium"
            >
              {isSplitView ? (
                <>
                  <Minimize2 className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline">Compact</span>
                </>
              ) : (
                <>
                  <Maximize2 className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline">Split Canvas</span>
                </>
              )}
            </button>
          )}

          {isPdf && pdfUrl && (
            <a
              href={pdfUrl}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Open PDF in new tab"
              title="Open full PDF"
              className="p-1.5 rounded text-slate-500 hover:text-blue-600 hover:bg-blue-50 transition-colors"
            >
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          )}

          <button
            onClick={onClose}
            aria-label="Close citation details"
            className="p-1.5 rounded text-slate-400 hover:text-slate-600 hover:bg-slate-200/60 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Body Area */}
      <div className="flex-1 overflow-hidden flex flex-col min-h-0">
        {/* PDF Split Canvas Mode */}
        {isPdf && isSplitView ? (
          <div className="flex-1 flex flex-col md:flex-row h-full overflow-hidden">
            {/* Embedded Native PDF Viewer Frame */}
            <div className="flex-1 bg-slate-900 border-r border-slate-200 relative flex flex-col min-h-[300px]">
              <div className="bg-slate-800 text-slate-300 text-[11px] px-3 py-1.5 flex items-center justify-between border-b border-slate-700 shrink-0">
                <span className="truncate max-w-[240px] font-medium">
                  {activeCitation.file_name}
                </span>
                <span className="font-mono text-slate-400">
                  Page {activeCitation.page_number || 1}
                </span>
              </div>
              <iframe
                src={pdfUrl}
                className="w-full flex-1 border-0"
                title={`Original PDF: ${activeCitation.file_name}`}
              />
            </div>

            {/* Visual Grounding Overlay & Excerpt Panel */}
            <div className="w-full md:w-80 lg:w-96 flex flex-col bg-white overflow-y-auto p-4 space-y-4 shrink-0">
              {/* Visual Grounding Canvas Mini-Map */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-slate-500 uppercase tracking-wider text-[10px] font-semibold flex items-center gap-1">
                    <Crosshair className="w-3 h-3 text-amber-500" />
                    Visual Bounding-Box Grounding
                  </span>
                  {activeCitation.page_number != null && (
                    <span className="text-[10px] font-mono px-1.5 py-0.2 bg-slate-100 text-slate-600 rounded">
                      p.{activeCitation.page_number}
                    </span>
                  )}
                </div>

                {/* Simulated Visual Page Canvas with Bounding Box Overlay */}
                <div className="relative w-full aspect-[8.5/11] bg-slate-50 border-2 border-dashed border-slate-300 rounded-lg overflow-hidden shadow-inner flex flex-col justify-between p-3 select-none">
                  {/* Watermark / Sheet lines preview */}
                  <div className="space-y-2 opacity-25 pointer-events-none">
                    <div className="h-1.5 bg-slate-400 rounded w-3/4"></div>
                    <div className="h-1.5 bg-slate-300 rounded w-full"></div>
                    <div className="h-1.5 bg-slate-300 rounded w-5/6"></div>
                    <div className="h-1.5 bg-slate-300 rounded w-2/3"></div>
                    <div className="h-1.5 bg-slate-300 rounded w-4/5"></div>
                    <div className="h-1.5 bg-slate-300 rounded w-11/12"></div>
                  </div>

                  {/* Bounding Box Highlight Overlay */}
                  <div
                    style={{
                      left: `${leftPct}%`,
                      top: `${topPct}%`,
                      width: `${widthPct}%`,
                      height: `${heightPct}%`,
                    }}
                    className="absolute border-2 border-amber-500 bg-amber-400/25 rounded shadow-lg backdrop-blur-[0.5px] transition-all duration-300 animate-pulse flex items-center justify-center pointer-events-none"
                  >
                    <span className="text-[9px] font-mono font-bold bg-amber-500 text-white px-1 rounded shadow">
                      [{activeCitation.index}] Grounded
                    </span>
                  </div>

                  {/* Footer Coordinates Badge */}
                  <div className="pt-2 border-t border-slate-200/60 flex items-center justify-between text-[9px] font-mono text-slate-500">
                    <span>
                      {hasBbox && activeCitation.bbox
                        ? `[${activeCitation.bbox.join(", ")}]`
                        : "Paragraph region"}
                    </span>
                    <span>
                      {activeCitation.page_width || 612}×{activeCitation.page_height || 792}pt
                    </span>
                  </div>
                </div>
              </div>

              {/* Grounded Excerpt */}
              <div className="space-y-1.5">
                <span className="text-slate-400 uppercase tracking-wider text-[10px] font-semibold block">
                  Grounding Source Passage
                </span>
                <div className="p-3 bg-amber-50/50 border border-amber-200/70 rounded-lg text-slate-800 text-xs leading-relaxed font-sans whitespace-pre-wrap select-text max-h-[220px] overflow-y-auto">
                  {activeCitation.text || activeCitation.chunk_text || "No preview available"}
                </div>
              </div>

              {/* Metadata details */}
              <div className="bg-slate-50 p-3 rounded-lg border border-slate-100 space-y-1.5 text-xs">
                <div className="flex justify-between">
                  <span className="text-slate-400 text-[10px] uppercase font-semibold">
                    Relevance
                  </span>
                  <span className="font-mono text-slate-700 font-medium">
                    {typeof activeCitation.score === "number"
                      ? activeCitation.score.toFixed(3)
                      : activeCitation.score ?? "—"}
                  </span>
                </div>
                {activeCitation.section && (
                  <div className="flex justify-between">
                    <span className="text-slate-400 text-[10px] uppercase font-semibold">
                      Section
                    </span>
                    <span className="text-slate-700 truncate max-w-[160px]">
                      {activeCitation.section}
                    </span>
                  </div>
                )}
                {activeCitation.chunk_index != null && (
                  <div className="flex justify-between">
                    <span className="text-slate-400 text-[10px] uppercase font-semibold">
                      Chunk
                    </span>
                    <span className="font-mono text-slate-700">
                      {activeCitation.chunk_index}
                      {activeCitation.total_chunks ? ` / ${activeCitation.total_chunks}` : ""}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : (
          /* Standard / Compact View (for Non-PDF or Compact Mode) */
          <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
            {/* Metadata Card */}
            <div className="bg-slate-50 p-3.5 rounded-lg border border-slate-100 space-y-2.5">
              <div>
                <span className="text-slate-400 uppercase tracking-wider text-[10px] font-semibold block">
                  Document
                </span>
                <span className="font-medium text-slate-800 text-sm break-all">
                  {activeCitation.file_name || activeCitation.title || "Unknown source"}
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

              {hasBbox && activeCitation.bbox && (
                <div className="pt-2 border-t border-slate-200/60 flex items-center justify-between text-[11px]">
                  <span className="text-slate-400 text-[10px] uppercase font-semibold flex items-center gap-1">
                    <Crosshair className="w-3 h-3 text-amber-500" />
                    BBox:
                  </span>
                  <span className="font-mono text-slate-700">
                    [{activeCitation.bbox.join(", ")}]
                  </span>
                </div>
              )}

              {activeCitation.url && (
                <div className="pt-2 border-t border-slate-200/60">
                  <a
                    href={activeCitation.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 text-blue-600 hover:text-blue-800 font-medium text-xs break-all"
                  >
                    <Globe className="w-3.5 h-3.5 text-emerald-600" />
                    <span>Open Web Source</span>
                    <ExternalLink className="w-3 h-3 text-slate-400" />
                  </a>
                </div>
              )}
            </div>

            {/* Source Content Preview */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-slate-400 uppercase tracking-wider text-[10px] font-semibold block">
                  Supporting Text Excerpt
                </span>
                {isPdf && (
                  <button
                    onClick={() => setIsSplitView(true)}
                    className="text-[10px] text-blue-600 hover:text-blue-800 font-medium flex items-center gap-0.5"
                  >
                    <Layers className="w-3 h-3" />
                    View on PDF Canvas
                  </button>
                )}
              </div>
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-slate-700 leading-relaxed font-sans whitespace-pre-wrap select-text max-h-[400px] overflow-y-auto">
                {activeCitation.text || activeCitation.chunk_text || "No preview text available"}
              </div>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
