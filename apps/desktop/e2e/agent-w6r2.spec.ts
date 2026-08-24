import { test, expect, type Page } from "@playwright/test";

/**
 * v0.8.0 W6-R2 · 第二轮试用反馈修订 E2E
 *
 * 覆盖计划 §7 W6-R2 退出条件：
 * 1. 今日页无 Agent 输入框/发送按钮；搜索入口加长且 1280/1440/1920 无溢出；
 * 2. 提醒摘要在上下文中心下方，有界条目，入口进提醒独立页；
 * 3. Agent 页左会话/右工作区宽屏稳定；切换/抽屉/草稿/键盘；
 * 4. 模型/推理/三档权限绑定真实契约，不支持能力有明确禁用态；
 * 5. 每轮公开过程可复查；最终回答一键复制（内容与可见回答一致）；
 * 6. 窄窗口会话栏抽屉可用。
 *
 * 后端以 page.route 拦截模拟（仅 127.0.0.1:8000，不误伤 Vite 模块）。
 */

const GREEN_HEALTH = {
  api: true,
  ollama: { ok: true, models: [] },
  mysql: { ok: true },
  chroma: { ok: true },
};

const SETTINGS = {
  llm_model: "qwen3:4b",
  embed_model: "bge-m3",
  llm_temperature: 0.2,
  llm_context_length: 8192,
  kb_enabled_by_default: false,
  provider_type: "ollama",
  remote_provider_enabled: false,
  openai_api_key_configured: false,
  openai_base_url: "",
  openai_model: "",
  claude_api_key_configured: false,
  claude_model: "",
  reminders_enabled: true,
  reminder_tick_seconds: 60,
};

const SESSIONS = [
  { id: 1, title: "整理发布材料", created_at: "2026-08-21T00:00:00Z", updated_at: "2026-08-21T01:00:00Z" },
  { id: 2, title: "修复窄窗口布局", created_at: "2026-08-22T00:00:00Z", updated_at: "2026-08-22T02:00:00Z" },
];

const LONG_ANSWER =
  "最终回答第一行。\n" +
  Array.from({ length: 400 }, (_, i) => `过程记录行 ${i + 1}`).join("\n") +
  "\n最终回答结束行。";

const MESSAGES_2 = [
  {
    id: 11,
    session_id: 2,
    role: "user",
    content: "帮我确认构建状态",
    created_at: "2026-08-22T02:01:00Z",
  },
  {
    id: 12,
    session_id: 2,
    role: "assistant",
    content: LONG_ANSWER,
    created_at: "2026-08-22T02:02:00Z",
  },
  {
    id: 13,
    session_id: 2,
    role: "user",
    content: "再来一轮",
    created_at: "2026-08-22T02:03:00Z",
  },
];

