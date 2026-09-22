import { describe, expect, it } from "vitest";
import {
  applyRunFrame,
  cloneRunProjection,
  createRunProjection,
  reconcileRunWithSnapshot,
} from "./runProjector";
import type { RunSnapshot, RunStreamFrame } from "./runContracts";

function frame(sequence: number, type: string, payload: Record<string, unknown> = {}): RunStreamFrame {
  return { sequence, type, payload };
}

it("压缩过程按检查点合并状态，重复事件幂等，不丢弃第二次压缩失败", () => {
  const projection = createRunProjection("compact");
  applyRunFrame(projection, frame(1, "context.compaction_started", { checkpoint_id: "one" }));
  applyRunFrame(projection, frame(2, "context.compaction_completed", { checkpoint_id: "one" }));
  applyRunFrame(projection, frame(2, "context.compaction_completed", { checkpoint_id: "one" }));
  applyRunFrame(projection, frame(3, "context.compaction_started", { checkpoint_id: "two" }));
  applyRunFrame(projection, frame(4, "context.compaction_failed", { checkpoint_id: "two", error: "压缩超时" }));
  expect(projection.entries).toMatchObject([
    { kind: "context-compaction", sequence: 1, state: "completed", message: null },
    { kind: "context-compaction", sequence: 3, state: "failed", message: "压缩超时" },
  ]);
  expect(projection.unknownEventTypes).toEqual([]);
});

const HAPPY: RunStreamFrame[] = [
  frame(1, "run.started", { max_steps: 12, max_tool_calls: 8, max_wall_time_seconds: 120 }),
  frame(2, "context.prepared", { estimated_tokens: 1200, truncated: false }),
  frame(3, "model.started", { ordinal: 1, kind: "model", name: "model" }),
  frame(4, "model.completed", { ordinal: 1, finish_reason: "tool_calls", input_tokens: 1200, output_tokens: 90, latency_ms: 800 }),
  frame(5, "plan.created", {
    plan_version: 1,
    items: [
      { item_key: "a", title: "阅读代码", status: "pending" },
      { item_key: "b", title: "修改文件", status: "pending" },
    ],
  }),
  frame(6, "tool.requested", { ordinal: 1, kind: "tool", tool_call_id: "tc-1", name: "read_code_file" }),
  frame(7, "tool.started", { tool_call_id: "tc-1", name: "read_code_file" }),
  frame(8, "tool.completed", { tool_call_id: "tc-1", name: "read_code_file" }),
  frame(9, "plan.item_changed", { plan_version: 1, item_key: "a", previous_status: "pending", status: "completed" }),
  frame(10, "tool.approval_required", { tool_call_id: "tc-2", name: "apply_patch_to_workspace", approval_id: "ap-1", tool_call_count: 2 }),
  frame(11, "patch_set.preview_created", { patch_set_id: "ps-1", preview_version: 1, file_count: 2, truncated: false }),
  frame(12, "tool.approval_resolved", { tool_call_id: "tc-2", name: "apply_patch_to_workspace", approval_id: "ap-1" }),
  frame(13, "tool.completed", { tool_call_id: "tc-2", name: "apply_patch_to_workspace" }),
  frame(14, "patch_set.applied", { patch_set_id: "ps-1", preview_version: 1, verified: true }),
  frame(15, "artifact.created", { artifact_id: "art-1", kind: "patch_applied", title: "修复", step_id: null }),
  frame(16, "output.validation_started", { verifier: "default", attempt: 1, retry_count: 0, max_retries: 1 }),
  frame(17, "output.validation_passed", { verifier: "default", attempt: 1, retry_count: 0, max_retries: 1, code: "ok", message: "通过" }),
  frame(18, "run.completed", { output: "完成", error: null, error_code: null, tool_call_count: 2, input_tokens: 2000, output_tokens: 300, cached_tokens: 0, cost_usd: null }),
  frame(19, "run.terminal", { status: "completed" }),
];

function project(frames: RunStreamFrame[]): ReturnType<typeof createRunProjection> {
  const projection = createRunProjection("run-1", "任务请求");
  for (const item of frames) applyRunFrame(projection, item);
  return projection;
}

