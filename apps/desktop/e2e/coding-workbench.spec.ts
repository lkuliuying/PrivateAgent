import { test, expect, type Page } from "@playwright/test";

/**
 * v0.8.0 W1：CodingWorkbench（?coding=1 内部 flag）E2E
 * 覆盖：W0 冻结矩阵首页六状态、侧栏项目树、新建任务主链（POST /sessions
 * kind=coding）、旧页导航回环、<1280px 抽屉模式、ui=v1 回退与敏感字段红线。
 */

const GREEN_HEALTH = {
  api: true,
  ollama: { ok: true, models: [] },
  mysql: { ok: true },
  chroma: { ok: true },
};

const PROJECT_DTO = {
  id: 1,
  name: "PrivateAgent",
  root_path: "C:\\secret\\local\\agent-root",
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
    root_path: "C:\\secret\\local\\agent-root",
    branch_name: null,
    head_sha: null,
    status: "active",
    last_used_at: "2026-08-22T01:00:00Z",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-22T01:00:00Z",
  },
  {
    id: 102,
    project_id: 1,
    kind: "git_worktree",
    root_path: "C:\\secret\\local\\agent-worktree",
    branch_name: "feature/coding-workbench",
    head_sha: "ab" + "0".repeat(38),
    status: "dirty",
    last_used_at: "2026-08-22T02:00:00Z",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-22T02:00:00Z",
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
  {
    id: 12,
    title: "梳理 coding 模块依赖",
    created_at: "2026-08-19T00:00:00Z",
    updated_at: "2026-08-21T00:00:00Z",
    project_id: 1,
    workspace_id: 102,
    kind: "coding",
    last_run_id: null,
    pinned_at: null,
    archived_at: null,
  },
];

const MODEL_PROFILE_DTOS = [
  {
    id: "local-coder",
    provider: "ollama",
    display_name: "Qwen3 Coder 30B",
    is_local: true,
    native_tool_calls: true,
    supports_streaming: true,
    supports_structured_output: true,
    supports_vision: false,
    context_tokens: 131072,
    reasoning_efforts: ["low", "medium", "high"],
    usage_reporting: true,
    enabled: true,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
  },
];

interface CodingStateOverrides {
  projects?: unknown[];
  workspaces?: unknown[];
  threads?: unknown[];
  modelProfiles?: number;
  modelProfilesBody?: unknown;
  healthStatus?: number;
  ensureStateful?: boolean;
  onSessionCreated?: (title: string) => unknown;
}

function mockCodingApi(page: Page, overrides: CodingStateOverrides = {}) {
  let workspaceEnsured = false;
  let nextSessionId = 100;
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
      if (overrides.healthStatus && overrides.healthStatus >= 500) {
        await route.fulfill({ status: overrides.healthStatus, json: {} });
      } else {
        await route.fulfill({ json: GREEN_HEALTH });
      }
      return;
    }
    if (path === "/sessions" && request.method() === "GET") {
      // 旧工作台 loadSessions（无查询）与 coding 线程拉取（project_id+kind）区分
      if (url.searchParams.get("kind") === "coding") {
        await route.fulfill({ json: overrides.threads ?? CODING_THREAD_DTOS });
      } else {
        await route.fulfill({ json: [] });
      }
      return;
    }
    if (path === "/sessions" && request.method() === "POST") {
      const body = request.postDataJSON() as { title?: string };
      nextSessionId += 1;
      const dto = overrides.onSessionCreated?.(body.title ?? "") ?? {
        id: nextSessionId,
        title: body.title ?? "新任务",
        created_at: "2026-08-22T03:00:00Z",
        updated_at: "2026-08-22T03:00:00Z",
        project_id: body.project_id ?? 1,
        workspace_id: body.workspace_id ?? 101,
        kind: "coding",
        last_run_id: null,
        pinned_at: null,
        archived_at: null,
      };
      await route.fulfill({ status: 201, json: dto });
      return;
    }
    if (path === "/projects" && request.method() === "GET") {
      await route.fulfill({ json: overrides.projects ?? [PROJECT_DTO] });
      return;
    }
    if (path === "/projects/1/workspaces" && request.method() === "GET") {
      if (overrides.ensureStateful && workspaceEnsured) {
        await route.fulfill({
          json: [
            {
              id: 101,
              project_id: 1,
              kind: "root",
              root_path: "C:\\secret\\local\\agent-root",
              branch_name: null,
              head_sha: null,
              status: "active",
              last_used_at: null,
              created_at: "2026-08-22T00:00:00Z",
              updated_at: "2026-08-22T00:00:00Z",
            },
          ],
        });
        return;
      }
      await route.fulfill({ json: overrides.workspaces ?? WORKSPACE_DTOS });
      return;
    }
    if (path === "/projects/1/workspaces/root/ensure" && request.method() === "POST") {
      workspaceEnsured = true;
      await route.fulfill({
        status: 201,
        json: {
          id: 101,
          project_id: 1,
          kind: "root",
          root_path: "C:\\secret\\local\\agent-root",
          branch_name: null,
          head_sha: null,
          status: "active",
          last_used_at: null,
          created_at: "2026-08-22T00:00:00Z",
          updated_at: "2026-08-22T00:00:00Z",
        },
      });
      return;
    }
    if (path === "/agent-model-profiles") {
      if (overrides.modelProfiles) {
        await route.fulfill({
          status: overrides.modelProfiles,
          json:
            overrides.modelProfilesBody ?? {
              error_code: "coding_mode_disabled",
              detail: "Coding 能力未开放",
            },
        });
        return;
      }
      await route.fulfill({ json: MODEL_PROFILE_DTOS });
      return;
    }
    if (path === "/settings") {
      await route.fulfill({ json: { model: "qwen3:4b", provider: "ollama" } });
      return;
    }
    await route.fulfill({ json: {} });
  });
}

