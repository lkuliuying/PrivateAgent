import { expect, test, type Page } from "@playwright/test";
import { prepareCodingFixture } from "./coding-auth-fixture";

const stamp = "2026-09-21T00:00:00Z";
const runId = "10101010-1010-4010-8010-101010101099";

async function fixture(page: Page, running = false, modelName = "deepseek-flash") {
  await prepareCodingFixture(page);
  if (running) await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (!url.pathname.endsWith("/events/stream")) return originalFetch(input, init);
      let sequence = Number(url.searchParams.get("after_sequence") ?? 0);
      let stopped = false;
      let timer: ReturnType<typeof setTimeout> | undefined;
      const controller = new AbortController();
      const stop = () => { stopped = true; clearTimeout(timer); controller.abort(); };
      const body = new ReadableStream<Uint8Array>({
        start(stream) {
          const encoder = new TextEncoder();
          async function poll() {
            try {
              // 使用同一隔离事件记录持续推送，避免有限响应伪装成长连接。
              const result = await originalFetch(`${url.origin}${url.pathname.replace(/\/stream$/, "")}?after_sequence=${sequence}`, { signal: controller.signal });
              if (!result.ok) throw new Error(`隔离事件读取失败：${result.status}`);
              const data = await result.json();
              if (stopped) return;
              for (const event of data.items) {
                stream.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
                sequence = event.sequence;
              }
              timer = setTimeout(poll, 100);
            } catch (error) { if (!stopped) { stop(); stream.error(error); } }
          }
          void poll();
        },
        cancel: stop,
      });
      window.addEventListener("pagehide", stop, { once: true });
      return Promise.resolve(new Response(body, { headers: { "Content-Type": "text/event-stream" } }));
    };
  });
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  const searches: URLSearchParams[] = [];
  const project = { id: 1, name: "工作台验收", root_path: "F:\\Fixture Workbench", status: "active", updated_at: stamp, created_at: stamp };
  const workspace = { id: 101, project_id: 1, root_path: project.root_path, kind: "root", status: "active", branch_name: "main", head_sha: "a".repeat(40), last_used_at: stamp };
  const workspaces = [workspace];
  const thread = { id: 11, project_id: 1, workspace_id: 101, title: "检查交付", kind: "coding", last_run_id: running ? runId : null, updated_at: stamp, created_at: stamp, archived_at: null as string | null };
  const run = { id: runId, session_id: 11, status: "running", provider: "fixture", model: "fixture", last_event_sequence: 1,
    tool_call_count: 0, input_tokens: 0, output_tokens: 0, cached_tokens: 0, cost_usd: null, output: null,
    error_code: null, error_message: null, cancel_requested_at: null, started_at: stamp, completed_at: null,
    created_at: stamp, updated_at: stamp, active_in_process: true, steps: [], project_id: 1, workspace_id: 101,
    base_head_sha: workspace.head_sha, base_branch_name: "main", base_git_dirty: false, model_profile_id: null,
    reasoning_effort: null, permission_mode: "confirm", plan: null, artifacts: [] };
  const recovery = { run_id: runId, status: "running", state_version: 1, checkpoint_id: "checkpoint", logical_task_id: runId,
    resumed_from_run_id: null, can_resume: false, blockers: [], controls: [], executions: [], budget: {}, expired_approvals: [], limitations: [] };
  const events = [{ sequence: 1, type: "run.started", payload: {} }];
  let queued: Record<string, unknown> | null = null;
  const skills: Record<string, unknown>[] = [];
  let skillText = "";
  await page.route("**://127.0.0.1:8000/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = decodeURIComponent(url.pathname), method = request.method();
    const body = method === "GET" || !request.postData() ? {} : request.postDataJSON();
    if (method !== "GET") writes.push({ path, body });
    if (path === "/capabilities") return route.fulfill({ json: { coding_agent_ui_enabled: true, agent_runs_api_enabled: true, project_bound_runs_enabled: true, coding_worktree_enabled: true, coding_context_budget_enabled: true, coding_recovery_contract_version: "1.0", coding_patchsets_enabled: true } });
    if (path === "/agent-model-profiles") return route.fulfill({ json: [
      { id: "fixture-model", display_name: "隔离模型", model_name: modelName, provider: "openai", provider_name: "供应商测试名称", enabled: true, is_default: true, is_local: false, native_tool_calls: true, supports_streaming: true, context_tokens: 258000, reasoning_efforts: ["low", "medium", "high", "max"] },
      { id: "fixture-qwen", display_name: "另一个隔离模型", model_name: "qwen-3.8-flash", provider: "openai", provider_name: "另一供应商", enabled: true, is_default: false, is_local: false, native_tool_calls: true, supports_streaming: true, context_tokens: 128000, reasoning_efforts: ["low", "high"] },
    ] });
    if (path === "/projects") return route.fulfill({ json: [project] });
    if (path === "/projects/1") return route.fulfill({ json: project });
    if (path === "/projects/1/workspaces") return route.fulfill({ json: workspaces });
    if (path === "/projects/1/observer-config") return route.fulfill({ json: { version: 0, enabled: false, checks: [] } });
    if (path === "/projects/1/workspaces/worktree") {
      const created = { ...workspace, id: 102, kind: "git_worktree", branch_name: "codex/worktree" };
      workspaces.push(created);
      return route.fulfill({ json: created });
    }
    if (path === "/projects/1/workspaces/101") return route.fulfill({ json: workspace });
    if (path.endsWith("/git/branches")) return route.fulfill({ json: { is_git: true, current_branch: "main", head_sha: workspace.head_sha, dirty: false, branches: [{ name: "main", is_current: true, head_sha: workspace.head_sha }] } });
    if (path === "/sessions/11/archive") { thread.archived_at = stamp; return route.fulfill({ json: thread }); }
    if (path === "/sessions/11/unarchive") { thread.archived_at = null; return route.fulfill({ json: thread }); }
    if (path === "/sessions" || path === "/sessions/recent") return route.fulfill({ json: thread.archived_at ? [] : [thread] });
    if (path === "/sessions/11") return route.fulfill({ json: thread });
    if (path.endsWith("/latest-agent-run")) return route.fulfill({ json: { run_id: thread.last_run_id } });
    if (path.endsWith("/messages")) return route.fulfill({ json: running ? [] : [{ id: 31, session_id: 11, role: "assistant", content: "这是一条可定位的历史证据。", created_at: stamp }] });
    if (path === "/workspace-search") {
      searches.push(url.searchParams);
      return route.fulfill({ json: { items: [{ kind: "message", project_id: 1, project_name: project.name, session_id: 11, message_id: 31, title: thread.title, excerpt: "可定位的历史证据", updated_at: stamp, status: "completed", archived: !!thread.archived_at }], next_cursor: null, examined: 1 } });
    }
    if (path === "/sessions/11/review") return route.fulfill({ json: { scope: url.searchParams.get("scope"), runs: [], workspace: { is_git: true, entries: [{ rel_path: "src/app.ts", status: "M" }], next_cursor: null } } });
    if (path === "/sessions/11/review/diff") return route.fulfill({ json: { rel_path: "src/app.ts", version: "b".repeat(64), diff: "@@ -4,1 +4,1 @@\n-before\n+after\n", next_offset: null } });
    if (path.endsWith("/context-budget")) return route.fulfill({ json: {
      used_tokens: 142000, max_context_tokens: 258000, reserved_output_tokens: 2048, usage_percent: 55,
      cache_hit_percent: null, source: "provider_usage", compaction_state: "idle", last_compacted_at: null, error_code: null, error_reason: null,
    } });
    if (path === `/agent-runs/${runId}`) return route.fulfill({ json: run });
    if (path === `/agent-runs/${runId}/events`) return route.fulfill({ json: { last_sequence: run.last_event_sequence, items: events.filter(event => event.sequence > Number(url.searchParams.get("after_sequence") ?? 0)) } });
    if (path === `/agent-runs/${runId}/recovery`) return route.fulfill({ json: recovery });
    if (path.endsWith("/steer") || path.endsWith("/pause") || path.endsWith("/resume")) {
      if (path.endsWith("/pause")) { recovery.status = "paused"; recovery.can_resume = true; }
      if (path.endsWith("/resume")) { recovery.status = "running"; recovery.can_resume = false; }
      if (path.endsWith("/pause") || path.endsWith("/resume")) {
        run.status = recovery.status;
        events.push({ sequence: ++run.last_event_sequence, type: path.endsWith("/pause") ? "run.paused" : "run.resumed", payload: {} });
      }
      recovery.state_version++;
      return route.fulfill({ json: { request_id: body.request_id, kind: path.split("/").pop(), status: "applied", result_run_id: runId } });
    }
    if (path === "/sessions/11/turn-queue") {
      if (method === "POST") queued = { ...body, state: "pending", after_run_id: runId };
      return route.fulfill({ json: method === "GET" ? { item: queued } : queued });
    }
    if (path.startsWith("/sessions/11/turn-queue/") && method === "DELETE") { queued = { ...queued, state: "cancelled" }; return route.fulfill({ json: queued }); }
    if (path.endsWith("/approvals") || path.endsWith("/executions")) return route.fulfill({ json: [] });
    if (path === "/projects/1/skills") {
      if (method === "POST") { skillText = body.content; skills.push({ id: "project:review", name: "project-review", description: "审阅技能", scope: "project", version: "c".repeat(64), enabled: false, missing_dependencies: [] }); }
      return route.fulfill({ json: { items: skills } });
    }
    if (path === "/projects/1/skills/project:review") {
      if (method === "PUT") { skills[0].enabled = body.enabled; return route.fulfill({ json: { updated: true } }); }
      return route.fulfill({ json: { content: skillText } });
    }
    if (path.endsWith("/integrations") || path.endsWith("/handoffs") || path.endsWith("/agents") || path.endsWith("/browser-evidence")) return route.fulfill({ json: { items: [] } });
    return route.fulfill({ status: 404, json: { error_code: "test_unhandled", detail: "隔离场景未定义此接口" } });
  });
  await page.setViewportSize({ width: 1440, height: 950 });
  await page.goto("/app?view=coding");
  return { writes, searches };
}

