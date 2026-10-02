import { beforeEach, describe, expect, it, vi } from "vitest";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { saveMcpCredential, type McpCredentialBinding } from "./mcpCredentials";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(), isTauri: vi.fn() }));
const binding: McpCredentialBinding = { identity: "a".repeat(64), service_id: "b".repeat(32), version: "c".repeat(32), slot: "static" };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(isTauri).mockReturnValue(true); });

describe("MCP 系统凭据入口", () => {
  it("只调用固定原生命令且返回引用", async () => {
    const status = { reference: "secret://os-keyring/mcp/reference", configured: true };
    vi.mocked(invoke).mockResolvedValue(status);
    expect(await saveMcpCredential(binding, "synthetic-secret")).toEqual(status);
    expect(invoke).toHaveBeenCalledWith("set_mcp_credential", { binding, value: "synthetic-secret" });
  });
  it("浏览器模式及 OAuth 槽不发送秘密", async () => {
    vi.mocked(isTauri).mockReturnValue(false);
    await expect(saveMcpCredential(binding, "synthetic-secret")).rejects.toThrow("桌面");
    vi.mocked(isTauri).mockReturnValue(true);
    await expect(saveMcpCredential({ ...binding, slot: "oauth" }, "synthetic-secret")).rejects.toThrow("OAuth");
    expect(invoke).not.toHaveBeenCalled();
  });
  it("保存失败保持失败结果", async () => {
    vi.mocked(invoke).mockRejectedValue(new Error("凭据库不可用"));
    await expect(saveMcpCredential(binding, "synthetic-secret")).rejects.toThrow("凭据库不可用");
  });
});
