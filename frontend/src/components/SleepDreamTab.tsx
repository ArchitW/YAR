import { Moon, Sparkles, Activity, CheckCircle } from "lucide-react";
import { DreamStatusData } from "../types";

interface SleepDreamTabProps {
  dreamStatus: DreamStatusData | null;
  isDreaming: boolean;
  dreamResult: string | null;
  onRunDreamCycle: () => void;
}

export default function SleepDreamTab({
  dreamStatus,
  isDreaming,
  dreamResult,
  onRunDreamCycle,
}: SleepDreamTabProps) {
  return (
    <div className="space-y-4">
      {/* Cognitive Health Cards */}
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="p-3 bg-purple-50 border border-purple-100 rounded-xl">
          <span className="text-[10px] uppercase font-bold text-purple-600 block">
            Active Nodes
          </span>
          <span className="text-xl font-bold font-mono text-purple-900">
            {dreamStatus?.active_nodes ?? 0}
          </span>
        </div>
        <div className="p-3 bg-amber-50 border border-amber-100 rounded-xl">
          <span className="text-[10px] uppercase font-bold text-amber-600 block">
            Pruned / Invalidated
          </span>
          <span className="text-xl font-bold font-mono text-amber-900">
            {dreamStatus?.invalidated_nodes ?? 0}
          </span>
        </div>
        <div className="p-3 bg-blue-50 border border-blue-100 rounded-xl">
          <span className="text-[10px] uppercase font-bold text-blue-600 block">
            Total Edges
          </span>
          <span className="text-xl font-bold font-mono text-blue-900">
            {dreamStatus?.total_edges ?? 0}
          </span>
        </div>
        <div className="p-3 bg-emerald-50 border border-emerald-100 rounded-xl">
          <span className="text-[10px] uppercase font-bold text-emerald-600 block">
            Total Ingested
          </span>
          <span className="text-xl font-bold font-mono text-emerald-900">
            {dreamStatus?.total_memories ?? 0}
          </span>
        </div>
      </div>

      {/* Node Breakdown */}
      {dreamStatus && dreamStatus.counts_by_type && (
        <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
          <span className="text-[11px] font-semibold text-slate-700 block mb-2">
            Active Memory Topology
          </span>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(dreamStatus.counts_by_type).map(([t, count]) => (
              <span
                key={t}
                className="px-2 py-0.5 bg-white border border-slate-200 rounded text-[10px] font-mono text-slate-700"
              >
                {t}: <strong className="text-slate-900">{count}</strong>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Consolidation Action Trigger */}
      <div className="p-4 bg-gradient-to-br from-indigo-50/70 to-purple-50/70 border border-indigo-100 rounded-xl space-y-3">
        <div className="flex items-center gap-2">
          <Moon className="w-4 h-4 text-indigo-600" />
          <h4 className="text-xs font-semibold text-slate-800">
            Cognitive Sleep Consolidation
          </h4>
        </div>
        <p className="text-[11px] text-slate-600 leading-relaxed">
          Triggers NREM synaptic pruning (decaying old, low-salience memories) and REM associative synthesis (surfacing hidden cross-document insights).
        </p>

        {dreamResult && (
          <div className="p-2.5 bg-white border border-indigo-200 rounded-lg text-xs text-indigo-900 flex items-start gap-1.5">
            <CheckCircle className="w-3.5 h-3.5 text-indigo-600 mt-0.5 shrink-0" />
            <span>{dreamResult}</span>
          </div>
        )}

        <button
          onClick={onRunDreamCycle}
          disabled={isDreaming}
          className="w-full py-2 px-3 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 rounded-lg shadow-sm transition-all flex items-center justify-center gap-2"
        >
          {isDreaming ? (
            <>
              <Activity className="w-3.5 h-3.5 animate-spin" />
              <span>Dreaming & Consolidating...</span>
            </>
          ) : (
            <>
              <Sparkles className="w-3.5 h-3.5" />
              <span>Run Consolidation Cycle</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
}
