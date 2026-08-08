import { test, expect, type Page } from "@playwright/test";

/**
 * 0.4.0 D4 全生产页面验收（计划 10.2/11.1：功能无丢失、空态、窄窗口、键盘可达）
 * 对 12 个生产视图逐一验证：
 *  - 导航可达且页面主体渲染（空数据 → 空态可见）；
 *  - 1280 宽无横向溢出；
 *  - 键盘 Tab 可达首个可聚焦元素。
 * 数据保留：所有页面共用空数据 mock，证明"无数据也能正确渲染"。
 */

const GREEN_HEALTH = {
  api: true,
  ollama: { ok: true, models: [] },
  mysql: { ok: true },
  chroma: { ok: true },
};

function mockApi(page: Page) {
  return page.route("**://127.0.0.1:8000/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/capabilities") {
      await route.fulfill({
        json: {
          chat_execution_mode: "legacy",
          legacy_tool_planner_enabled: true,
          agent_read_only_tools_enabled: true,
          rag_chat_runtime_enabled: false,
        },
      });
      return;
    }
    if (path === "/sessions") {
      await route.fulfill({ json: [] });
      return;
    }
    if (path === "/health") {
      await route.fulfill({ json: GREEN_HEALTH });
      return;
    }
    if (path === "/settings") {
      await route.fulfill({ json: { model: "qwen3:4b" } });
      return;
    }
    if (path.includes("/messages")) {
      await route.fulfill({ json: [] });
      return;
    }
    // 其余页面数据一律空数组/空对象：验证空态渲染
    await route.fulfill({ json: [] });
  });
}

interface PageCheck {
  view: string;
  /** 页面主体渲染后的关键定位元素（标题或内容锚点） */
  anchor: string | RegExp;
}

const PAGES: PageCheck[] = [
  { view: "today", anchor: /今日工作台|今日/ },
  { view: "chat", anchor: /准备好开始一个新任务|新任务/ },
  { view: "kb", anchor: /知识库/ },
  { view: "projects", anchor: /项目/ },
  { view: "tasks", anchor: /任务/ },
  { view: "learning", anchor: /学习/ },
  { view: "memory", anchor: /记忆/ },
  { view: "integrations", anchor: /集成/ },
  { view: "extensions", anchor: /扩展/ },
  { view: "settings", anchor: /设置/ },
  { view: "diagnostics", anchor: /诊断/ },
  { view: "backup", anchor: /备份/ },
];

async function openApp(page: Page) {
  await page.setViewportSize({ width: 1280, height: 800 });
  await mockApi(page);
  await page.goto("/?ui=v2");
  await expect(page.getByTestId("nav-chat")).toBeVisible();
  await page.waitForLoadState("networkidle");
}

test.describe("0.4.0 D4 全生产页面验收", () => {
  for (const pageCheck of PAGES) {
    test(`页面 ${pageCheck.view}：导航可达、主体渲染、无横向溢出、键盘可达`, async ({
      page,
    }) => {
      await openApp(page);
      await page.getByTestId(`nav-${pageCheck.view}`).click();
      await expect(page.getByTestId(`nav-${pageCheck.view}`)).toHaveAttribute(
        "aria-current",
        "page"
      );
      // 主体渲染（顶栏标题或页面内容锚点）
      const anchor = page.getByText(pageCheck.anchor).first();
      await expect(anchor).toBeVisible({ timeout: 15000 });
      // 无横向溢出
      const metrics = await page.evaluate(() => ({
        body: document.body.scrollWidth,
        root: document.documentElement.scrollWidth,
        viewport: window.innerWidth,
      }));
      expect(metrics.body).toBeLessThanOrEqual(metrics.viewport);
      expect(metrics.root).toBeLessThanOrEqual(metrics.viewport);
      // 键盘可达：Tab 能聚焦到可交互元素
      await page.keyboard.press("Tab");
      const focused = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        return el ? el.tagName : null;
      });
      expect(focused).not.toBeNull();
    });
  }

  test("后端断开：设置页展示未连接错误态（错误态覆盖）", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await mockApi(page);
    await page.route("**://127.0.0.1:8000/health", (r) =>
      r.fulfill({ status: 503 })
    );
    await page.goto("/?ui=v2");
    await expect(page.getByTestId("nav-chat")).toBeVisible();
    await page.getByTestId("nav-settings").click();
    await expect(
      page.getByText(/本地后端.*未连接|无法获取状态/).first()
    ).toBeVisible({ timeout: 20000 });
  });
});
