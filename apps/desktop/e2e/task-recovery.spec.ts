import { expect, test, type Page } from "@playwright/test";
import { prepareCodingFixture } from "./coding-auth-fixture";
import { prepareRedesignFixture } from "./redesign-fixture";

/**
 * 任务恢复界面：中断现场的核对、模型交接与本轮补丁入口。
 * 全部数据来自浏览器内路由夹具，不连接真实执行器、模型供应商或个人数据目录。
 */
const RUN = "run-recovery-1";
const STAMP = "2026-10-21T12:00:00Z";
const caps = { coding_agent_ui_enabled: true, agent_runs_api_enabled: true, project_bound_runs_enabled: true,
  coding_worktree_enabled: true, coding_context_budget_enabled: true, coding_patchsets_enabled: true,
  coding_execution_sessions_enabled: true, coding_recovery_contract_version: "1.0",
  coding_recovery_reconcile_enabled: true, coding_recovery_model_handoff_enabled: true, coding_recovery_timing_enabled: true };
const profiles = [
  { id: "fixture-model", display_name: "示例模型", model_name: "deepseek-flash", provider_id: "fixture", provider: "openai",
    provider_name: "示例供应商", enabled: true, is_default: true, is_local: false, native_tool_calls: true, supports_streaming: true,
    supports_vision: true, supports_structured_output: true, context_tokens: 128000, reasoning_efforts: ["low", "medium", "high"] },
  { id: "fixture-alt", display_name: "备用模型", model_name: "deepseek-reasoner", provider_id: "fixture", provider: "openai",
    provider_name: "示例供应商", enabled: true, is_default: false, is_local: false, native_tool_calls: true, supports_streaming: true,
    supports_vision: true, supports_structured_output: true, context_tokens: 256000, reasoning_efforts: null },
];
const snapshot = {
  id: RUN, session_id: 11, trace_id: "trace-recovery", status: "interrupted", provider: "openai", model: "deepseek-flash",
  last_event_sequence: 4, tool_call_count: 2, input_tokens: 1200, output_tokens: 80, cached_tokens: 0, cost_usd: null,
  output: null, error_code: "desktop_restarted", error_message: "本机执行服务已重启；未自动重放操作，请检查项目后重试",
  cancel_requested_at: null, started_at: STAMP, completed_at: STAMP, created_at: STAMP, updated_at: STAMP,
  active_in_process: false, steps: [], project_id: 1, workspace_id: 101, base_head_sha: "a".repeat(40), base_branch_name: "main",
  base_git_dirty: false, model_profile_id: "fixture-model", reasoning_effort: null, permission_mode: "confirm", plan: null, artifacts: [],
};
const report = {
  run_id: RUN, supported: true, status: "interrupted", state_version: 7, checkpoint_id: "checkpoint-7",
  logical_task_id: RUN, resumed_from_run_id: null, goal_version: 1, model_profile_id: "fixture-model",
  can_resume: false, recovery_class: "manual_resume", resumable_error: null,
  blockers: ["MCP 写入结果未知，请先核对远端结果：exec-mcp"],
  blocker_details: [{
    item_id: "mcp-item", kind: "mcp_write", label: "MCP 写入结果未知，请先核对远端结果：exec-mcp", status: "open", source: "machine",
    actions: ["externally_confirmed", "externally_failed"], resolvable: true,
    reason: "系统无法验证远端结果；人工说明只解除续跑阻塞，不产生成功证据，也不会重发请求",
    target: { execution_id: "exec-mcp", tool: "write_file", source_id: "docs" },
  }],
  open_items: ["mcp-item"], resolutions: [], controls: [], executions: [],
  budget: { model_requests: 3, max_model_requests: 24, tool_calls: 2, max_tool_calls: 40, active_seconds: 42, max_active_seconds: 3600 },
  timing: { format_version: "1.0", confirmed_active_seconds: 42, unconfirmed_tail: true, source: "restart" },
  time_policy: "confirmed_only", queue_reason: null, queue_position: null, expired_approvals: [], limitations: [],
};
const preview = {
  format_version: "1.0", run_id: RUN, checkpoint_id: "checkpoint-7", state_version: 7,
  source: { model_profile_id: "fixture-model", model_name: "deepseek-flash", provider: "openai", api_format: "chat_completions",
    endpoint: "https://example.com/v1", context_tokens: 128000, native_tool_calls: true, supports_vision: true,
    supports_structured_output: true, configuration_version: "config-a", capability_version: "cap-a" },
  target: { model_profile_id: "fixture-alt", model_name: "deepseek-reasoner", provider: "openai", api_format: "chat_completions",
    endpoint: "https://example.com/v1", context_tokens: 256000, native_tool_calls: true, supports_vision: true,
    supports_structured_output: true, configuration_version: "config-b", capability_version: "cap-b" },
  switched: true, capability_gaps: [], blockers: report.blockers, preview_sha256: "preview-sha", eligible: true, can_resume: false,
  recovery_class: "manual_resume", requires_model_change_acceptance: true, requires_timing_acceptance: true,
  budget_note: "沿用原逻辑任务的累计用量、失败记录与上限；切换模型不清零、不扩额", limitations: [],
};

