import { test, expect, type Page } from "@playwright/test";
import { fulfillCodingAuth, prepareCodingFixture } from "./coding-auth-fixture";

test.beforeEach(async ({ page }) => prepareCodingFixture(page));

/**
 * v0.8.0 W2：任务页与真实计划 E2E
 * 覆盖 W0 冻结矩阵第 7/8/9/10/14/15/16/18 项：请求已提交、生成计划、执行工具、
 * 等待审批（批准/拒绝）、终态、SSE 断线重连（快照纠偏+缺口重放一致性）。
 * 全部断言基于 durable 事件/快照事实，无启发式计划。
 */

const GREEN_HEALTH = {
  api: true,
  ollama: { ok: true, models: [] },
  mysql: { ok: true },
  chroma: { ok: true },
};

const RUN_ID = "run-e2e-1";

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
  title: "修复窄屏侧栏遮挡问题",
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

function runStarted(): Frame {
  return {
    sequence: 1,
    type: "run.started",
    payload: { max_steps: 12, max_tool_calls: 8, max_wall_time_seconds: 120 },
  };
}

function planCreated(): Frame {
  return {
    sequence: 4,
    type: "plan.created",
    payload: {
      plan_version: 1,
      items: [
        { item_key: "read", title: "阅读侧栏组件", status: "completed", ordinal: 1, detail: null },
        { item_key: "edit", title: "修改布局样式", status: "in_progress", ordinal: 2, detail: null },
        { item_key: "test", title: "运行相关测试", status: "pending", ordinal: 3, detail: null },
      ],
    },
  };
}

function terminalFrame(status: string, sequence: number): Frame {
  return { sequence, type: "run.terminal", payload: { status } };
}

/** 完整闭环帧（1..14）：计划 → 读文件 → 写文件（审批）→ 校验 → 完成 */
function fullLoopFrames(output: string): Frame[] {
  return [
    runStarted(),
    { sequence: 2, type: "context.prepared", payload: { estimated_tokens: 3200, truncated: false } },
    { sequence: 3, type: "model.started", payload: { ordinal: 1, kind: "model", name: "model" } },
    planCreated(),
    { sequence: 5, type: "model.completed", payload: { finish_reason: "tool_calls", tool_call_count: 1, input_tokens: 3200, output_tokens: 96, cached_tokens: 0, cost_usd: null, provider: "ollama", model: "qwen3-coder", request_id: "r1", latency_ms: 1200 } },
    { sequence: 6, type: "tool.requested", payload: { ordinal: 1, kind: "tool", tool_call_id: "tc-read", name: "read_code_file" } },
    { sequence: 7, type: "tool.started", payload: { tool_call_id: "tc-read", name: "read_code_file" } },
    { sequence: 8, type: "tool.completed", payload: { tool_call_id: "tc-read", name: "read_code_file" } },
    { sequence: 9, type: "tool.approval_required", payload: { tool_call_id: "tc-write", name: "apply_patch_to_workspace", approval_id: "ap-1", tool_call_count: 2 } },
    { sequence: 10, type: "tool.approval_resolved", payload: { tool_call_id: "tc-write", name: "apply_patch_to_workspace", approval_id: "ap-1" } },
    { sequence: 11, type: "tool.completed", payload: { tool_call_id: "tc-write", name: "apply_patch_to_workspace" } },
    { sequence: 12, type: "output.validation_started", payload: { verifier: "default", attempt: 1, retry_count: 0, max_retries: 1 } },
    { sequence: 13, type: "output.validation_passed", payload: { verifier: "default", attempt: 1, retry_count: 0, max_retries: 1, code: "ok", message: "校验通过" } },
    { sequence: 14, type: "run.completed", payload: { output, error: null, error_code: null, tool_call_count: 2, input_tokens: 6400, output_tokens: 320, cached_tokens: 0, cost_usd: null } },
    terminalFrame("completed", 15),
  ];
}

