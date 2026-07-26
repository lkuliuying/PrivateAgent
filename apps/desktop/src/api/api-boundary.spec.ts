import { describe, expect, it } from "vitest";

const apiSources = import.meta.glob("./*.ts", {
  eager: true,
  import: "default",
  query: "?raw",
}) as Record<string, string>;

describe("API transport boundary", () => {
  for (const [path, source] of Object.entries(apiSources)) {
    if (path === "./http.ts" || path.endsWith(".spec.ts")) continue;

    it(`${path} does not bypass apiFetch`, () => {
      expect(source).not.toMatch(/\bfetch\s*\(/);
    });
  }
});
