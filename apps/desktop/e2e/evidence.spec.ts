import { test, expect, type Page } from "@playwright/test";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

/**
 * 0.4.0 D6 视觉证据采集（docs/evidence/v0.4.0-alpha.1/）
 * 计划书要求：新壳 1280/1440/1920、Windows 125%/150% 缩放、UI Lab、回退壳截图。
 * 证据截图是采集产物（非断言基线），保存到仓库 docs/evidence/ 供检查点归档。
 */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const EVIDENCE_DIR = path.resolve(__dirname, "../../../docs/evidence/v0.4.0-alpha.1");

/**
 * 证据重生成开关：PA_EVIDENCE_REGEN=1 时才写入截图。
 * 常规 e2e（含 release-check）跳过本组，保证已提交证据不被运行时字节差异改写，
 * release-check 可绑定干净工作区。
 * 重生成命令：PA_EVIDENCE_REGEN=1 npx playwright test e2e/evidence.spec.ts
 */
const regen = process.env.PA_EVIDENCE_REGEN === "1";
if (!regen) {
  test.describe("0.4.0 视觉证据（跳过：未设置 PA_EVIDENCE_REGEN）", () => {
    test("证据重生成需显式开启", () => {
      // 占位：常规运行跳过证据采集，已提交 PNG 即绑定证据
    });
  });
} else {

const GREEN_HEALTH = {
  api: true,
  ollama: { ok: true, models: [] },
  mysql: { ok: true },
  chroma: { ok: true },
};

/** 固定浏览器时钟，保证证据截图字节稳定（相对时间/状态栏不随运行时刻漂移）。 */
const FIXED_NOW = new Date("2026-08-08T10:00:00.000Z");

async function freezeClock(page: Page) {
  await page.clock.install({ time: FIXED_NOW });
  await page.clock.setFixedTime(FIXED_NOW);
}

function mockApi(page: Page, title = "证据采集会话") {
  return page.route("**://127.0.0.1:8000/**", async (route) => {
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
            title,
            created_at: "2026-08-08T00:00:00Z",
            updated_at: "2026-08-08T01:00:00Z",
          },
        ],
      });
      return;
    }
    if (path.includes("/messages")) {
      await route.fulfill({
        json: [
          {
            id: 1,
            session_id: 1,
            role: "user",
            content: "重构个人 Agent 工作台，保留现有本地接口与业务能力。",
            created_at: "2026-08-08T00:01:00Z",
          },
          {
            id: 2,
            session_id: 1,
            role: "assistant",
            content:
              "已完成项目结构检查。当前重点是三栏工作台、统一审批卡与执行状态呈现，计划已建立，正在执行第一步。",
            created_at: "2026-08-08T00:02:00Z",
          },
        ],
      });
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
    if (path.includes("/tool-calls") || path.includes("/pending-approvals") || path.includes("/activities")) {
      await route.fulfill({ json: [] });
      return;
    }
    await route.fulfill({ json: {} });
  });
}

async function openV2(page: Page, width: number, height = 900) {
  await page.setViewportSize({ width, height });
  await freezeClock(page);
  await mockApi(page);
  await page.goto("/?ui=v2");
  await expect(page.getByTestId("nav-chat")).toBeVisible();
  await expect(page.getByRole("heading", { name: "证据采集会话" })).toBeVisible();
  // 等待异步请求（消息重水合/授权路径/活动轮询）收敛，避免截图落在渲染竞态中
  await page.waitForLoadState("networkidle");
}

/**
 * 证据截图：等待异步收敛 + 字体就绪 + 连续两次一致才落盘。
 * 首次栅格化/字体发现偶发差异被重试吸收，保证跨运行字节稳定。
 */
async function settleAndShot(
  page: Page,
  path: string,
  options: { scale?: "css" | "device" } = {}
) {
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready.then(() => true));
  await page.waitForTimeout(300);

  const tmpPath = path.replace(/\.png$/, "-tmp.png");
  const capture = () => page.screenshot({ path: tmpPath, ...options });
  const same = (a: Buffer, b: Buffer) =>
    a.length === b.length && a.equals(b);

  let last: Buffer | null = null;
  for (let attempt = 0; attempt < 4; attempt++) {
    const current = await capture();
    if (last && same(last, current)) {
      fs.writeFileSync(path, current);
      fs.rmSync(tmpPath, { force: true });
      return;
    }
    last = current;
    await page.waitForTimeout(400);
  }
  // 未能在 4 次内收敛：保存最后一次（后续人工复核）
  fs.renameSync(tmpPath, path);
}

test.describe("0.4.0 视觉证据", () => {
  // 证据采集固定布局与状态：reduced-motion 下 anime.js/CSS 动效全部跳过，
  // 截图不依赖动画帧，跨运行字节稳定。
  test.use({ reducedMotion: "reduce" });

  test("新壳 1280/1440/1920（Agent 工作区 + 上下文栏）", async ({ page }) => {
    await openV2(page, 1280);
    await settleAndShot(page, `${EVIDENCE_DIR}/v2-agent-1280.png`);

    await openV2(page, 1440);
    await settleAndShot(page, `${EVIDENCE_DIR}/v2-agent-1440.png`);

    await openV2(page, 1920);
    await settleAndShot(page, `${EVIDENCE_DIR}/v2-agent-1920.png`);
  });

  test("新壳今日视图 1440", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await freezeClock(page);
    await mockApi(page);
    await page.goto("/?ui=v2");
    await page.getByTestId("nav-today").click();
    await expect(page.getByTestId("nav-today")).toHaveAttribute("aria-current", "page");
    await settleAndShot(page, `${EVIDENCE_DIR}/v2-today-1440.png`);
  });

  test("UI Lab 1440", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await freezeClock(page);
    await page.goto("/?ui-lab=1");
    await expect(page.getByText("设计系统 2.0 · UI 状态展厅")).toBeVisible();
    await settleAndShot(page, `${EVIDENCE_DIR}/ui-lab-1440.png`);
  });

  test("ui=v1 回退壳 1440", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await freezeClock(page);
    await mockApi(page);
    await page.goto("/?ui=v1");
    await expect(page.getByTestId("nav-chat")).toBeVisible();
    await settleAndShot(page, `${EVIDENCE_DIR}/v1-legacy-shell-1440.png`);
  });
});

test.describe("0.4.0 视觉证据 · Windows 缩放 125%", () => {
  test.use({ deviceScaleFactor: 1.25, reducedMotion: "reduce" });
  test("新壳 1440 @125%", async ({ page }) => {
    await openV2(page, 1440);
    await settleAndShot(page, `${EVIDENCE_DIR}/v2-agent-1440-scale125.png`, {
      scale: "device",
    });
  });
});

test.describe("0.4.0 视觉证据 · Windows 缩放 150%", () => {
  test.use({ deviceScaleFactor: 1.5, reducedMotion: "reduce" });
  test("新壳 1440 @150%", async ({ page }) => {
    await openV2(page, 1440);
    await settleAndShot(page, `${EVIDENCE_DIR}/v2-agent-1440-scale150.png`, {
      scale: "device",
    });
  });
});
}
