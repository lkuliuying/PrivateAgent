import { describe, expect, it, vi } from "vitest";
import { flushPromises } from "@vue/test-utils";
import { effectScope } from "vue";
import { useRunStream, type RunStreamDeps } from "./useRunStream";
import type { RunSnapshot, RunStreamFrame } from "../model/runContracts";

function snapshot(overrides: Partial<RunSnapshot> = {}): RunSnapshot {
  return {
    id: "run-1",
    session_id: 1,
    status: "running",
    provider: null,
    model: null,
    last_event_sequence: 0,
    tool_call_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    cached_tokens: 0,
    cost_usd: null,
    output: null,
    error_code: null,
    error_message: null,
    cancel_requested_at: null,
    started_at: "2026-08-22T00:00:00Z",
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
    ...overrides,
  };
}

interface StreamCall {
  runId: string;
  afterSequence: number;
  callbacks: {
    onFrame: (frame: RunStreamFrame) => void;
    onError: (message: string) => void;
    onClose: () => void;
  };
}

function makeDeps() {
  const streams: StreamCall[] = [];
  const timers: Array<() => void> = [];
  const deps: RunStreamDeps = {
    createRun: vi.fn(async () => snapshot()),
    fetchSnapshot: vi.fn(async () => snapshot()),
    fetchEvents: vi.fn(async () => ({ items: [] as RunStreamFrame[] })),
    openStream: vi.fn((runId, afterSequence, callbacks) => {
      const call = { runId, afterSequence, callbacks };
      streams.push(call);
      return new AbortController();
    }),
    cancelRun: vi.fn(async () => undefined),
    schedule: (handler) => {
      timers.push(handler);
      return timers.length;
    },
    cancelSchedule: vi.fn(),
  };
  return { deps, streams, timers, runTimers: () => timers.splice(0).forEach((handler) => handler()) };
}

/** useRunStream 在 effectScope 中创建，测试后手动 dispose 触发清理 */
function scopedSetup(deps: RunStreamDeps) {
  const scope = effectScope();
  const controller = scope.run(() => useRunStream(deps))!;
  return { scope, controller };
}

const INPUT = {
  session_id: 1,
  message: "修复窄屏遮挡",
  project_id: 1,
  workspace_id: 101,
};

