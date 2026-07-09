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

test.describe("E2E smoke", () => {
  test("Today 首屏渲染", async ({ page }) => {
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

    await page.goto("/");
    // 应用外壳启动（NavRail 品牌）
    await expect(page.locator(".navrail-brand")).toBeVisible();
    // 默认进入 Today 视图（今日 nav 项激活）
    await expect(page.locator(".nav-item.active").getByText("今日")).toBeVisible();
    // Today 视图渲染了模拟收件项（宽超时，等待 /today 返回后渲染）
    await expect(page.getByText("E2E测试收件项")).toBeVisible({ timeout: 20_000 });
  });

  test("后端断开提示", async ({ page }) => {
    await mockApi(page, () => []);
    // /health 直接 503
    await page.route("**://127.0.0.1:8000/health", (r) =>
      r.fulfill({ status: 503 })
    );

    await page.goto("/");
    await expect(page.locator(".navrail-brand")).toBeVisible();
    // 进入设置页，应显示后端未连接提示
    await page.locator(".nav-item", { hasText: "设置" }).click();
    await expect(page.getByText(/本地后端未连接|无法获取状态/).first()).toBeVisible({
      timeout: 20_000,
    });
  });
});
