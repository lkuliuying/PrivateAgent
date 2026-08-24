import { test, expect, type Page } from "@playwright/test";

/**
 * v0.9.0 H1-B/H1-C（计划 §5.6/§5.7）：Agent 动手主链与权限/上下文可用性 E2E
 *
 * 覆盖：
 * - 可执行请求（本机 MySQL 检查样例）进入 durable run：创建请求按
 *   coding 契约，事件流呈现公开决策摘要 → 诊断命令 → 证据化结论；
 * - 完成但无工具/命令事件时如实标注（不呈现为有证据的完成）；
 * - 创建失败 = 失败关闭：阻塞卡片 + 草稿回填 + 恢复入口，重试后成功创建；
 * - 权限选择真实进入 run 创建体（替我批准 = workspace 快照）。
 */

const GREEN_HEALTH = {
  api: true,
  ollama: { ok: true, models: [] },
  mysql: { ok: true },
  chroma: { ok: true },
};

const RUN_ID = "run-h1b-1";

const PROJECT_DTO = {
  id: 1,
  name: "PrivateAgent",
  root_path: "C:\\secret\\agent",
  language: "python",
  framework: null,
  status: "active",
  last_scanned_at: null,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-22T00:00:00Z",
};

const WORKSPACE_DTO = {
  id: 101,
  project_id: 1,
  kind: "root",
  root_path: "C:\\secret\\agent",
  branch_name: "main",
  head_sha: "abcd1234ef567890",
  status: "active",
  last_used_at: null,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-22T00:00:00Z",
};

const THREAD_DTO = {
  id: 11,
  title: "本机环境检查",
  created_at: "2026-08-20T00:00:00Z",
  updated_at: "2026-08-22T00:00:00Z",
  project_id: 1,
  workspace_id: 101,
  kind: "coding",
  last_run_id: null,
  pinned_at: null,
  archived_at: null,
};

type Frame = { sequence: number; type: string; payload: Record<string, unknown> };

function sse(frames: Frame[]): { contentType: string; body: string } {
  const body =
    frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join("") + ": heartbeat\n\n";
  return { contentType: "text/event-stream; charset=utf-8", body };
}

/** 诊断主链帧：决策摘要 → where.exe mysql 诊断命令 → 证据化结论 */
function diagnosticFrames(): Frame[] {
  return [
    { sequence: 1, type: "run.started", payload: { max_steps: 12, max_tool_calls: 8, max_wall_time_seconds: 120 } },
    { sequence: 2, type: "model.started", payload: { ordinal: 1, kind: "model", name: "model" } },
    {
      sequence: 3,
      type: "decision.summary",
      payload: {
        goal: "看一下本机是否装了 MySQL",
        method: "本轮决策：调用工具 run_whitelisted_command",
        next_steps: ["run_whitelisted_command"],
      },
    },
    { sequence: 4, type: "model.completed", payload: { finish_reason: "tool_calls", tool_call_count: 1, input_tokens: 2400, output_tokens: 64, cached_tokens: 0, cost_usd: null, provider: "ollama", model: "qwen3-coder", request_id: "r1", latency_ms: 900 } },
    { sequence: 5, type: "tool.requested", payload: { ordinal: 1, kind: "tool", tool_call_id: "tc-diag", name: "run_whitelisted_command" } },
    { sequence: 6, type: "tool.started", payload: { tool_call_id: "tc-diag", name: "run_whitelisted_command" } },
    { sequence: 7, type: "tool.completed", payload: { tool_call_id: "tc-diag", name: "run_whitelisted_command" } },
    {
      sequence: 8,
      type: "run.completed",
      payload: {
        output: "已检查：where.exe mysql 命中 C:\\mysql\\bin\\mysql.exe（退出码 0）；服务 MySQL80 状态 RUNNING。结论：本机已安装 MySQL 8.0，证据来自诊断命令输出。",
        error: null,
        error_code: null,
        tool_call_count: 1,
        input_tokens: 4800,
        output_tokens: 160,
        cached_tokens: 0,
        cost_usd: null,
      },
    },
    { sequence: 9, type: "run.terminal", payload: { status: "completed" } },
  ];
}

/** 无工具事件的完成帧（文字回答，不得呈现为有执行证据的完成） */
function noEvidenceFrames(): Frame[] {
  return [
    { sequence: 1, type: "run.started", payload: { max_steps: 12, max_tool_calls: 8, max_wall_time_seconds: 120 } },
    { sequence: 2, type: "model.started", payload: { ordinal: 1, kind: "model", name: "model" } },
    { sequence: 3, type: "model.completed", payload: { finish_reason: "stop", tool_call_count: 0, input_tokens: 1200, output_tokens: 80, cached_tokens: 0, cost_usd: null, provider: "ollama", model: "qwen3-coder", request_id: "r2", latency_ms: 500 } },
    {
      sequence: 4,
      type: "run.completed",
      payload: {
        output: "MySQL 是一个关系型数据库……",
        error: null,
        error_code: null,
        tool_call_count: 0,
        input_tokens: 1200,
        output_tokens: 80,
        cached_tokens: 0,
        cost_usd: null,
      },
    },
    { sequence: 5, type: "run.terminal", payload: { status: "completed" } },
  ];
}

