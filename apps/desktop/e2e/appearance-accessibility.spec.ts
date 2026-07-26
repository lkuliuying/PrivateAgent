import { expect, test, type Page } from "@playwright/test";

const EMPTY_TODAY = {
  generated_at: new Date().toISOString(),
  summary: {
    due_cards: 0,
    attention_tasks: 0,
    failed_activities: 0,
    draft_memories: 0,
    due_reminders: 0,
    open_inbox: 0,
    last_backup_at: null,
  },
  due_cards: [],
  attention_tasks: [],
  failed_activities: [],
  draft_memories: [],
  due_reminders: [],
  open_inbox: [],
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

async function mockApi(page: Page) {
  await page.route("**://127.0.0.1:8000/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/today") await route.fulfill({ json: EMPTY_TODAY });
    else if (path === "/health") {
      await route.fulfill({
        json: {
          api: { ok: true },
          ollama: { ok: true, models: [] },
          mysql: { ok: true },
          chroma: { ok: true },
        },
      });
    } else await route.fulfill({ json: [] });
  });
}

test.describe("appearance and keyboard accessibility", () => {
  test("system dark theme, explicit preference and contrast persist", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
    await mockApi(page);
    await page.goto("/");

    const root = page.locator("html");
    await expect(root).toHaveAttribute("data-theme", "dark");
    await expect(root).toHaveAttribute("data-theme-preference", "system");
    await expect(page.getByRole("heading", { name: "今日工作台" })).toBeVisible();
    await page.screenshot({
      path: "test-results/today-workbench-dark-1440x900.png",
      fullPage: false,
    });

    const themeButton = page.getByRole("button", { name: /主题：系统/ });
    await themeButton.click();
    await expect(root).toHaveAttribute("data-theme", "light");
    await expect(root).toHaveAttribute("data-theme-preference", "light");

    await page.getByRole("button", { name: "开启高对比度" }).click();
    await expect(root).toHaveAttribute("data-contrast", "more");
    await page.reload();
    await expect(root).toHaveAttribute("data-theme", "light");
    await expect(root).toHaveAttribute("data-contrast", "more");

    const motion = await page.locator(".workspace-ambient").evaluate((element) => {
      const style = getComputedStyle(element.querySelector(".ambient-orb")!);
      return { duration: style.animationDuration, iterations: style.animationIterationCount };
    });
    expect(motion.duration).toBe("0.001s");
    expect(motion.iterations).toBe("1");
    await page.screenshot({
      path: "test-results/today-workbench-high-contrast-1440x900.png",
      fullPage: false,
    });
  });

  test("command palette traps focus and restores the trigger", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");

    const trigger = page.getByRole("button", { name: "打开快捷命令" });
    await trigger.focus();
    await trigger.click();
    const commandInput = page.getByRole("combobox", { name: "筛选命令" });
    await expect(commandInput).toBeFocused();
    await expect(page.locator("#app")).toHaveAttribute("aria-hidden", "true");
    await page.keyboard.press("Shift+Tab");
    await expect(commandInput).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "命令面板" })).toHaveCount(0);
    await expect(page.locator("#app")).not.toHaveAttribute("aria-hidden", "true");
    await expect(trigger).toBeFocused();
  });
});
