import { expect, test, type Locator, type Page, type TestInfo } from "@playwright/test";

async function openReadyHome(page: Page, testInfo: TestInfo): Promise<void> {
  await page.route("**/*", route => new URL(route.request().url()).origin === new URL(testInfo.project.use.baseURL as string).origin
    ? route.continue() : route.abort("blockedbyclient"));
  await page.addInitScript(() => {
    // 原生边界使用合成夹具，禁止访问真实凭据、项目目录和模型供应商。
    const surface = window as unknown as { isTauri: boolean; __TAURI_INTERNALS__: Record<string, unknown> };
    surface.isTauri = true;
    let callbackId = 0;
    surface.__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
      transformCallback: () => ++callbackId,
      unregisterCallback: () => undefined,
      invoke: async (command: string, args: {
        id: string; request: { path: string; method?: string; headers: Record<string, string> };
        onEvent: { onmessage: (frame: unknown) => void };
      }) => {
        if (command === "start_local_executor") return { transport: "stdio", protocol: 2 };
        if (command.startsWith("plugin:event|")) return 1;
        if (command !== "local_executor_request") throw new Error("测试未开放此原生操作");
        const path = args.request.path.split("?")[0];
        if (args.request.method && args.request.method !== "GET" && path !== "/identity/local") throw new Error(`测试不允许写入：${path}`);
        let body: unknown = [];
        if (path === "/health") body = { mode: "desktop-local", protocol: 1 };
        else if (path === "/identity/local") body = { ready: true, access_token: `local-session:${"a".repeat(43)}` };
        else {
          if (args.request.headers.authorization !== `Bearer local-session:${"a".repeat(43)}`) throw new Error("缺少合成身份");
          if (path === "/capabilities") body = { coding_agent_ui_enabled: true, project_bound_runs_enabled: true, coding_worktree_enabled: true };
          else if (path === "/model-settings") body = { llm_temperature: 0.2, llm_context_length: 8192, kb_enabled_by_default: false };
          else if (path === "/projects") body = [{ id: 1, name: "项目测试", status: "active", updated_at: "2026-09-17T00:00:00Z" }];
          else if (path === "/projects/1/workspaces") body = [{ id: 101, project_id: 1, kind: "root", status: "active", branch_name: null, head_sha: null, last_used_at: null }];
          else if (path === "/projects/1/git/branches") body = { is_git: true, branches: [], current_branch: null, head_sha: null, dirty: false };
          else if (path === "/agent-model-profiles") body = [{ id: "fixture-coder", provider: "ollama", display_name: "试用模型", is_local: true, enabled: true, context_tokens: 8192, reasoning_efforts: ["low", "medium", "high"] }];
        }
        args.onEvent.onmessage({ id: args.id, status: 200, headers: { "Content-Type": "application/json" } });
        args.onEvent.onmessage({ id: args.id, data: JSON.stringify(body) });
        args.onEvent.onmessage({ id: args.id, done: true });
      },
    };
  });
  await page.goto("/#/app");
  await expect(page.getByTestId("coding-home-ready")).toBeVisible();
  await expect(page.getByTestId("coding-nav-diagnostics")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "帮助与诊断" })).toHaveCount(0);
}

async function expectHint(page: Page, control: Locator, text: string): Promise<void> {
  await control.hover();
  const tooltip = page.locator("#pa-button-tooltip");
  await expect(tooltip).toHaveText(text);
  const box = (await tooltip.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  expect(box.y + box.height).toBeLessThanOrEqual(page.viewportSize()!.height);
}

test("侧栏可反复折叠展开，缩放后展开按钮仍可点击", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1500, height: 600 });
  await openReadyHome(page, testInfo);
  const toggle = page.getByTestId("coding-toggle-collapse");
  const railWidth = () => page.locator(".appshell-rail").evaluate(element => element.getBoundingClientRect().width);
  for (const width of [1500, 1280]) {
    await page.setViewportSize({ width, height: 600 });
    for (let cycle = 0; cycle < 2; cycle++) {
      await expect(toggle).toHaveAccessibleName("折叠侧栏");
      await toggle.click();
      await expect(toggle).toHaveAccessibleName("展开侧栏");
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await expect(toggle).toBeInViewport();
      await expect.poll(railWidth).toBe(72);
      const account = (await page.getByTestId("user-menu-trigger").boundingBox())!;
      const expand = (await toggle.boundingBox())!;
      expect(account.y + account.height).toBeLessThanOrEqual(expand.y);
      if (width === 1500 && cycle === 0) await page.screenshot({ path: testInfo.outputPath("collapsed-sidebar.png") });
      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      await expect.poll(railWidth).toBe(272);
      await expect(page.getByTestId("coding-project-1")).toBeVisible();
    }
  }
  await toggle.click();
  await page.setViewportSize({ width: 1000, height: 700 });
  await page.getByTestId("coding-drawer-tab").click();
  await expect(page.getByTestId("coding-project-1")).toBeVisible();
  await page.getByTestId("coding-drawer-close").click();
  await page.setViewportSize({ width: 1500, height: 700 });
  await expect(toggle).toHaveAccessibleName("展开侧栏");
  await toggle.click();
  await expect.poll(railWidth).toBe(272);
});

