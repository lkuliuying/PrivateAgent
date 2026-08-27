import { describe, expect, it } from "vitest";

import {
  shouldUseLegacyToolPlanner,
  supportsCodingRunCreation,
  type RuntimeCapabilities,
} from "./runtime";

function capabilities(
  chat_execution_mode: RuntimeCapabilities["chat_execution_mode"],
  overrides: Partial<RuntimeCapabilities> = {}
): RuntimeCapabilities {
  return {
    chat_execution_mode,
    legacy_tool_planner_enabled: chat_execution_mode === "legacy",
    agent_read_only_tools_enabled: true,
    rag_chat_runtime_enabled: false,
    patch_workflow_enabled: false,
    command_workflow_enabled: false,
    http_workflow_enabled: false,
    sql_readonly_workflow_enabled: false,
    ...overrides,
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

describe("coding run creation capability", () => {
  it("requires UI, Agent Runs API, and project-bound capabilities together", () => {
    expect(
      supportsCodingRunCreation(
        capabilities("legacy", {
          coding_agent_ui_enabled: true,
          agent_runs_api_enabled: true,
          project_bound_runs_enabled: true,
        })
      )
    ).toBe(true);
  });

  it("fails closed when Agent Runs API is disabled or absent", () => {
    expect(
      supportsCodingRunCreation(
        capabilities("legacy", {
          coding_agent_ui_enabled: true,
          agent_runs_api_enabled: false,
          project_bound_runs_enabled: true,
        })
      )
    ).toBe(false);
    expect(
      supportsCodingRunCreation(
        capabilities("legacy", {
          coding_agent_ui_enabled: true,
          project_bound_runs_enabled: true,
        })
      )
    ).toBe(false);
  });
});

describe("trusted workflow gates (v0.5.0 B0)", () => {
  it("defaults all four workflow gates to disabled", () => {
    const gates = capabilities("legacy");
    expect(gates.patch_workflow_enabled).toBe(false);
    expect(gates.command_workflow_enabled).toBe(false);
    expect(gates.http_workflow_enabled).toBe(false);
    expect(gates.sql_readonly_workflow_enabled).toBe(false);
  });

  it("keeps gates independent of the chat execution mode", () => {
    const gates = capabilities("agent_runtime", {
      patch_workflow_enabled: true,
      sql_readonly_workflow_enabled: true,
    });
    expect(gates.command_workflow_enabled).toBe(false);
    expect(gates.http_workflow_enabled).toBe(false);
    expect(shouldUseLegacyToolPlanner(gates)).toBe(false);
  });
});
