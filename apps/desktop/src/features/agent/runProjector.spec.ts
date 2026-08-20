/**
 * v0.6.0 C4：runProjector 单测。
 *
 * 覆盖计划书 C4 退出条件：
 * - 重复事件幂等（(run_id, sequence) 去重）
 * - 乱序迟到事件不回退已投影状态
 * - 重连快照纠偏（reconcileWithSnapshot）
 * - 切换 thread 后旧 run 迟到事件被拒绝
 * 以及 durable/delta 区分、legacy run 兼容与事件链完整性。
 */
import { describe, expect, it } from "vitest";
import type { RunDurableEvent } from "../../types";
import { buildLegacyRunFixture, buildRunPlanFixture } from "../../dev/runFixtures";
import {
  applyDurableEvent,
  createRunProjection,
  reconcileWithSnapshot,
  switchRun,
} from "./runProjector";

/** 模拟非 durable 的临时 delta 事件（如 run.started），仅用于测试。 */
function deltaEvent(runId: string, sequence: number): RunDurableEvent {
  return {
    run_id: runId,
    sequence,
    type: "run.started" as RunDurableEvent["type"],
    payload: { step_id: null },
  };
}

describe("runProjector 重复事件幂等", () => {
  it("相同 sequence 的重复 artifact.created 只投影一次", () => {
    const fixture = buildRunPlanFixture("run-1");
    let projection = createRunProjection("run-1");
    for (const event of fixture.events) {
      projection = applyDurableEvent(projection, event);
    }
    // fixture 内 seq+4 artifact.created 出现两次，其余事件 5 个 + 1 个乱序迟到
    expect(projection.artifacts).toHaveLength(1);
    expect(projection.artifacts[0]).toMatchObject({
      id: "artifact-1",
      kind: "test_report",
      title: "单元测试报告",
    });
  });

  it("重复事件不推进 lastSequence，续读边界稳定", () => {
    const fixture = buildRunPlanFixture("run-1");
    let projection = createRunProjection("run-1");
    for (const event of fixture.events) {
      projection = applyDurableEvent(projection, event);
    }
    expect(projection.lastSequence).toBe(fixture.lastSequence);
    const before = projection.lastSequence;
    projection = applyDurableEvent(projection, fixture.events[4]); // 重复 seq+4
    expect(projection.lastSequence).toBe(before);
  });
});

describe("runProjector 乱序迟到事件", () => {
  it("迟到旧事件被忽略，不回退已投影状态", () => {
    const fixture = buildRunPlanFixture("run-1");
    let projection = createRunProjection("run-1");
    for (const event of fixture.events) {
      projection = applyDurableEvent(projection, event);
    }
    // fixture 末尾是 seq+2 的 item_changed（inspect_failure -> in_progress）
    // 与 seq+3 plan.updated 后相比它是旧事件：状态保持投影后的结果
    const inspect = projection.plan?.items.find((i) => i.item_key === "inspect_failure");
    expect(inspect?.status).toBe("in_progress");
  });

  it("plan.updated 前的 item_changed 迟到不会覆盖新版本视图", () => {
    let projection = createRunProjection("run-1");
    projection = applyDurableEvent(projection, {
      run_id: "run-1",
      sequence: 11,
      type: "plan.created",
      payload: {
        plan_version: 1,
        items: [{ item_key: "inspect_failure", title: "定位失败测试", status: "pending" }],
      },
    });
    projection = applyDurableEvent(projection, {
      run_id: "run-1",
      sequence: 13,
      type: "plan.updated",
      payload: { previous_version: 1, plan_version: 2 },
    });
    // 迟到旧事件（seq 12 对应 v1 的 item_changed）：sequence 已落后，忽略
    projection = applyDurableEvent(projection, {
      run_id: "run-1",
      sequence: 12,
      type: "plan.item_changed",
      payload: { plan_version: 1, item_key: "inspect_failure", status: "in_progress" },
    });
    expect(projection.plan?.version).toBe(2);
  });
});

describe("runProjector 重连快照纠偏", () => {
  it("快照覆盖投影视图并标记 reconciled", () => {
    const fixture = buildRunPlanFixture("run-1");
    let projection = createRunProjection("run-1");
    for (const event of fixture.events) {
      projection = applyDurableEvent(projection, event);
    }
    projection = reconcileWithSnapshot(projection, fixture.snapshot, fixture.lastSequence);

    expect(projection.reconciled).toBe(true);
    expect(projection.plan?.version).toBe(2);
    expect(projection.plan?.items).toHaveLength(3);
    expect(projection.plan?.items.map((i) => i.item_key)).toEqual([
      "inspect_failure",
      "apply_fix",
      "verify",
    ]);
    // 快照状态（completed/in_progress/pending）覆盖事件流投影的 in_progress
    expect(projection.plan?.items[0].status).toBe("completed");
    expect(projection.plan?.items[1].status).toBe("in_progress");
    expect(projection.artifacts).toHaveLength(1);
    expect(projection.lastSequence).toBe(fixture.lastSequence);
  });

  it("lastSequence 取快照侧与现有投影的较大者，续读不回退", () => {
    const fixture = buildRunPlanFixture("run-1");
    let projection = createRunProjection("run-1");
    for (const event of fixture.events) {
      projection = applyDurableEvent(projection, event);
    }
    // 快照侧序列更高：取快照侧
    projection = reconcileWithSnapshot(projection, fixture.snapshot, fixture.lastSequence + 10);
    expect(projection.lastSequence).toBe(fixture.lastSequence + 10);
    // 快照侧序列落后：保留现有投影
    projection = reconcileWithSnapshot(projection, fixture.snapshot, 3);
    expect(projection.lastSequence).toBe(fixture.lastSequence + 10);
  });

  it("重连后迟到旧事件仍被忽略（快照是事实）", () => {
    const fixture = buildRunPlanFixture("run-1");
    let projection = createRunProjection("run-1");
    projection = reconcileWithSnapshot(projection, fixture.snapshot, fixture.lastSequence);
    // 快照后到达的旧事件（seq+1 plan.created）不覆盖快照
    projection = applyDurableEvent(projection, fixture.events[0]);
    expect(projection.plan?.version).toBe(2);
    expect(projection.plan?.items[0].status).toBe("completed");
  });
});

