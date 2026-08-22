import { test, expect, type Page } from "@playwright/test";

/**
 * v0.8.0 W6-R 试用反馈修订 E2E（RC 重开）
 *
 * 覆盖计划 §7 W6-R 退出条件：
 * 1. 今日页不再出现六个完整工作台面板，主滚动长度不随模块数据增长；
 * 2. 六个侧栏入口鼠标/键盘可达，折叠/窄窗口可识别，深链与刷新后路由正确；
 * 3. Agent 执行期间无需打开诊断页即可看到工具/命令的状态与详细结果；
 * 4. 命令详情含脱敏命令、退出码与耗时；长输出不拖垮页面、不泄露凭据。
 *
 * 后端以 page.route 拦截模拟（仅 127.0.0.1:8000，不误伤 Vite 模块）。
 */

const GREEN_HEALTH = {
  api: true,
  ollama: { ok: true, models: [] },
  mysql: { ok: true },
  chroma: { ok: true },
};

const TODAY_SNAPSHOT = {
  generated_at: "2026-08-22T00:00:00Z",
  summary: {
    due_cards: 0,
    attention_tasks: 0,
    failed_activities: 1,
    draft_memories: 0,
    due_reminders: 2,
    open_inbox: 3,
    last_backup_at: null,
  },
  due_cards: [],
  attention_tasks: [],
  failed_activities: [
    { id: 1, title: "失败活动示例", summary: "", error_message: "mock", due_at: null, source_type: "system", source_id: 1 },
  ],
  draft_memories: [],
  due_reminders: [
    { id: 901, title: "给医生打电话", status: "active", due_at: "2026-08-22T09:00:00" },
    { id: 902, title: "续费域名", status: "active", due_at: "2026-08-22T18:00:00" },
  ],
  open_inbox: [],
  backup: { last_backup_at: null, count: 1 },
  recent_checkins: [],
  recent_briefings: [],
  recent_docs: [],
  recent_sessions: [],
  maintenance: {
    last_backup_at: null,
    backup_count: 1,
    failed_activities: 1,
    draft_memories: 0,
    orphan_evidence: 0,
  },
};

const REMINDERS = [
  {
    id: 901,
    title: "给医生打电话",
    note: null,
    fire_at: "2026-08-22T09:00:00",
    next_fire_at: null,
    recurring: false,
    freq: null,
    interval: null,
    status: "active",
    created_at: "2026-08-21T00:00:00Z",
    updated_at: "2026-08-21T00:00:00Z",
  },
];

const PROJECT_DTO = {
  id: 1,
  name: "PrivateAgent",
  root_path: "C:\\local\\agent-root",
  language: "python",
  framework: null,
  status: "active",
  last_scanned_at: null,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-22T00:00:00Z",
};

const WORKSPACE_DTOS = [
  {
    id: 101,
    project_id: 1,
    kind: "root",
    root_path: "C:\\local\\agent-root",
    branch_name: null,
    head_sha: null,
    status: "active",
    last_used_at: "2026-08-22T01:00:00Z",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-22T01:00:00Z",
  },
];

const CODING_THREAD_DTOS = [
  {
    id: 11,
    title: "修复窄屏侧栏遮挡问题",
    created_at: "2026-08-20T00:00:00Z",
    updated_at: "2026-08-22T02:00:00Z",
    project_id: 1,
    workspace_id: 101,
    kind: "coding",
    last_run_id: null,
    pinned_at: null,
    archived_at: null,
  },
];

function mockW6rApi(page: Page) {
  return page.route("**://127.0.0.1:8000/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
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
    if (path === "/health") {
      await route.fulfill({ json: GREEN_HEALTH });
      return;
    }
    if (path === "/today") {
      await route.fulfill({ json: TODAY_SNAPSHOT });
      return;
    }
    if (path === "/reminders") {
      await route.fulfill({ json: REMINDERS });
      return;
    }
    if (path === "/inbox") {
      await route.fulfill({ json: [] });
      return;
    }
    if (path === "/sessions" && request.method() === "GET") {
      if (url.searchParams.get("kind") === "coding") {
        await route.fulfill({ json: CODING_THREAD_DTOS });
      } else {
        await route.fulfill({ json: [] });
      }
      return;
    }
    if (path === "/projects" && request.method() === "GET") {
      await route.fulfill({ json: [PROJECT_DTO] });
      return;
    }
    if (path === "/projects/1/workspaces" && request.method() === "GET") {
      await route.fulfill({ json: WORKSPACE_DTOS });
      return;
    }
    if (path === "/agent-model-profiles") {
      await route.fulfill({ json: [] });
      return;
    }
    if (path === "/settings") {
      await route.fulfill({ json: { model: "qwen3:4b", provider: "ollama" } });
      return;
    }
    await route.fulfill({ json: {} });
  });
}

const PERSONAL_VIEWS = ["reminders", "inbox", "goals", "briefings", "capture", "privacy"];

