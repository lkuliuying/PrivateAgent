import { test, expect } from "@playwright/test";
import { prepareRedesignFixture, settleDesign } from "./redesign-fixture";

test.use({ reducedMotion: "reduce" });

for (const [width, height, scale] of [[1280, 720, 1], [1440, 900, 1], [1920, 1080, 1], [1280, 720, 1.25], [1440, 900, 1.5], [390, 844, 1]]) {
  test.describe("紧凑首页 " + width + "@" + scale, () => {
    test.use({ viewport: { width, height }, deviceScaleFactor: scale });
    test("输入与主要操作可见且无横向溢出", async ({ page }, info) => {
      const state = await prepareRedesignFixture(page);
      await page.addInitScript(() => localStorage.setItem("pa_home_layout_v1", "compact"));
      await page.goto("/#/app");
      await expect(page.getByTestId("home-compact")).toBeVisible();
      await expect(page.getByTestId("home-hero")).toHaveCount(0);
      const input = page.getByTestId("coding-composer-input");
      await input.fill("紧凑模式保留输入");
      await settleDesign(page);
      await expect(input).toBeInViewport();
      await expect(page.getByTestId("coding-composer-send")).toBeInViewport();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: info.outputPath("compact-" + width + "-" + scale + ".png"), animations: "disabled" });
      expect(state.unknownRequests).toEqual([]);
      expect(state.writes).toEqual([]);
      expect(state.browserErrors).toEqual([]);
    });
  });
}


test("首页携带附件首发：失败保留，响应丢失按同一请求核对，确认后保留历史", async ({ page }) => {
  const state = await prepareRedesignFixture(page);
  const stamp = "2026-09-22T02:00:00Z";
  const item = { id: "a".repeat(32), name: "参考材料.txt", size_bytes: 18, sha256: "b".repeat(64), language: "txt", project_id: 1, workspace_id: 101 };
  const draftId = "c".repeat(32);
  const text = "根据附件解释项目";
  const thread = { id: 99, project_id: 1, workspace_id: 101, title: text, kind: "coding", last_run_id: null as string | null, updated_at: stamp, created_at: stamp };
  const run = { id: "fixture-attachment-run", session_id: 99, status: "completed", provider: "fixture", model: "fixture",
    last_event_sequence: 0, tool_call_count: 0, input_tokens: 0, output_tokens: 0, cached_tokens: 0, cost_usd: null,
    output: "已收到材料", error_code: null, error_message: null, cancel_requested_at: null, started_at: stamp, completed_at: stamp,
    created_at: stamp, updated_at: stamp, active_in_process: false, steps: [], project_id: 1, workspace_id: 101,
    base_head_sha: null, base_branch_name: "main", base_git_dirty: false, model_profile_id: "fixture-model",
    reasoning_effort: null, permission_mode: "confirm", plan: null, artifacts: [] };
  const creates: Record<string, unknown>[] = [];
  const checks: string[] = [];
  let sessions = 0;
  let accepted = false;
  await page.addInitScript(data => localStorage.setItem("pa_coding_draft_v2_1_101_new", JSON.stringify(data)),
    { text, chips: [], attachments: [item], draftId });
  await page.route("**://127.0.0.1:8000/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    if (path === "/sessions" && request.method() === "POST") { sessions++; return route.fulfill({ status: 201, json: thread }); }
    if (path === "/task-attachments") return route.fulfill({ json: accepted ? [] : [item] });
    if (path === "/sessions/99") return route.fulfill({ json: thread });
    if (path === "/sessions/99/latest-agent-run") return route.fulfill({ json: { run_id: thread.last_run_id } });
    if (path === "/sessions/99/messages") return route.fulfill({ json: accepted ? [
      { id: 901, session_id: 99, role: "user", content: text, attachments: [item], created_at: stamp },
      { id: 902, session_id: 99, role: "assistant", content: "已收到材料", created_at: stamp },
    ] : [] });
    if (path === "/agent-runs" && request.method() === "POST") {
      creates.push(request.postDataJSON());
      if (creates.length > 1) { accepted = true; thread.last_run_id = run.id; }
      return route.fulfill({ status: 503, json: { error_code: "connection_lost", detail: "本次未收到创建响应" } });
    }
    if (path.startsWith("/agent-runs/by-request/")) {
      checks.push(path.split("/").pop()!);
      return route.fulfill({ status: accepted ? 200 : 404, json: accepted
        ? { ...run, submitted_message: text, attachment_ids: [item.id] } : { detail: "尚未确认" } });
    }
    if (path === "/agent-runs/" + run.id) return route.fulfill({ json: run });
    if (path === "/agent-runs/" + run.id + "/recovery") return route.fulfill({ json: { run_id: run.id, status: "completed", state_version: 1, checkpoint_id: null, logical_task_id: run.id, resumed_from_run_id: null, can_resume: false, blockers: [], controls: [], executions: [], budget: {}, expired_approvals: [], limitations: [] } });
    if (path === "/agent-runs/" + run.id + "/approvals" || path === "/agent-runs/" + run.id + "/executions") return route.fulfill({ json: [] });
    return route.fallback();
  });
  await page.goto("/#/app");
  const input = page.getByTestId("coding-composer-input");
  await expect(input).toHaveValue(text);
  await page.getByTestId("coding-composer-send").click();
  await expect.poll(() => creates.length).toBe(1);
  await expect(input).toBeEnabled();
  await expect(input).toHaveValue(text);
  await expect(page.locator(".coding-composer .task-attachment")).toContainText(item.name);
  expect(creates[0]).toMatchObject({ message: text, attachment_ids: [item.id], attachment_draft_id: draftId, session_id: 99 });
  await page.getByTestId("coding-composer-send").click();
  await expect.poll(() => creates.length).toBe(2);
  await expect(input).toHaveValue("");
  expect(creates[1].client_request_id).toBe(creates[0].client_request_id);
  expect(checks).toEqual([creates[0].client_request_id, creates[0].client_request_id]);
  expect(sessions).toBe(1);
  await expect(page.locator(".user-copy .task-attachment")).toContainText(item.name);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("pa_coding_draft_v2_1_101_99")!).attachments)).toEqual([]);
  expect(state.writes).toEqual([]);
  expect(state.unknownRequests).toEqual([]);
});

