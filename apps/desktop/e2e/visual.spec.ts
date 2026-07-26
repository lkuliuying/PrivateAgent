import { expect, test, type Page } from "@playwright/test";

const FIXED_NOW = new Date("2026-07-15T02:30:00.000Z");
const THEME_KEY = "private-agent.appearance.theme";
const CONTRAST_KEY = "private-agent.appearance.contrast";

const TODAY_SNAPSHOT = {
  generated_at: FIXED_NOW.toISOString(),
  summary: {
    due_cards: 1,
    attention_tasks: 1,
    failed_activities: 0,
    draft_memories: 0,
    due_reminders: 0,
    open_inbox: 2,
    last_backup_at: "2026-07-14T18:00:00.000Z",
  },
  due_cards: [
    {
      id: 11,
      front: "复习架构边界与依赖方向",
      status: "due",
      due_at: "2026-07-15T04:00:00.000Z",
      source_type: "learning_card",
      source_id: 11,
    },
  ],
  attention_tasks: [
    {
      id: 21,
      title: "完成发布候选版验证",
      status: "running",
      priority: "high",
      due_at: "2026-07-15T09:00:00.000Z",
      source_type: "agent_task",
      source_id: 21,
    },
  ],
  failed_activities: [],
  draft_memories: [],
  due_reminders: [],
  open_inbox: [
    {
      id: 31,
      title: "整理视觉回归检查结果",
      status: "open",
      item_type: "todo",
      source_type: "inbox",
      source_id: 31,
    },
    {
      id: 32,
      title: "确认安装包签名信息",
      status: "open",
      item_type: "todo",
      source_type: "inbox",
      source_id: 32,
    },
  ],
  backup: { last_backup_at: "2026-07-14T18:00:00.000Z", count: 3 },
  recent_checkins: [
    {
      id: 41,
      goal_title: "桌面端发布质量",
      checkin_date: "2026-07-15T01:30:00.000Z",
      progress_note_md: "全量门禁保持通过",
      source_type: "goal_checkin",
      source_id: 41,
    },
  ],
  recent_briefings: [
    {
      id: 42,
      title: "今日工程简报",
      created_at: "2026-07-15T01:00:00.000Z",
      source_type: "briefing",
      source_id: 42,
    },
  ],
  recent_docs: [
    {
      id: 43,
      name: "发布验证清单.md",
      doc_type: "markdown",
      status: "ready",
      created_at: "2026-07-14T23:30:00.000Z",
      source_type: "document",
      source_id: 43,
    },
  ],
  recent_sessions: [
    {
      id: 44,
      title: "审查桌面端视觉一致性",
      updated_at: "2026-07-15T02:00:00.000Z",
      source_type: "chat_session",
      source_id: 44,
    },
  ],
  maintenance: {
    last_backup_at: "2026-07-14T18:00:00.000Z",
    backup_count: 3,
    failed_activities: 0,
    draft_memories: 0,
    orphan_evidence: 0,
  },
};

const WORKFLOW_TASK = {
  id: 21,
  session_id: null,
  title: "发布前验证 Agent 工作流",
  goal: "验证连接、执行、证据归档与完成状态",
  status: "running",
  plan_json: null,
  final_report_md: null,
  created_at: FIXED_NOW.toISOString(),
  updated_at: FIXED_NOW.toISOString(),
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
      started_at: FIXED_NOW.toISOString(),
      finished_at: FIXED_NOW.toISOString(),
      created_at: FIXED_NOW.toISOString(),
    },
    {
      id: 212,
      task_id: 21,
      ordinal: 2,
      title: "执行全量发布门禁",
      tool_name: "run_command",
      status: "running",
      tool_call_id: 52,
      input_json: {},
      output_json: null,
      error_message: null,
      started_at: FIXED_NOW.toISOString(),
      finished_at: null,
      created_at: FIXED_NOW.toISOString(),
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
      created_at: FIXED_NOW.toISOString(),
    },
  ],
};

