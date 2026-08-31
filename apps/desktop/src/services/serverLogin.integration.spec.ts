import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const runtime = vi.hoisted(() => ({ invoke: vi.fn(), request: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => true, invoke: runtime.invoke }));
vi.mock("./privateTransport", () => ({ requestPrivateRuntime: runtime.request }));

const user = { id: 7, username: "fixture", display_name: "Fixture", email: "fixture@example.test", role: "user", status: "active", last_login_at: null, created_at: "2026-08-31T00:00:00Z" };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });

describe("旧版升级后的真实登录调用链", () => {
  beforeEach(async () => {
    vi.resetModules();
    vi.clearAllMocks();
    const { createPinia, setActivePinia } = await import("pinia");
    setActivePinia(createPinia());
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.stubEnv("VITE_API_BASE_URL", "https://server.example.test");
    runtime.invoke.mockImplementation(async (command: string) => command === "account_server_origin" ? "https://server.example.test" : { transport: "stdio", protocol: 2 });
    runtime.request.mockImplementation(async (path: string) => {
      if (path === "/health") return json({ mode: "desktop-local", protocol: 1 });
      if (path === "/identity") return json({ ready: true });
      if (path === "/identity/clear") return json({ cleared: true });
      if (path === "/projects" || path === "/agent-model-profiles") return json([]);
      throw new Error("账号接口不得进入本机管道");
    });
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); window.localStorage.clear(); window.sessionStorage.clear(); });

  it("旧本地身份退出后，首次启动、登录、退出和再次登录均使用服务器", async () => {
    window.localStorage.setItem("privateagent.connection.v1", JSON.stringify({ mode: "local", model_endpoint: "http://127.0.0.1:11434" }));
    window.sessionStorage.setItem("pa_access_token", "obsolete-local-session");
    const network = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "https://server.example.test/auth/login") return json({ access_token: "server-session", user, token_type: "bearer" });
      if (url === "https://server.example.test/auth/logout") return json({ logged_out: true });
      if (url === "https://server.example.test/agent-model-profiles") return json([]);
      throw new Error("请求偏离配置的服务器");
    });
    vi.stubGlobal("fetch", network);
    const { ensureDesktopBackendReady } = await import("./backendStartup");
    const { useAuthStore } = await import("../stores/auth");
    const http = await import("../api/http");
    await ensureDesktopBackendReady();
    const auth = useAuthStore();
    expect(await auth.restoreSession()).toBe(false);
    expect(auth.user).toBeNull();
    expect(network).not.toHaveBeenCalled();
    expect(runtime.invoke).toHaveBeenCalledWith("start_local_executor", { modelConfig: expect.objectContaining({ inference_mode: "local" }) });
    await auth.login({ identifier: "fixture", password: "fixture-password" });
    expect(auth.user).toEqual(user);
    expect(runtime.request).toHaveBeenCalledWith("/identity", expect.objectContaining({ method: "POST" }));
    await http.apiFetch("https://server.example.test/agent-model-profiles");
    await http.apiFetch("https://server.example.test/projects");
    expect(runtime.request).toHaveBeenCalledWith("/projects", expect.any(Object));
    await auth.logout();
    expect(auth.user).toBeNull();
    expect(window.sessionStorage.getItem("pa_access_token")).toBeNull();
    expect(await auth.restoreSession()).toBe(false);
    await auth.login({ identifier: "fixture", password: "fixture-password" });
    expect(auth.isAuthenticated).toBe(true);
    expect(network.mock.calls.map(([url]) => String(url))).toEqual([
      "https://server.example.test/auth/login",
      "https://server.example.test/auth/logout", "https://server.example.test/auth/login",
    ]);
    expect(runtime.request.mock.calls.every(([path]) => !String(path).startsWith("/auth"))).toBe(true);
  });

  it("安装包忽略环境变量和旧服务器覆盖，仅从后端取得固定入口", async () => {
    window.localStorage.setItem("privateagent.server.v2", '{"server_origin":"https://other.example.test"}');
    vi.stubEnv("VITE_API_BASE_URL", "https://other.example.test");
    const { ensureApiBase } = await import("../api/http");
    expect(await ensureApiBase()).toBe("https://server.example.test");
    expect(runtime.invoke).toHaveBeenCalledWith("account_server_origin");
    expect(window.localStorage.getItem("privateagent.server.v2")).toBeNull();
  });

  it("错误密码或网络失败不会创建本机账号或绑定项目身份", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(json({ detail: "用户名或密码错误" }, 401))
      .mockRejectedValueOnce(new TypeError("网络不可达")));
    const { ensureDesktopBackendReady } = await import("./backendStartup");
    const { useAuthStore } = await import("../stores/auth");
    await ensureDesktopBackendReady();
    const auth = useAuthStore();
    await expect(auth.login({ identifier: "fixture", password: "wrong" })).rejects.toThrow("用户名或密码错误");
    await expect(auth.login({ identifier: "fixture", password: "wrong" })).rejects.toThrow("网络不可达");
    expect(auth.user).toBeNull();
    expect(window.sessionStorage.getItem("pa_access_token")).toBeNull();
    expect(runtime.request.mock.calls.some(([path]) => path === "/identity")).toBe(false);
  });

  it("内置服务器读取失败时不发送密码或启动执行器", async () => {
    runtime.invoke.mockRejectedValue(new Error("无法读取内置账号服务"));
    const network = vi.fn();
    vi.stubGlobal("fetch", network);
    const { ensureDesktopBackendReady } = await import("./backendStartup");
    const { loginAccount } = await import("./auth");
    await expect(ensureDesktopBackendReady()).rejects.toThrow("无法读取内置账号服务");
    await expect(loginAccount({ identifier: "fixture", password: "fixture" })).rejects.toThrow("无法读取内置账号服务");
    expect(network).not.toHaveBeenCalled();
    expect(runtime.invoke.mock.calls.every(([command]) => command === "account_server_origin")).toBe(true);
  });
});
