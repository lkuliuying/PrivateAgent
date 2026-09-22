import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "./http";
import { editMemory, memoryItems, saveSessionMemorySettings, type MemoryItem, type SessionMemorySettings } from "./memories";
import { isLocalProjectPath } from "../services/localExecutor";

vi.mock("./http", () => ({ ensureApiBase: vi.fn().mockResolvedValue("https://account.example.test"), apiFetch: vi.fn() }));
beforeEach(() => vi.clearAllMocks());

it("所有记忆入口走本机路由，携带项目边界、并发版本与取消信号", async () => {
  vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({ id: "m" })));
  const controller = new AbortController();
  await editMemory(7, { id: "m", version: 3 } as MemoryItem, { scope: "project", kind: "project", title: "标题", content: "内容" }, controller.signal);
  const [url, init] = vi.mocked(apiFetch).mock.calls[0];
  const pathname = new URL(String(url)).pathname;
  expect(pathname).toBe("/local-memories/items/m");
  expect(isLocalProjectPath(pathname)).toBe(true);
  expect(new URL(String(url)).searchParams.get("project_id")).toBe("7");
  expect(JSON.parse(String(init?.body)).expected_version).toBe(3);
  expect(init?.signal).toBeInstanceOf(AbortSignal);
});

it("取消在途请求会传递到传输层，并释放超时计时器", async () => {
  vi.useFakeTimers();
  try {
    const controller = new AbortController();
    vi.mocked(apiFetch).mockImplementationOnce((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("已取消", "AbortError")));
    }));
    const pending = memoryItems(null, controller.signal);
    const rejected = expect(pending).rejects.toThrow("已取消");
    await Promise.resolve();
    controller.abort();
    await rejected;
    expect(vi.getTimerCount()).toBe(0);
  } finally { vi.useRealTimers(); }
});

it("会话只提交可编辑字段，不回传召回历史", async () => {
  vi.mocked(apiFetch).mockResolvedValue(new Response("{}"));
  await saveSessionMemorySettings(7, { version: 2, use_memories: false, generate_memories: true, last_recall: { recalled_ids: ["private"] } } as SessionMemorySettings, new AbortController().signal);
  expect(JSON.parse(String(vi.mocked(apiFetch).mock.calls[0][1]?.body))).toEqual({ expected_version: 2, use_memories: false, generate_memories: true });
});

it("保留安全的并发冲突说明", async () => {
  vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({ detail: "记忆已变化" }), { status: 409 }));
  await expect(memoryItems(null, new AbortController().signal)).rejects.toThrow("记忆已变化");
});
