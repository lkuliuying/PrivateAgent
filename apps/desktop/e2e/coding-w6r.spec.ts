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

test.describe("v0.8.0 W6-R · 试用反馈修订", () => {
  test("Coding Agent 模式移除个人工作区与更多工作区入口", async ({ page }) => {
    await mockW6rApi(page);
    await page.goto("/?coding=1");
    await expect(page.getByTestId("coding-sidebar")).toBeVisible({ timeout: 10_000 });

    await expect(page.getByTestId("coding-personal")).toHaveCount(0);
    await expect(page.getByTestId("coding-legacy-section")).toHaveCount(0);
    await expect(page.getByText("个人工作区")).toHaveCount(0);
    await expect(page.getByText("更多工作区")).toHaveCount(0);
    await expect(page.getByTestId("coding-recent")).toBeVisible();
  });

  test("窄窗口保留 Coding Agent 抽屉入口与核心导航", async ({ page }) => {
    await page.setViewportSize({ width: 1100, height: 800 });
    await mockW6rApi(page);
    await page.goto("/?coding=1");
    await expect(page.getByTestId("coding-drawer-tab")).toBeVisible({ timeout: 10_000 });
    await page.getByTestId("coding-drawer-tab").click();
    await expect(page.getByTestId("coding-new-task")).toBeVisible();
    await expect(page.getByTestId("coding-toggle-projects")).toBeVisible();
    await expect(page.getByTestId("coding-nav-settings")).toBeVisible();
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

    // 命令卡：头部事实（退出码/耗时）默认呈现；命令文本、工作目录与
    // 输出在详情折叠区（W6-R：避免每次工具调用撑大卡片），展开后可见。
    await expect(page.getByTestId("command-exit-code")).toContainText("退出码 0");
    await expect(page.getByTestId("command-duration")).toBeVisible();
    await expect(page.getByTestId("command-output-body")).toHaveCount(0);
    await page.getByTestId("command-output-toggle").click();
    await expect(page.getByTestId("command-line")).toContainText("[REDACTED]");
    await expect(page.getByTestId("command-cwd")).toContainText("工作目录");
    await expect(page.getByTestId("command-output-body")).toContainText("test session starts");

    // 零容忍：演示凭据不出现在任何可见文本中
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toContain("sk-demo-secret-0001");
  });
});
