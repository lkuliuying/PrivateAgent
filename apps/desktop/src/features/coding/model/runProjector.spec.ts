import { describe, expect, it } from "vitest";
import {
  applyRunFrame,
  createRunProjection,
  reconcileRunWithSnapshot,
} from "./runProjector";
import type { RunSnapshot, RunStreamFrame } from "./runContracts";

function frame(sequence: number, type: string, payload: Record<string, unknown> = {}): RunStreamFrame {
  return { sequence, type, payload };
}

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
  it("七步闭环：条目按事实构建，计划/工具/审批/终态齐全", () => {
    const projection = project(HAPPY);
    expect(projection.status).toBe("completed");
    expect(projection.lastSequence).toBe(19);
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

  it("合成 run.terminal：仅在未收敛时补状态，不覆盖 durable 输出", () => {
    const projection = project(HAPPY.slice(0, 17));
    applyRunFrame(projection, frame(18, "run.terminal", { status: "completed" }));
    expect(projection.status).toBe("completed");
    expect(projection.output).toBeNull(); // durable run.completed 未到，不虚构输出
    applyRunFrame(projection, frame(19, "run.completed", HAPPY[17].payload)); // durable 终态补全文
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
    expect(projection.plan?.version).toBe(2);
    expect(projection.plan?.items).toHaveLength(3);
    expect(projection.entries.some((entry) => entry.kind === "artifact" && entry.key === "artifact:art-9")).toBe(true);
    // 游标不前跳：缺口由 events 重放补齐
    expect(projection.lastSequence).toBe(9);
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
    expect(projection.lastSequence).toBe(19);
  });

  it("patch_set 异常路径：failed/rolled_back/unknown 语义呈现", () => {
    const projection = createRunProjection("run-z");
    applyRunFrame(projection, frame(1, "patch_set.preview_created", { patch_set_id: "ps-9", preview_version: 2, file_count: 1 }));
    applyRunFrame(projection, frame(2, "patch_set.failed", { patch_set_id: "ps-9", error_code: "patchset_conflict", error_message: "目标文件已被外部修改" }));
    const entry = projection.entries.find((item) => item.kind === "patch-set");
    expect(entry).toMatchObject({ state: "failed", errorCode: "patchset_conflict" });
  });
});