function snapshot(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    id: RUN_ID,
    session_id: 11,
    trace_id: "trace-h1b",
    status: "running",
    provider: "ollama",
    model: "qwen3-coder",
    last_event_sequence: 0,
    tool_call_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    cached_tokens: 0,
    cost_usd: null,
    output: null,
    error_code: null,
    error_message: null,
    cancel_requested_at: null,
    started_at: "2026-08-23T00:00:00Z",
    completed_at: null,
    created_at: "2026-08-23T00:00:00Z",
    updated_at: "2026-08-23T00:00:00Z",
    active_in_process: true,
    steps: [],
    project_id: 1,
    workspace_id: 101,
    base_head_sha: "abcd1234ef567890",
    base_branch_name: "main",
    base_git_dirty: false,
    model_profile_id: null,
    reasoning_effort: null,
    permission_mode: "confirm",
    plan: null,
    artifacts: [],
    ...overrides,
  };
}

interface H1BOptions {
  /** 创建响应：默认 202；可注入 409 失败关闭场景 */
  createResponses?: Array<{ status: number; body: Record<string, unknown> }>;
  /** 首段流帧 */
  frames?: Frame[];
  /** /capabilities 覆盖字段 */
  capabilities?: Record<string, unknown>;
}

function mockH1BApi(page: Page, options: H1BOptions = {}) {
  const createdRequests: Record<string, unknown>[] = [];
  let createCall = 0;
  let deliveredMax = 0;
  let terminalStatus: string | null = null;
  const frames = options.frames ?? diagnosticFrames();
  for (const frame of frames) {
    deliveredMax = Math.max(deliveredMax, frame.sequence);
    if (frame.type === "run.terminal") terminalStatus = String(frame.payload.status ?? "");
  }

  return {
    createdRequests,
    route: page.route("**://127.0.0.1:8000/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;

      if (path === "/capabilities") {
        await route.fulfill({
          json: {
            chat_execution_mode: "legacy",
            legacy_tool_planner_enabled: true,
            agent_read_only_tools_enabled: true,
            rag_chat_runtime_enabled: false,
            coding_agent_ui_enabled: true,
            project_bound_runs_enabled: true,
            coding_workspace_auto_approve: true,
            coding_full_access_supported: true,
            coding_full_access_audit: true,
            coding_full_access_revoke: true,
            coding_context_budget_enabled: false,
            coding_diagnostic_commands_enabled: true,
            product_timezone: "Asia/Shanghai",
            ...(options.capabilities ?? {}),
          },
        });
        return;
      }
      if (path === "/health") {
        await route.fulfill({ json: GREEN_HEALTH });
        return;
      }
      if (path === "/projects" && request.method() === "GET") {
        await route.fulfill({ json: [PROJECT_DTO] });
        return;
      }
      if (path === "/projects/1/workspaces") {
        await route.fulfill({ json: [WORKSPACE_DTO] });
        return;
      }
      if (path === "/sessions" && request.method() === "GET") {
        if (url.searchParams.get("kind") === "coding") {
          await route.fulfill({ json: [THREAD_DTO] });
        } else {
          await route.fulfill({ json: [] });
        }
        return;
      }
      if (path === "/agent-runs" && request.method() === "POST") {
        createdRequests.push(request.postDataJSON() as Record<string, unknown>);
        const responses = options.createResponses ?? [
          { status: 202, body: snapshot({ status: "running" }) },
        ];
        const response =
          responses[Math.min(createCall, responses.length - 1)];
        createCall += 1;
        await route.fulfill({ status: response.status, json: response.body });
        return;
      }
      if (path === `/agent-runs/${RUN_ID}` && request.method() === "GET") {
        await route.fulfill({
          json: snapshot({
            status: terminalStatus ?? "running",
            last_event_sequence: deliveredMax,
          }),
        });
        return;
      }
      if (path.startsWith(`/agent-runs/${RUN_ID}/events/stream`)) {
        const after = Number(url.searchParams.get("after_sequence") ?? "0");
        await route.fulfill(sse(frames.filter((frame) => frame.sequence > after)));
        return;
      }
      if (path === `/agent-runs/${RUN_ID}/events` && request.method() === "GET") {
        await route.fulfill({ json: { items: [], last_sequence: deliveredMax } });
        return;
      }
      if (path === `/agent-runs/${RUN_ID}/approvals`) {
        await route.fulfill({ json: [] });
        return;
      }
      if (path === `/agent-runs/${RUN_ID}/executions`) {
        await route.fulfill({ json: [] });
        return;
      }
      if (path === "/agent-model-profiles") {
        await route.fulfill({ json: [] });
        return;
      }
      if (path === "/settings") {
        await route.fulfill({ json: { model: "qwen3-coder" } });
        return;
      }
      await route.fulfill({ json: {} });
    }),
  };
}

