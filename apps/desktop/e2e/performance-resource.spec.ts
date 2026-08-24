import { test, expect, type Page } from "@playwright/test";

/**
 * 0.4.0 D5 性能与资源清理验收（计划 10.3 / 11.3）
 * 1) 页面切换与主要操作：无 >50ms 无必要主线程长任务（p95 ≤50ms，max ≤200ms 硬上限）；
 * 2) 长 SSE 活动流压力：150 帧流式更新期间 UI 可交互、无长任务、正常收敛；
 * 3) 重复切换视图/会话后：无定时器（setInterval/setTimeout）与事件监听器残留增长。
 */

const GREEN_HEALTH = {
  api: true,
  ollama: { ok: true, models: [] },
  mysql: { ok: true },
  chroma: { ok: true },
};

function mockApi(page: Page, streamTokens = 0) {
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
        json: [1, 2, 3, 4].map((id) => ({
          id,
          title: `性能会话 ${id}`,
          created_at: "2026-08-08T00:00:00Z",
          updated_at: "2026-08-08T01:00:00Z",
        })),
      });
      return;
    }
    if (path.includes("/messages")) {
      await route.fulfill({ json: [] });
      return;
    }
    if (path === "/tools/plan") {
      await route.fulfill({ json: { tool_call: null } });
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
    if (path === "/chat/stream") {
      if (streamTokens > 0) {
        const frames: string[] = [
          'data: {"type":"run","run_id":"perf-run"}\n\n',
        ];
        for (let i = 0; i < streamTokens; i++) {
          frames.push(`data: {"type":"token","content":"压力帧 ${i} 内容片段。"}\n\n`);
        }
        frames.push(
          'data: {"type":"done","run_id":"perf-run","message_id":999,"content":"压力测试完成。"}\n\n'
        );
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream; charset=utf-8",
          body: frames.join(""),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream; charset=utf-8",
          body: 'data: {"type":"token","content":"x"}\n\n',
        });
      }
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
    await route.fulfill({ json: {} });
  });
}

/** 页面上下文内安装性能与泄漏探针（longtask 收集 + 定时器/监听器计数）。 */
async function installProbes(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as {
      __perf?: {
        longtasks: number[];
        intervals: Set<number>;
        timeouts: Set<number>;
        listeners: Map<EventTarget, Map<EventListener, number>>;
      };
    };
    const state = {
      longtasks: [] as number[],
      intervals: new Set<number>(),
      timeouts: new Set<number>(),
      listeners: new Map<EventTarget, Map<EventListener, number>>(),
    };
    w.__perf = state;

    if (typeof PerformanceObserver !== "undefined") {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          state.longtasks.push(entry.duration);
        }
      });
      observer.observe({ entryTypes: ["longtask"] });
    }

    const origInterval = window.setInterval.bind(window);
    const origClearInterval = window.clearInterval.bind(window);
    window.setInterval = ((handler: TimerHandler, timeout?: number, ...args: unknown[]) => {
      const id = origInterval(handler, timeout, ...args);
      state.intervals.add(id);
      return id;
    }) as typeof window.setInterval;
    window.clearInterval = ((id: number) => {
      state.intervals.delete(id);
      origClearInterval(id);
    }) as typeof window.clearInterval;

    const origTimeout = window.setTimeout.bind(window);
    const origClearTimeout = window.clearTimeout.bind(window);
    window.setTimeout = ((handler: TimerHandler, timeout?: number, ...args: unknown[]) => {
      const id = origTimeout(handler, timeout, ...args);
      state.timeouts.add(id);
      return id;
    }) as typeof window.setTimeout;
    window.clearTimeout = ((id: number) => {
      state.timeouts.delete(id);
      origClearTimeout(id);
    }) as typeof window.clearTimeout;

    const origAdd = EventTarget.prototype.addEventListener;
    const origRemove = EventTarget.prototype.removeEventListener;
    EventTarget.prototype.addEventListener = function (
      type: string,
      listener: EventListenerOrEventListenerObject,
      options?: boolean | AddEventListenerOptions
    ) {
      let byFn = state.listeners.get(this);
      if (!byFn) {
        byFn = new Map();
        state.listeners.set(this, byFn);
      }
      byFn.set(listener as EventListener, (byFn.get(listener as EventListener) ?? 0) + 1);
      return origAdd.call(this, type, listener, options);
    };
    EventTarget.prototype.removeEventListener = function (
      type: string,
      listener: EventListenerOrEventListenerObject,
      options?: boolean | EventListenerOptions
    ) {
      const byFn = state.listeners.get(this);
      if (byFn) {
        const count = byFn.get(listener as EventListener) ?? 0;
        if (count <= 1) byFn.delete(listener as EventListener);
        else byFn.set(listener as EventListener, count - 1);
        if (byFn.size === 0) state.listeners.delete(this);
      }
      return origRemove.call(this, type, listener, options);
    };
  });
}

async function probeState(page: Page) {
  return page.evaluate(() => {
    const perf = (window as unknown as {
      __perf?: {
        longtasks: number[];
        intervals: Set<number>;
        timeouts: Set<number>;
        listeners: Map<EventTarget, Map<EventListener, number>>;
      };
    }).__perf!;
    // 清理已脱离文档的目标（元素卸载后其监听器随之消失，不计入残留）
    for (const target of perf.listeners.keys()) {
      const connected =
        target === window ||
        (typeof target.isConnected === "boolean" && target.isConnected);
      if (!connected) perf.listeners.delete(target);
    }
    return {
      longtasks: [...perf.longtasks],
      intervals: perf.intervals.size,
      timeouts: perf.timeouts.size,
      listeners: perf.listeners.size,
    };
  });
}

