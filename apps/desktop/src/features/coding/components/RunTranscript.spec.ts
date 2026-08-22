import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import RunTranscript from "./RunTranscript.vue";
import { applyRunFrame, createRunProjection, type RunProjection } from "../model/runProjector";
import type { RunApprovalRecord } from "../model/runContracts";

function projection(frames: Array<[number, string, Record<string, unknown>]>, userMessage = "修复窄屏遮挡"): RunProjection {
  const target = createRunProjection("run-1", userMessage);
  for (const [sequence, type, payload] of frames) {
    applyRunFrame(target, { sequence, type, payload });
  }
  return target;
}

const APPROVAL: RunApprovalRecord = {
  id: "ap-1",
  run_id: "run-1",
  step_id: null,
  tool_call_id: "tc-2",
  tool_name: "apply_patch_to_workspace",
  tool_version: "1.0.0",
  arguments_sha256: "f".repeat(64),
  risk_level: "confirm",
  required_capabilities: ["filesystem.write"],
  status: "pending",
  expires_at: "2026-08-23T00:00:00Z",
  decision_at: null,
  consumed_at: null,
  created_at: "2026-08-22T00:00:00Z",
};

function mountTranscript(props: Record<string, unknown> = {}) {
  return mount(RunTranscript, {
    props: {
      projection: projection([
        [1, "run.started", { max_steps: 12, max_tool_calls: 8 }],
        [2, "context.prepared", { estimated_tokens: 1200, truncated: false }],
        [3, "tool.approval_required", { tool_call_id: "tc-2", name: "apply_patch_to_workspace", approval_id: "ap-1", tool_call_count: 1 }],
      ]),
      approvals: [APPROVAL],
      ...props,
    },
    attachTo: document.body,
  });
}