test("搜索定位、归档恢复与行级审阅在宽窄窗口可操作", async ({ page }, testInfo) => {
  const { writes, searches } = await fixture(page);
  const sidebarResize = page.getByRole("separator", { name: "调整侧栏宽度", exact: true });
  await sidebarResize.press("Home"); await expect(sidebarResize).toHaveAttribute("aria-valuenow", "240");
  await sidebarResize.press("ArrowRight"); await expect(sidebarResize).toHaveAttribute("aria-valuenow", "256");
  await expect(sidebarResize).toBeFocused();
  expect(await sidebarResize.evaluate(element => getComputedStyle(element).outlineStyle)).toBe("solid");
  await page.getByTestId("coding-open-search").click();
  await page.getByLabel("搜索内容").fill("历史证据");
  await expect.poll(() => searches.at(-1)?.get("q")).toBe("历史证据");
  await page.getByRole("button", { name: /检查交付.*可定位/ }).click();
  const message = page.locator('[data-message-id="31"]');
  await expect(message).toBeFocused();
  await page.getByLabel("任务输入", { exact: true }).fill("原有草稿");
  await page.getByTestId("thread-environment-toggle").click();
  const reviewResize = page.getByRole("separator", { name: "调整审阅面板宽度", exact: true });
  await reviewResize.press("Home"); await expect(reviewResize).toHaveAttribute("aria-valuenow", "320");
  await reviewResize.press("ArrowLeft"); await expect(reviewResize).toHaveAttribute("aria-valuenow", "336");
  await expect(reviewResize).toBeFocused();
  expect(await reviewResize.evaluate(element => getComputedStyle(element).outlineStyle)).toBe("solid");
  await reviewResize.press("ArrowLeft"); await reviewResize.press("ArrowLeft"); await reviewResize.press("ArrowLeft");
  await page.getByRole("combobox", { name: "审阅范围", exact: true }).selectOption("workspace");
  await page.getByRole("combobox", { name: "文件", exact: true }).selectOption("src/app.ts");
  await page.getByRole("button", { name: "反馈修改后第 4 行", exact: true }).click();
  await page.getByPlaceholder("描述问题及期望行为…").fill("为空时返回数组");
  await page.getByRole("button", { name: "添加到任务输入", exact: true }).click();
  await expect(page.getByLabel("任务输入", { exact: true })).toHaveValue(/原有草稿[\s\S]*src\/app.ts[\s\S]*修改后第 4 行[\s\S]*为空时返回数组/);
  expect(writes).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("workbench-review-wide.png"), fullPage: true });
  await page.setViewportSize({ width: 760, height: 900 });
  await expect.poll(async () => (await page.locator(".appshell-rail").boundingBox())?.width).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("workbench-review-narrow.png"), fullPage: true });
  await page.getByRole("button", { name: "关闭环境面板", exact: true }).click();
  await page.getByTestId("thread-menu-toggle").click();
  await page.getByRole("menuitem", { name: "归档任务", exact: true }).click();
  await expect(page.getByTestId("thread-menu-toggle")).toHaveCount(0);
  await page.getByTestId("coding-drawer-tab").click();
  await page.getByTestId("coding-open-search").click();
  await page.getByLabel("已归档", { exact: true }).check();
  await expect.poll(() => searches.at(-1)?.get("archived")).toBe("true");
  await page.getByRole("button", { name: /检查交付.*可定位/ }).click();
  await expect(message).toBeFocused();
  await expect(page.getByTestId("coding-sidebar")).toHaveCount(0);
  expect(writes.map(item => item.path)).toEqual(["/sessions/11/archive", "/sessions/11/unarchive"]);
});

