import { useState, useEffect, useCallback } from "react";
import {
  Brain,
  X,
  Sparkles,
  Moon,
  Layers,
  RefreshCw,
} from "lucide-react";
import { MemoryNodeItem, DreamStatusData } from "../types";
import EditEntityModal from "./EditEntityModal";
import LivingDossierTab from "./LivingDossierTab";
import MemoryStreamTab from "./MemoryStreamTab";
import SleepDreamTab from "./SleepDreamTab";

interface MemoryInspectorProps {
  workspaceId: number;
  workspaceName: string;
  isOpen: boolean;
  onClose: () => void;
  apiBase: string;
}

export default function MemoryInspector({
  workspaceId,
  workspaceName,
  isOpen,
  onClose,
  apiBase,
}: MemoryInspectorProps) {
  const [activeTab, setActiveTab] = useState<"dossier" | "stream" | "dream">("dossier");
  const [dossierEntities, setDossierEntities] = useState<MemoryNodeItem[]>([]);
  const [streamMemories, setStreamMemories] = useState<MemoryNodeItem[]>([]);
  const [streamFilter, setStreamFilter] = useState<string>("all");
  const [dreamStatus, setDreamStatus] = useState<DreamStatusData | null>(null);

  const [isLoading, setIsLoading] = useState(false);
  const [isDreaming, setIsDreaming] = useState(false);
  const [dreamResult, setDreamResult] = useState<string | null>(null);

  const [editingEntity, setEditingEntity] = useState<MemoryNodeItem | null>(null);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);

  // Load Dossier Entities
  const fetchDossier = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/memory/entities?workspace_id=${workspaceId}`);
      if (res.ok) {
        const data = await res.json();
        setDossierEntities(Array.isArray(data) ? data : []);
      }
    } catch {
      setDossierEntities([]);
    }
  }, [apiBase, workspaceId]);

  // Load Memory Stream
  const fetchStream = useCallback(async (typeFilter?: string) => {
    try {
      let url = `${apiBase}/memory?workspace_id=${workspaceId}&limit=50`;
      if (typeFilter && typeFilter !== "all") {
        url += `&node_type=${typeFilter}`;
      }
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setStreamMemories(data.items || []);
      }
    } catch {
      setStreamMemories([]);
    }
  }, [apiBase, workspaceId]);

  // Load Dream Health Status
  const fetchDreamStatus = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/memory/dream/status?workspace_id=${workspaceId}`);
      if (res.ok) {
        const data = await res.json();
        setDreamStatus(data);
      }
    } catch {
      setDreamStatus(null);
    }
  }, [apiBase, workspaceId]);

  // Refetch when drawer opens or workspace changes
  useEffect(() => {
    if (isOpen) {
      setIsLoading(true);
      Promise.all([fetchDossier(), fetchStream(streamFilter), fetchDreamStatus()]).finally(() => {
        setIsLoading(false);
      });
    }
  }, [isOpen, workspaceId, fetchDossier, fetchStream, fetchDreamStatus, streamFilter]);

  // Right-to-Forget: Delete memory
  const handleDeleteNode = async (nodeId: string) => {
    if (!window.confirm("Enforce Right-to-Forget: Invalidate and purge this memory?")) return;
    try {
      const res = await fetch(`${apiBase}/memory/${nodeId}`, { method: "DELETE" });
      if (res.ok) {
        setDossierEntities((prev) => prev.filter((item) => item.id !== nodeId));
        setStreamMemories((prev) => prev.filter((item) => item.id !== nodeId));
        fetchDreamStatus();
      }
    } catch {
      // Ignored
    }
  };

  // Edit Living Dossier entity
  const handleSaveEntity = async (
    nodeId: string,
    patch: { name: string; content: string; importance_score: number }
  ) => {
    const res = await fetch(`${apiBase}/memory/entities/${nodeId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error("Failed to update entity");
    await fetchDossier();
    await fetchDreamStatus();
  };

  // Trigger Dream Consolidation Cycle
  const handleRunDreamCycle = async () => {
    setIsDreaming(true);
    setDreamResult(null);
    try {
      const res = await fetch(`${apiBase}/memory/dream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace_id: workspaceId,
          run_nrem: true,
          run_rem: true,
          max_dreams: 3,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        const pruned = data.nrem?.pruned_count ?? 0;
        const dreams = data.rem?.dreams_created ?? 0;
        setDreamResult(
          `Cycle completed: Pruned ${pruned} low-salience nodes, created ${dreams} associative dreams.`
        );
        fetchDossier();
        fetchStream(streamFilter);
        fetchDreamStatus();
      } else {
        setDreamResult("Consolidation cycle completed with warnings.");
      }
    } catch {
      setDreamResult("Error running dream consolidation cycle.");
    } finally {
      setIsDreaming(false);
    }
  };

  if (!isOpen) return null;

  return (
    <>
      <aside
        className="w-96 sm:w-[480px] border-l bg-white flex flex-col h-full shadow-2xl z-30 animate-in slide-in-from-right-4 duration-150"
        aria-label="Memory and Dossier Inspector"
      >
        {/* Header */}
        <div className="h-14 px-4 border-b flex items-center justify-between bg-slate-50/70">
          <div className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-purple-600" />
            <div>
              <h3 className="font-semibold text-sm text-slate-800 leading-tight">
                Cognitive Memory
              </h3>
              <p className="text-[10px] text-slate-500 font-mono truncate max-w-[200px]">
                {workspaceName}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close memory inspector"
            className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-200/60 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="flex border-b border-slate-200 bg-slate-50/50 px-2 pt-2 gap-1 text-xs font-medium">
          <button
            onClick={() => setActiveTab("dossier")}
            className={`px-3 py-2 border-b-2 rounded-t-md transition-all flex items-center gap-1.5 ${
              activeTab === "dossier"
                ? "border-purple-600 text-purple-700 bg-white shadow-sm font-semibold"
                : "border-transparent text-slate-600 hover:text-slate-900"
            }`}
          >
            <Sparkles className="w-3.5 h-3.5 text-purple-500" />
            <span>Living Dossier</span>
          </button>
          <button
            onClick={() => setActiveTab("stream")}
            className={`px-3 py-2 border-b-2 rounded-t-md transition-all flex items-center gap-1.5 ${
              activeTab === "stream"
                ? "border-purple-600 text-purple-700 bg-white shadow-sm font-semibold"
                : "border-transparent text-slate-600 hover:text-slate-900"
            }`}
          >
            <Layers className="w-3.5 h-3.5 text-blue-500" />
            <span>Memory Stream</span>
          </button>
          <button
            onClick={() => setActiveTab("dream")}
            className={`px-3 py-2 border-b-2 rounded-t-md transition-all flex items-center gap-1.5 ${
              activeTab === "dream"
                ? "border-purple-600 text-purple-700 bg-white shadow-sm font-semibold"
                : "border-transparent text-slate-600 hover:text-slate-900"
            }`}
          >
            <Moon className="w-3.5 h-3.5 text-indigo-500" />
            <span>Sleep & Dreaming</span>
          </button>
        </div>

        {/* Tab Content Area */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {isLoading && (
            <div className="flex items-center justify-center py-10 gap-2 text-xs text-slate-400">
              <RefreshCw className="w-4 h-4 animate-spin text-purple-500" />
              <span>Loading cognitive memory state...</span>
            </div>
          )}

          {!isLoading && activeTab === "dossier" && (
            <LivingDossierTab
              entities={dossierEntities}
              onEdit={(entity) => {
                setEditingEntity(entity);
                setIsEditModalOpen(true);
              }}
              onDelete={handleDeleteNode}
            />
          )}

          {!isLoading && activeTab === "stream" && (
            <MemoryStreamTab
              memories={streamMemories}
              filter={streamFilter}
              onFilterChange={setStreamFilter}
              onDelete={handleDeleteNode}
            />
          )}

          {!isLoading && activeTab === "dream" && (
            <SleepDreamTab
              dreamStatus={dreamStatus}
              isDreaming={isDreaming}
              dreamResult={dreamResult}
              onRunDreamCycle={handleRunDreamCycle}
            />
          )}
        </div>
      </aside>

      {/* Edit Entity Modal */}
      <EditEntityModal
        entity={editingEntity}
        isOpen={isEditModalOpen}
        onClose={() => {
          setIsEditModalOpen(false);
          setEditingEntity(null);
        }}
        onSave={handleSaveEntity}
      />
    </>
  );
}