test("外观切换往返与重载保留草稿和紧凑偏好", async ({ page }) => {
  const state = await prepareRedesignFixture(page);
  await page.goto("/#/app");
  await page.getByLabel("任务输入", { exact: true }).fill("保留设置往返草稿");
  await page.locator(".workspace-header__profile").click();
  await page.getByTestId("settings-section-appearance").click();
  await page.getByRole("radio", { name: /紧凑/ }).check();
  await page.locator(".settings-nav__exit").click();
  await expect(page.getByTestId("home-compact")).toBeVisible();
  await expect(page.getByLabel("任务输入", { exact: true })).toHaveValue("保留设置往返草稿");
  await page.reload();
  await expect(page.getByTestId("home-compact")).toBeVisible();
  await expect(page.getByLabel("任务输入", { exact: true })).toHaveValue("保留设置往返草稿");
  expect(state.unknownRequests).toEqual([]);
  expect(state.writes).toEqual([]);
});

test("模型修改离开保护与弹窗键盘焦点", async ({ page }, info) => {
  const state = await prepareRedesignFixture(page);
  await page.goto("/#/app");
  await page.locator(".workspace-header__profile").click();
  await page.getByTestId("settings-section-provider").click();
  await page.getByLabel("模型 ID", { exact: true }).fill("manual-without-catalog");
  await page.getByRole("button", { name: "手动添加", exact: true }).click();
  const appearance = page.getByTestId("settings-section-appearance");
  await appearance.click();
  const dialog = page.getByRole("dialog", { name: "模型配置尚未保存" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "留在此处" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("button", { name: "保存并继续" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "留在此处" })).toBeFocused();
  await page.screenshot({ path: info.outputPath("unsaved-model-dialog.png"), animations: "disabled" });
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(appearance).toBeFocused();
  await expect(page.getByText("manual-without-catalog", { exact: true })).toBeVisible();
  await appearance.click();
  await dialog.getByRole("button", { name: "放弃更改" }).click();
  await expect(page.getByRole("radiogroup", { name: "首页布局" })).toBeVisible();
  expect(state.writes).toEqual([]);
});

test("任务处理入口定位审批和验证面板，查看时不执行操作", async ({ page }) => {
  const state = await prepareRedesignFixture(page);
  await page.goto("/?coding-run-preview=waiting-approval#/app");
  await page.getByTestId("coding-thread-11").click();
  await page.getByRole("button", { name: "查看审批", exact: true }).click();
  await expect(page.getByTestId("approval-approve-ap-preview-1")).toBeFocused();
  await expect(page.getByTestId("approval-approve-ap-preview-1")).toBeInViewport();
  await page.goto("/?coding-run-preview=command-output#/app");
  await page.getByTestId("coding-thread-11").click();
  const results = page.getByRole("button", { name: "查看验证结果", exact: true });
  await results.click();
  await expect(page.getByRole("tab", { name: "验证", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "关闭环境面板", exact: true }).click();
  await expect(results).toBeFocused();
  expect(state.writes).toEqual([]);
  expect(state.unknownRequests).toEqual([]);
});

test("附件恢复与预览不写项目，弹窗关闭返回焦点", async ({ page }, info) => {
  const state = await prepareRedesignFixture(page);
  const item = { id: "a".repeat(32), name: "参考材料.txt", size_bytes: 18, sha256: "b".repeat(64), language: "txt", project_id: 1, workspace_id: 101 };
  const calls: string[] = [];
  await page.addInitScript(item => localStorage.setItem("pa_coding_draft_v2_1_101_new", JSON.stringify({ text: "待发送材料", chips: [], attachments: [item], draftId: "c".repeat(32) })), item);
  await page.route("**://127.0.0.1:8000/task-attachments**", async route => {
    const request = route.request();
    calls.push(request.method() + " " + new URL(request.url()).pathname);
    await route.fulfill({ json: new URL(request.url()).pathname.endsWith("/content") ? { ...item, content: "只读参考材料", offset: 0, next_offset: null, total_chars: 6 } : [item] });
  });
  await page.goto("/#/app");
  const chip = page.locator(".task-attachment button").first();
  await expect(chip).toContainText("参考材料.txt");
  await chip.click();
  const dialog = page.getByRole("dialog", { name: "参考材料.txt" });
  await expect(dialog.locator("pre")).toHaveText("只读参考材料");
  await dialog.getByRole("button", { name: "导入项目…" }).focus();
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "关闭", exact: true })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("button", { name: "导入项目…" })).toBeFocused();
  await page.screenshot({ path: info.outputPath("attachment-preview.png"), animations: "disabled" });
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(chip).toBeFocused();
  expect(calls.every(call => call.startsWith("GET "))).toBe(true);
  expect(state.writes).toEqual([]);
  expect(state.unknownRequests).toEqual([]);
});
