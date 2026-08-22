import { test, expect, type Page } from "@playwright/test";

/**
 * 0.4.0 D2：AppShell v2（ui_v2 开关）E2E
 * 覆盖：新壳分组导航可用、视图切换/返回/前进、上下文栏、快捷键、ui_v1 回退。
 */

const GREEN_HEALTH = {
  api: true,
  ollama: { ok: true, models: [] },
  mysql: { ok: true },
  chroma: { ok: true },
};

function mockApi(page: Page) {
  return page.route("**://127.0.0.1:8000/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/capabilities") {
      await route.fulfill({
        json: {
          chat_execution_mode: "legacy",
          legacy_tool_planner_enabled: true,
          agent_read_only_tools_enabled: true,
          rag_chat_runtime_enabled: false,
        },
      });
      return;
    }
    if (path === "/sessions") {
      await route.fulfill({
        json: [
          {
            id: 1,
            title: "v2 壳测试会话",
            created_at: "2026-08-08T00:00:00Z",
            updated_at: "2026-08-08T01:00:00Z",
          },
        ],
      });
      return;
    }
    if (path.includes("/messages")) {
      await route.fulfill({ json: [] });
      return;
    }
    if (path === "/health") {
      await route.fulfill({ json: GREEN_HEALTH });
      return;
    }
    if (path === "/settings") {
      await route.fulfill({
        json: { model: "qwen3:4b", embedding_model: "nomic-embed-text", provider: "ollama" },
      });
      return;
    }
    if (path === "/tool-calls" || path.includes("/tool-calls")) {
      await route.fulfill({ json: [] });
      return;
    }
    if (path === "/agent-approvals" || path.includes("/agent-approvals")) {
      await route.fulfill({ json: [] });
      return;
    }
    await route.fulfill({ json: {} });
  });
}

async function openApp(page: Page, ui = "v2") {
  await mockApi(page);
  await page.goto(`/?ui=${ui}`);
  await expect(page.getByTestId("nav-chat")).toBeVisible({ timeout: 10000 });
}

