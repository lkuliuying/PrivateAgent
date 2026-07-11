import { describe, expect, it, vi } from "vitest";
import { createHealthStore } from "./health";

const GREEN_HEALTH = {
  api: { ok: true },
  ollama: { ok: true },
  mysql: { ok: true },
  chroma: { ok: true },
};

describe("health store", () => {
  it("keeps the last confirmed snapshot while a refresh is pending", async () => {
    let resolveSecond: ((value: Record<string, unknown>) => void) | undefined;
    const fetchHealth = vi
      .fn<() => Promise<Record<string, unknown>>>()
      .mockResolvedValueOnce(GREEN_HEALTH)
      .mockImplementationOnce(
        () => new Promise((resolve) => { resolveSecond = resolve; })
      );
    const store = createHealthStore(fetchHealth);

    await store.refresh();
    const pending = store.refresh();

    expect(store.refreshing.value).toBe(true);
    expect(store.health.value).toEqual(GREEN_HEALTH);

    resolveSecond?.(GREEN_HEALTH);
    await pending;
  });

  it("does not replace a confirmed green snapshot when refresh fails", async () => {
    const fetchHealth = vi
      .fn<() => Promise<Record<string, unknown>>>()
      .mockResolvedValueOnce(GREEN_HEALTH)
      .mockRejectedValueOnce(new Error("temporarily unavailable"));
    const store = createHealthStore(fetchHealth);

    await store.refresh();
    await store.refresh();

    expect(store.health.value).toEqual(GREEN_HEALTH);
    expect(store.error.value).toBe("temporarily unavailable");
  });
});