const CHAT_MESSAGES = [
  {
    id: 1,
    session_id: 1,
    role: "user",
    content: "请检查发布链路与视觉回归是否都已覆盖。",
    created_at: FIXED_NOW.toISOString(),
  },
  {
    id: 2,
    session_id: 1,
    role: "assistant",
    content: "已完成架构检查，正在验证签名、升级和动画证据。",
    created_at: FIXED_NOW.toISOString(),
  },
];

const PENDING_TOOL = {
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
  created_at: FIXED_NOW.toISOString(),
  updated_at: FIXED_NOW.toISOString(),
};

interface VisualCase {
  contrast: "normal" | "more";
  name: string;
  theme: "light" | "dark";
  viewport: { width: number; height: number };
  view: "today" | "chat" | "tasks";
}

const VISUAL_CASES: VisualCase[] = [
  {
    name: "today-light-compact-960x720",
    theme: "light",
    contrast: "normal",
    viewport: { width: 960, height: 720 },
    view: "today",
  },
  {
    name: "today-light-minimum-900x600",
    theme: "light",
    contrast: "normal",
    viewport: { width: 900, height: 600 },
    view: "today",
  },
  {
    name: "today-light-desktop-1440x900",
    theme: "light",
    contrast: "normal",
    viewport: { width: 1440, height: 900 },
    view: "today",
  },
  {
    name: "today-light-wide-1920x1080",
    theme: "light",
    contrast: "normal",
    viewport: { width: 1920, height: 1080 },
    view: "today",
  },
  {
    name: "today-dark-desktop-1440x900",
    theme: "dark",
    contrast: "normal",
    viewport: { width: 1440, height: 900 },
    view: "today",
  },
  {
    name: "today-high-contrast-desktop-1440x900",
    theme: "light",
    contrast: "more",
    viewport: { width: 1440, height: 900 },
    view: "today",
  },
  {
    name: "today-dark-high-contrast-desktop-1440x900",
    theme: "dark",
    contrast: "more",
    viewport: { width: 1440, height: 900 },
    view: "today",
  },
  {
    name: "tasks-light-compact-960x720",
    theme: "light",
    contrast: "normal",
    viewport: { width: 960, height: 720 },
    view: "tasks",
  },
  {
    name: "tasks-light-desktop-1440x900",
    theme: "light",
    contrast: "normal",
    viewport: { width: 1440, height: 900 },
    view: "tasks",
  },
  {
    name: "chat-dark-minimum-900x600",
    theme: "dark",
    contrast: "normal",
    viewport: { width: 900, height: 600 },
    view: "chat",
  },
  {
    name: "chat-dark-desktop-1440x900",
    theme: "dark",
    contrast: "normal",
    viewport: { width: 1440, height: 900 },
    view: "chat",
  },
];

async function mockApi(page: Page): Promise<void> {
  await page.route("**://127.0.0.1:8000/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/today") {
      await route.fulfill({ json: TODAY_SNAPSHOT });
      return;
    }
    if (path === "/health") {
      await route.fulfill({
        json: {
          api: { ok: true },
          ollama: { ok: true, models: ["qwen2.5:7b"] },
          mysql: { ok: true },
          chroma: { ok: true },
        },
      });
      return;
    }
    if (path === "/agent-tasks") {
      await route.fulfill({ json: [WORKFLOW_TASK] });
      return;
    }
    if (path === "/projects") {
      await route.fulfill({ json: [] });
      return;
    }
    if (path === "/reminders") {
      await route.fulfill({ json: [] });
      return;
    }
    if (path === "/inbox") {
      await route.fulfill({ json: [] });
      return;
    }
    if (
      path === "/notifications" ||
      path === "/briefings" ||
      path === "/goals" ||
      path === "/capture" ||
      path === "/privacy/audits" ||
      path === "/activities" ||
      path === "/files/trusted"
    ) {
      await route.fulfill({ json: [] });
      return;
    }
    if (path === "/maintenance/health-report") {
      await route.fulfill({
        json: {
          generated_at: FIXED_NOW.toISOString(),
          summary: {
            last_backup_at: null,
            backup_count: 0,
            failed_activities: 0,
            draft_memories: 0,
            attention_tasks: 0,
            orphan_evidence: 0,
            open_inbox: 0,
            due_reminders: 0,
          },
          recommendations: [],
        },
      });
      return;
    }
    if (path === "/settings") {
      await route.fulfill({
        json: {
          llm_model: "qwen2.5:7b",
          embed_model: "bge-m3",
          llm_temperature: 0.3,
          llm_context_length: 8192,
          kb_enabled_by_default: true,
          provider_type: "ollama",
          remote_provider_enabled: false,
          openai_api_key: "",
          openai_base_url: "",
          openai_model: "",
          claude_api_key: "",
          claude_model: "",
          reminders_enabled: true,
          reminder_tick_seconds: 60,
          desktop_notifications_enabled: true,
        },
      });
      return;
    }
    if (path === "/sessions") {
      await route.fulfill({
        json: [
          {
            id: 1,
            title: "发布质量复核",
            created_at: FIXED_NOW.toISOString(),
            updated_at: FIXED_NOW.toISOString(),
          },
        ],
      });
      return;
    }
    if (path === "/sessions/1/messages") {
      await route.fulfill({ json: CHAT_MESSAGES });
      return;
    }
    if (path === "/tool-calls") {
      await route.fulfill({ json: [PENDING_TOOL] });
      return;
    }
    throw new Error(`Unhandled visual regression API route: ${path}`);
  });
}