function snapshot(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    id: RUN_ID,
    session_id: 11,
    trace_id: "trace-1",
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
    started_at: "2026-08-22T00:00:00Z",
    completed_at: null,
    created_at: "2026-08-22T00:00:00Z",
    updated_at: "2026-08-22T00:00:00Z",
    active_in_process: true,
    steps: [],
    project_id: 1,
    workspace_id: 101,
    base_head_sha: "abcd1234ef567890",
    base_branch_name: "main",
    base_git_dirty: false,
    model_profile_id: null,
    reasoning_effort: null,
    permission_mode: "readonly",
    plan: null,
    artifacts: [],
    ...overrides,
  };
}

interface RunScenario {
  /** 第一段流帧（after=0）；默认全量闭环 */
  firstChunk?: Frame[];
  /** 闭环全文（续读缺口重放的完整帧序列来源） */
  output?: string;
  /** 审批场景：决策前续读返回空（等待），决策后返回剩余帧 */
  afterApproval?: (approved: boolean) => Frame[];
}

function mockRunApi(page: Page, scenario: RunScenario = {}) {
  const createdRequests: Record<string, unknown>[] = [];
  let approvalApproved: boolean | null = null;
  let deliveredMax = 0;
  let terminalStatus: string | null = null;
  let terminalFacts: Record<string, unknown> = {};

  function trackFrames(frames: Frame[]): void {
    for (const frame of frames) {
      deliveredMax = Math.max(deliveredMax, frame.sequence);
      if (["run.completed", "run.failed", "run.cancelled", "run.timed_out", "run.limit_exceeded", "run.interrupted"].includes(frame.type)) {
        terminalFacts = { output: frame.payload.output ?? null, error_code: frame.payload.error_code ?? null,
          error_message: frame.payload.error ?? null };
      }
      if (frame.type === "run.terminal") {
        terminalStatus = String(frame.payload.status ?? "");
      }
    }
  }

  // 注意：续读缺口重放永远以完整闭环为源；firstChunk 只用于首段（断线截断场景）
  const full = () =>
    fullLoopFrames(scenario.output ?? "已完成侧栏修复：折叠态宽度与抽屉模式均正常，相关测试 12 passed。");

  return {
    createdRequests,
    approvalDecision: () => approvalApproved,
    route: page.route("**://127.0.0.1:8000/**", async (route) => {
      if (await fulfillCodingAuth(route)) return;
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
            agent_runs_api_enabled: true,
            project_bound_runs_enabled: true,
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
        await route.fulfill({ status: 202, json: snapshot({ status: "running" }) });
        return;
      }
      if (path === `/agent-runs/${RUN_ID}` && request.method() === "GET") {
        await route.fulfill({
          json: snapshot({
            ...terminalFacts,
            status: terminalStatus ?? "running",
            last_event_sequence: deliveredMax,
          }),
        });
        return;
      }
      if (path === `/agent-runs/${RUN_ID}/approvals` && request.method() === "GET") {
        await route.fulfill({
          json: [
            {
              id: "ap-1",
              run_id: RUN_ID,
              step_id: null,
              tool_call_id: "tc-write",
              tool_name: "apply_patch_to_workspace",
              tool_version: "1.0.0",
              arguments_sha256: "f".repeat(64),
              risk_level: "confirm",
              required_capabilities: ["filesystem.write"],
              status: approvalApproved === null ? "pending" : approvalApproved ? "consumed" : "rejected",
              expires_at: "2026-08-23T00:00:00Z",
              decision_at: approvalApproved === null ? null : "2026-08-22T00:10:00Z",
              consumed_at: null,
              created_at: "2026-08-22T00:09:00Z",
            },
          ],
        });
        return;
      }
      if (path.includes(`/agent-runs/${RUN_ID}/approvals/ap-1/approve`)) {
        approvalApproved = true;
        await route.fulfill({ status: 202, json: snapshot({ status: "running" }) });
        return;
      }
      if (path.includes(`/agent-runs/${RUN_ID}/approvals/ap-1/reject`)) {
        approvalApproved = false;
        await route.fulfill({ status: 200, json: snapshot({ status: "cancelled", error_code: "approval_rejected" }) });
        return;
      }
      if (path.startsWith(`/agent-runs/${RUN_ID}/events/stream`)) {
        const after = Number(url.searchParams.get("after_sequence") ?? "0");
        let frames: Frame[];
        if (after === 0) {
          frames = scenario.firstChunk ?? full();
        } else if (scenario.afterApproval && approvalApproved === null) {
          // 等待人工决策：无新事件（连接空闲关闭 → 客户端退避重连）
          frames = [];
        } else if (scenario.afterApproval) {
          frames = scenario.afterApproval(approvalApproved === true).filter(
            (frame) => frame.sequence > after
          );
        } else {
          frames = full().filter((frame) => frame.sequence > after);
        }
        trackFrames(frames);
        await route.fulfill(sse(frames));
        return;
      }
      if (path === `/agent-runs/${RUN_ID}/events` && request.method() === "GET") {
        await route.fulfill({ json: { items: [], last_sequence: deliveredMax } });
        return;
      }
      if (path === "/agent-model-profiles") {
        await route.fulfill({
          json: [
            {
              id: "local-coder",
              provider: "ollama",
              display_name: "Qwen3 Coder 30B",
              is_local: true,
              native_tool_calls: true,
              supports_streaming: true,
              supports_structured_output: true,
              supports_vision: false,
              context_tokens: 131072,
              reasoning_efforts: ["low", "medium", "high"],
              usage_reporting: true,
              enabled: true,
              created_at: "2026-08-01T00:00:00Z",
              updated_at: "2026-08-01T00:00:00Z",
            },
          ],
        });
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

test("连续对话保持正文样式，重开任务恢复最终用时", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await mockRunApi(page).route;
  const firstOutput = "已完成。\n\n- 文件：`hello.py`\n\n```python\nprint('hello world')\n```";
  const messages: Array<Record<string, unknown>> = [];
  let round = 0;
  const finished = new Set<string>();
  const framesFor = (id: string) => [runStarted(),
    { sequence: 2, type: "run.completed", payload: { output: id.endsWith("1") ? firstOutput : "当前目录有 1 个文件。", tool_call_count: 0 } },
    terminalFrame("completed", 3)];
  await page.route("**://127.0.0.1:8000/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/sessions" && request.method() === "GET") {
      return route.fulfill({ json: [{ ...THREAD_DTO, last_run_id: round ? `style-${round}` : null }] });
    }
    if (path === "/sessions/11/messages") return route.fulfill({ json: messages });
    if (path === "/sessions/11/latest-agent-run") return route.fulfill({ json: { run_id: round ? `style-${round}` : null } });
    if (path === "/agent-runs" && request.method() === "POST") {
      round++;
      messages.push({ id: messages.length + 1, session_id: 11, role: "user", content: request.postDataJSON().message, created_at: "2026-09-17T00:00:00Z" });
      return route.fulfill({ status: 202, json: snapshot({ id: `style-${round}`, status: "running" }) });
    }
    const run = /^\/agent-runs\/(style-\d+)(.*)$/.exec(path);
    if (!run) return route.fallback();
    const [, id, suffix] = run;
    const frames = framesFor(id);
    if (suffix === "/events/stream") {
      if (!finished.has(id)) {
        finished.add(id);
        messages.push({ id: messages.length + 1, session_id: 11, role: "assistant", content: frames[1].payload.output, created_at: "2026-09-17T00:00:05Z" });
      }
      return route.fulfill(sse(frames));
    }
    if (suffix === "/events") return route.fulfill({ json: { items: frames.slice(0, 2), last_sequence: 2 } });
    if (suffix === "") return route.fulfill({ json: snapshot({ id, status: "completed", last_event_sequence: 2,
      output: frames[1].payload.output, started_at: "2026-09-17T00:00:00Z", completed_at: "2026-09-17T00:00:05Z" }) });
    return route.fulfill({ json: [] });
  });
  await openThread(page);
  await sendMessage(page, "创建 hello.py");
  const answer = page.getByTestId("terminal-output");
  await expect(answer).toContainText("hello world");
  await expect(page.getByTestId("run-duration-toggle")).toHaveAccessibleName(/^展开执行过程/);
  await expect(page.getByTestId("run-duration")).toContainText("用时 5.0 秒");
  const appearance = async (selector: string) => page.locator(selector).evaluate(element => {
    const style = getComputedStyle(element);
    const code = element.querySelector("pre")!;
    const codeStyle = getComputedStyle(code);
    return { width: element.getBoundingClientRect().width, fontSize: style.fontSize, lineHeight: style.lineHeight,
      background: style.backgroundColor, padding: style.padding, border: style.borderWidth,
      codeFont: codeStyle.fontSize, codeBackground: codeStyle.backgroundColor, codePadding: codeStyle.padding };
  });
  const before = await appearance('[data-testid="terminal-output"]');
  await sendMessage(page, "当前目录下有几个文件");
  await expect(answer).toContainText("当前目录有 1 个文件");
  await expect(page.getByTestId("transcript-history-assistant")).toHaveCount(1);
  expect(await appearance('[data-testid="transcript-history-assistant"] .assistant-response')).toEqual(before);
  await page.screenshot({ path: testInfo.outputPath("conversation-stable.png"), fullPage: true });
  await page.reload();
  await page.getByTestId("coding-thread-11").click();
  await expect(page.getByTestId("run-duration")).toContainText("用时 5.0 秒");
  await expect(answer).toContainText("当前目录有 1 个文件");
  await expect(page.getByTestId("transcript-history-assistant")).toHaveCount(1);
  await page.setViewportSize({ width: 760, height: 900 });
  const overflow = await page.getByTestId("transcript-history-assistant").evaluate(element => element.scrollWidth > element.clientWidth);
  expect(overflow).toBe(false);
});

test("完成任务居中展示，环境面板和文件工作区独立展开", async ({ page }, testInfo) => {
  await mockRunApi(page, { output: "已创建 hello.py，运行输出为 hello world!。" }).route;
  await page.route("**://127.0.0.1:8000/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/capabilities") {
      await route.fulfill({ json: { coding_agent_ui_enabled: true, agent_runs_api_enabled: true, project_bound_runs_enabled: true,
        chat_execution_mode: "legacy", coding_recovery_contract_version: "1.0", coding_patchsets_enabled: true, coding_execution_sessions_enabled: true, coding_worktree_enabled: true } });
    } else if (path.endsWith("/approvals")) {
      await route.fulfill({ json: [] });
    } else if (path === "/sessions/11/review") {
      await route.fulfill({ json: { scope: "last_turn", runs: [{ id: RUN_ID, status: "completed", created_at: "2026-09-17T00:00:00Z", workspace_id: 101, outcome: null, patch_count: 1 }], workspace: null } });
    } else if (path.endsWith("/patches")) {
      await route.fulfill({ json: { patches: [{ patch_set_id: "patch-hello", run_id: RUN_ID, preview_sha256: "a".repeat(64), status: "applied", kind: "patch",
        changes: [{ change_id: "file-hello", operation: "create", rel_path: "hello.py", before_kind: "missing", after_kind: "file", diff_chars: 20 }], conflicts: [], journal: [] }],
        baseline: null, current_git: { is_git: false }, ownership_note: "当前磁盘状态可能包含外部改动。" } });
    } else if (path.endsWith("/recovery")) {
      await route.fulfill({ json: { run_id: RUN_ID, supported: true, status: "completed", state_version: 5, can_resume: false,
        blockers: [], controls: [], budget: { model_requests: 5, tool_calls: 4, active_seconds: 14 }, expired_approvals: [], limitations: [] } });
    } else if (path === "/projects/1/workspaces/101/files") {
      await route.fulfill({ json: { entries: [{ rel_path: "hello.py", name: "hello.py", kind: "file", size_bytes: 22 }, { rel_path: "src", name: "src", kind: "directory", size_bytes: null }], next_cursor: null, total: 2 } });
    } else if (path === "/projects/1/workspaces/101/file") {
      await route.fulfill({ json: { rel_path: "hello.py", content: 'print("hello world!")\n', sha256: "a".repeat(64), offset: 0, next_offset: null, total_chars: 22 } });
    } else if (path === "/projects/1/workspaces/101") {
      await route.fulfill({ json: WORKSPACE_DTO });
    } else if (path === "/sessions/11/executions") {
      await route.fulfill({ json: { items: [{ execution_id: "hello-process", run_id: RUN_ID, argv: ["python", "hello.py"], cwd: ".", status: "exited",
        retention: "run", stopped: true, exit_code: 0, error: null, dropped_bytes: 0, last_output_sequence: 1 }] } });
    } else {
      await route.fallback();
    }
  });
  await openThread(page);
  await sendMessage(page, "创建一个 hello.py 文件，打印 hello world! 并运行");
  await expect(page.getByTestId("terminal-output")).toContainText("hello world!");
  await expect(page.getByTestId("run-duration-toggle")).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(".transcript-scroll .execution-panel")).toHaveCount(0);
  await page.getByTestId("thread-environment-toggle").click();
  await page.getByRole("tab", { name: "变更", exact: true }).click();
  await expect(page.locator(".environment-panel .patch-review > summary")).toContainText("hello.py");
  await page.getByRole("tab", { name: "进程", exact: true }).click();
  await expect(page.locator(".environment-panel .execution-panel")).toHaveCount(1);
  await page.getByRole("tab", { name: "环境", exact: true }).click();
  await expect(page.locator(".environment-overview")).toContainText("本机工作区");
  await expect(page.locator(".worktree-panel")).toContainText("当前任务使用项目本地目录");
  await expect(page.getByRole("button", { name: /创建并选择 worktree|清理当前 worktree/ })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("environment-panel.png") });
  await page.getByTestId("thread-files-toggle").click();
  await page.getByRole("button", { name: "hello.py", exact: true }).click();
  await expect(page.locator(".file-preview pre")).toContainText('print("hello world!")');
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.screenshot({ path: testInfo.outputPath("file-workspace-wide.png") });
  await page.setViewportSize({ width: 760, height: 700 });
  await expect.poll(() => page.locator(".appshell-rail").evaluate(element => element.getBoundingClientRect().width)).toBe(0);
  await expect(page.getByTestId("file-workspace")).toBeInViewport();
  await page.screenshot({ path: testInfo.outputPath("file-workspace-narrow.png") });
  await page.getByRole("button", { name: "关闭文件工作区", exact: true }).click();
  for (const viewport of [{ width: 1920, height: 1080 }, { width: 760, height: 700 }]) {
    await page.setViewportSize(viewport);
    if (viewport.width < 1280) {
      await expect.poll(() => page.locator(".appshell-rail").evaluate(element => element.getBoundingClientRect().width)).toBe(0);
      expect(await page.getByTestId("thread-back-home").evaluate(element => {
        const bounds = element.getBoundingClientRect();
        return element.contains(document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2));
      })).toBe(true);
    }
    const input = page.getByTestId("coding-composer-input");
    await expect(input).toBeInViewport();
    const bounds = await page.locator(".transcript-content").evaluate(element => {
      const column = element.getBoundingClientRect();
      const composer = document.querySelector('[data-testid="coding-composer"]')!.getBoundingClientRect();
      const scroll = element.parentElement!;
      return { width: column.width, offset: Math.abs(column.x - composer.x), scrollWidth: scroll.scrollWidth, clientWidth: scroll.clientWidth };
    });
    expect(bounds.width).toBeLessThanOrEqual(900);
    expect(bounds.offset).toBeLessThan(20);
    expect(bounds.scrollWidth).toBeLessThanOrEqual(bounds.clientWidth);
    await input.fill("继续检查");
    await page.screenshot({ path: testInfo.outputPath(`task-layout-${viewport.width}.png`) });
    await page.getByTestId("run-duration-toggle").click();
    await expect(page.getByTestId("transcript-tool").first()).toBeVisible();
    await expect(input).toBeInViewport();
    await page.getByTestId("run-duration-toggle").click();
  }
});

