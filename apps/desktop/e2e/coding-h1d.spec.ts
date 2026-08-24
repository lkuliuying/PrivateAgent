import { test, expect, type Page } from "@playwright/test";

/**
 * v0.9.0 H1-D（计划 §5.8/§12.19-20）· 安装版串联 E2E（浏览器模式）
 *
 * 等价第四轮试用机器 fixture：旧 .env 已有 Ollama URL/模型、
 * model_profiles 为空。串联验证：
 * 旧配置升级 → 一键验证并导入 profile → 原位进入就绪（不重建项目）→
 * 发起「看一下本机是否装了 MySQL」→ confirm 权限快照 + 诊断命令事件 →
 * 证据化结论；权限下拉三档可用（能力位真实声明）。
 *
 * 真实打包安装版的同链路验收随发布流水线执行（与既有门禁口径一致）。
 */

const GREEN_HEALTH = {
  api: true,
  ollama: { ok: true, models: [] },
  mysql: { ok: true },
  chroma: { ok: true },
};

const RUN_ID = "run-h1d-1";

const PROJECT_DTO = {
  id: 1,
  name: "旧安装项目",
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

const PROFILE_DTO = {
  id: "ollama-default",
  provider: "ollama",
  display_name: "qwen2.5:14b-instruct-q4_K_M",
  model_name: "qwen2.5:14b-instruct-q4_K_M",
  is_default: true,
  is_local: true,
  native_tool_calls: true,
  supports_streaming: true,
  supports_structured_output: false,
  supports_vision: false,
  context_tokens: 32768,
  reasoning_efforts: null,
  usage_reporting: true,
  enabled: true,
  created_at: "2026-08-23T00:00:00Z",
  updated_at: "2026-08-23T00:00:00Z",
};

type Frame = { sequence: number; type: string; payload: Record<string, unknown> };

function sse(frames: Frame[]): { contentType: string; body: string } {
  const body =
    frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join("") + ": heartbeat\n\n";
  return { contentType: "text/event-stream; charset=utf-8", body };
}

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
    { sequence: 4, type: "model.completed", payload: { finish_reason: "tool_calls", tool_call_count: 1, input_tokens: 2400, output_tokens: 64, cached_tokens: 0, cost_usd: null, provider: "ollama", model: "qwen2.5:14b-instruct-q4_K_M", request_id: "r1", latency_ms: 900 } },
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

function snapshot(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    id: RUN_ID,
    session_id: 11,
    trace_id: "trace-h1d",
    status: "running",
    provider: "ollama",
    model: "qwen2.5:14b-instruct-q4_K_M",
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
    // H1-D：run 绑定默认 profile（创建链默认绑定事实）
    model_profile_id: "ollama-default",
    reasoning_effort: null,
    permission_mode: "confirm",
    plan: null,
    artifacts: [],
    ...overrides,
  };
}

function mockH1DChain(page: Page) {
  const createdRequests: Record<string, unknown>[] = [];
  let imported = false;

  return {
    createdRequests,
    isImported: () => imported,
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
            coding_context_budget_enabled: true,
            coding_execution_detail_enabled: true,
            coding_diagnostic_commands_enabled: true,
            product_timezone: "Asia/Shanghai",
          },
        });
        return;
      }
      if (path === "/health") {
        await route.fulfill({ json: GREEN_HEALTH });
        return;
      }
      if (path === "/settings") {
        // 旧安装：全局 Ollama 配置已存在（.env 既有 PA_OLLAMA_BASE_URL/PA_LLM_MODEL）
        await route.fulfill({
          json: {
            provider_type: "ollama",
            llm_model: "qwen2.5:14b-instruct-q4_K_M",
            remote_provider_enabled: false,
            llm_context_length: 32768,
            coding_profile_import_state: imported ? "auto_imported" : "pending",
          },
        });
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
      if (path === "/agent-model-profiles/import-status") {
        await route.fulfill({
          json: {
            import_state: imported ? "auto_imported" : "pending",
            reason_code: null,
            provider: "ollama",
            model_available: true,
          },
        });
        return;
      }
      if (path === "/agent-model-profiles/import" && request.method() === "POST") {
        imported = true;
        await route.fulfill({
          json: { imported: true, already_exists: false, profile_id: "ollama-default" },
        });
        return;
      }
      if (path === "/agent-model-profiles" && request.method() === "GET") {
        // 升级前：profile 为空（第四轮试用机状态）；导入后：默认 profile 存在
        await route.fulfill({ json: imported ? [PROFILE_DTO] : [] });
        return;
      }
      if (path === "/agent-runs" && request.method() === "POST") {
        createdRequests.push(request.postDataJSON() as Record<string, unknown>);
        await route.fulfill({ status: 202, json: snapshot({ status: "running" }) });
        return;
      }
      if (path === `/agent-runs/${RUN_ID}` && request.method() === "GET") {
        await route.fulfill({ json: snapshot({ status: "completed", last_event_sequence: 9 }) });
        return;
      }
      if (path.startsWith(`/agent-runs/${RUN_ID}/events/stream`)) {
        const after = Number(url.searchParams.get("after_sequence") ?? "0");
        await route.fulfill(sse(diagnosticFrames().filter((f) => f.sequence > after)));
        return;
      }
      if (path === `/agent-runs/${RUN_ID}/events` && request.method() === "GET") {
        await route.fulfill({ json: { items: [], last_sequence: 9 } });
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
      await route.fulfill({ json: {} });
    }),
  };
}

