import { apiFetch, ensureApiBase } from "./http";
import type {
  BatchImportItem,
  ChunkDetail,
  CompareResult,
  DocumentItem,
  ExportResult,
  SectionSummary,
} from "../types";

// ---- 文档 / 知识库 ----
export async function listDocuments(
  search?: string,
  status?: string,
  enabled?: boolean,
  docType?: string,
  topic?: string,
  language?: string
): Promise<DocumentItem[]> {
  const base = await ensureApiBase();
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (status) params.set("status", status);
  if (enabled !== undefined) params.set("enabled", String(enabled));
  if (docType) params.set("doc_type", docType);
  if (topic) params.set("topic", topic);
  if (language) params.set("language", language);
  const qs = params.toString() ? `?${params}` : "";
  const r = await apiFetch(`${base}/documents${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function importDocument(file: File): Promise<DocumentItem> {
  const base = await ensureApiBase();
  const fd = new FormData();
  fd.append("file", file);
  const r = await apiFetch(`${base}/documents/import`, { method: "POST", body: fd });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function deleteDocument(id: number): Promise<void> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/documents/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
}

export async function retryDocument(id: number): Promise<DocumentItem> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/documents/${id}/retry`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 知识库增强（第二阶段 M3）----
export async function batchImportDocuments(
  files: File[]
): Promise<BatchImportItem[]> {
  const base = await ensureApiBase();
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  const r = await apiFetch(`${base}/documents/batch-import`, {
    method: "POST",
    body: fd,
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function patchDocument(
  id: number,
  enabled: boolean,
  metadata?: {
    doc_type?: string;
    topic?: string;
    tags?: string[];
    language?: string;
    project_id?: number;
  }
): Promise<DocumentItem> {
  const base = await ensureApiBase();
  const body: Record<string, unknown> = { enabled };
  if (metadata) Object.assign(body, metadata);
  const r = await apiFetch(`${base}/documents/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function reindexDocument(id: number): Promise<DocumentItem> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/documents/${id}/reindex`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function reindexAllDocuments(): Promise<{
  triggered: number;
  skipped: number;
}> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/documents/reindex-all`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getChunk(id: number): Promise<ChunkDetail> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/chunks/${id}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 文档工作台（第三阶段 M4）----
export async function summarizeSections(
  docId: number
): Promise<SectionSummary[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/documents/${docId}/sections/summary`, {
    method: "POST",
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json().then((b) => b.sections);
}

export async function compareDocuments(
  docIds: number[]
): Promise<CompareResult> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/documents/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_ids: docIds }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function exportMarkdown(
  content: string,
  filename: string,
  targetDir: string
): Promise<ExportResult> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/documents/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, filename, target_dir: targetDir }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function importNoteToKb(
  title: string,
  content: string
): Promise<BatchImportItem> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/documents/import-note`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, content }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}
