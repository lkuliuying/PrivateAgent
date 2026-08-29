import { describe, expect, it } from "vitest";
import { isCodingWorkspaceEnabled } from "./uiFlags";

describe("isCodingWorkspaceEnabled", () => {
  it("enables the Coding workspace for a regular user", () => {
    expect(isCodingWorkspaceEnabled(false)).toBe(true);
  });

  it("keeps administrators out of the regular Coding workspace", () => {
    expect(isCodingWorkspaceEnabled(true)).toBe(false);
  });
});
