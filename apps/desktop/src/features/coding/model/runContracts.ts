/**
 * v0.8.0 W2 · Coding run 契约（wire 字段名与后端 1:1）
 *
 * 事实源：src/personal_assistant/agents/contracts.py（AgentEventType/payload）、
 * routes_agent_runs.py（AgentRunResponse/AgentToolApprovalResponse/AgentRunEventPage、
 * SSE 帧格式）、core/run_plan.py（plan 快照 items）、
 * tests/test_v070_e5_gate.py（L1 真实事件序列）。
 *
 * 红线：payload 中不携带的敏感数据（审批 arguments 原文、工具完整输出、
 * 隐藏推理）本契约一律不声明；工具结果走 executions API（W3）。
 */

export type AgentRunStatus =
  | "created"
  | "running"
  | "waiting_approval"
  | "completed"
  | "failed"
  | "cancelled"
  | "timed_out"
  | "limit_exceeded";

export const TERMINAL_RUN_STATUSES: readonly AgentRunStatus[] = [
  "completed",
  "failed",
  "cancelled",
  "timed_out",
  "limit_exceeded",
];

export function isTerminalRunStatus(status: AgentRunStatus): boolean {
  return TERMINAL_RUN_STATUSES.includes(status);
}

/** durable 事件全集（contracts.py AgentEventType）+ SSE 合成 run.terminal */
export type RunStreamEventType =
  | "run.started"
  | "context.prepared"
  | "model.started"
  | "model.completed"
  | "output.validation_started"
  | "output.validation_passed"
  | "output.validation_failed"
  | "tool.requested"
  | "tool.started"
  | "tool.approval_required"
  | "tool.approval_resolved"
  | "tool.completed"
  | "tool.failed"
  | "run.completed"
  | "run.failed"
  | "run.cancelled"
  | "run.timed_out"
  | "run.limit_exceeded"
  | "chat.output_persisted"
  | "plan.created"
  | "plan.updated"
  | "plan.item_changed"
  | "artifact.created"
  | "patch_set.preview_created"
  | "patch_set.applied"
  | "patch_set.rolled_back"
  | "patch_set.failed"
  | "patch_set.unknown"
  // v0.9.0 H0 §7.2/§8（additive）：公开决策摘要、上下文压缩与权限降级；
  // decision.summary 只含结构化公开事实，不含隐藏 chain-of-thought。
  | "decision.summary"
  | "context.compaction_started"
  | "context.compaction_completed"
  | "context.compaction_failed"
  | "permission.downgraded"
  | "run.terminal";

export interface RunStreamFrame {
  sequence: number;
  type: RunStreamEventType | string;
  payload: Record<string, unknown>;
}

