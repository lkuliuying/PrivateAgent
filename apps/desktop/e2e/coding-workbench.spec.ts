import { test, expect, type Page } from "@playwright/test";
import { fulfillCodingAuth, prepareCodingFixture } from "./coding-auth-fixture";

test.beforeEach(async ({ page }) => prepareCodingFixture(page));

/**
 * v0.8.0 W1：CodingWorkbench（?coding=1 内部 flag）E2E
 * 覆盖：W0 冻结矩阵首页六状态、侧栏项目树、新建任务主链（POST /sessions
 * kind=coding）、设置导航回环、<1280px 抽屉模式、旧参数兼容与敏感字段红线。
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
  let currentBranch = "main";
  return page.route("**://127.0.0.1:8000/**", async (route) => {
    if (await fulfillCodingAuth(route)) return;
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;

    if (path === "/projects/1/git/branches" || path === "/projects/1/git/branches/select") {
      if (request.method() === "POST") currentBranch = request.postDataJSON().branch_name;
      await route.fulfill({ json: {
        is_git: true, current_branch: currentBranch, head_sha: "ab" + "0".repeat(38), dirty: false,
        branches: ["main", "feature/coding-workbench"].map((name) => ({
          name, head_sha: "ab" + "0".repeat(38), current: name === currentBranch,
        })),
      } });
      return;
    }

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
    await expect(page.getByTestId("coding-composer-input")).toBeVisible();
    await expect(page.getByTestId("coding-home-project-select")).toBeVisible();
    await expect(page.getByTestId("coding-home-workspace-select")).toBeVisible();

    // 当前侧栏按项目展示对话；分支选择和未提交状态分别从选择器与详情核对。
    await expect(page.getByTestId("coding-toggle-projects")).toHaveAttribute("aria-expanded", "true");
    await page.getByTestId("coding-home-workspace-select").selectOption("branch:feature/coding-workbench");
    await expect(page.getByTestId("coding-home-workspace-select")).toHaveValue("branch:feature/coding-workbench");
    await expect(page.getByTestId("coding-thread-11")).toBeVisible();
    await expect(page.getByTestId("coding-thread-12")).toBeVisible();
    await page.getByTestId("coding-thread-12").hover();
    await expect(page.getByTestId("coding-thread-details-12")).toContainText("有未提交更改");

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

    await page.getByTestId("coding-composer-input").fill("为侧栏补充键盘导航");
    await page.getByTestId("coding-composer-send").click();

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

  test("无项目：空态引导新建授权项目，取消后保留空态", async ({ page }) => {
    await openCoding(page, { projects: [] });
    await expect(page.getByTestId("coding-home-no-projects")).toBeVisible();
    await page.getByTestId("home-new-project").click();
    await expect(page.getByTestId("new-project-dialog")).toBeVisible();
    await expect(page.getByTestId("new-project-submit")).toBeDisabled();
    await page.getByTestId("new-project-dialog").getByRole("button", { name: "取消", exact: true }).click();
    await expect(page.getByTestId("new-project-dialog")).toBeHidden();
    await expect(page.getByTestId("coding-home-no-projects")).toBeVisible();
    await expect(page.getByRole("button", { name: "打开项目页" })).toHaveCount(0);
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
    await expect(page.getByTestId("settings-section-provider")).toHaveAttribute(
      "aria-current",
      "page"
    );
  });

  test("sidecar 未就绪（/health 失败）：错误态与重试入口", async ({ page }) => {
    await page.addInitScript(() => {
      type LocalRequest = { id: string; request: { path: string }; onEvent: { onmessage: (event: Record<string, unknown>) => void } };
      const surface = window as unknown as { __TAURI_INTERNALS__: { invoke: (command: string, args: LocalRequest) => Promise<unknown> } };
      const invoke = surface.__TAURI_INTERNALS__.invoke;
      let healthChecks = 0;
      surface.__TAURI_INTERNALS__.invoke = async (command, args) => {
        // 启动检查先成功，工作台随后失联；故障发生在真实本机请求边界。
        if (command === "local_executor_request" && args.request.path === "/health" && ++healthChecks === 2) {
          args.onEvent.onmessage({ id: args.id, status: 503, headers: { "Content-Type": "application/json" } });
          args.onEvent.onmessage({ id: args.id, data: "{}" });
          args.onEvent.onmessage({ id: args.id, done: true });
          return;
        }
        return invoke(command, args);
      };
    });
    await openCoding(page);
    await expect(page.getByTestId("coding-home-sidecar-unavailable")).toBeVisible();
    await expect(page.getByRole("button", { name: "重试连接" })).toBeVisible();
    await page.getByRole("button", { name: "重试连接" }).click();
    await expect(page.getByTestId("coding-home-ready")).toBeVisible();
  });

  test("工作区异常（missing）：状态语义与新建授权项目入口", async ({ page }) => {
    await openCoding(page, {
      workspaces: [{ ...WORKSPACE_DTOS[0], status: "missing" }],
      threads: [],
    });
    await expect(page.getByTestId("coding-home-workspace-invalid")).toBeVisible();
    await expect(page.getByText("路径缺失")).toBeVisible();
    await page.getByTestId("coding-home-workspace-invalid").getByRole("button", { name: "新建项目", exact: true }).click();
    await expect(page.getByTestId("new-project-dialog")).toBeVisible();
    await expect(page.getByTestId("new-project-submit")).toBeDisabled();
  });

  test("旧页导航回环：设置 → 返回 coding 首页（不经独立项目页）", async ({ page }) => {
    await openCoding(page);
    await page.getByTestId("user-menu-trigger").click();
    await page.getByRole("menuitem", { name: "设置", exact: true }).click();
    await expect(page.getByTestId("settings-module-nav")).toBeVisible();
    await page.getByRole("button", { name: "返回应用", exact: true }).click();
    await expect(page.getByTestId("coding-home-ready")).toBeVisible();
  });

  test("设置按模块切换，主区只显示当前模块", async ({ page }) => {
    await mockCodingApi(page);
    await page.addInitScript(() => {
      window.sessionStorage.setItem("pa_access_token", "health-privacy-e2e-session");
    });
    await page.route("**://127.0.0.1:8000/auth/me", (route) => route.fulfill({
      json: {
        id: 2, email: "user@example.test", username: "user", display_name: "user",
        role: "user", status: "active", last_login_at: null,
        created_at: "2026-08-30T00:00:00Z",
      },
    }));
    await page.goto("/?coding=1");
    await page.getByTestId("user-menu-trigger").click();
    await page.getByRole("menuitem", { name: "设置", exact: true }).click();

    await expect(page.getByTestId("settings-section-status")).toHaveCount(0);
    await expect(page.getByTestId("settings-section-current-model")).toHaveAttribute(
      "aria-current",
      "page"
    );
    await expect(page.getByRole("heading", { name: "当前模型" }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "运行状态" })).toHaveCount(0);

    await page.getByTestId("settings-section-provider").click();
    await expect(page.getByTestId("settings-section-provider")).toHaveAttribute(
      "aria-current",
      "page"
    );
    await expect(page.getByRole("heading", { name: "模型设置", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "运行状态" })).toHaveCount(0);
  });

  test("设置窄窗口：模块栏隐藏为浮动入口，可打开并在选择后自动收起", async ({ page }) => {
    await page.setViewportSize({ width: 1100, height: 760 });
    await openCoding(page, {}, "drawer-tab");
    await page.getByTestId("coding-drawer-tab").click();
    await page.getByTestId("user-menu-trigger").click();
    await page.getByRole("menuitem", { name: "设置", exact: true }).click();

    await expect(page.getByTestId("settings-drawer-tab")).toBeVisible();
    await expect(page.getByTestId("settings-module-nav")).toBeHidden();
    await page.getByTestId("settings-drawer-tab").click();
    await expect(page.getByTestId("settings-module-nav")).toBeVisible();
    await page.getByTestId("settings-section-provider").click();
    await expect(page.getByTestId("settings-module-nav")).toBeHidden();
    await expect(page.getByRole("heading", { name: "模型设置", exact: true })).toBeVisible();
  });

  test("矮窗口侧栏中部滚动，底部入口不与项目内容重叠", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 600 });
    await openCoding(page);

    const scrollRegion = page.locator(".sidebar-scroll-region");
    const footer = page.locator(".sidebar-footer");
    await expect(scrollRegion).toBeVisible();
    await expect(footer).toBeVisible();

    const scrollBox = await scrollRegion.boundingBox();
    const footerBox = await footer.boundingBox();
    expect(scrollBox).not.toBeNull();
    expect(footerBox).not.toBeNull();
    expect((scrollBox?.y ?? 0) + (scrollBox?.height ?? 0)).toBeLessThanOrEqual(
      (footerBox?.y ?? 0) + 1
    );
    expect((footerBox?.y ?? 0) + (footerBox?.height ?? 0)).toBeLessThanOrEqual(600);
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
    // 任务由对话中的 run 表达，控件名称与当前可访问标签一致。
    await expect(newTask).toHaveAttribute("aria-label", "新对话");
    await expect(page.getByTestId("coding-toggle-projects")).toHaveAttribute("aria-label", "项目");
    await expect(page.getByTestId("coding-tree")).toBeHidden();
  });

  test("旧 ui=v1 参数不绕过普通用户 Coding 工作台", async ({ page }) => {
    await mockCodingApi(page);
    await page.goto("/?coding=1&ui=v1");
    // 当前 uiFlags 按角色选择工作台，已不支持普通用户用查询参数切回旧壳。
    await expect(page.getByTestId("coding-home-ready")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("nav-utilities-toggle")).toHaveCount(0);
  });

  test("开发预览夹具：?coding-preview= 不依赖后端渲染六状态（W0 矩阵 L2）", async ({ page }) => {
    // 仅模拟账号，业务 API 被阻断；预览夹具仍独立提供六种状态。
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
