import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, ensureApiBase } from "./http";
import { cmdClearModelProviderSecret, cmdSetModelProviderSecret } from "./tauri";
import { getWorkspaceAccessToken } from "../auth/session";
import { removeUnusedModelCredentials, resumeModelSave, saveModelProviderRecoverably, unusedModelCredentials, type ModelSaveOperation } from "./modelSaves";
import type { ModelProviderSaveInput } from "./modelProviders";
vi.mock("./http", () => ({ apiFetch: vi.fn(), ensureApiBase: vi.fn() }));
vi.mock("./tauri", () => ({ cmdClearModelProviderSecret: vi.fn(), cmdSetModelProviderSecret: vi.fn() }));
vi.mock("../auth/session", () => ({ getWorkspaceAccessToken: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => true }));
const operation: ModelSaveOperation = { id: "a".repeat(32), provider_id: "sample", configuration: { name: "测试", base_url: "https://provider.example.test/v1", protocol: "openai" }, parameters: null,
  credential_action: "replace", credential_alias: "b".repeat(64), credential_ready: false, status: "prepared", updated_at: "saved" };
const configuration: ModelProviderSaveInput = { name: "测试", baseUrl: operation.configuration.base_url, protocol: "openai", apiFormat: "chat_completions", enabled: true,
  models: [{ modelId: "test-model", contextTokens: 32000, maxOutputTokens: null, metadataSource: "user_override" }] };
let order: string[];
beforeEach(() => {
  vi.clearAllMocks();
  order = [];
  vi.mocked(getWorkspaceAccessToken).mockReturnValue("synthetic-local-session");
  vi.mocked(ensureApiBase).mockResolvedValue("http://localhost");
  vi.mocked(cmdSetModelProviderSecret).mockImplementation(async () => { order.push("vault"); return { configured: true, reference: "synthetic-reference" }; });
  vi.mocked(cmdClearModelProviderSecret).mockResolvedValue({ configured: false, reference: "synthetic-reference" });
  vi.mocked(apiFetch).mockImplementation(async (path, init) => {
    const text = String(path);
    if (text.endsWith("/credential")) { order.push("hydrate"); return Response.json(operation); }
    if (text.endsWith("/commit")) { order.push("commit"); return Response.json({ ...operation, status: "completed" }); }
    if (text.endsWith("/cleanup")) return Response.json({ aliases: [operation.credential_alias] });
    if (text.endsWith("/cleared")) return Response.json({ cleared: true });
    if (init?.method === "POST") order.push("prepare");
    return Response.json(operation);
  });
});
describe("可恢复的模型配置保存", () => {
  it("先准备配置再保存凭据，固定恢复接口只发送别名，最后启用", async () => {
    await saveModelProviderRecoverably("sample", configuration, "synthetic-new-value", operation.id, null);
    expect(order).toEqual(["prepare", "vault", "hydrate", "commit"]);
    expect(cmdSetModelProviderSecret).toHaveBeenCalledWith(operation.credential_alias, "synthetic-new-value");
    expect(JSON.stringify(vi.mocked(apiFetch).mock.calls)).not.toContain("synthetic-new-value");
    const credential = vi.mocked(apiFetch).mock.calls.find(([path]) => String(path).endsWith("/credential"))!;
    expect(JSON.parse(credential[1]!.body as string)).toEqual({ stored_alias: operation.credential_alias });
  });
  it("凭据保存失败不会启用草案，提示原配置保留", async () => {
    vi.mocked(cmdSetModelProviderSecret).mockRejectedValueOnce(new Error("vault unavailable"));
    await expect(saveModelProviderRecoverably("sample", configuration, "synthetic-new-value", operation.id, null)).rejects.toThrow("原配置尚未替换");
    expect(order).toEqual(["prepare"]);
  });
  it("恢复待提交凭据由原生层读取，不要求浏览器持有密钥", async () => {
    await resumeModelSave(operation);
    expect(order).toEqual(["hydrate", "commit"]);
    expect(cmdSetModelProviderSecret).not.toHaveBeenCalled();
  });
  it("本机会话变化后不向新会话继续提交", async () => {
    vi.mocked(cmdSetModelProviderSecret).mockImplementationOnce(async () => {
      vi.mocked(getWorkspaceAccessToken).mockReturnValue("changed-session");
      return { configured: true, reference: "synthetic-reference" };
    });
    await expect(saveModelProviderRecoverably("sample", configuration, "synthetic-new-value", operation.id, null)).rejects.toThrow("本机会话已变化");
    expect(order).toEqual(["prepare"]);
  });
  it("清理先保留已核对的范围，删除成功后才标记完成", async () => {
    expect(await removeUnusedModelCredentials([operation.credential_alias])).toBe(1);
    expect(cmdClearModelProviderSecret).toHaveBeenCalledWith(operation.credential_alias);
    const calls = vi.mocked(apiFetch).mock.calls;
    expect(String(calls[0][0])).toContain("/cleanup");
    expect(String(calls[1][0])).toContain("/cleared");
  });
});

