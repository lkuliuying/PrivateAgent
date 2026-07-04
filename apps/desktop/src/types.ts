export interface Session {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: number;
  session_id: number;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
}

/** RAG 引用来源。 */
export interface Source {
  doc_name: string;
  ordinal: number;
  chunk_id: number;
}

export interface ChatEvent {
  type: "token" | "done" | "title" | "error";
  content?: string;
  message_id?: number;
  title?: string;
  message?: string;
  sources?: Source[];
}

export type DocStatus = "pending" | "processing" | "ready" | "failed" | "deleting";

export interface DocumentItem {
  id: number;
  name: string;
  mime_type: string | null;
  size_bytes: number | null;
  content_hash: string | null;
  embedding_model: string | null;
  chunk_count: number;
  status: DocStatus;
  error_message: string | null;
  indexed_at: string | null;
  created_at: string;
  updated_at: string;
}
