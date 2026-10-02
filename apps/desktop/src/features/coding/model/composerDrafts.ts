import type { CodingFirstTurnPayload } from "./contracts";
import { acknowledgeDurableDraft, transferDurableDraft, draftMessage } from "./composerDraftPersistence";

export function composerDraftKey(projectId: number | null, workspaceId: number | null, threadId: number | null): string {
  return "pa_coding_draft_v2_" + (projectId ?? "none") + "_" + (workspaceId ?? "none") + "_" + (threadId ?? "new");
}
export { draftMessage } from "./composerDraftPersistence";
export async function acknowledgeComposerDraft(key: string, requestId: string, message: string, attachmentIds: string[], durable = false): Promise<void> {
  if (durable) return acknowledgeDurableDraft(key, requestId, message, attachmentIds);
  const raw = window.localStorage.getItem(key);
  if (!raw) return;
  const saved = JSON.parse(raw);
  if (saved.clientRequestId !== requestId || draftMessage(saved) !== message
      || JSON.stringify((saved.attachments ?? []).map((item: { id: string }) => item.id)) !== JSON.stringify(attachmentIds)) return;
  // 只清除被服务确认的原输入；等待期间新写的草稿继续保留。
  window.localStorage.setItem(key, JSON.stringify({ text: "", chips: [], attachments: [] }));
  window.dispatchEvent(new CustomEvent("pa:draft-acknowledged", { detail: key }));
}
export async function transferFirstTurnDraft(payload: CodingFirstTurnPayload, projectId: number, workspaceId: number, threadId: number, durable = false): Promise<void> {
  if (!payload.draftId) return;
  const destination = composerDraftKey(projectId, workspaceId, threadId);
  if (durable && payload.draftStorageKey) return transferDurableDraft(payload.draftStorageKey, destination, {
    text: payload.text ?? payload.message, chips: payload.projectFiles ?? [], attachments: payload.attachments ?? [],
    draftId: payload.draftId, clientRequestId: payload.clientRequestId ?? "", requestSignature: payload.requestSignature ?? "",
  });
  // 先持久化目标草稿，再清理来源；存储失败时保留原始输入。
  window.localStorage.setItem(destination, JSON.stringify({
    text: payload.text ?? payload.message, chips: payload.projectFiles ?? [], attachments: payload.attachments ?? [],
    draftId: payload.draftId, clientRequestId: payload.clientRequestId, requestSignature: payload.requestSignature,
  }));
  if (payload.draftStorageKey && payload.draftStorageKey !== destination) window.localStorage.removeItem(payload.draftStorageKey);
}