async function openCoding(page: Page, overrides: CodingStateOverrides = {}, waitFor: "sidebar" | "drawer-tab" | "home" = "sidebar") {
  await mockCodingApi(page, overrides);
  await page.goto("/?coding=1");
  const target =
    waitFor === "drawer-tab" ? page.getByTestId("coding-drawer-tab") : page.getByTestId("coding-sidebar");
  await expect(target).toBeVisible({ timeout: 10000 });
}

test.describe("v0.8.0 W1 CodingWorkbench", () => {
  test("就绪态：侧栏项目树 + 首页输入齐备，敏感路径不进 UI", async ({ page }) => {
    await openCoding(page);
    await expect(page.getByTestId("coding-home-ready")).toBeVisible();
    await expect(page.getByTestId("coding-home-input")).toBeVisible();
    await expect(page.getByTestId("coding-home-project-select")).toBeVisible();
    await expect(page.getByTestId("coding-home-workspace-select")).toBeVisible();

    // 默认选择（项目 1 / root 工作区）在加载后自动展开祖先
    await expect(page.getByTestId("coding-workspace-101")).toBeVisible();
    await expect(page.getByTestId("coding-workspace-102")).toBeVisible();
    await expect(page.getByTestId("coding-workspace-102")).toHaveAttribute("data-status", "dirty");
    await expect(page.getByTestId("coding-thread-11")).toBeVisible();
    // 展开第二个工作区（分支）见其线程
    await page.getByTestId("coding-workspace-102").click();
    await expect(page.getByTestId("coding-thread-12")).toBeVisible();

    // 红线：root_path 原文不得出现在页面
    expect(await page.content()).not.toContain("C:\\secret");
  });

  test("新建任务主链：首页输入 → POST /sessions(kind=coding) → 任务页", async ({ page }) => {
    let createdBody: Record<string, unknown> | null = null;
    await openCoding(page, {
      onSessionCreated: (title) => {
        return {
          id: 201,
          title,
          created_at: "2026-08-22T03:00:00Z",
          updated_at: "2026-08-22T03:00:00Z",
          project_id: 1,
          workspace_id: 101,
          kind: "coding",
          last_run_id: null,
          pinned_at: null,
          archived_at: null,
        };
      },
    });
    page.on("request", (request) => {
      if (request.url().endsWith("/sessions") && request.method() === "POST") {
        createdBody = request.postDataJSON();
      }
    });

    await page.getByTestId("coding-home-input").fill("为侧栏补充键盘导航");
    await page.getByTestId("coding-home-submit").click();

    await expect(page.getByTestId("coding-thread-workspace")).toBeVisible();
    await expect(page.getByTestId("coding-thread-header")).toContainText("为侧栏补充键盘导航");
    expect(createdBody).toMatchObject({
      title: "为侧栏补充键盘导航",
      project_id: 1,
      workspace_id: 101,
      kind: "coding",
    });
    // 新线程随选择自动展开祖先并出现在侧栏树（root 工作区下）
    await expect(page.getByTestId("coding-thread-201")).toBeVisible();
  });

  test("无项目：空态引导打开项目页", async ({ page }) => {
    await openCoding(page, { projects: [] });
    await expect(page.getByTestId("coding-home-no-projects")).toBeVisible();
    await page.getByRole("button", { name: "打开项目页" }).click();
    // 首页空态让位于旧项目页，coding 侧栏仍在
    await expect(page.getByTestId("coding-home-no-projects")).toBeHidden();
    await expect(page.getByTestId("coding-sidebar")).toBeVisible();
  });

  test("有项目无 workspace：CTA 幂等补建根工作区后转入就绪", async ({ page }) => {
    await openCoding(page, { workspaces: [], threads: [], ensureStateful: true });
    await expect(page.getByTestId("coding-home-no-workspace")).toBeVisible();
    await page.getByRole("button", { name: "创建根工作区" }).click();
    await expect(page.getByTestId("coding-home-ready")).toBeVisible({ timeout: 10000 });
  });

  test("Provider 未配置（409 coding_mode_disabled）：引导前往设置", async ({ page }) => {
    await openCoding(page, { modelProfiles: 409 });
    await expect(page.getByTestId("coding-home-provider-unconfigured")).toBeVisible();
    await page.getByRole("button", { name: "前往设置" }).click();
    await expect(page.getByTestId("coding-nav-settings")).toHaveAttribute(
      "aria-current",
      "page"
    );
  });

  test("sidecar 未就绪（/health 失败）：错误态与重试入口", async ({ page }) => {
    await openCoding(page, { healthStatus: 503 });
    await expect(page.getByTestId("coding-home-sidecar-unavailable")).toBeVisible();
    await expect(page.getByRole("button", { name: "重试连接" })).toBeVisible();
  });

  test("工作区异常（missing）：状态语义与项目页入口", async ({ page }) => {
    await openCoding(page, {
      workspaces: [{ ...WORKSPACE_DTOS[0], status: "missing" }],
      threads: [],
    });
    await expect(page.getByTestId("coding-home-workspace-invalid")).toBeVisible();
    await expect(page.getByText("路径缺失")).toBeVisible();
  });

  test("旧页导航回环：设置 → 返回 coding 首页（不经独立项目页）", async ({ page }) => {
    await openCoding(page);
    await page.getByTestId("coding-nav-settings").click();
    await expect(page.getByTestId("coding-nav-settings")).toHaveAttribute(
      "aria-current",
      "page"
    );
    // coding 侧栏仍在，旧页可返回新壳首页
    await expect(page.getByTestId("coding-sidebar")).toBeVisible();
    await page.getByTestId("coding-new-task").click();
    await expect(page.getByTestId("coding-home-ready")).toBeVisible();
  });

  test("<1280px 抽屉模式：浮标打开、遮罩关闭", async ({ page }) => {
    await page.setViewportSize({ width: 1100, height: 720 });
    await openCoding(page, {}, "drawer-tab");
    await expect(page.getByTestId("coding-sidebar")).toBeHidden();
    await page.getByTestId("coding-drawer-tab").click();
    await expect(page.getByTestId("coding-sidebar")).toBeVisible();
    await page.getByTestId("coding-drawer-backdrop").click();
    await expect(page.getByTestId("coding-sidebar")).toBeHidden();
  });

  test("折叠侧栏：icon-only 控件保留可访问名称", async ({ page }) => {
    await openCoding(page);
    await page.getByTestId("coding-toggle-collapse").click();
    const newTask = page.getByTestId("coding-new-task");
    await expect(newTask).toHaveAttribute("aria-label", "新建任务");
    await expect(page.getByTestId("coding-tree")).toBeHidden();
  });

  test("ui=v1 回退仍可用（coding flag 不影响旧壳）", async ({ page }) => {
    await mockCodingApi(page);
    await page.goto("/?coding=1&ui=v1");
    await expect(page.getByTestId("nav-utilities-toggle")).toBeVisible({ timeout: 10000 });
  });

  test("开发预览夹具：?coding-preview= 不依赖后端渲染六状态（W0 矩阵 L2）", async ({ page }) => {
    // 无路由 mock：预览夹具替换数据源，后端不可达不影响状态呈现
    for (const [key, state] of [
      ["no-projects", "coding-home-no-projects"],
      ["no-workspace", "coding-home-no-workspace"],
      ["provider-unconfigured", "coding-home-provider-unconfigured"],
      ["sidecar-unavailable", "coding-home-sidecar-unavailable"],
      ["workspace-invalid", "coding-home-workspace-invalid"],
      ["ready", "coding-home-ready"],
    ] as const) {
      await page.goto(`/?coding=1&coding-preview=${key}`);
      await expect(page.getByTestId(state)).toBeVisible({ timeout: 10000 });
    }
  });
});
