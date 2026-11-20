import { useState, useRef } from "react";
import { UploadCloud, CheckCircle2, AlertCircle, Loader2 } from "lucide-react";

interface DocumentDropzoneProps {
  workspaceId: number;
  onUploadSuccess: () => void;
}

const SUPPORTED_FORMATS = [
  "PDF", "TXT", "MD", "CSV", "XLSX", "EPUB", "PNG", "JPG"
];

export default function DocumentDropzone({
  workspaceId,
  onUploadSuccess,
}: DocumentDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);
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
    if (files.length > 0) {
      await uploadFiles(files);
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const files = Array.from(e.target.files);
      await uploadFiles(files);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const uploadFiles = async (files: File[]) => {
    setIsUploading(true);
    setUploadStatus(null);
    let successCount = 0;
    let failedNames: string[] = [];

    for (const file of files) {
      const formData = new FormData();
      formData.append("file", file);

      try {
        const res = await fetch(`http://localhost:8000/documents/upload?workspace_id=${workspaceId}`, {
          method: "POST",
          body: formData,
        });

        if (!res.ok) {
          throw new Error(`Upload failed with HTTP ${res.status}`);
        }
        successCount++;
      } catch (err: any) {
        failedNames.push(file.name);
      }
    }

    setIsUploading(false);

    if (successCount > 0 && failedNames.length === 0) {
      setUploadStatus({
        type: "success",
        message: `Successfully indexed ${successCount} document${successCount > 1 ? "s" : ""}!`,
      });
      onUploadSuccess();
      setTimeout(() => setUploadStatus(null), 4000);
    } else if (successCount > 0 && failedNames.length > 0) {
      setUploadStatus({
        type: "error",
        message: `Uploaded ${successCount} files, but failed on: ${failedNames.join(", ")}`,
      });
      onUploadSuccess();
    } else {
      setUploadStatus({
        type: "error",
        message: `Failed to upload files: ${failedNames.join(", ")}`,
      });
    }
  };

  return (
    <div className="w-full">
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`relative flex flex-col items-center justify-center p-6 border-2 border-dashed rounded-xl cursor-pointer transition-all duration-150 ${
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

        {isUploading ? (
          <div className="flex flex-col items-center justify-center py-2 text-slate-700">
            <Loader2 className="w-7 h-7 text-blue-600 animate-spin mb-2" />
            <p className="text-xs font-semibold text-slate-800">Extracting & Vectorizing Document...</p>
            <p className="text-[11px] text-slate-500 mt-0.5">Chunking, OCR & embedding in progress</p>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center text-center">
            <div className="w-10 h-10 rounded-full bg-blue-50 flex items-center justify-center mb-2.5 text-blue-600">
              <UploadCloud className="w-5 h-5" />
            </div>
            <p className="text-xs font-medium text-slate-700">
              <span className="text-blue-600 font-semibold">Click to upload</span> or drag and drop
            </p>
            <p className="text-[11px] text-slate-400 mt-0.5">
              Multi-page documents, spreadsheets, text, and images
            </p>

            <div className="flex flex-wrap items-center justify-center gap-1 mt-2.5">
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
        )}
      </div>

      {uploadStatus && (
        <div
          className={`flex items-center gap-2 mt-2.5 p-2.5 rounded-lg text-xs transition-all ${
            uploadStatus.type === "success"
              ? "bg-emerald-50 border border-emerald-200 text-emerald-800"
              : "bg-red-50 border border-red-200 text-red-800"
          }`}
        >
          {uploadStatus.type === "success" ? (
            <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
          ) : (
            <AlertCircle className="w-4 h-4 text-red-600 shrink-0" />
          )}
          <span>{uploadStatus.message}</span>
        </div>
      )}
    </div>
  );
}
