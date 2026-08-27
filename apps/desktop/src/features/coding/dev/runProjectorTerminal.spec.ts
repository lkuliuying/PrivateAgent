import { describe, expect, it } from "vitest";

import {
  applyRunFrame,
  createRunProjection,
  reconcileRunWithSnapshot,
  type TranscriptEntry,
} from "../model/runProjector";
import type { RunSnapshot, RunStreamFrame } from "../model/runContracts";

function terminalEntry(projection: { entries: TranscriptEntry[] }) {
  return projection.entries.find((entry) => entry.kind === "terminal");
}

describe("runProjector 终态错误码保持（E2E 矩阵 14/18 守护）", () => {
  it("run.failed 后的合成 run.terminal 不得洗掉错误码", () => {
    const projection = createRunProjection("run-x", "修复侧栏遮挡");
    const frames: RunStreamFrame[] = [
      { sequence: 1, type: "run.started", payload: {} },
      {
        sequence: 2,
        type: "run.failed",
        payload: { output: null, error: "输出校验未通过", error_code: "output_validation_failed", tool_call_count: 0, input_tokens: 100, output_tokens: 0, cached_tokens: 0, cost_usd: null },
      },
      { sequence: 3, type: "run.terminal", payload: { status: "failed" } },
    ];
    for (const frame of frames) applyRunFrame(projection, frame);
    expect(projection.status).toBe("failed");
    expect(projection.error?.code).toBe("output_validation_failed");
    const terminal = terminalEntry(projection);
    expect(terminal?.kind === "terminal" && terminal.errorCode).toBe(
      "output_validation_failed"
    );
  });

  it("run.cancelled 错误码在终态条目中保持", () => {
    const projection = createRunProjection("run-y", "修复侧栏遮挡");
    const frames: RunStreamFrame[] = [
      { sequence: 1, type: "run.started", payload: {} },
      {
        sequence: 2,
        type: "run.cancelled",
        payload: { output: null, error: "tool approval rejected", error_code: "approval_rejected", tool_call_count: 1, input_tokens: 100, output_tokens: 10, cached_tokens: 0, cost_usd: null },
      },
      { sequence: 3, type: "run.terminal", payload: { status: "cancelled" } },
    ];
    for (const frame of frames) applyRunFrame(projection, frame);
    expect(projection.status).toBe("cancelled");
    const terminal = terminalEntry(projection);
    expect(terminal?.kind === "terminal" && terminal.errorCode).toBe(
      "approval_rejected"
    );
  });

  it("终态结算快照无错误码时不得洗掉已投影错误码（E2E 矩阵 14/18 同案）", () => {
    const projection = createRunProjection("run-z", "修复侧栏遮挡");
    const frames: RunStreamFrame[] = [
      { sequence: 1, type: "run.started", payload: {} },
      {
        sequence: 2,
        type: "run.failed",
        payload: { output: null, error: "输出校验未通过", error_code: "output_validation_failed", tool_call_count: 0, input_tokens: 100, output_tokens: 0, cached_tokens: 0, cost_usd: null },
      },
      { sequence: 3, type: "run.terminal", payload: { status: "failed" } },
    ];
    for (const frame of frames) applyRunFrame(projection, frame);
    const snapshot = {
      id: "run-z",
      session_id: 11,
      trace_id: null,
      status: "failed",
      provider: "ollama",
      model: "qwen3:4b",
      last_event_sequence: 3,
      tool_call_count: 0,
      input_tokens: 100,
      output_tokens: 0,
      cached_tokens: 0,
      cost_usd: null,
      output: null,
      error_code: null,
      error_message: null,
      cancel_requested_at: null,
      started_at: null,
      completed_at: null,
      plan: null,
      artifacts: [],
    } as unknown as RunSnapshot;
    reconcileRunWithSnapshot(projection, snapshot);
    const terminal = terminalEntry(projection);
    expect(terminal?.kind === "terminal" && terminal.errorCode).toBe(
      "output_validation_failed"
    );
  });
});
