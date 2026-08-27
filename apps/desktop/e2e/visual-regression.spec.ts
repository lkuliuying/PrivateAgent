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
  await page.goto("/?ui=v2&coding=0");
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

/** v0.8.0 W5：Coding 工作台视觉矩阵（确定性夹具：首页 ready 预览 + 任务页事件流预览） */
function mockCodingApi(page: Page) {
  return page.route("**://127.0.0.1:8000/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/capabilities") {
      await route.fulfill({
        json: {
          chat_execution_mode: "legacy",
          legacy_tool_planner_enabled: true,
          agent_read_only_tools_enabled: true,
          rag_chat_runtime_enabled: false,
          coding_agent_ui_enabled: true,
          agent_runs_api_enabled: true,
          project_bound_runs_enabled: true,
        },
      });
      return;
    }
    if (path === "/health") {
      await route.fulfill({ json: GREEN_HEALTH });
      return;
    }
    if (path === "/projects") {
      await route.fulfill({ json: [{ id: 1, name: "PrivateAgent", root_path: "C:\s", language: null, framework: null, status: "active", last_scanned_at: null, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-22T00:00:00Z" }] });
      return;
    }
    if (path === "/projects/1/workspaces") {
      await route.fulfill({ json: [{ id: 101, project_id: 1, kind: "root", root_path: "C:\s", branch_name: "main", head_sha: "abcd1234", status: "active", last_used_at: null, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-22T00:00:00Z" }] });
      return;
    }
    if (path === "/sessions") {
      await route.fulfill({ json: [{ id: 11, title: "修复窄屏侧栏遮挡问题", created_at: "2026-08-20T00:00:00Z", updated_at: "2026-08-22T00:00:00Z", project_id: 1, workspace_id: 101, kind: "coding", last_run_id: null, pinned_at: null, archived_at: null }] });
      return;
    }
    if (path === "/agent-model-profiles") {
      await route.fulfill({ json: [{ id: "local-coder", provider: "ollama", display_name: "Qwen3 Coder 30B", is_local: true, native_tool_calls: true, supports_streaming: true, supports_structured_output: true, supports_vision: false, context_tokens: 131072, reasoning_efforts: ["low", "medium", "high"], usage_reporting: true, enabled: true, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z" }] });
      return;
    }
    await route.fulfill({ json: {} });
  });
}

async function openCodingVisual(page: Page, width: number, height = 900, extra = "&coding-preview=ready") {
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: FIXED_NOW });
  await page.clock.setFixedTime(FIXED_NOW);
  await mockCodingApi(page);
  await page.goto(`/?coding=1${extra}`);
  await expect(page.getByTestId("coding-sidebar")).toBeVisible({ timeout: 10000 });
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready.then(() => true));
  await page.waitForTimeout(300);
}

test.describe("v0.8.0 Coding 视觉矩阵", () => {
  test.describe.configure({ retries: 1 });
  test.use({ reducedMotion: "reduce" });

  test("coding 首页 1280", async ({ page }) => {
    await openCodingVisual(page, 1280, 720);
    await expect(page.getByTestId("coding-home-ready")).toBeVisible();
    await expect(page).toHaveScreenshot("coding-home-1280.png", { maxDiffPixelRatio: 0.03 });
  });

  test("coding 首页 1440", async ({ page }) => {
    await openCodingVisual(page, 1440);
    await expect(page.getByTestId("coding-home-ready")).toBeVisible();
    await expect(page).toHaveScreenshot("coding-home-1440.png", { maxDiffPixelRatio: 0.03 });
  });

  test("coding 首页 1920", async ({ page }) => {
    await openCodingVisual(page, 1920, 1080);
    await expect(page.getByTestId("coding-home-ready")).toBeVisible();
    await expect(page).toHaveScreenshot("coding-home-1920.png", { maxDiffPixelRatio: 0.03 });
  });

  test("coding 任务页（审批+命令输出）1440", async ({ page }) => {
    await openCodingVisual(page, 1440, 900, "&coding-run-preview=command-output");
    await page.getByTestId("coding-thread-11").click();
    await expect(page.getByTestId("coding-composer-input")).toBeVisible();
    await expect(page.getByTestId("diff-artifact-toggle")).toBeVisible();
    await page.waitForTimeout(300);
    await expect(page).toHaveScreenshot("coding-thread-1440.png", { maxDiffPixelRatio: 0.03 });
  });
});

test.describe("coding é¦é¡µ 1280@125%", () => {
  test.describe.configure({ retries: 1 });
  test.use({ reducedMotion: "reduce", deviceScaleFactor: 1.25 });

  test("coding é¦é¡µ 1280@125%", async ({ page }) => {
    await openCodingVisual(page, 1280, 720);
    await expect(page.getByTestId("coding-home-ready")).toBeVisible();
    await expect(page).toHaveScreenshot("coding-home-1280-at-125.png", { maxDiffPixelRatio: 0.03 });
  });
});

test.describe("coding ä»»å¡é¡µ 1440@150%", () => {
  test.describe.configure({ retries: 1 });
  test.use({ reducedMotion: "reduce", deviceScaleFactor: 1.5 });

  test("coding ä»»å¡é¡µ 1440@150%", async ({ page }) => {
    await openCodingVisual(page, 1440, 900, "&coding-run-preview=command-output");
    await page.getByTestId("coding-thread-11").click();
    await expect(page.getByTestId("coding-composer-input")).toBeVisible();
    await expect(page.getByTestId("diff-artifact-toggle")).toBeVisible();
    await page.waitForTimeout(300);
    await expect(page).toHaveScreenshot("coding-thread-1440-at-150.png", { maxDiffPixelRatio: 0.03 });
  });
});