test("S5：追加约束回执、暂停继续和关联恢复在工作台收敛", async ({ page }) => {
  await page.addInitScript(() => window.sessionStorage.setItem("pa_access_token", "s5-browser-fixture"));
  const mock = mockRunApi(page);
  await mock.route;
  const nextId = "run-e2e-resumed";
  let currentId = RUN_ID;
  let status = "running";
  let version = 1;
  const controls: Record<string, unknown>[] = [];
  const frames: Frame[] = [runStarted()];
  await page.route("**://127.0.0.1:8000/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/auth/me") {
      await route.fulfill({ json: { id: 2, email: "user@example.test", username: "fixture", display_name: "fixture", role: "user", status: "active" } });
    } else if (path === "/capabilities") {
      await route.fulfill({ json: { coding_agent_ui_enabled: true, agent_runs_api_enabled: true, project_bound_runs_enabled: true,
        chat_execution_mode: "legacy", coding_recovery_contract_version: "1.0" } });
    } else if (path.endsWith("/recovery")) {
      await route.fulfill({ json: { run_id: currentId, supported: true, status, state_version: version, checkpoint_id: `cp-${version}`,
        logical_task_id: RUN_ID, resumed_from_run_id: currentId === nextId ? RUN_ID : null,
        can_resume: ["paused", "cancelled"].includes(status), blockers: [], controls, executions: [], budget: { model_requests: 3 }, expired_approvals: [], limitations: [] } });
    } else if (path.endsWith("/review")) {
      await route.fulfill({ json: { task_changes: [], preexisting_changes: [{ rel_path: "user.txt", status: "M" },
        ...Array.from({ length: 30 }, (_, index) => ({ rel_path: `history-${index}.txt`, status: "M" }))],
        external_or_unattributed: [], command_candidates: [], snapshot_complete: true, limitations: [] } });
    } else if (/\/agent-runs\/[^/]+\/(pause|resume|cancel|steer)$/.test(path)) {
      const kind = path.split("/").pop()!;
      const data = request.postDataJSON();
      expect(data.expected_state_version).toBe(version);
      version++;
      if (kind === "pause") status = "paused";
      if (kind === "cancel") status = "cancelled";
      if (kind === "resume") {
        if (status === "cancelled") currentId = nextId;
        status = "running";
      }
      const record = { request_id: data.request_id, kind, status: kind === "steer" ? "received" : "applied", result_run_id: currentId, message: data.message };
      controls.push(record);
      if (kind !== "steer") frames.push({ sequence: frames.length + 1, type: `run.${kind === "resume" ? "resumed" : status}`, payload: {} });
      await route.fulfill({ status: 202, json: record });
    } else if (path.endsWith("/events/stream")) {
      await route.fulfill(sse(frames.filter(frame => frame.sequence > Number(url.searchParams.get("after_sequence") ?? 0))));
    } else if (path === `/agent-runs/${RUN_ID}` || path === `/agent-runs/${nextId}`) {
      await route.fulfill({ json: { ...snapshot({ status, last_event_sequence: frames.length }), id: currentId } });
    } else {
      await route.fallback();
    }
  });
  await openThread(page);
  await sendMessage(page, "修改后保留现场");
  await page.getByTestId("thread-menu-toggle").click();
  await page.getByRole("menuitem", { name: "恢复现场详情", exact: true }).click();
  const panel = page.getByRole("region", { name: "任务恢复与协作" });
  await expect(panel).toBeVisible();
  expect(mock.createdRequests[0].recovery_contract_version).toBe("1.0");
  await panel.getByLabel("补充本任务约束").fill("停止写入，先解释结果");
  await panel.getByRole("button", { name: "追加约束", exact: true }).click();
  await expect(panel.getByLabel("控制进度")).toContainText("等待应用");
  await panel.getByRole("button", { name: "暂停", exact: true }).click();
  await expect(panel.getByRole("button", { name: "核对并继续" })).toBeEnabled();
  await panel.getByRole("button", { name: "核对并继续" }).click();
  await expect(panel.getByRole("button", { name: "暂停", exact: true })).toBeVisible();
  await panel.getByRole("button", { name: "取消任务" }).click();
  await expect(panel.getByRole("button", { name: "核对并继续" })).toBeEnabled();
  await panel.getByRole("button", { name: "核对并继续" }).click();
  await expect(panel).toContainText("已从中断记录继续");
  await expect(panel).toContainText("累计模型请求 3 次");
  await panel.getByText("核对变更归属", { exact: true }).click();
  await expect(panel).toContainText("已有改动 · user.txt");
  // 长审查列表在环境浮层内滚动，恢复按钮可操作且浮层不越出窗口。
  for (const viewport of [{ width: 1365, height: 900 }, { width: 760, height: 700 }]) {
    await page.setViewportSize(viewport);
    const pause = panel.getByRole("button", { name: "暂停", exact: true });
    await pause.scrollIntoViewIfNeeded();
    await expect.poll(() => pause.evaluate(element => {
      const box = element.getBoundingClientRect();
      return element.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
    })).toBe(true);
    const bounds = await page.getByTestId("thread-environment-panel").evaluate(element => {
      const box = element.getBoundingClientRect();
      return { bottom: box.bottom, viewport: window.innerHeight };
    });
    expect(bounds.bottom).toBeLessThanOrEqual(bounds.viewport);
  }
  await page.getByRole("button", { name: "关闭环境面板" }).click();
  await expect(page.getByTestId("coding-composer-input")).toBeInViewport();
});

