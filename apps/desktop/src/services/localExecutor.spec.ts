import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const host = vi.hoisted(() => ({ invoke: vi.fn(), isTauri: vi.fn(() => true) }));
vi.mock("@tauri-apps/api/core", () => host);

describe("connected desktop API routing", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_API_BASE_URL", "http://privateagent.localhost");
    vi.stubEnv("VITE_LOCAL_EXECUTOR", "true");
    host.invoke.mockImplementation(async (command: string) => command === "account_server_origin" ? "http://privateagent.localhost" : { port: 43188, token: "test-local-nonce-".repeat(4) });
    host.isTauri.mockReturnValue(true);
    window.sessionStorage.clear();
    window.localStorage.clear();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  async function setup() {
    const fetchMock = vi.fn(async (_input: unknown, _init?: RequestInit) =>
      new Response(JSON.stringify({ status: "ok", mode: "desktop-local", protocol: 1 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const local = await import("./localExecutor");
    await local.startLocalExecutor();
    const session = await import("../auth/session");
    session.setLocalAccessToken("local-session:" + "a".repeat(43));
    fetchMock.mockClear();
    return { local, fetchMock, http: await import("../api/http") };
  }

  it("sends Windows project paths only to the nonce-protected local executor", async () => {
    const { http, fetchMock } = await setup();
    const controller = new AbortController();
    const body = JSON.stringify({ name: "project", root_path: "D:\\work\\project" });
    await http.apiFetch("http://privateagent.localhost/projects", { method: "POST", body, signal: controller.signal });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:43188/projects");
    expect(init?.body).toBe(body);
    expect(init?.signal).toBe(controller.signal);
    expect(new Headers(init?.headers).get("X-PrivateAgent-Local")).toBe("test-local-nonce-".repeat(4));
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer local-session:" + "a".repeat(43));
    expect(init?.redirect).toBe("error");
  });

  it("删除的账号和管理接口不会发出网络请求", async () => {
    const { http, fetchMock } = await setup();
    for (const path of ["/auth/login", "/auth/register", "/admin/logs/nginx-error"]) {
      expect((await http.apiFetch(`http://privateagent.localhost${path}`)).status).toBe(410);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it("工作区健康检查只访问本机", async () => {
    const { local, fetchMock } = await setup();
    expect(await local.checkLocalExecutorHealth()).toBe(true);
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:43188/health");
  });

  it("旧手动配置不再控制执行位置，模型清单由本机提供", async () => {
    const { defaultConnectionProfile, saveConnectionProfile } = await import("./connectionProfile");
    saveConnectionProfile({ ...defaultConnectionProfile(), inference_mode: "local", model_name: "fixture" });
    const { http, fetchMock } = await setup();
    expect(host.invoke).toHaveBeenCalledWith("start_local_executor", { modelConfig: { inference_mode: "auto" } });
    await http.apiFetch("http://privateagent.localhost/agent-model-profiles?enabled_only=true");
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:43188/agent-model-profiles?enabled_only=true");
    await http.apiFetch("http://privateagent.localhost/local-models/discover", { method: "POST", body: '{"protocol":"ollama","base_url":"http://127.0.0.1:11434"}' });
    expect(fetchMock.mock.calls[1][0]).toBe("http://127.0.0.1:43188/local-models/discover");
  });

  it("授权撤销与上下文查询均留在本机执行器", async () => {
    const { http, fetchMock } = await setup();
    await http.apiFetch("http://privateagent.localhost/full-access-grants/fixture", { method: "DELETE" });
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:43188/full-access-grants/fixture");
    expect(fetchMock.mock.calls[0][1]?.method).toBe("DELETE");
    await http.apiFetch("http://privateagent.localhost/sessions/7/context-budget?model_profile_id=model");
    expect(fetchMock.mock.calls[1][0]).toBe("http://127.0.0.1:43188/sessions/7/context-budget?model_profile_id=model");
  });

  it("fails closed when a local executor is absent, with no cloud project request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const http = await import("../api/http");
    await expect(http.apiFetch("http://privateagent.localhost/projects")).rejects.toThrow("本机执行器未就绪");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("所有模型管理请求进入本机，调用失败时不发送服务器请求", async () => {
    const { http, fetchMock } = await setup();
    for (const [path, method] of [
      ["/model-providers", "GET"], ["/model-providers/provider", "PUT"],
      ["/model-providers/provider/runtime-secret", "PUT"], ["/model-providers/discover/models", "POST"],
      ["/agent-model-profiles/p/tool-probe", "POST"], ["/agent-model-profiles/p/set-default", "POST"],
      ["/model-settings", "PUT"], ["/model-evaluation/preflight?profile_id=p", "GET"],
    ]) {
      await http.apiFetch(`http://privateagent.localhost${path}`, { method, ...(method !== "GET" ? { body: "{}" } : {}) });
      expect(fetchMock.mock.calls[fetchMock.mock.calls.length - 1]?.[0]).toBe(`http://127.0.0.1:43188${path}`);
    }
    fetchMock.mockClear();
    fetchMock.mockRejectedValue(new Error("本机进程已退出"));
    await expect(http.apiFetch("http://privateagent.localhost/model-providers")).rejects.toThrow("本机进程已退出");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:43188/model-providers");
  });

  it("没有执行器的浏览器不能把模型密钥提交到服务器", async () => {
    host.isTauri.mockReturnValue(false);
    vi.stubEnv("VITE_LOCAL_EXECUTOR", "false");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const http = await import("../api/http");
    await expect(http.apiFetch("http://privateagent.localhost/model-providers/p/runtime-secret", { method: "PUT", body: '{"secret":"fixture"}' }))
      .rejects.toThrow("桌面客户端");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("保留 Request 正文，旧完整后端开关不能把本机项目发送到服务器", async () => {
    const { http, fetchMock } = await setup();
    await http.apiFetch(new Request("http://privateagent.localhost/sessions", { method: "POST", body: '{"title":"任务"}' }));
    const [, init] = fetchMock.mock.calls[0];
    expect(new TextDecoder().decode(init?.body as ArrayBuffer)).toBe('{"title":"任务"}');
    vi.stubEnv("VITE_LOCAL_EXECUTOR", "false");
    await http.apiFetch("http://privateagent.localhost/projects");
    expect(fetchMock.mock.calls[fetchMock.mock.calls.length - 1][0]).toBe("http://127.0.0.1:43188/projects");
  });

  it("clears the binding on logout and never routes an unrelated origin locally", async () => {
    const { local, http, fetchMock } = await setup();
    await local.clearLocalIdentity();
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:43188/identity/clear");
    await http.apiFetch("https://other.example.test/projects");
    const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    expect(url).toBe("https://other.example.test/projects");
    expect(new Headers(init?.headers).has("Authorization")).toBe(false);
    expect(new Headers(init?.headers).has("X-PrivateAgent-Local")).toBe(false);
  });
  it("重新绑定后解除旧会话撤权失败的阻塞", async () => {
    const { local, fetchMock, http } = await setup();
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 401 }));
    await expect(local.setLocalProjectContext(null)).rejects.toThrow("撤权失败");
    await expect(http.apiFetch("http://privateagent.localhost/projects", { method: "POST", body: "{}" })).rejects.toThrow("撤权失败");
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ ready: true, access_token: `local-session:${"a".repeat(43)}` })));
    await local.bindLocalAccess();
    await expect(http.apiFetch("http://privateagent.localhost/projects", { method: "POST", body: "{}" })).resolves.toBeInstanceOf(Response);
  });

});
