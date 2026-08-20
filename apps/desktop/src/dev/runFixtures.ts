/**
 * v0.6.0 C4：RunProjector 开发 fixture（仅开发模式 / UI Lab / 测试使用，
 * 生产构建不引用）。使用真实公开 DTO 形状（C0 §4.5/§7.2 事件与快照契约），
 * 覆盖重复、乱序、重连与切换场景，禁止虚构后端状态。
 */
import type {
  RunArtifact,
  RunDurableEvent,
  RunPlanItem,
  RunPlanSnapshot,
} from "../types";

export interface RunFixture {
  runId: string;
  /** 完整事件流（含非 durable 的临时 delta 事件，模拟真实 SSE）。 */
  events: RunDurableEvent[];
  /** 重连纠偏快照（GET /agent-runs/{id} 响应）。 */
  snapshot: { plan: RunPlanSnapshot | null; artifacts: RunArtifact[] };
  lastSequence: number;
}

function planItem(
  id: string,
  item_key: string,
  title: string,
  status: RunPlanItem["status"],
  plan_version: number,
  ordinal: number,
): RunPlanItem {
  return {
    id,
    run_id: "run-fixture",
    plan_version,
    item_key,
    ordinal,
    title,
    detail: `${title} 的详情`,
    status,
    evidence_json: null,
    created_at: "2026-08-20T10:00:00.000Z",
    updated_at: "2026-08-20T10:00:00.000Z",
  };
}

function durable(
  runId: string,
  sequence: number,
  type: RunDurableEvent["type"],
  payload: Record<string, unknown>,
): RunDurableEvent {
  return { run_id: runId, sequence, type, payload, created_at: "2026-08-20T10:00:00.000Z" };
}

/** 标准「定位失败 → 修复 → 验证」计划流 fixture。 */
export function buildRunPlanFixture(runId: string): RunFixture {
  const base = 10;
  return {
    runId,
    events: [
      // 临时 delta：run.started 不进投影，只推进 seen sequence
      durable(runId, base + 1, "plan.created", {
        plan_version: 1,
        items: [
          { item_key: "inspect_failure", title: "定位失败测试", status: "pending" },
          { item_key: "apply_fix", title: "修复缺陷", status: "pending" },
          { item_key: "verify", title: "验证通过", status: "pending" },
        ],
      }),
      durable(runId, base + 2, "plan.item_changed", {
        plan_version: 1,
        item_key: "inspect_failure",
        previous_status: "pending",
        status: "in_progress",
      }),
      durable(runId, base + 3, "plan.updated", {
        previous_version: 1,
        plan_version: 2,
      }),
      durable(runId, base + 4, "artifact.created", {
        artifact_id: "artifact-1",
        kind: "test_report",
        title: "单元测试报告",
        step_id: null,
      }),
      // 重复事件（模拟客户端重试）
      durable(runId, base + 4, "artifact.created", {
        artifact_id: "artifact-1",
        kind: "test_report",
        title: "单元测试报告",
        step_id: null,
      }),
      // 乱序迟到事件（模拟重连后竞态）
      durable(runId, base + 2, "plan.item_changed", {
        plan_version: 1,
        item_key: "inspect_failure",
        previous_status: "pending",
        status: "in_progress",
      }),
    ],
    snapshot: {
      plan: {
        version: 2,
        items: [
          planItem("item-1", "inspect_failure", "定位失败测试", "completed", 2, 1),
          planItem("item-2", "apply_fix", "修复缺陷", "in_progress", 2, 2),
          planItem("item-3", "verify", "验证通过", "pending", 2, 3),
        ],
      },
      artifacts: [
        {
          id: "artifact-1",
          run_id: runId,
          kind: "test_report",
          title: "单元测试报告",
          rel_path: "reports/test.txt",
          step_id: null,
          content_sha256: "a".repeat(64),
          metadata: { summary: "3 passed" },
          created_at: "2026-08-20T10:00:00.000Z",
        },
      ],
    },
    lastSequence: base + 4,
  };
}

/** flag 关闭（无 plan/artifacts）的 legacy run fixture。 */
export function buildLegacyRunFixture(runId: string): RunFixture {
  return {
    runId,
    events: [],
    snapshot: { plan: null, artifacts: [] },
    lastSequence: 0,
  };
}
