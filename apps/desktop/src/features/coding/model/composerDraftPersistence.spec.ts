import { beforeEach, describe, expect, it, vi } from "vitest";
import { codingFetchJson } from "../api/codingHttp";
import { acknowledgeDurableDraft, inspectComposerDraft, loadComposerDraft, persistComposerDraft, resolveComposerDraft, type DurableComposerDraft } from "./composerDraftPersistence";
vi.mock("../api/codingHttp", async (original) => ({ ...await original<typeof import("../api/codingHttp")>(), codingFetchJson: vi.fn() }));
let ordinal = 700;
let scope: string;
let remote: { revision: number; mutation_id: string | null; data: DurableComposerDraft | null; updated_at: string | null };
let loseResponse = false;
function data(text = "材料草稿"): DurableComposerDraft {
  return { text, chips: [], attachments: [], draftId: "a".repeat(32), clientRequestId: "original-request", requestSignature: "original-signature" };
}
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  scope = `pa_coding_draft_v2_${++ordinal}_801_new`;
  remote = { revision: 0, mutation_id: null, data: null, updated_at: null };
  loseResponse = false;
  vi.mocked(codingFetchJson).mockImplementation(async (path, init) => {
    if (!init) return structuredClone(remote);
    const body = JSON.parse(init.body as string);
    if (init.method === "PUT") {
      if (body.revision !== remote.revision) throw new Error("revision conflict");
      remote = { revision: remote.revision + 1, mutation_id: body.mutation_id, data: structuredClone(body.data), updated_at: "saved" };
      if (loseResponse) { loseResponse = false; throw new Error("response lost"); }
      return structuredClone(remote);
    }
    if (path.endsWith("/acknowledge")) {
      if (remote.data?.text === body.message && remote.data?.clientRequestId === body.client_request_id) {
        remote = { ...remote, revision: remote.revision + 1, data: data("") };
      }
      return structuredClone(remote);
    }
    throw new Error("unexpected operation");
  });
});
describe("本机正文草稿持久化", () => {
  it("从旧浏览器草稿迁移后，清空浏览器存储仍恢复正文与请求标识", async () => {
    localStorage.setItem(scope, JSON.stringify(data()));
    expect(await loadComposerDraft(scope)).toEqual(data());
    localStorage.clear();
    expect(await loadComposerDraft(scope)).toEqual(data());
    expect(remote.revision).toBe(1);
  });
  it("没有读取的持久版本不能被旧缓存静默覆盖", async () => {
    remote = { ...remote, revision: 4, data: data("更新版本") };
    await expect(persistComposerDraft(scope, data("旧输入"))).rejects.toThrow("尚未核对");
    expect(remote.data?.text).toBe("更新版本");
  });
  it("保存响应丢失后先核对原操作，下一次保存不会误判冲突", async () => {
    await loadComposerDraft(scope);
    loseResponse = true;
    await expect(persistComposerDraft(scope, data())).rejects.toThrow("response lost");
    await persistComposerDraft(scope, data("接着编辑"));
    expect(remote.data?.text).toBe("接着编辑");
    expect(remote.revision).toBe(2);
  });
  it("未知结果遇到其他窗口更新时保留本地输入并要求核对", async () => {
    await loadComposerDraft(scope);
    loseResponse = true;
    await expect(persistComposerDraft(scope, data())).rejects.toThrow();
    remote = { ...remote, revision: 9, mutation_id: "another", data: data("其他窗口") };
    await expect(persistComposerDraft(scope, data("我继续编辑"))).rejects.toThrow("其他窗口");
    expect(remote.data?.text).toBe("其他窗口");
    const inspected = await inspectComposerDraft(scope);
    await resolveComposerDraft(scope, data("核对后保留我的输入"), inspected.revision);
    expect(remote.data?.text).toBe("核对后保留我的输入");
  });
  it("核对弹窗打开后数据再次变化，旧确认仍不能覆盖", async () => {
    await loadComposerDraft(scope);
    await persistComposerDraft(scope, data());
    const inspected = await inspectComposerDraft(scope);
    remote = { ...remote, revision: remote.revision + 1, data: data("弹窗之后的版本") };
    await expect(resolveComposerDraft(scope, data("当前窗口"), inspected.revision)).rejects.toThrow("conflict");
    expect(remote.data?.text).toBe("弹窗之后的版本");
  });
  it("迟到发送回执不会清除更新后的草稿", async () => {
    await loadComposerDraft(scope);
    await persistComposerDraft(scope, data());
    await persistComposerDraft(scope, data("新的输入"));
    await acknowledgeDurableDraft(scope, "original-request", "材料草稿", []);
    expect((await loadComposerDraft(scope))?.text).toBe("新的输入");
  });
  it("WebView 存储不可写时，本机保存仍可完成", async () => {
    await loadComposerDraft(scope);
    const failing = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); });
    try {
      await persistComposerDraft(scope, data());
      expect((await loadComposerDraft(scope))?.text).toBe("材料草稿");
    } finally { failing.mockRestore(); }
  });
});

it("旧保存的响应不覆盖等待期间的新缓存输入", async () => {
  await loadComposerDraft(scope);
  const handler = vi.mocked(codingFetchJson).getMockImplementation()!;
  let finish!: () => void;
  vi.mocked(codingFetchJson).mockImplementationOnce(async (path, init) => {
    const result = await handler(path, init);
    await new Promise<void>(resolve => { finish = resolve; });
    return result;
  });
  const pending = persistComposerDraft(scope, data("已提交写入"));
  await vi.waitFor(() => expect(finish).toBeDefined());
  const cached = JSON.parse(localStorage.getItem(scope)!);
  localStorage.setItem(scope, JSON.stringify({ ...cached, ...data("新的输入"), _pending: true }));
  finish(); await pending;
  const latest = JSON.parse(localStorage.getItem(scope)!);
  expect(latest.text).toBe("新的输入");
  expect(latest._revision).toBe(remote.revision);
  expect(await loadComposerDraft(scope)).toEqual(data("新的输入"));
});
