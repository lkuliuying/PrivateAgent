import { expect, test, type Page } from "@playwright/test";

const now = new Date().toISOString();

const todaySnapshot = {
  generated_at: now,
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

const workflowTask = {
  id: 21,
  session_id: null,
  title: "发布前验证 Agent 动画",
  goal: "验证连接、执行与完成状态",
  status: "running",
  plan_json: null,
  final_report_md: null,
  created_at: now,
  updated_at: now,
  evidence: [],
  steps: [
    {
      id: 211,
      task_id: 21,
      ordinal: 1,
      title: "读取工作区",
      tool_name: "read_file",
      status: "succeeded",
      tool_call_id: 51,
      input_json: {},
      output_json: { ok: true },
      error_message: null,
      started_at: now,
      finished_at: now,
      created_at: now,
    },
    {
      id: 212,
      task_id: 21,
      ordinal: 2,
      title: "执行构建",
      tool_name: "run_command",
      status: "running",
      tool_call_id: 52,
      input_json: {},
      output_json: null,
      error_message: null,
      started_at: now,
      finished_at: null,
      created_at: now,
    },
    {
      id: 213,
      task_id: 21,
      ordinal: 3,
      title: "归档证据",
      tool_name: null,
      status: "planned",
      tool_call_id: null,
      input_json: {},
      output_json: null,
      error_message: null,
      started_at: null,
      finished_at: null,
      created_at: now,
    },
  ],
};

interface MockOptions {
  includePendingTool?: boolean;
  streamDelayMs?: number;
  approveDelayMs?: number;
}

async function navigate(page: Page, view: string) {
  const target = page.getByTestId(`nav-${view}`);
  if (await target.count()) {
    await target.click();
    return;
  }

  await page.getByTestId("nav-utilities-toggle").click();
  await page.getByTestId(`nav-${view}`).click();
}

async function mockApi(page: Page, options: MockOptions = {}) {
  const {
    includePendingTool = true,
    streamDelayMs = 0,
    approveDelayMs = 0,
  } = options;
  await page.route("**://127.0.0.1:8000/**", async (route) => {
    const url = route.request().url();
    const path = new URL(url).pathname;
    if (path.endsWith("/chat/stream")) {
      if (streamDelayMs) await new Promise((resolve) => setTimeout(resolve, streamDelayMs));
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          'data: {"type":"token","content":"状态"}\n\n' +
          'data: {"type":"done","message_id":81,"content":"状态切换完成"}\n\n',
      });
      return;
    }

    if (path.endsWith("/tool-calls/61/approve")) {
      if (approveDelayMs) await new Promise((resolve) => setTimeout(resolve, approveDelayMs));
      await route.fulfill({
        json: {
          id: 61,
          session_id: 1,
          task_id: null,
          step_id: null,
          tool_name: "read_file",
          risk_level: "confirm",
          status: "succeeded",
          input_json: { path: "README.md" },
          output_json: {
            path: "README.md",
            size_bytes: 18,
            content: "Tool 动画验收内容",
            truncated: false,
          },
          error_message: null,
          created_at: now,
          updated_at: now,
        },
      });
      return;
    }

    let json: unknown = [];
    if (url.endsWith("/today")) json = todaySnapshot;
    else if (url.endsWith("/agent-tasks")) json = [workflowTask];
    else if (url.endsWith("/projects")) json = [];
    else if (url.endsWith("/sessions")) {
      json = [{ id: 1, title: "动画验收会话", created_at: now, updated_at: now }];
    } else if (url.includes("/sessions/1/messages")) {
      json = [
        { id: 1, session_id: 1, role: "user", content: "检查动画系统", created_at: now },
        { id: 2, session_id: 1, role: "assistant", content: "动画层已加载。", created_at: now },
      ];
    } else if (path.endsWith("/tools/plan")) {
      json = { tool_call: null };
    } else if (url.includes("/tool-calls")) {
      json = includePendingTool ? [
        {
          id: 61,
          session_id: 1,
          task_id: null,
          step_id: null,
          tool_name: "read_file",
          risk_level: "confirm",
          status: "pending_approval",
          input_json: { path: "README.md" },
          output_json: null,
          error_message: null,
          created_at: now,
          updated_at: now,
        },
      ] : [];
    }
    await route.fulfill({ json } as never);
  });
}

