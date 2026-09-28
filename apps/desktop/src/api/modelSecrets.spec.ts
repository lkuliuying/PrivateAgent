import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, ensureApiBase } from "./http";
import { cmdClearModelProviderSecret, cmdSetModelProviderSecret } from "./tauri";
import { clearModelProviderRuntimeSecret, updateModelProviderRuntimeSecret } from "./modelProviders";
import { getWorkspaceAccessToken } from "../auth/session";

vi.mock("./http", () => ({ apiFetch: vi.fn(), ensureApiBase: vi.fn() }));
vi.mock("./tauri", () => ({ cmdClearModelProviderSecret: vi.fn(), cmdSetModelProviderSecret: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => true }));
vi.mock("../auth/session", () => ({ getWorkspaceAccessToken: vi.fn() }));

const alias = "a".repeat(64);
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getWorkspaceAccessToken).mockReturnValue("fixture-account");
  vi.mocked(ensureApiBase).mockResolvedValue("https://account.example.test");
  vi.mocked(apiFetch).mockImplementation(async (input) => new Response(JSON.stringify(
    String(input).endsWith("/secret-reference") ? { alias, reference: `secret://os-keyring/model-provider/${alias}` } : { configured: true }
  ), { status: 200 }));
});
afterEach(() => vi.resetAllMocks());

describe("本机供应商凭据保存", () => {
  it("本机模式使用独立会话保存系统凭据并热更新", async () => {
    const localToken = `local-session:${"a".repeat(43)}`;
    vi.mocked(getWorkspaceAccessToken).mockReturnValue(localToken);
    await updateModelProviderRuntimeSecret("provider", "fixture-provider-secret");
    expect(cmdSetModelProviderSecret).toHaveBeenCalledWith(alias, "fixture-provider-secret");
    for (const [, init] of vi.mocked(apiFetch).mock.calls) {
      expect(new Headers(init?.headers).get("Authorization")).toBe(`Bearer ${localToken}`);
    }
  });
  it("系统凭据使用账号与端点隔离的别名，热更新保留原账号令牌", async () => {
    await updateModelProviderRuntimeSecret("provider", "fixture-provider-secret");
    expect(cmdSetModelProviderSecret).toHaveBeenCalledWith(alias, "fixture-provider-secret");
    expect(apiFetch).toHaveBeenCalledTimes(2);
    const [, init] = vi.mocked(apiFetch).mock.calls[1];
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer fixture-account");
    expect(JSON.parse(init?.body as string)).toEqual({ secret: "fixture-provider-secret" });
    expect(vi.mocked(cmdSetModelProviderSecret).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(apiFetch).mock.invocationCallOrder[1]);
  });

  it("账号在读取引用后切换时，不写入密钥或热更新", async () => {
    vi.mocked(getWorkspaceAccessToken).mockReturnValueOnce("fixture-account").mockReturnValue("another-account");
    await expect(updateModelProviderRuntimeSecret("provider", "fixture-provider-secret")).rejects.toThrow("本机会话已变化");
    expect(cmdSetModelProviderSecret).not.toHaveBeenCalled();
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("凭据库写入失败时不会假装执行器已保存", async () => {
    vi.mocked(cmdSetModelProviderSecret).mockRejectedValueOnce(new Error("凭据库不可用"));
    await expect(updateModelProviderRuntimeSecret("provider", "fixture-provider-secret")).rejects.toThrow("凭据库不可用");
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("删除同时清理系统凭据和本机执行器", async () => {
    await clearModelProviderRuntimeSecret("provider");
    expect(cmdClearModelProviderSecret).toHaveBeenCalledWith(alias);
    expect(vi.mocked(apiFetch).mock.calls[1][1]?.method).toBe("DELETE");
  });
});
