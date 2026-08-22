/**
 * v0.8.0 W2 · Coding run 投影器
 *
 * 以 (run_id, sequence) 幂等消费 durable 事件（计划 §5.3）：
 * - sequence 严格递增，重复/迟到帧按游标跳过；
 * - 按 id 更新 plan/tool/approval 条目，不整页重置；
 * - 快照纠偏：仅接受 last_event_sequence >= 游标的快照（plan/output/status 以快照为准）；
 * - 后端未知事件记录诊断并安全忽略，不推测含义（零容忍 §10）。
 *
 * 本模块为纯函数（无 Vue 依赖）：调用方持 shallowRef，帧后 triggerRef。
 */
import type {
  AgentRunStatus,
  RunArtifactRecord,
  RunPlanItemRecord,
  RunPlanItemStatus,
  RunPlanState,
  RunSnapshot,
  RunStreamFrame,
} from "./runContracts";
import { isTerminalRunStatus } from "./runContracts";

export type ToolActivityState =
  | "requested"
  | "started"
  | "approval_required"
  | "completed"
  | "failed";

export type TranscriptEntry =
  | {
      kind: "run-start";
      key: string;
      sequence: number;
      maxSteps: number;
      maxToolCalls: number;
      maxWallTimeSeconds: number | null;
    }
  | {
      kind: "context";
      key: string;
      sequence: number;
      estimatedTokens: number;
      truncated: boolean;
    }
  | {
      kind: "model-turn";
      key: string;
      sequence: number;
      ordinal: number;
      state: "running" | "completed";
      finishReason: string | null;
      inputTokens: number;
      outputTokens: number;
      latencyMs: number | null;
    }
  | {
      kind: "plan";
      key: string;
      sequence: number;
      version: number;
      itemCount: number;
      note: "created" | "updated";
    }
  | {
      kind: "tool";
      key: string;
      sequence: number;
      toolCallId: string;
      name: string;
      state: ToolActivityState;
      errorType: string | null;
      errorMessage: string | null;
    }
  | {
      kind: "approval";
      key: string;
      sequence: number;
      approvalId: string;
      toolCallId: string;
      toolName: string;
      resolved: boolean;
    }
  | {
      kind: "verification";
      key: string;
      sequence: number;
      verifier: string;
      attempt: number;
      state: "started" | "passed" | "failed";
      message: string | null;
      willRetry: boolean;
    }
  | {
      kind: "artifact";
      key: string;
      sequence: number;
      artifactId: string;
      artifactKind: string;
      title: string;
    }
  | {
      kind: "patch-set";
      key: string;
      sequence: number;
      patchSetId: string;
      state: "previewed" | "applied" | "rolled_back" | "failed" | "unknown";
      fileCount: number | null;
      verified: boolean | null;
      errorCode: string | null;
      reason: string | null;
    }
  | {
      kind: "terminal";
      key: string;
      sequence: number;
      status: AgentRunStatus;
      errorCode: string | null;
      output: string | null;
    };

export interface RunUsage {
  toolCallCount: number;
  inputTokens: number;
  outputTokens: number;
  costUsd: number | null;
}

export interface RunProjection {
  runId: string;
  status: AgentRunStatus;
  /** durable 游标：已应用的最大 sequence */
  lastSequence: number;
  plan: RunPlanState | null;
  entries: TranscriptEntry[];
  /** 本次 run 的用户消息（创建时提交，非 durable 事件） */
  userMessage: string | null;
  output: string | null;
  error: { code: string | null; message: string | null } | null;
  usage: RunUsage;
  startedAt: string | null;
  completedAt: string | null;
  /** 后端新增事件类型的诊断清单（安全忽略，不推测含义） */
  unknownEventTypes: string[];
}

export function createRunProjection(runId: string, userMessage: string | null = null): RunProjection {
  return {
    runId,
    status: "created",
    lastSequence: 0,
    plan: null,
    entries: [],
    userMessage,
    output: null,
    error: null,
    usage: { toolCallCount: 0, inputTokens: 0, outputTokens: 0, costUsd: null },
    startedAt: null,
    completedAt: null,
    unknownEventTypes: [],
  };
}

