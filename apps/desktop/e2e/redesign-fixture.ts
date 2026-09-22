import type { Page } from "@playwright/test";
import { prepareCodingFixture } from "./coding-auth-fixture";

const stamp = "2026-09-22T02:00:00Z";
const projects = ["PrivateAgent", "设计实验室", "示例项目", "文档工具"].map((name, i) => ({
  id: i + 1, name, root_path: `F:\\Fixture\\project-${i + 1}`, status: "active", updated_at: stamp, created_at: stamp,
}));
const workspace = (id: number) => ({ id: id * 100 + 1, project_id: id, kind: "root", root_path: projects[id - 1]?.root_path,
  branch_name: "main", head_sha: "a".repeat(40), status: "active", last_used_at: stamp });
const thread = { id: 11, project_id: 1, workspace_id: 101, title: "优化页面布局", kind: "coding", last_run_id: null,
  updated_at: stamp, created_at: stamp, archived_at: null };

/** 只在隔离浏览器内提供页面数据；任何未定义请求都会失败，不连接真实服务。 */
export async function prepareRedesignFixture(page: Page) {
  const unknownRequests: string[] = [];
  const writes: string[] = [];
  const browserErrors: string[] = [];
  page.on("pageerror", error => browserErrors.push(error.message));
  page.on("console", message => { if (message.type() === "error") browserErrors.push(message.text()); });
  await prepareCodingFixture(page);
  await page.addInitScript(() => {
    const surface = window as unknown as { __TAURI_INTERNALS__: { invoke: (command: string, args: unknown) => Promise<unknown> } };
    const invoke = surface.__TAURI_INTERNALS__.invoke;
    surface.__TAURI_INTERNALS__.invoke = (command, args) => command === "get_update_configuration"
      ? Promise.resolve({ version: "1.0.0", endpoint: null, target: "local" }) : invoke(command, args);
  });
  await page.clock.install({ time: new Date(stamp) });
  await page.clock.setFixedTime(new Date(stamp));
  await page.route("**://127.0.0.1:8000/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== "GET") writes.push(`${request.method()} ${path}`);
    let json: unknown;
    if (path === "/capabilities") json = { coding_agent_ui_enabled: true, agent_runs_api_enabled: true, project_bound_runs_enabled: true,
      coding_worktree_enabled: true, coding_context_budget_enabled: true, coding_recovery_contract_version: "1.0" };
    else if (path === "/projects") json = projects;
    else if (/^\/projects\/\d+$/.test(path)) json = projects[Number(path.split("/")[2]) - 1];
    else if (/^\/projects\/\d+\/workspaces$/.test(path)) json = [workspace(Number(path.split("/")[2]))];
    else if (/^\/projects\/\d+\/workspaces\/\d+$/.test(path)) json = workspace(Number(path.split("/")[2]));
    else if (path.endsWith("/git/branches")) json = { is_git: true, current_branch: "main", head_sha: "a".repeat(40), dirty: false,
      branches: [{ name: "main", is_current: true, head_sha: "a".repeat(40) }] };
    else if (path === "/sessions" || path === "/sessions/recent") json = new URL(request.url()).searchParams.get("project_id") === "1" ? [thread] : [];
    else if (path === "/sessions/11") json = thread;
    else if (path.endsWith("/latest-agent-run")) json = { run_id: null };
    else if (path.endsWith("/messages")) json = [
      { id: 30, session_id: 11, role: "user", content: "请检查首页布局，保留现有项目和会话行为。", created_at: stamp },
      { id: 31, session_id: 11, role: "assistant", content: "## 页面布局检查\n\n首页现在依次展示欢迎区、最近项目、快捷任务和输入框。\n\n- 保留项目选择与首次发送流程\n- 统一输入、列表与审批状态\n- 检查窄窗口中的换行和键盘焦点\n\n```ts\nconst visibleProjects = projects.slice(0, 3);\n```\n\n接下来可以从侧栏继续原有任务。", created_at: stamp },
    ];
    else if (path === "/agent-model-profiles") json = [{ id: "fixture-model", display_name: "示例模型", model_name: "deepseek-flash",
      provider_id: "fixture", provider: "openai", provider_name: "示例供应商", enabled: true, is_default: true, is_local: false,
      native_tool_calls: true, supports_streaming: true, context_tokens: 128000, reasoning_efforts: ["low", "medium", "high"] }];
    else if (path === "/model-providers") json = [{ id: "fixture", name: "示例供应商", protocol: "openai", base_url: "https://example.com/v1",
      api_format: "chat_completions", enabled: true, is_builtin: false, api_key_configured: true,
      models: [{ profile_id: "fixture-model", model_id: "deepseek-flash", context_tokens: 128000, max_output_tokens: 8192, metadata_source: "user_override" }] }];
    else if (path === "/model-settings") json = { llm_temperature: 0.7, llm_context_length: 8192, kb_enabled_by_default: false };
    else if (path.endsWith("/observer-config")) json = { version: 0, enabled: false, checks: [] };
    else if (path.endsWith("/turn-queue")) json = { item: null };
    else if (path.endsWith("/context-budget")) json = { used_tokens: 0, max_context_tokens: 128000, reserved_output_tokens: 8192,
      usage_percent: 0, cache_hit_percent: null, source: "estimate", compaction_state: "idle", last_compacted_at: null, error_code: null, error_reason: null };
    else if (path.endsWith("/review")) json = { scope: "task", runs: [], workspace: { is_git: true, entries: [], next_cursor: null } };
    else if (path.endsWith("/skills")) json = { items: [{ id: "project:review", name: "project-review", description: "检查当前项目的代码改动与测试结果。", scope: "project", enabled: true, version: "b".repeat(64), missing_dependencies: [] }] };
    else if (path.endsWith("/integrations")) json = { items: [{ id: "docs", name: "项目文档", transport: "https", url: "https://example.com/mcp",
      enabled: true, version: 1, connection: { status: "connected" }, tools: [], catalog: { tools: [] } }] };
    else if (path.endsWith("/handoffs") || path.endsWith("/agents") || path.endsWith("/browser-evidence")) json = { items: [] };
    else if (path === "/local-memories/settings") json = { enabled: false, use_memories: true, generate_memories: false,
      exclude_external_context: true, model_profile_id: null, idle_seconds: 300, max_calls_per_day: 12, version: 1, generation_since: "" };
    else if (path === "/local-memories/status") json = { calls_today: 0, worker_running: false, last_attempt: null, error: null };
    else if (path === "/local-memories/items" || path === "/local-history/imports" || path.endsWith("/documentation-sources")) json = [];
    else {
      unknownRequests.push(path);
      return route.fulfill({ status: 404, json: { detail: "视觉夹具未定义此请求" } });
    }
    return route.fulfill({ json });
  });
  return { unknownRequests, writes, browserErrors };
}

export async function settleDesign(page: Page) {
  await page.mouse.move(1, 1);
  await page.clock.runFor(250);
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(Array.from(document.images).map(img => img.decode().catch(() => undefined)));
  });
}
