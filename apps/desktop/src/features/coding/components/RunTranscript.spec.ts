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
    expect(wrapper.find('[data-testid="transcript-context"]').text()).toContain("已整理上下文");
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
    expect(wrapper.find('[data-testid="terminal-summary"]').text()).not.toContain("输出总结");
    expect(wrapper.find('[data-testid="terminal-output"]').text()).toContain("修复完成");
    expect(wrapper.find('[data-testid="stream-reconnect-notice"]').exists()).toBe(true);
    await wrapper.find('[data-testid="stream-reconnect-notice"] button').trigger("click");
    expect(wrapper.emitted("retry-stream")).toBeTruthy();
  });

  it("完成结果默认独立展示，点击耗时后展开叙事式公开执行过程", async () => {
    const current = projection([
      [1, "run.started", { max_steps: 12, max_tool_calls: 8 }],
      [2, "context.prepared", { estimated_tokens: 1572, truncated: false }],
      [3, "model.started", { ordinal: 1 }],
      [4, "model.completed", { input_tokens: 120, output_tokens: 47, latency_ms: 1996, finish_reason: "tool_calls" }],
      [5, "decision.summary", { goal: "创建 hello.txt", method: "调用工作区补丁工具", next_steps: ["验证文件内容"] }],
      [6, "tool.started", { tool_call_id: "tc-1", name: "apply_patch_to_workspace" }],
      [7, "tool.completed", { tool_call_id: "tc-1", name: "apply_patch_to_workspace", ordinal: 1 }],
      [8, "run.completed", { output: "已创建 hello.txt。", tool_call_count: 1, input_tokens: 120, output_tokens: 47 }],
    ], "创建 hello.txt");
    current.startedAt = "2026-08-24T01:00:00.000Z";
    current.completedAt = "2026-08-24T01:00:05.400Z";

    const wrapper = mount(RunTranscript, {
      props: { projection: current, approvals: [] },
      attachTo: document.body,
    });
    expect(wrapper.find('[data-testid="terminal-summary"]').text()).not.toContain("输出总结");
    expect(wrapper.find('[data-testid="terminal-output"]').text()).toContain("已创建 hello.txt");
    const duration = wrapper.find('[data-testid="run-duration-toggle"]');
    expect(duration.text()).toContain("用时 5.4 秒");
    expect(duration.attributes("aria-expanded")).toBe("false");
    expect(wrapper.find('[data-testid="transcript-decision-summary"]').isVisible()).toBe(false);

    await duration.trigger("click");
    expect(duration.attributes("aria-expanded")).toBe("true");
    expect(wrapper.find('[data-testid="transcript-decision-summary"]').isVisible()).toBe(true);
    expect(wrapper.find('[data-testid="transcript-decision-summary"]').text()).toContain("创建 hello.txt");
    expect(wrapper.find('[data-testid="transcript-tool"]').text()).toContain("编辑了文件");
    expect(wrapper.find('[data-testid="process-footer"]').text()).toContain("编辑了文件");
  });

  it("失败终态在输出总结中直接显示可信失败原因", () => {
    const wrapper = mount(RunTranscript, {
      props: {
        projection: projection([
          [1, "run.started", {}],
          [2, "run.failed", {
            error: "文件变更任务没有 succeeded 的 Patch 写入执行",
            error_code: "output_validation_failed",
            tool_call_count: 1,
          }],
        ]),
        approvals: [],
      },
      attachTo: document.body,
    });
    const reason = wrapper.find('[data-testid="terminal-failure-reason"]');
    expect(reason.text()).toContain("失败原因");
    expect(reason.text()).toContain("没有 succeeded 的 Patch 写入执行");
  });

  it("完成结果把文件修改与产物显示为独立结果卡", () => {
    const wrapper = mount(RunTranscript, {
      props: {
        projection: projection([
          [1, "patch_set.preview_created", { patch_set_id: "ps-1", file_count: 2 }],
          [2, "patch_set.applied", { patch_set_id: "ps-1", verified: true }],
          [3, "artifact.created", { artifact_id: "art-1", kind: "final_report", title: "最终报告" }],
          [4, "run.completed", { output: "已完成。", tool_call_count: 1 }],
        ]),
        approvals: [],
      },
      attachTo: document.body,
    });
    expect(wrapper.find('[data-testid="result-patch-card"]').text()).toContain("已编辑 2 个文件");
    expect(wrapper.find('[data-testid="result-patch-card"]').text()).toContain("已验证");
    expect(wrapper.find('[data-testid="result-artifact-card"]').text()).toContain("最终报告");
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

  it("重开任务呈现 durable 历史，并裁掉与当前 run 重复的尾部一轮", () => {
    const current = projection([
      [1, "run.started", {}],
      [2, "run.completed", { output: "当前回答", error_code: null }],
    ], "当前问题");
    const wrapper = mount(RunTranscript, {
      props: {
        projection: current,
        history: [
          { id: 1, session_id: 1, role: "user", content: "更早问题", created_at: "2026-08-24T00:00:00Z" },
          { id: 2, session_id: 1, role: "assistant", content: "更早回答", created_at: "2026-08-24T00:00:01Z" },
          { id: 3, session_id: 1, role: "user", content: "当前问题", created_at: "2026-08-24T00:01:00Z" },
          { id: 4, session_id: 1, role: "assistant", content: "当前回答", created_at: "2026-08-24T00:01:01Z" },
        ],
        approvals: [],
      },
      attachTo: document.body,
    });
    expect(wrapper.findAll('[data-testid="transcript-history-user"]')).toHaveLength(1);
    expect(wrapper.findAll('[data-testid="transcript-history-assistant"]')).toHaveLength(1);
    expect(wrapper.find('[data-testid="transcript-history-user"]').text()).toContain("更早问题");
    expect(wrapper.find('[data-testid="transcript-user-message"]').text()).toContain("当前问题");
    expect(wrapper.find('[data-testid="terminal-output"]').text()).toContain("当前回答");
  });

  it("重复提问只裁掉当前 run 副本，并将历史与当前执行分区", () => {
    const current = projection([
      [1, "run.started", {}],
      [2, "run.completed", { output: "当前回答", error_code: null }],
    ], "相同问题");
    const wrapper = mount(RunTranscript, {
      props: {
        projection: current,
        history: [
          { id: 1, session_id: 1, role: "user", content: "相同问题", created_at: "2026-08-24T00:00:00Z" },
          { id: 2, session_id: 1, role: "assistant", content: "更早回答", created_at: "2026-08-24T00:00:01Z" },
          { id: 3, session_id: 1, role: "user", content: "相同问题\r\n", created_at: "2026-08-24T00:01:00Z" },
          { id: 4, session_id: 1, role: "assistant", content: "当前回答\n", created_at: "2026-08-24T00:01:01Z" },
          { id: 5, session_id: 1, role: "system", content: "同步完成", created_at: "2026-08-24T00:01:02Z" },
        ],
        approvals: [],
      },
      attachTo: document.body,
    });
    expect(wrapper.findAll('[data-testid="transcript-history-user"]')).toHaveLength(1);
    expect(wrapper.findAll('[data-testid="transcript-history-assistant"]')).toHaveLength(1);
    expect(wrapper.find('[data-testid="transcript-history-assistant"]').text()).toContain("更早回答");
    expect(wrapper.find('[data-testid="transcript-history-section"]').text()).toContain("更早对话");
    expect(wrapper.text()).toContain("当前执行");
  });

  it("当前与历史助手输出按 Markdown 渲染", () => {
    const wrapper = mount(RunTranscript, {
      props: {
        projection: projection([
          [1, "run.completed", { output: "**完成**\n\n```c\nint main() {}\n```" }],
        ], "创建 C 文件"),
        history: [
          { id: 1, session_id: 1, role: "assistant", content: "- 历史条目", created_at: "2026-08-24T00:00:00Z" },
        ],
        approvals: [],
      },
      attachTo: document.body,
    });
    expect(wrapper.find('[data-testid="terminal-output"] strong').text()).toBe("完成");
    expect(wrapper.find('[data-testid="terminal-output"] pre code').text()).toContain("int main()");
    expect(wrapper.find('[data-testid="transcript-history-assistant"] li').text()).toBe("历史条目");
    expect(wrapper.text()).not.toContain("```");
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
    expect(wrapper.find('[data-testid="tool-time"]').text()).toContain("4.0 秒");
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

  it("非命令工具不渲染横跨整行的命令输出卡", () => {
    const readExecution = {
      ...CMD_EXECUTION,
      id: "exec-read",
      tool_name: "read_file",
      output: { path: "hello.txt", found: true },
    };
    const wrapper = mount(RunTranscript, {
      props: {
        projection: projection([
          [1, "tool.started", { tool_call_id: "tc-read", name: "read_file" }],
          [2, "tool.completed", { tool_call_id: "tc-read", name: "read_file", ordinal: 1 }],
        ]),
        approvals: [],
        executionByTool: { "tc-read": readExecution },
        executions: [readExecution],
      },
      attachTo: document.body,
    });
    expect(wrapper.find('[data-testid="command-output-exec-read"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="transcript-tool"]').text()).toContain("read_file");
  });
});
