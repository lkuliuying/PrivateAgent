import { beforeEach, describe, expect, it, vi } from "vitest";
import { backendStartupState, ensureDesktopBackendReady, resetDesktopBackendStartup } from "./backendStartup";
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
