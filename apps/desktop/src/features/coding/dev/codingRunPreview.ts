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
import type {
  RunApprovalPreviewRecord,
  RunExecutionOutputPage,
  RunExecutionRecord,
  RunStreamFrame,
} from "../model/runContracts";

export const CODING_RUN_PREVIEW_KEYS = [
  "running-early",
  "planning",
  "tools",
  "waiting-approval",
  "completed",
  "failed",
  "cancelled",
  "limit-exceeded",
  // v0.8.0 W3（W0 矩阵第 11/12/13/17/19 项）
  "patch-preview",
  "command-output",
  "verification",
  "conflict",
  "partial-unknown",
  // v0.8.0 W5：5,000 活动记录压力（分段渲染）
  "stress",
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

const DECISION_START: RunStreamFrame = {
  sequence: 3,
  type: "decision.summary",
  payload: {
    goal: "我会先检查侧栏布局、窄屏断点和现有测试，再确定需要调整的组件范围。",
    method: "这次只改动当前工作区的布局与可访问性，不改变项目导航和数据流。",
    next_steps: ["读取目标组件", "修改布局", "运行相关测试"],
  },
};

const DECISION_AFTER_READ: RunStreamFrame = {
  sequence: 10,
  type: "decision.summary",
  payload: {
    goal: "已经确认遮挡来自折叠宽度与窄窗口抽屉共用同一组尺寸约束。",
    method: "我正在把两种状态拆开处理，并保留现有 aria-label 和键盘路径。",
    next_steps: ["应用文件修改", "验证窄屏状态"],
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
    output: "已完成侧栏布局修复。\n\n- 折叠态宽度调整为 72px，并保留 aria-label。\n- 窄窗口抽屉改为自包含布局。\n- 相关测试全部通过（12 passed）。",
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
        DECISION_START,
        MODEL_STARTED,
        PLAN_CREATED,
        MODEL_COMPLETED,
        ...TOOL_READ,
        DECISION_AFTER_READ,
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
        // 投影器对乱序帧幂等跳过：重编序号保证演示帧序严格递增。
      ].map((frame, index) => ({ ...frame, sequence: index + 1 }));
    case "cancelled":
      return [
        RUN_STARTED,
        CONTEXT_PREPARED,
        MODEL_STARTED,
        MODEL_COMPLETED,
        TOOL_WRITE_APPROVAL,
        { sequence: 6, type: "run.cancelled", payload: { output: null, error: "tool approval rejected", error_code: "approval_rejected", tool_call_count: 1, input_tokens: 2100, output_tokens: 120, cached_tokens: 0, cost_usd: null } },
        // 同上：重编序号（TOOL_WRITE_APPROVAL 原序号 10 会吃掉后续帧）。
      ].map((frame, index) => ({ ...frame, sequence: index + 1 }));
    case "limit-exceeded":
      return [
        RUN_STARTED,
        CONTEXT_PREPARED,
        MODEL_STARTED,
        ...TOOL_READ,
        { sequence: 9, type: "run.limit_exceeded", payload: { output: null, error: "达到最大步数", error_code: "max_steps", tool_call_count: 8, input_tokens: 9800, output_tokens: 700, cached_tokens: 0, cost_usd: null } },
      ];
    // W3：PatchSet 预览（审批等待 + 预览 diff，矩阵 11）
    case "patch-preview":
      return frames("waiting-approval");
    // W3：命令运行与流式输出（矩阵 12）
    case "command-output":
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
        { sequence: 13, type: "tool.completed", payload: { tool_call_id: "tc-write", name: "apply_patch_to_workspace" } },
        { sequence: 14, type: "tool.requested", payload: { ordinal: 3, kind: "tool", tool_call_id: "tc-cmd", name: "run_whitelisted_command" } },
        { sequence: 15, type: "tool.started", payload: { tool_call_id: "tc-cmd", name: "run_whitelisted_command" } },
      ];
    // W3：验证中（矩阵 13）
    case "verification":
      return [
        RUN_STARTED,
        CONTEXT_PREPARED,
        MODEL_STARTED,
        PLAN_CREATED,
        MODEL_COMPLETED,
        ...TOOL_READ,
        VALIDATION_STARTED,
      ];
    // W3：workspace 冲突（patchset_conflict，矩阵 17）
    case "conflict":
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
        { sequence: 13, type: "patch_set.failed", payload: { patch_set_id: "ps-1", error_code: "patchset_conflict", error_message: "目标文件已被外部修改，预览基于的内容过期" } },
        { sequence: 14, type: "run.failed", payload: { output: null, error: "PatchSet 应用失败", error_code: "patchset_conflict", tool_call_count: 2, input_tokens: 5000, output_tokens: 200, cached_tokens: 0, cost_usd: null } },
      ];
    // W3：partial_unknown 人工处置（矩阵 19）
    case "partial-unknown":
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
        { sequence: 13, type: "patch_set.applied", payload: { patch_set_id: "ps-1", preview_version: 3, verified: true } },
        { sequence: 14, type: "patch_set.rolled_back", payload: { patch_set_id: "ps-1", reason: "验证失败后回滚部分完成" } },
        { sequence: 15, type: "patch_set.unknown", payload: { patch_set_id: "ps-1", reason: "回滚中断，磁盘状态未知，需人工处置" } },
        { sequence: 16, type: "run.failed", payload: { output: null, error: "回滚中断", error_code: "patchset_partial_unknown", tool_call_count: 2, input_tokens: 5200, output_tokens: 210, cached_tokens: 0, cost_usd: null } },
      ];
    // W5：5,000 活动记录压力（tool.requested/started/completed 循环 + 终态）
    case "stress": {
      const frames: RunStreamFrame[] = [
        RUN_STARTED,
        CONTEXT_PREPARED,
        MODEL_STARTED,
        PLAN_CREATED,
        MODEL_COMPLETED,
      ];
      let sequence = frames.length;
      for (let i = 0; i < 1666; i++) {
        const toolCallId = `tc-stress-${i}`;
        frames.push(
          { sequence: ++sequence, type: "tool.requested", payload: { ordinal: i + 1, kind: "tool", tool_call_id: toolCallId, name: i % 3 === 0 ? "read_code_file" : i % 3 === 1 ? "grep_code" : "run_whitelisted_command" } },
          { sequence: ++sequence, type: "tool.started", payload: { tool_call_id: toolCallId, name: "tool" } },
          { sequence: ++sequence, type: "tool.completed", payload: { tool_call_id: toolCallId, name: "tool" } }
        );
      }
      frames.push(
        { sequence: ++sequence, type: "run.completed", payload: { output: "压力测试完成：5,000 条活动记录已投影。", error: null, error_code: null, tool_call_count: 1666, input_tokens: 999999, output_tokens: 8888, cached_tokens: 0, cost_usd: null } },
        { sequence: ++sequence, type: "run.terminal", payload: { status: "completed" } }
      );
      return frames;
    }
  }
}