describe("useRunStream", () => {
  it("startRun：创建→快照→续流，帧按序投影，run.terminal 收敛", async () => {
    const { deps, streams } = makeDeps();
    (deps.fetchSnapshot as ReturnType<typeof vi.fn>).mockResolvedValue(
      snapshot({
        status: "completed",
        last_event_sequence: 2,
        output: "完成",
        completed_at: "2026-08-22T00:00:05Z",
      })
    );
    const { scope, controller } = scopedSetup(deps);
    await controller.startRun(INPUT);
    expect(deps.createRun).toHaveBeenCalledWith(INPUT);
    expect(streams).toHaveLength(1);
    expect(streams[0].afterSequence).toBe(0);
    streams[0].callbacks.onFrame({ sequence: 1, type: "run.started", payload: {} });
    streams[0].callbacks.onFrame({
      sequence: 2,
      type: "run.completed",
      payload: { output: "完成", error_code: null },
    });
    expect(controller.projection.value?.status).toBe("completed");
    expect(controller.projection.value?.output).toBe("完成");
    streams[0].callbacks.onFrame({ sequence: 3, type: "run.terminal", payload: { status: "completed" } });
    await flushPromises();
    expect(controller.phase.value).toBe("terminal");
    expect(deps.fetchSnapshot).toHaveBeenCalledWith("run-1");
    expect(controller.projection.value?.completedAt).toBe("2026-08-22T00:00:05Z");
    scope.stop();
  });

  it("迟到回调拒绝：detach 后旧流帧不再写入", async () => {
    const { deps, streams } = makeDeps();
    const { scope, controller } = scopedSetup(deps);
    await controller.startRun(INPUT);
    const stream = streams[0];
    stream.callbacks.onFrame({ sequence: 1, type: "run.started", payload: {} });
    controller.detach();
    stream.callbacks.onFrame({ sequence: 2, type: "run.completed", payload: { output: "旧帧" } });
    expect(controller.projection.value?.status).toBe("running");
    expect(controller.projection.value?.output).toBeNull();
    expect(controller.phase.value).toBe("idle");
    scope.stop();
  });

  it("断线恢复：错误→退避重连→快照纠偏→缺口重放→续流带游标", async () => {
    const { deps, streams, runTimers } = makeDeps();
    (deps.fetchSnapshot as ReturnType<typeof vi.fn>).mockResolvedValue(
      snapshot({ last_event_sequence: 5, status: "running" })
    );
    (deps.fetchEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        { sequence: 1, type: "run.started", payload: {} },
        { sequence: 2, type: "plan.created", payload: { plan_version: 1, items: [{ item_key: "a", title: "步骤", status: "pending" }] } },
        { sequence: 3, type: "model.started", payload: { ordinal: 1 } },
        { sequence: 4, type: "model.completed", payload: { ordinal: 1, input_tokens: 10, output_tokens: 5 } },
        { sequence: 5, type: "tool.started", payload: { tool_call_id: "tc-1", name: "read_code_file" } },
      ] as RunStreamFrame[],
    });
    const { scope, controller } = scopedSetup(deps);
    await controller.startRun(INPUT);
    streams[0].callbacks.onFrame({ sequence: 1, type: "run.started", payload: {} });
    streams[0].callbacks.onError("network reset");
    expect(controller.phase.value).toBe("reconnecting");
    expect(controller.connectionError.value).toBe("network reset");
    await runTimers();
    await flushPromises();
    // 快照 + 缺口重放后以游标 5 续流
    expect(streams[1].afterSequence).toBe(5);
    expect(controller.projection.value?.plan?.items).toHaveLength(1);
    expect(controller.phase.value).toBe("streaming");
    scope.stop();
  });

  it("重连遇终态快照：不再开流", async () => {
    const { deps, streams, runTimers } = makeDeps();
    (deps.fetchSnapshot as ReturnType<typeof vi.fn>).mockResolvedValue(
      snapshot({ status: "completed", last_event_sequence: 2, output: "已结束" })
    );
    const { scope, controller } = scopedSetup(deps);
    await controller.startRun(INPUT);
    streams[0].callbacks.onClose();
    await runTimers();
    await flushPromises();
    expect(controller.phase.value).toBe("terminal");
    expect(streams).toHaveLength(1);
    expect(controller.projection.value?.output).toBe("已结束");
    scope.stop();
  });

  it("取消走 API，状态由事件/快照收敛（不本地猜测）", async () => {
    const { deps, streams } = makeDeps();
    const { scope, controller } = scopedSetup(deps);
    await controller.startRun(INPUT);
    streams[0].callbacks.onFrame({ sequence: 1, type: "run.started", payload: {} });
    await controller.cancelActive();
    expect(deps.cancelRun).toHaveBeenCalledWith("run-1");
    expect(controller.projection.value?.status).toBe("running");
    scope.stop();
  });

  it("attachRun：重开任务时保留 durable 历史恢复出的用户请求", async () => {
    const { deps } = makeDeps();
    (deps.fetchSnapshot as ReturnType<typeof vi.fn>).mockResolvedValue(
      snapshot({ status: "completed", output: "已完成", last_event_sequence: 0 })
    );
    const { scope, controller } = scopedSetup(deps);
    await controller.attachRun("run-1", "创建 hello.txt");
    expect(controller.projection.value?.userMessage).toBe("创建 hello.txt");
    expect(controller.projection.value?.output).toBe("已完成");
    expect(controller.phase.value).toBe("terminal");
    scope.stop();
  });
});
