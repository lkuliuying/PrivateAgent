import { expect, test } from "@playwright/test";
import { prepareCodingFixture } from "./coding-auth-fixture";

test("输出阶段、文件引用和产物在宽窄窗口安全交付", async ({ page }, testInfo) => {
  const external: string[] = [];
  const reads: string[] = [];
  const writes: string[] = [];
  const origin = new URL(testInfo.project.use.baseURL as string).origin;
  await page.route("**/*", async route => {
    if (new URL(route.request().url()).origin === origin) return route.continue();
    external.push(route.request().url());
    return route.abort("blockedbyclient");
  });
  await prepareCodingFixture(page);
  await page.addInitScript(() => {
    const surface = window as unknown as { outputCopied?: string };
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: {
      writeText: async (value: string) => { surface.outputCopied = value; },
    } });
  });

  const stamp = "2026-09-21T00:00:00Z";
  const runId = "10101010-1010-4010-8010-101010101011";
  const project = { id: 1, name: "输出交付验收", root_path: "F:\\Fixture Output", status: "active", updated_at: stamp, created_at: stamp };
  const workspace = { id: 101, project_id: 1, root_path: project.root_path, kind: "root", status: "active", branch_name: null, head_sha: null, last_used_at: stamp };
  const thread = { id: 11, project_id: 1, workspace_id: 101, title: "交付脚本与说明", kind: "coding", last_run_id: runId, updated_at: stamp, created_at: stamp };
  const output = "## 输出验收完成\n\n[查看源码](src/app.py:2) · [越界引用](</F:/Outside/account.txt:1>)\n\n```python\nprint('交付完成')\n```";
  const frames = [
    { sequence: 1, type: "run.started", payload: { max_steps: 10, max_tool_calls: 8 } },
    { sequence: 2, type: "model.output.delta", payload: { attempt_id: "public-output", message_id: "progress", phase: "commentary", delta: "已检查脚本，正在准备文件交付。" } },
    { sequence: 3, type: "model.output.delta", payload: { attempt_id: "public-output", message_id: "answer", phase: "final_answer", delta: output } },
    { sequence: 4, type: "model.output.finished", payload: { attempt_id: "public-output", has_tool_calls: false, messages: [
      { message_id: "progress", phase: "commentary", truncated: false },
      { message_id: "answer", phase: "final_answer", truncated: false },
    ] } },
    { sequence: 5, type: "run.completed", payload: { output, tool_call_count: 1, final_output_attempt_id: "public-output", structured_output: null } },
  ];
  const run = {
    id: runId, session_id: 11, status: "completed", provider: "fixture", model: "fixture", last_event_sequence: 5,
    tool_call_count: 1, input_tokens: 128, output_tokens: 64, cached_tokens: 0, cost_usd: null,
    output, final_output_attempt_id: "public-output", structured_output: null, error_code: null, error_message: null, cancel_requested_at: null, started_at: stamp,
    completed_at: "2026-09-21T00:00:05Z", created_at: stamp, updated_at: stamp, active_in_process: false,
    steps: [], project_id: 1, workspace_id: 101, base_head_sha: null, base_branch_name: null,
    base_git_dirty: false, model_profile_id: null, reasoning_effort: null, permission_mode: "confirm", plan: null,
    artifacts: [{ id: "report", kind: "file", title: "交付说明", rel_path: "docs/report.md" }],
  };
  await page.route("**://127.0.0.1:8000/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (request.method() !== "GET") writes.push(`${request.method()} ${path}`);
    if (path === "/capabilities") return route.fulfill({ json: { coding_agent_ui_enabled: true, agent_runs_api_enabled: true, project_bound_runs_enabled: true, coding_worktree_enabled: false } });
    if (path === "/agent-model-profiles") return route.fulfill({ json: [] });
    if (path === "/projects") return route.fulfill({ json: [project] });
    if (path === "/projects/1") return route.fulfill({ json: project });
    if (path === "/projects/1/workspaces") return route.fulfill({ json: [workspace] });
    if (path === "/projects/1/workspaces/101") return route.fulfill({ json: workspace });
    if (path === "/projects/1/workspaces/101/files") return route.fulfill({ json: { entries: [], next_cursor: null, total: 0 } });
    if (path === "/projects/1/workspaces/101/file") {
      const relative = url.searchParams.get("path") ?? "";
      reads.push(relative);
      const content = relative === "src/app.py" ? "def deliver():\n    return '交付完成'\n" : "# 交付说明\n\n检查结果与使用方式。";
      return route.fulfill({ json: { rel_path: relative, content, sha256: "a".repeat(64), offset: 0, next_offset: null, total_chars: content.length } });
    }
    if (path.endsWith("/git/branches")) return route.fulfill({ json: { is_git: false, current_branch: null, head_sha: null, dirty: false, branches: [] } });
    if (path === "/sessions") return route.fulfill({ json: [thread] });
    if (path.endsWith("/latest-agent-run")) return route.fulfill({ json: { run_id: runId } });
    if (path.endsWith("/messages") || path === "/sessions/recent" || path === "/sessions/search") return route.fulfill({ json: [] });
    if (path.endsWith("/context-budget")) return route.fulfill({ json: {} });
    if (path === `/agent-runs/${runId}`) return route.fulfill({ json: run });
    if (path === `/agent-runs/${runId}/events`) return route.fulfill({ json: { last_sequence: 5, items: frames.filter(frame => frame.sequence > Number(url.searchParams.get("after_sequence") ?? 0)) } });
    if (path.endsWith("/approvals") || path.endsWith("/executions")) return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { error_code: "test_unhandled", detail: "此测试不支持此接口" } });
  });

  await page.setViewportSize({ width: 1440, height: 950 });
  await page.goto("/app?view=coding");
  await page.getByTestId("coding-thread-11").click();
  const result = page.getByTestId("terminal-output");
  await expect(result.getByRole("heading", { name: "输出验收完成" })).toHaveCount(1);
  await page.getByTestId("run-duration-toggle").click();
  await expect(page.getByTestId("model-public-output")).toContainText("正在准备文件交付");
  await expect(page.getByRole("heading", { name: "输出验收完成" })).toHaveCount(1);
  await result.getByRole("button", { name: "复制代码", exact: true }).click();
  expect(await page.evaluate(() => (window as unknown as { outputCopied?: string }).outputCopied)).toBe("print('交付完成')");

  await result.getByRole("button", { name: "查看源码", exact: true }).click();
  const files = page.getByTestId("file-workspace");
  await expect(files.getByLabel("第 2 行", { exact: true })).toContainText("return '交付完成'");
  await expect(files.locator(".file-preview > header")).toContainText("src/app.py:2");
  await page.screenshot({ path: testInfo.outputPath("output-files-wide.png"), fullPage: true });
  await files.getByRole("button", { name: "关闭文件工作区", exact: true }).click();

  await result.getByRole("button", { name: "查看产物 交付说明", exact: true }).click();
  await expect(files.getByRole("tab", { name: "report.md", exact: true })).toBeVisible();
  await expect(files.locator("pre")).toContainText("检查结果与使用方式");
  await page.setViewportSize({ width: 760, height: 900 });
  await expect(files).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("output-files-narrow.png"), fullPage: true });
  await files.getByRole("button", { name: "关闭文件工作区", exact: true }).click();
  await result.getByRole("button", { name: "越界引用", exact: true }).click();
  await expect(page.getByText("文件引用无效或位于此任务工作区之外。", { exact: true })).toBeVisible();
  await expect(files).toHaveCount(0);
  expect(reads).toEqual(["src/app.py", "docs/report.md"]);
  expect(writes).toEqual([]);
  expect(external).toEqual([]);
});
