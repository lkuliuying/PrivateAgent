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
  PendingPlanInput,
  RunArtifactRecord,
  RunPlanItemRecord,
  RunPlanItemStatus,
  RunPlanState,
  RunSnapshot,
  RunStreamFrame,
} from "./runContracts";
import { isTerminalRunStatus } from "./runContracts";
import type { Requirement, RunOutcome } from "./generated/codingContracts";
import { parseRequirements, parseRunOutcome, unknownRunOutcome } from "./runOutcome";

export type ToolActivityState =
  | "requested"
  | "started"
  | "approval_required"
  | "completed"
  | "failed";

export interface PublicModelOutput {
  attemptId: string;
  messageId: string | null;
  phase: "commentary" | "final_answer" | null;
  generation: number | null;
  text: string;
  state: "streaming" | "finished" | "interrupted";
  hasToolCalls: boolean | null;
  truncated: boolean;
}

export type TranscriptEntry =
  | {
      kind: "context-compaction";
      key: string;
      sequence: number;
      state: "started" | "completed" | "failed";
      message: string | null;
    }
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
      estimatedTokens: number | null;
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
      usageComplete?: boolean;
      latencyMs: number | null;
    }
  | {
      kind: "model-output";
      key: string;
      sequence: number;
    } & PublicModelOutput
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
      state: "started" | "passed" | "failed" | "unverified";
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
      relPath: string | null;
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
      kind: "decision-summary";
      key: string;
      sequence: number;
      /** 公开决策摘要（只含结构化公开事实，不含隐藏推理，H0 §8） */
      goal: string;
      method: string | null;
      nextSteps: string[];
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
  projectId?: number | null;
  workspaceId?: number | null;
  sessionId?: number | null;
  collaborationMode?: "default" | "plan";
  pendingInput?: PendingPlanInput | null;
  stateVersion?: number;
  modelOutput?: PublicModelOutput | null;
  runOutcome: RunOutcome;
  completionRequirements: Requirement[];
  verifying: boolean;
  runId: string;
  status: AgentRunStatus;
  /** durable 游标：已应用的最大 sequence */
  lastSequence: number;
  plan: RunPlanState | null;
  entries: TranscriptEntry[];
  /** 本次 run 的用户消息（创建时提交，非 durable 事件） */
  userMessage: string | null;
  output: string | null;
  /** 缺省代表旧事件；null 表示最终正文经过验收替换，不能按文本隐藏候选。 */
  finalOutputAttemptId?: string | null;
  structuredOutput?: Record<string, unknown> | null;
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
    runOutcome: unknownRunOutcome(runId),
    completionRequirements: [],
    verifying: false,
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
    modelOutput: source.modelOutput ? { ...source.modelOutput } : null,
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

function outputPhase(value: unknown): PublicModelOutput["phase"] {
  return value === "commentary" || value === "final_answer" ? value : null;
}

function structuredOutput(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
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
      ...(Array.isArray(item.requirement_ids) ? { requirement_ids: item.requirement_ids.filter((id): id is string => typeof id === "string") } : {}),
      ...(Array.isArray(item.evidence_calls) ? { evidence_calls: item.evidence_calls.filter((id): id is string => typeof id === "string") } : {}),
      ...(Array.isArray(item.supersedes) ? { supersedes: item.supersedes.filter((id): id is string => typeof id === "string") } : {}),
    }))
    .sort((a, b) => a.ordinal - b.ordinal);
}

function parsePendingInput(raw: unknown): PendingPlanInput | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  if (typeof value.input_id !== "string" || !Array.isArray(value.questions)
      || value.questions.length < 1 || value.questions.length > 3) return null;
  const questions: PendingPlanInput["questions"] = [];
  for (const rawQuestion of value.questions) {
    if (!rawQuestion || typeof rawQuestion !== "object") return null;
    const item = rawQuestion as Record<string, unknown>;
    if (typeof item.id !== "string" || typeof item.question !== "string" || !Array.isArray(item.options)) return null;
    const options: PendingPlanInput["questions"][number]["options"] = [];
    for (const rawOption of item.options) {
      if (!rawOption || typeof rawOption !== "object") return null;
      const option = rawOption as Record<string, unknown>;
      if (typeof option.label !== "string" || typeof option.description !== "string") return null;
      options.push({ label: option.label, description: option.description });
    }
    questions.push({ id: item.id, question: item.question, options });
  }
  return { input_id: value.input_id, questions, goal_version: num(value, "goal_version", 1),
    generation: num(value, "generation"), created_at: str(value, "created_at") };
}