test("侧栏折叠后进入设置保持完整导航，返回和历史切换保留可恢复状态", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1500, height: 800 });
  await openReadyHome(page, testInfo);
  const toggle = page.getByTestId("coding-toggle-collapse");
  await toggle.click();
  await page.getByTestId("user-menu-trigger").click();
  await page.getByTestId("user-menu-settings").click();
  const settingsNav = page.getByTestId("settings-module-nav");
  await expect(settingsNav).toBeVisible();
  await expect.poll(() => settingsNav.evaluate(element => element.getBoundingClientRect().width)).toBe(272);
  for (const label of ["返回应用", "当前模型", "模型设置"]) {
    const button = settingsNav.getByRole("button", { name: label, exact: true });
    await expect(button).toBeVisible();
    expect(await button.locator("span").evaluate(element => element.getBoundingClientRect().height)).toBeLessThan(30);
  }
  await page.getByTestId("settings-section-provider").click();
  await expect(page.getByTestId("model-provider-manager")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("settings-after-collapse.png") });
  await page.setViewportSize({ width: 1000, height: 700 });
  await page.getByTestId("settings-drawer-tab").click();
  await expect(settingsNav).toBeInViewport();
  expect((await settingsNav.boundingBox())!.width).toBeGreaterThan(250);
  await page.getByTestId("settings-section-current-model").click();
  await expect(settingsNav).toHaveCount(0);
  await page.getByTestId("settings-drawer-tab").click();
  await settingsNav.getByRole("button", { name: "返回应用", exact: true }).click();
  await page.setViewportSize({ width: 1500, height: 800 });
  await expect(toggle).toHaveAccessibleName("展开侧栏");
  await page.keyboard.press("Alt+ArrowLeft");
  await expect(settingsNav).toBeVisible();
  await expect.poll(() => settingsNav.evaluate(element => element.getBoundingClientRect().width)).toBe(272);
  await page.keyboard.press("Alt+ArrowRight");
  await expect(toggle).toHaveAccessibleName("展开侧栏");
  await toggle.click();
  await expect(page.getByTestId("coding-project-1")).toBeVisible();
});

test("窗口缩放时首页不再显示独立工作区，侧栏和顶部控件仍可操作", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1500, height: 900 });
  await openReadyHome(page, testInfo);
  for (const width of [1500, 1280, 1279, 1200, 1000, 800, 640]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator(".worktree-panel")).toHaveCount(0);
    await expect(page.getByText("独立工作区", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /创建并选择 worktree|清理当前 worktree/ })).toHaveCount(0);
    const toggle = page.getByTestId("coding-drawer-tab");
    if (width < 1280) {
      await expect(toggle).toBeVisible();
      await toggle.click();
      await expect(page.getByTestId("coding-sidebar")).toBeVisible();
      await expect(page.getByTestId("coding-nav-diagnostics")).toHaveCount(0);
      await page.getByTestId("coding-drawer-close").click();
    } else await expect(toggle).toHaveCount(0);
    await expect(page.getByTestId("coding-composer-input")).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (width === 640 || width === 1500) await page.screenshot({ path: testInfo.outputPath(`home-${width}.png`) });
  }
  await page.getByTestId("coding-drawer-tab").click();
  await page.getByTestId("coding-nav-extensions").click();
  await expect(page.locator(".appshell-topbar")).toBeVisible();
  const toggleBox = (await page.getByTestId("coding-drawer-tab").boundingBox())!;
  const backBox = (await page.getByRole("button", { name: "返回上一视图" }).boundingBox())!;
  expect(toggleBox.x + toggleBox.width).toBeLessThanOrEqual(backBox.x);
});

test("功能提示覆盖首页、禁用控件、弹窗与键盘，并避开窗口边缘", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1000, height: 800 });
  await openReadyHome(page, testInfo);
  await expectHint(page, page.getByTestId("coding-drawer-tab"), "打开 Coding Agent 侧栏");
  await page.screenshot({ path: testInfo.outputPath("sidebar-button-tooltip.png") });
  await page.getByTestId("coding-drawer-tab").click();
  await page.getByRole("button", { name: "新建项目", exact: true }).click();
  const create = page.getByTestId("new-project-submit");
  await expect(create).toBeDisabled();
  await expectHint(page, create, "创建项目（当前不可用）");
  const cancel = page.getByRole("button", { name: "取消", exact: true });
  await expectHint(page, cancel, "取消");
  await cancel.click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator("#pa-button-tooltip")).toHaveCount(0);
  await page.getByTestId("coding-drawer-close").click();
  const model = page.getByTestId("composer-model");
  await expectHint(page, model, "模型");
  await page.screenshot({ path: testInfo.outputPath("composer-tooltip.png") });
  await page.mouse.move(900, 200);
  const drawer = page.getByTestId("coding-drawer-tab");
  await drawer.focus();
  await expect(page.locator("#pa-button-tooltip")).toHaveText("打开 Coding Agent 侧栏");
  await page.keyboard.press("Escape");
  await expect(page.locator("#pa-button-tooltip")).toHaveCount(0);
  await expect(drawer).toBeFocused();
  const voice = page.getByRole("button", { name: "语音输入暂不可用" });
  await voice.hover();
  await expect(voice).toHaveAttribute("title", "语音输入将在后续版本开放");
  await expect(page.locator("#pa-button-tooltip")).toHaveCount(0);
});