test("右下角暂停与继续正常工作，运行中只编辑草稿且不再补充或排队", async ({ page }, testInfo) => {
  const { writes } = await fixture(page, true);
  await page.getByTestId("coding-thread-11").click();
  const input = page.getByLabel("任务输入", { exact: true });
  await expect(input).toBeEnabled();
  await expect(page.getByLabel("运行中发送方式")).toHaveCount(0);
  await expect(page.getByText("任务执行中，可补充要求", { exact: true })).toHaveCount(0);
  await expect(page.getByTestId("coding-composer-send")).toHaveCount(0);
  await expect(page.getByTestId("stream-live")).toHaveText("正在思考");
  await input.fill("保留公共接口");
  await input.press("Enter");
  await expect(input).toHaveValue("保留公共接口");
  expect(writes).toEqual([]);
  const pause = page.getByRole("button", { name: "暂停任务", exact: true });
  await expect(pause).toBeEnabled();
  await page.screenshot({ path: testInfo.outputPath("annotation-fix-wide.png"), fullPage: true });
  await page.setViewportSize({ width: 760, height: 900 });
  await expect.poll(async () => (await page.locator(".appshell-rail").boundingBox())?.width).toBe(0);
  await expect(pause).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("annotation-fix-narrow.png"), fullPage: true });
  await pause.click();
  await expect(page.getByRole("button", { name: "继续任务", exact: true })).toBeVisible();
  await expect(pause).toHaveCount(0);
  await expect(page.getByTestId("stream-live")).toHaveCount(0);
  await expect(input).toHaveValue("保留公共接口");
  await page.getByRole("button", { name: "继续任务", exact: true }).click();
  await expect(pause).toBeEnabled();
  await expect(input).toHaveValue("保留公共接口");
  expect(writes.map(item => item.path)).toEqual([`/agent-runs/${runId}/pause`, `/agent-runs/${runId}/resume`]);
  expect(writes[0].body).toMatchObject({ expected_state_version: 1, request_id: expect.any(String) });
});

