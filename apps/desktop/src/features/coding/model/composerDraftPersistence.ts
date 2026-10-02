import type { TaskAttachment } from "../../../types";
import type { CodingFileHint } from "./runContracts";
import { codingFetchJson, codingJsonInit } from "../api/codingHttp";

export function draftMessage(saved: { text?: string; chips?: Array<{ relPath: string }>; attachments?: unknown[] }): string {
  return [saved.text?.trim() ?? "", ...(saved.chips ?? []).map(item => "@" + item.relPath)].filter(Boolean).join("\n") || (saved.attachments?.length ? "附件材料" : "");
}

export interface DurableComposerDraft {
  text: string;
  chips: CodingFileHint[];
  attachments: TaskAttachment[];
  draftId: string;
  clientRequestId: string;
  requestSignature: string;
}
interface Envelope { revision: number; mutation_id: string | null; data: DurableComposerDraft | null; updated_at: string | null }
interface CachedDraft extends DurableComposerDraft { _revision?: number; _pending?: boolean; _mutation?: string }
const queues = new Map<string, Promise<unknown>>();
const revisions = new Map<string, number>();
const uncertain = new Map<string, { revision: number; mutation: string }>();
const freshId = () => crypto.randomUUID().replace(/-/g, "");
const endpoint = (key: string) => "/composer-drafts/" + encodeURIComponent(key);