function planMetadata(raw: Pick<RunPlanState, "goal_version" | "needs_review" | "explanation">): Partial<RunPlanState> {
  return {
    ...(typeof raw.goal_version === "number" ? { goal_version: raw.goal_version } : {}),
    ...(typeof raw.needs_review === "boolean" ? { needs_review: raw.needs_review } : {}),
    ...(typeof raw.explanation === "string" ? { explanation: raw.explanation } : {}),
  };
}

/** 终态 durable 事件的 payload（runtime _terminal_payload） */
const TERMINAL_EVENT_STATUS: Record<string, AgentRunStatus> = {
  "run.interrupted": "interrupted",
  "run.completed": "completed",
  "run.failed": "failed",
  "run.cancelled": "cancelled",
  "run.timed_out": "timed_out",
  "run.limit_exceeded": "limit_exceeded",
};

export function applyRunFrame(projection: RunProjection, frame: RunStreamFrame): RunProjection {
  if (frame.type === "run.terminal") return projection;
  if (frame.sequence <= projection.lastSequence) {
    return projection; // 幂等：重复/迟到帧跳过
  }
  projection.lastSequence = frame.sequence;
  const payload = frame.payload ?? {};
  if (typeof payload.state_version === "number") projection.stateVersion = payload.state_version;

  switch (frame.type) {
    case "input.requested":
      if (isTerminalRunStatus(projection.status)) break;
      projection.pendingInput = parsePendingInput(payload.pending_input);
      projection.status = "waiting_input";
      break;
    case "input.resolved":
    case "input.invalidated":
      if (projection.pendingInput?.input_id === payload.input_id) {
        projection.pendingInput = null;
        if (projection.status === "waiting_input") projection.status = "running";
      }
      break;
    case "run.paused":
      projection.status = "paused";
      break;
    case "run.queued":
      projection.status = "queued";
      break;
    case "run.resumed":
      projection.status = "running";
      break;
    case "model.output.delta": {
      const attemptId = str(payload, "attempt_id");
      const delta = str(payload, "delta");
      if (!attemptId || !delta) break;
      const messageId = str(payload, "message_id") || null;
      const key = messageId === null ? `model-output:${attemptId}` : `model-output:${JSON.stringify([attemptId, messageId])}`;
      const previous = projection.entries.find((entry): entry is Extract<TranscriptEntry, { kind: "model-output" }> =>
        entry.kind === "model-output" && entry.key === key);
      // 请求级终结覆盖所有消息；迟到的新消息也不能重新打开已经结束的请求。
      if (projection.entries.some(entry => entry.kind === "model-output" && entry.attemptId === attemptId && entry.state !== "streaming")) break;
      const text = (previous?.text ?? "") + delta;
      const output: PublicModelOutput = {
        attemptId, messageId,
        phase: outputPhase(payload.phase) ?? previous?.phase ?? null,
        generation: nullableNum(payload, "generation") ?? previous?.generation ?? null,
        text: text.slice(-64000), state: "streaming", hasToolCalls: null,
        truncated: previous?.truncated === true || payload.truncated === true || text.length > 64000,
      };
      upsertEntry(projection, { kind: "model-output", key, sequence: previous?.sequence ?? frame.sequence, ...output });
      projection.modelOutput = output;
      break;
    }
    case "model.output.finished":
    case "model.output.interrupted": {
      const attemptId = str(payload, "attempt_id");
      const entries = projection.entries.filter((item): item is Extract<TranscriptEntry, { kind: "model-output" }> =>
        item.kind === "model-output" && item.attemptId === attemptId);
      // 空正文只保留原事件，不生成虚假的进展段落。
      const messages = Array.isArray(payload.messages) ? payload.messages : [];
      for (const entry of entries) {
        if (entry.state !== "streaming") continue;
        const metadata = messages.find((item): item is Record<string, unknown> =>
          item !== null && typeof item === "object" && item.message_id === entry.messageId);
        const output: PublicModelOutput = {
          attemptId, messageId: entry.messageId, generation: entry.generation, text: entry.text,
          phase: outputPhase(metadata?.phase) ?? entry.phase ?? (entries.length === 1 ? outputPhase(payload.phase) : null),
          state: frame.type === "model.output.finished" ? "finished" : "interrupted",
          hasToolCalls: typeof payload.has_tool_calls === "boolean" ? payload.has_tool_calls : null,
          truncated: entry.truncated || metadata?.truncated === true,
        };
        upsertEntry(projection, { ...entry, ...output });
        if (projection.modelOutput?.attemptId === attemptId && projection.modelOutput.messageId === entry.messageId) projection.modelOutput = output;
      }
      break;
    }
    case "execution.output":
    case "execution.terminal":
      break;
    case "run.started": {
      projection.collaborationMode = payload.collaboration_mode === "plan" ? "plan" : "default";
      projection.completionRequirements = parseRequirements(payload.completion_requirements);
      projection.status = "running";
      // 事件不携带时间戳，保留快照已确认的开始时间。
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
    case "context.compaction_started":
    case "context.compaction_completed":
    case "context.compaction_failed": {
      const key = `compaction:${str(payload, "checkpoint_id") || frame.sequence}`;
      const previous = projection.entries.find(entry => entry.key === key);
      upsertEntry(projection, {
        kind: "context-compaction", key, sequence: previous?.sequence ?? frame.sequence,
        state: frame.type === "context.compaction_started" ? "started"
          : frame.type === "context.compaction_completed" ? "completed" : "failed",
        message: str(payload, "error") || null,
      });
      break;
    }
    case "context.prepared": {
      const estimate = "estimated_input_tokens" in payload ? payload.estimated_input_tokens : payload.estimated_tokens;
      upsertEntry(projection, {
        kind: "context",
        key: "context",
        sequence: frame.sequence,
        estimatedTokens: typeof estimate === "number" && Number.isSafeInteger(estimate) && estimate >= 0 ? estimate : null,
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
        existing.usageComplete = payload.usage_complete !== false;
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
    case "decision.summary": {
      // v0.9.0 H0 §8：逐轮公开决策摘要（目标/方法/后续步骤）；
      // payload 键集后端冻结，缺失/无 goal 时不投影（不伪造）。
      const goal = str(payload, "goal");
      if (!goal) break;
      const nextStepsRaw = payload.next_steps;
      const nextSteps = Array.isArray(nextStepsRaw)
        ? nextStepsRaw.filter((item): item is string => typeof item === "string").slice(0, 12)
        : [];
      upsertEntry(projection, {
        kind: "decision-summary",
        key: `decision:${frame.sequence}`,
        sequence: frame.sequence,
        goal,
        method: str(payload, "method") || null,
        nextSteps,
      });
      break;
    }
    case "output.validation_started":
    case "output.validation_passed":
    case "output.validation_failed": {
      projection.verifying = frame.type === "output.validation_started";
      const verifier = str(payload, "verifier");
      const attempt = num(payload, "attempt", 1);
      const state =
        frame.type === "output.validation_started"
          ? ("started" as const)
          : frame.type === "output.validation_passed"
            ? (verifier === "local_completion" && payload.code === "completion_limited" ? "unverified" as const : "passed" as const)
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
      if (projection.plan && version < projection.plan.version) break;
      projection.plan = { ...planMetadata(payload), version, items: normalizePlanItems(payload.items) };
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
      if (projection.plan && version < projection.plan.version) break;
      projection.plan = {
        ...projection.plan, ...planMetadata(payload), version,
        items: Array.isArray(payload.items) ? normalizePlanItems(payload.items) : projection.plan?.items ?? [],
      };
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
        if (num(payload, "plan_version", projection.plan.version) < projection.plan.version) break;
        const itemKey = str(payload, "item_key");
        const status = str(payload, "status") as RunPlanItemStatus;
        const index = projection.plan.items.findIndex((item) => item.item_key === itemKey);
        if (index >= 0) {
          const items = [...projection.plan.items];
          items[index] = { ...items[index], status };
          projection.plan = { ...projection.plan, items };
        } else {
          // 未见 plan.created 的增量（理论不发生，快照纠偏兜底）：以 item_key 占位
          projection.plan = {
            ...projection.plan,
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
      const key = `artifact:${str(payload, "artifact_id")}`;
      const existing = projection.entries.find(entry => entry.kind === "artifact" && entry.key === key);
      upsertEntry(projection, {
        kind: "artifact",
        key,
        sequence: frame.sequence,
        artifactId: str(payload, "artifact_id"),
        artifactKind: str(payload, "kind"),
        title: str(payload, "title"),
        relPath: str(payload, "rel_path") || (existing?.kind === "artifact" ? existing.relPath : null),
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
      const patchSetId = str(payload, "patch_set_id");
      const previewEntry = projection.entries.find(
        (entry): entry is Extract<TranscriptEntry, { kind: "patch-set" }> =>
          entry.kind === "patch-set" && entry.patchSetId === patchSetId
      );
      upsertEntry(projection, {
        kind: "patch-set",
        key: `patchset:${patchSetId}`,
        sequence: frame.sequence,
        patchSetId,
        state: "applied",
        fileCount: previewEntry?.fileCount ?? null,
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
    case "run.interrupted":
    case "run.failed":
    case "run.cancelled":
    case "run.timed_out":
    case "run.limit_exceeded": {
      const status = TERMINAL_EVENT_STATUS[frame.type];
      projection.runOutcome = parseRunOutcome(payload.run_outcome, projection.runId);
      projection.verifying = false;
      if ("final_output_attempt_id" in payload) projection.finalOutputAttemptId = str(payload, "final_output_attempt_id") || null;
      if ("structured_output" in payload) projection.structuredOutput = structuredOutput(payload.structured_output);
      applyTerminal(projection, status, frame.sequence, {
        output: typeof payload.output === "string" ? payload.output : null,
        errorCode: str(payload, "error_code") || null,
        errorMessage: str(payload, "error") || null,
      });
      applyTerminalUsage(projection, payload);
      break;
    }
    case "run.terminal": {
      // 流层合成帧（不落库）：流将关闭；状态若未收敛以帧内状态补齐
      const status = str(payload, "status") as AgentRunStatus;
      if (isTerminalRunStatus(status) && !isTerminalRunStatus(projection.status)) {
        applyTerminal(projection, status, frame.sequence, {
          output: null,
          errorCode: null,
          errorMessage: null,
        });
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
  facts: {
    output: string | null;
    errorCode: string | null;
    errorMessage: string | null;
  }
): void {
  projection.status = status;
  projection.pendingInput = null;
  // 重放终态时保留快照时间；新运行由独立投影初始化。
  if (facts.output !== null) projection.output = facts.output;
  if (facts.errorCode || facts.errorMessage) {
    projection.error = {
      code: facts.errorCode ?? projection.error?.code ?? "run_failed",
      message: facts.errorMessage ?? projection.error?.message ?? null,
    };
  }
  upsertEntry(projection, {
    kind: "terminal",
    key: "terminal",
    sequence,
    status,
    // 流层合成的 run.terminal 帧不带错误事实：不得把已落库的错误码洗成空。
    errorCode: facts.errorCode ?? projection.error?.code ?? null,
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
  projection.projectId = snapshot.project_id;
  projection.workspaceId = snapshot.workspace_id;
  projection.sessionId = snapshot.session_id;
  projection.collaborationMode = snapshot.collaboration_mode === "plan" ? "plan" : "default";
  projection.pendingInput = isTerminalRunStatus(snapshot.status) ? null : parsePendingInput(snapshot.pending_input);
  projection.stateVersion = snapshot.state_version;
  projection.runOutcome = parseRunOutcome(snapshot.run_outcome, projection.runId);
  projection.completionRequirements = parseRequirements(snapshot.completion_requirements);
  projection.verifying = snapshot.verification_state === "started" && !isTerminalRunStatus(snapshot.status);
  projection.output = snapshot.output ?? projection.output;
  if ("final_output_attempt_id" in snapshot) projection.finalOutputAttemptId = snapshot.final_output_attempt_id ?? null;
  if ("structured_output" in snapshot) projection.structuredOutput = structuredOutput(snapshot.structured_output);
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
  if (snapshot.plan && snapshot.plan.version >= (projection.plan?.version ?? 0)) {
    projection.plan = {
      ...planMetadata(snapshot.plan),
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
      // 快照未携带错误码时不得把已投影的错误事实洗成空（终态结算/纠偏同理）。
      errorCode: snapshot.error_code ?? projection.error?.code ?? null,
      output: snapshot.output,
    });
  }
  return projection;
}

function mergeArtifact(projection: RunProjection, artifact: RunArtifactRecord): void {
  const key = `artifact:${artifact.id}`;
  const existing = projection.entries.find((item) => item.key === key);
  if (existing?.kind === "artifact") {
    // 旧事件可能没有文件定位信息，快照只补齐已确认的路径，不重复生成产物卡。
    upsertEntry(projection, { ...existing, relPath: artifact.rel_path ?? existing.relPath ?? null });
    return;
  }
  projection.entries.push({
    kind: "artifact",
    key,
    sequence: projection.lastSequence,
    artifactId: artifact.id,
    artifactKind: artifact.kind,
    title: artifact.title,
    relPath: artifact.rel_path ?? null,
  });
}
