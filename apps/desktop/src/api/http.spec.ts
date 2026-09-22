import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, ensureApiBase } from "./http";
import { getWorkspaceAccessToken, setLocalAccessToken } from "../auth/session";
const local = vi.hoisted(() => ({ fetch: vi.fn(), enabled: vi.fn(() => true) }));
vi.mock("../services/localExecutor", async (original) => ({ ...await original<object>(), fetchLocalProject: local.fetch, usesLocalExecutor: local.enabled }));
const token = `local-session:${"a".repeat(43)}`;
const expired = () => new Response("{}", { status: 401, headers: { "X-PrivateAgent-Session": "expired" } });
describe("本机 API 路由及失效边界", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    vi.clearAllMocks();
    setLocalAccessToken(token);
    local.enabled.mockReturnValue(true);
    local.fetch.mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}")));
  });
  afterEach(() => vi.unstubAllGlobals());
  it("MCP 和模型请求带本机会话并进入 IPC", async () => {
    for (const path of ["/projects/1/documentation-sources", "/model-providers", "/workspace-search?q=test&archived=true", "/sessions/1/turn-queue", "/sessions/1/review?scope=task", "/projects/1/skills", "/projects/1/integrations", "/agent-runs/run/browser-evidence/image"]) {
      await apiFetch(`${await ensureApiBase()}${path}`);
      expect(local.fetch).toHaveBeenLastCalledWith(path, expect.objectContaining({ headers: expect.any(Headers) }));
      expect(new Headers(local.fetch.mock.lastCall?.[1].headers).get("Authorization")).toBe(`Bearer ${token}`);
    }
    expect(fetch).not.toHaveBeenCalled();
  });
  it("删除的账号、自动化和插件接口不访问服务器", async () => {
    for (const path of ["/auth/login", "/auth/register", "/admin/users", "/agent-tasks", "/extensions", "/settings"]) {
      expect((await apiFetch(`${await ensureApiBase()}${path}`)).status).toBe(410);
    }
    expect(fetch).not.toHaveBeenCalled();
    expect(local.fetch).not.toHaveBeenCalled();
  });
  it("供应商 401 不清除工作区身份", async () => {
    local.fetch.mockResolvedValueOnce(new Response('{"error_code":"model_unauthorized"}', { status: 401 }));
    await apiFetch(`${await ensureApiBase()}/model-providers`);
    expect(getWorkspaceAccessToken()).toBe(token);
  });
  it("真实本机会话失效发出恢复事件且不重放写请求", async () => {
    const handler = vi.fn();
    window.addEventListener("pa:session-expired", handler);
    try {
      local.fetch.mockResolvedValueOnce(expired());
      await apiFetch(`${await ensureApiBase()}/projects`, { method: "POST", body: "{}" });
      expect(handler).toHaveBeenCalledTimes(1);
      expect(getWorkspaceAccessToken()).toBeNull();
      expect(local.fetch).toHaveBeenCalledTimes(1);
    } finally { window.removeEventListener("pa:session-expired", handler); }
  });
  it("旧请求的迟到 401 不清除新会话", async () => {
    const current = `local-session:${"b".repeat(43)}`;
    local.fetch.mockImplementationOnce(async () => { setLocalAccessToken(current); return expired(); });
    await apiFetch(`${await ensureApiBase()}/projects`);
    expect(getWorkspaceAccessToken()).toBe(current);
  });
  it("外部请求不注入本机凭证，显式泄漏也被阻止", async () => {
    await apiFetch("https://example.test/resource");
    expect(new Headers(vi.mocked(fetch).mock.lastCall?.[1]?.headers).has("Authorization")).toBe(false);
    await expect(apiFetch("https://example.test/resource", { headers: { Authorization: `Bearer ${token}` } })).rejects.toThrow("不能发送到外部服务");
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("浏览器预览不能把内部请求回退到网络", async () => {
    local.enabled.mockReturnValue(false);
    await expect(apiFetch(`${await ensureApiBase()}/projects`)).rejects.toThrow("桌面客户端");
    expect(fetch).not.toHaveBeenCalled();
  });
});