describe("runProjector", () => {
  it("重放澄清请求和回答，旧帧及终态不会重新打开问题", () => {
    const input = { input_id: "q", goal_version: 1, generation: 0, created_at: "",
      questions: [{ id: "scope", question: "检查范围？", options: [] }] };
    const value = project([frame(1, "run.started", { collaboration_mode: "plan" }),
      frame(2, "input.requested", { pending_input: input, state_version: 9 })]);
    expect(value).toMatchObject({ status: "waiting_input", pendingInput: input, collaborationMode: "plan", stateVersion: 9 });
    applyRunFrame(value, frame(3, "input.resolved", { input_id: "q", state_version: 10 }));
    applyRunFrame(value, frame(2, "input.requested", { pending_input: input }));
    expect(value.pendingInput).toBeNull();
    expect(value.status).toBe("running");
    applyRunFrame(value, frame(4, "input.requested", { pending_input: input }));
    applyRunFrame(value, frame(5, "run.cancelled"));
    expect(value.pendingInput).toBeNull();
  });
  it("完整计划事件更新条目和目标状态，回放及旧版本不覆盖新计划", () => {
    const created = frame(1, "plan.created", { plan_version: 1, goal_version: 1,
      items: [{ item_key: "read", title: "检查代码", status: "in_progress" }] });
    const revised = frame(2, "plan.updated", { plan_version: 2, goal_version: 1, needs_review: true,
      explanation: "用户追加了验收条件", items: [{ item_key: "read", title: "检查代码", status: "completed", evidence_calls: ["read-1"] }] });
    const value = project([created, revised, revised]);
    expect(value.plan).toMatchObject({ version: 2, needs_review: true, explanation: "用户追加了验收条件",
      items: [{ status: "completed", evidence_calls: ["read-1"] }] });
    applyRunFrame(value, frame(3, "plan.updated", { plan_version: 1, items: [] }));
    applyRunFrame(value, frame(4, "plan.item_changed", { plan_version: 1, item_key: "read", status: "pending" }));
    expect(value.plan?.version).toBe(2);
    expect(value.plan?.items[0].status).toBe("completed");
    applyRunFrame(value, frame(5, "plan.updated", { plan_version: 3, goal_version: 2, needs_review: false,
      explanation: "已核对追加条件", items: [{ item_key: "read", title: "检查代码", status: "completed" },
        { item_key: "test", title: "验证", status: "in_progress" }] }));
    expect(value.plan).toMatchObject({ version: 3, goal_version: 2, needs_review: false });
    expect(value.plan?.items).toHaveLength(2);
    expect(value.entries.filter(entry => entry.kind === "plan")).toHaveLength(3);
  });

  it("旧后端只有版本的计划更新仍保留既有条目", () => {
    const value = project([frame(1, "plan.created", { plan_version: 1, items: [{ item_key: "a", title: "读取", status: "pending" }] }),
      frame(2, "plan.updated", { plan_version: 2 })]);
    expect(value.plan?.items[0].title).toBe("读取");
    expect(value.plan?.version).toBe(2);
  });

  it.each([
    ["output.validation_passed", "local_completion", "completion_limited", "unverified"],
    ["output.validation_passed", "local_completion", "completion_verified", "passed"],
    ["output.validation_failed", "local_completion", "completion_limited", "failed"],
    ["output.validation_passed", "default", "completion_limited", "passed"],
  ])("按事件和验证器识别保留未验证项：%s / %s / %s", (type, verifier, code, state) => {
    const event = frame(1, type, { verifier, code, message: "核验结果" });
    const value = project([event, event]);
    expect(value.entries.filter(entry => entry.kind === "verification")).toMatchObject([{ state, message: "核验结果" }]);
    expect(value.runOutcome.goal_outcome).toBe("unknown");
  });

  it.each([
    [{ estimated_input_tokens: 3521 }, 3521],
    [{ estimated_tokens: 1200 }, 1200],
    [{ estimated_input_tokens: 0, estimated_tokens: 1200 }, 0],
    [{ estimated_input_tokens: 3521, estimated_tokens: 1200 }, 3521],
    [{}, null],
    [{ estimated_input_tokens: null, estimated_tokens: 1200 }, null],
    [{ estimated_input_tokens: -1 }, null],
    [{ estimated_input_tokens: 1.5 }, null],
    [{ estimated_input_tokens: "3521" }, null],
    [{ estimated_input_tokens: NaN }, null],
    [{ estimated_tokens: Infinity }, null],
    [{ estimated_tokens: Number.MAX_SAFE_INTEGER + 1 }, null],
  ])("上下文估算读取真实字段并兼容旧事件：%j", (payload, expected) => {
    const value = project([frame(1, "context.prepared", payload)]);
    expect(value.entries.find(entry => entry.kind === "context")).toMatchObject({ estimatedTokens: expected });
    const replay = project([frame(1, "context.prepared", payload), frame(1, "context.prepared", payload)]);
    expect(replay.entries).toEqual(value.entries);
  });

  it("暂停、排队、继续和中断从有序事件收敛，旧帧不覆盖终态", () => {
    const value = createRunProjection("recovery");
    applyRunFrame(value, frame(1, "run.queued"));
    expect(value.status).toBe("queued");
    applyRunFrame(value, frame(2, "run.paused"));
    expect(value.status).toBe("paused");
    applyRunFrame(value, frame(3, "run.resumed"));
    expect(value.status).toBe("running");
    applyRunFrame(value, frame(4, "run.interrupted", { error_code: "desktop_restarted", error: "需核对现场" }));
    applyRunFrame(value, frame(2, "run.paused"));
    expect(value.status).toBe("interrupted");
    expect(value.entries.filter(item => item.kind === "terminal")).toHaveLength(1);
  });
  it("公开模型增量不提前生成最终答案，重复帧不重复文本", () => {
    const value = createRunProjection("streaming");
    const delta = frame(1, "model.output.delta", { attempt_id: "a", delta: "处理中" });
    applyRunFrame(value, delta); applyRunFrame(value, delta);
    expect(value.modelOutput?.text).toBe("处理中");
    expect(value.output).toBeNull();
    expect(value.runOutcome.goal_outcome).toBe("unknown");
    applyRunFrame(value, frame(2, "model.output.interrupted", { attempt_id: "a" }));
    expect(value.modelOutput?.state).toBe("interrupted");
  });
  it("跨轮公开正文与工具交错保留，重放不重复且克隆更新不污染旧视图", () => {
    const frames = [
      frame(1, "model.output.delta", { attempt_id: "first", delta: "先读取" }),
      frame(2, "model.output.delta", { attempt_id: "first", delta: "文件。" }),
      frame(3, "model.output.finished", { attempt_id: "first", has_tool_calls: true }),
      frame(4, "tool.completed", { tool_call_id: "read", name: "read_code_file" }),
      frame(5, "model.output.delta", { attempt_id: "second", delta: "已确认原因。" }),
      frame(6, "model.output.finished", { attempt_id: "second", has_tool_calls: true }),
      frame(7, "tool.completed", { tool_call_id: "patch", name: "apply_project_patch" }),
      frame(8, "model.output.delta", { attempt_id: "final", delta: "修复完成。" }),
      frame(9, "model.output.finished", { attempt_id: "final", has_tool_calls: false }),
    ];
    const value = project(frames.slice(0, 1));
    const next = cloneRunProjection(value);
    for (const item of frames.slice(1)) applyRunFrame(next, item);
    expect(value.entries).toMatchObject([{ text: "先读取", state: "streaming" }]);
    expect(next.entries.map(entry => entry.kind)).toEqual(["model-output", "tool", "model-output", "tool", "model-output"]);
    expect(next.entries.filter(entry => entry.kind === "model-output")).toMatchObject([
      { text: "先读取文件。", sequence: 1, state: "finished", hasToolCalls: true },
      { text: "已确认原因。", sequence: 5, state: "finished", hasToolCalls: true },
      { text: "修复完成。", sequence: 8, state: "finished", hasToolCalls: false },
    ]);
    expect(project(frames.flatMap(item => [item, item]))).toEqual(next);
    expect(next.output).toBeNull();
  });

  it("缺失正文不造进展，旧轮结束或迟到增量不覆盖当前轮", () => {
    const value = project([
      frame(1, "model.output.finished", { attempt_id: "empty" }),
      frame(2, "model.output.delta", { attempt_id: "empty", delta: "" }),
      frame(3, "model.output.delta", { delta: "无请求标识" }),
      frame(4, "model.output.delta", { attempt_id: "old", delta: "未完成说明" }),
      frame(5, "model.output.delta", { attempt_id: "current", delta: "当前说明" }),
      frame(6, "model.output.interrupted", { attempt_id: "old" }),
      frame(7, "model.output.delta", { attempt_id: "old", delta: "不应续写" }),
    ]);
    expect(value.entries).toMatchObject([
      { attemptId: "old", text: "未完成说明", state: "interrupted" },
      { attemptId: "current", text: "当前说明", state: "streaming" },
    ]);
    expect(value.modelOutput).toMatchObject({ attemptId: "current", text: "当前说明" });
    expect(value.runOutcome.goal_outcome).toBe("unknown");
  });

  it("每轮公开正文维持已有长度上限", () => {
    const value = project([
      frame(1, "model.output.delta", { attempt_id: "long", delta: "前".repeat(64000) }),
      frame(2, "model.output.delta", { attempt_id: "long", delta: "后" }),
    ]);
    expect(value.modelOutput?.text).toHaveLength(64000);
    expect(value.modelOutput?.text.endsWith("后")).toBe(true);
    expect(value.entries).toMatchObject([{ text: value.modelOutput?.text }]);
    expect(value.modelOutput?.truncated).toBe(true);
  });

  it("同一请求的公开进展与最终候选按消息标识独立保存，结束元数据可补齐阶段", () => {
    const value = project([
      frame(1, "model.output.delta", { attempt_id: "a", message_id: "progress", phase: "commentary", generation: 2, delta: "先核查。" }),
      frame(2, "model.output.delta", { attempt_id: "a", message_id: "answer", delta: "核查" }),
      frame(3, "model.output.delta", { attempt_id: "a", message_id: "answer", delta: "完成。", phase: "unexpected" }),
      frame(4, "model.output.finished", { attempt_id: "a", phase: "final_answer", has_tool_calls: false,
        messages: [{ message_id: "progress", phase: "commentary" }, { message_id: "answer", phase: "final_answer" }] }),
    ]);
    expect(value.entries).toMatchObject([
      { messageId: "progress", phase: "commentary", generation: 2, text: "先核查。", state: "finished", truncated: false },
      { messageId: "answer", phase: "final_answer", text: "核查完成。", state: "finished", truncated: false },
    ]);
    expect(value.entries[0].key).not.toBe(value.entries[1].key);
    expect(value.modelOutput).toMatchObject({ messageId: "answer", phase: "final_answer" });
    expect(value.output).toBeNull();
    expect(value.runOutcome.goal_outcome).toBe("unknown");
  });

  it("请求级阶段只补齐单条未知消息，不覆盖明确进展或猜测多消息阶段", () => {
    const value = project([
      frame(1, "model.output.delta", { attempt_id: "old", delta: "旧正文" }),
      frame(2, "model.output.finished", { attempt_id: "old", phase: "final_answer" }),
      frame(3, "model.output.delta", { attempt_id: "explicit", phase: "commentary", delta: "进展" }),
      frame(4, "model.output.finished", { attempt_id: "explicit", phase: "final_answer" }),
      frame(5, "model.output.delta", { attempt_id: "multiple", message_id: "one", delta: "第一条" }),
      frame(6, "model.output.delta", { attempt_id: "multiple", message_id: "two", delta: "第二条" }),
      frame(7, "model.output.finished", { attempt_id: "multiple", phase: "final_answer", messages: [null, { message_id: "one", phase: "invalid" }] }),
    ]);
    expect(value.entries).toMatchObject([
      { messageId: null, phase: "final_answer" }, { phase: "commentary" },
      { messageId: "one", phase: null }, { messageId: "two", phase: null },
    ]);
  });

  it("中断关闭请求内所有消息，迟到的新消息与结束事件不恢复正文或覆盖新请求", () => {
    const value = project([
      frame(1, "model.output.delta", { attempt_id: "a", message_id: "one", delta: "一" }),
      frame(2, "model.output.delta", { attempt_id: "a", message_id: "two", delta: "二" }),
      frame(3, "model.output.delta", { attempt_id: "b", message_id: "current", delta: "当前" }),
      frame(4, "model.output.interrupted", { attempt_id: "a" }),
      frame(5, "model.output.delta", { attempt_id: "a", message_id: "late", delta: "不应出现" }),
      frame(6, "model.output.finished", { attempt_id: "a", phase: "final_answer" }),
    ]);
    expect(value.entries).toHaveLength(3);
    expect(value.entries).toMatchObject([{ state: "interrupted" }, { state: "interrupted" }, { state: "streaming" }]);
    expect(value.modelOutput).toMatchObject({ attemptId: "b", text: "当前", state: "streaming" });
  });

  it("区分旧终态、原始回答与验收替换正文的来源，不推断原始回答被提交", () => {
    const value = project([frame(1, "run.completed", { output: "旧记录" })]);
    expect(value.finalOutputAttemptId).toBeUndefined();
    applyRunFrame(value, frame(2, "run.completed", { output: "原始回答", final_output_attempt_id: "a" }));
    expect(value.finalOutputAttemptId).toBe("a");
    applyRunFrame(value, frame(3, "run.completed", { output: "验收替换", final_output_attempt_id: null }));
    expect(value.finalOutputAttemptId).toBeNull();
  });

  it("七步闭环：条目按事实构建，计划/工具/审批/终态齐全", () => {
    const projection = project(HAPPY);
    expect(projection.status).toBe("completed");
    expect(projection.lastSequence).toBe(18);
    expect(projection.output).toBe("完成");
    expect(projection.userMessage).toBe("任务请求");
    const kinds = projection.entries.map((entry) => entry.kind);
    expect(kinds).toContain("run-start");
    expect(kinds).toContain("context");
    expect(kinds).toContain("model-turn");
    expect(kinds).toContain("plan");
    expect(kinds.filter((kind) => kind === "tool")).toHaveLength(2);
    expect(kinds).toContain("approval");
    expect(kinds).toContain("patch-set");
    expect(kinds).toContain("artifact");
    expect(kinds).toContain("verification");
    expect(kinds).toContain("terminal");
    // 计划条目状态随 item_changed 更新
    expect(projection.plan?.items.find((item) => item.item_key === "a")?.status).toBe("completed");
    // 工具卡按 id 就地更新（不重复追加）
    const toolEntries = projection.entries.filter((entry) => entry.kind === "tool");
    expect(toolEntries.every((entry) => entry.kind === "tool" && entry.state === "completed")).toBe(true);
  });

  it("幂等：重复/迟到帧按游标跳过，不重复追加", () => {
    const projection = project(HAPPY.slice(0, 8));
    const before = projection.entries.length;
    applyRunFrame(projection, HAPPY[7]); // sequence 8 重放
    applyRunFrame(projection, HAPPY[3]); // sequence 4 迟到
    expect(projection.entries.length).toBe(before);
    expect(projection.lastSequence).toBe(8);
  });

  it("v0.9.0 H0 §8：decision.summary 投影为公开决策摘要；无 goal 不伪造", () => {
    // sequence 递增重编号（插入决策摘要帧）
    const raw = [
      ...HAPPY.slice(0, 4),
      frame(0, "decision.summary", {
        goal: "修复测试失败",
        method: "本轮决策：调用工具 read_code_file",
        next_steps: ["read_code_file"],
      }),
    ];
    const frames = raw.map((f, i) => frame(i + 1, f.type, f.payload));
    const projection = project(frames);
    const decision = projection.entries.find((e) => e.kind === "decision-summary");
    expect(decision).toBeTruthy();
    if (decision && decision.kind === "decision-summary") {
      expect(decision.goal).toBe("修复测试失败");
      expect(decision.method).toContain("read_code_file");
      expect(decision.nextSteps).toEqual(["read_code_file"]);
    }

    // 无 goal 的 payload 不投影（不伪造摘要）
    const empty = project([
      frame(1, "run.started", {}),
      frame(2, "decision.summary", { method: "无目标" }),
    ]);
    expect(empty.entries.some((e) => e.kind === "decision-summary")).toBe(false);
  });

  it("审批等待：状态收敛 waiting_approval，批准后恢复 running", () => {
    const projection = project(HAPPY.slice(0, 11));
    expect(projection.status).toBe("waiting_approval");
    const approval = projection.entries.find((entry) => entry.kind === "approval");
    expect(approval).toMatchObject({ approvalId: "ap-1", resolved: false });
    applyRunFrame(projection, HAPPY[11]); // approval_resolved
    expect(projection.status).toBe("running");
    expect(
      projection.entries.find((entry) => entry.kind === "approval")
    ).toMatchObject({ resolved: true });
  });

  it.each([
    ["run.failed", { error_code: "output_validation_failed", error: "校验失败" }, "failed", "output_validation_failed"],
    ["run.timed_out", { error_code: "wall_time" }, "timed_out", "wall_time"],
    ["run.limit_exceeded", { error_code: "max_steps" }, "limit_exceeded", "max_steps"],
    ["run.cancelled", { error_code: "approval_rejected", error: "tool approval rejected" }, "cancelled", "approval_rejected"],
  ] as const)(
    "终态 %s 收敛状态与错误码",
    (type, payload, expectedStatus, expectedCode) => {
      const projection = createRunProjection("run-x");
      applyRunFrame(projection, frame(1, "run.started", {}));
      applyRunFrame(projection, frame(2, type, { output: null, ...payload }));
      expect(projection.status).toBe(expectedStatus);
      expect(projection.error?.code).toBe(expectedCode);
      const last = projection.entries[projection.entries.length - 1];
    expect(last).toMatchObject({ kind: "terminal", status: expectedStatus });
    }
  );

  it("合成 run.terminal 不推进游标或替代持久化终态", () => {
    const projection = project(HAPPY.slice(0, 17));
    applyRunFrame(projection, frame(18, "run.terminal", { status: "completed" }));
    expect(projection.status).toBe("running");
    expect(projection.lastSequence).toBe(17);
    expect(projection.output).toBeNull(); // durable run.completed 未到，不虚构输出
    applyRunFrame(projection, frame(18, "run.completed", HAPPY[17].payload)); // 持久化终态仍使用真正的下一个序号。
    expect(projection.output).toBe("完成");
  });

  it("未知事件：记录诊断并安全忽略，不推测含义", () => {
    const projection = createRunProjection("run-y");
    applyRunFrame(projection, frame(1, "run.started", {}));
    applyRunFrame(projection, frame(2, "future.cool_feature", { whatever: 1 }));
    applyRunFrame(projection, frame(3, "future.cool_feature", { whatever: 2 }));
    applyRunFrame(projection, frame(4, "another.future_event", {}));
    expect(projection.unknownEventTypes).toEqual(["future.cool_feature", "another.future_event"]);
    expect(projection.entries).toHaveLength(1);
    expect(projection.status).toBe("running");
  });

  it("快照纠偏：更新的快照以 durable 事实覆盖 plan/output/状态", () => {
    const projection = project(HAPPY.slice(0, 9));
    const snapshot: RunSnapshot = {
      id: "run-1",
      session_id: 1,
      status: "completed",
      provider: "ollama",
      model: "qwen3-coder",
      last_event_sequence: 30,
      tool_call_count: 2,
      input_tokens: 2000,
      output_tokens: 300,
      cached_tokens: 0,
      cost_usd: null,
      output: "快照最终输出",
      final_output_attempt_id: "final-model",
      error_code: null,
      error_message: null,
      cancel_requested_at: null,
      started_at: "2026-08-22T00:00:00Z",
      completed_at: "2026-08-22T00:02:00Z",
      created_at: "2026-08-22T00:00:00Z",
      updated_at: "2026-08-22T00:02:00Z",
      active_in_process: false,
      steps: [],
      project_id: 1,
      workspace_id: 101,
      base_head_sha: "ab0000",
      base_branch_name: "main",
      base_git_dirty: false,
      model_profile_id: "local-coder",
      reasoning_effort: null,
      permission_mode: "readonly",
      plan: {
        version: 2,
        goal_version: 2,
        needs_review: false,
        explanation: "已根据追加要求完成核对",
        items: [
          { item_key: "a", ordinal: 1, title: "阅读代码", detail: null, status: "completed" },
          { item_key: "b", ordinal: 2, title: "修改文件", detail: null, status: "completed" },
          { item_key: "c", ordinal: 3, title: "补测试", detail: null, status: "completed" },
        ],
      },
      artifacts: [{ id: "art-9", kind: "final_report", title: "最终报告", rel_path: "reports/final.md" }],
    };
    reconcileRunWithSnapshot(projection, snapshot);
    expect(projection.status).toBe("completed");
    expect(projection.output).toBe("快照最终输出");
    expect(projection).toMatchObject({ projectId: 1, workspaceId: 101, sessionId: 1, finalOutputAttemptId: "final-model" });
    expect(projection.plan?.version).toBe(2);
    expect(projection.plan?.items).toHaveLength(3);
    expect(projection.plan).toMatchObject({ goal_version: 2, needs_review: false, explanation: "已根据追加要求完成核对" });
    expect(projection.entries.some((entry) => entry.kind === "artifact" && entry.key === "artifact:art-9")).toBe(true);
    expect(projection.entries.find(entry => entry.key === "artifact:art-9")).toMatchObject({ relPath: "reports/final.md" });
    // 游标不前跳：缺口由 events 重放补齐
    expect(projection.lastSequence).toBe(9);
    applyRunFrame(projection, frame(10, "plan.updated", { plan_version: 1, items: [] }));
    expect(projection.plan?.items).toHaveLength(3);
    applyRunFrame(projection, frame(11, "artifact.created", { artifact_id: "art-9", title: "最终报告", kind: "final_report" }));
    expect(projection.entries.find(entry => entry.key === "artifact:art-9")).toMatchObject({ relPath: "reports/final.md" });
    const legacy = project([frame(1, "artifact.created", { artifact_id: "art-9", kind: "final_report", title: "最终报告" })]);
    const restored = cloneRunProjection(legacy);
    reconcileRunWithSnapshot(restored, { ...snapshot, final_output_attempt_id: null });
    expect(restored.entries.filter(entry => entry.kind === "artifact")).toHaveLength(1);
    expect(restored.entries[0]).toMatchObject({ relPath: "reports/final.md" });
    expect(legacy.entries[0]).toMatchObject({ relPath: null });
    expect(restored.finalOutputAttemptId).toBeNull();
  });

  it("旧快照不回退已应用事实", () => {
    const projection = project(HAPPY);
    const stale: RunSnapshot = {
      ...{ id: "run-1", session_id: 1, status: "running", provider: null, model: null },
      last_event_sequence: 3,
      tool_call_count: 0,
      input_tokens: 0,
      output_tokens: 0,
      cached_tokens: 0,
      cost_usd: null,
      output: null,
      error_code: null,
      error_message: null,
      cancel_requested_at: null,
      started_at: null,
      completed_at: null,
      created_at: "2026-08-22T00:00:00Z",
      updated_at: "2026-08-22T00:00:00Z",
      active_in_process: true,
      steps: [],
      project_id: 1,
      workspace_id: 101,
      base_head_sha: null,
      base_branch_name: null,
      base_git_dirty: null,
      model_profile_id: null,
      reasoning_effort: null,
      permission_mode: null,
      plan: null,
      artifacts: [],
    } as RunSnapshot;
    reconcileRunWithSnapshot(projection, stale);
    expect(projection.status).toBe("completed");
    expect(projection.lastSequence).toBe(18);
  });

  it("patch_set 异常路径：failed/rolled_back/unknown 语义呈现", () => {
    const projection = createRunProjection("run-z");
    applyRunFrame(projection, frame(1, "patch_set.preview_created", { patch_set_id: "ps-9", preview_version: 2, file_count: 1 }));
    applyRunFrame(projection, frame(2, "patch_set.failed", { patch_set_id: "ps-9", error_code: "patchset_conflict", error_message: "目标文件已被外部修改" }));
    const entry = projection.entries.find((item) => item.kind === "patch-set");
    expect(entry).toMatchObject({ state: "failed", errorCode: "patchset_conflict" });
  });
});