async function recoveryFixture(page: Page) {
  const state = await prepareRedesignFixture(page);
  await page.addInitScript(() => localStorage.setItem("pa_last_view", "coding"));
  const calls: { path: string; body?: Record<string, unknown> }[] = [];
  await page.route("**://127.0.0.1:8000/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    if (path === "/capabilities") return route.fulfill({ json: caps });
    if (path === "/sessions" || path === "/sessions/recent") return route.fulfill({ json: [{ id: 11, project_id: 1, workspace_id: 101,
      title: "优化页面布局", kind: "coding", last_run_id: RUN, updated_at: STAMP, created_at: STAMP, archived_at: null }] });
    if (path === "/sessions/11") return route.fulfill({ json: { id: 11, project_id: 1, workspace_id: 101, title: "优化页面布局",
      kind: "coding", last_run_id: RUN, updated_at: STAMP, created_at: STAMP, archived_at: null } });
    if (path === "/agent-model-profiles") return route.fulfill({ json: profiles });
    if (path === "/sessions/11/latest-agent-run") return route.fulfill({ json: { run_id: RUN } });
    if (path === `/agent-runs/${RUN}`) return route.fulfill({ json: snapshot });
    if (path === `/agent-runs/${RUN}/events`) return route.fulfill({ json: { items: [], last_sequence: 4 } });
    if (path.startsWith(`/agent-runs/${RUN}/events/stream`)) return route.fulfill({ contentType: "text/event-stream; charset=utf-8", body: ": heartbeat\n\n" });
    if (path === `/agent-runs/${RUN}/approvals`) return route.fulfill({ json: [] });
    if (path === `/agent-runs/${RUN}/executions`) return route.fulfill({ json: [] });
    if (path === `/agent-runs/${RUN}/patches`) return route.fulfill({ json: { patch_sets: [] } });
    if (path === `/agent-runs/${RUN}/review`) return route.fulfill({ json: { task_changes: [], preexisting_changes: [], external_or_unattributed: [],
      command_candidates: [], snapshot_complete: true, limitations: ["只核对已提交日志；同一时刻的外部编辑可能无法归属。"] } });
    if (path === `/agent-runs/${RUN}/recovery` && method === "GET") return route.fulfill({ json: report });
    if (path === `/agent-runs/${RUN}/recovery/reconcile` && method === "POST") {
      calls.push({ path, body: request.postDataJSON() as Record<string, unknown> });
      return route.fulfill({ status: 202, json: { request_id: "reconcile-1", kind: "reconcile", status: "applied", result_run_id: RUN,
        item_id: "mcp-item", source: "user_statement", verified: false, note: "远端已出现目标文件" } });
    }
    if (path === `/agent-runs/${RUN}/resume/preview` && method === "POST") {
      calls.push({ path, body: request.postDataJSON() as Record<string, unknown> });
      return route.fulfill({ json: preview });
    }
    if (path === `/agent-runs/${RUN}/resume` && method === "POST") {
      calls.push({ path, body: request.postDataJSON() as Record<string, unknown> });
      return route.fulfill({ json: { request_id: "resume-1", kind: "resume", status: "applied", result_run_id: "run-child", model_switched: true } });
    }
    if (path === "/sessions/11/review") return route.fulfill({ json: { scope: "task", runs: [{ id: RUN, status: "interrupted", created_at: STAMP,
      workspace_id: 101, outcome: null, patch_count: 0, resumed_from_run_id: null, logical_task_id: RUN, ancestor_count: 0,
      error_code: "desktop_restarted", error_message: "本机执行服务已重启", recovery_class: "manual_resume", resolution_count: 1,
      model_switch: true, model_switch_from: "deepseek-flash", model_switch_to: "deepseek-reasoner", patch_status: [], rollback_available: false }],
      workspace: { is_git: true, entries: [], next_cursor: null } } });
    return route.fallback();
  });
  return { state, calls };
}

