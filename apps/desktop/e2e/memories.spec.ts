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
        if (path === "/health") body = { mode: "desktop-local", protocol: 1 };
        else if (path === "/identity/local") body = { ready: true, access_token: `local-session:${"a".repeat(43)}` };
        else if (path === "/identity/clear") body = { cleared: true };
        else {
          if (args.request.headers.authorization !== `Bearer local-session:${"a".repeat(43)}`) throw new Error("缺少本机身份");
          if (path === "/capabilities") body = { coding_agent_ui_enabled: true, project_bound_runs_enabled: true };
          else if (path === "/projects") body = [{ id: 7, name: "记忆验收项目", status: "active", updated_at: new Date().toISOString() }];
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
            else { memories[0] = { ...memories[0], ...JSON.parse(args.request.body), version: 2 }; body = memories[0]; }
          }
        }
        args.onEvent.onmessage({ id: args.id, status: 200, headers: { "Content-Type": "application/json" } });
        args.onEvent.onmessage({ id: args.id, data: JSON.stringify(body) });
        args.onEvent.onmessage({ id: args.id, done: true });
      },
    };
  });
  await page.goto("/#/app?view=settings&section=provider");
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
  await page.getByRole("dialog").getByRole("button", { name: "遗忘", exact: true }).click();
  await expect(page.locator("article")).toHaveCount(0);
  expect(external).toEqual([]);
});
