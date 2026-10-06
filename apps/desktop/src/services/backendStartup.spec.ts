import { beforeEach, describe, expect, it, vi } from "vitest";
import { backendStartupState, ensureDesktopBackendReady, reconnectDesktopBackend, resetDesktopBackendStartup } from "./backendStartup";
import { getWorkspaceAccessToken } from "../auth/session";
const mocks = vi.hoisted(() => ({ start: vi.fn(), bind: vi.fn() }));
vi.mock("./localExecutor", () => ({ startLocalExecutor: mocks.start, bindLocalAccess: mocks.bind }));
const token = `local-session:${"a".repeat(43)}`;
describe("本机工作台启动", () => {
  beforeEach(() => {
    resetDesktopBackendStartup();
    window.sessionStorage.clear();
    vi.resetAllMocks();
    mocks.start.mockResolvedValue(undefined);
    mocks.bind.mockResolvedValue(token);
  });
  it("首次启动自动创建本机会话并清除旧平台令牌", async () => {
    window.sessionStorage.setItem("pa_access_token", "obsolete");
    await ensureDesktopBackendReady();
    expect(mocks.start).toHaveBeenCalledTimes(1);
    expect(mocks.bind).toHaveBeenCalledTimes(1);
    expect(getWorkspaceAccessToken()).toBe(token);
    expect(window.sessionStorage.getItem("pa_access_token")).toBeNull();
    expect(backendStartupState.status).toBe("ready");
  });
  it("并发入口共享一次启动和绑定", async () => {
    await Promise.all([ensureDesktopBackendReady(), ensureDesktopBackendReady(), ensureDesktopBackendReady()]);
    expect(mocks.start).toHaveBeenCalledTimes(1);
    expect(mocks.bind).toHaveBeenCalledTimes(1);
  });
  it("工作台并发重连共享握手且保持全局就绪", async () => {
    await ensureDesktopBackendReady();
    let finish!: () => void;
    mocks.start.mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; }));
    const first = reconnectDesktopBackend();
    const second = reconnectDesktopBackend();
    expect(first).toBe(second);
    expect(backendStartupState.status).toBe("ready");
    expect(getWorkspaceAccessToken()).toBeNull();
    expect(mocks.start).toHaveBeenCalledTimes(2);
    finish();
    await first;
    expect(mocks.bind).toHaveBeenCalledTimes(2);
    expect(getWorkspaceAccessToken()).toBe(token);
    expect(backendStartupState.status).toBe("ready");
  });
  it("启动与工作台重连交错时共享同一次身份绑定", async () => {
    let finish!: () => void;
    mocks.start.mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; }));
    const starting = ensureDesktopBackendReady();
    const reconnecting = reconnectDesktopBackend();
    finish();
    await Promise.all([starting, reconnecting]);
    expect(mocks.start).toHaveBeenCalledTimes(1);
    expect(mocks.bind).toHaveBeenCalledTimes(1);
    expect(backendStartupState.status).toBe("ready");
  });
  it("工作台重连失败保留挂载状态，后续重试重新握手", async () => {
    await ensureDesktopBackendReady();
    mocks.bind.mockRejectedValueOnce(new Error("身份绑定失败"));
    await expect(reconnectDesktopBackend()).rejects.toThrow("身份绑定失败");
    expect(backendStartupState.status).toBe("ready");
    expect(getWorkspaceAccessToken()).toBeNull();
    await reconnectDesktopBackend();
    expect(mocks.start).toHaveBeenCalledTimes(3);
    expect(getWorkspaceAccessToken()).toBe(token);
  });
  it.each(["start", "bind"] as const)("%s 失败时保留错误且允许重试", async (step) => {
    mocks[step].mockRejectedValueOnce(new Error("本机连接失败"));
    await expect(ensureDesktopBackendReady()).rejects.toThrow("本机连接失败");
    expect(backendStartupState.status).toBe("error");
    expect(getWorkspaceAccessToken()).toBeNull();
    await ensureDesktopBackendReady();
    expect(backendStartupState.status).toBe("ready");
    expect(getWorkspaceAccessToken()).toBe(token);
  });
});
