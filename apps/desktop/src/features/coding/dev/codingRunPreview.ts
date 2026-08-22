/**
 * v0.8.0 W2 · 任务页事件流静态预览夹具
 *
 * ?coding-run-preview=<key>（DEV 动态 import，生产构建不进入）。
 * 帧序列严格对齐后端 L1 事实（contracts.py payload / E5 七步闭环顺序），
 * 禁止虚构后端状态；覆盖 W0 冻结矩阵第 7/8/9/10/14/18 项。
 */
import {
  applyRunFrame,
  createRunProjection,
  type RunProjection,
} from "../model/runProjector";
import type { RunStreamFrame } from "../model/runContracts";

export const CODING_RUN_PREVIEW_KEYS = [
  "running-early",
  "planning",
  "tools",
  "waiting-approval",
  "completed",
  "failed",
  "cancelled",
  "limit-exceeded",
] as const;

export type CodingRunPreviewKey = (typeof CODING_RUN_PREVIEW_KEYS)[number];

const RUN_STARTED: RunStreamFrame = {
  sequence: 1,
  type: "run.started",
  payload: { max_steps: 12, max_tool_calls: 8, max_wall_time_seconds: 120.0, output_verifier: "default", max_verification_retries: 1 },
};

const CONTEXT_PREPARED: RunStreamFrame = {
  sequence: 2,
  type: "context.prepared",
  payload: {
    estimated_tokens: 3521,
    section_tokens: { history: 1800, memory: 240, rag: 1200, summary: 281 },
    history_included: 4,
    memory_included: 2,
    rag_included: 6,
    summary_included: 0,
    sensitive_excluded: 1,
    truncated: false,
    decisions: [{ id: "d1", kind: "memory", included: true, reason: "相关记忆命中", estimated_tokens: 240 }],
    decisions_truncated: false,
  },
};

const MODEL_STARTED: RunStreamFrame = {
  sequence: 3,
  type: "model.started",
  payload: { ordinal: 1, kind: "model", name: "model" },
};

const PLAN_CREATED: RunStreamFrame = {
  sequence: 4,
  type: "plan.created",
  payload: {
    plan_version: 1,
    items: [
      { item_key: "read-structure", title: "阅读目标模块结构", status: "completed" },
      { item_key: "edit-file", title: "修改侧栏布局样式", status: "in_progress" },
      { item_key: "run-tests", title: "运行相关测试", status: "pending" },
      { item_key: "summarize", title: "总结改动", status: "pending" },
    ],
  },
};

const MODEL_COMPLETED: RunStreamFrame = {
  sequence: 5,
  type: "model.completed",
  payload: {
    finish_reason: "tool_calls",
    tool_call_count: 1,
    input_tokens: 3521,
    output_tokens: 180,
    cached_tokens: 512,
    cost_usd: null,
    provider: "ollama",
    model: "qwen3-coder:30b",
    request_id: "req-1",
    latency_ms: 2140.5,
  },
};

const TOOL_READ: RunStreamFrame[] = [
  { sequence: 6, type: "tool.requested", payload: { ordinal: 1, kind: "tool", tool_call_id: "tc-read", name: "read_code_file" } },
  { sequence: 7, type: "tool.started", payload: { tool_call_id: "tc-read", name: "read_code_file" } },
  { sequence: 8, type: "tool.completed", payload: { tool_call_id: "tc-read", name: "read_code_file" } },
];

const PLAN_ITEM_MOVED: RunStreamFrame = {
  sequence: 9,
  type: "plan.item_changed",
  payload: { plan_version: 1, item_key: "edit-file", previous_status: "in_progress", status: "in_progress" },
};

const TOOL_WRITE_APPROVAL: RunStreamFrame = {
  sequence: 10,
  type: "tool.approval_required",
  payload: { tool_call_id: "tc-write", name: "apply_patch_to_workspace", approval_id: "ap-preview-1", tool_call_count: 2 },
};

const PATCH_PREVIEW: RunStreamFrame = {
  sequence: 11,
  type: "patch_set.preview_created",
  payload: { patch_set_id: "ps-1", preview_version: 3, file_count: 2, truncated: false, base_head_sha: "ab" + "0".repeat(38) },
};

const PATCH_APPLIED: RunStreamFrame = {
  sequence: 18,
  type: "patch_set.applied",
  payload: { patch_set_id: "ps-1", preview_version: 3, verified: true },
};

const VALIDATION_STARTED: RunStreamFrame = {
  sequence: 19,
  type: "output.validation_started",
  payload: { verifier: "default", attempt: 1, retry_count: 0, max_retries: 1 },
};

const VALIDATION_PASSED: RunStreamFrame = {
  sequence: 20,
  type: "output.validation_passed",
  payload: { verifier: "default", attempt: 1, retry_count: 0, max_retries: 1, code: "ok", message: "输出校验通过" },
};

