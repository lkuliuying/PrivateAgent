import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiConnection, SidecarStartResult } from "../api/tauri";
import {
  backendStartupState,
  ensureDesktopBackendReady,
  resetDesktopBackendStartup,
} from "./backendStartup";

const mocks = vi.hoisted(() => ({
  getApiInfo: vi.fn(async () => ({ name: "PrivateAgent" })),
  hasRemote: vi.fn(() => false),
  setBase: vi.fn(),
  setDefault: vi.fn(),
  isDesktop: vi.fn(() => true),
  getConnection: vi.fn<() => Promise<ApiConnection | null>>(async () => null),
  getStartupError: vi.fn<() => Promise<string | null>>(async () => null),
  startSidecar: vi.fn<() => Promise<SidecarStartResult>>(async () => ({
    ok: true,
    dev_mode: false,
    port: 43123,
    token: "x".repeat(32),
    error: null,
  })),
}));

vi.mock("../api", () => ({ getApiInfo: mocks.getApiInfo }));
vi.mock("../api/http", () => ({
  hasConfiguredRemoteApi: mocks.hasRemote,
  setApiBase: mocks.setBase,
  setApiBaseDefault: mocks.setDefault,
}));
vi.mock("../api/tauri", () => ({
  cmdStartSidecar: mocks.startSidecar,
  getApiConnection: mocks.getConnection,
  getSidecarStartupError: mocks.getStartupError,
  isDesktopRuntime: mocks.isDesktop,
}));

describe("desktop backend startup", () => {
  beforeEach(() => {
    resetDesktopBackendStartup();
    vi.clearAllMocks();
    mocks.hasRemote.mockReturnValue(false);
    mocks.isDesktop.mockReturnValue(true);
    mocks.getConnection.mockResolvedValue(null);
    mocks.getStartupError.mockResolvedValue(null);
    mocks.getApiInfo.mockResolvedValue({ name: "PrivateAgent" });
    mocks.startSidecar.mockResolvedValue({
      ok: true,
      dev_mode: false,
      port: 43123,
      token: "x".repeat(32),
      error: null,
    });
  });

  it("starts the packaged sidecar and waits for its API", async () => {
    await ensureDesktopBackendReady();

    expect(mocks.startSidecar).toHaveBeenCalledTimes(1);
    expect(mocks.setBase).toHaveBeenCalledWith(43123, "x".repeat(32));
    expect(mocks.getApiInfo).toHaveBeenCalledTimes(1);
    expect(backendStartupState.status).toBe("ready");
  });

  it("shares one startup across concurrent auth requests", async () => {
    await Promise.all([
      ensureDesktopBackendReady(),
      ensureDesktopBackendReady(),
      ensureDesktopBackendReady(),
    ]);
    expect(mocks.startSidecar).toHaveBeenCalledTimes(1);
  });

  it("reuses an already running sidecar", async () => {
    mocks.getConnection.mockResolvedValue({ port: 45100, token: "y".repeat(32) });
    await ensureDesktopBackendReady();

    expect(mocks.setBase).toHaveBeenCalledWith(45100, "y".repeat(32));
    expect(mocks.startSidecar).not.toHaveBeenCalled();
  });

  it("leaves remote builds on their build-time API", async () => {
    mocks.hasRemote.mockReturnValue(true);
    await ensureDesktopBackendReady();

    expect(mocks.setDefault).toHaveBeenCalledTimes(1);
    expect(mocks.startSidecar).not.toHaveBeenCalled();
  });

  it("reports sidecar startup failures and permits a retry", async () => {
    mocks.startSidecar.mockResolvedValueOnce({
      ok: false,
      dev_mode: false,
      port: null,
      token: null,
      error: "数据库配置不可用",
    });
    await expect(ensureDesktopBackendReady()).rejects.toThrow("数据库配置不可用");

    await ensureDesktopBackendReady();
    expect(mocks.startSidecar).toHaveBeenCalledTimes(2);
  });

  it("surfaces a terminated sidecar reason without waiting for the full timeout", async () => {
    mocks.getApiInfo.mockRejectedValue(new Error("not ready"));
    mocks.getStartupError.mockResolvedValue(
      "本地数据库正在被另一个 PrivateAgent 或开发后端使用。请关闭其他实例后重试。"
    );

    await expect(ensureDesktopBackendReady()).rejects.toThrow(
      "本地数据库正在被另一个 PrivateAgent 或开发后端使用"
    );
    expect(mocks.getApiInfo).toHaveBeenCalledTimes(1);
    expect(backendStartupState.status).toBe("error");
  });
});
