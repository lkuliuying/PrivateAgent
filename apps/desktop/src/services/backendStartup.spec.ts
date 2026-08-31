import { beforeEach, describe, expect, it, vi } from "vitest";
import { backendStartupState, ensureDesktopBackendReady, resetDesktopBackendStartup } from "./backendStartup";

const mocks = vi.hoisted(() => ({
  base: vi.fn(async () => "https://server.example.test"),
  local: vi.fn(() => true),
  start: vi.fn(async () => undefined),
}));
vi.mock("../api/http", () => ({ ensureApiBase: mocks.base }));
vi.mock("./localExecutor", () => ({ startLocalExecutor: mocks.start, usesLocalExecutor: mocks.local }));

describe("服务器账号客户端启动", () => {
  beforeEach(() => {
    resetDesktopBackendStartup();
    vi.clearAllMocks();
    mocks.base.mockResolvedValue("https://server.example.test");
    mocks.local.mockReturnValue(true);
    mocks.start.mockResolvedValue(undefined);
  });
  it("只读取内置账号源站并启动轻量执行器，不启动完整业务后端", async () => {
    await ensureDesktopBackendReady();
    expect(mocks.start).toHaveBeenCalledTimes(1);
    expect(mocks.start).toHaveBeenCalledWith();
    expect(backendStartupState.status).toBe("ready");
  });
  it("并发登录准备共享一次执行器启动", async () => {
    await Promise.all([ensureDesktopBackendReady(), ensureDesktopBackendReady(), ensureDesktopBackendReady()]);
    expect(mocks.start).toHaveBeenCalledTimes(1);
  });
  it("内置地址读取失败时不启动执行器并允许重试", async () => {
    mocks.base.mockRejectedValueOnce(new Error("无法读取内置账号服务"));
    await expect(ensureDesktopBackendReady()).rejects.toThrow("无法读取内置账号服务");
    expect(mocks.start).not.toHaveBeenCalled();
    expect(backendStartupState.status).toBe("error");
    await ensureDesktopBackendReady();
    expect(backendStartupState.status).toBe("ready");
  });
  it("执行器故障不回退到服务器文件系统，重试仍使用同一源站", async () => {
    mocks.start.mockRejectedValueOnce(new Error("本机执行器启动失败"));
    await expect(ensureDesktopBackendReady()).rejects.toThrow("本机执行器启动失败");
    await ensureDesktopBackendReady();
    expect(mocks.start).toHaveBeenCalledTimes(2);
    expect(mocks.start).toHaveBeenLastCalledWith();
  });
  it("浏览器开发只访问账号服务器，不尝试启动本机执行器", async () => {
    mocks.local.mockReturnValue(false);
    await ensureDesktopBackendReady();
    expect(mocks.start).not.toHaveBeenCalled();
    expect(backendStartupState.status).toBe("ready");
  });
});
