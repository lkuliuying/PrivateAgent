/**
 * v0.6.0 C4：runProjector —— 按 (run_id, sequence) 幂等投影 durable 事件。
 *
 * 公开契约（C0 §4.5/§7.2）：
 * - 只有 plan.created / plan.updated / plan.item_changed / artifact.created
 *   是 durable 公开事件，进入投影；其余事件是临时 delta，只推进 seen
 *   sequence（SSE 续读边界），不改变 plan/artifacts 视图。
 * - 投影按 `(run_id, sequence)` 幂等：重复或乱序到达的旧事件被忽略，
 *   不会回退已投影状态。
 * - 重连时用 GET /agent-runs/{id} 快照纠偏：快照是事实，覆盖投影视图。
 * - 切换 thread 后旧 run 的迟到事件被拒绝（run_id 不匹配）。
 *
 * 纯函数 + 不可变返回，便于 Vitest 单测与 Vue 响应式集成。
 */
import type {
  PlanItemStatus,
  RunArtifact,
  RunDurableEvent,
  RunDurableEventType,
  RunPlanSnapshot,
} from "../../types";

export const DURABLE_EVENT_TYPES: readonly RunDurableEventType[] = [
  "plan.created",
  "plan.updated",
  "plan.item_changed",
  "artifact.created",
];

const PLAN_ITEM_STATUSES: readonly PlanItemStatus[] = [
  "pending",
  "in_progress",
  "completed",
  "blocked",
  "failed",
  "cancelled",
];

/** 投影视图内计划项的轻量形态（事件 payload 与快照字段的公共子集）。 */
export interface ProjectedPlanItem {
  item_key: string;
  title: string;
  status: PlanItemStatus;
}

/** 投影视图内 artifact 的轻量形态（artifact.created 事件 payload 不含 rel_path）。 */
export interface ProjectedArtifact {
  id: string;
  kind: string;
  title: string;
  step_id: string | null;
}

export interface RunProjection {
  runId: string;
  plan: { version: number; items: ProjectedPlanItem[] } | null;
  artifacts: ProjectedArtifact[];
  /** 已见最大 sequence（含被忽略的旧/非 durable 事件），用于 SSE 续读。 */
  lastSequence: number;
  /** 是否已与 GET /agent-runs/{id} 快照纠偏（重连）。 */
  reconciled: boolean;
}

export function createRunProjection(runId: string): RunProjection {
  return { runId, plan: null, artifacts: [], lastSequence: 0, reconciled: false };
}

function isPlanItemStatus(value: unknown): value is PlanItemStatus {
  return typeof value === "string" && PLAN_ITEM_STATUSES.includes(value as PlanItemStatus);
}

function toProjectedItems(events: unknown): ProjectedPlanItem[] {
  if (!Array.isArray(events)) return [];
  const items: ProjectedPlanItem[] = [];
  for (const raw of events) {
    if (typeof raw !== "object" || raw === null) continue;
    const item = raw as Record<string, unknown>;
    const itemKey = item.item_key;
    const title = item.title;
    if (typeof itemKey !== "string" || typeof title !== "string") continue;
    items.push({
      item_key: itemKey,
      title,
      status: isPlanItemStatus(item.status) ? item.status : "pending",
    });
  }
  return items;
}

/** 幂等投影一个 durable 事件；旧/重复/异 run/非 durable 事件安全忽略。 */
export function applyDurableEvent(
  projection: RunProjection,
  event: RunDurableEvent,
): RunProjection {
  if (event.run_id !== projection.runId) return projection;
  if (event.sequence <= projection.lastSequence) return projection;
  const next: RunProjection = { ...projection, lastSequence: event.sequence };
  if (!DURABLE_EVENT_TYPES.includes(event.type)) return next;

  switch (event.type) {
    case "plan.created": {
      const version = Number(event.payload.plan_version);
      next.plan = {
        version: Number.isFinite(version) && version >= 1 ? version : 1,
        items: toProjectedItems(event.payload.items),
      };
      return next;
    }
    case "plan.updated": {
      if (next.plan === null) return next;
      const version = Number(event.payload.plan_version);
      next.plan = {
        ...next.plan,
        version: Number.isFinite(version) && version >= 1 ? version : next.plan.version,
      };
      return next;
    }
    case "plan.item_changed": {
      if (next.plan === null) return next;
      const itemKey = event.payload.item_key;
      const status = event.payload.status;
      if (typeof itemKey !== "string" || !isPlanItemStatus(status)) return next;
      next.plan = {
        ...next.plan,
        items: next.plan.items.map((item) =>
          item.item_key === itemKey ? { ...item, status } : item,
        ),
      };
      return next;
    }
    case "artifact.created": {
      const artifactId = event.payload.artifact_id;
      const title = event.payload.title;
      if (typeof artifactId !== "string" || typeof title !== "string") return next;
      const kind = typeof event.payload.kind === "string" ? event.payload.kind : "file";
      const stepId = typeof event.payload.step_id === "string" ? event.payload.step_id : null;
      next.artifacts = [
        ...next.artifacts,
        { id: artifactId, kind, title, step_id: stepId },
      ];
      return next;
    }
  }
}

/**
 * 重连纠偏：快照（GET /agent-runs/{id}）是事实，覆盖投影的 plan/artifacts；
 * lastSequence 取快照侧序列与现有投影的较大者（避免续读回退）。
 */
export function reconcileWithSnapshot(
  projection: RunProjection,
  snapshot: { plan: RunPlanSnapshot | null; artifacts: RunArtifact[] },
  lastSequence?: number,
): RunProjection {
  const next: RunProjection = { ...projection, reconciled: true };
  next.plan =
    snapshot.plan === null
      ? null
      : {
          version: snapshot.plan.version,
          items: snapshot.plan.items.map((item) => ({
            item_key: item.item_key,
            title: item.title,
            status: item.status,
          })),
        };
  next.artifacts = snapshot.artifacts.map((artifact) => ({
    id: artifact.id,
    kind: artifact.kind,
    title: artifact.title,
    step_id: artifact.step_id,
  }));
  if (lastSequence !== undefined) {
    next.lastSequence = Math.max(projection.lastSequence, lastSequence);
  }
  return next;
}

/** 切换 thread/run：丢弃旧投影；旧 run 的迟到事件由 applyDurableEvent 拒绝。 */
export function switchRun(projection: RunProjection, runId: string): RunProjection {
  if (projection.runId === runId) return projection;
  return createRunProjection(runId);
}
