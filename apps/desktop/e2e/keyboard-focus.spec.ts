import { test, expect, type Page } from "@playwright/test";

/**
 * v0.5.0 rc.2：键盘深度焦点检查（验收修复——禁止条件跳过）
 *
 * 全部通过真实组件与真实 SSE/API 流渲染后断言：
 * - 审批卡：SSE 播报 approval → 真实渲染 → 按钮键盘可达并触发审批；
 * - Diff 弹窗：executions 结果渲染 ContextRail 变更摘要 → 打开 Diff →
 *   Esc 关闭 → 焦点恢复；
 * - SQL 表格：executions 输出渲染真实结果表格（含行数/截断标记）；
 * - 命令长输出：真实命令输出组件渲染 5000 行不卡死且可交互；
 * - 配置页：HTTP/SQL profile 表单键盘 Tab 遍历。
 */

const GREEN_HEALTH = { api: true, ollama: { ok: true }, mysql: { ok: true }, chroma: { ok: true } };

function mockApi(page: Page, sseMode: "pending" | "approved" = "pending") {
  const approvalStatus = sseMode === "approved" ? "approved" : "pending";
  return page.route("**://127.0.0.1:8000/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/capabilities") {
      await route.fulfill({
        json: {
          chat_execution_mode: "agent_runtime",
          legacy_tool_planner_enabled: false,
          agent_read_only_tools_enabled: true,
          rag_chat_runtime_enabled: false,
          patch_workflow_enabled: true,
          command_workflow_enabled: true,
          http_workflow_enabled: true,
          sql_readonly_workflow_enabled: true,
        },
      });
      return;
    }
    if (path === "/sessions") {
      await route.fulfill({
        json: [
          {
            id: 1,
            title: "键盘检查会话",
            created_at: "2026-08-09T00:00:00Z",
            updated_at: "2026-08-09T01:00:00Z",
          },
        ],
      });
      return;
    }
    if (path.includes("/messages")) {
      await route.fulfill({ json: [] });
      return;
    }
    if (path.includes("/pending-approvals")) {
      await route.fulfill({ json: [] });
      return;
    }
    if (path.includes("/agent-runs") && path.includes("/executions") && path.includes("/output")) {
      await route.fulfill({ json: { lines: [], last_seq: 0, finished: true } });
      return;
    }
    if (path.includes("/agent-runs") && path.includes("/executions")) {
      await route.fulfill({
        json: [
          {
            id: "exec-apply",
            tool_name: "apply_patch_to_workspace",
            tool_version: "1.0.0",
            status: "succeeded",
            error_code: null,
            error_message: null,
            output: {
              rel_path: "src/main.py",
              verified: true,
              diff: "--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-old\n+new",
            },
            created_at: "2026-08-09T00:00:00Z",
            completed_at: "2026-08-09T00:00:05Z",
          },
          {
            id: "exec-sql",
            tool_name: "query_readonly_sql",
            tool_version: "1.0.0",
            status: "succeeded",
            error_code: null,
            error_message: null,
            output: {
              columns: ["id", "title"],
              rows: [[1, "alpha"], [2, "beta"], [3, "gamma"]],
              row_count: 3,
              truncated: false,
              read_only_confirmed: true,
            },
            created_at: "2026-08-09T00:00:00Z",
            completed_at: "2026-08-09T00:00:05Z",
          },
        ],
      });
      return;
    }
    if (path === "/files/trusted") {
      await route.fulfill({
        json: [
          { id: 1, path: "src/main.py", kind: "file", granted_at: "2026-08-09T00:00:00Z" },
        ],
      });
      return;
    }
    if (path === "/settings") {
      // v0.9.0 H1-B（§5.6）：模型未配置时执行按钮禁用；声明已配置模型
      await route.fulfill({
        json: {
          provider_type: "ollama",
          llm_model: "qwen2.5:14b-instruct-q4_K_M",
          remote_provider_enabled: false,
          llm_context_length: 32768,
        },
      });
      return;
    }
    if (path === "/chat/stream") {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream; charset=utf-8",
        body:
          'data: {"type":"run","run_id":"run-kb"}\n\n' +
          `data: {"type":"approval","approval":{"id":"ap-1","run_id":"run-kb","tool_call_id":"tc-1","tool_name":"apply_patch_to_workspace","tool_version":"1.0.0","arguments_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","risk_level":"confirm","required_capabilities":["filesystem.write"],"status":"${approvalStatus}","expires_at":"2026-08-10T00:00:00Z","created_at":"2026-08-09T00:00:00Z"}}\n\n` +
          `data: {"type":"approval","approval":{"id":"ap-2","run_id":"run-kb","tool_call_id":"tc-2","tool_name":"query_readonly_sql","tool_version":"1.0.0","arguments_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","risk_level":"confirm","required_capabilities":["database.query"],"status":"${approvalStatus}","expires_at":"2026-08-10T00:00:00Z","created_at":"2026-08-09T00:00:00Z"}}\n\n` +
          `data: {"type":"approval","approval":{"id":"ap-3","run_id":"run-kb","tool_call_id":"tc-3","tool_name":"run_whitelisted_command","tool_version":"1.0.0","arguments_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","risk_level":"confirm","required_capabilities":["process.execute"],"status":"${approvalStatus}","expires_at":"2026-08-10T00:00:00Z","created_at":"2026-08-09T00:00:00Z"}}\n\n` +
          'data: {"type":"done","run_id":"run-kb","message_id":10,"content":"完成"}\n\n',
      });
      return;
    }
    if (path === "/health") {
      await route.fulfill({ json: GREEN_HEALTH });
      return;
    }
    await route.fulfill({ json: {} });
  });
}

