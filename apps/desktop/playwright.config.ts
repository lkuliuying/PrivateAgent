import { defineConfig, devices } from "@playwright/test";

// 第八阶段 M1：Playwright E2E（浏览器模式，路由拦截模拟后端）。
// webServer 自动启动 Vite dev server（1420）。Tauri 桌面窗口级 E2E 见 docs/usage-guide。
export default defineConfig({
  testDir: "./e2e",
  snapshotPathTemplate:
    "{testDir}/visual-baselines/{platform}/{projectName}/{arg}{ext}",
  timeout: 60_000,
  expect: {
    timeout: 20_000,
    toHaveScreenshot: {
      animations: "disabled",
      caret: "hide",
      maxDiffPixelRatio: 0.001,
      scale: "css",
      stylePath: "./e2e/visual-stability.css",
      threshold: 0.2,
    },
  },
  fullyParallel: false,
  retries: 0,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 4173",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        deviceScaleFactor: 1,
        locale: "zh-CN",
        serviceWorkers: "block",
        timezoneId: "Asia/Shanghai",
      },
    },
  ],
});
