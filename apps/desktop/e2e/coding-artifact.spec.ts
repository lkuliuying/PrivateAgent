import { test, expect, type Page } from "@playwright/test";

/**
 * v0.8.0 W3：输入器、审批影响范围与 Artifact E2E
 * 覆盖 W0 矩阵第 11（PatchSet 预览/审批 diff）/12（命令输出与 parsed 测试摘要）/
 * 13·17·19（验证中、冲突、partial_unknown 预览态）+ CodingComposer 契约
 * （权限/模型/推理进入 run 创建体、@ 上下文发现、/ 命令模板）。
 */

const GREEN_HEALTH = {
  api: true,
  ollama: { ok: true, models: [] },
  mysql: { ok: true },
  chroma: { ok: true },
};

const RUN_ID = "run-w3-1";

const APPROVAL_DIFF = [
  "@@ -12,7 +12,9 @@",
  " export function useSidebar() {",
  "-  const open = ref(false);",
  "+  const open = ref(false);",
  '+  const overlay = useMediaQuery("(max-width: 1279px)");',
  "   return { open };",
].join("\n");

interface Frame {
  sequence: number;
  type: string;
  payload: Record<string, unknown>;
}

function sse(frames: Frame[]): { contentType: string; body: string } {
  return {
    contentType: "text/event-stream; charset=utf-8",
    body: frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join("") + ": heartbeat\n\n",
  };
}

function baseFrames(): Frame[] {
  return [
    { sequence: 1, type: "run.started", payload: { max_steps: 12, max_tool_calls: 8, max_wall_time_seconds: 120 } },
    { sequence: 2, type: "context.prepared", payload: { estimated_tokens: 3000, truncated: false } },
    { sequence: 3, type: "model.started", payload: { ordinal: 1, kind: "model", name: "model" } },
    { sequence: 4, type: "model.completed", payload: { finish_reason: "tool_calls", tool_call_count: 1, input_tokens: 3000, output_tokens: 90, cached_tokens: 0, cost_usd: null, provider: "ollama", model: "qwen3-coder", request_id: "r1", latency_ms: 1100 } },
  ];
}

function approvalWaitFrames(): Frame[] {
  return [
    ...baseFrames(),
    { sequence: 5, type: "tool.requested", payload: { ordinal: 1, kind: "tool", tool_call_id: "tc-write", name: "apply_patch_to_workspace" } },
    { sequence: 6, type: "tool.approval_required", payload: { tool_call_id: "tc-write", name: "apply_patch_to_workspace", approval_id: "ap-w3", tool_call_count: 1 } },
    { sequence: 7, type: "patch_set.preview_created", payload: { patch_set_id: "ps-w3", preview_version: 1, file_count: 1, truncated: false } },
  ];
}

function commandFrames(): Frame[] {
  return [
    ...baseFrames(),
    { sequence: 5, type: "tool.requested", payload: { ordinal: 1, kind: "tool", tool_call_id: "tc-cmd", name: "run_whitelisted_command" } },
    { sequence: 6, type: "tool.started", payload: { tool_call_id: "tc-cmd", name: "run_whitelisted_command" } },
    { sequence: 7, type: "tool.completed", payload: { tool_call_id: "tc-cmd", name: "run_whitelisted_command" } },
    { sequence: 8, type: "output.validation_passed", payload: { verifier: "default", attempt: 1, retry_count: 0, max_retries: 1, code: "ok", message: "校验通过" } },
    { sequence: 9, type: "run.completed", payload: { output: "命令已执行，测试全部通过。", error: null, error_code: null, tool_call_count: 1, input_tokens: 5000, output_tokens: 300, cached_tokens: 0, cost_usd: null } },
    { sequence: 10, type: "run.terminal", payload: { status: "completed" } },
  ];
}

function snapshot(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    id: RUN_ID,
    session_id: 11,
    status: "running",
    provider: null,
    model: null,
    last_event_sequence: 0,
    tool_call_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    cached_tokens: 0,
    cost_usd: null,
    output: null,
    error_code: null,
    error_message: null,
    cancel_requested_at: null,
    started_at: null,
    completed_at: null,
    created_at: "2026-08-22T00:00:00Z",
    updated_at: "2026-08-22T00:00:00Z",
    active_in_process: true,
    steps: [],
    project_id: 1,
    workspace_id: 101,
    base_head_sha: null,
    base_branch_name: "main",
    base_git_dirty: false,
    model_profile_id: null,
    reasoning_effort: null,
    permission_mode: null,
    plan: null,
    artifacts: [],
    ...overrides,
  };
}

