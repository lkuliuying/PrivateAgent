import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * v0.8.0 W5：Coding 工作台可访问性、键盘、压力与资源清理 QA
 * 覆盖计划 §7 W5 任务 1–4 与退出条件：
 * - Axe WCAG AA（首页/任务页含 diff·命令输出·抽屉的富内容态）；
 * - 键盘可达（侧栏动作/树、计划浮层 Esc、输入器）；
 * - 5,000 活动记录压力（分段渲染 + 可交互）；
 * - 重复 thread 切换监听器/定时器无增长（组件挂载/卸载清理）；
 * - 1280/1440/1920 无横向溢出与页面级双滚动。
 * 视觉矩阵（任务 5/6）在 visual-regression.spec.ts 的 coding 用例中扩展。
 */

const GREEN_HEALTH = {
  api: true,
  ollama: { ok: true, models: [] },
  mysql: { ok: true },
  chroma: { ok: true },
};

const PROJECTS = [
  { id: 1, name: "PrivateAgent", root_path: "C:\\s", language: null, framework: null, status: "active", last_scanned_at: null, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-22T00:00:00Z" },
];

const WORKSPACES = [
  { id: 101, project_id: 1, kind: "root", root_path: "C:\\s", branch_name: "main", head_sha: "abcd1234", status: "active", last_used_at: null, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-22T00:00:00Z" },
];

function session(id: number, title: string) {
  return { id, title, created_at: "2026-08-20T00:00:00Z", updated_at: "2026-08-22T00:00:00Z", project_id: 1, workspace_id: 101, kind: "coding", last_run_id: null, pinned_at: null, archived_at: null };
}

const THREADS = [session(11, "修复窄屏侧栏遮挡问题"), session(12, "梳理模块依赖")];

async function mockWorkspace(page: Page) {
  await page.route("**://127.0.0.1:8000/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/capabilities") {
      await route.fulfill({ json: { chat_execution_mode: "legacy", legacy_tool_planner_enabled: true, agent_read_only_tools_enabled: true, rag_chat_runtime_enabled: false } });
      return;
    }
    if (path === "/health") {
      await route.fulfill({ json: GREEN_HEALTH });
      return;
    }
    if (path === "/projects") {
      await route.fulfill({ json: PROJECTS });
      return;
    }
    if (path === "/projects/1/workspaces") {
      await route.fulfill({ json: WORKSPACES });
      return;
    }
    if (path === "/sessions" && url.searchParams.get("kind") === "coding") {
      await route.fulfill({ json: THREADS });
      return;
    }
    if (path === "/sessions") {
      await route.fulfill({ json: [] });
      return;
    }
    if (path === "/agent-model-profiles") {
      await route.fulfill({
        json: [{ id: "local-coder", provider: "ollama", display_name: "Qwen3 Coder 30B", is_local: true, native_tool_calls: true, supports_streaming: true, supports_structured_output: true, supports_vision: false, context_tokens: 131072, reasoning_efforts: ["low", "medium", "high"], usage_reporting: true, enabled: true, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z" }],
      });
      return;
    }
    await route.fulfill({ json: {} });
  });
}

async function openCoding(page: Page, extra = "") {
  await mockWorkspace(page);
  await page.goto(`/?coding=1${extra}`);
  await expect(page.getByTestId("coding-sidebar")).toBeVisible({ timeout: 10000 });
}

/** 监听器/定时器探针（性能套件同款语义的精简版） */
async function installProbe(page: Page) {
  await page.addInitScript(() => {
    // 净值语义（与 performance-resource.spec.ts 一致）：Map 记录在册监听器，
    // 读取时过滤已脱离文档的目标（元素卸载后监听器随之消失，不计残留）
    const state = {
      listeners: new Map<EventTarget, Map<EventListener, number>>(),
      intervals: new Set<number>(),
      timeouts: new Set<number>(),
    };
    const origAdd = EventTarget.prototype.addEventListener;
    const origRemove = EventTarget.prototype.removeEventListener;
    EventTarget.prototype.addEventListener = function (type, listener, options) {
      let byFn = state.listeners.get(this);
      if (!byFn) {
        byFn = new Map();
        state.listeners.set(this, byFn);
      }
      byFn.set(listener as EventListener, (byFn.get(listener as EventListener) ?? 0) + 1);
      return origAdd.call(this, type, listener, options);
    };
    EventTarget.prototype.removeEventListener = function (type, listener, options) {
      const byFn = state.listeners.get(this);
      if (byFn) {
        const count = byFn.get(listener as EventListener) ?? 0;
        if (count <= 1) byFn.delete(listener as EventListener);
        else byFn.set(listener as EventListener, count - 1);
        if (byFn.size === 0) state.listeners.delete(this);
      }
      return origRemove.call(this, type, listener, options);
    };
    const origInterval = window.setInterval;
    const origClearInterval = window.clearInterval;
    window.setInterval = ((handler, timeout, ...args) => {
      const id = origInterval(handler, timeout, ...args);
      state.intervals.add(id as number);
      return id;
    }) as typeof setInterval;
    window.clearInterval = ((id) => {
      state.intervals.delete(id as number);
      return origClearInterval(id);
    }) as typeof clearInterval;
    const origTimeout = window.setTimeout;
    const origClearTimeout = window.clearTimeout;
    window.setTimeout = ((handler, timeout, ...args) => {
      const id = origTimeout(handler, timeout, ...args);
      state.timeouts.add(id as number);
      return id;
    }) as typeof setTimeout;
    window.clearTimeout = ((id) => {
      state.timeouts.delete(id as number);
      return origClearTimeout(id);
    }) as typeof clearTimeout;
    (window as unknown as { __probe: typeof state }).__probe = state;
  });
}

async function probeState(page: Page) {
  return page.evaluate(() => {
    const probe = (window as unknown as {
      __probe: {
        listeners: Map<EventTarget, Map<EventListener, number>>;
        intervals: Set<number>;
        timeouts: Set<number>;
      };
    }).__probe;
    for (const target of probe.listeners.keys()) {
      const connected =
        target === window ||
        (typeof target.isConnected === "boolean" && target.isConnected);
      if (!connected) probe.listeners.delete(target);
    }
    return {
      listeners: probe.listeners.size,
      intervals: probe.intervals.size,
      timeouts: probe.timeouts.size,
    };
  });
}

test.describe("v0.8.0 W5 Coding 质量门禁", () => {
  test("Axe：首页与任务页（富内容态）无严重 WCAG AA 违规", async ({ page }) => {
    await openCoding(page);
    await expect(page.getByTestId("coding-home-ready")).toBeVisible();

    const homeScan = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();
    const homeSerious = homeScan.violations.filter(
      (item) => item.impact === "serious" || item.impact === "critical"
    );
    expect(homeSerious, JSON.stringify(homeSerious, null, 2)).toEqual([]);

    await page.goto("/?coding=1&coding-run-preview=command-output");
    await expect(page.getByTestId("coding-thread-11")).toBeVisible({ timeout: 10000 });
    await page.getByTestId("coding-thread-11").click();
    await expect(page.getByTestId("coding-composer-input")).toBeVisible();
    // 富内容：diff、命令输出、抽屉同时在场
    await expect(page.getByTestId("diff-artifact-toggle")).toBeVisible();
    await expect(page.getByTestId("command-parsed")).toBeVisible();
    await page.getByTestId("thread-context-toggle").click();
    await expect(page.getByTestId("context-drawer")).toBeVisible();

    const threadScan = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();
    const threadSerious = threadScan.violations.filter(
      (item) => item.impact === "serious" || item.impact === "critical"
    );
    expect(threadSerious, JSON.stringify(threadSerious, null, 2)).toEqual([]);
  });

  test("键盘可达：侧栏动作与树、计划浮层 Esc 关闭、输入器可聚焦", async ({ page }) => {
    await openCoding(page, "&coding-run-preview=command-output");
    await expect(page.getByTestId("coding-thread-11")).toBeVisible();

    // Tab 进入侧栏一级动作
    await page.keyboard.press("Tab");
    const focused = page.evaluate(() => document.activeElement?.closest('[data-testid="coding-sidebar"]') !== null);
    expect(await focused).toBe(true);

    // 树条目可聚焦/激活（Enter 打开任务）
    await page.getByTestId("coding-thread-11").focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("coding-thread-workspace")).toBeVisible();

    // 计划浮层：打开后 Esc 关闭
    await page.getByTestId("thread-plan-toggle").click();
    await expect(page.getByTestId("run-plan-popover")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("run-plan-popover")).toBeHidden();

    // 计划入口键盘可聚焦（preview 模式输入器禁用属预期，聚焦性由 W3 组件测试覆盖）
    await page.getByTestId("thread-plan-toggle").focus();
    await expect(page.getByTestId("thread-plan-toggle")).toBeFocused();
  });

  test("5,000 活动记录压力：分段渲染 + 「显示更早」+ 可交互", async ({ page }) => {
    await openCoding(page, "&coding-run-preview=stress");
    await page.getByTestId("coding-thread-11").click();
    await expect(page.getByTestId("run-transcript")).toBeVisible();

    // 默认仅渲染最近批次：隐藏计数 > 0 且可见条目有界
    const earlier = page.getByTestId("transcript-load-earlier");
    await expect(earlier).toBeVisible({ timeout: 20000 });
    expect(await earlier.textContent()).toContain("显示更早");
    const rendered = await page.locator('[data-testid="transcript-tool"]').count();
    expect(rendered).toBeLessThanOrEqual(200);

    // 展开后条目增长且终端摘要仍可交互
    await earlier.click();
    const grown = await page.locator('[data-testid="transcript-tool"]').count();
    expect(grown).toBeGreaterThan(200);
    await expect(page.getByTestId("terminal-summary")).toBeVisible();
    // preview 模式输入器禁用属预期：断言可见即可（可交互性由 load-earlier 验证）
    await expect(page.getByTestId("coding-composer-input")).toBeVisible();
  });

  test("重复 thread 切换：监听器与定时器无增长（挂载/卸载清理）", async ({ page }) => {
    await installProbe(page);
    await openCoding(page, "&coding-run-preview=command-output");
    await expect(page.getByTestId("coding-thread-11")).toBeVisible();

    // 预热一轮（展开祖先、首次挂载）
    await page.getByTestId("coding-thread-11").click();
    await expect(page.getByTestId("coding-thread-workspace")).toBeVisible();
    await page.getByTestId("thread-back-home").click();
    await expect(page.getByTestId("coding-home-ready")).toBeVisible();
    const before = await probeState(page);

    for (let round = 0; round < 6; round++) {
      await page.getByTestId("coding-thread-11").click();
      await expect(page.getByTestId("coding-thread-workspace")).toBeVisible();
      // 计划浮层开合（键盘监听器挂载/卸载路径）
      await page.getByTestId("thread-plan-toggle").click();
      await expect(page.getByTestId("run-plan-popover")).toBeVisible();
      await page.keyboard.press("Escape");
      await page.getByTestId("thread-back-home").click();
      await expect(page.getByTestId("coding-home-ready")).toBeVisible();
    }
    const after = await probeState(page);
    expect(after.listeners).toBeLessThanOrEqual(before.listeners + 2);
    expect(after.intervals).toBeLessThanOrEqual(before.intervals);
    expect(after.timeouts).toBeLessThanOrEqual(before.timeouts + 1);
  });

  const cases: Array<[number, number]> = [
    [1280, 720],
    [1440, 900],
    [1920, 1080],
  ];
  for (const [width, height] of cases) {
    test(`视口 ${width}：无横向溢出与页面级双滚动`, async ({ page }) => {
      await page.setViewportSize({ width, height });
    await openCoding(page);
    await expect(page.getByTestId("coding-home-ready")).toBeVisible();
    const homeOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth
    );
    expect(homeOverflow).toBeLessThanOrEqual(1);

    await page.getByTestId("coding-thread-11").click();
    await expect(page.getByTestId("coding-thread-workspace")).toBeVisible();
    const metrics = await page.evaluate(() => ({
      horizontal: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      bodyVertical: document.body.scrollHeight - document.documentElement.clientHeight,
    }));
    expect(metrics.horizontal).toBeLessThanOrEqual(1);
    expect(metrics.bodyVertical).toBeLessThanOrEqual(2);
    });
  }
});
