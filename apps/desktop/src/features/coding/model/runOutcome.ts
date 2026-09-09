import type { ExecutionResult, Requirement, RunOutcome } from "./generated/codingContracts";
import type { AgentRunStatus } from "./runContracts";
import { RUN_STATUS_META } from "./runContracts";

export function unknownRunOutcome(runId: string): RunOutcome {
  return { schema_version: "1.0", run_id: runId, goal_outcome: "unknown", requirements: [],
    verification_results: [], evidence_ids: [], unverified_items: ["没有可用的完成验证结果"] };
}

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.length <= 256 && value.every(item => typeof item === "string");
}

export function parseRequirements(value: unknown): Requirement[] {
  if (!Array.isArray(value) || value.length > 128) return [];
  return value.filter((item): item is Requirement => record(item) && typeof item.requirement_id === "string"
    && typeof item.description === "string" && (item.required === undefined || typeof item.required === "boolean"));
}

/** 未知版本、错配运行或不完整证据必须显示未知；类型断言不能代替边界校验。 */
export function parseRunOutcome(value: unknown, runId: string): RunOutcome {
  const unknown = unknownRunOutcome(runId);
  if (!record(value) || value.schema_version !== "1.0" || value.run_id !== runId
    || !["answered", "verified", "unmet", "blocked", "unknown"].includes(String(value.goal_outcome))) return unknown;
  const requirements = parseRequirements(value.requirements ?? []);
  if (!Array.isArray(value.requirements ?? []) || requirements.length !== ((value.requirements ?? []) as unknown[]).length
    || !Array.isArray(value.verification_results) || value.verification_results.length > 128
    || !strings(value.evidence_ids) || !strings(value.unverified_items)) return unknown;
  const keys = requirements.map(item => item.requirement_id);
  const results = value.verification_results;
  if (new Set(keys).size !== keys.length || results.some(item => !record(item)
    || !keys.includes(String(item.requirement_id)) || !["passed", "failed", "blocked", "unverified"].includes(String(item.status))
    || !strings(item.evidence_ids) || item.evidence_ids.some(id => !(value.evidence_ids as string[]).includes(id))
    || (item.message !== undefined && typeof item.message !== "string")
    || (item.status === "passed" && item.evidence_ids.length === 0))) return unknown;
  if (new Set(results.map(item => item.requirement_id)).size !== results.length) return unknown;
  const refs = value.evidence_refs;
  if (requirements.some(item => item.origin && item.origin !== "legacy")) {
    if (!Array.isArray(refs) || refs.length > 256 || refs.some(item => !record(item) || item.run_id !== runId
      || typeof item.evidence_id !== "string" || typeof item.operation_id !== "string"
      || !Number.isSafeInteger(item.source_sequence) || Number(item.source_sequence) < 1
      || !record(item.content_ref) || typeof item.content_ref.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(item.content_ref.sha256)
      || !Number.isSafeInteger(item.content_ref.bytes) || Number(item.content_ref.bytes) < 0
      || typeof item.verified_at !== "string" || !Number.isFinite(Date.parse(item.verified_at)))) return unknown;
    const refIds = refs.map(item => item.evidence_id);
    if (new Set(refIds).size !== refIds.length || value.evidence_ids.some(id => !refIds.includes(id))) return unknown;
  }
  if (value.goal_outcome === "verified") {
    const required = requirements.filter(item => item.required !== false);
    if (!required.length || value.unverified_items.length || results.some(item => item.status === "failed")
      || required.some(item => !results.some(result => result.requirement_id === item.requirement_id && result.status === "passed"))) return unknown;
  }
  if (value.goal_outcome === "answered" && requirements.some(item => item.required !== false && item.kind !== "preview")) return unknown;
  return { schema_version: "1.0", run_id: runId, goal_outcome: value.goal_outcome as RunOutcome["goal_outcome"],
    requirements, verification_results: results, evidence_ids: value.evidence_ids, unverified_items: value.unverified_items };
}

export function parseExecutionResult(value: unknown, executionId: string): ExecutionResult | undefined {
  if (!record(value) || value.schema_version !== "1.0" || value.execution_id !== executionId || typeof value.operation_id !== "string"
    || !["exited", "timed_out", "cancelled", "failed", "unknown"].includes(String(value.outcome))
    || !["test", "search", "development", "unclassified"].includes(String(value.command_kind))
    || !["succeeded", "failed", "unknown"].includes(String(value.validation_outcome))) return undefined;
  const exit = value.exit_code;
  if (exit !== null && exit !== undefined && (typeof exit !== "number" || !Number.isSafeInteger(exit))) return undefined;
  if (value.outcome === "exited" && typeof exit !== "number") return undefined;
  if (value.outcome === "unknown" && exit != null) return undefined;
  if (value.validation_outcome === "succeeded" && (value.outcome !== "exited" || value.command_kind === "unclassified"
    || !(value.command_kind === "search" ? [0, 1] : [0]).includes(exit as number))) return undefined;
  return value as ExecutionResult;
}

export function runResultMeta(status: AgentRunStatus, outcome?: RunOutcome | null, verifying = false): { label: string; tone: string } {
  if (["queued", "paused", "interrupted"].includes(status)) return RUN_STATUS_META[status];
  if (["created", "running", "waiting_approval"].includes(status)) {
    return verifying ? { label: "验证中", tone: "info" } : RUN_STATUS_META[status];
  }
  if (["cancelled", "timed_out", "limit_exceeded"].includes(status)) return RUN_STATUS_META[status];
  switch (outcome?.goal_outcome) {
    case "answered": return { label: "已回答 / 已生成预览", tone: "neutral" };
    case "verified": return status === "completed" ? { label: "已验证完成", tone: "success" } : { label: "结果未确认", tone: "warning" };
    case "unmet": return { label: outcome.verification_results?.some(item => item.status === "failed"
      && outcome.requirements?.some(requirement => requirement.requirement_id === item.requirement_id && requirement.kind === "test"))
      ? "测试失败，任务未完成" : "任务未完成", tone: "danger" };
    case "blocked": return { label: "受阻，等待处理", tone: "warning" };
    default: return { label: status === "failed" ? "执行失败，结果未确认" : "结果未确认", tone: "warning" };
  }
}