function credentialAliases(count: number): string[] {
  return Array.from({ length: count }, (_, index) => index.toString(16).padStart(64, "0"));
}
function mockCredentialCleanup(aliases: string[], hooks: {
  reserve?: (batch: string[], number: number) => void;
  clear?: (alias: string) => void;
  acknowledge?: (alias: string) => void;
} = {}) {
  const remaining = new Set(aliases);
  const cleared = new Set<string>();
  const batches: string[][] = [];
  vi.mocked(apiFetch).mockImplementation(async (path, init) => {
    const text = String(path);
    if (text.endsWith("/unused")) return Response.json({ aliases: [...remaining] });
    if (text.endsWith("/cleanup")) {
      const batch = JSON.parse(init!.body as string).aliases as string[];
      batches.push(batch);
      order.push(`reserve:${batch.length}`);
      hooks.reserve?.(batch, batches.length);
      return Response.json({ aliases: batch });
    }
    const alias = text.match(/\/credentials\/([a-f0-9]{64})\/cleared$/)?.[1];
    if (!alias) throw new Error("未预期的凭据清理请求");
    order.push(`acknowledge:${alias}`);
    hooks.acknowledge?.(alias);
    remaining.delete(alias);
    return Response.json({ cleared: true });
  });
  vi.mocked(cmdClearModelProviderSecret).mockImplementation(async (alias) => {
    order.push(`clear:${alias}`);
    hooks.clear?.(alias);
    cleared.add(alias);
    return { configured: false, reference: `secret://os-keyring/model-provider/${alias}` };
  });
  return { remaining, cleared, batches };
}

describe("旧模型凭据分批清理", () => {
  it.each([0, 64, 65, 129])("%i 项按最多 64 项保留范围，并逐项删除后确认", async (count) => {
    const aliases = credentialAliases(count);
    const { remaining, batches } = mockCredentialCleanup(aliases);
    expect(await removeUnusedModelCredentials(aliases)).toBe(count);
    expect(batches.flat()).toEqual(aliases);
    expect(batches.map((batch) => batch.length)).toEqual(count === 0 ? [] : count === 64 ? [64] : count === 65 ? [64, 1] : [64, 64, 1]);
    const expected = aliases.flatMap((alias, index) => [
      ...(index % 64 === 0 ? [`reserve:${Math.min(64, count - index)}`] : []),
      `clear:${alias}`, `acknowledge:${alias}`,
    ]);
    expect(order).toEqual(expected);
    expect(cmdClearModelProviderSecret).toHaveBeenCalledTimes(count);
    expect(remaining.size).toBe(0);
    if (count === 0) {
      expect(apiFetch).not.toHaveBeenCalled();
      expect(getWorkspaceAccessToken).not.toHaveBeenCalled();
    }
  });

  it("等待期间调用方修改清单不会扩大已确认的清理范围", async () => {
    const aliases = credentialAliases(65);
    const reviewed = [...aliases];
    const { batches } = mockCredentialCleanup(reviewed, {
      reserve: (_, number) => { if (number === 1) aliases.splice(64, 1, "f".repeat(64)); },
    });
    expect(await removeUnusedModelCredentials(aliases)).toBe(65);
    expect(batches.flat()).toEqual(reviewed);
    expect(cmdClearModelProviderSecret).not.toHaveBeenCalledWith("f".repeat(64));
  });

  it("第二批保留范围失败时保留第一批确认数量，停止后续清理", async () => {
    const aliases = credentialAliases(129);
    const { batches, remaining } = mockCredentialCleanup(aliases, {
      reserve: (_, number) => { if (number === 2) throw new Error("范围已变化"); },
    });
    await expect(removeUnusedModelCredentials(aliases)).rejects.toThrow("已确认清理 64 项");
    expect(batches.map((batch) => batch.length)).toEqual([64, 64]);
    expect(cmdClearModelProviderSecret).toHaveBeenCalledTimes(64);
    expect([...remaining]).toEqual(aliases.slice(64));
    expect(order[order.length - 1]).toBe("reserve:64");
  });

  it.each(["clear", "acknowledge"] as const)("第二批 %s 失败只统计已确认项，重新读取后可重试剩余范围", async (phase) => {
    const aliases = credentialAliases(65);
    let failOnce = true;
    const { remaining, cleared, batches } = mockCredentialCleanup(aliases, {
      [phase]: (alias: string) => {
        if (alias === aliases[64] && failOnce) {
          failOnce = false;
          throw new Error("合成凭据操作失败");
        }
      },
    });
    await expect(removeUnusedModelCredentials(aliases)).rejects.toThrow("已确认清理 64 项");
    expect([...remaining]).toEqual([aliases[64]]);
    expect(cleared.size).toBe(phase === "clear" ? 64 : 65);
    expect(order[order.length - 1]).toBe(`${phase}:${aliases[64]}`);
    const reviewedAgain = await unusedModelCredentials();
    expect(reviewedAgain).toEqual([aliases[64]]);
    expect(await removeUnusedModelCredentials(reviewedAgain)).toBe(1);
    expect(batches.map((batch) => batch.length)).toEqual([64, 1, 1]);
    expect(remaining.size).toBe(0);
    expect(cmdClearModelProviderSecret).toHaveBeenCalledTimes(66);
  });

  it.each([
    ["reserve", 0], ["clear", 0], ["acknowledge", 1],
  ] as const)("%s 期间会话变化后停止，报告 %i 项已确认结果", async (phase, confirmed) => {
    const aliases = credentialAliases(65);
    mockCredentialCleanup(aliases, {
      [phase]: () => { vi.mocked(getWorkspaceAccessToken).mockReturnValue("changed-session"); },
    });
    await expect(removeUnusedModelCredentials(aliases)).rejects.toThrow(`已确认清理 ${confirmed} 项`);
    expect(order).toEqual([
      "reserve:64",
      ...(phase === "reserve" ? [] : [`clear:${aliases[0]}`]),
      ...(phase === "acknowledge" ? [`acknowledge:${aliases[0]}`] : []),
    ]);
    expect(cmdClearModelProviderSecret).not.toHaveBeenCalledWith(aliases[1]);
  });
});