test.describe("v0.5.0 rc.2 键盘深度焦点", () => {
  test("审批卡经真实 SSE 渲染，按钮键盘可达且可触发审批", async ({ page }) => {
    let approveCalls = 0;
    await mockApi(page);
    await page.route("**://127.0.0.1:8000/agent-runs/run-kb/approvals/**/approve", async (route) => {
      approveCalls += 1;
      await route.fulfill({
        json: {
          id: "run-kb",
          session_id: null,
          trace_id: "t",
          status: "waiting_approval",
          provider: null,
          model: null,
          last_event_sequence: 3,
          tool_call_count: 1,
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
          created_at: "2026-08-09T00:00:00Z",
          updated_at: "2026-08-09T00:00:00Z",
          active_in_process: false,
          steps: [],
        },
      });
    });
    await page.goto("/?ui=v2&coding=0");
    await expect(page.getByTestId("nav-chat")).toBeVisible();
    await page.getByRole("button", { name: "键盘检查会话" }).first().click();
    await page.getByTestId("task-composer-input").fill("请修改文件");
    await page.getByTestId("task-composer-submit").click();

    const approveButton = page.getByRole("button", { name: "批准执行" }).first();
    await expect(approveButton).toBeVisible({ timeout: 10_000 });
    await approveButton.focus();
    await expect(approveButton).toBeFocused();
    await page.keyboard.press("Enter");
    await expect.poll(() => approveCalls).toBe(1);
  });

  test("SQL 查询结果经真实 executions 渲染为表格且可键盘访问", async ({ page }) => {
    await mockApi(page, "approved");
    await page.goto("/?ui=v2&coding=0");
    await expect(page.getByTestId("nav-chat")).toBeVisible();
    await page.getByRole("button", { name: "键盘检查会话" }).first().click();
    await page.getByTestId("task-composer-input").fill("查询数据库");
    await page.getByTestId("task-composer-submit").click();

    // 审批卡展示 SQL 结果表格（executions mock）
    const table = page.locator("[data-testid='sql-result-table']");
    await expect(table).toBeVisible({ timeout: 10_000 });
    await expect(table.locator("thead th")).toHaveCount(2);
    await expect(table.locator("tbody tr")).toHaveCount(3);
    await expect(table.locator("tbody tr").first().locator("td").first()).toHaveText("1");
    await expect(page.getByText("只读事务")).toBeVisible();
  });

  test("对话框 Esc 关闭后焦点回到触发按钮（W6-R3：上下文栏入口已移除，载体改为设置页对话框）", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockApi(page, "approved");
    await page.goto("/?ui=v2&coding=0");
    await expect(page.getByTestId("nav-chat")).toBeVisible();
    // W6-R3：Agent 页上下文栏/顶部控件已移除，PaDialog 焦点恢复契约改用仍活跃的载体验证（不允许跳过）
    await expect(page.getByTestId("session-context-toggle")).toHaveCount(0);
    await page.getByTestId("nav-settings").click();
    const diffTrigger = page.getByRole("button", { name: "新建连接" }).first();
    await expect(diffTrigger).toBeVisible({ timeout: 10_000 });
    await diffTrigger.focus();
    await diffTrigger.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("新建只读连接");
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    // 焦点必须回到触发按钮（PaDialog 卸载时恢复 previousFocus）
    await expect(diffTrigger).toBeFocused();
  });

  test("命令 5000 行输出经真实审批卡渲染且页面可交互", async ({ page }) => {
    const longLines = Array.from(
      { length: 5000 },
      (_, index) => `flood-line-${index}`
    ).join("\n");
    await mockApi(page, "approved");
    await page.route("**://127.0.0.1:8000/agent-runs/run-kb/executions/exec-cmd/output*", async (route) => {
      await route.fulfill({
        json: {
          lines: longLines.split("\n").map((text, index) => ({ seq: index, kind: "stdout", text })),
          last_seq: 4999,
          finished: true,
        },
      });
      return;
    });
    // executions 路由在 mockApi 中定义，这里补充 command execution
    await page.route("**://127.0.0.1:8000/agent-runs/run-kb/executions", async (route) => {
      await route.fulfill({
        json: [
          {
            id: "exec-cmd",
            tool_name: "run_whitelisted_command",
            tool_version: "1.0.0",
            status: "succeeded",
            error_code: null,
            error_message: null,
            output: {
              args: ["python", "-c", "flood"],
              cwd: "F:\\project",
              returncode: 0,
              succeeded: true,
              processes_remaining: 0,
            },
            created_at: "2026-08-09T00:00:00Z",
            completed_at: "2026-08-09T00:00:05Z",
          },
        ],
      });
    });
    await page.goto("/?ui=v2&coding=0");
    await expect(page.getByTestId("nav-chat")).toBeVisible();
    await page.getByRole("button", { name: "键盘检查会话" }).first().click();
    await page.getByTestId("task-composer-input").fill("运行长命令");
    await page.getByTestId("task-composer-submit").click();

    // 命令输出组件（ApprovalCardV2 command-output）真实渲染长文本
    const output = page.getByTestId("command-output");
    await expect(output).toBeVisible({ timeout: 10_000 });
    const text = await output.innerText();
    expect(text.length).toBeGreaterThan(50_000);
    expect(text).toContain("flood-line-4999");
    // 渲染后页面仍响应导航点击
    await page.getByTestId("nav-today").click();
    await expect(page.getByTestId("nav-today")).toBeVisible();
  });

  test("HTTP/SQL 配置面板真实 Tab 焦点顺序", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockApi(page);
    await page.route("**://127.0.0.1:8000/http-profiles*", async (route) => {
      await route.fulfill({ json: [] });
    });
    await page.goto("/?ui=v2&coding=0");
    await expect(page.getByTestId("nav-chat")).toBeVisible();

    // 打开设置页（v2 壳导航）
    const settingsNav = page.getByTestId("nav-settings");
    await settingsNav.click();
    await page.waitForTimeout(500);

    // 断言 HTTP 面板存在并打开新建表单
    await expect(page.getByRole("button", { name: "新建端点" })).toBeVisible();
    await page.getByRole("button", { name: "新建端点" }).click();
    const form = page.getByRole("dialog");
    await expect(form).toBeVisible();

    // 表单 Tab 顺序：名称 → Scheme → Host → Port → Path 前缀
    const nameInput = form.locator("input[placeholder='如 weather-api']");
    await nameInput.focus();
    await page.keyboard.press("Tab");
    const scheme = await page.evaluate(() => (document.activeElement as HTMLSelectElement)?.tagName);
    expect(scheme).toBe("SELECT");
    await page.keyboard.press("Tab");
    const hostTag = await page.evaluate(() => (document.activeElement as HTMLElement)?.tagName);
    expect(hostTag).toBe("INPUT");
    // Esc 关闭弹窗，焦点恢复
    await page.keyboard.press("Escape");
    await expect(form).not.toBeVisible();
  });
});
