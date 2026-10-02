import { pickFile } from "../../../api/tauri";
import { codingFetchJson, codingJsonInit } from "./codingHttp";
import type { TaskAttachment } from "../../../types";

export type AttachmentScope = { project_id: number; workspace_id: number; session_id?: number | null };
export type AttachmentOwner = { draft_id?: string; session_id?: number };
export interface AttachmentPage extends TaskAttachment { content: string; offset: number; next_offset: number | null; total_chars: number; page?: number; image_data_url?: string }

export async function pickTaskAttachment(scope: AttachmentScope, draftId: string): Promise<TaskAttachment | null> {
  const source = await pickFile([{ name: "文本、图片和 PDF", extensions: ["png", "jpg", "jpeg", "webp", "pdf", "txt", "md", "json", "csv", "log", "py", "ts", "tsx", "js", "vue", "html", "css", "yaml", "yml", "toml", "xml", "sql", "rs", "go", "java", "c", "cpp", "h"] }]);
  if (!source) return null;
  return codingFetchJson("/task-attachments", codingJsonInit("POST", { ...scope, draft_id: draftId, source_path: source }));
}
export function listDraftAttachments(draftId: string): Promise<TaskAttachment[]> {
  return codingFetchJson("/task-attachments?draft_id=" + encodeURIComponent(draftId));
}
export function readTaskAttachment(id: string, owner: AttachmentOwner, offset = 0, page = 1): Promise<AttachmentPage> {
  const query = new URLSearchParams({ offset: String(offset), limit: "6000", page: String(page) });
  if (owner.draft_id) query.set("draft_id", owner.draft_id);
  else if (owner.session_id) query.set("session_id", String(owner.session_id));
  return codingFetchJson("/task-attachments/" + encodeURIComponent(id) + "/content?" + query);
}
export function removeTaskAttachment(id: string, draftId: string): Promise<{ removed: boolean }> {
  return codingFetchJson("/task-attachments/" + encodeURIComponent(id) + "?draft_id=" + encodeURIComponent(draftId), codingJsonInit("DELETE", {}));
}
export function importTaskAttachment(id: string, owner: AttachmentOwner, relPath: string): Promise<unknown> {
  return codingFetchJson("/task-attachments/" + encodeURIComponent(id) + "/import", codingJsonInit("POST", { ...owner, rel_path: relPath }));
}