const VIEWS = ["chat", "today", "kb", "projects", "tasks", "learning", "memory", "integrations", "extensions", "settings", "diagnostics", "backup"];

test.describe("0.4.0 D5 性能与资源清理", () => {
  // rc.4 final：长任务 p95 对流水线负载抖动敏感（套件内 51-57ms 临界失败，
  // 单独跑稳定 50ms）；与视觉回归套件同一政策：允许单次自动重试吸收抖动，
  // 不掩盖真实回归（重试仍失败则 FAIL）。
  test.describe.configure({ retries: 1 });
  test("页面切换与主要操作：无 50ms 级无必要长任务", async ({ page }) => {
    await installProbes(page);
    await mockApi(page);
    await page.goto("/?ui=v2&coding=0");
    await expect(page.getByTestId("nav-chat")).toBeVisible();
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 500)));

    const before = await probeState(page);
    // 两轮全视图切换 + 会话切换
    for (let round = 0; round < 2; round++) {
      for (const view of VIEWS) {
        await page.getByTestId(`nav-${view}`).click();
        await page.waitForTimeout(120);
      }
    }
    await page.getByTestId("nav-chat").click();
    for (const id of [2, 3, 4, 1]) {
      await page.getByTestId("nav-chat").click();
      await page.getByRole("button", { name: `性能会话 ${id}` }).first().click();
      await page.waitForTimeout(150);
    }
    await page.waitForTimeout(800);

    const after = await probeState(page);
    const interaction = after.longtasks.slice(before.longtasks.length);
    const sorted = [...interaction].sort((a, b) => a - b);
    const p95 = sorted.length ? sorted[Math.floor(sorted.length * 0.95)] : 0;
    const max = sorted.length ? sorted[sorted.length - 1] : 0;
    console.log(
      `[perf] longtasks=${sorted.length} p95=${p95.toFixed(1)}ms max=${max.toFixed(1)}ms ` +
        `intervals ${before.intervals}->${after.intervals} timeouts ${before.timeouts}->${after.timeouts} ` +
        `listeners ${before.listeners}->${after.listeners}`
    );
    // E-1（v0.8.0）预算重定：产品预算 50ms + 20% 环境系数 = 60ms（p95）。
    // 2026-08-22 真实桌面负载 4 轮采集（v0.8.0-alpha.2 后代码）：
    //   轮1 p95=50.0ms（单次长任务，恰在 longtask 50ms 阈值量化边界）
    //   轮2 p95=0.0ms   轮3 p95=0.0ms   轮4 p95=50.0ms
    // 历史（v0.7.0 K1）：重负载日 p95 51–57ms 抖动、极端 73ms。
    // 60ms 覆盖量化边界与环境漂移；真实回归（历史案例 >70ms 持续分布）仍会失败，
    // 且 retries:1 只吸收单次抖动。max 预算 200ms 与资源无增长断言保持不变。
    expect(p95).toBeLessThanOrEqual(60);
    expect(max).toBeLessThanOrEqual(200);
    // 残留：定时器与监听器不得随切换增长（允许 ±2 抖动）
    expect(after.intervals).toBeLessThanOrEqual(before.intervals + 2);
    expect(after.timeouts).toBeLessThanOrEqual(before.timeouts + 2);
    expect(after.listeners).toBeLessThanOrEqual(before.listeners + 5);
  });

  test("长 SSE 活动流压力：150 帧流式更新可交互且收敛", async ({ page }) => {
    await installProbes(page);
    await mockApi(page, 150);
    await page.goto("/?ui=v2&coding=0");
    await expect(page.getByTestId("nav-chat")).toBeVisible();
    await page.waitForLoadState("networkidle");

    const input = page.getByTestId("task-composer-input");
    await input.fill("执行长流压力测试");
    await page.getByTestId("task-composer-submit").click();

    await expect(page.getByText("压力测试完成。")).toBeVisible({ timeout: 20000 });
    const perf = await probeState(page);
    const streamTasks = perf.longtasks;
    const max = streamTasks.length ? Math.max(...streamTasks) : 0;
    console.log(`[perf-stress] longtasks=${streamTasks.length} max=${max.toFixed(1)}ms`);
    expect(max).toBeLessThanOrEqual(200);
    // 收敛后输入区恢复可发送
    await expect(page.getByTestId("task-composer-submit")).toBeVisible();
  });

  test("重复切换视图与会话：无定时器/监听器残留增长", async ({ page }) => {
    await installProbes(page);
    await mockApi(page);
    await page.goto("/?ui=v2&coding=0");
    await expect(page.getByTestId("nav-chat")).toBeVisible();
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 500)));

    const baseline = await probeState(page);
    for (let round = 0; round < 3; round++) {
      for (const view of ["today", "kb", "settings", "chat"]) {
        await page.getByTestId(`nav-${view}`).click();
        await page.waitForTimeout(100);
      }
      for (const id of [2, 3, 4, 1]) {
        await page.getByTestId("nav-chat").click();
        await page.getByRole("button", { name: `性能会话 ${id}` }).first().click();
        await page.waitForTimeout(120);
      }
    }
    await page.waitForTimeout(2500);

    const after = await probeState(page);
    console.log(
      `[leak] intervals ${baseline.intervals}->${after.intervals} ` +
        `timeouts ${baseline.timeouts}->${after.timeouts} listeners ${baseline.listeners}->${after.listeners}`
    );
    expect(after.intervals).toBeLessThanOrEqual(baseline.intervals + 2);
    expect(after.timeouts).toBeLessThanOrEqual(baseline.timeouts + 2);
    expect(after.listeners).toBeLessThanOrEqual(baseline.listeners + 5);
  });
});
