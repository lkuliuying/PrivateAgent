import { describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
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
  it("运行时显示正在思考，暂停后隐藏该状态", async () => {
    const wrapper = mountTranscript({ phase: "streaming", approvals: [] });
    try {
      expect(wrapper.get('[data-testid="stream-live"]').text()).toBe("正在思考");
      await wrapper.setProps({ projection: projection([[1, "run.paused", {}]]) });
      expect(wrapper.find('[data-testid="stream-live"]').exists()).toBe(false);
    } finally { wrapper.unmount(); }
  });

  it("收起时只保留最终正文和文件摘要，展开后过程顺序稳定且不重复公开进展", async () => {
    const value = projection([
      [1, "model.output.delta", { attempt_id: "progress", phase: "commentary", delta: "正在检查 `src/app.ts`。" }],
      [2, "model.output.finished", { attempt_id: "progress", has_tool_calls: true }],
      [3, "decision.summary", { goal: "检查文件", method: "正在检查 \\`src/app.ts\\`。" }],
      [4, "tool.completed", { tool_call_id: "read", name: "read_code_file" }],
      [5, "context.compaction_started", { checkpoint_id: "compact" }],
      [6, "context.compaction_completed", { checkpoint_id: "compact" }],
      [7, "model.output.delta", { attempt_id: "next", phase: "commentary", delta: "正在检查 `src/app.ts`。" }],
      [8, "model.output.finished", { attempt_id: "next", has_tool_calls: true }],
      [9, "run.completed", { output: "## 任务总结\n\n检查结束。", tool_call_count: 1 }],
    ]);
    value.completionRequirements = [{ requirement_id: "one", description: "检查文件", kind: "manual", evidence_policy: "manual", origin: "user", required: true }];
    const wrapper = mount(RunTranscript, { props: { projection: value }, attachTo: document.body,
      slots: { "result-files": '<div data-testid="files-summary">已编辑 4 个文件</div>' } });
    try {
      expect(wrapper.get('[data-testid="completion-requirements"]').isVisible()).toBe(false);
      expect(wrapper.get('[data-testid="files-summary"]').isVisible()).toBe(true);
      await wrapper.get('[data-testid="run-duration-toggle"]').trigger("click");
      expect(wrapper.findAll(".entry").filter(item => item.isVisible()).map(item => item.attributes("data-testid")))
        .toEqual(["transcript-model-output", "transcript-tool", "transcript-context-compaction", "transcript-model-output", "transcript-terminal"]);
      expect(wrapper.findAll('[data-testid="model-public-output"]')).toHaveLength(2);
      expect(wrapper.get('[data-testid="transcript-context-compaction"]').text()).toBe("上下文已压缩");
      expect(wrapper.get('[data-testid="terminal-output"] h2').text()).toBe("任务总结");
      await wrapper.get('[data-testid="run-duration-toggle"]').trigger("click");
      expect(wrapper.get('[data-testid="terminal-output"]').isVisible()).toBe(true);
      expect(wrapper.get('[data-testid="files-summary"]').isVisible()).toBe(true);
    } finally { wrapper.unmount(); }
  });

  it("用户限制导致未验证时不显示输出校验失败或机器检查通过", () => {
    const value = projection([[1, "output.validation_passed", {
      verifier: "local_completion", code: "completion_limited", attempt: 1,
      message: "修改已完成；按用户要求未运行测试，功能正确性尚未验证",
    }]]);
    const wrapper = mountTranscript({ projection: value, approvals: [] });
    try {
      expect(wrapper.text()).toContain("核验结束，保留未验证项");
      expect(wrapper.text()).toContain("按用户要求未运行测试");
      expect(wrapper.text()).not.toContain("输出校验未通过");
      expect(wrapper.text()).not.toContain("机器检查已通过");
    } finally { wrapper.unmount(); }
  });

  it("流式公开输出使用同一安全表格渲染器且不冒充最终验收", () => {
    const value = projection([[1, "model.output.delta", { attempt_id: "a", delta: "| 要求 | 状态 |\n|---|---|\n| 修改 | 待验证 |" }]]);
    const wrapper = mountTranscript({ projection: value, approvals: [] });
    try {
      expect(wrapper.get('[data-testid="model-public-output"]').find("table").exists()).toBe(true);
      expect(wrapper.get('[data-testid="model-public-output"]').text()).not.toContain("最终结论以任务验收为准");
      expect(wrapper.get('[data-testid="model-public-output"]').find("button").exists()).toBe(false);
      expect(value.output).toBeNull();
      expect(value.runOutcome.goal_outcome).toBe("unknown");
    } finally { wrapper.unmount(); }
  });

  it("成功正文提供简洁的结果标签，未验证仍有必要提示且不修改验收数据", async () => {
    const value = projection([
      [1, "output.validation_passed", { verifier: "local_completion", code: "completion_verified", message: "机器检查已通过" }],
      [2, "run.completed", { output: "修改完成", tool_call_count: 1 }],
    ]);
    value.runOutcome = { schema_version: "1.0", run_id: value.runId, goal_outcome: "verified",
      requirements: [{ requirement_id: "change", kind: "file_changed", description: "修改 app.py", required: true }],
      verification_results: [{ requirement_id: "change", status: "passed", message: "磁盘已核验", evidence_ids: ["patch"] }],
      evidence_ids: ["patch"], unverified_items: [] };
    const before = JSON.stringify(value);
    const wrapper = mountTranscript({ projection: value, approvals: [] });
    try {
      await wrapper.get('[data-testid="run-duration-toggle"]').trigger("click");
      for (const text of ["已使用", "验收记录", "机器检查已通过", "复制 Markdown"]) {
        expect(wrapper.text()).not.toContain(text);
      }
      expect(wrapper.find('[data-testid="terminal-attention"]').exists()).toBe(false);
      expect(wrapper.get('[data-testid="terminal-result-label"]').text()).toBe("已验证完成");
      expect(wrapper.get('[data-testid="terminal-output"] button').attributes("aria-label")).toBe("复制 Markdown");
      expect(JSON.stringify(value)).toBe(before);
      await wrapper.setProps({ projection: { ...value,
        runOutcome: { ...value.runOutcome, goal_outcome: "unknown", unverified_items: ["用户禁止测试"] } } });
      expect(wrapper.get('[data-testid="terminal-attention"]').text()).toContain("修改已完成，仍有未验证项");
      expect(wrapper.find('[data-testid="verification-results"]').exists()).toBe(false);
    } finally { wrapper.unmount(); }
  });

  it("没有最终正文的失败任务仍保留已产生的文件产物", () => {
    const wrapper = mountTranscript({ approvals: [], projection: projection([
      [1, "patch_set.preview_created", { patch_set_id: "ps", file_count: 1 }],
      [2, "patch_set.applied", { patch_set_id: "ps", verified: true }],
      [3, "run.failed", { error_code: "model_failed", error: "模型连接中断" }],
    ]) });
    try {
      expect(wrapper.get('[data-testid="result-patch-card"]').text()).toContain("已编辑 1 个文件");
      expect(wrapper.get('[data-testid="terminal-attention"]').text()).toContain("model_failed");
      expect(wrapper.get('[data-testid="terminal-failure-reason"]').text()).toContain("模型连接中断");
      expect(wrapper.find('[data-testid="terminal-output"] button').exists()).toBe(false);
    } finally { wrapper.unmount(); }
  });

  it.each([
    [{ estimated_input_tokens: 3521 }, 3521],
    [{ estimated_tokens: 1200 }, 1200],
    [{ estimated_input_tokens: 0 }, 0],
    [{}, null],
    [{ estimated_input_tokens: null }, null],
  ])("上下文估算保留在事件投影，不再插入正文：%j", (payload, expected) => {
    const value = projection([[1, "context.prepared", payload]]);
    const wrapper = mountTranscript({ projection: value, approvals: [] });
    try {
      expect(value.entries).toMatchObject([{ kind: "context", estimatedTokens: expected }]);
      expect(wrapper.find('[data-testid="transcript-context"]').exists()).toBe(false);
      expect(wrapper.text()).not.toContain("tokens");
    } finally { wrapper.unmount(); }
  });

  it("实时计时在终态固定，换任务重新计时，卸载清理定时器", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-17T00:00:01Z"));
    const current = projection([[1, "run.started", {}]]);
    current.startedAt = "2026-09-17T00:00:00Z";
    const wrapper = mountTranscript({ projection: current, approvals: [] });
    try {
      expect(wrapper.get('[data-testid="run-duration-toggle"]').text()).not.toContain("执行过程");
      expect(wrapper.get('[data-testid="run-duration-toggle"]').attributes("aria-label")).toContain("收起执行过程");
      expect(wrapper.get('[data-testid="run-duration"]').text()).toContain("已用时 1.0 秒");
      await vi.advanceTimersByTimeAsync(2000);
      expect(wrapper.get('[data-testid="run-duration"]').text()).toContain("已用时 3.0 秒");
      const done = projection([[1, "run.started", {}], [2, "run.completed", { output: "完成" }]]);
      done.startedAt = current.startedAt;
      done.completedAt = "2026-09-17T00:00:02.500Z";
      await wrapper.setProps({ projection: done });
      await vi.advanceTimersByTimeAsync(5000);
      expect(wrapper.get('[data-testid="run-duration"]').text()).toContain("用时 2.5 秒");
      expect(vi.getTimerCount()).toBe(0);
      const next = createRunProjection("run-2", "下一轮");
      next.status = "running";
      next.startedAt = new Date().toISOString();
      await wrapper.setProps({ projection: next });
      await vi.advanceTimersByTimeAsync(1000);
      expect(wrapper.get('[data-testid="run-duration"]').text()).toContain("已用时 1.0 秒");
    } finally {
      wrapper.unmount();
      expect(vi.getTimerCount()).toBe(0);
      vi.useRealTimers();
    }
  });

  it.each([null, "invalid", "2026-09-17T00:00:10Z"])("起点缺失或无效时不伪造耗时：%s", async (start) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-17T00:00:00Z"));
    const current = projection([[1, "run.started", {}], [2, "run.completed", { output: "完成" }]]);
    current.startedAt = start;
    current.completedAt = "2026-09-17T00:00:05Z";
    const wrapper = mountTranscript({ projection: current, approvals: [] });
    try {
      expect(wrapper.get('[data-testid="run-duration"]').text()).toContain("用时待同步");
      expect(vi.getTimerCount()).toBe(0);
    } finally { wrapper.unmount(); vi.useRealTimers(); }
  });

  it("呈现用户请求与活动条目", () => {
    const wrapper = mountTranscript();
    expect(wrapper.find('[data-testid="transcript-user-message"]').text()).toContain("修复窄屏遮挡");
    expect(wrapper.find('[data-testid="transcript-run-start"]').text()).toContain("任务开始");
    expect(wrapper.find('[data-testid="transcript-context"]').exists()).toBe(false);
  });

  it("生成用户指令索引，并按侧栏目标滚动到对应消息", async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    const wrapper = mountTranscript({
      history: [
        { id: 7, session_id: 11, role: "user", content: "先检查布局", created_at: "2026-08-29T00:00:00Z" },
        { id: 8, session_id: 11, role: "assistant", content: "已经检查", created_at: "2026-08-29T00:01:00Z" },
      ],
    });
    const markerEvents = wrapper.emitted("instruction-markers-change");
    const markers = markerEvents?.[markerEvents.length - 1]?.[0] as Array<{ id: string; label: string }>;
    expect(markers).toEqual([
      { id: "message:7", label: "先检查布局" },
      { id: "run:run-1", label: "修复窄屏遮挡" },
    ]);

    await wrapper.setProps({ instructionTarget: { id: "message:7", seq: 1 } });
    await flushPromises();
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center" });
    expect(wrapper.find('[data-instruction-id="message:7"]').classes()).toContain("instruction-targeted");
    wrapper.unmount();
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

  it("完成结果默认折叠过程，仍可展开查看完整执行证据", async () => {
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
    expect(wrapper.find('[data-testid="terminal-output"]').isVisible()).toBe(true);
    await duration.trigger("click");
    expect(duration.attributes("aria-expanded")).toBe("true");
    expect(wrapper.find('[data-testid="transcript-decision-summary"]').isVisible()).toBe(true);
    expect(wrapper.find('[data-testid="transcript-decision-summary"]').text()).toContain("调用工作区补丁工具");
    expect(wrapper.find('[data-testid="transcript-decision-summary"]').text()).not.toContain("本轮决策");
    expect(wrapper.find('[data-testid="transcript-decision-summary"]').text()).not.toContain("接下来");
    expect(wrapper.find('[data-testid="transcript-tool"]').text()).toContain("编辑了文件");
    expect(wrapper.find('[data-testid="process-footer"]').exists()).toBe(false);

    await duration.trigger("click");
    expect(duration.attributes("aria-expanded")).toBe("false");
    wrapper.unmount();
  });

  it("默认活动展开、完成收起，待处理审批独立可见，下一任务恢复默认", async () => {
    const wrapper = mountTranscript({ approvals: [] });
    const toggle = wrapper.get('[data-testid="run-duration-toggle"]');
    expect(toggle.attributes("aria-expanded")).toBe("true");
    const done = projection([
      [1, "run.started", {}],
      [2, "tool.approval_required", { tool_call_id: "tc-2", name: "apply_patch_to_workspace", approval_id: "ap-1" }],
      [3, "run.completed", { output: "任务已结束" }],
    ]);
    await wrapper.setProps({ projection: done });
    expect(toggle.attributes("aria-expanded")).toBe("false");
    await wrapper.setProps({ approvals: [APPROVAL] });
    expect(wrapper.get('[data-testid="approval-approve-ap-1"]').isVisible()).toBe(true);
    expect(toggle.attributes("aria-expanded")).toBe("false");
    const next = projection([[1, "run.started", {}], [2, "context.prepared", { estimated_tokens: 100 }]]);
    next.runId = "run-next";
    await wrapper.setProps({ projection: next, approvals: [] });
    expect(toggle.attributes("aria-expanded")).toBe("true");
    expect(wrapper.find('[data-testid="transcript-context"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("运行中可折叠过程，超出活动窗口的待处理审批仍可操作", async () => {
    const frames: Array<[number, string, Record<string, unknown>]> = [
      [1, "tool.approval_required", { tool_call_id: "tc-2", name: APPROVAL.tool_name, approval_id: APPROVAL.id }],
      ...Array.from({ length: 220 }, (_, index): [number, string, Record<string, unknown>] =>
        [index + 2, "tool.completed", { tool_call_id: `read-${index}`, name: "read_code_file" }]),
    ];
    const wrapper = mountTranscript({ projection: projection(frames) });
    try {
      const toggle = wrapper.get('[data-testid="run-duration-toggle"]');
      await toggle.trigger("click");
      expect(toggle.attributes("aria-expanded")).toBe("false");
      expect(wrapper.get('[data-testid="approval-approve-ap-1"]').isVisible()).toBe(true);
      expect(wrapper.findAll('[data-testid="tool-toggle"]').every(item => !item.isVisible())).toBe(true);
      await wrapper.get('[data-testid="approval-reject-ap-1"]').trigger("click");
      expect(wrapper.emitted("reject")?.[0]).toEqual(["ap-1"]);
    } finally { wrapper.unmount(); }
  });

  it("多轮进展保持顺序，工具默认折叠，重复最终正文仅呈现一次", async () => {
    const value = projection([
      [1, "model.output.delta", { attempt_id: "a", delta: "先检查计算函数。" }],
      [2, "model.output.finished", { attempt_id: "a", has_tool_calls: true }],
      [3, "decision.summary", { goal: "修复", method: "本轮决策：调用工具 read_code_file" }],
      [4, "tool.completed", { tool_call_id: "read", name: "read_code_file" }],
      [5, "model.output.delta", { attempt_id: "b", delta: "原因已确认，接下来修复。" }],
      [6, "model.output.finished", { attempt_id: "b", has_tool_calls: true }],
      [7, "model.output.delta", { attempt_id: "final", delta: "修复完成。\r\n" }],
      [8, "model.output.finished", { attempt_id: "final", has_tool_calls: false }],
      [9, "run.completed", { output: "修复完成。\n" }],
    ]);
    // 模拟重开任务先插入终态快照，再收到完整历史事件的条目顺序。
    value.entries.unshift(value.entries.pop()!);
    const wrapper = mountTranscript({ projection: value, approvals: [] });
    try {
      await wrapper.get('[data-testid="run-duration-toggle"]').trigger("click");
      expect(wrapper.findAll('[data-testid="model-public-output"]').map(item => item.text())).toEqual([
        expect.stringContaining("先检查计算函数。"), expect.stringContaining("原因已确认，接下来修复。"),
      ]);
      const visible = wrapper.findAll(".entry").filter(item => item.isVisible()).map(item => item.attributes("data-testid"));
      expect(visible.slice(0, 3)).toEqual(["transcript-model-output", "transcript-tool", "transcript-model-output"]);
      expect(visible[visible.length - 1]).toBe("transcript-terminal");
      expect(wrapper.get<HTMLDetailsElement>("details.tool-disclosure").element.open).toBe(false);
      expect(wrapper.findAll('[data-testid="model-candidate-output"]')).toHaveLength(0);
      expect(wrapper.text().match(/修复完成。/g)).toHaveLength(1);
      expect(wrapper.find('[data-testid="transcript-decision-summary"]').isVisible()).toBe(false);
    } finally { wrapper.unmount(); }
  });

  it("验收改写前的候选正文默认收起，中断正文明确标记不完整", async () => {
    const wrapper = mountTranscript({ approvals: [], projection: projection([
      [1, "model.output.delta", { attempt_id: "interrupted", delta: "只生成一部分" }],
      [2, "model.output.interrupted", { attempt_id: "interrupted" }],
      [3, "model.output.delta", { attempt_id: "candidate", delta: "候选回答宣称已完成" }],
      [4, "model.output.finished", { attempt_id: "candidate", has_tool_calls: false }],
      [5, "run.completed", { output: "修改完成，测试未验证" }],
    ]) });
    try {
      await wrapper.get('[data-testid="run-duration-toggle"]').trigger("click");
      expect(wrapper.get('[data-testid="model-public-output"]').text()).toContain("公开输出已中断，内容不完整");
      const candidate = wrapper.get<HTMLDetailsElement>('[data-testid="model-candidate-output"]');
      expect(candidate.element.open).toBe(false);
      expect(candidate.text()).toContain("候选回答宣称已完成");
      expect(wrapper.get('[data-testid="terminal-output"] p').text()).toBe("修改完成，测试未验证");
    } finally { wrapper.unmount(); }
  });

  it("按阶段保留无工具的公开进展，按提交来源隐藏同请求的多段最终候选", async () => {
    const wrapper = mountTranscript({ approvals: [], projection: projection([
      [1, "model.output.delta", { attempt_id: "a", message_id: "progress", phase: "commentary", delta: "结果相同" }],
      [2, "model.output.delta", { attempt_id: "a", message_id: "final-one", phase: "final_answer", delta: "第一段" }],
      [3, "model.output.delta", { attempt_id: "a", message_id: "final-two", phase: "final_answer", delta: "第二段" }],
      [4, "model.output.finished", { attempt_id: "a", has_tool_calls: false }],
      [5, "run.completed", { output: "结果相同", final_output_attempt_id: "a" }],
    ]) });
    try {
      await wrapper.get('[data-testid="run-duration-toggle"]').trigger("click");
      expect(wrapper.findAll('[data-testid="model-public-output"]')).toHaveLength(1);
      expect(wrapper.get('[data-testid="model-public-output"]').text()).toBe("结果相同");
      expect(wrapper.find('[data-testid="model-candidate-output"]').exists()).toBe(false);
      expect(wrapper.get('[data-testid="terminal-output"]').text()).toContain("结果相同");
      expect(wrapper.text()).not.toContain("第一段");
      expect(wrapper.text()).not.toContain("第二段");
    } finally { wrapper.unmount(); }
  });

  it("验收替换的终态不能按相等文本隐藏候选，也不能隐藏其他请求的回答", async () => {
    const value = projection([
      [1, "model.output.delta", { attempt_id: "candidate", phase: "final_answer", delta: "完成" }],
      [2, "model.output.finished", { attempt_id: "candidate", has_tool_calls: true }],
      [3, "run.completed", { output: "完成", final_output_attempt_id: null }],
    ]);
    const wrapper = mountTranscript({ approvals: [], projection: value });
    try {
      await wrapper.get('[data-testid="run-duration-toggle"]').trigger("click");
      expect(wrapper.get('[data-testid="model-candidate-output"]').text()).toContain("完成");
      await wrapper.setProps({ projection: { ...value, finalOutputAttemptId: "other-attempt" } });
      expect(wrapper.get('[data-testid="model-candidate-output"]').text()).toContain("完成");
    } finally { wrapper.unmount(); }
  });

  it("较长正文显示截断提示，旧记录不会以被截断的尾部冒充完整最终回答", async () => {
    const value = projection([
      [1, "model.output.delta", { attempt_id: "long", delta: "前" + "后".repeat(64000) }],
    ]);
    const wrapper = mountTranscript({ approvals: [], projection: value });
    try {
      expect(wrapper.get('[data-testid="model-output-truncated"]').text()).toContain("内容不完整");
      const completed = { ...value, entries: [...value.entries] };
      applyRunFrame(completed, { sequence: 2, type: "model.output.finished", payload: { attempt_id: "long", has_tool_calls: false } });
      applyRunFrame(completed, { sequence: 3, type: "run.completed", payload: { output: "后".repeat(64000) } });
      await wrapper.setProps({ projection: completed });
      await wrapper.get('[data-testid="run-duration-toggle"]').trigger("click");
      expect(wrapper.get('[data-testid="model-candidate-output"] [data-testid="model-output-truncated"]').text()).toContain("64,000");
      expect(wrapper.get('[data-testid="terminal-output"]').text()).toContain("后");
    } finally { wrapper.unmount(); }
  });

  it("有安全文件路径的产物可打开，无路径或非法路径不产生文件操作", async () => {
    const wrapper = mountTranscript({ approvals: [], projection: projection([
      [1, "artifact.created", { artifact_id: "one", kind: "report", title: "报告", rel_path: "reports/final.md:12" }],
      [2, "artifact.created", { artifact_id: "two", kind: "report", title: "旧报告" }],
      [3, "artifact.created", { artifact_id: "three", kind: "report", title: "无效报告", rel_path: "../outside.txt" }],
      [4, "run.completed", { output: "已生成报告" }],
    ]) });
    try {
      const cards = wrapper.findAll('[data-testid="result-artifact-card"]');
      expect(cards).toHaveLength(3);
      await cards[0].get("button").trigger("click");
      expect(wrapper.emitted("open-file")).toEqual([[{ path: "reports/final.md", line: 12 }]]);
      expect(cards[1].find("button").exists()).toBe(false);
      expect(cards[2].find("button").exists()).toBe(false);
    } finally { wrapper.unmount(); }
  });

  it("仅将已完成终态的结构化结果展示为 JSON，保留原正文与候选验收边界", async () => {
    const value = projection([
      [1, "model.output.delta", { attempt_id: "a", phase: "final_answer", delta: "候选内容" }],
      [2, "run.completed", { output: '{"ok":true}', structured_output: { ok: true }, final_output_attempt_id: null }],
    ]);
    const wrapper = mountTranscript({ approvals: [], projection: value });
    try {
      expect(wrapper.get('[data-testid="terminal-output"] pre code').text()).toBe('{\n  "ok": true\n}');
      expect(value.output).toBe('{"ok":true}');
      expect(wrapper.get('[data-testid="model-candidate-output"]').text()).toContain("候选内容");
      const failed = projection([[1, "run.failed", { output: "结构不符合要求", structured_output: { ok: true } }]]);
      await wrapper.setProps({ projection: failed });
      expect(wrapper.find('[data-testid="terminal-output"] pre').exists()).toBe(false);
      expect(wrapper.get('[data-testid="terminal-output"]').text()).toContain("结构不符合要求");
    } finally { wrapper.unmount(); }
  });

  it("历史、进展、候选与最终正文的文件请求统一交给工作区处理", async () => {
    const wrapper = mountTranscript({ approvals: [], history: [{ id: 99, role: "assistant", content: "历史回答" }], projection: projection([
      [1, "model.output.delta", { attempt_id: "progress", phase: "commentary", delta: "进展" }],
      [2, "model.output.finished", { attempt_id: "progress", has_tool_calls: false }],
      [3, "model.output.delta", { attempt_id: "answer", phase: "final_answer", delta: "候选" }],
      [4, "model.output.finished", { attempt_id: "answer", has_tool_calls: false }],
      [5, "run.completed", { output: "最终正文", final_output_attempt_id: null }],
    ]) });
    try {
      const markdown = wrapper.findAllComponents({ name: "MarkdownContent" });
      expect(markdown).toHaveLength(4);
      for (const component of markdown) component.vm.$emit("open-file", { path: "src/app.ts", line: 7 });
      await flushPromises();
      expect(wrapper.emitted("open-file")).toHaveLength(4);
      expect(wrapper.emitted("open-file")?.every(args => JSON.stringify(args) === JSON.stringify([{ path: "src/app.ts", line: 7 }]))).toBe(true);
    } finally { wrapper.unmount(); }
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

  it("工具详情按需展开，后续正文更新保留展开选择，换任务重新折叠", async () => {
    const wrapper = mountTranscript({ projection: toolProjection(), approvals: [], executionByTool: { "tc-cmd": CMD_EXECUTION } });
    try {
      const disclosure = wrapper.get<HTMLDetailsElement>("details.tool-disclosure");
      expect(disclosure.element.open).toBe(false);
      expect(wrapper.get('[data-testid="tool-command"]').isVisible()).toBe(false);
      await disclosure.get("summary").trigger("click");
      expect(disclosure.element.open).toBe(true);
      expect(wrapper.get('[data-testid="tool-command"]').isVisible()).toBe(true);
      expect(wrapper.emitted("load-output")).toBeUndefined();
      const next = toolProjection();
      applyRunFrame(next, { sequence: 4, type: "model.output.delta", payload: { attempt_id: "next", delta: "已读取结果" } });
      await wrapper.setProps({ projection: next });
      expect(disclosure.element.open).toBe(true);
      await wrapper.setProps({ projection: { ...next, runId: "another-run" } });
      expect(wrapper.get<HTMLDetailsElement>("details.tool-disclosure").element.open).toBe(false);
    } finally { wrapper.unmount(); }
  });

  it.each([
    ["exited", "succeeded", 0, "测试通过"],
    ["exited", "unknown", 0, "结果未验证"],
    ["exited", "failed", 1, "测试失败"],
    ["unknown", "unknown", null, "结果未知"],
    ["unknown", "succeeded", null, "结果未验证"],
  ])("折叠摘要保留命令验证状态与警告：%s / %s", (outcome, validation, exitCode, expected) => {
    const execution = { ...CMD_EXECUTION, execution_result: {
      schema_version: "1.0", execution_id: CMD_EXECUTION.id, operation_id: "op", outcome,
      command_kind: "test", exit_code: exitCode, validation_outcome: validation,
    }, output: { ...CMD_EXECUTION.output, runtime_warnings: [{ code: "python_path_resolution_warning" }] } };
    const wrapper = mountTranscript({ projection: toolProjection(), approvals: [], executionByTool: { "tc-cmd": execution } });
    try {
      const summary = wrapper.get('[data-testid="tool-toggle"]');
      expect(summary.text()).toContain(expected);
      expect(summary.text()).toContain("Python 路径解析警告");
      expect(summary.text()).toContain("pytest tests");
      expect(summary.text()).not.toContain("sk-demo");
      expect(summary.text()).toContain("[REDACTED]");
      expect(wrapper.get<HTMLDetailsElement>("details.tool-disclosure").element.open).toBe(false);
    } finally { wrapper.unmount(); }
  });

  it("被拒绝工具请求在折叠摘要中可见", () => {
    const wrapper = mountTranscript({ approvals: [], projection: projection([
      [1, "tool.failed", { tool_call_id: "rejected", name: "exec_command", error_type: "local_tool_rejected", error: "未登记" }],
    ]) });
    try { expect(wrapper.get('[data-testid="tool-toggle"]').text()).toContain("请求被拒绝"); }
    finally { wrapper.unmount(); }
  });

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
    // 单次调用不显示多次调用计数。
    expect(wrapper.find('[data-testid="tool-invocation"]').exists()).toBe(false);
  });

  it("同名工具多次执行只呈现调用序号，不推断重试", () => {
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
    const calls = wrapper.findAll('[data-testid="tool-invocation"]');
    expect(calls.map(item => item.text())).toEqual(["调用 1/2", "调用 2/2"]);
    expect(wrapper.text()).not.toContain("重试");
    wrapper.unmount();
  });

  it.each(['空字符串（""）', "null", "数组（1 项，内容已隐藏）"])("失败搜索可展开参数详情：%s", async (received) => {
    const execution = { ...CMD_EXECUTION, id: "search-failed", tool_name: "search_project_files", status: "failed",
      output: { parameter_errors: [{ field: "glob", received, hint: 'glob 不能为空；不限制文件类型时填写 "*"。' }] } };
    const wrapper = mountTranscript({
      projection: projection([[1, "tool.failed", { tool_call_id: "search", name: "search_project_files", error: "搜索参数无效" }]]),
      approvals: [], executionByTool: { search: execution }, executions: [execution],
    });
    try {
      const details = wrapper.get<HTMLDetailsElement>('[data-testid="tool-parameters"]');
      expect(details.element.open).toBe(false);
      expect(details.get("summary").text()).toBe("查看失败参数");
      await details.get("summary").trigger("click");
      expect(details.element.open).toBe(true);
      expect(details.text()).toContain(received);
      expect(details.text()).toContain('填写 "*"');
      expect(wrapper.find('[data-testid="command-output"]').exists()).toBe(false);
    } finally { wrapper.unmount(); }
  });

  it.each([null, { parameter_errors: "invalid" }, { parameter_errors: [null, { field: "unknown", received: "hidden", hint: "hidden" }] }])(
    "旧记录或无有效诊断时不虚构参数详情：%s", (output) => {
      const execution = { ...CMD_EXECUTION, tool_name: "search_project_files", status: "failed", output };
      const wrapper = mountTranscript({
        projection: projection([[1, "tool.failed", { tool_call_id: "search", name: "search_project_files" }]]),
        approvals: [], executionByTool: { search: execution }, executions: [execution],
      });
      try { expect(wrapper.find('[data-testid="tool-parameters"]').exists()).toBe(false); }
      finally { wrapper.unmount(); }
    },
  );

  it("参数详情转义文本并脱敏，不显示超长或不属于搜索的诊断", () => {
    const execution = { ...CMD_EXECUTION, tool_name: "search_project_files", status: "failed", output: {
      parameter_errors: [
        { field: "glob", received: "password=example-value", hint: '<img src="x" onerror="alert(1)">' },
        { field: "query", received: "a".repeat(201), hint: "过长详情不能显示" },
      ],
    } };
    const wrapper = mountTranscript({
      projection: projection([
        [1, "tool.failed", { tool_call_id: "search", name: "search_project_files" }],
        [2, "tool.failed", { tool_call_id: "read", name: "read_code_file" }],
      ]), approvals: [], executionByTool: { search: execution, read: { ...execution, tool_name: "read_code_file" } },
    });
    try {
      expect(wrapper.findAll('[data-testid="tool-parameters"]')).toHaveLength(1);
      expect(wrapper.text()).toContain("[REDACTED]");
      expect(wrapper.text()).not.toContain("example-value");
      expect(wrapper.text()).not.toContain("过长详情不能显示");
      expect(wrapper.find("img").exists()).toBe(false);
    } finally { wrapper.unmount(); }
  });

  it("成功读取不同文件仍是调用次数，记录未同步时不编造序号", async () => {
    const reads = ["a.py", "b.py"].map((path, index) => ({
      ...CMD_EXECUTION, id: `read-${index}`, tool_name: "read_code_file", status: "completed", output: { rel_path: path },
    }));
    const wrapper = mountTranscript({ approvals: [], projection: projection([
      [1, "tool.completed", { tool_call_id: "read-a", name: "read_code_file" }],
      [2, "tool.completed", { tool_call_id: "read-b", name: "read_code_file" }],
    ]), executionByTool: { "read-a": reads[0], "read-b": reads[1] }, executions: reads });
    expect(wrapper.findAll('[data-testid="tool-invocation"]').map(item => item.text())).toEqual(["调用 1/2", "调用 2/2"]);
    expect(wrapper.text()).not.toContain("重试");
    await wrapper.setProps({ executions: reads.map(item => ({ ...item, id: `other-${item.id}` })) });
    expect(wrapper.find('[data-testid="tool-invocation"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it.each(["succeeded", "failed"])("读取执行结果不产生另一条命令结论，原命令状态保持 %s", (validation) => {
    const command = { ...CMD_EXECUTION, tool_name: "exec_command", status: validation === "failed" ? "failed" : "completed",
      execution_result: { schema_version: "1.0", execution_id: CMD_EXECUTION.id, operation_id: "op-test",
        outcome: "exited", command_kind: "test", exit_code: validation === "failed" ? 1 : 0,
        validation_outcome: validation },
    };
    const read = { ...CMD_EXECUTION, id: "read-result", tool_name: "read_execution", status: "completed",
      output: { execution_id: command.id, exit_code: command.execution_result.exit_code, execution_result: command.execution_result },
    };
    const wrapper = mountTranscript({ approvals: [], projection: projection([
      [1, `tool.${validation === "failed" ? "failed" : "completed"}`, { tool_call_id: "command", name: "exec_command" }],
      [2, "tool.completed", { tool_call_id: "read", name: "read_execution" }],
    ]), executionByTool: { command, read }, executions: [command, read] });
    expect(wrapper.findAll(".command-output")).toHaveLength(1);
    expect(wrapper.text()).toContain(validation === "failed" ? "测试失败" : "测试通过");
    expect(wrapper.text()).toContain("读取执行结果");
    expect(wrapper.text()).not.toContain("结果未验证");
    wrapper.unmount();
  });

  it("读取执行结果失败仍明确显示错误", () => {
    const wrapper = mountTranscript({ approvals: [], projection: projection([
      [1, "tool.failed", { tool_call_id: "read", name: "read_execution", error: "执行记录不可访问" }],
    ]) });
    expect(wrapper.text()).toContain("读取执行结果");
    expect(wrapper.text()).toContain("执行记录不可访问");
    expect(wrapper.findAll(".command-output")).toHaveLength(0);
    wrapper.unmount();
  });

  it.each(["completed", "failed"])("补丁预览与写入分别标记，预览 %s 不宣称编辑文件", (state) => {
    const wrapper = mountTranscript({ approvals: [], projection: projection([
      [1, `tool.${state}`, { tool_call_id: "preview", name: "propose_project_patch", error: state === "failed" ? "预览失败" : undefined }],
      [2, "tool.completed", { tool_call_id: "apply", name: "apply_project_patch" }],
      [3, "tool.completed", { tool_call_id: "search", name: "search_project_files" }],
    ]) });
    expect(wrapper.text()).toContain("生成补丁预览");
    expect(wrapper.text()).toContain("应用补丁");
    expect(wrapper.text()).toContain("搜索项目文件");
    expect(wrapper.text()).not.toContain("编辑了文件");
    if (state === "failed") expect(wrapper.text()).toContain("预览失败");
    wrapper.unmount();
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
