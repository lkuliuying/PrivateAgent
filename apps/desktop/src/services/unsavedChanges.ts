import { reactive } from "vue";

type DraftGuard = { dirty: () => boolean; save: () => Promise<boolean>; discard: () => void | Promise<void> };
let active: DraftGuard | null = null;
let resolvePending: ((allowed: boolean) => void) | null = null;
export const unsavedChanges = reactive({ open: false, saving: false, error: "" });

/** 只保存内存中的回调，不把配置或密钥草稿写入浏览器存储。 */
export function registerDraftGuard(guard: DraftGuard): () => void {
  active = guard;
  return () => {
    if (active !== guard) return;
    active = null;
    finish(false);
  };
}

export async function allowDiscardingChanges(): Promise<boolean> {
  if (resolvePending) return false;
  if (!active?.dirty()) return true;
  unsavedChanges.open = true;
  unsavedChanges.error = "";
  return new Promise<boolean>((resolve) => { resolvePending = resolve; });
}

function finish(allowed: boolean): void {
  const resolve = resolvePending;
  resolvePending = null;
  unsavedChanges.open = false;
  unsavedChanges.error = "";
  resolve?.(allowed);
}

export async function resolveUnsavedChanges(action: "save" | "discard" | "cancel"): Promise<void> {
  if (!resolvePending || unsavedChanges.saving) return;
  if (action === "cancel") return finish(false);
  const guard = active;
  if (!guard) return finish(false);
  unsavedChanges.saving = true;
  try {
    if (action === "discard") { await guard.discard(); return finish(true); }
    if (await guard.save()) finish(true);
    else unsavedChanges.error = "保存未完成，输入已保留。请留在此处查看并处理配置提示。";
  } catch {
    unsavedChanges.error = action === "discard" ? "草稿尚未清除，未离开当前页面。请重试。" : "保存未完成，输入已保留。请留在此处重试。";
  } finally { unsavedChanges.saving = false; }
}