async function prepareVisualState(page: Page, visualCase: VisualCase): Promise<void> {
  await page.setViewportSize(visualCase.viewport);
  await page.emulateMedia({
    colorScheme: visualCase.theme,
    reducedMotion: "reduce",
  });
  await page.clock.setFixedTime(FIXED_NOW);
  await page.addInitScript(
    ({ contrast, contrastKey, theme, themeKey }) => {
      window.localStorage.setItem(themeKey, theme);
      window.localStorage.setItem(contrastKey, contrast);
    },
    {
      contrast: visualCase.contrast,
      contrastKey: CONTRAST_KEY,
      theme: visualCase.theme,
      themeKey: THEME_KEY,
    }
  );
  await mockApi(page);
  await page.goto("/", { waitUntil: "networkidle" });

  await expect(page.locator("html")).toHaveAttribute("data-theme", visualCase.theme);
  await expect(page.locator("html")).toHaveAttribute(
    "data-contrast",
    visualCase.contrast
  );
  await expect(page.locator(".today-shell")).toHaveAttribute("aria-busy", "false");
  await expect(page.locator(".today-overview")).toBeVisible();

  if (visualCase.view === "tasks") {
    await page.locator(".nav-item", { hasText: "任务" }).click();
    await expect(page.locator(".tasks-shell")).toBeVisible();
    await expect(page.locator("[data-workflow-step]")).toHaveCount(3);
  } else if (visualCase.view === "chat") {
    await page.locator(".nav-item", { hasText: "对话" }).click();
    await expect(page.locator(".chat")).toBeVisible();
    await expect(page.locator("[data-chat-message]")).toHaveCount(3);
  }

  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(
      Array.from(document.images, (image) =>
        image.complete ? Promise.resolve() : image.decode().catch(() => undefined)
      )
    );
    document.querySelectorAll<HTMLElement>("[data-scroll-container]").forEach((element) => {
      element.scrollTop = 0;
      element.scrollLeft = 0;
    });
    window.scrollTo(0, 0);
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
    );
  });
}

test.describe("Windows visual regression", () => {
  test.skip(
    process.platform !== "win32",
    "当前视觉基线只维护 Windows Chromium，其他平台需独立采集。"
  );

  for (const visualCase of VISUAL_CASES) {
    test(visualCase.name, async ({ page }) => {
      await prepareVisualState(page, visualCase);
      await expect(page).toHaveScreenshot(`${visualCase.name}.png`, {
        fullPage: false,
      });
      if (visualCase.name === "tasks-light-desktop-1440x900") {
        await expect(page.locator(".task-main")).toHaveScreenshot(
          "tasks-workflow-critical.png",
          { maxDiffPixels: 250 }
        );
      }
      if (visualCase.name === "chat-dark-desktop-1440x900") {
        await expect(page.locator(".chat")).toHaveScreenshot(
          "chat-agent-critical.png",
          { maxDiffPixels: 250 }
        );
      }
    });
  }
});