const RUN_COMPLETED: RunStreamFrame = {
  sequence: 21,
  type: "run.completed",
  payload: {
    output: "已完成侧栏布局修复：\n1. 调整折叠态宽度 72px 并保留 aria-label\n2. 窄窗口抽屉模式自包含\n3. 相关测试全部通过（12 passed）",
    error: null,
    error_code: null,
    tool_call_count: 3,
    input_tokens: 8210,
    output_tokens: 640,
    cached_tokens: 1024,
    cost_usd: null,
  },
};

function frames(key: CodingRunPreviewKey): RunStreamFrame[] {
  switch (key) {
    case "running-early":
      return [RUN_STARTED, CONTEXT_PREPARED, MODEL_STARTED];
    case "planning":
      return [RUN_STARTED, CONTEXT_PREPARED, MODEL_STARTED, PLAN_CREATED];
    case "tools":
      return [RUN_STARTED, CONTEXT_PREPARED, MODEL_STARTED, PLAN_CREATED, MODEL_COMPLETED, ...TOOL_READ, PLAN_ITEM_MOVED];
    case "waiting-approval":
      return [
        RUN_STARTED,
        CONTEXT_PREPARED,
        MODEL_STARTED,
        PLAN_CREATED,
        MODEL_COMPLETED,
        ...TOOL_READ,
        PLAN_ITEM_MOVED,
        TOOL_WRITE_APPROVAL,
        PATCH_PREVIEW,
      ];
    case "completed":
      return [
        RUN_STARTED,
        CONTEXT_PREPARED,
        MODEL_STARTED,
        PLAN_CREATED,
        MODEL_COMPLETED,
        ...TOOL_READ,
        PLAN_ITEM_MOVED,
        TOOL_WRITE_APPROVAL,
        PATCH_PREVIEW,
        { sequence: 12, type: "tool.approval_resolved", payload: { tool_call_id: "tc-write", name: "apply_patch_to_workspace", approval_id: "ap-preview-1" } },
        { sequence: 13, type: "tool.requested", payload: { ordinal: 2, kind: "tool", tool_call_id: "tc-write", name: "apply_patch_to_workspace" } },
        { sequence: 14, type: "tool.completed", payload: { tool_call_id: "tc-write", name: "apply_patch_to_workspace" } },
        { sequence: 15, type: "plan.item_changed", payload: { plan_version: 1, item_key: "edit-file", previous_status: "in_progress", status: "completed" } },
        { sequence: 16, type: "artifact.created", payload: { artifact_id: "art-1", kind: "patch_applied", title: "侧栏布局修复", step_id: null } },
        { sequence: 17, type: "plan.item_changed", payload: { plan_version: 1, item_key: "run-tests", previous_status: "pending", status: "in_progress" } },
        PATCH_APPLIED,
        VALIDATION_STARTED,
        VALIDATION_PASSED,
        RUN_COMPLETED,
        { sequence: 22, type: "run.terminal", payload: { status: "completed" } },
      ].map((frame, index) => ({ ...frame, sequence: index + 1 }));
    case "failed":
      return [
        RUN_STARTED,
        CONTEXT_PREPARED,
        MODEL_STARTED,
        VALIDATION_STARTED,
        { sequence: 5, type: "output.validation_failed", payload: { verifier: "default", attempt: 1, retry_count: 0, max_retries: 1, code: "empty_output", message: "输出为空", correction: null, will_retry: false } },
        { sequence: 6, type: "run.failed", payload: { output: null, error: "输出校验未通过", error_code: "output_validation_failed", tool_call_count: 0, input_tokens: 1200, output_tokens: 0, cached_tokens: 0, cost_usd: null } },
      ];
    case "cancelled":
      return [
        RUN_STARTED,
        CONTEXT_PREPARED,
        MODEL_STARTED,
        MODEL_COMPLETED,
        TOOL_WRITE_APPROVAL,
        { sequence: 6, type: "run.cancelled", payload: { output: null, error: "tool approval rejected", error_code: "approval_rejected", tool_call_count: 1, input_tokens: 2100, output_tokens: 120, cached_tokens: 0, cost_usd: null } },
      ];
    case "limit-exceeded":
      return [
        RUN_STARTED,
        CONTEXT_PREPARED,
        MODEL_STARTED,
        ...TOOL_READ,
        { sequence: 9, type: "run.limit_exceeded", payload: { output: null, error: "达到最大步数", error_code: "max_steps", tool_call_count: 8, input_tokens: 9800, output_tokens: 700, cached_tokens: 0, cost_usd: null } },
      ];
  }
}

export interface CodingRunPreviewResult {
  projection: RunProjection;
}

/** 由帧序列构建静态投影（userMessage 为演示输入原文） */
export function createStaticProjection(key: CodingRunPreviewKey): CodingRunPreviewResult {
  const projection = createRunProjection("run-preview", "修复侧栏在窄窗口下的布局遮挡问题");
  for (const frame of frames(key)) {
    applyRunFrame(projection, frame);
  }
  return { projection };
}
