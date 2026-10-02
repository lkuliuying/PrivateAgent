import { describe, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { clearModelProviderDraft, readModelProviderDraft, writeModelProviderDraft } from "./modelProviderDraft";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(), isTauri: () => true }));
describe("加密模型草稿调用", () => {
  it("写入串行，清除等待旧写入结束，读取不会恢复已放弃的旧密钥", async () => {
    let release!: () => void;
    vi.mocked(invoke).mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve; }));
    const first = writeModelProviderDraft("synthetic-first");
    const second = writeModelProviderDraft("synthetic-second");
    const clear = clearModelProviderDraft();
    await Promise.resolve();
    await Promise.resolve();
    expect(invoke).toHaveBeenCalledTimes(1);
    release();
    await Promise.all([first, second, clear]);
    expect(vi.mocked(invoke).mock.calls.map(call => call[0])).toEqual([
      "write_model_provider_draft", "write_model_provider_draft", "clear_model_provider_draft",
    ]);
    vi.mocked(invoke).mockResolvedValueOnce(null);
    expect(await readModelProviderDraft()).toBeNull();
  });
  it("写入失败可以重试，错误不会带出密钥", async () => {
    vi.mocked(invoke).mockRejectedValueOnce(new Error("encrypted store unavailable"));
    await expect(writeModelProviderDraft("synthetic-only")).rejects.toThrow("encrypted store unavailable");
    vi.mocked(invoke).mockResolvedValueOnce(undefined);
    await expect(writeModelProviderDraft("synthetic-retry")).resolves.toBeUndefined();
  });
});