const TODAY_SNAPSHOT = {
  generated_at: "2026-08-22T00:00:00Z",
  summary: {
    due_cards: 0,
    attention_tasks: 0,
    failed_activities: 0,
    draft_memories: 0,
    due_reminders: 4,
    open_inbox: 0,
    last_backup_at: null,
  },
  due_cards: [],
  attention_tasks: [],
  failed_activities: [],
  draft_memories: [],
  due_reminders: [
    { id: 1, title: "提醒甲", status: "active", due_at: "2026-08-22T09:00:00" },
    { id: 2, title: "提醒乙", status: "active", due_at: "2026-08-22T10:00:00" },
    { id: 3, title: "提醒丙", status: "active", due_at: "2026-08-22T11:00:00" },
    { id: 4, title: "提醒丁", status: "active", due_at: "2026-08-22T12:00:00" },
  ],
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

function mockW6r2Api(page: Page) {
  return page.route("**://127.0.0.1:8000/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/capabilities") {
      await route.fulfill({
        json: {
          chat_execution_mode: "agent_runtime",
          legacy_tool_planner_enabled: false,
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
    if (path === "/settings") {
      await route.fulfill({ json: SETTINGS });
      return;
    }
    if (path === "/today") {
      await route.fulfill({ json: TODAY_SNAPSHOT });
      return;
    }
    if (path === "/sessions" && request.method() === "GET") {
      await route.fulfill({ json: SESSIONS });
      return;
    }
    if (/^\/sessions\/\d+\/messages$/.test(path)) {
      const id = Number(path.split("/")[2]);
      await route.fulfill({ json: id === 2 ? MESSAGES_2 : [] });
      return;
    }
    if (
      path.includes("/tool-calls") ||
      path.includes("/trusted-paths") ||
      path.includes("/activities") ||
      path.includes("/reminders") ||
      path.includes("/inbox")
    ) {
      await route.fulfill({ json: [] });
      return;
    }
    await route.fulfill({ json: {} });
  });
}

test.describe("v0.8.0 W6-R2 · 第二轮试用反馈修订", () => {
  test("今日页二次精简：无 Agent 输入/发送；搜索加长；提醒摘要有界且可跳转", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockW6r2Api(page);
    await page.goto("/?ui=v2&coding=0");
    await page.getByTestId("nav-today").click();

    // 退出条件 1：DOM 与键盘路径中不再存在 Agent 输入框/发送按钮
    await expect(page.locator("#today-composer-input")).toHaveCount(0);
    await expect(page.locator(".today-composer")).toHaveCount(0);

    // 搜索入口加长（1440 下目标 360–560px 量级），键盘可聚焦
    const search = page.locator(".command-entry");
    await expect(search).toBeVisible();
    const box = await search.boundingBox();
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(360);
    expect(box?.width ?? 0).toBeLessThanOrEqual(560);
    await search.focus();
    await expect(search).toBeFocused();

    // 退出条件 2：提醒摘要位于上下文中心下方（右侧栏），有界条目
    const summary = page.getByTestId("today-reminder-summary");
    await expect(summary).toBeVisible();
    expect(await page.getByTestId("today-reminder-item").count()).toBeLessThanOrEqual(3);
    await expect(page.getByTestId("today-reminder-count")).toContainText("4");
    // 查看全部/新建提醒进入提醒独立页，今日页不重复完整提醒管理
    await page.getByTestId("today-reminder-all").click();
    await expect(page.locator(".personal-view")).toBeVisible();
    await expect(page.getByTestId("nav-reminders")).toHaveAttribute("aria-current", "page");
  });

  test("今日页搜索在 1280/1920 下使用更多头部宽度且无横向溢出", async ({ page }) => {
    for (const width of [1280, 1920]) {
      await page.setViewportSize({ width, height: 900 });
      await mockW6r2Api(page);
      await page.goto("/?ui=v2&coding=0");
      await page.getByTestId("nav-today").click();
      const box = await page.locator(".command-entry").boundingBox();
      expect(box?.width ?? 0).toBeGreaterThanOrEqual(300);
      const overflow = await page.evaluate(() => ({
        body: document.body.scrollWidth,
        viewport: window.innerWidth,
      }));
      expect(overflow.body).toBeLessThanOrEqual(overflow.viewport);
    }
  });

  test("Agent 页两区结构：左真实会话列表/右工作区；切换/草稿/模型与权限契约", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockW6r2Api(page);
    await page.goto("/?ui=v2&coding=0");
    await page.getByTestId("nav-chat").click();

    // 左栏：真实会话（含标题与运行/选中态），右区：头部/逐轮/输入器
    await expect(page.getByTestId("agent-conversations")).toBeVisible();
    await expect(page.getByTestId("agent-conversation-1")).toBeVisible();
    await expect(page.getByTestId("agent-conversation-2")).toBeVisible();
    await expect(page.getByTestId("session-header")).toBeVisible();
    await expect(page.getByTestId("turn-transcript")).toBeVisible();

    // 模型：来自公开配置事实；配置入口在底部（不在组件读写密钥）
    await expect(page.getByTestId("composer-model-entry")).toContainText("qwen3:4b");
    await expect(page.getByTestId("composer-model-entry")).toContainText("本地");
    // W6-R3：顶部模型 chip 与上下文按钮已移除（不残留隐藏 DOM）
    await expect(page.getByTestId("session-model")).toHaveCount(0);
    await expect(page.getByTestId("session-context-toggle")).toHaveCount(0);

    // 权限三档（下拉）：总是询问可选；替我批准/完全访问禁用且不伪装可用
    const permission = page.getByTestId("composer-permission-select");
    await expect(permission).toBeVisible();
    await expect(permission.locator("option").nth(0)).not.toHaveAttribute("disabled", "");
    await expect(permission.locator("option").nth(1)).toHaveAttribute("disabled", "");
    await expect(permission.locator("option").nth(2)).toHaveAttribute("disabled", "");
    await expect(permission.locator("option").nth(2)).toContainText("不可用");
    // 推理强度控件已随 W6-R3 重排移除（不残留空占位）
    await expect(page.getByTestId("composer-reasoning")).toHaveCount(0);
    // 上下文用量圆环存在（v0.9.0：真实 typed budget 或不可用态，不伪造百分比）
    await expect(page.getByTestId("context-usage-ring")).toBeVisible();

    // 会话切换：选中态迁移，消息按会话加载（会话 2 有历史）
    await page.getByTestId("agent-conversation-2").click();
    await expect(page.getByTestId("agent-conversation-2")).toHaveAttribute("aria-current", "page");
    await expect(page.getByText("帮我确认构建状态")).toBeVisible({ timeout: 10000 });
  });

  test("键盘可达：会话列表 → 切换会话 → 回到输入器", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockW6r2Api(page);
    await page.goto("/?ui=v2&coding=0");
    await page.getByTestId("nav-chat").click();
    await expect(page.getByTestId("agent-conversations")).toBeVisible();

    // Tab/焦点进入会话列表并回车切换会话
    await page.getByTestId("agent-conversation-2").focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("agent-conversation-2")).toHaveAttribute("aria-current", "page");

    // 回到输入器（可聚焦并可输入）
    const input = page.getByTestId("task-composer-input");
    await input.focus();
    await expect(input).toBeFocused();
    await input.fill("键盘输入内容");
    await expect(input).toHaveValue("键盘输入内容");

    // 模型/权限控件均可被键盘聚焦（W6-R3：权限下拉）
    await page.getByTestId("composer-permission-select").focus();
    await expect(page.getByTestId("composer-permission-select")).toBeFocused();
    await page.getByTestId("composer-model-entry").focus();
    await expect(page.getByTestId("composer-model-entry")).toBeFocused();
  });

  test("逐轮分组与回答复制：内容与可见最终回答一致，不混入过程/按钮", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockW6r2Api(page);
    await page.goto("/?ui=v2&coding=0");
    await page.getByTestId("nav-chat").click();
    await page.getByTestId("agent-conversation-2").click();
    await expect(page.getByText("帮我确认构建状态")).toBeVisible({ timeout: 10000 });

    // 两个用户消息 → 两个稳定 turn 容器；第一轮完成后提供复制按钮
    await expect(page.getByTestId("turn-0")).toBeVisible();
    await expect(page.getByTestId("turn-1")).toBeVisible();
    await expect(page.getByTestId("turn-copy-0")).toBeVisible();

    // 长回答：主时间线独立滚动，不产生页面级横向滚动
    const overflow = await page.evaluate(() => ({
      body: document.body.scrollWidth,
      viewport: window.innerWidth,
    }));
    expect(overflow.body).toBeLessThanOrEqual(overflow.viewport);

    // 复制：剪贴板内容 = 完整最终回答正文（含换行），不含按钮文案/过程混淆字段
    await page.getByTestId("turn-copy-0").click();
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    expect(clip.startsWith("最终回答第一行。")).toBe(true);
    expect(clip.endsWith("最终回答结束行。")).toBe(true);
    expect(clip).not.toContain("复制回答");
    // 成功提示固定文案，通知不含回答正文
    await expect(page.getByText("回答已复制")).toBeVisible();
  });

  test("窄窗口（<1280）会话栏折叠为抽屉，可打开并切换会话", async ({ page }) => {
    await page.setViewportSize({ width: 1100, height: 800 });
    await mockW6r2Api(page);
    await page.goto("/?ui=v2&coding=0");
    await page.getByTestId("nav-chat").click();

    await expect(page.getByTestId("agent-conversations-tab")).toBeVisible();
    await expect(page.getByTestId("agent-conversations")).toHaveCount(0);
    await page.getByTestId("agent-conversations-tab").click();
    await expect(page.getByTestId("agent-conversations")).toBeVisible();
    await page.getByTestId("agent-conversation-2").click();
    // 选择后抽屉收起，右工作区加载该会话
    await expect(page.getByTestId("agent-conversations")).toHaveCount(0);
    await expect(page.getByText("帮我确认构建状态")).toBeVisible({ timeout: 10000 });
  });
});
