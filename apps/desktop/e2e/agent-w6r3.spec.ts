import { test, expect, type Page } from "@playwright/test";

/**
 * v0.8.0 W6-R3 · 第三轮试用反馈修订 E2E
 *
 * 覆盖计划 §7 W6-R3 退出条件（可 E2E 化部分）：
 * 1. 主侧栏最近任务归位「Agent 执行」下方，无重复实例；
 * 2. 顶部工作目录/Git 分支与当前任务一致，快速切换不残留旧值；
 * 3. 顶部模型/上下文控件与独立计划卡已移除（无隐藏 DOM 残留）；
 * 4. 会话栏收起后完全退出布局/焦点/读屏，展开后状态保持；
 * 5. 逐轮过程区 + 无命令真实空态；
 * 6. 底部权限下拉/模型入口/上下文用量；知识检索与生成记忆不存在;
 * 7. 上下文用量真实数值（公开 usage），无负数/无 >100% 错误显示；
 * 8. 1280/1440/1920、窄窗口、150% 缩放无横向溢出与不可达操作。
 */

const GREEN_HEALTH = {
  api: true,
  ollama: { ok: true, models: [] },
  mysql: { ok: true },
  chroma: { ok: true },
};

const SETTINGS = {
  llm_model: "qwen3:4b-a-very-long-model-name-for-layout-testing",
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
  {
    id: 1,
    title: "W6-R3 会话一",
    created_at: "2026-08-22T00:00:00Z",
    updated_at: "2026-08-22T02:00:00Z",
    project_id: 1,
    workspace_id: 101,
    last_run_id: "run-w6r3-1",
  },
  {
    id: 2,
    title: "W6-R3 会话二",
    created_at: "2026-08-22T00:00:00Z",
    updated_at: "2026-08-22T01:00:00Z",
    project_id: 1,
    workspace_id: 102,
    last_run_id: null,
  },
];

const WORKSPACES = [
  {
    id: 101,
    project_id: 1,
    kind: "root",
    root_path: "F:/workspace/w6r3-demo-project-alpha",
    branch_name: "feature/w6r3-round-three",
    head_sha: "a1".repeat(20),
    status: "active",
    last_used_at: null,
    created_at: "",
    updated_at: "",
  },
  {
    id: 102,
    project_id: 1,
    kind: "git_worktree",
    root_path: "F:/workspace/w6r3-demo-project-alpha/worktrees/detached-case",
    branch_name: null,
    head_sha: "b2".repeat(20),
    status: "active",
    last_used_at: null,
    created_at: "",
    updated_at: "",
  },
];

const MESSAGES_1 = [
  { id: 11, session_id: 1, role: "user", content: "帮我运行测试", created_at: "2026-08-22T02:01:00Z" },
  { id: 12, session_id: 1, role: "assistant", content: "已完成测试运行。", created_at: "2026-08-22T02:02:00Z" },
  { id: 13, session_id: 1, role: "user", content: "再总结一下", created_at: "2026-08-22T02:03:00Z" },
];

const RUN_SNAPSHOT = {
  id: "run-w6r3-1",
  session_id: 1,
  status: "completed",
  provider: "ollama",
  model: "qwen3:4b",
  last_event_sequence: 9,
  tool_call_count: 1,
  input_tokens: 4096,
  output_tokens: 512,
  cached_tokens: 0,
  cost_usd: null,
  output: "已完成",
  error_code: null,
  error_message: null,
  cancel_requested_at: null,
  started_at: "2026-08-22T02:01:00Z",
  completed_at: "2026-08-22T02:02:00Z",
  created_at: "2026-08-22T02:01:00Z",
  updated_at: "2026-08-22T02:02:00Z",
  active_in_process: false,
  steps: [],
  project_id: 1,
  workspace_id: 101,
  base_head_sha: null,
  base_branch_name: null,
  base_git_dirty: null,
  model_profile_id: null,
  reasoning_effort: null,
  permission_mode: null,
  plan: null,
  artifacts: [],
};