function ordered<T>(key: string, operation: () => Promise<T>): Promise<T> {
  const result = (queues.get(key) ?? Promise.resolve()).catch(() => undefined).then(operation);
  queues.set(key, result);
  void result.finally(() => { if (queues.get(key) === result) queues.delete(key); }).catch(() => undefined);
  return result;
}
export function cachedComposerDraft(key: string): CachedDraft | null {
  const raw = localStorage.getItem(key);
  return raw ? JSON.parse(raw) as CachedDraft : null;
}
function cache(key: string, value: CachedDraft): void {
  try { localStorage.setItem(key, JSON.stringify(value)); }
  catch { /* 已确认的正文以本机数据库为准，WebView 缓存不可用不阻止使用。 */ }
}
function normalize(value: Partial<DurableComposerDraft>): DurableComposerDraft {
  return { text: value.text ?? "", chips: value.chips ?? [], attachments: value.attachments ?? [],
    draftId: value.draftId || freshId(), clientRequestId: value.clientRequestId ?? "", requestSignature: value.requestSignature ?? "" };
}
async function reconcile(key: string): Promise<Envelope> {
  const remote = await codingFetchJson<Envelope>(endpoint(key));
  const previous = uncertain.get(key);
  if (previous && remote.revision !== previous.revision && remote.mutation_id !== previous.mutation) {
    throw new Error("草稿在其他窗口中发生变化。当前输入仍保留，请核对后再保存。");
  }
  uncertain.delete(key);
  revisions.set(key, remote.revision);
  return remote;
}
function cacheWriteProgress(key: string, data: DurableComposerDraft, revision: number, mutation?: string): void {
  let latest: CachedDraft | null = null;
  try { latest = cachedComposerDraft(key); } catch { /* 缓存不可用时仍保留本机保存结果。 */ }
  // 请求在途时用户可能继续输入，旧写入回执只能推进版本，不能覆盖更新的缓存正文。
  if (latest?._pending && JSON.stringify(normalize(latest)) !== JSON.stringify(data)) {
    cache(key, { ...latest, _revision: revision, _pending: true, _mutation: mutation });
  } else cache(key, { ...data, _revision: revision, _pending: Boolean(mutation), _mutation: mutation });
}
async function write(key: string, data: DurableComposerDraft): Promise<void> {
  if (!revisions.has(key)) {
    let cached: CachedDraft | null = null;
    try { cached = cachedComposerDraft(key); } catch { /* 无缓存时不能覆盖尚未读取的持久版本。 */ }
    const remote = await reconcile(key);
    if (remote.revision !== 0 && remote.revision !== cached?._revision && remote.mutation_id !== cached?._mutation) {
      revisions.delete(key);
      throw new Error("本机存在尚未核对的草稿，未覆盖已保存版本。请先查看本机草稿。");
    }
  } else if (uncertain.has(key)) await reconcile(key);
  const revision = revisions.get(key)!;
  const mutation = freshId();
  cacheWriteProgress(key, data, revision, mutation);
  uncertain.set(key, { revision, mutation });
  const result = await codingFetchJson<Envelope>(endpoint(key), codingJsonInit("PUT", { revision, mutation_id: mutation, data }));
  revisions.set(key, result.revision);
  uncertain.delete(key);
  cacheWriteProgress(key, data, result.revision);
}
export function persistComposerDraft(key: string, data: DurableComposerDraft): Promise<void> {
  return ordered(key, () => write(key, data));
}
export function loadComposerDraft(key: string): Promise<DurableComposerDraft | null> {
  return ordered(key, async () => {
    let saved: CachedDraft | null = null;
    try { saved = cachedComposerDraft(key); } catch { /* 缓存损坏时仍读取本机数据库，原缓存不主动删除。 */ }
    const remote = await reconcile(key);
    if (saved && (remote.revision === 0 || saved._pending)) {
      if (saved._pending && remote.revision !== (saved._revision ?? 0) && remote.mutation_id !== saved._mutation) {
        throw new Error("本机已有更新的草稿；浏览器中未确认的输入仍保留，请先核对两个版本。");
      }
      const data = normalize(saved);
      await write(key, data);
      return data;
    }
    if (remote.data) cache(key, { ...remote.data, _revision: remote.revision, _pending: false });
    return remote.data;
  });
}
export function acknowledgeDurableDraft(key: string, requestId: string, message: string, attachmentIds: string[]): Promise<void> {
  return ordered(key, async () => {
    const result = await codingFetchJson<Envelope>(endpoint(key) + "/acknowledge", codingJsonInit("POST", {
      client_request_id: requestId, message, attachment_ids: attachmentIds,
    }));
    revisions.set(key, result.revision);
    let saved: CachedDraft | null = null;
    try { saved = cachedComposerDraft(key); } catch { /* 回执已写入本机库；缓存访问失败不改变发送结果。 */ }
    const submitted = saved && saved.clientRequestId === requestId && draftMessage(saved) === message
      && JSON.stringify(saved.attachments.map(item => item.id)) === JSON.stringify(attachmentIds);
    if (result.data && submitted) cache(key, { ...result.data, _revision: result.revision, _pending: false });
    window.dispatchEvent(new CustomEvent("pa:draft-acknowledged", { detail: { key, requestId, message, attachmentIds } }));
  });
}
export function transferDurableDraft(source: string, destination: string, data: DurableComposerDraft): Promise<void> {
  return ordered(source, async () => {
    if (!revisions.has(source)) await reconcile(source);
    const result = await codingFetchJson<Envelope>(endpoint(source) + "/transfer", codingJsonInit("POST", {
      destination, revision: revisions.get(source), draft_id: data.draftId, data,
    }));
    revisions.set(destination, result.revision);
    const origin = await reconcile(source);
    if (result.data) cache(destination, { ...result.data, _revision: result.revision, _pending: false });
    if (origin.data) cache(source, { ...origin.data, _revision: origin.revision, _pending: false });
  });
}

export function inspectComposerDraft(key: string): Promise<Envelope> {
  return codingFetchJson<Envelope>(endpoint(key));
}
export function resolveComposerDraft(key: string, data: DurableComposerDraft, reviewedRevision: number): Promise<void> {
  return ordered(key, async () => {
    // 用户核对的版本仍由后端比较；确认窗口打开期间的新保存不会被覆盖。
    uncertain.delete(key);
    revisions.set(key, reviewedRevision);
    await write(key, data);
  });
}
