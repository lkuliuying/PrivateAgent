import { expect, test } from "@playwright/test";
import { prepareCodingFixture } from "./coding-auth-fixture";

test("输出收起与展开对齐参考布局，文件摘要及审核保持独立", async ({ page }, testInfo) => {
  const writes: string[] = [];
  const external: string[] = [];
  const origin = new URL(testInfo.project.use.baseURL as string).origin;
  await page.route("**/*", route => {
    if (new URL(route.request().url()).origin === origin) return route.continue();
    external.push(route.request().url());
    return route.abort("blockedbyclient");
  });
  await prepareCodingFixture(page);
  const stamp = "2026-09-21T00:00:00Z";
  const runId = "10101010-1010-4010-8010-101010101021";
  const project = { id: 1, name: "输出布局检查", root_path: "F:\\Fixture Layout", status: "active", updated_at: stamp, created_at: stamp };
  const workspace = { id: 101, project_id: 1, root_path: project.root_path, kind: "root", status: "active", branch_name: "main", head_sha: null, last_used_at: stamp };
  const thread = { id: 11, project_id: 1, workspace_id: 101, title: "核对文件与交付结果", kind: "coding", last_run_id: runId, updated_at: stamp, created_at: stamp };
  const output = ["## 任务总结", "**文件写入和回读均通过。** 内容为 `QA_FILE_OK`，末尾换行和文件摘要一致。",
    "## 变更文件", "更新了测试记录，新增补验脚本和证据。", "## 验证结果",
    "- 文件存在时停止，没有重复写入。\n- 普通问答正确返回结果。\n- 相关组件与构建检查通过。",
    "## 项目记忆", "已读取项目说明，按当前源码核对，保留已有历史。", "## 风险、限制与假设",
    "本页使用隔离场景验证展示，不代表真实模型验收。", "## 用户需执行的操作", "无需额外操作。"].join("\n\n");
  const outcome = { schema_version: "1.0", run_id: runId, goal_outcome: "verified",
    requirements: [{ requirement_id: "files", kind: "file_changed", description: "修改文件并回读", required: true }],
    verification_results: [{ requirement_id: "files", status: "passed", evidence_ids: ["patch"] }],
    evidence_ids: ["patch"], unverified_items: [] };
  const frames = [
    { sequence: 1, type: "run.started", payload: {} },
    { sequence: 2, type: "model.output.delta", payload: { attempt_id: "a", phase: "commentary", delta: "我会核对文件字节和任务记录，再整理验证结果。" } },
    { sequence: 3, type: "model.output.finished", payload: { attempt_id: "a", has_tool_calls: true } },
    { sequence: 4, type: "decision.summary", payload: { goal: "核对", method: "我会核对文件字节和任务记录，再整理验证结果。" } },
    { sequence: 5, type: "tool.completed", payload: { tool_call_id: "read", name: "read_code_file" } },
    { sequence: 6, type: "model.output.delta", payload: { attempt_id: "b", phase: "commentary", delta: "文件内容与回读一致，接下来核对测试输出。" } },
    { sequence: 7, type: "model.output.finished", payload: { attempt_id: "b", has_tool_calls: true } },
    { sequence: 8, type: "context.compaction_completed", payload: { checkpoint_id: "compact" } },
    { sequence: 9, type: "tool.completed", payload: { tool_call_id: "edit", name: "write_project_file" } },
    { sequence: 10, type: "model.output.delta", payload: { attempt_id: "final", phase: "final_answer", delta: output } },
    { sequence: 11, type: "model.output.finished", payload: { attempt_id: "final", has_tool_calls: false } },
    { sequence: 12, type: "run.completed", payload: { output, tool_call_count: 2, final_output_attempt_id: "final", run_outcome: outcome } },
  ];
  const run = { id: runId, session_id: 11, status: "completed", provider: "fixture", model: "fixture", last_event_sequence: 12,
    tool_call_count: 2, input_tokens: 128, output_tokens: 64, cached_tokens: 0, cost_usd: null, output, run_outcome: outcome,
    final_output_attempt_id: "final", structured_output: null, error_code: null, error_message: null, cancel_requested_at: null,
    started_at: stamp, completed_at: "2026-09-21T00:17:33Z", created_at: stamp, updated_at: stamp, active_in_process: false,
    steps: [], project_id: 1, workspace_id: 101, base_head_sha: null, base_branch_name: null, base_git_dirty: false,
    model_profile_id: null, reasoning_effort: null, permission_mode: "confirm", plan: null, artifacts: [] };
  const changes = ["scripts/verify_file.py", "docs/test-report.md", "src/components/RunTranscript.vue", "src/components/long-path/another-component/extra-file.spec.ts"]
    .map((rel_path, index) => ({ change_id: `file-${index}`, rel_path, operation: "update", before_kind: "file", after_kind: "file", diff_chars: 120, additions: [110, 25, 93, 69][index], deletions: index === 1 ? 13 : 0 }));
  const patch = { patch_set_id: "patch", run_id: runId, preview_sha256: "a".repeat(64), status: "applied", kind: "patch", changes, conflicts: [],
    journal: changes.map(change => ({ change_id: change.change_id, rel_path: change.rel_path, status: "applied" })) };
  await page.route("**://127.0.0.1:8000/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (request.method() !== "GET") writes.push(`${request.method()} ${path}`);
    if (path === "/capabilities") return route.fulfill({ json: { coding_agent_ui_enabled: true, agent_runs_api_enabled: true, project_bound_runs_enabled: true, coding_patchsets_enabled: true, coding_worktree_enabled: false } });
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
    if (path === `/agent-runs/${runId}`) return route.fulfill({ json: run });
    if (path === `/agent-runs/${runId}/events`) return route.fulfill({ json: { last_sequence: 12, items: frames.filter(frame => frame.sequence > Number(url.searchParams.get("after_sequence") ?? 0)) } });
    if (path.endsWith("/approvals") || path.endsWith("/executions")) return route.fulfill({ json: [] });
    if (path.endsWith("/patches")) return route.fulfill({ json: { patches: [patch], baseline: null, current_git: { is_git: false, head_sha: null, current_branch: null, dirty: false }, ownership_note: "本任务操作记录，不包含其他来源文件" } });
    return route.fulfill({ status: 404, json: { error_code: "test_unhandled", detail: "此场景不支持此接口" } });
  });
  await page.setViewportSize({ width: 1440, height: 1760 });
  await page.goto("/app?view=coding");
  await page.getByTestId("coding-thread-11").click();
  await page.mouse.move(1380, 80);
  await expect(page.getByTestId("coding-thread-details-11")).toBeHidden();
  const toggle = page.getByTestId("run-duration-toggle");
  const result = page.getByTestId("terminal-output");
  const card = result.getByTestId("result-patch-card");
  const captureOutput = async (name: string) => {
    await page.locator(".transcript-scroll").evaluate(element => { element.scrollTop = 0; });
    await expect(result.getByRole("button", { name: "复制 Markdown", exact: true })).toBeInViewport();
    const top = await toggle.boundingBox();
    const bottom = await result.boundingBox();
    if (!top || !bottom) throw new Error("输出区域未显示");
    await page.screenshot({ path: testInfo.outputPath(name), clip: {
      x: top.x - 12, y: top.y - 12, width: bottom.width + 24, height: bottom.y + bottom.height - top.y + 24,
    } });
  };
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(toggle).toContainText("用时 17 分钟 33 秒");
  await expect(card).toContainText("已编辑 4 个文件");
  await expect(card.locator("header .stat-add")).toHaveText("+297");
  await expect(card.locator("header .stat-del")).toHaveText("-13");
  await expect(card.getByTestId("result-file-row")).toHaveCount(3);
  await expect(page.getByTestId("model-public-output").first()).toBeHidden();
  await expect(page.getByTestId("terminal-attention")).toHaveCount(0);
  await captureOutput("output-collapsed.png");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("model-public-output")).toHaveCount(2);
  await expect(page.getByTestId("transcript-context-compaction")).toHaveText("上下文已压缩");
  await expect(page.getByRole("heading", { name: "任务总结", exact: true })).toHaveCount(1);
  await expect(page.locator(".tool-disclosure[open]")).toHaveCount(0);
  await captureOutput("output-expanded.png");
  await toggle.click();
  await card.getByRole("button", { name: "再显示 1 个文件", exact: true }).click();
  await expect(card.getByTestId("result-file-row")).toHaveCount(4);
  await card.getByRole("button", { name: "审核", exact: true }).click();
  await expect(card.locator("details.patch-review")).toHaveAttribute("open", "");
  await card.getByRole("button", { name: "审核", exact: true }).click();
  await page.setViewportSize({ width: 620, height: 1000 });
  await expect(card).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(await result.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  await card.screenshot({ path: testInfo.outputPath("output-files-narrow.png") });
  await card.getByRole("button", { name: "收起文件列表", exact: true }).click();
  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Space");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(writes).toEqual([]);
  expect(external).toEqual([]);
});