async function openThread(page: Page) {
  await page.goto("/?coding=1");
  await expect(page.getByTestId("coding-thread-11")).toBeVisible({ timeout: 10000 });
  await page.getByTestId("coding-thread-11").click();
  await expect(page.getByTestId("coding-composer-input")).toBeVisible();
}

async function sendMessage(page: Page, text: string) {
  await page.getByTestId("coding-composer-input").fill(text);
  await page.getByTestId("coding-composer-send").click();
}

test.describe("v0.9.0 H1-B：Agent 动手主链（§5.6）", () => {
  test("可执行请求进入 durable run：决策摘要 → 诊断命令 → 证据化结论", async ({ page }) => {
    const mock = mockH1BApi(page);
    await mock.route;
    await openThread(page);
    await sendMessage(page, "看一下本机是否装了 MySQL");

    // 创建请求按 coding 契约（默认权限 confirm，不扩大默认权限）
    await expect(page.getByTestId("transcript-decision-summary").first()).toBeVisible({ timeout: 15000 });
    expect(mock.createdRequests[0]).toMatchObject({
      session_id: 11,
      project_id: 1,
      workspace_id: 101,
      message: "看一下本机是否装了 MySQL",
      permission_mode: "confirm",
    });
    // 公开决策摘要与诊断命令事件可见（执行证据链）
    await expect(page.locator('[data-testid="transcript-decision-summary"]').last()).toContainText("run_whitelisted_command");
    await expect(
      page.getByTestId("transcript-tool").filter({ hasText: "run_whitelisted_command" })
    ).toBeVisible();
    // 证据化结论呈现于终态输出
    await expect(page.getByTestId("terminal-output")).toContainText("where.exe mysql", { timeout: 15000 });
    await expect(page.getByTestId("terminal-no-evidence")).toHaveCount(0);
  });

  test("完成但无工具/命令事件 → 如实标注无执行证据（不伪装已完成任务）", async ({ page }) => {
    await mockH1BApi(page, { frames: noEvidenceFrames() }).route;
    await openThread(page);
    await sendMessage(page, "MySQL 是什么");
    await expect(page.getByTestId("terminal-output")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("terminal-no-evidence")).toBeVisible();
    await expect(page.getByTestId("terminal-no-evidence")).toContainText("未执行工具/命令");
  });

  test("创建失败关闭：阻塞卡片 + 草稿回填 + 恢复重试后成功创建", async ({ page }) => {
    const mock = mockH1BApi(page, {
      createResponses: [
        {
          status: 409,
          body: { error_code: "full_access_revoked", detail: "完全访问授予已撤销" },
        },
        { status: 202, body: snapshot({ status: "running" }) },
      ],
    });
    await mock.route;
    await openThread(page);
    await sendMessage(page, "检查本机 MySQL 服务状态");

    // 阻塞卡片：具体阻塞项 + 恢复入口（不静默隐藏、无假完成记录）
    await expect(page.getByTestId("run-create-blocker")).toBeVisible();
    await expect(page.getByTestId("run-create-blocker")).toContainText("完全访问");
    // 草稿回填：未成功的输入不丢失
    await expect(page.getByTestId("coding-composer-input")).toHaveValue("检查本机 MySQL 服务状态");
    // 无误导性重连提示（无 run 时不显示）
    await expect(page.getByTestId("stream-reconnect-notice")).toHaveCount(0);
    // 恢复入口重试 → 第二次创建成功进入事件流
    await page.getByTestId("run-blocker-recover").click();
    await expect(page.getByTestId("transcript-decision-summary").first()).toBeVisible({ timeout: 15000 });
    expect(mock.createdRequests).toHaveLength(2);
  });

  test("替我批准（workspace）真实进入 run 权限快照", async ({ page }) => {
    const mock = mockH1BApi(page);
    await mock.route;
    await openThread(page);
    // PaSelect 属性透传到原生 select，可直接 selectOption
    await page.getByTestId("composer-permission").selectOption("workspace");
    await sendMessage(page, "运行项目测试");
    await expect(page.getByTestId("transcript-decision-summary").first()).toBeVisible({ timeout: 15000 });
    expect(mock.createdRequests[0]).toMatchObject({ permission_mode: "workspace" });
  });
});
