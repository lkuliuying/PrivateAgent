import { beforeEach, describe, expect, it } from "vitest";

import {
  clearWindowCloseBehavior,
  getSavedWindowCloseBehavior,
  saveWindowCloseBehavior,
} from "./windowClose";

describe("window close preference", () => {
  beforeEach(() => window.localStorage.clear());

  it("defaults to asking when no preference has been saved", () => {
    expect(getSavedWindowCloseBehavior()).toBeNull();
  });

  it("persists either supported close behavior", () => {
    saveWindowCloseBehavior("background");
    expect(getSavedWindowCloseBehavior()).toBe("background");

    saveWindowCloseBehavior("exit");
    expect(getSavedWindowCloseBehavior()).toBe("exit");
  });

  it("clears the saved behavior and ignores unsupported values", () => {
    saveWindowCloseBehavior("background");
    clearWindowCloseBehavior();
    expect(getSavedWindowCloseBehavior()).toBeNull();

    window.localStorage.setItem("pa_window_close_behavior", "close-window");
    expect(getSavedWindowCloseBehavior()).toBeNull();
  });
});
