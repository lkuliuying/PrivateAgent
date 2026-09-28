import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1440, height: 900 } });

test("首次启动直接使用 API Key，已删除入口不再请求平台", async ({ page }, testInfo) => {
  const externalRequests: string[] = [];
  await page.route("**/*", async route => {
    const url = new URL(route.request().url());
    if (url.origin === new URL(testInfo.project.use.baseURL as string).origin) return route.continue();
    externalRequests.push(url.pathname);
    await route.abort("blockedbyclient");
  });
  await page.addInitScript(() => {
    // 只模拟原生 IPC 边界；运行真实页面、状态管理、路由与请求分流，不读取系统凭据。
    const surface = window as unknown as {
      isTauri: boolean;
      __TAURI_INTERNALS__: Record<string, unknown>;
      __localFixturePaths: string[];
    };
    surface.isTauri = true;
    surface.__localFixturePaths = [];
    let callbackId = 0;
    surface.__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
      transformCallback: () => ++callbackId,
      unregisterCallback: () => undefined,
      invoke: async (command: string, args: {
        id: string; request: { path: string; headers: Record<string, string> };
        onEvent: { onmessage: (frame: unknown) => void };
      }) => {
        if (command === "start_local_executor") return { transport: "stdio", protocol: 2 };
        if (command === "local_executor_request") {
          const path = args.request.path.split("?")[0];
          surface.__localFixturePaths.push(path);
          let body: unknown = [];
          if (path === "/health") body = { mode: "desktop-local", protocol: 1 };
          else if (path === "/identity/local") body = { ready: true, access_token: `local-session:${"a".repeat(43)}` };
          else if (path === "/identity/clear") body = { cleared: true };
          else {
            if (args.request.headers.authorization !== `Bearer local-session:${"a".repeat(43)}`) {
              throw new Error("本机业务请求缺少独立身份凭证");
            }
            if (path === "/capabilities") body = { coding_agent_ui_enabled: true, project_bound_runs_enabled: true };
            if (path === "/model-settings") body = { llm_temperature: 0.2, llm_context_length: 8192, kb_enabled_by_default: false };
          }
          args.onEvent.onmessage({ id: args.id, status: 200, headers: { "Content-Type": "application/json" } });
          args.onEvent.onmessage({ id: args.id, data: JSON.stringify(body) });
          args.onEvent.onmessage({ id: args.id, done: true });
          return;
        }
        if (command.startsWith("plugin:event|")) return 1;
        throw new Error("测试未开放此原生操作");
      },
    };
  });

  await page.goto("/#/login");
  await expect(page).toHaveURL(/#\/app$/);
  await expect(page.getByTestId("auth-local-access")).toHaveCount(0);
  await expect(page.getByTestId("coding-nav-tasks")).toHaveCount(0);
  await page.getByTestId("coding-nav-extensions").click();
  await expect(page.getByRole("heading", { name: "让搭档多一份能力" })).toBeVisible();
  await page.goto("/#/app?view=settings");
  await page.reload();
  await page.getByTestId("settings-section-appearance").click();
  await expect(page.getByTestId("wallpaper-plugin")).toContainText("壁纸主题");
  await expect(page.getByRole("switch", { name: "启用壁纸主题" })).toHaveAttribute("aria-checked", "false");
  await page.goto("/#/app?view=settings&section=provider");
  await page.reload();
  await expect(page.getByTestId("model-provider-manager")).toBeVisible();
  await expect(page.getByPlaceholder("输入 API Key")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("api-key-settings.png"), fullPage: true });
  expect(await page.evaluate(() => sessionStorage.getItem("pa_access_token"))).toBeNull();

  await page.reload();
  await expect(page.getByTestId("model-provider-manager")).toBeVisible();
  await page.getByRole("button", { name: "备份与恢复", exact: true }).click();
  await expect(page.getByRole("button", { name: "导出当前工作记录" })).toBeVisible();
  await expect(page.getByRole("button", { name: "导出旧完整后端历史" })).toHaveCount(0);
  await page.getByRole("button", { name: "返回应用", exact: true }).click();
  await expect(page.getByTestId("user-menu-trigger")).toContainText("本机工作区");
  await expect(page.getByTestId("coding-home-no-projects")).toBeVisible();
  await expect(page.getByTestId("coding-home-sidecar-unavailable")).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("api-key-workspace.png"), fullPage: true });
  await page.evaluate(() => localStorage.setItem("pa_last_view", "diagnostics"));
  await page.goto("/#/app");
  await page.reload();
  await expect(page.getByTestId("coding-home-no-projects")).toBeVisible();
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog", { name: "搜索与命令" })).toBeVisible();
  await page.getByRole("button", { name: "导航命令", exact: true }).click();
  await expect(page.getByText("打开诊断", { exact: true })).toHaveCount(0);
  await page.getByLabel("搜索内容", { exact: true }).fill("诊断");
  await expect(page.getByText("无匹配命令", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByText("加载诊断失败", { exact: true })).toHaveCount(0);
  await page.evaluate(() => sessionStorage.clear());
  await page.goto("/");
  await expect(page).toHaveURL(/#\/app$/);
  await expect(page.getByTestId("user-menu-trigger")).toContainText("本机工作区");
  await expect(page.getByTestId("coding-home-no-projects")).toBeVisible();
  await page.goto("/#/admin");
  await expect(page).toHaveURL(/#\/app$/);
  await expect(page.getByTestId("coding-home-no-projects")).toBeVisible();
  const paths = await page.evaluate(() => (window as unknown as { __localFixturePaths: string[] }).__localFixturePaths);
  expect(paths.some(path => /^\/(auth|admin|agent-tasks|extensions)(\/|$)/.test(path))).toBe(false);
  expect(externalRequests).toEqual([]);
});
