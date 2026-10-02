import { expect, test } from "@playwright/test";

test("本机长期记忆的启用、编辑、遗忘和窄窗口管理", async ({ page }, testInfo) => {
  const external: string[] = [];
  await page.route("**/*", async route => {
    if (new URL(route.request().url()).origin === new URL(testInfo.project.use.baseURL as string).origin) return route.continue();
    external.push(new URL(route.request().url()).origin);
    await route.abort("blockedbyclient");
  });
  await page.addInitScript(() => {
    const surface = window as unknown as { isTauri: boolean; __TAURI_INTERNALS__: Record<string, unknown> };
    surface.isTauri = true;
    let config = { enabled: false, use_memories: true, generate_memories: true, exclude_external_context: true,
      model_profile_id: null, idle_seconds: 300, max_calls_per_day: 12, version: 1, generation_since: "" };
    let memories: Array<Record<string, unknown>> = [];
    const stamp = "2026-10-02T00:00:00Z";
    const sourceThread = { id: 11, project_id: 7, workspace_id: 70, title: "记忆来源会话", kind: "coding", last_run_id: null, updated_at: stamp, created_at: stamp, archived_at: null };
    const project = { id: 7, name: "记忆验收项目", root_path: "F:\\Fixture\\memory", status: "active", updated_at: stamp, created_at: stamp };
    const workspace = { id: 70, project_id: 7, kind: "root", root_path: project.root_path, branch_name: "main", head_sha: "a".repeat(40), status: "active", last_used_at: stamp };
    let conflictNextEdit = false;
    (window as unknown as { memoryFixture: { seed: () => void; conflict: () => void } }).memoryFixture = {
      seed: () => { memories = [{ id: "memory", title: "测试流程", content: "先运行模块测试", scope: "project", kind: "workflow", project_id: 7, origin: "generated", version: 1, status: "pending_review", review_reason: "conflict", source_session_id: 11, source_item_ids: ["source"], updated_at: "2026-10-02T00:00:00Z" }]; },
      conflict: () => { conflictNextEdit = true; },
    };
    let callbackId = 0;
    surface.__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
      transformCallback: () => ++callbackId, unregisterCallback: () => undefined,
      invoke: async (command: string, args: { id: string; request: { path: string; method: string; body: string; headers: Record<string, string> };
        onEvent: { onmessage: (frame: unknown) => void } }) => {
        if (command === "start_local_executor") return { transport: "stdio", protocol: 2 };
        if (command === "local_executor_cancel") return;
        if (command.startsWith("plugin:event|")) return 1;
        if (command !== "local_executor_request") throw new Error("未开放的测试操作");
        const path = args.request.path.split("?")[0];
        let body: unknown = [];
        let status = 200;
        if (path === "/health") body = { mode: "desktop-local", protocol: 1 };
        else if (path === "/identity/local") body = { ready: true, access_token: `local-session:${"a".repeat(43)}` };
        else if (path === "/identity/clear") body = { cleared: true };
        else {
          if (args.request.headers.authorization !== `Bearer local-session:${"a".repeat(43)}`) throw new Error("缺少本机身份");
          if (path === "/capabilities") body = { coding_agent_ui_enabled: true, project_bound_runs_enabled: true };
          else if (path === "/projects") body = [project];
          else if (path === "/projects/7") body = project;
          else if (path === "/projects/7/workspaces") body = [workspace];
          else if (path === "/projects/7/workspaces/70") body = workspace;
          else if (path === "/sessions" || path === "/sessions/recent") body = [sourceThread];
          else if (path === "/sessions/11") body = sourceThread;
          else if (path === "/sessions/11/messages") body = [{ id: 5, session_id: 11, role: "user", content: "请记住：先运行模块测试", created_at: stamp }, { id: 6, session_id: 11, role: "assistant", content: "已记录项目约定", created_at: stamp }];
          else if (path === "/sessions/11/latest-agent-run") body = { run_id: null };
          else if (path.endsWith("/observer-config")) body = { version: 0, enabled: false, checks: [] };
          else if (path.endsWith("/turn-queue")) body = { item: null };
          else if (path === "/model-settings") body = { llm_temperature: 0.2, llm_context_length: 8192, kb_enabled_by_default: false };
          else if (path === "/local-memories/settings") {
            if (args.request.method === "PUT") config = { ...config, ...JSON.parse(args.request.body), version: config.version + 1 };
            body = config;
          } else if (path === "/local-memories/status") body = { calls_today: 0, worker_running: config.enabled && config.generate_memories, last_attempt: null, error: null };
          else if (path === "/local-memories/items") {
            if (args.request.method === "POST") {
              const item = { ...JSON.parse(args.request.body), id: "memory", origin: "user", version: 1, source_session_id: null, source_item_ids: [] };
              memories.push(item); body = item;
            } else body = memories;
          } else if (path === "/local-memories/items/memory") {
            if (args.request.method === "DELETE") memories = [];
            else if (args.request.method === "GET") body = memories[0];
            else if (conflictNextEdit) { conflictNextEdit = false; status = 409; body = { detail: "记忆已变化，请刷新后重新编辑" }; }
            else { memories[0] = { ...memories[0], ...JSON.parse(args.request.body), version: 2 }; body = memories[0]; }
          } else if (path === "/local-memories/items/memory/review") {
            memories[0] = { ...memories[0], status: "active", review_reason: null, version: 2 }; body = memories[0];
          } else if (path === "/local-memories/items/memory/sources/source") {
            body = { item_id: "source", content: JSON.stringify({ role: "user", content: "请记住：先运行模块测试" }), offset: 0, next_offset: null, total_chars: 50, session_id: 11, project_id: 7, message_id: 5, run_id: "source-run" };
          } else if (path === "/local-memories/items/memory/revisions") {
            body = memories.map(item => ({ ...item, revision_reason: "generated" }));
          }
        }
        args.onEvent.onmessage({ id: args.id, status, headers: { "Content-Type": "application/json" } });
        args.onEvent.onmessage({ id: args.id, data: JSON.stringify(body) });
        args.onEvent.onmessage({ id: args.id, done: true });
      },
    };
  });
  await page.goto("/#/app?view=settings");
  await page.getByRole("button", { name: "记忆", exact: true }).click();
  await expect(page.getByText("此范围暂无记忆。", { exact: false })).toBeVisible();
  await page.getByLabel("启用本机长期记忆").check();
  await page.getByRole("button", { name: "保存记忆设置", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("费用");
  await page.getByRole("dialog").getByRole("button", { name: "开启", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("记忆设置已保存");
  await expect(page.getByText("今日已发起", { exact: false })).toContainText("后台已启用");
  await expect(page.getByRole("dialog")).toBeHidden();
  await page.getByRole("heading", { name: "记忆", exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("memories-settings.png"), fullPage: true });
  await page.getByLabel("标题", { exact: true }).fill("代码说明语言");
  await page.getByLabel("内容", { exact: true }).fill("说明实现思路和测试结果时优先使用中文。代码标识符保留原文。".repeat(6));
  await page.getByRole("button", { name: "保存记忆", exact: true }).click();
  await expect(page.locator("article")).toContainText("代码说明语言");
  await page.screenshot({ path: testInfo.outputPath("memories-wide.png"), fullPage: true });
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByLabel("内容", { exact: true }).fill("优先中文，遇到专业术语保留英文。".repeat(8));
  await page.getByRole("button", { name: "保存记忆", exact: true }).click();
  await expect(page.locator("article")).toContainText("专业术语保留英文");
  await page.setViewportSize({ width: 760, height: 900 });
  await page.locator("article").scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("memories-narrow.png"), fullPage: true });
  await page.getByRole("button", { name: "遗忘", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("会话原文保持不变");
  await page.getByRole("dialog").getByRole("button", { name: "遗忘", exact: true }).click();
  await expect(page.locator("article")).toHaveCount(0);
  await page.evaluate(() => (window as unknown as { memoryFixture: { seed: () => void } }).memoryFixture.seed());
  await page.getByRole("button", { name: "刷新记忆与设置", exact: true }).click();
  await expect(page.locator("article")).toContainText("待复核");
  await page.getByText("查看来源与修订", { exact: true }).click();
  await page.getByRole("button", { name: "来源 1", exact: true }).click();
  await expect(page.locator("article pre")).toContainText("请记住：先运行模块测试");
  await expect(page.getByRole("button", { name: "打开来源会话", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "确认使用", exact: true }).click();
  await expect(page.locator("article")).toContainText("可使用");
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByLabel("内容", { exact: true }).fill("修改尚未保存时应保留");
  await page.evaluate(() => (window as unknown as { memoryFixture: { conflict: () => void } }).memoryFixture.conflict());
  await page.getByRole("button", { name: "保存记忆", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("记忆已变化");
  await expect(page.getByLabel("内容", { exact: true })).toHaveValue("修改尚未保存时应保留");
  await page.screenshot({ path: testInfo.outputPath("memories-review-source-conflict.png"), fullPage: true });
  await page.getByRole("button", { name: "取消编辑", exact: true }).click();
  await page.getByRole("button", { name: "来源 1", exact: true }).click();
  await page.getByRole("button", { name: "打开来源会话", exact: true }).click();
  await expect(page.getByTestId("coding-thread-workspace").getByRole("heading", { name: "记忆来源会话", exact: true })).toBeVisible();
  await expect(page.locator('[data-message-id="5"]')).toContainText("请记住：先运行模块测试");
  await expect(page.locator('[data-message-id="5"]')).toBeFocused();
  await page.screenshot({ path: testInfo.outputPath("memories-source-navigation.png"), fullPage: true });
  expect(external).toEqual([]);
});
