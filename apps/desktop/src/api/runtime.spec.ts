import { describe, expect, it } from "vitest";

import {
  shouldUseLegacyToolPlanner,
  type RuntimeCapabilities,
} from "./runtime";

function capabilities(
  chat_execution_mode: RuntimeCapabilities["chat_execution_mode"]
): RuntimeCapabilities {
  return {
    chat_execution_mode,
    legacy_tool_planner_enabled: chat_execution_mode === "legacy",
    agent_read_only_tools_enabled: true,
    rag_chat_runtime_enabled: false,
  };
}

describe("chat execution mode", () => {
  it("keeps the planner for an older backend without capability discovery", () => {
    expect(shouldUseLegacyToolPlanner(null)).toBe(true);
  });

  it("keeps the planner in explicit legacy mode", () => {
    expect(shouldUseLegacyToolPlanner(capabilities("legacy"))).toBe(true);
  });

  it("bypasses the planner in Agent Runtime mode", () => {
    expect(shouldUseLegacyToolPlanner(capabilities("agent_runtime"))).toBe(false);
  });
});
