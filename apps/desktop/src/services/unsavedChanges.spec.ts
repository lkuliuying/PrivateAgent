import { describe, it, expect, vi } from "vitest";
import { allowDiscardingChanges, registerDraftGuard, resolveUnsavedChanges, unsavedChanges } from "./unsavedChanges";

describe("未保存配置守卫", () => {
  it("没有修改时不展示弹窗", async () => {
    const remove = registerDraftGuard({ dirty: () => false, save: vi.fn(), discard: vi.fn() });
    expect(await allowDiscardingChanges()).toBe(true);
    expect(unsavedChanges.open).toBe(false);
    remove();
  });
  it("并发离开请求不会重复执行导航，保存完成后才放行", async () => {
    let complete!: (value: boolean) => void;
    const save = vi.fn(() => new Promise<boolean>(resolve => { complete = resolve; }));
    const remove = registerDraftGuard({ dirty: () => true, save, discard: vi.fn() });
    const first = allowDiscardingChanges();
    expect(await allowDiscardingChanges()).toBe(false);
    const action = resolveUnsavedChanges("save");
    expect(unsavedChanges.saving).toBe(true);
    await resolveUnsavedChanges("discard");
    complete(true);
    await action;
    expect(await first).toBe(true);
    expect(save).toHaveBeenCalledOnce();
    remove();
  });
  it("保存失败保持弹窗，取消不丢弃草稿", async () => {
    const discard = vi.fn();
    const remove = registerDraftGuard({ dirty: () => true, save: async () => false, discard });
    const leaving = allowDiscardingChanges();
    await resolveUnsavedChanges("save");
    expect(unsavedChanges.open).toBe(true);
    await resolveUnsavedChanges("cancel");
    expect(await leaving).toBe(false);
    expect(discard).not.toHaveBeenCalled();
    remove();
  });
});
