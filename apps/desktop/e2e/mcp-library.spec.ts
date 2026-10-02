import { expect, test } from "@playwright/test";

test("个人 MCP 服务库原生凭据桥、项目独立授权与参数向导", async ({ page }, testInfo) => {
  const external: string[] = [];
  await page.route("**/*", async route => {
    if (new URL(route.request().url()).origin === new URL(testInfo.project.use.baseURL as string).origin) return route.continue();
    external.push(new URL(route.request().url()).origin);
    await route.abort("blockedbyclient");
  });
  await page.addInitScript(() => {
    const state = { nativeWrites: 0, connected: 0, requests: [] as { path: string; body: unknown }[], selections: [] as { project: number; body: unknown }[] };
    const surface = window as unknown as { isTauri: boolean; __TAURI_INTERNALS__: Record<string, unknown>; __mcpFixture: typeof state };
    surface.isTauri = true; surface.__mcpFixture = state;
    const serviceId = "b".repeat(32), revision = "c".repeat(32), identity = "d".repeat(64);
    const projects = [7, 8].map(id => ({ id, name: `项目 ${id}`, status: "active", updated_at: new Date().toISOString(), root_path: `C:/fixture/project-${id}` }));
    let service: Record<string, any> | null = null, change: Record<string, any> | null = null, callbackId = 0;
    const sources: Record<number, Record<string, any>> = {};
    surface.__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
      transformCallback: () => ++callbackId, unregisterCallback: () => undefined,
      invoke: async (command: string, args: any) => {
        if (command === "start_local_executor") return { transport: "stdio", protocol: 2 };
        if (command === "local_executor_cancel") return;
        if (command.startsWith("plugin:event|")) return 1;
        if (command === "set_mcp_credential") {
          if (args.binding.service_id !== serviceId || JSON.parse(args.value).bearer !== "synthetic-ui-only") throw new Error("凭据桥入参错误");
          state.nativeWrites++;
          return { reference: `secret://os-keyring/mcp/${identity}/${serviceId}/${revision}/static`, configured: true };
        }
        if (command !== "local_executor_request") throw new Error("未开放的测试操作");
        const path = args.request.path.split("?")[0], data = args.request.body ? JSON.parse(args.request.body) : null;
        const method = args.request.method, project = Number(path.match(/^\/projects\/(\d+)/)?.[1]);
        let body: unknown = [];
        if (path === "/health") body = { mode: "desktop-local", protocol: 1 };
        else if (path === "/identity/local") body = { ready: true, access_token: `local-session:${"a".repeat(43)}` };
        else {
          if (args.request.headers.authorization !== `Bearer local-session:${"a".repeat(43)}`) throw new Error("缺少本机身份");
          if (["POST", "PUT", "DELETE"].includes(method)) state.requests.push({ path, body: data });
          if (path === "/capabilities") body = { coding_agent_ui_enabled: true, project_bound_runs_enabled: true };
          else if (path === "/projects") body = projects;
          else if (/^\/projects\/\d+$/.test(path)) body = projects.find(item => item.id === project);
          else if (path.endsWith("/workspaces")) body = [{ id: project, project_id: project, name: "主工作区", root_path: `C:/fixture/project-${project}`, kind: "root", status: "active" }];
          else if (path === "/model-settings") body = { llm_temperature: 0.2, llm_context_length: 8192, kb_enabled_by_default: false };
          else if (path === "/mcp-services") body = { items: service ? [{ ...service, projects: Object.keys(sources).map(id => ({ project_id: Number(id), project_name: `项目 ${id}`, source_id: sources[Number(id)].id })) }] : [], pending_changes: [], credential_cleanup_pending: [] };
          else if (path === "/mcp-services/preflight") body = { valid: true, notice: "配置结构检查通过，尚未连接服务或启动进程。" };
          else if (path === "/mcp-services/prepare") {
            change = { ...data, id: data.request_id, service_id: serviceId, credential_revision: revision, required_fields: ["bearer"],
              binding: { identity, service_id: serviceId, version: revision, slot: "static" } };
            body = change;
          } else if (path.endsWith("/commit")) {
            if (data.reference !== `secret://os-keyring/mcp/${identity}/${serviceId}/${revision}/static`) throw new Error("提交必须只有原生引用");
            service = { ...change!.configuration, id: serviceId, version: "e".repeat(32), credential_revision: revision, auth_revision: "f".repeat(32), projects: [], required_fields: ["bearer"] };
            body = service;
          } else if (path.endsWith("/integrations/bind")) {
            sources[project] = { ...service, id: `source-${project}`, service_id: serviceId, service_version: service!.version, version: `v-${project}`, enabled: false,
              tools: [], catalog: null, discovered_at: null, connection: { status: null, authorization_url: null, error: null } };
            body = sources[project];
          } else if (path.endsWith("/integrations")) {
            body = { items: sources[project] ? [sources[project]] : [] };
          } else if (path.endsWith("/connect")) {
            state.connected++;
            sources[project] = { ...sources[project], discovered_at: "2026-10-02T08:00:00Z", connection: { status: "connected" }, catalog: { tools: [
              { name: "lookup", description: "读取测试目录", input_schema: { type: "object", properties: {} } },
            ], unavailable_tools: [{ name: "recursive", reason: "不支持递归引用", error_code: "mcp_invalid_schema" }] } };
            body = { started: true };
          } else if (/\/integrations\/source-\d+$/.test(path) && method === "PUT") {
            state.selections.push({ project, body: data });
            sources[project] = { ...sources[project], enabled: data.enabled, tools: data.tools }; body = sources[project];
          }
        }
        args.onEvent.onmessage({ id: args.id, status: 200, headers: { "Content-Type": "application/json" } });
        args.onEvent.onmessage({ id: args.id, data: JSON.stringify(body) });
        args.onEvent.onmessage({ id: args.id, done: true });
      },
    };
  });
  await page.goto("/#/app?view=settings");
  await page.getByRole("button", { name: "MCP 外部能力", exact: true }).click();
  const panel = page.getByRole("region", { name: "通用 MCP 服务" });
  await panel.getByText("添加 MCP 服务", { exact: true }).click();
  await panel.getByLabel("名称", { exact: true }).fill("团队查询服务");
  await panel.getByLabel("服务地址").fill("https://fixture.example.test/mcp");
  await panel.getByLabel("认证方式").selectOption("bearer");
  await panel.getByLabel("Bearer Token", { exact: true }).fill("synthetic-ui-only");
  await panel.getByRole("button", { name: "本地检查配置" }).click();
  await expect(panel.getByText("配置结构检查通过，尚未连接服务或启动进程。")).toBeVisible();
  await panel.getByRole("button", { name: "保存配置", exact: true }).click();
  await expect(panel.getByRole("article").getByText("团队查询服务", { exact: true })).toBeVisible();
  const saved = await page.evaluate(() => (window as any).__mcpFixture);
  expect(saved.nativeWrites).toBe(1); expect(saved.connected).toBe(0); expect(saved.selections).toEqual([]);
  expect(JSON.stringify(saved.requests)).not.toContain("synthetic-ui-only");
  await panel.getByRole("button", { name: "连接并发现", exact: true }).click();
  await expect(panel.getByText(/最近验证：.*2026/)).toBeVisible();
  await panel.getByText("检查并选择工具（1）", { exact: true }).click();
  await expect(panel.getByText("recursive：暂不可用，不支持递归引用")).toBeVisible();
  await panel.getByRole("checkbox", { name: "lookup", exact: true }).check();
  await panel.getByRole("button", { name: "保存并启用所选工具" }).click();
  await expect(panel.getByText(/工具已启用/)).toBeVisible();
  await page.getByLabel("MCP 所属项目").selectOption("8");
  await panel.getByText("个人服务库（1）", { exact: true }).click();
  await panel.getByRole("button", { name: "绑定当前项目" }).click();
  await expect(panel.getByRole("article").getByText(/工具未启用/)).toBeVisible();
  const rebound = await page.evaluate(() => (window as any).__mcpFixture);
  expect(rebound.nativeWrites).toBe(1); expect(rebound.selections).toHaveLength(1); expect(rebound.selections[0].project).toBe(7);
  await panel.getByText("添加 MCP 服务", { exact: true }).click();
  await panel.getByLabel("名称", { exact: true }).fill("本机参数检查");
  await panel.getByLabel("连接类型").selectOption("stdio");
  await panel.getByLabel("可执行文件绝对路径").fill("C:/fixture/node.exe");
  await panel.getByRole("button", { name: "添加参数", exact: true }).click();
  await panel.getByRole("textbox", { name: "参数 1", exact: true }).fill("C:/fixture with spaces/server.js");
  await panel.getByRole("button", { name: "添加参数", exact: true }).click();
  await panel.getByRole("checkbox", { name: /我信任此程序/ }).check();
  await panel.getByRole("button", { name: "本地检查配置" }).click();
  await expect.poll(() => page.evaluate(() => (window as any).__mcpFixture.requests.filter((item: any) => item.path.endsWith("/preflight") && item.body.transport === "stdio").at(-1)?.body.args))
    .toEqual(["C:/fixture with spaces/server.js", ""]);
  await expect(panel.getByRole("button", { name: "本地检查配置" })).toBeEnabled();
  await page.setViewportSize({ width: 760, height: 900 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("mcp-library-narrow.png"), fullPage: true });
  expect(external).toEqual([]);
});
