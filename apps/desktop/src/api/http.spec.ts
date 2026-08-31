import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, resetApiBase } from "./http";
import { clearAccessToken, setAccessToken } from "../auth/session";

describe("服务器 API 认证边界", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_API_BASE_URL", "https://server.example.test");
    window.localStorage.clear();
    resetApiBase();
  });
  afterEach(() => { resetApiBase(); clearAccessToken(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

  it("将账号令牌发送到配置的服务器，禁止认证重定向", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken("user-session");
    await apiFetch("https://server.example.test/auth/me");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer user-session");
    expect(init.redirect).toBe("error");
  });
  it("未登录时不向账号接口附加本机进程令牌", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("VITE_API_TOKEN", "unused-process-token");
    await apiFetch("https://server.example.test/auth/login", { method: "POST" });
    expect(new Headers(fetchMock.mock.calls[0][1].headers).has("Authorization")).toBe(false);
  });
  it("保留调用方明确提供的认证头", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken("user-session");
    await apiFetch("https://server.example.test/auth/me", { headers: { Authorization: "Bearer explicit-session" } });
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get("Authorization")).toBe("Bearer explicit-session");
  });
  it("不向其他源站发送账号令牌", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken("user-session");
    await apiFetch("https://unrelated.example.test/resource");
    expect(new Headers(fetchMock.mock.calls[0][1].headers).has("Authorization")).toBe(false);
  });
  it("服务器会话失效会清除令牌并通知界面", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
    const expired = vi.fn();
    window.addEventListener("pa:session-expired", expired);
    setAccessToken("expired");
    try {
      await apiFetch("https://server.example.test/auth/me");
      expect(window.sessionStorage.getItem("pa_access_token")).toBeNull();
      expect(expired).toHaveBeenCalledTimes(1);
    } finally { window.removeEventListener("pa:session-expired", expired); }
  });
});
