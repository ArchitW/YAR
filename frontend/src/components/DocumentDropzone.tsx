import { useState, useRef } from "react";
import { UploadCloud, CheckCircle2, AlertCircle, Loader2, FileText } from "lucide-react";

interface DocumentDropzoneProps {
  workspaceId: number;
  onUploadSuccess: () => void;
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
        `http://localhost:8000/documents/upload/stream?workspace_id=${workspaceId}`,
        { method: "POST", body: formData }
      );

      if (!res.ok || !res.body) {
        throw new Error(`Upload failed with HTTP ${res.status}`);
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

      {/* Live Ingestion Queue */}
      {jobs.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Ingestion Pipeline
            </span>
            {jobs.every((j) => j.currentStage === "complete" || j.currentStage === "error") && (
              <button
                type="button"
                onClick={() => setJobs([])}
                className="text-[11px] text-slate-400 hover:text-slate-600"
              >
                Clear
              </button>
            )}
          </div>

          {jobs.map((job) => {
            const isDone = job.currentStage === "complete";
            const isError = job.currentStage === "error";

            return (
              <div
                key={job.id}
                className={`p-3 rounded-xl border text-xs transition-colors ${
                  isDone
                    ? "bg-emerald-50/50 border-emerald-200"
                    : isError
                    ? "bg-rose-50/50 border-rose-200"
                    : "bg-white border-slate-200 shadow-sm"
                }`}
              >
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <FileText className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                    <span className="font-medium text-slate-800 truncate">{job.name}</span>
                  </div>
                  <span className="text-[11px] font-mono tabular-nums text-slate-500 shrink-0">
                    {formatBytes(job.sizeBytes)} · {job.progress}%
                  </span>
                </div>

                {/* Progress bar */}
                <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden mb-2.5">
                  <div
                    className={`h-full transition-all duration-300 ${
                      isError ? "bg-rose-500" : isDone ? "bg-emerald-500" : "bg-blue-600"
                    }`}
                    style={{ width: `${job.progress}%` }}
                  />
                </div>

                {/* Stage steps */}
                <div className="space-y-1">
                  {PIPELINE_STEPS.map((step) => {
                    const completed = job.completedStages.includes(step.key);
                    const active = !isDone && !isError && job.currentStage === step.key;
                    const detail = job.stageDetails[step.key];

                    return (
                      <div key={step.key} className="flex items-center justify-between gap-2 text-[11px]">
                        <div className="flex items-center gap-1.5">
                          {completed ? (
                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
                          ) : active ? (
                            <Loader2 className="w-3.5 h-3.5 text-blue-600 animate-spin shrink-0" />
                          ) : (
                            <span className="w-3.5 h-3.5 rounded-full border border-slate-300 inline-block shrink-0" />
                          )}
                          <span
                            className={
                              completed
                                ? "text-slate-700 font-medium"
                                : active
                                ? "text-blue-700 font-semibold"
                                : "text-slate-400"
                            }
                          >
                            {step.label}
                          </span>
                        </div>
                        {detail && (
                          <span className="text-slate-500 truncate max-w-[165px]" title={detail}>
                            {detail}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>

                {isDone && job.summary && (
                  <p className="mt-2 pt-1.5 border-t border-emerald-200/70 text-[11px] font-medium text-emerald-800">
                    {job.summary}
                  </p>
                )}

                {isError && job.error && (
                  <div className="mt-2 pt-1.5 border-t border-rose-200/70 flex items-start gap-1.5 text-[11px] text-rose-700">
                    <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                    <span>{job.error}</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
