import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch, resetApiBase, setApiBase } from "./http";

describe("local API authentication", () => {
  afterEach(() => {
    resetApiBase();
    vi.unstubAllGlobals();
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
});
