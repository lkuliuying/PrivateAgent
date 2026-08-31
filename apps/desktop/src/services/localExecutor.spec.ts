import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const host = vi.hoisted(() => ({ invoke: vi.fn(), isTauri: vi.fn(() => true) }));
vi.mock("@tauri-apps/api/core", () => host);

describe("connected desktop API routing", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_API_BASE_URL", "https://cloud.example.test");
    vi.stubEnv("VITE_LOCAL_EXECUTOR", "true");
    host.invoke.mockResolvedValue({ port: 43188, token: "test-local-nonce-".repeat(4) });
    host.isTauri.mockReturnValue(true);
    window.sessionStorage.clear();
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
    await local.startLocalExecutor("https://cloud.example.test");
    const session = await import("../auth/session");
    session.setAccessToken("test-account-session");
    await local.bindLocalIdentity("test-account-session");
    fetchMock.mockClear();
    return { local, fetchMock, http: await import("../api/http") };
  }

  it("sends Windows project paths only to the nonce-protected local executor", async () => {
    const { http, fetchMock } = await setup();
    const controller = new AbortController();
    const body = JSON.stringify({ name: "project", root_path: "D:\\work\\project" });
    await http.apiFetch("https://cloud.example.test/projects", { method: "POST", body, signal: controller.signal });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:43188/projects");
    expect(init?.body).toBe(body);
    expect(init?.signal).toBe(controller.signal);
    expect(new Headers(init?.headers).get("X-PrivateAgent-Local")).toBe("test-local-nonce-".repeat(4));
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer test-account-session");
    expect(init?.redirect).toBe("error");
  });

  it("keeps accounts, models and administrator logs on the cloud without the local nonce", async () => {
    const { http, fetchMock } = await setup();
    for (const path of ["/auth/me", "/agent-model-profiles", "/admin/logs/nginx-error"]) {
      await http.apiFetch(`https://cloud.example.test${path}`);
      const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
      expect(url).toBe(`https://cloud.example.test${path}`);
      expect(new Headers(init?.headers).has("X-PrivateAgent-Local")).toBe(false);
    }
  });

  it("fails closed when a local executor is absent, with no cloud project request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const http = await import("../api/http");
    await expect(http.apiFetch("https://cloud.example.test/projects")).rejects.toThrow("本机执行器未就绪");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("preserves Request bodies and keeps the full local edition on its existing backend", async () => {
    const { http, fetchMock } = await setup();
    await http.apiFetch(new Request("https://cloud.example.test/sessions", { method: "POST", body: '{"title":"任务"}' }));
    const [, init] = fetchMock.mock.calls[0];
    expect(new TextDecoder().decode(init?.body as ArrayBuffer)).toBe('{"title":"任务"}');
    vi.stubEnv("VITE_LOCAL_EXECUTOR", "false");
    await http.apiFetch("https://cloud.example.test/projects");
    expect(fetchMock.mock.calls[fetchMock.mock.calls.length - 1][0]).toBe("https://cloud.example.test/projects");
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
});
