import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, requestJson, requestVoid, setApiBaseDefault } from "./http";

describe("HTTP boundary", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
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
});