async function openRecovery(page: Page) {
  await page.goto("/app");
  // 项目树里的会话行进入编码工作台；测试环境按标题定位，避免依赖固定 id 的可见性。
  await page.getByText("优化页面布局").first().click();
  await expect(page.getByTestId("coding-composer-input")).toBeEnabled();
  await page.getByTestId("thread-menu-toggle").click();
  await page.getByRole("menuitem", { name: "恢复现场详情", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "环境与变更" })).toBeVisible();
  await expect(page.locator(".recovery-panel")).toContainText("MCP 写入结果未知");
}

test("中断现场展示计时说明、结构化阻塞与人工核对入口", async ({ page }) => {
  const { state, calls } = await recoveryFixture(page);
  await openRecovery(page);
  await expect(page.locator(".recovery-panel")).toContainText("末段耗时未确认");
  await expect(page.locator(".recovery-panel")).toContainText("系统无法验证远端结果");
  await page.locator(".recovery-panel textarea").fill("远端已出现目标文件");
  await page.locator(".recovery-panel").getByRole("button", { name: "已核对完成", exact: true }).click();
  await expect.poll(() => calls.filter(item => item.path.endsWith("/recovery/reconcile")).length).toBe(1);
  const body = calls.find(item => item.path.endsWith("/recovery/reconcile"))!.body!;
  expect(body.item_id).toBe("mcp-item");
  expect(body.decision).toBe("externally_confirmed");
  expect(body.note).toBe("远端已出现目标文件");
  expect(body.checkpoint_id).toBe("checkpoint-7");
  expect(body.expected_state_version).toBe(7);
  expect(state.writes.some(write => write.includes("/resume"))).toBe(false);
  expect(state.unknownRequests).toEqual([]);
});

test("选择模型后继续先取只读预览，再提交摘要与显式接受", async ({ page }) => {
  const { state, calls } = await recoveryFixture(page);
  await openRecovery(page);
  await page.locator(".recovery-panel select").selectOption("fixture-alt");
  await page.locator(".recovery-panel").getByRole("button", { name: "预览差异", exact: true }).click();
  await expect(page.locator(".recovery-panel")).toContainText("deepseek-reasoner");
  await expect(page.locator(".recovery-panel")).toContainText("沿用原逻辑任务");
  expect(calls.find(item => item.path.endsWith("/resume/preview"))!.body).toMatchObject({ model_profile_id: "fixture-alt", checkpoint_id: "checkpoint-7" });
  await page.locator(".recovery-panel").getByLabel("我了解末段耗时未确认").check();
  await page.locator(".recovery-panel").getByRole("button", { name: "用目标模型继续", exact: true }).click();
  await expect.poll(() => calls.filter(item => item.path.endsWith("/resume") && !item.path.endsWith("/preview")).length).toBe(1);
  const body = calls.find(item => item.path.endsWith("/resume") && !item.path.endsWith("/preview"))!.body!;
  expect(body.model_profile_id).toBe("fixture-alt");
  expect(body.preview_sha256).toBe("preview-sha");
  expect(body.accept_model_change).toBe(true);
  expect(body.accept_unconfirmed_timing).toBe(true);
  // 续跑成功后界面会转向关联的新运行；只允许该新运行的读取请求，其他接口仍需夹具覆盖。
  expect(state.unknownRequests.filter(path => !path.startsWith("/agent-runs/run-child"))).toEqual([]);
});

