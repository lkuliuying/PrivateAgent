// v0.8.0 W0：改造前 UI 基线截图采集（v2 Agent 工作台，dev 预览夹具）。
//
// 用法（在 apps/desktop 下）：
//   node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 1420 --strictPort &
//   node scripts/capture-ui-baseline.mjs [输出目录]
//
// 采集矩阵（W5 视觉基线复用同一脚本）：
//   - 分辨率基线：1280x720 / 1440x900 / 1920x1080（dsf=1）
//   - 缩放基线：1920x1080 @125%（dsf=1.25）、1440x900 @150%（dsf=1.5）
// 页面使用 ?workspace-preview=running 显式开发夹具（生产构建不进入该分支），
// 与 docs/releases/v0.8.0 W0 冻结文档中的状态矩阵对应（运行中 + 工具卡 + 审批等待）。
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const BASE_URL = process.env.PA_E2E_BASE_URL ?? "http://127.0.0.1:1420";
const TARGET = `${BASE_URL}/?workspace-preview=running`;
const OUT_DIR = resolve(
  process.argv[2] ?? "../../docs/releases/v0.8.0/assets/baseline",
);

const MATRIX = [
  { name: "v2-workbench-1280x720", width: 1280, height: 720, scale: 1 },
  { name: "v2-workbench-1440x900", width: 1440, height: 900, scale: 1 },
  { name: "v2-workbench-1920x1080", width: 1920, height: 1080, scale: 1 },
  { name: "v2-workbench-1920x1080@125", width: 1920, height: 1080, scale: 1.25 },
  { name: "v2-workbench-1440x900@150", width: 1440, height: 900, scale: 1.5 },
];

mkdirSync(OUT_DIR, { recursive: true });
const browser = await chromium.launch();
try {
  for (const item of MATRIX) {
    const context = await browser.newContext({
      viewport: { width: item.width, height: item.height },
      deviceScaleFactor: item.scale,
    });
    const page = await context.newPage();
    await page.goto(TARGET, { waitUntil: "networkidle" });
    // 等待入场过渡与流式光标稳定，避免捕获中间帧（design-qa 同一口径）
    await page.waitForTimeout(1800);
    const out = resolve(OUT_DIR, `${item.name}.png`);
    await page.screenshot({ path: out, fullPage: false });
    console.log(`[baseline] ${item.name} -> ${out}`);
    await context.close();
  }
} finally {
  await browser.close();
}
