import { ensureApiBase } from "./http";

export interface OcrAvailability {
  available: boolean;
  reason: string;
  engine: string | null;
}

export interface OcrJob {
  id: number;
  doc_id: number | null;
  file_path: string | null;
  source: string;
  status: string;
  engine: string | null;
  output_text: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export async function getOcrAvailability(): Promise<OcrAvailability> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/ocr/availability`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function listOcrJobs(opts?: { status?: string }): Promise<OcrJob[]> {
  const base = await ensureApiBase();
  const qs = new URLSearchParams();
  if (opts?.status) qs.set("status", opts.status);
  const q = qs.toString();
  const r = await fetch(`${base}/ocr-jobs${q ? `?${q}` : ""}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function retryOcrJob(id: number): Promise<OcrJob> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/ocr-jobs/${id}/retry`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
