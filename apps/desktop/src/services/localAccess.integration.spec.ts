import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const runtime = vi.hoisted(() => ({ invoke: vi.fn(), request: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => true, invoke: runtime.invoke }));
vi.mock("./privateTransport", () => ({ requestPrivateRuntime: runtime.request }));

const token = `local-session:${"a".repeat(43)}`;
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { "Content-Type": "application/json" },
});

describe("API Key 免登录调用链", () => {
  beforeEach(async () => {
    vi.resetModules();
    vi.clearAllMocks();
    window.localStorage.clear();
    window.sessionStorage.clear();
    const { createPinia, setActivePinia } = await import("pinia");
    setActivePinia(createPinia());
    runtime.invoke.mockImplementation(async (command: string) => command === "account_server_origin"
      ? "https://account.example.test" : { transport: "stdio", protocol: 2 });
    runtime.request.mockImplementation(async (path: string) => {
      if (path === "/health") return json({ mode: "desktop-local", protocol: 1 });
      if (path === "/identity/local") return json({ ready: true, access_token: token });
      if (path === "/identity" || path === "/identity/clear" || path === "/projects/context") return json({ ready: true });
      return json([]);
    });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("账号服务器不可达")));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  async function setup() {
    const { ensureDesktopBackendReady } = await import("./backendStartup");
    await ensureDesktopBackendReady();
    return { http: await import("../api/http"), session: await import("../auth/session") };
  }

  it("服务器不可达时仍可进入本机工作区、配置模型和撤销项目授权", async () => {
    const { http, session } = await setup();
    expect(session.getWorkspaceAccessToken()).toBe(token);
    for (const path of ["/projects", "/model-providers", "/agent-model-profiles", "/model-settings"]) {
      await http.apiFetch(`http://privateagent.localhost${path}`);
      const [target, init] = runtime.request.mock.calls[runtime.request.mock.calls.length - 1];
      expect(target).toBe(path);
      expect(new Headers(init.headers).get("Authorization")).toBe(`Bearer ${token}`);
    }
    const { setLocalProjectContext } = await import("./localExecutor");
    await setLocalProjectContext(null);
    expect(runtime.request).toHaveBeenLastCalledWith("/projects/context", expect.objectContaining({
      headers: expect.objectContaining({ Authorization: `Bearer ${token}` }),
    }));
    expect(fetch).not.toHaveBeenCalled();
    expect(JSON.stringify(window.localStorage)).not.toContain(token);
  });

  it("首次启动和重新连接均自动恢复本机会话", async () => {
    await setup();
    const { retryDesktopBackendStartup } = await import("./backendStartup");
    window.sessionStorage.clear();
    await retryDesktopBackendStartup();
    expect(window.sessionStorage.getItem("pa_local_access_token")).toBe(token);
    expect(fetch).not.toHaveBeenCalled();
    expect(runtime.invoke.mock.calls.every(([command]) => command === "start_local_executor")).toBe(true);
  });

  it("健康检查后进程退出导致绑定失败，启动页重试会重新启动进程", async () => {
    let dead = false;
    let terminateAfterHealth = true;
    runtime.invoke.mockImplementation(async () => { dead = false; return { transport: "stdio", protocol: 2 }; });
    runtime.request.mockImplementation(async (path: string) => {
      if (dead) throw new Error("本机运行时已断开");
      if (path === "/health") {
        if (terminateAfterHealth) { terminateAfterHealth = false; dead = true; }
        return json({ mode: "desktop-local", protocol: 1 });
      }
      return json({ ready: true, access_token: token });
    });
    const { ensureDesktopBackendReady, retryDesktopBackendStartup, backendStartupState } = await import("./backendStartup");
    await expect(ensureDesktopBackendReady()).rejects.toThrow("本机运行时已断开");
    expect(backendStartupState.status).toBe("error");
    await retryDesktopBackendStartup();
    expect(runtime.invoke).toHaveBeenCalledTimes(2);
    expect(backendStartupState.status).toBe("ready");
    expect(window.sessionStorage.getItem("pa_local_access_token")).toBe(token);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("工作台运行时退出后显式重连重新启动和绑定，但不卸载全局工作台或重放写请求", async () => {
    await setup();
    const { backendStartupState } = await import("./backendStartup");
    const { createCodingWorkspaceStore } = await import("../features/coding/model/codingWorkspaceStore");
    const workspace = createCodingWorkspaceStore();
    await workspace.bootstrap();
    let dead = true;
    runtime.invoke.mockImplementation(async () => { dead = false; return { transport: "stdio", protocol: 2 }; });
    runtime.request.mockImplementation(async (path: string) => {
      if (dead) throw new Error("本机运行时已断开");
      if (path === "/health") return json({ mode: "desktop-local", protocol: 1 });
      if (path === "/identity/local") return json({ ready: true, access_token: token });
      return json([]);
    });
    await workspace.refresh();
    expect(workspace.homeState.value).toBe("sidecar-unavailable");
    const pending = workspace.reconnect();
    expect(backendStartupState.status).toBe("ready");
    await pending;
    expect(runtime.invoke).toHaveBeenCalledTimes(2);
    expect(workspace.sidecarOk.value).toBe(true);
    expect(backendStartupState.status).toBe("ready");
    const writes = runtime.request.mock.calls.filter(([, init]) => init?.method === "POST").map(([path]) => path);
    expect(writes.every(path => ["/identity/local", "/projects/context"].includes(path))).toBe(true);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("握手期间重置会话复用身份绑定，旧工作台不再恢复项目上下文", async () => {
    await setup();
    const { retryDesktopBackendStartup, backendStartupState } = await import("./backendStartup");
    const { useCodingWorkspace, resetCodingWorkspace } = await import("../features/coding/model/codingWorkspaceStore");
    const { setLocalProjectContext } = await import("./localExecutor");
    const previous = useCodingWorkspace();
    previous.selectedProjectId.value = 1;
    await setLocalProjectContext(1);
    runtime.request.mockClear();

    let finishBinding!: (response: Response) => void;
    runtime.request.mockImplementation(async (path: string) => {
      if (path === "/health") return json({ mode: "desktop-local", protocol: 1 });
      if (path === "/identity/local") return new Promise<Response>(resolve => { finishBinding = resolve; });
      return json([]);
    });
    const reconnecting = previous.reconnect();
    const retired = expect(reconnecting).rejects.toThrow("当前工作台会话已失效");
    await vi.waitFor(() => expect(finishBinding).toBeTypeOf("function"));
    resetCodingWorkspace();
    const current = useCodingWorkspace();
    const starting = retryDesktopBackendStartup();
    const replacementToken = `local-session:${"b".repeat(43)}`;
    finishBinding(json({ ready: true, access_token: replacementToken }));
    await Promise.all([retired, starting]);
    await current.bootstrap();
    current.selectedProjectId.value = 2;
    await vi.waitFor(() => expect(runtime.request).toHaveBeenCalledWith("/projects/context", expect.any(Object)));

    previous.selectedProjectId.value = 3;
    const requests = runtime.request.mock.calls.length;
    await previous.refresh();
    expect(runtime.request).toHaveBeenCalledTimes(requests);
    expect(runtime.request.mock.calls.filter(([path]) => path === "/projects/context").map(([, init]) => JSON.parse(init.body).project_id)).toEqual([2]);
    expect(runtime.request.mock.calls.filter(([path]) => path === "/identity/local")).toHaveLength(1);
    expect(runtime.invoke).toHaveBeenCalledTimes(2);
    expect(window.sessionStorage.getItem("pa_local_access_token")).toBe(replacementToken);
    expect(current.loadPhase.value).toBe("ready");
    expect(current.loadError.value).toBeNull();
    expect(backendStartupState.status).toBe("ready");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("账号服务器不可达时，Coding 首页按本机执行器状态正常加载", async () => {
    await setup();
    const { createCodingWorkspaceStore } = await import("../features/coding/model/codingWorkspaceStore");
    const workspace = createCodingWorkspaceStore();
    runtime.request.mockClear();

    await workspace.bootstrap();

    expect(workspace.sidecarOk.value).toBe(true);
    expect(workspace.loadPhase.value).toBe("ready");
    expect(workspace.homeState.value).toBe("no-projects");
    expect(runtime.request).toHaveBeenCalledWith("/health", expect.any(Object));
    expect(runtime.request).toHaveBeenCalledWith("/projects", expect.any(Object));
    expect(fetch).not.toHaveBeenCalled();
  });

  it("本机执行器真实故障仍阻止首页，恢复后可重试且保留本机身份", async () => {
    const { session } = await setup();
    const { createCodingWorkspaceStore } = await import("../features/coding/model/codingWorkspaceStore");
    const workspace = createCodingWorkspaceStore();
    runtime.request.mockRejectedValueOnce(new Error("本机管道已关闭"));

    await workspace.bootstrap();

    expect(workspace.sidecarOk.value).toBe(false);
    expect(workspace.homeState.value).toBe("sidecar-unavailable");
    expect(session.getLocalAccessToken()).toBe(token);

    await workspace.refresh();

    expect(workspace.sidecarOk.value).toBe(true);
    expect(workspace.homeState.value).toBe("no-projects");
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([
    [200, null],
    [200, { status: "ok", mode: "account-server", protocol: 1 }],
    [200, { status: "ok", mode: "desktop-local", protocol: 2 }],
    [503, { status: "ok", mode: "desktop-local", protocol: 1 }],
  ])("本机健康响应不符合契约时不显示就绪：%s %j", async (status, body) => {
    await setup();
    const { createCodingWorkspaceStore } = await import("../features/coding/model/codingWorkspaceStore");
    const workspace = createCodingWorkspaceStore();
    runtime.request.mockResolvedValueOnce(json(body, status));

    await workspace.bootstrap();

    expect(workspace.sidecarOk.value).toBe(false);
    expect(workspace.homeState.value).toBe("sidecar-unavailable");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("本机模式不向云端功能发送凭证，也不会被云端 401 退出", async () => {
    const { http, session } = await setup();
    const expired = vi.fn();
    window.addEventListener("pa:session-expired", expired);
    try {
      const response = await http.apiFetch("http://privateagent.localhost/admin/users");
      expect(response.status).toBe(410);
      expect(await response.json()).toMatchObject({ detail: expect.stringContaining("已移除") });
      expect(fetch).not.toHaveBeenCalled();
      expect(expired).not.toHaveBeenCalled();
      expect(session.getLocalAccessToken()).toBe(token);
      await expect(http.apiFetch("https://other.example.test/test", {
        headers: { Authorization: `Bearer ${token}` },
      })).rejects.toThrow("不能发送到外部服务");
      expect(fetch).not.toHaveBeenCalled();
    } finally { window.removeEventListener("pa:session-expired", expired); }
  });

  it("无效本机凭证阻止启动并允许重试", async () => {
    const { ensureDesktopBackendReady, backendStartupState } = await import("./backendStartup");
    runtime.request.mockImplementationOnce(async () => json({ mode: "desktop-local", protocol: 1 }))
      .mockImplementationOnce(async () => json({ ready: true, access_token: "invalid" }));
    await expect(ensureDesktopBackendReady()).rejects.toThrow("本机使用凭证无效");
    expect(backendStartupState.status).toBe("error");
    expect(window.sessionStorage.getItem("pa_local_access_token")).toBeNull();
    await ensureDesktopBackendReady();
    expect(backendStartupState.status).toBe("ready");
    expect(fetch).not.toHaveBeenCalled();
  });
});