test.describe("v0.8.0 W2 任务页与真实计划", () => {
  test("闭环：发送→计划→工具→校验→终态，缺完成证据不标成功（矩阵 7/8/9/14）", async ({ page }) => {
    const mock = mockRunApi(page);
    await mock.route;
    await openThread(page);
    await sendMessage(page, "修复侧栏在窄窗口下的遮挡");

    await expect(page.getByTestId("thread-run-status")).toHaveText(/执行中|结果未确认/);
    // 完成后过程默认折叠，先按真实界面展开，再核对完整执行证据。
    await expect(page.getByTestId("thread-run-status")).toHaveText(/结果未确认/);
    await page.getByRole("button", { name: /^展开执行过程/ }).click();
    await expect(page.getByTestId("transcript-user-message")).toContainText("遮挡");
    await expect(page.getByTestId("transcript-plan-note")).toBeVisible();
    await expect(
      page.getByTestId("transcript-tool").filter({ hasText: "read_code_file" })
    ).toBeVisible();
    await expect(page.getByTestId("terminal-output")).toContainText("12 passed", { timeout: 15000 });
    // 历史载荷只有 completed；缺少 S1 完成证据时不得显示已验证成功。
    await expect(page.getByTestId("thread-run-status")).toHaveText(/结果未确认/);
    await expect(page.getByTestId("thread-run-status")).not.toHaveClass(/tone-success/);
    // run 创建请求按 coding 契约
    expect(mock.createdRequests[0]).toMatchObject({
      session_id: 11,
      project_id: 1,
      workspace_id: 101,
      message: "修复侧栏在窄窗口下的遮挡",
    });
  });

  test("计划浮层：后端真实计划条目与状态（非启发式）", async ({ page }) => {
    await mockRunApi(page).route;
    await openThread(page);
    await sendMessage(page, "修复侧栏遮挡");
    await expect(page.getByTestId("thread-run-status")).toHaveText(/结果未确认/);
    await page.getByRole("button", { name: /^展开执行过程/ }).click();
    await expect(page.getByTestId("transcript-plan-note")).toBeVisible({ timeout: 15000 });
    await page.getByTestId("thread-environment-toggle").click();
    await page.getByRole("tab", { name: "环境", exact: true }).click();
    await page.getByTestId("thread-plan-toggle").click();
    await expect(page.getByTestId("run-plan-popover")).toBeVisible();
    await expect(page.getByTestId("plan-item-read")).toHaveAttribute("data-status", "completed");
    await expect(page.getByTestId("plan-item-edit")).toHaveAttribute("data-status", "in_progress");
    await expect(page.getByTestId("plan-item-test")).toHaveAttribute("data-status", "pending");
    // 完成后 item 状态不再变化（帧内无更多 item_changed）
    await expect(page.getByTestId("terminal-output")).toBeVisible({ timeout: 15000 });
  });

  test("等待审批→批准→续跑完成（矩阵 10）", async ({ page }) => {
    const full = fullLoopFrames("批准后完成写入并校验通过。");
    const cut = full.findIndex((frame) => frame.type === "tool.approval_resolved");
    await mockRunApi(page, {
      // 第一段流停在 tool.approval_required（含），run 进入等待审批
      firstChunk: full.slice(0, cut),
      afterApproval: (approved) =>
        approved
          ? full.slice(cut)
          : [
              { sequence: 11, type: "run.cancelled", payload: { output: null, error: "tool approval rejected", error_code: "approval_rejected", tool_call_count: 1, input_tokens: 100, output_tokens: 10, cached_tokens: 0, cost_usd: null } },
              terminalFrame("cancelled", 12),
            ],
    }).route;
    await openThread(page);
    await sendMessage(page, "修复侧栏遮挡");

    // 审批卡带风险与能力，等待审批状态
    await expect(page.getByTestId("approval-card")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("approval-card")).toContainText("apply_patch_to_workspace");
    await expect(page.getByTestId("approval-card")).toContainText("需确认");
    await expect(page.getByTestId("thread-run-status")).toContainText("等待审批");

    await page.getByTestId("approval-approve-ap-1").click();
    await expect(page.getByTestId("terminal-output")).toContainText("批准后完成", { timeout: 20000 });
    await expect(page.getByTestId("thread-run-status")).toHaveText(/结果未确认/);
    await expect(page.getByTestId("thread-run-status")).not.toHaveClass(/tone-success/);
  });

  test("等待审批→拒绝→任务取消（矩阵 18）", async ({ page }) => {
    const full = fullLoopFrames("不应到达");
    const cut = full.findIndex((frame) => frame.type === "tool.approval_resolved");
    await mockRunApi(page, {
      firstChunk: full.slice(0, cut),
      afterApproval: (approved) =>
        approved
          ? full.slice(cut)
          : [
              { sequence: 11, type: "run.cancelled", payload: { output: null, error: "tool approval rejected", error_code: "approval_rejected", tool_call_count: 1, input_tokens: 100, output_tokens: 10, cached_tokens: 0, cost_usd: null } },
              terminalFrame("cancelled", 12),
            ],
    }).route;
    await openThread(page);
    await sendMessage(page, "修复侧栏遮挡");
    await expect(page.getByTestId("approval-card")).toBeVisible({ timeout: 15000 });
    await page.getByTestId("approval-reject-ap-1").click();
    await expect(page.getByTestId("thread-run-status")).toHaveText(/已取消/, { timeout: 20000 });
    await expect(page.getByTestId("terminal-summary")).toContainText("approval_rejected");
  });

  test("SSE 断线重连：快照纠偏+缺口重放后 transcript/计划一致（矩阵 15/16）", async ({ page }) => {
    const full = fullLoopFrames("重连后恢复一致的最终输出。");
    // 第一段流只送到 plan.created（sequence 4）即断开；续读以完整闭环重放缺口
    await mockRunApi(page, { firstChunk: full.slice(0, 4), output: "重连后恢复一致的最终输出。" }).route;
    await openThread(page);
    await sendMessage(page, "修复侧栏遮挡");
    await expect(page.getByTestId("transcript-plan-note")).toBeVisible({ timeout: 15000 });

    // 断开后自动重连：快照（已在执行后段）→ events 缺口重放 → 续流 → 终态一致
    await expect(page.getByTestId("terminal-output")).toContainText("重连后恢复一致", { timeout: 25000 });
    await expect(page.getByTestId("thread-run-status")).toHaveText(/结果未确认/);
    await expect(page.getByTestId("thread-run-status")).not.toHaveClass(/tone-success/);
    // 条目不重复（run-start 只出现一次）
    const runStartCount = await page.getByTestId("transcript-run-start").count();
    expect(runStartCount).toBe(1);
    const planNotes = await page.getByTestId("transcript-plan-note").count();
    expect(planNotes).toBe(1);
  });

  test("失败终态：错误码与说明呈现（矩阵 14）", async ({ page }) => {
    await mockRunApi(page, {
      firstChunk: [
        runStarted(),
        { sequence: 2, type: "output.validation_started", payload: { verifier: "default", attempt: 1, retry_count: 0, max_retries: 1 } },
        { sequence: 3, type: "output.validation_failed", payload: { verifier: "default", attempt: 1, retry_count: 0, max_retries: 1, code: "empty_output", message: "输出为空", correction: null, will_retry: false } },
        { sequence: 4, type: "run.failed", payload: { output: null, error: "输出校验未通过", error_code: "output_validation_failed", tool_call_count: 0, input_tokens: 100, output_tokens: 0, cached_tokens: 0, cost_usd: null } },
        terminalFrame("failed", 5),
      ],
    }).route;
    await openThread(page);
    await sendMessage(page, "修复侧栏遮挡");
    await expect(page.getByTestId("thread-run-status")).toHaveText(/失败/, { timeout: 15000 });
    await expect(page.getByTestId("terminal-summary")).toContainText("output_validation_failed");
    await expect(page.getByTestId("transcript-verification")).toContainText("未通过");
  });
});
