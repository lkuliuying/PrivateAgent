import { expect, test } from "@playwright/test";

test("本机文档 MCP 的发现、启用与窄窗口设置", async ({ page }, testInfo) => {
  const external: string[] = [];
  await page.route("**/*", async route => {
    if (new URL(route.request().url()).origin === new URL(testInfo.project.use.baseURL as string).origin) return route.continue();
    external.push(new URL(route.request().url()).origin);
    await route.abort("blockedbyclient");
  });
  await page.addInitScript(() => {
    const surface = window as unknown as { isTauri: boolean; __TAURI_INTERNALS__: Record<string, unknown> };
    surface.isTauri = true;
    let source: Record<string, unknown> | null = null;
    let callbackId = 0;
    surface.__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
      transformCallback: () => ++callbackId, unregisterCallback: () => undefined,
      invoke: async (command: string, args: { id: string; request: { path: string; method: string; body: string; headers: Record<string, string> };
        onEvent: { onmessage: (frame: unknown) => void } }) => {
        if (command === "start_local_executor") return { transport: "stdio", protocol: 2 };
        if (command === "local_executor_cancel") return;
        if (command.startsWith("plugin:event|")) return 1;
        if (command !== "local_executor_request") throw new Error("未开放的测试操作");
        const path = args.request.path.split("?")[0];
        let body: unknown = [];
        if (path === "/health") body = { mode: "desktop-local", protocol: 1 };
        else if (path === "/identity/local") body = { ready: true, access_token: `local-session:${"a".repeat(43)}` };
        else if (path === "/identity/clear") body = { cleared: true };
        else {
          if (args.request.headers.authorization !== `Bearer local-session:${"a".repeat(43)}`) throw new Error("缺少本机身份");
          if (path === "/capabilities") body = { coding_agent_ui_enabled: true, project_bound_runs_enabled: true };
          else if (path === "/projects") body = [{ id: 7, name: "文档工具验收项目", status: "active", updated_at: new Date().toISOString() }];
          else if (path.endsWith("/integrations")) body = { items: [] };
          else if (path === "/model-settings") body = { llm_temperature: 0.2, llm_context_length: 8192, kb_enabled_by_default: false };
          else if (path === "/projects/7/documentation-sources") {
            if (args.request.method === "POST") {
              source = { ...JSON.parse(args.request.body), id: "source", version: "v1", enabled: false, tools: [], catalog: null, discovered_at: null };
              body = source;
            } else body = source ? [source] : [];
          } else if (path.endsWith("/source/discover")) {
            source = { ...source, version: "v2", discovered_at: new Date().toISOString(), catalog: { sha256: "fixture", tools: [
              { name: "microsoft_docs_search", description: "检索官方技术文档，并返回原文链接。", input_schema: { type: "object" }, output_schema: null },
            ] } };
            body = source;
          } else if (path.endsWith("/source/selection")) {
            const selection = JSON.parse(args.request.body);
            source = { ...source, version: "v3", enabled: selection.enabled, tools: selection.tools };
            body = source;
          }
        }
        args.onEvent.onmessage({ id: args.id, status: 200, headers: { "Content-Type": "application/json" } });
        args.onEvent.onmessage({ id: args.id, data: JSON.stringify(body) });
        args.onEvent.onmessage({ id: args.id, done: true });
      },
    };
  });
  await page.goto("/#/app?view=settings&section=provider");
  await expect(page.getByTestId("model-provider-manager")).toBeVisible();
  await page.getByRole("button", { name: "MCP 外部能力", exact: true }).click();
  await page.getByText("公开文档服务", { exact: true }).click();
  await expect(page.getByRole("button", { name: "添加文档服务" })).toBeEnabled();
  await page.getByRole("button", { name: "添加文档服务" }).click();
  await page.getByRole("button", { name: "发现工具", exact: true }).click();
  await page.getByRole("button", { name: "连接并发现" }).click();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "启用所选工具", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "启用所选工具" }).click();
  await expect(page.getByText("已启用", { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("documentation-wide.png"), fullPage: true });
  await page.setViewportSize({ width: 760, height: 900 });
  await expect(page.getByRole("button", { name: "停用", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("documentation-narrow.png"), fullPage: true });
  await page.getByRole("button", { name: "停用", exact: true }).click();
  await expect(page.getByText("未启用", { exact: true })).toBeVisible();
  expect(external).toEqual([]);
});
