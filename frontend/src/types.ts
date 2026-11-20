export interface Workspace {
  id: number;
  name: string;
  description?: string;
  created_at?: string;
}

export interface DocumentItem {
  id: number;
  workspace_id: number;
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
