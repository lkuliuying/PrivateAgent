import { defineConfig, devices } from "@playwright/test";

// 第八阶段 M1：Playwright E2E（浏览器模式，路由拦截模拟后端）。
// webServer 自动启动 Vite dev server（1420）。Tauri 桌面窗口级 E2E 见 docs/usage-guide。
const baseURL = process.env.PA_E2E_BASE_URL ?? "http://127.0.0.1:1420";
const externalServer = process.env.PA_E2E_EXTERNAL_SERVER === "1";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  retries: 0,
  workers: 1,
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: externalServer
    ? undefined
    : {
        command:
          "node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 1420 --strictPort",
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
      },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
