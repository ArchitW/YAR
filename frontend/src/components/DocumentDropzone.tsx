import { useState, useRef } from "react";
import { UploadCloud, CheckCircle2, AlertCircle, Loader2 } from "lucide-react";

interface DocumentDropzoneProps {
  workspaceId: number;
  onUploadSuccess: () => void;
  indexToMaster?: boolean;
}

type StageKey = "upload" | "extract" | "sanitize" | "chunk" | "vectorize";

interface FileJob {
  id: string;
  name: string;
  sizeBytes: number;
  progress: number;
  currentStage: StageKey | "complete" | "error";
  completedStages: StageKey[];
  stageDetails: Partial<Record<StageKey, string>>;
  summary?: string;
  error?: string;
}

const PIPELINE_STEPS: { key: StageKey; label: string }[] = [
  { key: "upload", label: "Upload" },
  { key: "extract", label: "Extract" },
  { key: "sanitize", label: "PII Scrub" },
  { key: "chunk", label: "Chunk" },
  { key: "vectorize", label: "Vectorize" },
];

const SUPPORTED_FORMATS = ["PDF", "TXT", "MD", "CSV", "XLSX", "EPUB", "PNG", "JPG"];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DocumentDropzone({
  workspaceId,
  onUploadSuccess,
  indexToMaster = false,
}: DocumentDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [jobs, setJobs] = useState<FileJob[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) await uploadFiles(files);
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const files = Array.from(e.target.files);
      await uploadFiles(files);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const updateJob = (jobId: string, updater: (prev: FileJob) => FileJob) => {
    setJobs((prev) => prev.map((j) => (j.id === jobId ? updater(j) : j)));
  };

  const uploadSingleFile = async (file: File, jobId: string): Promise<boolean> => {
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(
        `http://localhost:8000/documents/upload/stream?workspace_id=${workspaceId}&index_to_master=${indexToMaster}`,
        { method: "POST", body: formData }
      );

      if (!res.ok) {
        let detail = `Upload failed with HTTP ${res.status}`;
        try {
          const err = await res.json();
          if (err?.detail) detail = String(err.detail);
        } catch {
          // ignore body parse errors
        }
        throw new Error(detail);
      }
      if (!res.body) {
        throw new Error("Upload failed: empty response");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let succeeded = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          const evt = JSON.parse(raw) as {
            stage: StageKey | "complete" | "error";
            progress: number;
            detail: string;
          };

          if (evt.stage === "error") {
            updateJob(jobId, (j) => ({
              ...j,
              progress: 100,
              currentStage: "error",
              error: evt.detail || "Ingestion failed",
            }));
            return false;
          }

          if (evt.stage === "complete") {
            succeeded = true;
            updateJob(jobId, (j) => ({
              ...j,
              progress: 100,
              currentStage: "complete",
              completedStages: ["upload", "extract", "sanitize", "chunk", "vectorize"],
              summary: evt.detail,
            }));
          } else {
            const stageIdx = PIPELINE_STEPS.findIndex((s) => s.key === evt.stage);
            const completed = PIPELINE_STEPS.slice(0, Math.max(0, stageIdx + 1)).map((s) => s.key);
            updateJob(jobId, (j) => ({
              ...j,
              progress: evt.progress,
              currentStage: evt.stage,
              completedStages: completed,
              stageDetails: { ...j.stageDetails, [evt.stage]: evt.detail },
            }));
          }
        }
      }
      return succeeded;
    } catch (err: any) {
      updateJob(jobId, (j) => ({
        ...j,
        progress: 100,
        currentStage: "error",
        error: err?.message || "Upload failed",
      }));
      return false;
    }
  };

  const uploadFiles = async (files: File[]) => {
    const newJobs: FileJob[] = files.map((file, idx) => ({
      id: `${Date.now()}-${idx}-${file.name}`,
      name: file.name,
      sizeBytes: file.size,
      progress: 5,
      currentStage: "upload",
      completedStages: [],
      stageDetails: {},
    }));

    setJobs((prev) => [...newJobs, ...prev]);

    let anySuccess = false;
    for (let i = 0; i < files.length; i++) {
      const ok = await uploadSingleFile(files[i], newJobs[i].id);
      if (ok) anySuccess = true;
    }

    if (anySuccess) {
      onUploadSuccess();
    }
  };

  const overall = jobs.length
    ? Math.round(jobs.reduce((s, j) => s + j.progress, 0) / jobs.length)
    : 0;
  const allDone =
    jobs.length > 0 && jobs.every((j) => j.currentStage === "complete" || j.currentStage === "error");
  const running = jobs.some((j) => j.currentStage !== "complete" && j.currentStage !== "error");

  return (
    <div className="w-full space-y-3">
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`relative flex flex-col items-center justify-center p-5 border-2 border-dashed rounded-xl cursor-pointer transition-all duration-150 ${
          isDragging
            ? "border-blue-500 bg-blue-50/50 scale-[0.99]"
            : "border-slate-200 bg-slate-50/50 hover:bg-slate-100/60 hover:border-slate-300"
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFileSelect}
          className="hidden"
          aria-label="Upload documents"
        />

        <div className="flex flex-col items-center justify-center text-center">
          <div className="w-9 h-9 rounded-full bg-blue-50 flex items-center justify-center mb-2 text-blue-600">
            <UploadCloud className="w-4 h-4" />
          </div>
          <p className="text-xs font-medium text-slate-700">
            <span className="text-blue-600 font-semibold">Click to upload</span> or drag and drop
          </p>
          <p className="text-[11px] text-slate-400 mt-0.5">
            Multi-page documents, spreadsheets, text, and images
          </p>

          <div className="flex flex-wrap items-center justify-center gap-1 mt-2">
            {SUPPORTED_FORMATS.map((fmt) => (
              <span
                key={fmt}
                className="px-1.5 py-0.5 text-[10px] font-mono font-medium bg-white text-slate-500 rounded border border-slate-200"
              >
                {fmt}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Upload queue — single panel, one row per file */}
      {jobs.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 bg-slate-50/60 border-b border-slate-100">
            <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              Upload queue ({jobs.length})
            </span>
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-mono tabular-nums text-slate-500">{overall}%</span>
              {allDone && (
                <button
                  type="button"
                  onClick={() => setJobs([])}
                  className="text-[11px] text-slate-400 hover:text-slate-600"
                >
                  Clear
                </button>
              )}
            </div>
          </div>

          {running && (
            <div className="h-1 bg-blue-100">
              <div
                className="h-full bg-gradient-to-r from-blue-500 to-indigo-500 transition-all duration-300"
                style={{ width: `${overall}%` }}
              />
            </div>
          )}

          <ul className="divide-y divide-slate-100 max-h-72 overflow-y-auto">
            {jobs.map((job) => {
              const isDone = job.currentStage === "complete";
              const isError = job.currentStage === "error";
              const stageLabel = PIPELINE_STEPS.find((s) => s.key === job.currentStage)?.label;
              const detail = job.stageDetails[job.currentStage as StageKey];

              return (
                <li key={job.id} className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    {isDone ? (
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" aria-hidden="true" />
                    ) : isError ? (
                      <AlertCircle className="w-3.5 h-3.5 text-rose-600 shrink-0" aria-hidden="true" />
                    ) : (
                      <Loader2 className="w-3.5 h-3.5 text-blue-600 animate-spin shrink-0" aria-hidden="true" />
                    )}
                    <span className="text-xs font-medium text-slate-800 truncate flex-1">{job.name}</span>
                    <span className="text-[10px] font-mono tabular-nums text-slate-400 shrink-0">
                      {formatBytes(job.sizeBytes)} · {job.progress}%
                    </span>
                  </div>

                  {isError ? (
                    <p className="mt-1 pl-5 text-[11px] text-rose-700 break-words leading-snug">
                      {job.error || "Ingestion failed"}
                    </p>
                  ) : isDone ? (
                    job.summary && (
                      <p className="mt-1 pl-5 text-[11px] text-emerald-700 break-words leading-snug">
                        {job.summary}
                      </p>
                    )
                  ) : (
                    <p className="mt-1 pl-5 text-[11px] text-slate-500 truncate">
                      {stageLabel}
                      {detail ? ` — ${detail}` : "…"}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
