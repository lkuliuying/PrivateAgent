import { describe, expect, it } from "vitest";
import samples from "../../../../../../tests/coding_acceptance/s1-wire-examples.json";
import { parseExecutionResult, parseRunOutcome, runResultMeta, unknownRunOutcome } from "./runOutcome";
import { applyRunFrame, createRunProjection, reconcileRunWithSnapshot } from "./runProjector";
import type { RunSnapshot } from "./runContracts";

describe("S1 同源 API 契约与投影", () => {
  it("修改证据齐全时展示已修改但仍未验证，缺失证据或其他未满足要求不放行", () => {
    const outcome = unknownRunOutcome("run");
    outcome.requirements = [{ requirement_id: "file", kind: "file_changed", description: "修改 app.py", required: true }];
    outcome.verification_results = [{ requirement_id: "file", status: "passed", evidence_ids: ["patch"] }];
    outcome.evidence_ids = ["patch"];
    outcome.unverified_items = ["用户禁止运行测试；本轮未执行测试，测试结果未验证"];
    expect(runResultMeta("completed", outcome).label).toBe("修改已完成，仍有未验证项");
    expect(runResultMeta("cancelled", outcome).label).toBe("已取消");
    expect(runResultMeta("failed", outcome).label).toBe("执行失败，结果未确认");
    for (const key of ["requirements", "verification_results", "unverified_items"] as const) {
      expect(runResultMeta("completed", { ...outcome, [key]: undefined }).label).toBe("结果未确认");
    }
    for (const verification_results of [[], [{ ...outcome.verification_results[0], evidence_ids: [] }],
      [{ ...outcome.verification_results[0], status: "failed" as const }]]) {
      expect(runResultMeta("completed", { ...outcome, verification_results }).label).toBe("结果未确认");
    }
    expect(runResultMeta("completed", { ...outcome, requirements: [
      ...outcome.requirements, { requirement_id: "manual", kind: "manual", description: "保持 API 兼容" },
    ] }).label).toBe("结果未确认");
  });

  it.each(Object.entries(samples))("%s 的快照与终态重放一致且幂等", (_name, sample) => {
    const snapshot = sample.snapshot as unknown as RunSnapshot;
    const fromEvents = createRunProjection(snapshot.id);
    for (const event of sample.events) applyRunFrame(fromEvents, event);
    expect(fromEvents.runOutcome.goal_outcome).toBe(sample.snapshot.goal_outcome);
    const before = JSON.stringify(fromEvents);
    for (const event of sample.events) applyRunFrame(fromEvents, event);
    expect(JSON.stringify(fromEvents)).toBe(before);
    const fromSnapshot = createRunProjection(snapshot.id);
    reconcileRunWithSnapshot(fromSnapshot, snapshot);
    expect(fromSnapshot.runOutcome).toEqual(fromEvents.runOutcome);
    expect(fromSnapshot.completionRequirements).toEqual(sample.snapshot.completion_requirements);
  });

  it("旧记录、未知协议、错配运行和不完整证据一律未知", () => {
    const value = samples.verified.snapshot.run_outcome;
    for (const raw of [undefined, { ...value, schema_version: "2.0" }, { ...value, run_id: "other" },
      { ...value, evidence_ids: [] }, { ...value, evidence_refs: [] }, { ...value, verification_results: [] }, { ...value, requirements: [] },
      { ...value, unverified_items: ["尚未确认"] }]) {
      expect(parseRunOutcome(raw, value.run_id).goal_outcome).toBe("unknown");
    }
  });

  it("验证中状态不会替换运行生命周期，取消仍保持取消", () => {
    const projection = createRunProjection("run");
    applyRunFrame(projection, { type: "run.started", sequence: 1, payload: {} });
    applyRunFrame(projection, { type: "output.validation_started", sequence: 2, payload: { verifier: "local_completion" } });
    expect(projection.status).toBe("running");
    expect(runResultMeta(projection.status, projection.runOutcome, projection.verifying).label).toBe("验证中");
    applyRunFrame(projection, { type: "run.cancelled", sequence: 3, payload: {} });
    expect(projection.verifying).toBe(false);
    expect(runResultMeta(projection.status, projection.runOutcome).label).toBe("已取消");
  });

  it("命令失败不会因 completed 或伪造 succeeded 被解释为通过", () => {
    const execution = samples.test_failed.executions[0];
    const result = parseExecutionResult(execution.execution_result, execution.id)!;
    expect(result.outcome).toBe("exited");
    expect(result.exit_code).toBe(1);
    expect(result.validation_outcome).toBe("failed");
    expect(parseExecutionResult({ ...result, validation_outcome: "succeeded" }, execution.id)).toBeUndefined();
    expect(parseExecutionResult({ ...result, schema_version: "2.0" }, execution.id)).toBeUndefined();
  });
});