/** GET /agent-runs/{id}/events 分页项（含 step_id/created_at） */
export interface RunEventRecord {
  sequence: number;
  type: string;
  step_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface RunEventPage {
  items: RunEventRecord[];
  last_sequence: number;
}

export type RunPlanItemStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "blocked"
  | "failed"
  | "cancelled";

export interface RunPlanItemRecord {
  item_key: string;
  ordinal: number;
  title: string;
  detail: string | null;
  status: RunPlanItemStatus;
}

export interface RunPlanState {
  version: number;
  items: RunPlanItemRecord[];
}

export interface RunArtifactRecord {
  id: string;
  kind: string;
  title: string;
  rel_path: string | null;
}

export interface RunStepRecord {
  id: string;
  ordinal: number;
  kind: string;
  status: string;
  tool_call_id: string | null;
  name: string | null;
  latency_ms: number | null;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
}

/** GET /agent-runs/{id} 快照（重连纠偏事实源；plan/artifacts 为 durable 快照） */
export interface RunSnapshot {
  id: string;
  session_id: number | null;
  status: AgentRunStatus;
  provider: string | null;
  model: string | null;
  last_event_sequence: number;
  tool_call_count: number;
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  cost_usd: number | null;
  output: string | null;
  error_code: string | null;
  error_message: string | null;
  cancel_requested_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  active_in_process: boolean;
  steps: RunStepRecord[];
  project_id: number | null;
  workspace_id: number | null;
  base_head_sha: string | null;
  base_branch_name: string | null;
  base_git_dirty: boolean | null;
  model_profile_id: string | null;
  reasoning_effort: string | null;
  permission_mode: string | null;
  plan: { version: number; items: RunPlanItemRecord[] } | null;
  artifacts: RunArtifactRecord[];
}

/** POST /agent-runs 创建输入（coding 判定：project_id+workspace_id 成对） */
export interface CodingRunCreateInput {
  session_id: number;
  message: string;
  project_id: number;
  workspace_id: number;
  permission_mode?: string;
  model_profile_id?: string;
  reasoning_effort?: string;
  client_request_id?: string;
}

/** GET /agent-runs/{id}/approvals 项（AgentToolApprovalResponse，无 arguments 原文） */
export interface RunApprovalRecord {
  id: string;
  run_id: string;
  step_id: string | null;
  tool_call_id: string;
  tool_name: string;
  tool_version: string;
  arguments_sha256: string;
  risk_level: string;
  required_capabilities: string[];
  status: "pending" | "approved" | "rejected" | "consumed" | "expired" | "cancelled";
  expires_at: string;
  decision_at: string | null;
  consumed_at: string | null;
  created_at: string;
}

export interface RunCancelResult {
  run_id: string;
  accepted: boolean;
  active_in_process: boolean;
}

export type RunConnectionPhase =
  | "idle"
  | "starting"
  | "streaming"
  | "reconnecting"
  | "terminal"
  | "error";

/** GET /agent-runs/{id}/approvals/{aid}/preview（W3：审批完整影响范围） */
export interface RunApprovalPreviewRecord {
  tool_name: string;
  previewable: boolean;
  rel_path: string | null;
  creates_file: boolean | null;
  old_sha256: string | null;
  new_sha256: string | null;
  diff: string | null;
  truncated: boolean | null;
  reason: string | null;
}

/** GET /agent-runs/{id}/executions 项（脱敏有界 output；无 tool_call_id，按工具名+完成顺序关联） */
export interface RunExecutionRecord {
  id: string;
  tool_name: string;
  tool_version: string;
  status: string;
  error_code: string | null;
  error_message: string | null;
  output: Record<string, unknown> | null;
  created_at: string;
  completed_at: string | null;
}

/** GET /agent-runs/{id}/executions/{eid}/output?after_seq=（流式行续读） */
export interface RunExecutionOutputPage {
  lines: Array<{ seq: number; kind: string; text: string }>;
  last_seq: number;
  finished: boolean;
}

/** @ 上下文发现（GET /projects/{id}/search?kind=name） */
export interface CodingFileHint {
  relPath: string;
  name: string;
  language: string | null;
}

/** 权限模式呈现语义（v0.9.0 §5.3 三档真实契约词汇）。
 * readonly 为附加的最小权限模式（服务端缺省语义）；产品默认是 confirm。
 * workspace 与 full_access 是独立能力，不是别名。 */
export const PERMISSION_MODE_META: Record<string, { label: string; hint: string }> = {
  readonly: { label: "只读", hint: "仅读取文件与查询，不执行写入" },
  confirm: { label: "总是询问", hint: "写入或命令前逐次进入审批流" },
  workspace: {
    label: "替我批准",
    hint: "已授权工作区内命中安全命令档案的操作自动执行；越界/高风险仍会询问",
  },
  full_access: {
    label: "完全访问",
    hint: "普通本机文件与已登记开发命令免逐次审批；不获得管理员权限，项目脚本可访问用户文件并联网；需限时授权且可撤销",
  },
};

/** run 状态呈现语义（权限/风险语义用警告色系，W0 §2.3） */
export const RUN_STATUS_META: Record<
  AgentRunStatus,
  { label: string; tone: "neutral" | "info" | "success" | "warning" | "danger" }
> = {
  created: { label: "已创建", tone: "neutral" },
  running: { label: "执行中", tone: "info" },
  waiting_approval: { label: "等待审批", tone: "warning" },
  completed: { label: "已完成", tone: "success" },
  failed: { label: "失败", tone: "danger" },
  cancelled: { label: "已取消", tone: "neutral" },
  timed_out: { label: "超时", tone: "danger" },
  limit_exceeded: { label: "达到上限", tone: "warning" },
};

export const PLAN_ITEM_META: Record<RunPlanItemStatus, { label: string; tone: string }> = {
  pending: { label: "待开始", tone: "neutral" },
  in_progress: { label: "进行中", tone: "info" },
  completed: { label: "已完成", tone: "success" },
  blocked: { label: "受阻", tone: "warning" },
  failed: { label: "失败", tone: "danger" },
  cancelled: { label: "已取消", tone: "neutral" },
};