test.describe("0.4.0 AppShell v2", () => {
  test("ui=v2 新壳渲染分组导航（日常/执行/工作/知识/连接/系统）", async ({ page }) => {
    await openApp(page, "v2");
    for (const key of ["today", "chat", "projects", "kb", "integrations", "settings", "diagnostics", "backup"]) {
      await expect(page.getByTestId(`nav-${key}`)).toBeVisible();
    }
    await expect(page.getByTestId("nav-chat")).toHaveAttribute("aria-current", "page");
    await expect(page.getByRole("heading", { name: "v2 壳测试会话" })).toBeVisible();
  });

  test("视图切换与返回（Alt+←）", async ({ page }) => {
    await openApp(page, "v2");
    await page.getByTestId("nav-today").click();
    await expect(page.getByTestId("nav-today")).toHaveAttribute("aria-current", "page");
    await page.keyboard.press("Alt+ArrowLeft");
    await expect(page.getByTestId("nav-chat")).toHaveAttribute("aria-current", "page");
  });

  test("上下文入口已移除（W6-R3）：顶部无上下文按钮，上下文改由 Runtime 自动装配", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openApp(page, "v2");
    await page.getByTestId("nav-chat").click();
    // W6-R3：顶部上下文切换按钮与会话头部上下文按钮均已移除，不残留隐藏 DOM
    await expect(page.getByLabel("切换上下文栏")).toHaveCount(0);
    await expect(page.getByTestId("session-context-toggle")).toHaveCount(0);
    // 上下文改由底部用量模块反馈（真实事实或不可用态，不伪造）
    await expect(page.getByTestId("context-usage-meter")).toBeVisible();
  });

  test("Ctrl/Cmd+K 打开命令面板并包含注册表视图命令", async ({ page }) => {
    await openApp(page, "v2");
    await page.keyboard.press("Control+k");
    await expect(page.getByRole("dialog", { name: "命令面板" })).toBeVisible();
    await expect(page.getByText("打开知识库")).toBeVisible();
  });

  test("ui=v1 回退到兼容壳（legacy NavRail 可用）", async ({ page }) => {
    await openApp(page, "v1");
    await expect(page.getByTestId("nav-utilities-toggle")).toBeVisible();
    await page.getByTestId("nav-utilities-toggle").click();
    await expect(page.getByTestId("nav-today")).toBeVisible();
  });

  test("v2 Agent 流：发送→审批→批准→完成带 RAG 来源", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockApi(page);
    const sha = "a".repeat(64);
    let streamCount = 0;
    await page.route("**://127.0.0.1:8000/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path === "/capabilities") {
        await route.fulfill({
          json: {
            chat_execution_mode: "agent_runtime",
            legacy_tool_planner_enabled: false,
            agent_read_only_tools_enabled: true,
            rag_chat_runtime_enabled: true,
          },
        });
        return;
      }
      if (path === "/sessions") {
        await route.fulfill({
          json: [
            {
              id: 1,
              title: "v2 Agent 流测试",
              created_at: "2026-08-08T00:00:00Z",
              updated_at: "2026-08-08T01:00:00Z",
            },
          ],
        });
        return;
      }
      if (path.includes("/messages")) {
        await route.fulfill({ json: [] });
        return;
      }
      if (path === "/chat/stream") {
        streamCount += 1;
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream; charset=utf-8",
          body:
            'data: {"type":"run","run_id":"run-v2-1"}\n\n' +
            `data: {"type":"approval","approval":{"id":"ap-v2","run_id":"run-v2-1","tool_call_id":"tc-1","tool_name":"mcp.filesystem.write_file","tool_version":"1.0.0","arguments_sha256":"${sha}","risk_level":"confirm","required_capabilities":["fs.write"],"status":"pending","expires_at":"2026-08-09T00:00:00Z","created_at":"2026-08-08T00:00:00Z"}}\n\n` +
            'data: {"type":"done","run_id":"run-v2-1","message_id":10,"content":"正在等待确认"}\n\n',
        });
        return;
      }
      if (path.includes("/agent-runs/run-v2-1/approvals/ap-v2/approve")) {
        await route.fulfill({ json: {} });
        return;
      }
      if (path.includes("/chat/agent-runs/run-v2-1/stream")) {
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream; charset=utf-8",
          body:
            'data: {"type":"token","content":"已写入文件，任务完成。"}\n\n' +
            'data: {"type":"done","run_id":"run-v2-1","message_id":11,"content":"已写入文件，任务完成。","sources":[{"doc_name":"运维手册-备份章节.md","ordinal":3,"chunk_id":418,"heading":"每日备份","score":0.86,"matched_via":["dense"]}]}\n\n',
        });
        return;
      }
      if (path.includes("/pending-approvals") || path.includes("/agent-approvals")) {
        await route.fulfill({ json: [] });
        return;
      }
      if (path === "/health") {
        await route.fulfill({ json: GREEN_HEALTH });
        return;
      }
      if (path === "/settings") {
        await route.fulfill({ json: { model: "qwen3:4b" } });
        return;
      }
      await route.fulfill({ json: {} });
    });

    await page.goto("/?ui=v2");
    await expect(page.getByTestId("nav-chat")).toBeVisible();

    // 发送任务
    const input = page.getByTestId("task-composer-input");
    await input.fill("把笔记同步到知识库");
    await page.getByTestId("task-composer-submit").click();
    expect(streamCount).toBe(1);

    // 审批卡出现并批准（按钮在点击后随状态变化立即消失，用 dispatchEvent 避免 actionability 重试超时）
    await expect(page.getByText("授权请求").first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("mcp.filesystem.write_file").first()).toBeVisible();
    await page.getByRole("button", { name: /批准执行/ }).first().dispatchEvent("click");

    // 批准后 continuation 流式完成，带 RAG 来源
    await expect(page.getByText("已写入文件，任务完成。")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("运维手册-备份章节.md")).toBeVisible();
    // W6-R3：上下文栏入口已移除；RAG 来源在转录中可见（上方断言）
  });

  test("v2 停止：流式期间停止按钮立即反馈", async ({ page }) => {
    await mockApi(page);
    await page.route("**://127.0.0.1:8000/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path === "/capabilities") {
        await route.fulfill({
          json: {
            chat_execution_mode: "legacy",
            legacy_tool_planner_enabled: true,
            agent_read_only_tools_enabled: true,
            rag_chat_runtime_enabled: false,
          },
        });
        return;
      }
      if (path === "/sessions") {
        await route.fulfill({
          json: [
            {
              id: 1,
              title: "停止测试",
              created_at: "2026-08-08T00:00:00Z",
              updated_at: "2026-08-08T01:00:00Z",
            },
          ],
        });
        return;
      }
      if (path.includes("/messages")) {
        await route.fulfill({ json: [] });
        return;
      }
      if (path === "/tools/plan") {
        await route.fulfill({ json: { tool_call: null } });
        return;
      }
      if (path === "/chat/stream") {
        // 延迟返回，保持「运行中」窗口以验证停止按钮与即时反馈
        await new Promise((resolve) => setTimeout(resolve, 3000));
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream; charset=utf-8",
          body: 'data: {"type":"token","content":"正在生成"}\n\n',
        });
        return;
      }
      await route.fulfill({ json: {} });
    });

    await page.goto("/?ui=v2");
    await expect(page.getByTestId("nav-chat")).toBeVisible();
    const input = page.getByTestId("task-composer-input");
    await input.fill("生成一份草稿");
    await page.getByTestId("task-composer-submit").click();

    const stopBtn = page.getByTestId("task-composer-stop");
    await expect(stopBtn).toBeVisible({ timeout: 10000 });
    // 点击后按钮随流停止立即消失，用 dispatchEvent 验证即时视觉反馈
    await stopBtn.dispatchEvent("click");
    await expect(stopBtn).toContainText("正在停止");
  });
});
