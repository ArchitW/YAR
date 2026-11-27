export interface Workspace {
  id: number;
  name: string;
  description?: string;
  created_at?: string;
}

export interface Chat {
  id: number;
  workspace_id: number;
  title: string;
  use_local_knowledge: boolean;
  save_to_memory: boolean;
  created_at?: string;
}

export interface DocumentItem {
  id: number;
  workspace_id: number;
  is_master?: boolean;
  name: string;
  source_type?: string;
  file_type?: string;
  status: "indexed" | "queued" | "error" | string;
  size_bytes: number;
  content?: string;
  created_at?: string;
  updated_at?: string;
}

export interface Citation {
  index: number;
  document_id?: number;
  file_name?: string;
  page_number?: number | null;
  section?: string | null;
  chunk_index?: number | null;
  total_chunks?: number | null;
  text?: string;
  chunk_text?: string;
  score?: number;
  is_dream?: boolean;
  dream_title?: string;
  is_web?: boolean;
  url?: string;
  title?: string;
  bbox?: [number, number, number, number] | null;
  page_width?: number | null;
  page_height?: number | null;
}

export interface Message {
  id?: number;
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
  provider?: string;
  model?: string;
  degraded?: boolean;
}

export interface MemoryNodeItem {
  id: string;
  workspace_id: number;
  user_id?: number | null;
  node_type: "episodic_memory" | "entity" | "user_preference" | "concept" | "dream_insight" | string;
  name: string;
  content: string;
  summary?: string | null;
  importance_score: number;
  confidence: number;
  properties?: Record<string, any>;
  access_count: number;
  last_accessed_at?: string | null;
  created_at?: string | null;
  invalidated_at?: string | null;
}

export interface DreamStatusData {
  workspace_id: number;
  total_memories: number;
  active_nodes: number;
  invalidated_nodes: number;
  counts_by_type: Record<string, number>;
  total_edges: number;
}