test("插件中启用技能后通过 /skill 使用，输入区不再显示预算选项", async ({ page }, testInfo) => {
  await fixture(page);
  await page.getByTestId("coding-nav-extensions").click();
  await page.getByRole("button", { name: "新建技能", exact: true }).click();
  await page.getByLabel("目录名称", { exact: true }).fill("review");
  await page.getByRole("button", { name: "保存后检查", exact: true }).click();
  await page.getByRole("button", { name: "检查内容", exact: true }).click();
  await expect(page.locator(".skill-preview pre")).toContainText("先阅读项目规则");
  await page.getByRole("button", { name: "允许当前项目按需使用", exact: true }).click();
  await expect(page.getByText("项目 · 已启用", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "MCP 工具", exact: true }).click();
  await page.getByText("添加 MCP 服务", { exact: true }).click();
  await page.getByRole("combobox", { name: "传输", exact: true }).selectOption("stdio");
  await expect(page.getByLabel("可执行文件绝对路径", { exact: true })).toBeVisible();
  await expect(page.getByText(/我信任此程序/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("workbench-mcp.png"), fullPage: true });
  await page.getByTestId("coding-new-task").click();
  await expect(page.getByText("任务预算与协作", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel(/允许独立只读子任务/)).toHaveCount(0);
  const input = page.getByLabel("任务输入", { exact: true });
  await input.fill("/skill");
  await input.press("Enter");
  await expect(page.getByTestId("composer-skill-pop")).toBeVisible();
  await page.getByRole("button", { name: "project-review", exact: true }).click();
  await expect(input).toHaveValue("$project:review");
});

test("新会话快捷任务、简洁模型 ID 与项目编辑 worktree 在宽窄窗口可用", async ({ page }, testInfo) => {
  const modelName = "deepseek-flash";
  const { writes } = await fixture(page, false, modelName);
  await page.getByTestId("coding-new-task").click();
  const empty = page.getByTestId("coding-home-empty-chat");
  const composer = page.getByTestId("coding-composer");
  await expect(empty.getByRole("button", { name: "读懂项目", exact: true })).toBeVisible();
  await empty.getByRole("button", { name: "审查改动", exact: true }).click();
  await expect(page.getByLabel("任务输入", { exact: true })).toHaveValue(/请审查当前工作区的未提交改动/);
  await expect(composer.getByText("使用技能", { exact: true })).toHaveCount(0);
  await expect(page.locator(".model-selection-label")).toHaveText(modelName);
  await expect(page.locator(".model-select")).not.toContainText("默认");
  await expect(page.locator(".model-select")).not.toContainText("供应商测试名称");
  await page.getByTestId("composer-model").selectOption("fixture-qwen");
  await expect(page.locator(".model-selection-label")).toHaveText("qwen-3.8-flash");
  await page.getByTestId("composer-model").selectOption("fixture-model");
  for (const width of [1440, 900, 600]) {
    await page.setViewportSize({ width, height: 950 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const label = page.locator(".model-selection-label");
    expect(await label.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    await expect(page.getByTestId("coding-composer-send")).toBeInViewport();
    await page.screenshot({ path: testInfo.outputPath(`conversation-controls-${width}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 950 });
  await page.getByTestId("coding-project-1").locator("summary").click();
  await page.getByTestId("coding-project-edit-1").click();
  const editor = page.getByRole("dialog", { name: "编辑项目", exact: true });
  await expect(editor.getByRole("combobox", { name: "起始分支", exact: true })).toHaveValue("main");
  await page.screenshot({ path: testInfo.outputPath("project-worktree-settings.png"), fullPage: true });
  await editor.getByTestId("project-create-worktree").click();
  await expect(editor).toHaveCount(0);
  await expect(page.getByTestId("coding-home-workspace-select")).toHaveValue("102");
  expect(writes.filter(item => item.path === "/projects/1/workspaces/worktree")).toEqual([{ path: "/projects/1/workspaces/worktree", body: { ref: "main", request_id: expect.any(String) } }]);
});

test("上下文、模型 ID 和模型强度依次排列，浮层支持键盘和窄窗口", async ({ page }, testInfo) => {
  await fixture(page);
  await page.getByTestId("coding-thread-11").click();
  const ring = page.getByTestId("context-usage-ring");
  const model = page.locator(".model-selection-label");
  const strength = page.getByTestId("composer-effort");
  for (const width of [1440, 600]) {
    await page.setViewportSize({ width, height: 950 });
    await expect(model).toHaveText("deepseek-flash");
    const ringBox = (await ring.boundingBox())!;
    const modelBox = (await model.boundingBox())!;
    const strengthBox = (await strength.boundingBox())!;
    expect(ringBox.x + ringBox.width).toBeLessThanOrEqual(modelBox.x);
    expect(modelBox.x + modelBox.width).toBeLessThanOrEqual(strengthBox.x);
    await ring.hover();
    const tooltip = page.getByRole("tooltip");
    await expect(tooltip).toContainText("55% 已用");
    await expect(tooltip).toContainText("已用 142k 标记，共 258k");
    await expect(tooltip).toBeInViewport();
    await page.screenshot({ path: testInfo.outputPath(`model-context-${width}.png`), fullPage: true });
    await strength.click();
    const slider = page.getByRole("slider", { name: "模型强度", exact: true });
    await slider.press("End");
    await expect(strength).toHaveText("最高");
    await expect(page.getByTestId("model-strength-popover")).toBeInViewport();
    await page.screenshot({ path: testInfo.outputPath(`model-strength-${width}.png`), fullPage: true });
    await slider.press("ArrowLeft");
    await expect(strength).toHaveText("高");
    await page.getByRole("button", { name: "恢复默认强度", exact: true }).click();
    await expect(strength).toHaveText("默认");
    await expect(slider).toBeFocused();
    await slider.press("Escape");
    await expect(page.getByTestId("model-strength-popover")).toHaveCount(0);
    await expect(strength).toBeFocused();
  }
});

test("关于与更新无需填写地址，检查和安装使用客户端预设来源", async ({ page }, testInfo) => {
  await fixture(page);
  await page.evaluate(() => {
    localStorage.setItem("pa_update_source_unified-windows-x86_64", "https://legacy.example.test/latest.json");
    const surface = window as unknown as {
      __TAURI_INTERNALS__: { invoke: (command: string, args?: unknown) => Promise<unknown> };
      updaterCalls: { command: string; args?: unknown }[];
    };
    const original = surface.__TAURI_INTERNALS__.invoke;
    surface.updaterCalls = [];
    surface.__TAURI_INTERNALS__.invoke = async (command, args) => {
      if (command === "get_update_configuration") return { version: "1.0.0", endpoint: "https://updates.example.test/unified/latest.json", target: "unified-windows-x86_64" };
      if (["check_for_updates", "download_and_install_update", "relaunch_app"].includes(command)) {
        surface.updaterCalls.push({ command, args });
        if (command === "check_for_updates") return { version: "1.0.1", date: null, body: "合成更新，用于验证界面流程。" };
        return;
      }
      return original(command, args);
    };
  });
  await page.getByTestId("user-menu-trigger").click();
  await page.getByTestId("user-menu-settings").click();
  await page.getByTestId("settings-section-about").click();
  await expect(page.getByLabel("更新清单地址", { exact: true })).toHaveCount(0);
  await expect(page.getByText("更新源设置", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "检查更新", exact: true }).click();
  await expect(page.getByRole("button", { name: "下载并安装 v1.0.1", exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("updater-configured.png"), fullPage: true });
  await page.getByRole("button", { name: "下载并安装 v1.0.1", exact: true }).click();
  await page.getByRole("button", { name: "下载并安装", exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { updaterCalls: unknown[] }).updaterCalls)).toEqual([
    { command: "check_for_updates", args: { endpoint: undefined } },
    { command: "download_and_install_update", args: { expectedVersion: "1.0.1", endpoint: undefined } },
    { command: "relaunch_app", args: {} },
  ]);
});
