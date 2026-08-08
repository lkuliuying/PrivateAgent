import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * 0.4.0 D5：可访问性检查（@axe-core/playwright）
 * 扫描 v2 壳 + Agent 工作区的 WCAG AA 违规；规则基于文档计划 10.3。
 * 已知且允许的 P2 项记录在 docs/v0.4.0-alpha.1-checkpoint-20260808.md。
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
      await route.fulfill({
        json: [
          {
            id: 1,
            title: "无障碍检查会话",
            created_at: "2026-08-08T00:00:00Z",
            updated_at: "2026-08-08T01:00:00Z",
          },
        ],
      });
      return;
    }
    if (path.includes("/messages")) {
      await route.fulfill({ json: [] });
      return;
    }
    if (path === "/health") {
      await route.fulfill({ json: GREEN_HEALTH });
      return;
    }
    await route.fulfill({ json: {} });
  });
}

test.describe("0.4.0 可访问性", () => {
  test("v2 壳 + Agent 工作区无严重 WCAG AA 违规", async ({ page }) => {
    await mockApi(page);
    await page.goto("/?ui=v2");
    await expect(page.getByTestId("nav-chat")).toBeVisible();

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();

    const serious = results.violations.filter(
      (violation) =>
        violation.impact === "serious" || violation.impact === "critical"
    );
    expect(
      serious.map((v) => `${v.id}: ${v.help}`),
      `严重违规:\n${JSON.stringify(serious, null, 2)}`
    ).toEqual([]);
  });

  test("键盘焦点可见：Tab 导航出现 focus-visible 环", async ({ page }) => {
    await mockApi(page);
    await page.goto("/?ui=v2");
    await expect(page.getByTestId("nav-chat")).toBeVisible();

    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return null;
      const ring = getComputedStyle(el).boxShadow;
      const outline = getComputedStyle(el).outlineStyle;
      return { tag: el.tagName, ring, outline };
    });
    expect(focused).not.toBeNull();
    expect(focused!.ring).not.toBe("none");
  });
});
