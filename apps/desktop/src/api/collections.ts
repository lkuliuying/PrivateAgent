import { apiFetch, ensureApiBase } from "./http";
import type {
  CollectionDetail,
  CollectionDetailItem,
  DocumentCollection,
  DocumentExtraction,
  ExtractRequest,
  OcrResult,
  TemplateReportRequest,
  TemplateReportResponse,
} from "../types";

// ---- 文档集合 / 抽取 / 模板报告（第四阶段 M3）----
export async function listDocumentCollections(): Promise<DocumentCollection[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/document-collections`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createDocumentCollection(data: {
  title: string;
  goal?: string;
  tags?: string[];
}): Promise<DocumentCollection> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/document-collections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function getDocumentCollection(
  id: number
): Promise<CollectionDetail> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/document-collections/${id}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function updateDocumentCollection(
  id: number,
  data: { title?: string; goal?: string; tags?: string[] }
): Promise<DocumentCollection> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/document-collections/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function deleteDocumentCollection(id: number): Promise<void> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/document-collections/${id}`, { method: "DELETE" });
  if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
}

export async function addCollectionItem(
  collectionId: number,
  docId: number
): Promise<CollectionDetailItem> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/document-collections/${collectionId}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_id: docId }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function removeCollectionItem(
  collectionId: number,
  docId: number
): Promise<void> {
  const base = await ensureApiBase();
  const r = await apiFetch(
    `${base}/document-collections/${collectionId}/items/${docId}`,
    { method: "DELETE" }
  );
  if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
}

export async function extractDocument(
  docId: number,
  kind: ExtractRequest["kind"]
): Promise<DocumentExtraction> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/documents/${docId}/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function extractCollection(
  collectionId: number,
  kind: ExtractRequest["kind"]
): Promise<DocumentExtraction> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/document-collections/${collectionId}/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function templateReport(
  req: TemplateReportRequest
): Promise<TemplateReportResponse> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/documents/template-report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function ocrDocument(docId: number): Promise<OcrResult> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/documents/${docId}/ocr`, { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function listDocumentExtractions(
  docId: number,
  kind?: string
): Promise<DocumentExtraction[]> {
  const base = await ensureApiBase();
  const qs = kind ? `?kind=${kind}` : "";
  const r = await apiFetch(`${base}/documents/${docId}/extractions${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function listCollectionExtractions(
  collectionId: number,
  kind?: string
): Promise<DocumentExtraction[]> {
  const base = await ensureApiBase();
  const qs = kind ? `?kind=${kind}` : "";
  const r = await apiFetch(
    `${base}/document-collections/${collectionId}/extractions${qs}`
  );
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
