import { test, expect, type Page } from "@playwright/test";

/**
 * 0.4.0 D6 视觉回归矩阵（toHaveScreenshot 断言基线）
 * 覆盖：v2 壳 Agent 工作区（1280/1440/1920）、今日、UI Lab 关键场景。
 * 确定性措施：冻结时钟 + reduced-motion + fonts.ready（与证据采集一致），
 * maxDiffPixelRatio 吸收字体栅格化噪声。
 * 更新基线：npx playwright test e2e/visual-regression.spec.ts --update-snapshots
 */

const GREEN_HEALTH = {
  api: true,
  ollama: { ok: true, models: [] },
  mysql: { ok: true },
  chroma: { ok: true },
};

const FIXED_NOW = new Date("2026-08-08T10:00:00.000Z");

function mockApi(page: Page, title = "视觉基线会话") {
  return page.route("**://127.0.0.1:8000/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/capabilities") {
      await route.fulfill({
        json: {
          chat_execution_mode: "agent_runtime",
          legacy_tool_planner_enabled: false,
          agent_read_only_tools_enabled: true,
          rag_chat_runtime_enabled: true,
        },
      });
      return;
    }
    if (path === "/sessions") {
      await route.fulfill({
        json: [
          {
            id: 1,
            title,
            created_at: "2026-08-08T00:00:00Z",
            updated_at: "2026-08-08T01:00:00Z",
          },
        ],
      });
      return;
    }
    if (path.includes("/messages")) {
      await route.fulfill({
        json: [
          {
            id: 1,
            session_id: 1,
            role: "user",
            content: "重构个人 Agent 工作台，保留现有本地接口与业务能力。",
            created_at: "2026-08-08T00:01:00Z",
          },
          {
            id: 2,
            session_id: 1,
            role: "assistant",
            content:
              "已完成项目结构检查。当前重点是三栏工作台、统一审批卡与执行状态呈现。",
            created_at: "2026-08-08T00:02:00Z",
          },
        ],
      });
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
    if (
      path.includes("/tool-calls") ||
      path.includes("/pending-approvals") ||
      path.includes("/activities") ||
      path.includes("/trusted-paths")
    ) {
      await route.fulfill({ json: [] });
      return;
    }
    await route.fulfill({ json: {} });
  });
}

async function openV2(page: Page, width: number, height = 900) {
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: FIXED_NOW });
  await page.clock.setFixedTime(FIXED_NOW);
  await mockApi(page);
  await page.goto("/?ui=v2");
  await expect(page.getByTestId("nav-chat")).toBeVisible();
  await expect(page.getByRole("heading", { name: "视觉基线会话" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready.then(() => true));
  await page.waitForTimeout(300);
}

test.describe("0.4.0 视觉回归矩阵", () => {
  // rc.3：视觉基线对流水线负载下的字体栅格化抖动敏感（单独跑稳定）；
  // 允许单次自动重试吸收抖动，不掩盖真实回归（重试仍失败则 FAIL）。
  test.describe.configure({ retries: 1 });
  test.use({ reducedMotion: "reduce" });

  test("v2 Agent 工作区 1280", async ({ page }) => {
    await openV2(page, 1280);
    await expect(page).toHaveScreenshot("v2-agent-1280.png", {
      maxDiffPixelRatio: 0.03,
    });
  });

  test("v2 Agent 工作区 1440", async ({ page }) => {
    await openV2(page, 1440);
    await expect(page).toHaveScreenshot("v2-agent-1440.png", {
      maxDiffPixelRatio: 0.03,
    });
  });

  test("v2 Agent 工作区 1920", async ({ page }) => {
    await openV2(page, 1920);
    await expect(page).toHaveScreenshot("v2-agent-1920.png", {
      maxDiffPixelRatio: 0.03,
    });
  });

  test("v2 今日视图 1440", async ({ page }) => {
    await openV2(page, 1440);
    await page.getByTestId("nav-today").click();
    await expect(page.getByTestId("nav-today")).toHaveAttribute("aria-current", "page");
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveScreenshot("v2-today-1440.png", {
      maxDiffPixelRatio: 0.03,
    });
  });

  test("v1 回退壳 1440", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.clock.install({ time: FIXED_NOW });
    await page.clock.setFixedTime(FIXED_NOW);
    await mockApi(page);
    await page.goto("/?ui=v1");
    await expect(page.getByTestId("nav-chat")).toBeVisible();
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => document.fonts.ready.then(() => true));
    await page.waitForTimeout(300);
    await expect(page).toHaveScreenshot("v1-legacy-1440.png", {
      maxDiffPixelRatio: 0.03,
    });
  });
});
