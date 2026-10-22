import { expect, test } from "@playwright/test";

/** M5：记忆管理页的对照、疑似重复提示与状态筛选（模拟本机 IPC，不含真实数据）。 */
test("记忆维护：同主题对照、疑似重复与状态筛选", async ({ page }, testInfo) => {
  const external: string[] = [];
  const writes: string[] = [];
  await page.route("**/*", async route => {
    if (new URL(route.request().url()).origin === new URL(testInfo.project.use.baseURL as string).origin) return route.continue();
    external.push(new URL(route.request().url()).origin);
    await route.abort("blockedbyclient");
  });
  await page.addInitScript(() => {
    const surface = window as unknown as { isTauri: boolean; __TAURI_INTERNALS__: Record<string, unknown> };
    surface.isTauri = true;
    const stamp = "2026-10-02T00:00:00Z";
    const config = { enabled: true, use_memories: true, generate_memories: false, exclude_external_context: true,
      model_profile_id: null, idle_seconds: 300, max_calls_per_day: 12, version: 1, generation_since: "" };
    const project = { id: 7, name: "记忆维护项目", root_path: "F:\\Fixture\\memory", status: "active", updated_at: stamp, created_at: stamp };
    const workspace = { id: 70, project_id: 7, kind: "root", root_path: project.root_path, branch_name: "main",
      head_sha: "a".repeat(40), status: "active", last_used_at: stamp };
    const memories = [
      { id: "current", title: "发布流程", content: "先合并后发布", scope: "project", kind: "project", project_id: 7,
        origin: "user", version: 3, status: "active", review_reason: null, topic_key: "topic:release",
        source_session_id: 11, source_item_ids: ["source"], source_updated_at: stamp, updated_at: "2026-10-01T00:00:00Z" },
      { id: "candidate", title: "发布流程", content: "先发布后合并", scope: "project", kind: "project", project_id: 7,
        origin: "generated", version: 1, status: "pending_review", review_reason: "conflict", topic_key: "topic:release",
        supersedes_id: "current", supersedes_version: 3, source_session_id: 11, source_item_ids: ["source", "source"],
        updated_at: "2026-10-02T00:00:00Z" },
      { id: "duplicate", title: "发布流程 ", content: "先合并后发布", scope: "project", kind: "preference", project_id: 7,
        origin: "generated", version: 1, status: "stale", review_reason: "volatile", topic_key: "topic:release-2",
        source_session_id: null, source_item_ids: [], updated_at: "2026-09-01T00:00:00Z" },
    ];
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
        const status = 200;
        if (path === "/health") body = { mode: "desktop-local", protocol: 1 };
        else if (path === "/identity/local") body = { ready: true, access_token: `local-session:${"a".repeat(43)}` };
        else if (path === "/capabilities") body = { coding_agent_ui_enabled: true, project_bound_runs_enabled: true };
        else if (path === "/projects") body = [project];
        else if (path === "/projects/7") body = project;
        else if (path === "/projects/7/workspaces") body = [workspace];
        else if (path === "/sessions/recent") body = [];
        else if (path === "/local-memories/settings") body = config;
        else if (path === "/local-memories/status") body = { calls_today: 0, worker_running: false, last_attempt: null, error: null };
        else if (path === "/local-memories/items") body = memories;
        else if (path.endsWith("/revisions") || path.includes("/sources/")) body = [];
        args.onEvent.onmessage({ id: args.id, status, headers: { "Content-Type": "application/json" } });
        args.onEvent.onmessage({ id: args.id, data: JSON.stringify(body) });
        args.onEvent.onmessage({ id: args.id, done: true });
      },
    };
  });
  await page.goto("/#/app?view=settings");
  await page.getByRole("button", { name: "记忆", exact: true }).click();
  await page.getByLabel("查看范围").selectOption("7");
  const conflicts = page.getByTestId("memory-conflicts");
  await expect(conflicts).toContainText("当前条目");
  await expect(conflicts).toContainText("新候选");
  await expect(conflicts).toContainText("先合并后发布");
  await expect(conflicts).toContainText("先发布后合并");
  await expect(conflicts).toContainText("版本 3");
  // 来源只作为可追溯引用展示，不宣称已验证。
  await expect(conflicts).toContainText("新候选有 2 个会话来源");
  await expect(conflicts).not.toContainText("已验证");
  const duplicates = page.getByTestId("memory-duplicates");
  await expect(duplicates).toContainText("规范化标题相同");
  await expect(duplicates).toContainText("规范化正文相同");
  // 键盘可展开疑似重复分组。
  await duplicates.locator("summary").first().focus();
  await page.keyboard.press("Enter");
  await expect(duplicates.locator("details").first()).toHaveAttribute("open", "");
  await page.screenshot({ path: testInfo.outputPath("memory-maintenance-wide.png"), fullPage: true });
  // 状态筛选只影响展示，不改变条目状态。
  await page.getByTestId("memory-status-filter").selectOption("stale");
  await expect(page.locator("article")).toContainText("发布流程");
  await expect(page.locator("article")).not.toContainText("先发布后合并");
  await page.getByTestId("memory-status-filter").selectOption("pending_review");
  await expect(page.locator("article")).toContainText("先发布后合并");
  await page.setViewportSize({ width: 760, height: 900 });
  await expect(page.getByTestId("memory-conflicts")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("memory-maintenance-narrow.png"), fullPage: true });
  expect(writes).toEqual([]);
  expect(external).toEqual([]);
});