describe("runProjector 切换 thread", () => {
  it("switchRun 丢弃旧投影，旧 run 迟到事件被拒绝", () => {
    const fixture = buildRunPlanFixture("run-1");
    let projection = createRunProjection("run-1");
    for (const event of fixture.events) {
      projection = applyDurableEvent(projection, event);
    }
    projection = switchRun(projection, "run-2");
    expect(projection.runId).toBe("run-2");
    expect(projection.plan).toBeNull();
    expect(projection.artifacts).toHaveLength(0);
    expect(projection.lastSequence).toBe(0);

    // 旧 run 的迟到事件被拒绝
    const after = applyDurableEvent(projection, fixture.events[3]);
    expect(after).toBe(projection);
  });

  it("switchRun 到相同 runId 时保持原投影", () => {
    const fixture = buildRunPlanFixture("run-1");
    let projection = createRunProjection("run-1");
    for (const event of fixture.events) {
      projection = applyDurableEvent(projection, event);
    }
    expect(switchRun(projection, "run-1")).toBe(projection);
  });
});

describe("runProjector durable 与 delta 区分", () => {
  it("非 durable 事件只推进 lastSequence，不改变视图", () => {
    let projection = createRunProjection("run-1");
    projection = applyDurableEvent(projection, deltaEvent("run-1", 5));
    expect(projection.plan).toBeNull();
    expect(projection.artifacts).toHaveLength(0);
    expect(projection.lastSequence).toBe(5);
  });

  it("delta 事件之后 durable 事件仍正常投影", () => {
    let projection = createRunProjection("run-1");
    projection = applyDurableEvent(projection, deltaEvent("run-1", 5));
    projection = applyDurableEvent(projection, {
      run_id: "run-1",
      sequence: 6,
      type: "plan.created",
      payload: {
        plan_version: 1,
        items: [{ item_key: "inspect_failure", title: "定位失败测试", status: "pending" }],
      },
    });
    expect(projection.plan?.version).toBe(1);
    expect(projection.plan?.items).toHaveLength(1);
  });
});

describe("runProjector 事件链完整性", () => {
  it("plan.created -> item_changed -> plan.updated -> artifact.created 全链路", () => {
    let projection = createRunProjection("run-1");
    projection = applyDurableEvent(projection, {
      run_id: "run-1",
      sequence: 1,
      type: "plan.created",
      payload: {
        plan_version: 1,
        items: [
          { item_key: "inspect_failure", title: "定位失败测试", status: "pending" },
          { item_key: "apply_fix", title: "修复缺陷", status: "pending" },
        ],
      },
    });
    projection = applyDurableEvent(projection, {
      run_id: "run-1",
      sequence: 2,
      type: "plan.item_changed",
      payload: {
        plan_version: 1,
        item_key: "inspect_failure",
        previous_status: "pending",
        status: "in_progress",
      },
    });
    projection = applyDurableEvent(projection, {
      run_id: "run-1",
      sequence: 3,
      type: "plan.updated",
      payload: { previous_version: 1, plan_version: 2 },
    });
    projection = applyDurableEvent(projection, {
      run_id: "run-1",
      sequence: 4,
      type: "artifact.created",
      payload: { artifact_id: "a-1", kind: "diff", title: "补丁", step_id: null },
    });
    expect(projection.plan?.version).toBe(2);
    expect(projection.plan?.items.find((i) => i.item_key === "inspect_failure")?.status).toBe(
      "in_progress",
    );
    expect(projection.artifacts.map((a) => a.id)).toEqual(["a-1"]);
  });

  it("item_changed 对未知 item_key 不新增项", () => {
    let projection = createRunProjection("run-1");
    projection = applyDurableEvent(projection, {
      run_id: "run-1",
      sequence: 1,
      type: "plan.created",
      payload: {
        plan_version: 1,
        items: [{ item_key: "inspect_failure", title: "定位失败测试", status: "pending" }],
      },
    });
    projection = applyDurableEvent(projection, {
      run_id: "run-1",
      sequence: 2,
      type: "plan.item_changed",
      payload: { plan_version: 1, item_key: "ghost", status: "failed" },
    });
    expect(projection.plan?.items).toHaveLength(1);
  });

  it("plan.updated 在 plan 未创建时只推进 lastSequence", () => {
    let projection = createRunProjection("run-1");
    projection = applyDurableEvent(projection, {
      run_id: "run-1",
      sequence: 1,
      type: "plan.updated",
      payload: { previous_version: 1, plan_version: 2 },
    });
    expect(projection.plan).toBeNull();
    expect(projection.lastSequence).toBe(1);
  });
});

describe("runProjector legacy 兼容", () => {
  it("legacy run 无 plan/artifacts，视图为空", () => {
    const fixture = buildLegacyRunFixture("run-legacy");
    let projection = createRunProjection("run-legacy");
    for (const event of fixture.events) {
      projection = applyDurableEvent(projection, event);
    }
    projection = reconcileWithSnapshot(projection, fixture.snapshot, fixture.lastSequence);
    expect(projection.plan).toBeNull();
    expect(projection.artifacts).toHaveLength(0);
    expect(projection.lastSequence).toBe(0);
    expect(projection.reconciled).toBe(true);
  });
});