/**
 * 写时复制克隆：浅层复制可变集合（entries/plan.items/usage/诊断），
 * 供 shallowRef 持有方在 mutate 后产生新引用，保证 computed 链失效。
 */
export function cloneRunProjection(source: RunProjection): RunProjection {
  return {
    ...source,
    entries: [...source.entries],
    plan: source.plan ? { ...source.plan, items: [...source.plan.items] } : null,
    error: source.error ? { ...source.error } : null,
    usage: { ...source.usage },
    unknownEventTypes: [...source.unknownEventTypes],
  };
}

function str(payload: Record<string, unknown>, key: string, fallback = ""): string {
  const value = payload[key];
  return typeof value === "string" ? value : fallback;
}

function num(payload: Record<string, unknown>, key: string, fallback = 0): number {
  const value = payload[key];
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function nullableNum(payload: Record<string, unknown>, key: string): number | null {
  const value = payload[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function upsertEntry(projection: RunProjection, entry: TranscriptEntry, byKey = true): void {
  if (byKey) {
    const index = projection.entries.findIndex((item) => item.key === entry.key);
    if (index >= 0) {
      projection.entries[index] = entry;
      return;
    }
  }
  projection.entries.push(entry);
}

function upsertToolEntry(
  projection: RunProjection,
  frame: RunStreamFrame,
  patch: Partial<Extract<TranscriptEntry, { kind: "tool" }>>
): void {
  const toolCallId = str(frame.payload, "tool_call_id");
  const key = `tool:${toolCallId}`;
  const existing = projection.entries.find(
    (item): item is Extract<TranscriptEntry, { kind: "tool" }> =>
      item.kind === "tool" && item.key === key
  );
  if (existing) {
    Object.assign(existing, patch, { sequence: frame.sequence });
    // 就地更新保持条目稳定（不整页重置）；Vue 侧经 triggerRef 通知
    const index = projection.entries.findIndex((item) => item.key === key);
    projection.entries[index] = { ...existing };
    return;
  }
  const entry: TranscriptEntry = {
    kind: "tool",
    key,
    sequence: frame.sequence,
    toolCallId,
    name: str(frame.payload, "name"),
    state: "requested",
    errorType: null,
    errorMessage: null,
    ...patch,
  };
  projection.entries.push(entry);
}

function normalizePlanItems(raw: unknown): RunPlanItemRecord[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
    .map((item, index) => ({
      item_key: typeof item.item_key === "string" ? item.item_key : `item-${index}`,
      ordinal: typeof item.ordinal === "number" ? item.ordinal : index + 1,
      title: typeof item.title === "string" ? item.title : String(item.item_key ?? `步骤 ${index + 1}`),
      detail: typeof item.detail === "string" ? item.detail : null,
      status: (typeof item.status === "string" ? item.status : "pending") as RunPlanItemStatus,
    }))
    .sort((a, b) => a.ordinal - b.ordinal);
}

/** 终态 durable 事件的 payload（runtime _terminal_payload） */
const TERMINAL_EVENT_STATUS: Record<string, AgentRunStatus> = {
  "run.completed": "completed",
  "run.failed": "failed",
  "run.cancelled": "cancelled",
  "run.timed_out": "timed_out",
  "run.limit_exceeded": "limit_exceeded",
};

export function applyRunFrame(projection: RunProjection, frame: RunStreamFrame): RunProjection {
  if (frame.sequence <= projection.lastSequence) {
    return projection; // 幂等：重复/迟到帧跳过
  }
  projection.lastSequence = frame.sequence;
  const payload = frame.payload ?? {};

  switch (frame.type) {
    case "run.started": {
      projection.status = "running";
      projection.startedAt = null; // 时间戳以快照为准（SSE 帧不含）
      upsertEntry(projection, {
        kind: "run-start",
        key: "run-start",
        sequence: frame.sequence,
        maxSteps: num(payload, "max_steps"),
        maxToolCalls: num(payload, "max_tool_calls"),
        maxWallTimeSeconds: nullableNum(payload, "max_wall_time_seconds"),
      });
      break;
    }
    case "context.prepared": {
      upsertEntry(projection, {
        kind: "context",
        key: "context",
        sequence: frame.sequence,
        estimatedTokens: num(payload, "estimated_tokens", 0),
        truncated: payload.truncated === true,
      });
      break;
    }
    case "model.started": {
      const ordinal = num(payload, "ordinal", 1);
      upsertEntry(projection, {
        kind: "model-turn",
        key: `model:${ordinal}`,
        sequence: frame.sequence,
        ordinal,
        state: "running",
        finishReason: null,
        inputTokens: 0,
        outputTokens: 0,
        latencyMs: null,
      });
      break;
    }
    case "model.completed": {
      const ordinal = findLastModelOrdinal(projection);
      const key = `model:${ordinal}`;
      const existing = projection.entries.find(
        (item): item is Extract<TranscriptEntry, { kind: "model-turn" }> =>
          item.kind === "model-turn" && item.key === key
      );
      if (existing) {
        existing.state = "completed";
        existing.finishReason = str(payload, "finish_reason") || null;
        existing.inputTokens = num(payload, "input_tokens", existing.inputTokens);
        existing.outputTokens = num(payload, "output_tokens", existing.outputTokens);
        existing.latencyMs = nullableNum(payload, "latency_ms") ?? existing.latencyMs;
        const index = projection.entries.findIndex((item) => item.key === key);
        projection.entries[index] = { ...existing };
      }
      projection.usage.inputTokens += num(payload, "input_tokens");
      projection.usage.outputTokens += num(payload, "output_tokens");
      projection.usage.costUsd = nullableNum(payload, "cost_usd") ?? projection.usage.costUsd;
      break;
    }
    case "output.validation_started":
    case "output.validation_passed":
    case "output.validation_failed": {
      const verifier = str(payload, "verifier");
      const attempt = num(payload, "attempt", 1);
      const state =
        frame.type === "output.validation_started"
          ? ("started" as const)
          : frame.type === "output.validation_passed"
            ? ("passed" as const)
            : ("failed" as const);
      upsertEntry(
        projection,
        {
          kind: "verification",
          key: `verify:${verifier}:${attempt}`,
          sequence: frame.sequence,
          verifier,
          attempt,
          state,
          message: str(payload, "message") || null,
          willRetry: payload.will_retry === true,
        },
        true
      );
      break;
    }
    case "tool.requested": {
      upsertToolEntry(projection, frame, { state: "requested" });
      break;
    }
    case "tool.started": {
      upsertToolEntry(projection, frame, { state: "started" });
      break;
    }
    case "tool.approval_required": {
      projection.status = "waiting_approval";
      upsertToolEntry(projection, frame, { state: "approval_required" });
      upsertEntry(projection, {
        kind: "approval",
        key: `approval:${str(payload, "approval_id")}`,
        sequence: frame.sequence,
        approvalId: str(payload, "approval_id"),
        toolCallId: str(payload, "tool_call_id"),
        toolName: str(payload, "name"),
        resolved: false,
      });
      break;
    }
    case "tool.approval_resolved": {
      const approvalKey = `approval:${str(payload, "approval_id")}`;
      const approval = projection.entries.find(
        (item): item is Extract<TranscriptEntry, { kind: "approval" }> =>
          item.kind === "approval" && item.key === approvalKey
      );
      if (approval) {
        approval.resolved = true;
        const index = projection.entries.findIndex((item) => item.key === approvalKey);
        projection.entries[index] = { ...approval };
      }
      // 批准后工具继续执行（resume 首个工具不再发 tool.started）
      upsertToolEntry(projection, frame, { state: "started" });
      if (projection.status === "waiting_approval") projection.status = "running";
      break;
    }
    case "tool.completed": {
      projection.usage.toolCallCount = Math.max(projection.usage.toolCallCount, num(payload, "ordinal", 0));
      upsertToolEntry(projection, frame, { state: "completed" });
      break;
    }
    case "tool.failed": {
      upsertToolEntry(projection, frame, {
        state: "failed",
        errorType: str(payload, "error_type") || null,
        errorMessage: str(payload, "error") || null,
      });
      break;
    }
    case "plan.created": {
      const version = num(payload, "plan_version", 1);
      projection.plan = { version, items: normalizePlanItems(payload.items) };
      upsertEntry(projection, {
        kind: "plan",
        key: `plan:${version}`,
        sequence: frame.sequence,
        version,
        itemCount: projection.plan.items.length,
        note: "created",
      });
      break;
    }
    case "plan.updated": {
      const version = num(payload, "plan_version");
      projection.plan = projection.plan
        ? { ...projection.plan, version }
        : { version, items: [] };
      upsertEntry(projection, {
        kind: "plan",
        key: `plan:${version}`,
        sequence: frame.sequence,
        version,
        itemCount: projection.plan.items.length,
        note: "updated",
      });
      break;
    }
    case "plan.item_changed": {
      if (projection.plan) {
        const itemKey = str(payload, "item_key");
        const status = str(payload, "status") as RunPlanItemStatus;
        const index = projection.plan.items.findIndex((item) => item.item_key === itemKey);
        if (index >= 0) {
          const items = [...projection.plan.items];
          items[index] = { ...items[index], status };
          projection.plan = { version: projection.plan.version, items };
        } else {
          // 未见 plan.created 的增量（理论不发生，快照纠偏兜底）：以 item_key 占位
          projection.plan = {
            version: projection.plan.version,
            items: [
              ...projection.plan.items,
              { item_key: itemKey, ordinal: projection.plan.items.length + 1, title: itemKey, detail: null, status },
            ],
          };
        }
      }
      break;
    }
    case "artifact.created": {
      upsertEntry(projection, {
        kind: "artifact",
        key: `artifact:${str(payload, "artifact_id")}`,
        sequence: frame.sequence,
        artifactId: str(payload, "artifact_id"),
        artifactKind: str(payload, "kind"),
        title: str(payload, "title"),
      });
      break;
    }
    case "patch_set.preview_created": {
      upsertEntry(projection, {
        kind: "patch-set",
        key: `patchset:${str(payload, "patch_set_id")}`,
        sequence: frame.sequence,
        patchSetId: str(payload, "patch_set_id"),
        state: "previewed",
        fileCount: nullableNum(payload, "file_count"),
        verified: null,
        errorCode: null,
        reason: null,
      });
      break;
    }
    case "patch_set.applied": {
      upsertEntry(projection, {
        kind: "patch-set",
        key: `patchset:${str(payload, "patch_set_id")}`,
        sequence: frame.sequence,
        patchSetId: str(payload, "patch_set_id"),
        state: "applied",
        fileCount: null,
        verified: payload.verified === true,
        errorCode: null,
        reason: null,
      });
      break;
    }
    case "patch_set.rolled_back":
    case "patch_set.unknown": {
      upsertEntry(projection, {
        kind: "patch-set",
        key: `patchset:${str(payload, "patch_set_id")}`,
        sequence: frame.sequence,
        patchSetId: str(payload, "patch_set_id"),
        state: frame.type === "patch_set.rolled_back" ? "rolled_back" : "unknown",
        fileCount: null,
        verified: null,
        errorCode: null,
        reason: str(payload, "reason") || null,
      });
      break;
    }
    case "patch_set.failed": {
      upsertEntry(projection, {
        kind: "patch-set",
        key: `patchset:${str(payload, "patch_set_id")}`,
        sequence: frame.sequence,
        patchSetId: str(payload, "patch_set_id"),
        state: "failed",
        fileCount: null,
        verified: null,
        errorCode: str(payload, "error_code") || null,
        reason: str(payload, "error_message") || null,
      });
      break;
    }
    case "run.completed":
    case "run.failed":
    case "run.cancelled":
    case "run.timed_out":
    case "run.limit_exceeded": {
      const status = TERMINAL_EVENT_STATUS[frame.type];
      applyTerminal(projection, status, frame.sequence, {
        output: typeof payload.output === "string" ? payload.output : null,
        errorCode: str(payload, "error_code") || null,
      });
      applyTerminalUsage(projection, payload);
      break;
    }
    case "run.terminal": {
      // 流层合成帧（不落库）：流将关闭；状态若未收敛以帧内状态补齐
      const status = str(payload, "status") as AgentRunStatus;
      if (isTerminalRunStatus(status) && !isTerminalRunStatus(projection.status)) {
        applyTerminal(projection, status, frame.sequence, { output: null, errorCode: null });
      }
      break;
    }
    case "chat.output_persisted":
      // 聊天路径持久化标记，coding 任务页不呈现
      break;
    default: {
      // 后端新增事件：记录诊断并安全忽略（不推测含义）
      if (!projection.unknownEventTypes.includes(frame.type)) {
        projection.unknownEventTypes.push(frame.type);
      }
      break;
    }
  }
  return projection;
}

function applyTerminal(
  projection: RunProjection,
  status: AgentRunStatus,
  sequence: number,
  facts: { output: string | null; errorCode: string | null }
): void {
  projection.status = status;
  projection.completedAt = null; // 时间戳以快照为准
  if (facts.output !== null) projection.output = facts.output;
  if (facts.errorCode) {
    projection.error = { code: facts.errorCode, message: projection.error?.message ?? null };
  }
  upsertEntry(projection, {
    kind: "terminal",
    key: "terminal",
    sequence,
    status,
    errorCode: facts.errorCode,
    output: facts.output,
  });
}

/** 终态 payload 的用量/工具计数是 durable 事实（_terminal_payload） */
function applyTerminalUsage(
  projection: RunProjection,
  payload: Record<string, unknown>
): void {
  const toolCallCount = nullableNum(payload, "tool_call_count");
  const inputTokens = nullableNum(payload, "input_tokens");
  const outputTokens = nullableNum(payload, "output_tokens");
  const costUsd = nullableNum(payload, "cost_usd");
  if (toolCallCount !== null) projection.usage.toolCallCount = toolCallCount;
  if (inputTokens !== null) projection.usage.inputTokens = inputTokens;
  if (outputTokens !== null) projection.usage.outputTokens = outputTokens;
  if (costUsd !== null) projection.usage.costUsd = costUsd;
}

function findLastModelOrdinal(projection: RunProjection): number {
  let ordinal = 0;
  for (const entry of projection.entries) {
    if (entry.kind === "model-turn" && entry.ordinal > ordinal) ordinal = entry.ordinal;
  }
  return Math.max(ordinal, 1);
}

/**
 * 快照纠偏（重连/水合）：仅接受 last_event_sequence >= 游标 的快照；
 * plan/output/status/usage 以快照 durable 事实为准，事件游标不前跳
 * （缺口由 events 重放补齐后续流续读）。
 */
export function reconcileRunWithSnapshot(
  projection: RunProjection,
  snapshot: RunSnapshot
): RunProjection {
  if (snapshot.last_event_sequence < projection.lastSequence) {
    return projection; // 旧快照：不回退已应用事实
  }
  projection.status = snapshot.status;
  projection.output = snapshot.output ?? projection.output;
  projection.error = snapshot.error_code
    ? { code: snapshot.error_code, message: snapshot.error_message ?? null }
    : projection.error;
  projection.usage = {
    toolCallCount: snapshot.tool_call_count,
    inputTokens: snapshot.input_tokens,
    outputTokens: snapshot.output_tokens,
    costUsd: snapshot.cost_usd,
  };
  projection.startedAt = snapshot.started_at;
  projection.completedAt = snapshot.completed_at;
  if (snapshot.plan) {
    projection.plan = {
      version: snapshot.plan.version,
      items: normalizePlanItems(snapshot.plan.items),
    };
  } else if (projection.plan === null) {
    // 无计划与快照一致；已有计划保留（快照 null 可能是列未投影的旧后端）
  }
  for (const artifact of snapshot.artifacts ?? []) {
    mergeArtifact(projection, artifact);
  }
  if (isTerminalRunStatus(snapshot.status)) {
    upsertEntry(projection, {
      kind: "terminal",
      key: "terminal",
      sequence: Math.max(projection.lastSequence, snapshot.last_event_sequence),
      status: snapshot.status,
      errorCode: snapshot.error_code,
      output: snapshot.output,
    });
  }
  return projection;
}

function mergeArtifact(projection: RunProjection, artifact: RunArtifactRecord): void {
  const key = `artifact:${artifact.id}`;
  const exists = projection.entries.some((item) => item.key === key);
  if (exists) return; // 事件条目已在，避免重复
  projection.entries.push({
    kind: "artifact",
    key,
    sequence: projection.lastSequence,
    artifactId: artifact.id,
    artifactKind: artifact.kind,
    title: artifact.title,
  });
}
