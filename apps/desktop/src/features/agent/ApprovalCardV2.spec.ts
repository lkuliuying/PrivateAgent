import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import ApprovalCardV2 from "./ApprovalCardV2.vue";
import type { AgentRunApproval, ToolCall } from "../../types";

function makeApproval(overrides: Partial<AgentRunApproval> = {}): AgentRunApproval {
  return {
    id: "ap-1",
    run_id: "run-1",
    tool_call_id: "tc-1",
    tool_name: "mcp.filesystem.write_file",
    tool_version: "1.0.0",
    arguments_sha256: "a".repeat(64),
    risk_level: "confirm",
    required_capabilities: ["fs.write"],
    status: "pending",
    expires_at: "2026-08-09T00:00:00Z",
    created_at: "2026-08-08T00:00:00Z",
    ...overrides,
  };
}

function makeTool(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    id: 1,
    session_id: 1,
    task_id: null,
    step_id: null,
    tool_name: "run_command",
    risk_level: "confirm",
    status: "pending_approval",
    input_json: { command: "mv screenshot-*.png archive/" },
    output_json: null,
    error_message: null,
    created_at: "2026-08-08T00:00:00Z",
    updated_at: "2026-08-08T00:00:00Z",
    ...overrides,
  };
}

describe("ApprovalCardV2", () => {
  it("Runtime 审批展示动作、范围与过期时间", () => {
    const wrapper = mount(ApprovalCardV2, { props: { approval: makeApproval() } });
    expect(wrapper.text()).toContain("mcp.filesystem.write_file");
    expect(wrapper.text()).toContain("等待审批");
    expect(wrapper.text()).toContain("fs.write");
    expect(wrapper.text()).toContain("2026/8/9");
  });

  it("批准与拒绝发出对应事件", async () => {
    const wrapper = mount(ApprovalCardV2, { props: { approval: makeApproval() } });
    const buttons = wrapper.findAll("button");
    await buttons.find((b) => b.text().includes("批准执行"))!.trigger("click");
    expect(wrapper.emitted("approve-agent")?.[0]).toEqual(["run-1", "ap-1"]);
    await buttons.find((b) => b.text().includes("拒绝"))!.trigger("click");
    expect(wrapper.emitted("reject-agent")?.[0]).toEqual(["run-1", "ap-1"]);
  });

  it("legacy 工具审批发 id 事件；已拒绝状态无操作按钮", async () => {
    const wrapper = mount(ApprovalCardV2, { props: { toolCall: makeTool() } });
    const approveBtn = wrapper.findAll("button").find((b) => b.text().includes("批准执行"));
    expect(approveBtn).toBeTruthy();
    await approveBtn!.trigger("click");
    expect(wrapper.emitted("approve-tool")?.[0]).toEqual([1]);
    const rejected = mount(ApprovalCardV2, {
      props: { toolCall: makeTool({ status: "rejected" }) },
    });
    expect(rejected.text()).toContain("已拒绝");
    expect(rejected.findAll("button").some((b) => b.text().includes("批准"))).toBe(false);
  });

  it("过期状态展示恢复提示", () => {
    const wrapper = mount(ApprovalCardV2, {
      props: { approval: makeApproval({ status: "expired" }) },
    });
    expect(wrapper.text()).toContain("已过期");
    expect(wrapper.text()).toContain("重新发起");
  });
});
