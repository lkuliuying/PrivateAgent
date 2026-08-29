import { afterEach, describe, expect, it, vi } from "vitest";

import { resetApiBase, setApiBase } from "../api/http";
import {
  loginAccount,
  sendRegistrationVerificationCode,
} from "./auth";

describe("auth service", () => {
  afterEach(() => {
    resetApiBase();
    vi.unstubAllGlobals();
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
    setApiBase(43123, "startup-secret");

    await loginAccount({ identifier: "alice", password: "password-123" });

    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:43123/auth/login");
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
    setApiBase(43123, "startup-secret");

    const result = await sendRegistrationVerificationCode("alice@example.com");

    expect(result).toEqual({ expires_in_seconds: 300, retry_after_seconds: 60 });
    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://127.0.0.1:43123/auth/email-verification/send"
    );
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      email: "alice@example.com",
    });
  });
});