test.describe("v0.9.0 H1-D：旧配置升级 → 导入 → 串联执行", () => {
  test("一键导入解除阻塞 → 进入原项目 → MySQL 检查证据链（§5.8）", async ({ page }) => {
    const mock = mockH1DChain(page);
    await mock.route;

    // 1) 升级后首次进入：全局已配置但 profile 为空 → profile_missing 阻塞
    await page.goto("/?coding=1");
    await expect(page.getByTestId("coding-home-provider-unconfigured")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("coding-home-provider-unconfigured")).toContainText("尚无 Coding 模型");

    // 2) 一键验证并导入（幂等导入 API）→ 原位刷新解除阻塞，不重建项目
    await page.getByTestId("home-provider-import").click();
    await expect(page.getByTestId("coding-home-ready")).toBeVisible({ timeout: 10000 });
    expect(mock.isImported()).toBe(true);

    // 3) 进入原有线程，发起可执行请求（默认权限 confirm）
    await page.getByTestId("coding-thread-11").click();
    await expect(page.getByTestId("coding-composer-input")).toBeVisible();

    // 权限下拉三档可用（能力位真实声明；不出现无响应项）
    const permissionSelect = page.getByTestId("composer-permission");
    await expect(permissionSelect.locator("option[value='workspace']")).toBeEnabled();
    await expect(permissionSelect.locator("option[value='full_access']")).toBeEnabled();

    await page.getByTestId("coding-composer-input").fill("看一下本机是否装了 MySQL");
    await page.getByTestId("coding-composer-send").click();

    // 4) run 创建按 coding 契约（confirm 权限快照；默认 profile 绑定由后端完成）
    await expect(page.getByTestId("transcript-decision-summary").first()).toBeVisible({ timeout: 15000 });
    expect(mock.createdRequests[0]).toMatchObject({
      session_id: 11,
      project_id: 1,
      workspace_id: 101,
      permission_mode: "confirm",
    });

    // 5) 诊断命令事件与证据化结论
    await expect(
      page.getByTestId("transcript-tool").filter({ hasText: "run_whitelisted_command" })
    ).toBeVisible();
    await expect(page.getByTestId("terminal-output")).toContainText("where.exe mysql", { timeout: 15000 });
    await expect(page.getByTestId("terminal-no-evidence")).toHaveCount(0);
  });

  test("导入幂等：重复进入不重复创建（already_exists 收敛）", async ({ page }) => {
    const mock = mockH1DChain(page);
    await mock.route;
    await page.goto("/?coding=1");
    await expect(page.getByTestId("coding-home-provider-unconfigured")).toBeVisible({ timeout: 10000 });
    await page.getByTestId("home-provider-import").click();
    await expect(page.getByTestId("coding-home-ready")).toBeVisible({ timeout: 10000 });
    // 刷新后 profile 非空：不再出现导入横幅/阻塞态
    await page.reload();
    await expect(page.getByTestId("coding-home-ready")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("home-provider-import")).toHaveCount(0);
    expect(mock.isImported()).toBe(true);
  });
});