test.describe("anime.js motion system", () => {
  test("Agent card hover uses transform, shadow and border glow", async ({ page }) => {
    await mockApi(page);
    await page.goto("/?coding=0");

    const card = page.locator("[data-agent-card]").first();
    await expect(card).toBeVisible();
    await card.hover();
    await page.waitForTimeout(320);
    const style = await card.evaluate((element) => {
      const computed = getComputedStyle(element);
      return {
        transform: computed.transform,
        shadow: computed.boxShadow,
        border: computed.borderColor,
      };
    });

    // D0 冻结：高密度卡片 hover 位移 0–2px 且不缩放（transform 仍生效）
    expect(style.transform).not.toBe("none");
    const match = style.transform.match(/matrix3d\(([^)]+)\)|matrix\(([^)]+)\)/);
    const values = (match?.[1] ?? match?.[2] ?? "").split(",").map(Number);
    const ty = values.length === 16 ? values[13] : values.length === 6 ? values[5] : 0;
    expect(Math.abs(ty)).toBeGreaterThan(0);
    expect(Math.abs(ty)).toBeLessThanOrEqual(4);
    expect(style.shadow).not.toBe("none");
    expect(style.border).not.toBe("");
  });

  test("reduced motion keeps the interface stable", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApi(page);
    await page.goto("/?coding=0");

    const card = page.locator("[data-agent-card]").first();
    await expect(card).toBeVisible();
    // 先滚动到可见再测量，避免 hover 隐式滚动改变坐标
    await card.scrollIntoViewIfNeeded();
    const before = await card.boundingBox();
    await card.hover();
    await page.waitForTimeout(320);
    const after = await card.boundingBox();

    expect(after?.x).toBeCloseTo(before!.x, 1);
    expect(after?.y).toBeCloseTo(before!.y, 1);
    expect(after?.width).toBeCloseTo(before!.width, 1);
  });

  test("workflow draws SVG paths, activates a node and reveals checks", async ({ page }) => {
    await mockApi(page);
    await page.goto("/?coding=0");
    await navigate(page, "tasks");

    const steps = page.locator("[data-workflow-step]");
    await expect(steps).toHaveCount(3);
    await page.waitForTimeout(700);
    await expect(steps.nth(0).locator("[data-workflow-check-path]")).toBeVisible();
    await expect(steps.nth(1)).toHaveAttribute("data-workflow-state", "running");

    const activeNodeTransform = await steps
      .nth(1)
      .locator("[data-workflow-node]")
      .evaluate((element) => getComputedStyle(element).transform);
    const pathDash = await steps
      .nth(0)
      .locator("[data-workflow-path]")
      .evaluate((element) => getComputedStyle(element).strokeDasharray);
    const brainTransform = await page
      .locator("[data-agent-brain]")
      .evaluate((element) => getComputedStyle(element).transform);

    expect(activeNodeTransform).not.toBe("none");
    expect(pathDash).not.toBe("none");
    expect(brainTransform).not.toBe("none");
  });

  test("chat messages and tool calls mount through the isolated animation layer", async ({ page }) => {
    await mockApi(page);
    await page.goto("/?ui=v1");
    await navigate(page, "chat");

    await expect(page.locator("[data-chat-message]")).toHaveCount(3);
    await expect(page.locator(".tool-card[data-agent-card]")).toBeVisible();
    await expect(page.locator("[data-tool-section]")).toBeVisible();
    await expect(page.locator("[data-agent-state]").last()).toHaveAttribute(
      "data-agent-state",
      "idle"
    );

    const assistantResponse = page.locator(".agent-response").first();
    await assistantResponse.evaluate((element) => {
      element.classList.add("is-streaming");
      const text = element.querySelector(".response-copy")?.firstChild;
      if (text) text.textContent = `${text.textContent} 正在渐进更新`;
    });
    await page.waitForFunction(
      (element) => Number(getComputedStyle(element).opacity) < 0.999,
      await assistantResponse.elementHandle()
    );
    await page.waitForTimeout(180);
    await expect
      .poll(() => assistantResponse.evaluate((element) => Number(getComputedStyle(element).opacity)))
      .toBeCloseTo(1, 2);
  });

  test("Thinking state transitions through a real chat action", async ({ page }) => {
    await mockApi(page, {
      includePendingTool: false,
      streamDelayMs: 650,
    });
    await page.goto("/?ui=v1");
    await navigate(page, "chat");

    await page.getByTestId("task-composer-input").fill("触发 Thinking 状态");
    await page.getByTestId("task-composer-submit").click();

    const thinkingMarker = page.locator('[data-agent-state="thinking"]');
    await expect(thinkingMarker).toBeVisible();
    await page.waitForTimeout(120);
    const thinkingTransform = await thinkingMarker.evaluate(
      (element) => getComputedStyle(element).transform
    );
    expect(thinkingTransform).not.toBe("none");

    await expect(thinkingMarker).toHaveCount(0, { timeout: 2_000 });
    await expect(page.locator(".agent-response .response-state").last()).toBeVisible();
  });

  test("Tool approval drives Executing flow, disclosure motion and cleanup", async ({ page }) => {
    await mockApi(page, {
      approveDelayMs: 650,
      streamDelayMs: 1_200,
    });
    await page.goto("/?ui=v1");
    await navigate(page, "chat");
    await page.getByRole("button", { name: "批准执行" }).click();

    const executingCard = page.locator('.tool-card[data-agent-state="executing"]');
    await expect(executingCard).toBeVisible();
    await page.waitForTimeout(180);
    const executingTransform = await executingCard.evaluate(
      (element) => getComputedStyle(element).transform
    );
    expect(executingTransform).not.toBe("none");

    const disclosure = page.locator("[data-tool-disclosure]");
    await expect(disclosure).toBeVisible({ timeout: 2_000 });
    const panel = disclosure.locator("[data-tool-panel]");
    await expect(panel).toBeAttached({ timeout: 2_000 });
    if (await disclosure.evaluate((element) => (element as HTMLDetailsElement).open)) {
      await disclosure.locator("summary").click();
    }
    await disclosure.locator("summary").click();
    await page.waitForFunction(
      (element) => Number(getComputedStyle(element).opacity) < 0.999,
      await panel.elementHandle()
    );
    await page.waitForTimeout(300);
    await expect
      .poll(() => panel.evaluate((element) => Number(getComputedStyle(element).opacity)))
      .toBeCloseTo(1, 2);

    const idleCard = page.locator('.tool-card[data-agent-state="idle"]');
    await expect(idleCard).toBeVisible();
    const detachedCard = await idleCard.elementHandle();
    await navigate(page, "today");
    await expect
      .poll(() => detachedCard!.evaluate((element) => element.isConnected))
      .toBe(false);
    await expect
      .poll(() => detachedCard!.evaluate((element) => element.getAttribute("style") ?? ""))
      .not.toContain("transform");
    await expect
      .poll(() => detachedCard!.evaluate((element) => element.getAttribute("style") ?? ""))
      .not.toContain("opacity");
  });
});
