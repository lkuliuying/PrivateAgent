import { requestJson } from "./modelProviders";
import type { TaskAttachment } from "../types";
export interface MaterialDraft { id: string; title: string; session_id: number | null; scope_key: string | null; revision: number | null }
export interface MaterialSession { id: number; title: string; messages: number }
export interface StoredMaterial extends TaskAttachment { project_name: string; read_status: string; drafts: MaterialDraft[]; sessions: MaterialSession[] }
export interface AttachmentStorage { total: number; size_bytes: number; offset: number; items: StoredMaterial[]; cache_bytes: number; cache_policy: string; retention: string }
export interface CleanupPreview { version: string; attachment_id: string; draft_id: string; name: string; draft: MaterialDraft; remaining_drafts: number; sessions: MaterialSession[]; reclaim_bytes: number }
export function getAttachmentStorage(offset = 0): Promise<AttachmentStorage> { return requestJson(`/attachment-storage?offset=${offset}&limit=30`); }
export function previewAttachmentCleanup(attachmentId: string, draftId: string): Promise<CleanupPreview> {
  return requestJson("/attachment-storage/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ attachment_id: attachmentId, draft_id: draftId }) });
}
export function applyAttachmentCleanup(preview: CleanupPreview): Promise<{ removed: boolean; cleanup_pending: boolean }> {
  return requestJson("/attachment-storage/cleanup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ attachment_id: preview.attachment_id, draft_id: preview.draft_id, version: preview.version }) });
}