describe("RunTranscript", () => {
  it("呈现用户请求与活动条目", () => {
    const wrapper = mountTranscript();
    expect(wrapper.find('[data-testid="transcript-user-message"]').text()).toContain("修复窄屏遮挡");
    expect(wrapper.find('[data-testid="transcript-run-start"]').text()).toContain("任务开始");
    expect(wrapper.find('[data-testid="transcript-context"]').text()).toContain("上下文就绪");
  });

  it("审批卡：风险/能力 + 批准/拒绝事件", async () => {
    const wrapper = mountTranscript();
    const card = wrapper.find('[data-testid="approval-card"]');
    expect(card.text()).toContain("apply_patch_to_workspace");
    expect(card.text()).toContain("需确认");
    expect(card.text()).toContain("filesystem.write");
    await wrapper.find('[data-testid="approval-approve-ap-1"]').trigger("click");
    expect(wrapper.emitted("approve")?.[0]).toEqual(["ap-1"]);
    await wrapper.find('[data-testid="approval-reject-ap-1"]').trigger("click");
    expect(wrapper.emitted("reject")?.[0]).toEqual(["ap-1"]);
  });

  it("已处理审批不再显示操作按钮", () => {
    const wrapper = mountTranscript({
      approvals: [{ ...APPROVAL, status: "consumed" }],
    });
    expect(wrapper.find('[data-testid="approval-approve-ap-1"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("已处理");
  });

  it("终态摘要含输出原文与用量；reconnecting 呈现重连提示与立即重试", async () => {
    const wrapper = mount(RunTranscript, {
      props: {
        projection: projection([
          [1, "run.started", {}],
          [2, "run.completed", { output: "修复完成，共 2 处改动", error_code: null, tool_call_count: 2, input_tokens: 100, output_tokens: 50 }],
        ]),
        phase: "reconnecting",
        connectionError: "network reset",
        approvals: [],
      },
      attachTo: document.body,
    });
    expect(wrapper.find('[data-testid="terminal-summary"]').text()).toContain("已完成");
    expect(wrapper.find('[data-testid="terminal-output"]').text()).toContain("修复完成");
    expect(wrapper.find('[data-testid="stream-reconnect-notice"]').exists()).toBe(true);
    await wrapper.find('[data-testid="stream-reconnect-notice"] button').trigger("click");
    expect(wrapper.emitted("retry-stream")).toBeTruthy();
  });

  it("计划摘要可点击打开计划浮层", async () => {
    const wrapper = mount(RunTranscript, {
      props: {
        projection: projection([
          [1, "plan.created", { plan_version: 1, items: [{ item_key: "a", title: "步骤", status: "pending" }] }],
        ]),
        approvals: [],
      },
      attachTo: document.body,
    });
    await wrapper.find('[data-testid="transcript-plan-note"]').trigger("click");
    expect(wrapper.emitted("open-plan")).toBeTruthy();
  });

  it("无投影时呈现空态引导", () => {
    const wrapper = mount(RunTranscript, { props: { projection: null } });
    expect(wrapper.find('[data-testid="transcript-empty"]').exists()).toBe(true);
  });

  // ============ v0.8.0 W6-R：工具卡可追溯详情（计划 §4.3/§6.6） ============
  const CMD_EXECUTION = {
    id: "exec-cmd",
    tool_name: "run_whitelisted_command",
    tool_version: "1.0.0",
    status: "succeeded",
    error_code: null,
    error_message: null,
    output: {
      args: ["pytest", "tests", "--token=sk-demo"],
      cwd: "F:/workspace/demo",
      returncode: 0,
      parsed: { parser: "pytest", summary: "12 passed in 3.42s" },
    },
    created_at: "2026-08-22T00:10:00Z",
    completed_at: "2026-08-22T00:10:04Z",
  };

  function toolProjection() {
    return projection([
      [1, "run.started", {}],
      [2, "tool.started", { tool_call_id: "tc-cmd", name: "run_whitelisted_command" }],
      [3, "tool.completed", { tool_call_id: "tc-cmd", name: "run_whitelisted_command", ordinal: 1 }],
    ]);
  }

  it("工具卡呈现脱敏命令、起止时间、耗时与结果摘要", () => {
    const wrapper = mount(RunTranscript, {
      props: {
        projection: toolProjection(),
        approvals: [],
        executionByTool: { "tc-cmd": CMD_EXECUTION },
        executions: [CMD_EXECUTION],
      },
      attachTo: document.body,
    });
    const command = wrapper.find('[data-testid="tool-command"]');
    expect(command.text()).toContain("pytest tests");
    expect(command.text()).not.toContain("sk-demo");
    expect(command.text()).toContain("[REDACTED]");
    expect(wrapper.find('[data-testid="tool-time"]').text()).toContain("4.0s");
    expect(wrapper.find('[data-testid="tool-result"]').text()).toContain("12 passed in 3.42s");
    // 单次执行不呈现重试徽标（不虚构）
    expect(wrapper.find('[data-testid="tool-retry"]').exists()).toBe(false);
  });

  it("同名执行 ≥2 次时呈现重试序号（公开事实）", () => {
    const first = { ...CMD_EXECUTION, id: "exec-1", completed_at: "2026-08-22T00:10:02Z" };
    const second = { ...CMD_EXECUTION, id: "exec-2", status: "failed" };
    const wrapper = mount(RunTranscript, {
      props: {
        projection: projection([
          [1, "run.started", {}],
          [2, "tool.started", { tool_call_id: "tc-a", name: "run_whitelisted_command" }],
          [3, "tool.failed", { tool_call_id: "tc-a", name: "run_whitelisted_command", error: "退出码 1" }],
          [4, "tool.started", { tool_call_id: "tc-b", name: "run_whitelisted_command" }],
          [5, "tool.completed", { tool_call_id: "tc-b", name: "run_whitelisted_command", ordinal: 2 }],
        ]),
        approvals: [],
        executionByTool: { "tc-a": first, "tc-b": second },
        executions: [first, second],
      },
      attachTo: document.body,
    });
    const retries = wrapper.findAll('[data-testid="tool-retry"]');
    expect(retries.length).toBe(2);
    expect(retries[0].text()).toContain("1/2");
    expect(retries[1].text()).toContain("2/2");
  });

  it("无执行记录的工具卡不虚构时序/参数（只呈现状态事实）", () => {
    const wrapper = mount(RunTranscript, {
      props: {
        projection: projection([
          [1, "tool.started", { tool_call_id: "tc-x", name: "search_kb" }],
        ]),
        approvals: [],
      },
      attachTo: document.body,
    });
    expect(wrapper.find('[data-testid="tool-command"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="tool-time"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="tool-result"]').exists()).toBe(false);
  });
});
