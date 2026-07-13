import { describe, expect, it, vi } from "vitest";
import { normalizeAgentMotionState } from "./agent";
import { createCompositeHandle, type AnimationHandle } from "./utils";
import { workflowVisualState } from "./workflow";

describe("animation state mapping", () => {
  it("normalizes unknown Agent states to the restrained idle motion", () => {
    expect(normalizeAgentMotionState("thinking")).toBe("thinking");
    expect(normalizeAgentMotionState("executing")).toBe("executing");
    expect(normalizeAgentMotionState("failed")).toBe("idle");
    expect(normalizeAgentMotionState()).toBe("idle");
  });

  it("maps workflow domain states to visual states", () => {
    expect(workflowVisualState("running")).toBe("active");
    expect(workflowVisualState("waiting_approval")).toBe("active");
    expect(workflowVisualState("succeeded")).toBe("complete");
    expect(workflowVisualState("failed")).toBe("failed");
    expect(workflowVisualState("planned")).toBe("idle");
  });
});
describe("animation lifecycle", () => {
  it("destroys every child handle once", () => {
    const firstDestroy = vi.fn();
    const secondDestroy = vi.fn();
    const handle = createCompositeHandle([
      { destroyed: false, destroy: firstDestroy },
      { destroyed: false, destroy: secondDestroy },
    ] satisfies AnimationHandle[]);

    handle.destroy();
    handle.destroy();

    expect(firstDestroy).toHaveBeenCalledTimes(1);
    expect(secondDestroy).toHaveBeenCalledTimes(1);
    expect(handle.destroyed).toBe(true);
  });
});
