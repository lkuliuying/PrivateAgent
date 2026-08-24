import { test, expect } from "@playwright/test";

/**
 * 第八阶段 M1：E2E smoke（浏览器模式）。
 *
 * 浏览器模式下 App.vue boot() 检测 !isTauri() 后直接 bootState="done" 并使用
 * 127.0.0.1:8000（无需 Tauri/sidecar/向导）。后端用 page.route 拦截模拟。
 * route 只拦截 API 主机 127.0.0.1:8000，避免误伤 Vite 模块（localhost:1420）。
 * 覆盖：Today 首屏、后端断开提示。桌面 Tauri 窗口级 E2E 见 docs/usage-guide。
 */

const GREEN_HEALTH = {
  api: true,
  ollama: { ok: true, models: [] },
  mysql: { ok: true },
  chroma: { ok: true },
};

const TODAY_SNAPSHOT = {
  generated_at: new Date().toISOString(),
  summary: {
    due_cards: 0,
    attention_tasks: 0,
    failed_activities: 0,
    draft_memories: 0,
    due_reminders: 0,
    open_inbox: 1,
    last_backup_at: null,
  },
  due_cards: [],
  attention_tasks: [],
  failed_activities: [],
  draft_memories: [],
  due_reminders: [],
  open_inbox: [
    {
      id: 1,
      title: "E2E测试收件项",
      item_type: "todo",
      status: "open",
      priority: "normal",
      source_type: "inbox",
      source_id: 1,
    },
  ],
  backup: { last_backup_at: null, count: 0 },
  recent_checkins: [],
  recent_briefings: [],
  recent_docs: [],
  recent_sessions: [],
  maintenance: {
    last_backup_at: null,
    backup_count: 0,
    failed_activities: 0,
    draft_memories: 0,
    orphan_evidence: 0,
  },
};

/** 只拦截 API 主机 127.0.0.1:8000，避免误伤 Vite 模块。 */
function mockApi(
  page: import("@playwright/test").Page,
  fulfill: (url: string) => unknown
) {
  return page.route("**://127.0.0.1:8000/**", async (r) => {
    await r.fulfill({ json: fulfill(r.request().url()) } as never);
  });
}

async function navigate(page: import("@playwright/test").Page, view: string) {
  const target = page.getByTestId(`nav-${view}`);
  if (await target.count()) {
    await target.click();
    return;
  }

  await page.getByTestId("nav-utilities-toggle").click();
  await page.getByTestId(`nav-${view}`).click();
}