test("按轮次查阅标注续跑链与人工核对来源", async ({ page }) => {
  await recoveryFixture(page);
  await openRecovery(page);
  await page.locator(".recovery-panel").getByText("查看本轮修改与变更归属", { exact: true }).click();
  await expect(page.locator(".recovery-panel")).toContainText("只核对已提交日志");
  await page.getByTestId("thread-environment-panel").getByRole("button", { name: "关闭环境面板" }).click();
  await page.getByTestId("thread-environment-toggle").click();
  await page.getByRole("tab", { name: "变更", exact: true }).click();
  await expect(page.locator(".task-review")).toContainText("模型切换 · deepseek-flash → deepseek-reasoner");
  await expect(page.locator(".task-review")).toContainText("人工核对 1 项");
});

async function narrowLayout(page: Page) {
  const panel = page.getByTestId("thread-environment-panel");
  await expect(panel).toBeVisible();
  // 面板必须占据整个窄视口，不能只拿到侧栏剩下的宽度。
  const box = (await panel.boundingBox())!;
  expect(box.x).toBeLessThanOrEqual(1);
  expect(box.width).toBeGreaterThanOrEqual(389);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  // 关键控件的边界、完整文本与内层裁切都要核对，不能只看根节点无滚动。
  for (const name of ["刷新现场", "保留当前代码并继续", "已核对完成"]) {
    const button = page.locator(".recovery-panel").getByRole("button", { name, exact: true });
    await expect(button).toBeVisible();
    const rect = (await button.boundingBox())!;
    expect(rect.x).toBeGreaterThanOrEqual(0);
    expect(rect.x + rect.width).toBeLessThanOrEqual(391);
    expect(rect.height).toBeGreaterThanOrEqual(30);
    expect(await button.evaluate(node => node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1)).toBe(false);
  }
  const note = page.locator(".recovery-panel textarea").first();
  const noteBox = (await note.boundingBox())!;
  expect(noteBox.x + noteBox.width).toBeLessThanOrEqual(391);
  const clipped = await page.evaluate(() => {
    const body = document.querySelector(".environment-body")!;
    const recovery = document.querySelector(".recovery-panel")!;
    return [body.scrollWidth - body.clientWidth, recovery.scrollWidth - recovery.clientWidth];
  });
  expect(clipped[0]).toBeLessThanOrEqual(1);
  expect(clipped[1]).toBeLessThanOrEqual(1);
  await page.screenshot({ path: "test-results/narrow-recovery.png" });
  // 窄窗口下仍要能提交核对，而不是仅仅“看起来存在”。
  await note.fill("窄窗口核对：远端已出现目标文件");
  await page.locator(".recovery-panel").getByRole("button", { name: "已核对完成", exact: true }).click();
}

test("窄窗口下从宽到窄仍完整可读可操作", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const { calls } = await recoveryFixture(page);
  await openRecovery(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await narrowLayout(page);
  await expect.poll(() => calls.filter(item => item.path.endsWith("/recovery/reconcile")).length).toBe(1);
  expect(calls.find(item => item.path.endsWith("/recovery/reconcile"))!.body!.note).toBe("窄窗口核对：远端已出现目标文件");
});

test("直接以 390px 进入恢复现场同样完整可读可操作", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { calls } = await recoveryFixture(page);
  // 窄窗口直接进入：先恢复编码视图，再从抽屉式侧栏选择会话。
  await page.addInitScript(() => window.localStorage.setItem("pa_last_view", "coding"));
  await page.goto("/app");
  await page.getByTestId("coding-drawer-tab").click();
  await page.getByText("优化页面布局").first().click();
  await expect(page.getByTestId("coding-composer-input")).toBeEnabled();
  await page.getByTestId("thread-menu-toggle").click();
  await page.getByRole("menuitem", { name: "恢复现场详情", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "环境与变更" })).toBeVisible();
  await narrowLayout(page);
  await expect.poll(() => calls.filter(item => item.path.endsWith("/recovery/reconcile")).length).toBe(1);
});