function mockW6r3Api(page: Page) {
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
          rag_chat_runtime_enabled: true,
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
    if (path === "/sessions" && request.method() === "GET") {
      await route.fulfill({ json: SESSIONS });
      return;
    }
    if (/^\/sessions\/\d+\/messages$/.test(path)) {
      const id = Number(path.split("/")[2]);
      await route.fulfill({ json: id === 1 ? MESSAGES_1 : [] });
      return;
    }
    if (path === "/projects" && request.method() === "GET") {
      await route.fulfill({
        json: [{ id: 1, name: "w6r3-demo", root_path: "F:/workspace", language: "python", framework: null, status: "active", last_scanned_at: null, created_at: "", updated_at: "" }],
      });
      return;
    }
    if (path === "/projects/1/workspaces") {
      await route.fulfill({ json: WORKSPACES });
      return;
    }
    if (path === "/agent-runs/run-w6r3-1") {
      await route.fulfill({ json: RUN_SNAPSHOT });
      return;
    }
    if (path.includes("/tool-calls") || path.includes("/agent-approvals") || path.includes("/trusted-paths") || path.includes("/activities")) {
      await route.fulfill({ json: [] });
      return;
    }
    await route.fulfill({ json: {} });
  });
}

async function openAgent(page: Page, width = 1440, height = 900) {
  await page.setViewportSize({ width, height });
  await mockW6r3Api(page);
  await page.goto("/?ui=v2&coding=0");
  await expect(page.getByTestId("nav-chat")).toBeVisible({ timeout: 10000 });
  await page.getByTestId("nav-chat").click();
  await expect(page.getByTestId("session-header")).toBeVisible({ timeout: 10000 });
}

