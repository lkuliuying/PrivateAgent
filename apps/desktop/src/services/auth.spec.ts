import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetApiBase } from "../api/http";
import {
  loginAccount,
  sendRegistrationVerificationCode,
} from "./auth";

describe("auth service", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.stubEnv("VITE_API_BASE_URL", "https://server.example.test");
  });
  afterEach(() => {
    resetApiBase();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("sends an email-or-username identifier to the login endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: "token",
          token_type: "bearer",
          expires_at: "2026-09-05T00:00:00Z",
          user: {},
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    await loginAccount({ identifier: "alice", password: "password-123" });

    expect(fetchMock.mock.calls[0][0]).toBe("https://server.example.test/auth/login");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      identifier: "alice",
      password: "password-123",
    });
  });

  it("requests a registration verification code through the auth boundary", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ expires_in_seconds: 300, retry_after_seconds: 60 }),
        { status: 202, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await sendRegistrationVerificationCode("alice@example.com");

    expect(result).toEqual({ expires_in_seconds: 300, retry_after_seconds: 60 });
    expect(fetchMock.mock.calls[0][0]).toBe(
      "https://server.example.test/auth/email-verification/send"
    );
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      email: "alice@example.com",
    });
  });
  it("账号接口不存在时解释配置或部署问题，不直接显示 Not Found", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"detail":"Not Found"}', { status: 404 })));
    await expect(loginAccount({ identifier: "fixture", password: "fixture" })).rejects.toThrow("服务器未提供账号接口");
  });
});
