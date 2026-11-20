import { useState, useRef, useEffect } from "react";
import { FolderGit2, ChevronDown, Plus, Settings, Check } from "lucide-react";
import { Workspace } from "../types";

interface WorkspaceSelectorProps {
  workspaces: Workspace[];
  activeWorkspace: Workspace | null;
  onSelectWorkspace: (workspace: Workspace) => void;
  onOpenCreateModal: () => void;
  onOpenEditModal: () => void;
}

export default function WorkspaceSelector({
  workspaces,
  activeWorkspace,
  onSelectWorkspace,
  onOpenCreateModal,
  onOpenEditModal,
}: WorkspaceSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className="relative inline-block text-left" ref={dropdownRef}>
      <div className="flex items-center gap-1 bg-slate-100/80 border border-slate-200 rounded-lg p-1">
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          aria-expanded={isOpen}
          aria-label="Select active workspace"
          className="flex items-center gap-2 px-2.5 py-1 text-xs font-medium text-slate-700 hover:text-slate-900 rounded-md transition-colors"
        >
          <FolderGit2 className="w-3.5 h-3.5 text-blue-600" />
          <span className="max-w-[140px] truncate">
            {activeWorkspace ? activeWorkspace.name : "Select Workspace"}
          </span>
          <ChevronDown className="w-3 h-3 text-slate-400" />
        </button>

        {activeWorkspace && (
          <button
            type="button"
            onClick={onOpenEditModal}
            aria-label="Workspace settings"
            title="Workspace settings"
            className="p-1 text-slate-400 hover:text-slate-700 rounded-md hover:bg-slate-200/60 transition-colors"
          >
            <Settings className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {isOpen && (
        <div className="absolute left-0 mt-1.5 w-64 origin-top-left rounded-xl bg-white border border-slate-200 shadow-xl z-50 py-1 focus:outline-none">
          <div className="px-3 py-2 border-b border-slate-100 flex items-center justify-between">
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Workspaces ({workspaces.length})
            </span>
          </div>

          <div className="max-h-60 overflow-y-auto py-1">
            {workspaces.map((ws) => {
              const isSelected = activeWorkspace?.id === ws.id;
              return (
                <button
                  key={ws.id}
                  type="button"
                  onClick={() => {
                    onSelectWorkspace(ws);
                    setIsOpen(false);
                  }}
                  className={`w-full flex items-center justify-between px-3 py-2 text-xs text-left transition-colors ${
                    isSelected
                      ? "bg-blue-50 text-blue-700 font-semibold"
                      : "text-slate-700 hover:bg-slate-50 hover:text-slate-900"
                  }`}
                >
                  <div className="truncate pr-2">
                    <p className="truncate">{ws.name}</p>
                    {ws.description && (
                      <p className="text-[10px] text-slate-400 truncate">{ws.description}</p>
                    )}
                  </div>
                  {isSelected && <Check className="w-3.5 h-3.5 text-blue-600 shrink-0" />}
                </button>
              );
            })}
          </div>

          <div className="border-t border-slate-100 p-1">
            <button
              type="button"
              onClick={() => {
                setIsOpen(false);
                onOpenCreateModal();
              }}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Create Workspace</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
