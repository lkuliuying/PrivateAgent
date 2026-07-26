import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  apiFetch,
  requestJson,
  requestVoid,
  resetApiBase,
  setApiBase,
  setApiBaseDefault,
  setApiConnection,
} from "./http";

describe("HTTP boundary", () => {
  afterEach(() => {
    resetApiBase();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("adds JSON headers and returns typed data", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    vi.stubGlobal("fetch", fetchMock);
    setApiBaseDefault();

    await expect(
      requestJson<{ ok: boolean }>("/probe", {
        method: "POST",
        body: JSON.stringify({ ping: true }),
      })
    ).resolves.toEqual({ ok: true });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(new Headers(init.headers).get("Accept")).toBe("application/json");
  });

  it("normalizes backend detail into ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "无权访问该目录" }), {
          status: 403,
          headers: { "Content-Type": "application/json" },
        })
      )
    );
    setApiBaseDefault();

    const error = await requestJson("/private").catch((reason) => reason);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 403,
      detail: "无权访问该目录",
      path: "/private",
    });
  });

  it("accepts an empty successful response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    setApiBaseDefault();

    await expect(requestVoid("/items/1", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("keeps the sidecar token in memory and attaches it at the local boundary", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    const persistSpy = vi.spyOn(Storage.prototype, "setItem");
    const token = "a".repeat(64);
    setApiConnection(43127, token);

    await apiFetch("http://127.0.0.1:43127/health");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBe(`Bearer ${token}`);
    expect(init.credentials).toBe("omit");
    expect(persistSpy).not.toHaveBeenCalled();

    setApiBase(43127);
    await apiFetch("http://127.0.0.1:43127/health");
    const devInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(new Headers(devInit.headers).has("Authorization")).toBe(false);
  });

  it("never forwards the token to a different origin", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    setApiConnection(43127, "b".repeat(64));

    await expect(apiFetch("https://example.com/collect")).rejects.toThrow(
      "拒绝向非本地 API 发送桌面鉴权信息"
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects malformed sidecar connection data before any request", () => {
    expect(() => setApiConnection(0, "c".repeat(64))).toThrow(
      "无效的桌面后端端口"
    );
    expect(() => setApiConnection(43127, "short-token")).toThrow(
      "无效的桌面后端安全凭据"
    );
  });
});