interface W3Scenario {
  frames: () => Frame[];
  withApprovalDecision?: boolean;
}

function mockW3(page: Page, scenario: W3Scenario) {
  const createdBodies: Record<string, unknown>[] = [];
  let approvalApproved: boolean | null = null;
  let deliveredMax = 0;
  let terminalStatus: string | null = null;
  let outputAfterSeq = -1;

  return {
    createdBodies,
    route: page.route("**://127.0.0.1:8000/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;

      if (path === "/capabilities") {
        await route.fulfill({ json: { chat_execution_mode: "legacy", legacy_tool_planner_enabled: true, agent_read_only_tools_enabled: true, rag_chat_runtime_enabled: false } });
        return;
      }
      if (path === "/health") {
        await route.fulfill({ json: GREEN_HEALTH });
        return;
      }
      if (path === "/projects" && request.method() === "GET") {
        await route.fulfill({
          json: [
            { id: 1, name: "PrivateAgent", root_path: "C:\\secret\\a", language: "python", framework: null, status: "active", last_scanned_at: null, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-22T00:00:00Z" },
          ],
        });
        return;
      }
      if (path === "/projects/1/workspaces") {
        await route.fulfill({
          json: [
            { id: 101, project_id: 1, kind: "root", root_path: "C:\\secret\\a", branch_name: "main", head_sha: "abcd1234", status: "active", last_used_at: null, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-22T00:00:00Z" },
          ],
        });
        return;
      }
      if (path === "/projects/1/search") {
        await route.fulfill({
          json: {
            results: [
              { rel_path: "src/features/coding/components/CodingSidebar.vue", name: "CodingSidebar.vue", language: "vue" },
              { rel_path: "src/features/coding/components/CodingHome.vue", name: "CodingHome.vue", language: "vue" },
            ],
            count: 2,
          },
        });
        return;
      }
      if (path === "/sessions" && request.method() === "GET") {
        if (url.searchParams.get("kind") === "coding") {
          await route.fulfill({
            json: [
              { id: 11, title: "修复窄屏侧栏遮挡问题", created_at: "2026-08-20T00:00:00Z", updated_at: "2026-08-22T00:00:00Z", project_id: 1, workspace_id: 101, kind: "coding", last_run_id: null, pinned_at: null, archived_at: null },
            ],
          });
        } else {
          await route.fulfill({ json: [] });
        }
        return;
      }
      if (path === "/agent-runs" && request.method() === "POST") {
        createdBodies.push(request.postDataJSON() as Record<string, unknown>);
        await route.fulfill({ status: 202, json: snapshot({ status: "running" }) });
        return;
      }
      if (path === `/agent-runs/${RUN_ID}` && request.method() === "GET") {
        await route.fulfill({ json: snapshot({ status: terminalStatus ?? "running", last_event_sequence: deliveredMax }) });
        return;
      }
      if (path === `/agent-runs/${RUN_ID}/approvals` && request.method() === "GET") {
        await route.fulfill({
          json: [
            {
              id: "ap-w3",
              run_id: RUN_ID,
              step_id: null,
              tool_call_id: "tc-write",
              tool_name: "apply_patch_to_workspace",
              tool_version: "1.0.0",
              arguments_sha256: "f".repeat(64),
              risk_level: "confirm",
              required_capabilities: ["filesystem.write"],
              status: approvalApproved === null ? "pending" : approvalApproved ? "consumed" : "rejected",
              expires_at: "2026-08-23T00:00:00Z",
              decision_at: null,
              consumed_at: null,
              created_at: "2026-08-22T00:09:00Z",
            },
          ],
        });
        return;
      }
      if (path.includes(`/agent-runs/${RUN_ID}/approvals/ap-w3/preview`)) {
        await route.fulfill({
          json: {
            tool_name: "apply_patch_to_workspace",
            previewable: true,
            rel_path: "src/features/coding/components/CodingSidebar.vue",
            creates_file: false,
            old_sha256: "1".repeat(64),
            new_sha256: "2".repeat(64),
            diff: APPROVAL_DIFF,
            truncated: false,
            reason: null,
          },
        });
        return;
      }
      if (path.includes(`/agent-runs/${RUN_ID}/approvals/ap-w3/approve`)) {
        approvalApproved = true;
        await route.fulfill({ status: 202, json: snapshot({ status: "running" }) });
        return;
      }
      if (path.includes(`/agent-runs/${RUN_ID}/approvals/ap-w3/reject`)) {
        approvalApproved = false;
        await route.fulfill({ status: 200, json: snapshot({ status: "cancelled" }) });
        return;
      }
      if (path === `/agent-runs/${RUN_ID}/executions` && request.method() === "GET") {
        await route.fulfill({
          json: [
            {
              id: "exec-cmd-1",
              tool_name: "run_whitelisted_command",
              tool_version: "1.0.0",
              status: "succeeded",
              error_code: null,
              error_message: null,
              output: {
                // 与后端 run_command 真实 output_json 字段对齐（args/cwd/returncode）；
                // 参数含凭据形态，验证呈现层脱敏（W6-R）
                args: ["pytest", "tests", "-q", "--token=sk-e2e-secret"],
                cwd: "F:/workspace/privateagent-demo",
                returncode: 0,
                succeeded: true,
                truncated: false,
                parsed: { parser: "pytest", summary: "12 passed in 3.42s", passed: 12, failed: 0, skipped: 0, errors: 0, failures: [], truncated: false },
              },
              created_at: "2026-08-22T00:10:00Z",
              completed_at: "2026-08-22T00:10:04Z",
            },
          ],
        });
        return;
      }
      if (path.includes(`/agent-runs/${RUN_ID}/executions/exec-cmd-1/output`)) {
        const after = Number(url.searchParams.get("after_seq") ?? "-1");
        const lines = [
          { seq: 1, kind: "stdout", text: "collected 12 items" },
          { seq: 2, kind: "stdout", text: "tests/test_sidebar.py ....... [ 58%]" },
          { seq: 3, kind: "stdout", text: "======== 12 passed in 3.42s ========" },
        ].filter((line) => line.seq > after);
        outputAfterSeq = lines.length ? lines[lines.length - 1].seq : after;
        await route.fulfill({ json: { lines, last_seq: outputAfterSeq, finished: true } });
        return;
      }
      if (path.startsWith(`/agent-runs/${RUN_ID}/events/stream`)) {
        const after = Number(url.searchParams.get("after_sequence") ?? "0");
        let frames: Frame[];
        if (after === 0) {
          frames = scenario.frames();
        } else if (scenario.withApprovalDecision && approvalApproved === null) {
          frames = [];
        } else if (scenario.withApprovalDecision && approvalApproved === true) {
          frames = [
            { sequence: 8, type: "tool.approval_resolved", payload: { tool_call_id: "tc-write", name: "apply_patch_to_workspace", approval_id: "ap-w3" } },
            { sequence: 9, type: "tool.completed", payload: { tool_call_id: "tc-write", name: "apply_patch_to_workspace" } },
            { sequence: 10, type: "run.completed", payload: { output: "写入完成并验证通过。", error: null, error_code: null, tool_call_count: 1, input_tokens: 4000, output_tokens: 220, cached_tokens: 0, cost_usd: null } },
            { sequence: 11, type: "run.terminal", payload: { status: "completed" } },
          ].filter((frame) => frame.sequence > after);
        } else {
          frames = scenario.frames().filter((frame) => frame.sequence > after);
        }
        for (const frame of frames) {
          deliveredMax = Math.max(deliveredMax, frame.sequence);
          if (frame.type === "run.terminal") terminalStatus = String(frame.payload.status ?? "");
        }
        await route.fulfill(sse(frames));
        return;
      }
      if (path === `/agent-runs/${RUN_ID}/events` && request.method() === "GET") {
        await route.fulfill({ json: { items: [], last_sequence: deliveredMax } });
        return;
      }
      if (path === "/agent-model-profiles") {
        await route.fulfill({
          json: [
            { id: "local-coder", provider: "ollama", display_name: "Qwen3 Coder 30B", is_local: true, native_tool_calls: true, supports_streaming: true, supports_structured_output: true, supports_vision: false, context_tokens: 131072, reasoning_efforts: ["low", "medium", "high"], usage_reporting: true, enabled: true, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z" },
          ],
        });
        return;
      }
      if (path === "/settings") {
        await route.fulfill({ json: { model: "qwen3-coder" } });
        return;
      }
      await route.fulfill({ json: {} });
    }),
  };
}

async function openThread(page: Page) {
  await page.goto("/?coding=1");
  await expect(page.getByTestId("coding-thread-11")).toBeVisible({ timeout: 10000 });
  await page.getByTestId("coding-thread-11").click();
  await expect(page.getByTestId("coding-composer-input")).toBeVisible();
}

test.describe("v0.8.0 W3 输入器、审批影响范围与 Artifact", () => {
  test("审批显示完整影响范围：预览 diff 自动加载并可展开（矩阵 11）", async ({ page }) => {
    await mockW3(page, { frames: approvalWaitFrames, withApprovalDecision: true }).route;
    await openThread(page);
    await page.getByTestId("coding-composer-input").fill("调整抽屉断点");
    await page.getByTestId("coding-composer-send").click();

    await expect(page.getByTestId("approval-card")).toBeVisible({ timeout: 15000 });
    // 影响范围预览自动加载（不需要用户操作即看到 diff 摘要）
    const diffToggle = page.getByTestId("diff-artifact-toggle");
    await expect(diffToggle).toBeVisible({ timeout: 10000 });
    await expect(diffToggle).toContainText("CodingSidebar.vue");
    await expect(diffToggle).toContainText("+2");
    await diffToggle.click();
    await expect(page.getByTestId("diff-artifact-body")).toContainText("+  const overlay");
    // 批准后完成
    await page.getByTestId("approval-approve-ap-w3").click();
    await expect(page.getByTestId("thread-run-status")).toHaveText(/已完成/, { timeout: 20000 });
  });

  test("命令输出与测试报告：脱敏命令/退出码/耗时 + parsed 摘要 + 按需展开输出行（矩阵 12，W6-R 增强）", async ({ page }) => {
    await mockW3(page, { frames: commandFrames }).route;
    await openThread(page);
    await page.getByTestId("coding-composer-input").fill("运行测试");
    await page.getByTestId("coding-composer-send").click();

    // W6-R：命令卡默认呈现脱敏命令、工作目录范围、退出码与耗时（不阻塞主区）
    await expect(page.getByTestId("command-line")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("command-line")).toContainText("pytest tests -q --token=[REDACTED]");
    await expect(page.getByTestId("command-line")).not.toContainText("sk-e2e-secret");
    await expect(page.getByTestId("command-cwd")).toContainText("工作目录");
    await expect(page.getByTestId("command-exit-code")).toContainText("退出码 0");
    await expect(page.getByTestId("command-duration")).toBeVisible();

    // parsed 摘要随执行结果出现；输出默认折叠，按需展开（长输出不拖垮页面）
    await expect(page.getByTestId("command-parsed")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("command-parsed")).toContainText("12 passed in 3.42s");
    await page.getByTestId("command-output-load").click();
    // 终态卡随后出现并自动跟随到底部；展开输出用 DOM 事件（避免跟随滚动的命中遮挡）
    await page.getByTestId("command-output-toggle").scrollIntoViewIfNeeded();
    await page.getByTestId("command-output-toggle").dispatchEvent("click");
    await expect(page.getByTestId("command-output-body")).toContainText("12 passed in 3.42s");
    await expect(page.getByTestId("terminal-output")).toContainText("命令已执行", { timeout: 15000 });
  });

  test("CodingComposer 契约：权限/模型/推理进入 run 创建体；@ 发现与 / 模板", async ({ page }) => {
    const mock = mockW3(page, { frames: commandFrames });
    await mock.route;
    await openThread(page);

    // / 命令模板
    await page.getByTestId("coding-composer-input").fill("/");
    await page.getByTestId("composer-slash-fix-test").click();
    await expect(page.getByTestId("coding-composer-input")).toHaveValue(/失败的测试/);

    // @ 文件发现（chip 附入消息）
    const input = page.getByTestId("coding-composer-input");
    await input.fill("参考 @Cod");
    await expect(page.getByTestId("composer-at-pop")).toBeVisible({ timeout: 5000 });
    await page.getByTestId("composer-at-item-0").click();
    await expect(page.getByTestId("composer-chips")).toContainText("CodingSidebar.vue");

    // 权限/模型/推理选择
    await page.getByTestId("composer-permission").selectOption("confirm");
    await page.getByTestId("composer-model").selectOption("local-coder");
    await page.getByTestId("composer-effort").selectOption("high");
    await page.getByTestId("coding-composer-send").click();

    expect(mock.createdBodies[0]).toMatchObject({
      session_id: 11,
      project_id: 1,
      workspace_id: 101,
      permission_mode: "confirm",
      model_profile_id: "local-coder",
      reasoning_effort: "high",
    });
    expect(String((mock.createdBodies[0] as { message: string }).message)).toContain(
      "@src/features/coding/components/CodingSidebar.vue"
    );
    await expect(page.getByTestId("command-parsed")).toBeVisible({ timeout: 15000 });
  });

  test("预览夹具五态：验证中/冲突/partial_unknown/补丁预览/命令输出（矩阵 13/17/19/11/12 L2）", async ({ page }) => {
    await page.route("**://127.0.0.1:8000/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/health") {
        await route.fulfill({ json: GREEN_HEALTH });
        return;
      }
      if (path === "/capabilities") {
        await route.fulfill({ json: {} });
        return;
      }
      if (path === "/projects") {
        await route.fulfill({
          json: [{ id: 1, name: "PrivateAgent", root_path: "C:\\s", language: null, framework: null, status: "active", last_scanned_at: null, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-22T00:00:00Z" }],
        });
        return;
      }
      if (path === "/projects/1/workspaces") {
        await route.fulfill({
          json: [{ id: 101, project_id: 1, kind: "root", root_path: "C:\\s", branch_name: "main", head_sha: null, status: "active", last_used_at: null, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-22T00:00:00Z" }],
        });
        return;
      }
      if (path === "/sessions" && new URL(route.request().url()).searchParams.get("kind") === "coding") {
        await route.fulfill({
          json: [{ id: 11, title: "修复窄屏侧栏遮挡问题", created_at: "2026-08-20T00:00:00Z", updated_at: "2026-08-22T00:00:00Z", project_id: 1, workspace_id: 101, kind: "coding", last_run_id: null, pinned_at: null, archived_at: null }],
        });
        return;
      }
      await route.fulfill({ json: [] });
    });

    await page.goto("/?coding=1&coding-run-preview=verification");
    await expect(page.getByTestId("coding-thread-11")).toBeVisible({ timeout: 10000 });
    await page.getByTestId("coding-thread-11").click();
    await expect(page.getByTestId("transcript-verification")).toContainText("进行中");

    await page.goto("/?coding=1&coding-run-preview=conflict");
    await page.getByTestId("coding-thread-11").click();
    await expect(page.getByTestId("transcript-patch-set")).toContainText("应用失败");
    await expect(page.getByTestId("terminal-summary")).toContainText("patchset_conflict");

    await page.goto("/?coding=1&coding-run-preview=partial-unknown");
    await page.getByTestId("coding-thread-11").click();
    await expect(page.getByTestId("transcript-patch-set")).toContainText("人工处置");

    await page.goto("/?coding=1&coding-run-preview=patch-preview");
    await page.getByTestId("coding-thread-11").click();
    await expect(page.getByTestId("approval-card")).toBeVisible();
    await expect(page.getByTestId("diff-artifact-toggle")).toContainText("CodingSidebar.vue");

    await page.goto("/?coding=1&coding-run-preview=command-output");
    await page.getByTestId("coding-thread-11").click();
    await expect(page.getByTestId("command-parsed")).toContainText("12 passed");
  });

  test("ContextDrawer：Files/Context/Sources/Artifacts 事实面板", async ({ page }) => {
    await mockW3(page, { frames: approvalWaitFrames, withApprovalDecision: true }).route;
    await openThread(page);
    await page.getByTestId("composer-permission").selectOption("confirm");
    await page.getByTestId("coding-composer-input").fill("调整断点");
    await page.getByTestId("coding-composer-send").click();
    await expect(page.getByTestId("diff-artifact-toggle")).toBeVisible({ timeout: 15000 });

    await page.getByTestId("thread-context-toggle").click();
    await expect(page.getByTestId("context-drawer")).toBeVisible();
    await expect(page.getByTestId("context-pane-files")).toContainText("CodingSidebar.vue");
    await page.getByTestId("context-tab-context").click();
    await expect(page.getByTestId("context-pane-context")).toContainText("写入需确认");
    await page.getByTestId("context-tab-sources").click();
    await expect(page.getByTestId("context-pane-sources")).toContainText("不使用 RAG 来源");
  });
});
