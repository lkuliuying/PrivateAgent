import { afterEach, describe, expect, it, vi } from "vitest";
import { requestPrivateRuntime } from "./privateTransport";

const host = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({
  invoke: host.invoke,
  Channel: class { onmessage: (frame: unknown) => void = () => undefined; },
}));
afterEach(() => vi.clearAllMocks());

describe("私有运行时通信", () => {
  it("通过 Tauri 管道交付 JSON 与中文流，不发起 fetch", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    host.invoke.mockImplementation(async (name, args) => {
      if (name !== "local_executor_request") return;
      expect(args.request.path).toBe("/projects");
      expect(args.request.headers.authorization).toBe("Bearer fixture");
      queueMicrotask(() => {
        args.onEvent.onmessage({ id: args.id, status: 200, headers: { "content-type": "application/json" } });
        args.onEvent.onmessage({ id: args.id, data: '{"name":"中文项目"}' });
        args.onEvent.onmessage({ id: args.id, done: true });
      });
    });
    const response = await requestPrivateRuntime("/projects", { headers: { Authorization: "Bearer fixture" } });
    expect(await response.json()).toEqual({ name: "中文项目" });
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("取消已建立的流会停止管道订阅并使读取失败", async () => {
    host.invoke.mockImplementation(async (name, args) => {
      if (name === "local_executor_request") queueMicrotask(() => args.onEvent.onmessage({ id: args.id, status: 200 }));
    });
    const abort = new AbortController();
    const response = await requestPrivateRuntime("/agent-runs/run/events/stream", { signal: abort.signal });
    const body = response.text();
    abort.abort();
    await expect(body).rejects.toThrow();
    expect(host.invoke).toHaveBeenCalledWith("local_executor_cancel", expect.objectContaining({ id: expect.any(String) }));
  });

  it("无效请求标识与宿主错误均失败关闭", async () => {
    host.invoke.mockImplementation(async (_name, args) => {
      if (!args.onEvent) return;
      queueMicrotask(() => args.onEvent.onmessage({ id: "wrong", status: 200 }));
    });
    await expect(requestPrivateRuntime("/projects", {})).rejects.toThrow("标识不匹配");
    host.invoke.mockRejectedValueOnce(new Error("管道断开"));
    await expect(requestPrivateRuntime("/projects", {})).rejects.toThrow("管道断开");
  });
});
