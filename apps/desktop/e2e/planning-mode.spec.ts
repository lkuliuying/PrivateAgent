import { test, expect } from "@playwright/test";
import { prepareCodingFixture } from "./coding-auth-fixture";

test("规划模式完成澄清、重开恢复和按计划执行，窄屏保留操作入口", async ({ page }, testInfo) => {
  await prepareCodingFixture(page);
  const stamp = "2026-09-20T08:00:00Z";
  const input = { input_id: "q-1", goal_version: 1, generation: 0, created_at: stamp,
    questions: [{ id: "scope", question: "这次调整希望覆盖哪些模块？", options: [
      { label: "当前模块", description: "先完善规划流程" }, { label: "相关模块", description: "包含调用入口与验证流程" }] }] };
  const plan = { version: 1, goal_version: 2, needs_review: false,
    items: [{ item_key: "inspect", ordinal: 1, title: "核对模块职责与现有测试", detail: "检查调用边界，明确验收条件。", status: "pending" },
      { item_key: "edit", ordinal: 2, title: "完善规划交互并验证", detail: "覆盖只读限制、回答失效与执行交接。", status: "pending" }] };
  let phase: "idle" | "question" | "ready" | "implemented" = "idle";
  const created: Record<string, unknown>[] = [];
  const submitted: Record<string, unknown>[] = [];
  const implementRequests: Record<string, unknown>[] = [];
  const outcome = (id: string) => ({ schema_version: "1.0", run_id: id, goal_outcome: "answered", requirements: [],
    verification_results: [], evidence_ids: [], unverified_items: ["仅完成计划，尚未实施"] });
  function snapshot(id: string) {
    const child = id === "child";
    const ready = child || phase === "ready" || phase === "implemented";
    return { id, session_id: 11, status: ready ? "completed" : "waiting_input", collaboration_mode: child ? "default" : "plan",
      state_version: ready ? 8 : 2, checkpoint_id: "cp", last_event_sequence: ready ? 5 : 2,
      output: ready ? child ? "实施任务已接收。" : "实施计划（尚未执行）\n\n先核对现状，再完善交互与验证。" : null,
      permission_mode: "confirm", pending_input: ready ? null : input, plan: ready ? plan : null,
      run_outcome: ready ? outcome(id) : undefined, verification_state: ready ? "passed" : "pending",
      tool_call_count: 1, input_tokens: 20, output_tokens: 20, cached_tokens: 0, cost_usd: null,
      provider: "test", model: "fixture", error_code: null, error_message: null, cancel_requested_at: null,
      active_in_process: !ready, started_at: stamp, completed_at: ready ? stamp : null,
      created_at: stamp, updated_at: stamp, steps: [], artifacts: [] };
  }
  await page.route("**://127.0.0.1:8000/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/capabilities") return route.fulfill({ json: { chat_execution_mode: "agent_runtime",
      coding_agent_ui_enabled: true, agent_runs_api_enabled: true, project_bound_runs_enabled: true,
      coding_planning_contract_version: "1.0", coding_recovery_contract_version: "1.0" } });
    if (path === "/projects") return route.fulfill({ json: [{ id: 1, name: "规划器演示项目", status: "active", updated_at: stamp }] });
    if (path === "/projects/1/workspaces") return route.fulfill({ json: [{ id: 101, project_id: 1, kind: "root", status: "active", branch_name: "main" }] });
    if (path === "/sessions") return route.fulfill({ json: url.searchParams.get("kind") === "coding" ? [{ id: 11, title: "完善规划器模块", project_id: 1,
      workspace_id: 101, kind: "coding", updated_at: stamp, last_run_id: phase === "idle" ? null : phase === "implemented" ? "child" : "plan" }] : [] });
    if (path === "/agent-model-profiles") return route.fulfill({ json: [{ id: "fixture", provider: "openai", model_name: "test-model", display_name: "测试模型",
      native_tool_calls: true, enabled: true, is_default: true, reasoning_efforts: [] }] });
    if (path === "/agent-runs" && request.method() === "POST") {
      created.push(request.postDataJSON()); phase = "question";
      return route.fulfill({ status: 201, json: snapshot("plan") });
    }
    if (path === "/agent-runs/plan/answer") {
      submitted.push(request.postDataJSON()); phase = "ready";
      return route.fulfill({ status: 202, json: { status: "applied", kind: "answer", result_run_id: "plan" } });
    }
    if (path === "/agent-runs/plan/implement-plan") {
      implementRequests.push(request.postDataJSON()); phase = "implemented";
      return route.fulfill({ status: 202, json: { status: "applied", kind: "implement", result_run_id: "child" } });
    }
    const runId = path.split("/")[2];
    if (path === `/agent-runs/${runId}`) return route.fulfill({ json: snapshot(runId) });
    if (path.includes("/events")) {
      const after = Number(url.searchParams.get("after_sequence") ?? 0);
      const ready = phase === "ready" || phase === "implemented";
      const frames = [{ sequence: 1, type: "run.started", payload: { collaboration_mode: runId === "child" ? "default" : "plan" } },
        { sequence: 2, type: "input.requested", payload: { pending_input: input } },
        ...(ready ? [{ sequence: 3, type: "input.resolved", payload: { input_id: "q-1" } },
          { sequence: 4, type: "plan.created", payload: { ...plan, plan_version: 1 } },
          { sequence: 5, type: "run.completed", payload: { output: snapshot(runId).output, run_outcome: outcome(runId) } }] : [])];
      const current = frames.filter(frame => frame.sequence > after);
      if (path.endsWith("/stream")) return route.fulfill({ contentType: "text/event-stream", body: current.map(frame => `data: ${JSON.stringify(frame)}\n\n`).join("") });
      return route.fulfill({ json: { items: current, last_sequence: ready ? 5 : 2 } });
    }
    if (path.endsWith("/messages") || path.endsWith("/approvals") || path.endsWith("/executions")) return route.fulfill({ json: [] });
    return route.fulfill({ json: {} });
  });
  await page.goto("/?coding=1");
  await page.getByTestId("coding-thread-11").click();
  await page.getByTestId("coding-composer-input").fill("/plan 完善规划器模块");
  await page.getByTestId("coding-composer-send").click();
  await expect(page.getByTestId("planning-interaction")).toBeVisible();
  expect(created[0]).toMatchObject({ collaboration_mode: "plan", message: "完善规划器模块" });
  await expect(page.getByTestId("planning-answer")).toBeDisabled();
  await page.reload();
  await page.getByTestId("coding-thread-11").click();
  await expect(page.getByTestId("planning-interaction")).toBeVisible();
  await page.getByRole("button", { name: "当前模块 先完善规划流程" }).click();
  expect((await page.getByRole("button", { name: "当前模块 先完善规划流程" }).boundingBox())?.height).toBeGreaterThanOrEqual(56);
  await page.screenshot({ path: testInfo.outputPath("planning-question.png") });
  await page.setViewportSize({ width: 640, height: 820 });
  await expect(page.getByTestId("planning-answer")).toBeInViewport();
  await page.getByTestId("planning-answer").click();
  await expect(page.getByTestId("planning-implement")).toBeVisible();
  expect(submitted[0]).toMatchObject({ input_id: "q-1", answers: { scope: "当前模块" }, expected_state_version: 2 });
  await page.getByText("查看实施步骤（2 项）").click();
  await expect(page.getByTestId("planning-implement")).toBeInViewport();
  await page.screenshot({ path: testInfo.outputPath("planning-ready-narrow.png") });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByTestId("planning-implement").click();
  await expect(page.getByText("实施任务已接收。", { exact: true }).first()).toBeVisible();
  expect(implementRequests).toHaveLength(1);
  expect(implementRequests[0]).toMatchObject({ expected_plan_version: 1, expected_state_version: 8, checkpoint_id: "cp" });
});