test.describe("v0.8.0 W6-R · 试用反馈修订", () => {
  test("六模块迁出今日页：面板消失、侧栏入口到达独立主区、深链刷新保持", async ({ page }) => {
    await mockW6rApi(page);
    await page.goto("/?coding=1");
    await expect(page.getByTestId("coding-sidebar")).toBeVisible({ timeout: 10_000 });

    // 六个侧栏入口渲染且带待处理徽标（今日快照只读数字）
    for (const view of PERSONAL_VIEWS) {
      await expect(page.getByTestId(`coding-personal-${view}`)).toBeVisible();
    }
    await expect(page.getByTestId("coding-personal-badge-reminders")).toHaveText("2");
    await expect(page.getByTestId("coding-personal-badge-inbox")).toHaveText("3");

    // 点击入口进入提醒独立主区（沿用既有业务组件，数据接口保真）
    await page.getByTestId("coding-personal-reminders").click();
    await expect(page.getByText("给医生打电话")).toBeVisible({ timeout: 10_000 });
    // 当前个人页高亮
    await expect(page.getByTestId("coding-personal-reminders")).toHaveAttribute("aria-current", "page");

    // 深链语义：刷新后（本地持久视图）仍停留在提醒独立页
    await page.reload();
    await expect(page.getByText("给医生打电话")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("coding-personal-reminders")).toHaveAttribute("aria-current", "page");

    // 回到今日页：不再内嵌六个完整面板，主滚动区在快速入口后结束
    await page.evaluate(() => window.localStorage.setItem("pa_last_view", "today"));
    await page.reload();
    await expect(page.locator(".today-shell")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".workbench-modules")).toHaveCount(0);
    // 主滚动长度不随六模块数据量增长：页面高度与视口同量级（无长列表模块撑高）
    const scrollHeight = await page.locator(".today-shell").evaluate((el) => el.scrollHeight);
    const clientHeight = await page.locator(".today-shell").evaluate((el) => el.clientHeight);
    expect(scrollHeight).toBeLessThan(clientHeight * 4);
  });

  test("六个侧栏入口键盘可达；折叠态保留可辨识名称", async ({ page }) => {
    await mockW6rApi(page);
    await page.goto("/?coding=1");
    await expect(page.getByTestId("coding-sidebar")).toBeVisible({ timeout: 10_000 });

    // 键盘：focus + Enter 打开收件箱独立主区
    const inboxEntry = page.getByTestId("coding-personal-inbox");
    await inboxEntry.focus();
    await page.keyboard.press("Enter");
    await expect(inboxEntry).toHaveAttribute("aria-current", "page");

    // 逐入口 Tab 可达（六个入口均为可聚焦按钮）
    for (const view of PERSONAL_VIEWS) {
      const entry = page.getByTestId(`coding-personal-${view}`);
      await entry.focus();
      await expect(entry).toBeFocused();
    }

    // 折叠态：图标 + tooltip/aria-label 可识别
    await page.getByTestId("coding-toggle-collapse").click();
    for (const view of PERSONAL_VIEWS) {
      const entry = page.getByTestId(`coding-personal-${view}`);
      await expect(entry).toHaveAttribute("aria-label", /.+/);
    }
  });

  test("窄窗口抽屉模式下六入口仍可识别并导航", async ({ page }) => {
    await page.setViewportSize({ width: 1100, height: 800 });
    await mockW6rApi(page);
    await page.goto("/?coding=1");
    await expect(page.getByTestId("coding-drawer-tab")).toBeVisible({ timeout: 10_000 });
    await page.getByTestId("coding-drawer-tab").click();
    await expect(page.getByTestId("coding-personal-reminders")).toBeVisible();
    await page.getByTestId("coding-personal-reminders").click();
    await expect(page.getByText("给医生打电话")).toBeVisible({ timeout: 10_000 });
  });

  test("执行详情可追溯：脱敏命令/退出码/耗时/测试结果；凭据不外泄；长输出可折叠", async ({ page }) => {
    await mockW6rApi(page);
    await page.goto("/?coding=1&coding-run-preview=command-output");
    await expect(page.getByTestId("coding-thread-11")).toBeVisible({ timeout: 10_000 });
    await page.getByTestId("coding-thread-11").click();

    // 无需打开诊断页：工具卡直接给出脱敏命令、时序与结果摘要
    const toolCommand = page.getByTestId("tool-command");
    await expect(toolCommand).toBeVisible();
    await expect(toolCommand).toContainText("pytest tests");
    await expect(toolCommand).toContainText("[REDACTED]");
    await expect(page.getByTestId("tool-time")).toBeVisible();
    await expect(page.getByTestId("tool-result")).toContainText("12 passed in 3.42s");

    // 命令卡：退出码/耗时/工作目录范围 + 输出默认折叠（长输出不拖垮页面）
    await expect(page.getByTestId("command-exit-code")).toContainText("退出码 0");
    await expect(page.getByTestId("command-duration")).toBeVisible();
    await expect(page.getByTestId("command-cwd")).toContainText("工作目录");
    await expect(page.getByTestId("command-output-body")).toHaveCount(0);
    await page.getByTestId("command-output-toggle").click();
    await expect(page.getByTestId("command-output-body")).toContainText("test session starts");

    // 零容忍：演示凭据不出现在任何可见文本中
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toContain("sk-demo-secret-0001");
  });
});
