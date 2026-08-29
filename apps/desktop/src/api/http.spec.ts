import { afterEach, describe, expect, it, vi } from "vitest";

import {
  apiFetch,
  configureRemoteApi,
  getConfiguredRemoteApi,
  resetApiBase,
  setApiBase,
} from "./http";
import { clearAccessToken, setAccessToken } from "../auth/session";

describe("local API authentication", () => {
  afterEach(() => {
    configureRemoteApi("");
    resetApiBase();
    clearAccessToken();
    vi.unstubAllGlobals();
  });

  it("prefers the logged-in user token over the local service token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    setApiBase(43123, "startup-secret");
    setAccessToken("user-session-secret");

    await apiFetch("http://127.0.0.1:43123/sessions");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer user-session-secret"
    );
  });

  it("adds the per-startup bearer token to local API requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    setApiBase(43123, "startup-secret");

    await apiFetch("http://127.0.0.1:43123/sessions", { method: "GET" });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer startup-secret"
    );
  });

  it("does not overwrite an explicit authorization header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    setApiBase(43123, "startup-secret");

    await apiFetch("http://127.0.0.1:43123/sessions", {
      headers: { Authorization: "Bearer explicit-secret" },
    });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer explicit-secret"
    );
  });

  it("persists a runtime remote API address and uses it for authenticated calls", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    expect(configureRemoteApi("https://api.example.test/")).toBe(
      "https://api.example.test"
    );
    expect(getConfiguredRemoteApi()).toBe("https://api.example.test");
    setAccessToken("user-session-secret");

    await apiFetch("https://api.example.test/auth/me");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer user-session-secret"
    );
  });

  it("never sends an API bearer token to a different origin", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    setApiBase(43123, "startup-secret");
    setAccessToken("user-session-secret");

    await apiFetch("https://unrelated.example.test/resource");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).has("Authorization")).toBe(false);
  });
});
