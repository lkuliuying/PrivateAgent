import { codingFetchJson, codingJsonInit } from "./codingHttp";

export type ObserverCheckKind = "artifact" | "test" | "command";
export type ObserverCheckStatus = "pending" | "passed" | "failed" | "blocked" | "unverified" | "skipped";

export interface ObserverCheck {
  id: string;
  kind: ObserverCheckKind;
  scope: string;
}

export interface ProjectObserverConfig {
  version: number;
  enabled: boolean;
  checks: ObserverCheck[];
}

export interface RunObserverReport {
  schema_version: "1.0";
  run_id: string;
  status: string;
  goal_outcome: string | null;
  last_event_sequence: number;
  config_version: number | null;
  counts: { events: number; steps: number; executions: number };
  truncated: boolean;
  progress: { repeated_observations: number; failure_repeats: number; verification_retries: number };
  error: { category: string; code: string } | null;
  steps: Array<{ id: string | null; ordinal: number; kind: string; status: string; name: string | null; plan_item_key: string | null }>;
  checks: Array<{ id: string; kind: ObserverCheckKind; status: ObserverCheckStatus; reason_code: string; evidence_ids: string[] }>;
  events: Array<{ sequence: number; type: string; step_id: string | null; execution_id: string | null; category: string }>;
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("观察器返回的数据格式不正确");
  return value as Record<string, unknown>;
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new Error("观察器返回的数据格式不正确");
  return value;
}

function count(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw new Error("观察器返回的计数不正确");
  return value;
}

function flag(value: unknown): boolean {
  if (typeof value !== "boolean") throw new Error("观察器返回的数据格式不正确");
  return value;
}

function array(value: unknown, limit = Number.POSITIVE_INFINITY): unknown[] {
  if (!Array.isArray(value) || value.length > limit) throw new Error("观察器返回的记录超过范围或格式不正确");
  return value;
}

function choice<T extends string>(value: unknown, choices: readonly T[]): T {
  if (!choices.includes(value as T)) throw new Error("观察器返回了不支持的状态或检查类型");
  return value as T;
}

const kinds = ["artifact", "test", "command"] as const;
const statuses = ["pending", "passed", "failed", "blocked", "unverified", "skipped"] as const;
const nullableText = (value: unknown): string | null => value === null ? null : text(value);

export function parseObserverConfig(value: unknown): ProjectObserverConfig {
  const data = object(value);
  return {
    version: count(data.version), enabled: flag(data.enabled),
    checks: array(data.checks, 8).map(value => {
      const item = object(value);
      return { id: text(item.id), kind: choice(item.kind, kinds), scope: text(item.scope) };
    }),
  };
}

/** 显式投影白名单字段，后端新增正文或内部数据时不会被复制到诊断 JSON。 */
export function parseObserverReport(value: unknown): RunObserverReport {
  const data = object(value), counts = object(data.counts), progress = object(data.progress);
  const error = data.error === null ? null : object(data.error);
  return {
    schema_version: choice(data.schema_version, ["1.0"]), run_id: text(data.run_id), status: text(data.status),
    goal_outcome: nullableText(data.goal_outcome), last_event_sequence: count(data.last_event_sequence),
    config_version: data.config_version === null ? null : count(data.config_version),
    counts: { events: count(counts.events), steps: count(counts.steps), executions: count(counts.executions) },
    truncated: flag(data.truncated),
    progress: { repeated_observations: count(progress.repeated_observations), failure_repeats: count(progress.failure_repeats), verification_retries: count(progress.verification_retries) },
    error: error && { category: text(error.category), code: text(error.code) },
    steps: array(data.steps, 100).map(value => {
      const item = object(value);
      return { id: nullableText(item.id), ordinal: count(item.ordinal), kind: text(item.kind), status: text(item.status), name: nullableText(item.name), plan_item_key: nullableText(item.plan_item_key) };
    }),
    checks: array(data.checks, 8).map(value => {
      const item = object(value);
      return { id: text(item.id), kind: choice(item.kind, kinds), status: choice(item.status, statuses), reason_code: text(item.reason_code), evidence_ids: array(item.evidence_ids).map(text) };
    }),
    events: array(data.events, 100).map(value => {
      const item = object(value);
      return { sequence: count(item.sequence), type: text(item.type), step_id: nullableText(item.step_id), execution_id: nullableText(item.execution_id), category: text(item.category) };
    }),
  };
}

export function observerReportJson(report: RunObserverReport): string {
  return JSON.stringify(parseObserverReport(report), null, 2);
}

export async function fetchRunObserver(runId: string, signal?: AbortSignal): Promise<RunObserverReport> {
  const report = parseObserverReport(await codingFetchJson<unknown>(`/agent-runs/${encodeURIComponent(runId)}/observer`, { signal }));
  if (report.run_id !== runId) throw new Error("观察报告与当前任务不一致，请重新读取");
  return report;
}

export async function fetchProjectObserverConfig(projectId: number, signal?: AbortSignal): Promise<ProjectObserverConfig> {
  return parseObserverConfig(await codingFetchJson<unknown>(`/projects/${projectId}/observer-config`, { signal }));
}

export async function saveProjectObserverConfig(projectId: number, input: {
  expected_version: number; enabled: boolean; checks: ObserverCheck[];
}, signal?: AbortSignal): Promise<ProjectObserverConfig> {
  return parseObserverConfig(await codingFetchJson<unknown>(`/projects/${projectId}/observer-config`, {
    ...codingJsonInit("PUT", input), signal,
  }));
}