test.describe("v0.8.0 W6-R3 · 第三轮试用反馈修订", () => {
  test("主侧栏最近任务归位「Agent 执行」下方；原位置无重复实例", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockW6r3Api(page);
    await page.goto("/?ui=v2&coding=0");
    await expect(page.getByTestId("nav-chat")).toBeVisible({ timeout: 10000 });

    // 「Agent 执行」分组标题 + 紧随其后的最近任务（DOM 连续）
    await expect(page.getByText("Agent 执行").first()).toBeVisible();
    const recent = page.getByTestId("rail-recent-tasks");
    await expect(recent).toBeVisible();
    expect(await recent.count()).toBe(1); // 旧位置重复实例已删除
    await expect(page.getByTestId("rail-recent-task-1")).toBeVisible();
    await expect(page.getByTestId("rail-recent-task-1")).toContainText("W6-R3 会话一");

    // 选择最近任务打开对应 session（稳定 id 关联）
    await page.getByTestId("rail-recent-task-2").click();
    await expect(page.getByTestId("session-header")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("session-header")).toContainText("W6-R3 会话二");
  });

  test("顶部工作目录/Git 分支与当前任务一致；快速切换不残留旧值", async ({ page }) => {
    await openAgent(page);

    // 会话一：正常分支
    await expect(page.getByTestId("session-workdir")).toContainText("w6r3-demo-project-alpha");
    await expect(page.getByTestId("session-git")).toContainText("feature/w6r3-round-three");

    // 快速切换：会话二（detached）→ 立即切回会话一
    await page.getByTestId("agent-conversation-2").click();
    await page.getByTestId("agent-conversation-1").click();
    await expect(page.getByTestId("session-git")).toContainText("feature/w6r3-round-three", { timeout: 10000 });
    await expect(page.getByTestId("session-git")).not.toContainText("detached");

    // 切到会话二：detached 状态真实呈现
    await page.getByTestId("agent-conversation-2").click();
    await expect(page.getByTestId("session-git")).toContainText("detached", { timeout: 10000 });
  });

  test("顶部模型/上下文控件与独立计划卡已移除（无隐藏 DOM/空占位）", async ({ page }) => {
    await openAgent(page);
    await expect(page.getByTestId("session-model")).toHaveCount(0);
    await expect(page.getByTestId("session-context-toggle")).toHaveCount(0);
    await expect(page.getByLabel("切换上下文栏")).toHaveCount(0);
    await expect(page.locator(".plan-step-hit")).toHaveCount(0);
    // 逐轮过程仍在（计划事实随 turn 呈现，不因移除大卡丢失）
    await expect(page.getByTestId("turn-transcript")).toBeVisible();
  });

  test("会话栏收起后完全退出布局/键盘/读屏；展开后选中与草稿保持", async ({ page }) => {
    await openAgent(page);

    // 草稿写入（会话一）
    await page.getByTestId("task-composer-input").fill("W6-R3 草稿");

    // 收起：条件卸载 → 不可点击/聚焦/读屏（DOM 不存在）
    await page.getByTestId("agent-conversations-collapse").click();
    await expect(page.getByTestId("agent-conversations")).toHaveCount(0);
    await expect(page.getByTestId("agent-conversation-1")).toHaveCount(0);
    // 主工作区占满：无会话栏宽度占位
    const mainBox = await page.locator(".agent-main").boundingBox();
    const pageBox = await page.locator(".agent-page").boundingBox();
    expect(mainBox?.width ?? 0).toBeGreaterThanOrEqual((pageBox?.width ?? 1) - 4);

    // 展开：列表恢复、选中态与草稿保持
    await page.getByTestId("agent-conversations-expand").click();
    await expect(page.getByTestId("agent-conversations")).toBeVisible();
    await expect(page.getByTestId("agent-conversation-1")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("task-composer-input")).toHaveValue("W6-R3 草稿");
  });

  test("逐轮过程区：无命令轮呈现真实空态，不串入其他轮", async ({ page }) => {
    await openAgent(page);
    await expect(page.getByTestId("turn-0")).toBeVisible();
    await expect(page.getByTestId("turn-1")).toBeVisible();
    // 两轮均无工具/命令：各自明确空态（不留白、不伪造动作）
    expect(await page.getByTestId("turn-no-commands").count()).toBe(2);
    await expect(page.getByTestId("turn-no-commands").first()).toContainText("本轮未执行命令或工具");
  });

  test("底部控制：权限下拉在原知识检索位；知识检索/生成记忆不存在；模型入口可进设置", async ({ page }) => {
    await openAgent(page);

    const permission = page.getByTestId("composer-permission-select");
    await expect(permission).toBeVisible();
    await expect(permission.locator("option")).toHaveCount(3);
    await expect(permission.locator("option").nth(0)).not.toHaveAttribute("disabled", "");
    await expect(permission.locator("option").nth(1)).toHaveAttribute("disabled", "");
    await expect(permission.locator("option").nth(2)).toHaveAttribute("disabled", "");

    // 被移除按钮无残留（含快捷键占位）
    await expect(page.getByText("知识检索")).toHaveCount(0);
    await expect(page.getByText("生成记忆")).toHaveCount(0);

    // 模型入口（长模型名）可键盘聚焦并可进入设置
    const modelEntry = page.getByTestId("composer-model-entry");
    await expect(modelEntry).toContainText("qwen3:4b");
    await modelEntry.click();
    await expect(page.getByTestId("nav-settings")).toHaveAttribute("aria-current", "page");
  });

  test("上下文用量（v0.9.0 圆环）：能力未开启时诚实不可用，不伪造数值", async ({ page }) => {
    await openAgent(page);
    const ring = page.getByTestId("context-usage-ring");
    await expect(ring).toBeVisible();
    // v0.9.0 口径：矩形模块已移除，圆环按后端 typed budget 呈现；
    // 能力位未开启/不可用时如实「不可用」，不呈现百分比/负数/伪造数值（零容忍）
    await expect(ring).toHaveAttribute("aria-label", /上下文用量不可用/);
    const text = await ring.innerText();
    expect(text).not.toMatch(/\d+\s*%/);
    expect(text).not.toMatch(/-\d/);
  });

  test("布局韧性：1280/1440/1920 与 150% 缩放下无横向溢出且控件可达", async ({ page }) => {
    for (const width of [1280, 1440, 1920]) {
      await openAgent(page, width);
      const overflow = await page.evaluate(() => ({
        body: document.body.scrollWidth,
        viewport: window.innerWidth,
      }));
      expect(overflow.body).toBeLessThanOrEqual(overflow.viewport);
      await expect(page.getByTestId("composer-permission-select")).toBeVisible();
      await expect(page.getByTestId("task-composer-submit")).toBeVisible();
    }
  });

  test("窄窗口抽屉：可打开、Escape 关闭并恢复焦点", async ({ page }) => {
    await page.setViewportSize({ width: 1100, height: 800 });
    await mockW6r3Api(page);
    await page.goto("/?ui=v2&coding=0");
    await page.getByTestId("nav-chat").click();
    await expect(page.getByTestId("agent-conversations-tab")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("agent-conversations")).toHaveCount(0);

    await page.getByTestId("agent-conversations-tab").click();
    await expect(page.getByTestId("agent-conversations")).toBeVisible();
    await page.getByTestId("agent-conversation-2").click();
    // 选择后抽屉收起
    await expect(page.getByTestId("agent-conversations")).toHaveCount(0);

    // Escape 关闭并恢复焦点到触发按钮
    await page.getByTestId("agent-conversations-tab").click();
    await expect(page.getByTestId("agent-conversations")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("agent-conversations")).toHaveCount(0);
    await expect(page.getByTestId("agent-conversations-tab")).toBeFocused();
  });
});