const PREVIEW_DIFF = [
  "@@ -12,7 +12,9 @@",
  " export function useSidebar() {",
  "-  const open = ref(false);",
  "+  const open = ref(false);",
  '+  const overlay = useMediaQuery("(max-width: 1279px)");',
  "+  watchEffect(() => { if (!overlay.value) drawerOpen.value = false; });",
  "   return { open };",
].join("\n");

const W3_APPROVAL_PREVIEWS: Record<string, RunApprovalPreviewRecord | null> = {
  "ap-preview-1": {
    tool_name: "apply_patch_to_workspace",
    previewable: true,
    rel_path: "src/features/coding/components/CodingSidebar.vue",
    creates_file: false,
    old_sha256: "1".repeat(64),
    new_sha256: "2".repeat(64),
    diff: PREVIEW_DIFF,
    truncated: false,
    reason: null,
  },
};

const W3_EXECUTIONS: RunExecutionRecord[] = [
  {
    id: "exec-cmd-1",
    tool_name: "run_whitelisted_command",
    tool_version: "1.0.0",
    status: "succeeded",
    error_code: null,
    error_message: null,
    output: {
      // 与后端 run_command 真实 output_json 字段对齐（args/cwd/returncode）；
      // 参数含凭据形态，验证呈现层脱敏（W6-R）
      args: ["pytest", "tests", "-q", "--token=sk-demo-secret-0001"],
      cwd: "F:/workspace/privateagent-demo",
      returncode: 0,
      succeeded: true,
      truncated: false,
      parsed: {
        parser: "pytest",
        summary: "12 passed in 3.42s",
        passed: 12,
        failed: 0,
        skipped: 0,
        errors: 0,
        failures: [],
        truncated: false,
      },
    },
    created_at: "2026-08-22T00:10:00Z",
    completed_at: "2026-08-22T00:10:04Z",
  },
];

const W3_OUTPUT_PAGE: RunExecutionOutputPage = {
  lines: [
    { seq: 1, kind: "stdout", text: "============================= test session starts =============================" },
    { seq: 2, kind: "stdout", text: "collected 12 items" },
    { seq: 3, kind: "stdout", text: "tests/test_sidebar.py .......                                             [ 58%]" },
    { seq: 4, kind: "stdout", text: "tests/test_composer.py .....                                              [100%]" },
    { seq: 5, kind: "stdout", text: "======================== 12 passed in 3.42s ==========================" },
  ],
  last_seq: 5,
  finished: true,
};

export interface CodingRunPreviewResult {
  projection: RunProjection;
  approvalPreviews?: Record<string, RunApprovalPreviewRecord | null>;
  executions?: RunExecutionRecord[];
  outputPages?: Record<string, RunExecutionOutputPage | null>;
}

/** 由帧序列构建静态投影（userMessage 为演示输入原文；W3 键附带预览/执行/输出夹具） */
export function createStaticProjection(key: CodingRunPreviewKey): CodingRunPreviewResult {
  const projection = createRunProjection("run-preview", "修复侧栏在窄窗口下的布局遮挡问题");
  for (const frame of frames(key)) {
    applyRunFrame(projection, frame);
  }
  if (key === "completed") {
    projection.startedAt = "2026-08-28T12:00:00.000Z";
    projection.completedAt = "2026-08-28T12:38:58.000Z";
  }
  if (key === "command-output") {
    return {
      projection,
      approvalPreviews: W3_APPROVAL_PREVIEWS,
      executions: W3_EXECUTIONS,
      outputPages: { "exec-cmd-1": W3_OUTPUT_PAGE },
    };
  }
  if (key === "patch-preview" || key === "conflict" || key === "partial-unknown") {
    return { projection, approvalPreviews: W3_APPROVAL_PREVIEWS };
  }
  return { projection };
}