test.describe("E2E smoke", () => {
  test("v0.9.0 默认切换：新安装首启进入 Coding 工作台（显式回退键保留）", async ({ page }) => {
    await mockApi(page, (url) => {
      if (url.includes("/health")) return GREEN_HEALTH;
      if (url.includes("/capabilities")) {
        return {
          chat_execution_mode: "legacy",
          legacy_tool_planner_enabled: true,
          agent_read_only_tools_enabled: false,
          rag_chat_runtime_enabled: false,
          coding_agent_ui_enabled: true,
          project_bound_runs_enabled: true,
          product_timezone: "Asia/Shanghai",
        };
      }
      return [];
    });

    // 默认（无显式参数）进入 Coding 侧栏与首页空态（无项目）
    await page.goto("/");
    await expect(page.getByTestId("coding-sidebar")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("coding-home-no-projects")).toBeVisible();

    // 显式回退键：?coding=0 回到旧 Agent 界面（计划 §3.3）
    await page.goto("/?coding=0");
    await expect(page.getByTestId("nav-chat")).toBeVisible({ timeout: 10000 });
  });

  test("能力位回退：后端声明关闭且非显式选择时回落旧 UI", async ({ page }) => {
    await mockApi(page, (url) => {
      if (url.includes("/health")) return GREEN_HEALTH;
      if (url.includes("/capabilities")) {
        return {
          chat_execution_mode: "legacy",
          legacy_tool_planner_enabled: true,
          agent_read_only_tools_enabled: false,
          rag_chat_runtime_enabled: false,
          coding_agent_ui_enabled: false,
        };
      }
      return [];
    });

    await page.goto("/");
    // 短暂出现后回落旧壳（能力位关闭；回落原因本地计数）
    await expect(page.getByTestId("nav-chat")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("coding-sidebar")).toHaveCount(0);
  });
  test("Agent Runtime 模式的新消息绕过旧工具规划器", async ({ page }) => {
    let plannerCalls = 0;
    let chatStreamCalls = 0;
    await page.route("**://127.0.0.1:8000/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path === "/capabilities") {
        await route.fulfill({
          json: {
            chat_execution_mode: "agent_runtime",
            legacy_tool_planner_enabled: false,
            agent_read_only_tools_enabled: true,
            rag_chat_runtime_enabled: false,
          },
        });
        return;
      }
      if (path === "/sessions") {
        await route.fulfill({
          json: [
            {
              id: 1,
              title: "Runtime route test",
              created_at: "2026-08-03T00:00:00Z",
              updated_at: "2026-08-03T00:00:00Z",
            },
          ],
        });
        return;
      }
      if (path === "/settings") {
        // v0.9.0 H1-B（§5.6）：模型未配置时执行按钮禁用；声明已配置模型
        await route.fulfill({
          json: {
            provider_type: "ollama",
            llm_model: "qwen2.5:14b-instruct-q4_K_M",
            remote_provider_enabled: false,
            llm_context_length: 32768,
          },
        });
        return;
      }
      if (path === "/tools/plan") {
        plannerCalls += 1;
        await route.fulfill({ json: { tool_call: null } });
        return;
      }
      if (path === "/chat/stream") {
        chatStreamCalls += 1;
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream; charset=utf-8",
          body:
            'data: {"type":"run","run_id":"run-e2e"}\n\n' +
            'data: {"type":"token","content":"Runtime E2E reply"}\n\n' +
            'data: {"type":"done","run_id":"run-e2e","message_id":10,"content":"Runtime E2E reply"}\n\n',
        });
        return;
      }
      await route.fulfill({ json: [] });
    });

    await page.goto("/?coding=0");
    await page.getByTestId("task-composer-input").fill("Use the runtime");
    await page.getByTestId("task-composer-submit").click();

    await expect(page.getByText("Runtime E2E reply")).toBeVisible();
    expect(chatStreamCalls).toBe(1);
    expect(plannerCalls).toBe(0);
  });

  test("legacy 能力下新消息仍走旧规划器（回退契约不回退）", async ({ page }) => {
    let plannerCalls = 0;
    let chatStreamCalls = 0;
    await page.route("**://127.0.0.1:8000/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/capabilities") {
        await route.fulfill({
          json: {
            chat_execution_mode: "legacy",
            legacy_tool_planner_enabled: true,
            agent_read_only_tools_enabled: false,
            rag_chat_runtime_enabled: false,
          },
        });
        return;
      }
      if (path === "/sessions") {
        await route.fulfill({
          json: [
            {
              id: 1,
              title: "Legacy route test",
              created_at: "",
              updated_at: "",
            },
          ],
        });
        return;
      }
      if (path === "/settings") {
        // v0.9.0 H1-B（§5.6）：模型未配置时执行按钮禁用；声明已配置模型
        await route.fulfill({
          json: {
            provider_type: "ollama",
            llm_model: "qwen2.5:14b-instruct-q4_K_M",
            remote_provider_enabled: false,
            llm_context_length: 32768,
          },
        });
        return;
      }
      if (path === "/tools/plan") {
        plannerCalls += 1;
        await route.fulfill({ json: { tool_call: null } });
        return;
      }
      if (path === "/chat/stream") {
        chatStreamCalls += 1;
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream; charset=utf-8",
          body:
            'data: {"type":"done","message_id":11,"content":"Legacy E2E reply","sources":[],"memories":[]}\n\n',
        });
        return;
      }
      await route.fulfill({ json: [] });
    });

    await page.goto("/?coding=0");
    await page.getByTestId("task-composer-input").fill("Use legacy");
    await page.getByTestId("task-composer-submit").click();

    await expect(page.getByText("Legacy E2E reply")).toBeVisible();
    expect(plannerCalls).toBe(1);
    expect(chatStreamCalls).toBe(1);
  });

  test("Today 首屏渲染（W6-R：六模块迁出，收件项在独立主区验证）", async ({ page }) => {
    await mockApi(page, (url) => {
      if (url.includes("/health")) return GREEN_HEALTH;
      if (url.includes("/today")) return TODAY_SNAPSHOT;
      if (url.includes("/inbox"))
        return [
          {
            id: 1,
            title: "E2E测试收件项",
            body_md: null,
            item_type: "todo",
            status: "open",
            priority: "normal",
            due_at: null,
            source_type: "inbox",
            source_id: 1,
            target_type: null,
            target_id: null,
            meta_json: null,
            created_at: "",
            updated_at: "",
            handled_at: null,
          },
        ];
      return [];
    });

    await page.goto("/?coding=0");
    // 应用外壳启动（两种壳均有主导航，v2 为 .rail-brand；等待 nav 项更稳）
    await expect(page.getByTestId("nav-chat")).toBeVisible();
    // 当前产品默认进入 Agent 工作区；显式进入 Today 后再验证首屏。
    await navigate(page, "today");
    await expect(page.getByTestId("nav-today")).toHaveAttribute("aria-current", "page");
    // v0.8.0 W6-R：今日页不再内嵌六个完整面板；收件箱只读数字仍在（宽超时，等 /today 返回）
    await expect(page.locator(".workbench-modules")).toHaveCount(0);
    await expect(page.getByText("收件箱").first()).toBeVisible({ timeout: 20_000 });
    // 收件项在独立收件箱主区呈现（路由归属迁移，业务能力保真）
    await navigate(page, "inbox");
    await expect(page.getByText("E2E测试收件项")).toBeVisible({ timeout: 20_000 });
  });

  test("后端断开提示", async ({ page }) => {
    await mockApi(page, () => []);
    // /health 直接 503
    await page.route("**://127.0.0.1:8000/health", (r) =>
      r.fulfill({ status: 503 })
    );

    await page.goto("/?coding=0");
    await expect(page.getByTestId("nav-chat")).toBeVisible();
    // 进入设置页，应显示后端未连接提示
    await navigate(page, "settings");
    await expect(page.getByText(/本地后端.*未连接|无法获取状态/).first()).toBeVisible({
      timeout: 20_000,
    });
  });

  test("知识库窄窗口状态与操作区无横向溢出", async ({ page }) => {
    await page.setViewportSize({ width: 960, height: 720 });
    await mockApi(page, (url) => {
      if (url.includes("/health")) return GREEN_HEALTH;
      if (url.includes("/documents"))
        return [
          {
            id: 1,
            name: "一份用于验证超长文档名称在窄窗口中正确换行而不挤出操作区的资料.md",
            mime_type: "text/markdown",
            size_bytes: 4096,
            content_hash: "hash",
            embedding_model: "test",
            chunk_count: 8,
            status: "ready",
            enabled: true,
            error_message: null,
            last_error_at: null,
            indexed_at: null,
            doc_type: "markdown",
            topic: "页面显示",
            tags_json: ["窄窗口", "长名称"],
            language: "zh",
            project_id: null,
            created_at: "",
            updated_at: "",
          },
        ];
      return [];
    });

    await page.goto("/?coding=0");
    await navigate(page, "kb");
    // v2 壳顶部栏与知识库页各有一个「知识库」标题
    await expect(page.getByRole("heading", { name: "知识库" }).first()).toBeVisible();
    await expect(page.getByText(/一份用于验证超长文档名称/)).toBeVisible();
    const metrics = await page.evaluate(() => ({
      body: document.body.scrollWidth,
      root: document.documentElement.scrollWidth,
      viewport: window.innerWidth,
    }));
    expect(metrics.body).toBeLessThanOrEqual(metrics.viewport);
    expect(metrics.root).toBeLessThanOrEqual(metrics.viewport);
  });

  for (const viewport of [
    { width: 1280, height: 720 },
    { width: 1440, height: 900 },
    { width: 1920, height: 1080 },
    { width: 960, height: 720 },
  ]) {
    test(`Today 布局 ${viewport.width}x${viewport.height} 无横向溢出`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await mockApi(page, (url) => {
        if (url.includes("/health")) return GREEN_HEALTH;
        if (url.includes("/today")) return TODAY_SNAPSHOT;
        return [];
      });
      await page.goto("/?coding=0");
      await navigate(page, "today");
      await expect(page.getByRole("heading", { name: "今日工作台" })).toBeVisible();
      const metrics = await page.evaluate(() => ({
        body: document.body.scrollWidth,
        root: document.documentElement.scrollWidth,
        viewport: window.innerWidth,
      }));
      expect(metrics.body).toBeLessThanOrEqual(metrics.viewport);
      expect(metrics.root).toBeLessThanOrEqual(metrics.viewport);
      // W6-R2：today-composer 已移除；头部加长搜索入口仍在且无溢出
      await expect(page.locator(".command-entry")).toBeVisible();
      if (viewport.width === 1440) {
        await page.screenshot({ path: "test-results/today-workbench-1440x900.png", fullPage: false });
      }
    });
  }
});
