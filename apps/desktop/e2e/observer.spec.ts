import { expect, test, type Locator, type Page } from "@playwright/test";
import { prepareCodingFixture } from "./coding-auth-fixture";
import type { ProjectObserverConfig, RunObserverReport } from "../src/features/coding/api/observer";

async function expectWithinWindow(page: Page, panel: Locator) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const box = await panel.boundingBox();
  expect(box).not.toBeNull();
  const width = page.viewportSize()!.width;
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(width);
  expect(await panel.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
}

test("项目验收配置与正式运行诊断在宽窄窗口可用且只导出白名单", async ({ page }, testInfo) => {
  const external: string[] = [];
  const writes: string[] = [];
  const appOrigin = new URL(testInfo.project.use.baseURL as string).origin;
  await page.route("**/*", async route => {
    const origin = new URL(route.request().url()).origin;
    if (origin === appOrigin) return route.continue();
    external.push(origin);
    await route.abort("blockedbyclient");
  });
  await prepareCodingFixture(page);
  await page.addInitScript(() => {
    const surface = window as unknown as { observerCopied: string | null };
    surface.observerCopied = null;
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: {
      writeText: async (value: string) => { surface.observerCopied = value; },
    } });
  });

  const stamp = "2026-09-21T00:00:00Z";
  const runId = "10101010-1010-4010-8010-101010101010";
  const stepId = "20202020-2020-4020-8020-202020202020";
  const executionId = "30303030-3030-4030-8030-303030303030";
  const project = { id: 1, name: "观察器验收项目", root_path: "C:\\fixture\\observer", status: "active", pinned_at: null, updated_at: stamp, created_at: stamp };
  const workspace = { id: 101, project_id: 1, root_path: project.root_path, kind: "root", status: "active", branch_name: null, head_sha: null, last_used_at: stamp };
  const thread = { id: 11, project_id: 1, workspace_id: 101, title: "生成构建报告并核验", kind: "coding", last_run_id: runId, updated_at: stamp, created_at: stamp };
  // 已完成运行保留 v1 快照；编辑项目只更新后续任务的配置。
  let config: ProjectObserverConfig = { version: 1, enabled: true, checks: [{ id: "build-report", kind: "artifact", scope: "dist/previous-report.json" }] };
  let observerReads = 0;
  const report = (): RunObserverReport => ({
    schema_version: "1.0", run_id: runId, status: "completed", goal_outcome: "verified", last_event_sequence: observerReads > 1 ? 3 : 2,
    config_version: 1, counts: { events: observerReads > 1 ? 3 : 2, steps: 1, executions: 1 }, truncated: false,
    progress: { repeated_observations: 0, failure_repeats: 0, verification_retries: 1 }, error: null,
    steps: [{ id: stepId, ordinal: 1, kind: "tool", status: "completed", name: "run_project_command", plan_item_key: "plan-123456abcdef" }],
    checks: [{ id: "build-report", kind: "artifact", status: "passed", reason_code: "evidence_passed", evidence_ids: ["evidence-123456abcdef"] }],
    events: [{ sequence: 2, type: "observer.checks_completed", step_id: stepId, execution_id: executionId, category: "verification" }],
  });
  const run = {
    id: runId, session_id: 11, status: "completed", provider: "fixture", model: "fixture", last_event_sequence: 2,
    tool_call_count: 1, input_tokens: 128, output_tokens: 64, cached_tokens: 0, cost_usd: null,
    output: "构建报告已生成，项目验收检查通过。", error_code: null, error_message: null, cancel_requested_at: null,
    started_at: stamp, completed_at: "2026-09-21T00:00:05Z", created_at: stamp, updated_at: stamp,
    active_in_process: false, steps: [], project_id: 1, workspace_id: 101, base_head_sha: null, base_branch_name: null,
    base_git_dirty: false, model_profile_id: null, reasoning_effort: null, permission_mode: "confirm", plan: null, artifacts: [],
    run_outcome: {
      schema_version: "1.0", run_id: runId, goal_outcome: "verified",
      requirements: [{ requirement_id: "observer-build-report", kind: "artifact", scope: "dist/previous-report.json", description: "产物存在", required: true, origin: "tool", evidence_policy: "disk" }],
      verification_results: [{ requirement_id: "observer-build-report", status: "passed", message: "产物存在", evidence_ids: ["evidence-123456abcdef"] }],
      evidence_ids: ["evidence-123456abcdef"], unverified_items: [],
      evidence_refs: [{ evidence_id: "evidence-123456abcdef", run_id: runId, operation_id: "fixture-operation", source_sequence: 2, content_ref: { bytes: 32, sha256: "a".repeat(64) }, verified_at: stamp, workspace_version: 1 }],
    },
  };
  await page.route("**://127.0.0.1:8000/**", async route => {
    const request = route.request();
    const url = new URL(request.url()), path = url.pathname, method = request.method();
    if (method !== "GET") writes.push(`${method} ${path}`);
    if (path === "/capabilities") return route.fulfill({ json: { coding_agent_ui_enabled: true, agent_runs_api_enabled: true, project_bound_runs_enabled: true, coding_worktree_enabled: false } });
    if (path === "/agent-model-profiles") return route.fulfill({ json: [] });
    if (path === "/projects") return route.fulfill({ json: [project] });
    if (path === "/projects/1") return route.fulfill({ json: project });
    if (path === "/projects/1/workspaces") return route.fulfill({ json: [workspace] });
    if (path === "/projects/1/workspaces/101") return route.fulfill({ json: workspace });
    if (path.endsWith("/git/branches")) return route.fulfill({ json: { is_git: false, current_branch: null, head_sha: null, dirty: false, branches: [] } });
    if (path === "/sessions") return route.fulfill({ json: [thread] });
    if (path.endsWith("/latest-agent-run")) return route.fulfill({ json: { run_id: runId } });
    if (path.endsWith("/messages") || path === "/sessions/recent" || path === "/sessions/search") return route.fulfill({ json: [] });
    if (path.endsWith("/context-budget")) return route.fulfill({ json: {} });
    if (path === "/projects/1/observer-config") {
      if (method === "PUT") {
        const body = request.postDataJSON();
        expect(body).toEqual({ expected_version: 1, enabled: true, checks: [{ id: "build-report", kind: "artifact", scope: "dist/report.json" }] });
        config = { version: 2, enabled: body.enabled, checks: body.checks };
      }
      return route.fulfill({ json: config });
    }
    if (path === `/agent-runs/${runId}/observer`) {
      observerReads++;
      // 模拟后端未来增加字段，验证前端导出仍只包含协议白名单。
      return route.fulfill({ json: { ...report(), output: "fixture-private-body", arguments: { hidden: "fixture-private-arguments" } } });
    }
    if (path === `/agent-runs/${runId}`) return route.fulfill({ json: run });
    if (path === `/agent-runs/${runId}/events`) return route.fulfill({ json: { last_sequence: 2, items: [
      { sequence: 1, type: "run.started", payload: { max_steps: 10, max_tool_calls: 8 } },
      { sequence: 2, type: "run.completed", payload: { output: run.output, run_outcome: run.run_outcome, tool_call_count: 1 } },
    ].filter(item => item.sequence > Number(url.searchParams.get("after_sequence") ?? 0)) } });
    if (path.endsWith("/approvals") || path.endsWith("/executions")) return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { error_code: "test_unhandled", detail: "此测试不支持此接口" } });
  });

  await page.setViewportSize({ width: 1440, height: 950 });
  await page.goto("/app?view=coding");
  await page.getByTestId("coding-project-edit-1").click();
  const editor = page.getByRole("dialog", { name: "编辑项目", exact: true });
  await editor.getByTestId("observer-config-enabled").check();
  await expect(editor.getByTestId("observer-check-id")).toHaveValue("build-report");
  await editor.getByTestId("observer-check-scope").fill("dist/report.json");
  await editor.getByTestId("observer-config-save").click();
  await expect(editor).toContainText("验收检查已保存，仅影响后续新建任务");
  await expect(editor).toContainText("配置 v2");
  await expectWithinWindow(page, editor);
  await page.screenshot({ path: testInfo.outputPath("observer-settings-wide.png"), fullPage: true });
  await editor.getByRole("button", { name: "取消", exact: true }).click();
  await page.setViewportSize({ width: 760, height: 900 });
  await page.getByTestId("coding-drawer-tab").click();
  await page.getByTestId("coding-project-edit-1").click();
  await expect(editor.getByTestId("observer-check-scope")).toHaveValue("dist/report.json");
  await expect(editor).toContainText("配置 v2");
  await expectWithinWindow(page, editor);
  await page.screenshot({ path: testInfo.outputPath("observer-settings-narrow.png"), fullPage: true });
  await editor.getByRole("button", { name: "取消", exact: true }).click();

  await page.setViewportSize({ width: 1440, height: 950 });
  await page.getByTestId("coding-thread-11").click();
  await expect(page.getByTestId("terminal-output")).toContainText("构建报告已生成");
  await expect(page.getByTestId("thread-run-status")).toContainText("已验证完成");
  await page.getByTestId("thread-environment-toggle").click();
  await page.getByRole("tab", { name: "观察诊断", exact: true }).click();
  const panel = page.getByTestId("run-observer-panel");
  await expect(panel).toContainText("已有通过证据");
  await expect(panel).toContainText("检查结论取自上次核验");
  expect(observerReads).toBe(1);
  await panel.getByTestId("observer-refresh").click();
  await expect(panel.locator(".run-observer-meta > div").filter({ hasText: "末事件序号" })).toContainText("3");
  expect(observerReads).toBe(2);
  await panel.getByTestId("observer-copy").click();
  await expect(panel.getByRole("status")).toHaveText("已复制诊断摘要。");
  const copied = await page.evaluate(() => (window as unknown as { observerCopied: string | null }).observerCopied);
  expect(copied).not.toBeNull();
  expect(copied).not.toContain("fixture-private");
  expect(copied).not.toContain(project.root_path);
  expect(JSON.parse(copied!)).toMatchObject({ run_id: runId, config_version: 1, last_event_sequence: 3, checks: [{ id: "build-report", status: "passed" }] });
  await expectWithinWindow(page, page.getByTestId("thread-environment-panel"));
  await page.screenshot({ path: testInfo.outputPath("observer-report-wide.png"), fullPage: true });

  await page.setViewportSize({ width: 760, height: 900 });
  await expect(panel).toBeVisible();
  await expectWithinWindow(page, page.getByTestId("thread-environment-panel"));
  await expectWithinWindow(page, panel);
  await panel.getByText("关联事件 · 1", { exact: true }).click();
  await expect(panel).toContainText(executionId);
  await page.screenshot({ path: testInfo.outputPath("observer-report-narrow.png"), fullPage: true });
  expect(external).toEqual([]);
  expect(writes).toEqual(["PUT /projects/1/observer-config"]);
});
