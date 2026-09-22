import { test, expect, type Page } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { prepareRedesignFixture, settleDesign } from "./redesign-fixture";

/** 使用真实组件与隔离本机接口；基线只能在逐张检查截图后更新。 */
async function openCodingVisual(page: Page, width: number, height: number, task = false) {
  await page.setViewportSize({ width, height });
  const state = await prepareRedesignFixture(page);
  await page.goto(task ? "/?coding-run-preview=command-output#/app" : "/#/app");
  await expect(page.getByTestId("coding-home-ready")).toBeVisible();
  if (task) {
    await page.getByTestId("coding-thread-11").click();
    await expect(page.getByTestId("tool-toggle").last()).toBeVisible();
    await page.getByTestId("tool-toggle").last().click();
    await page.getByTestId("command-output-toggle").click();
    await page.getByTestId("command-output-detail").scrollIntoViewIfNeeded();
  }
  await expect(page.getByTestId("coding-composer-input")).toBeVisible();
  await settleDesign(page);
  await expect(page.locator(".workspace-header__title")).toBeInViewport();
  await expect(page.locator(".app-brand")).toHaveCount(0);
  if (!task) {
    const dock = await page.locator(".draft-dock").boundingBox();
    expect(dock).not.toBeNull();
    expect(height - (dock!.y + dock!.height)).toBeCloseTo(16, 0);
  }
  expect(state.unknownRequests).toEqual([]);
  return state;
}

test.use({ reducedMotion: "reduce" });
test("设计稿对应尺寸预览", async ({ page }, testInfo) => {
  await openCodingVisual(page, 1488, 1058);
  await page.screenshot({ animations: "disabled", path: testInfo.outputPath("home-reference-size.png") });
  await page.locator(".home-hero").screenshot({ path: testInfo.outputPath("hero-detail.png") });
  const client = await page.context().newCDPSession(page);
  await client.send("DOM.enable"); await client.send("CSS.enable");
  const { root } = await client.send("DOM.getDocument");
  const { nodeId } = await client.send("DOM.querySelector", { nodeId: root.nodeId, selector: ".home-hero__description" });
  const fonts = await client.send("CSS.getPlatformFontsForNode", { nodeId });
  await writeFile(testInfo.outputPath("rendered-fonts.json"), JSON.stringify(fonts, null, 2));
  await client.detach();
});
for (const [width, height] of [[1280, 720], [1440, 900], [1920, 1080]]) {
  test(`coding 首页 ${width}`, async ({ page }, testInfo) => {
    const state = await openCodingVisual(page, width, height);
    await expect(page.locator(".home-project")).toHaveCount(3);
    await expect(page.getByTestId("coding-project-4")).toBeVisible();
    const sections = await page.locator(".home-hero, .home-projects, .task-starters, .draft-dock").evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().top));
    expect(sections).toHaveLength(4);
    expect(sections).toEqual([...sections].sort((a, b) => a - b));
    expect(state.writes).toEqual([]);
    await expect(page.getByTestId("coding-composer-send")).toBeInViewport();
    await page.screenshot({ animations: "disabled", path: testInfo.outputPath(`home-${width}.png`) });
    await expect(page).toHaveScreenshot(`coding-home-${width}.png`, { maxDiffPixelRatio: 0.01 });
  });
}

test("coding 任务页（审批+命令输出）1440", async ({ page }, testInfo) => {
  await openCodingVisual(page, 1440, 900, true);
  await page.screenshot({ animations: "disabled", path: testInfo.outputPath("task-1440.png") });
  await expect(page).toHaveScreenshot("coding-thread-1440.png", { maxDiffPixelRatio: 0.01 });
});

test.describe("Windows 125% 缩放", () => {
  test.use({ deviceScaleFactor: 1.25 });
  test("coding 首页 1280@125%", async ({ page }, testInfo) => {
    await openCodingVisual(page, 1280, 720);
    await page.screenshot({ animations: "disabled", path: testInfo.outputPath("home-1280-at-125.png") });
    await expect(page).toHaveScreenshot("coding-home-1280-at-125.png", { maxDiffPixelRatio: 0.01 });
  });
});

test.describe("Windows 150% 缩放", () => {
  test.use({ deviceScaleFactor: 1.5 });
  test("coding 任务页 1440@150%", async ({ page }, testInfo) => {
    await openCodingVisual(page, 1440, 900, true);
    await page.screenshot({ animations: "disabled", path: testInfo.outputPath("task-1440-at-150.png") });
    await expect(page).toHaveScreenshot("coding-thread-1440-at-150.png", { maxDiffPixelRatio: 0.01 });
  });
});

test("首页输入区在高度断点与抽屉布局下保持底部对齐", async ({ page }) => {
  await openCodingVisual(page, 1280, 720);
  for (const [width, height] of [[1280, 801], [1440, 950], [1440, 951], [1120, 986]]) {
    await page.setViewportSize({ width, height });
    await settleDesign(page);
    const dock = await page.locator(".draft-dock").boundingBox();
    expect(dock).not.toBeNull();
    expect(height - (dock!.y + dock!.height)).toBeCloseTo(16, 0);
    await expect(page.getByTestId("coding-composer-send")).toBeInViewport();
  }
});

test("设置资料同步、插件、窄窗口与草稿往返", async ({ page }, testInfo) => {
  const state = await openCodingVisual(page, 1440, 900);
  const input = page.getByLabel("任务输入", { exact: true });
  await page.getByRole("button", { name: "读懂项目", exact: true }).click();
  await expect(input).toBeFocused();
  await expect(input).toHaveValue(/请先阅读项目说明与目录/);
  await input.fill("保留这段未发送的草稿");
  await page.locator(".workspace-header__profile").click();
  await page.getByLabel("称呼", { exact: true }).fill("开发者");
  await page.getByLabel("个人简介", { exact: true }).fill("保持好奇，认真构建。");
  await page.getByTestId("profile-save").click();
  await expect(page.locator(".workspace-header__profile")).toContainText("开发者");
  await expect(page.locator(".app-brand")).toHaveCount(0);
  await settleDesign(page);
  await page.screenshot({ animations: "disabled", path: testInfo.outputPath("profile-1440.png") });
  for (const section of ["current-model", "provider", "mcp", "memories", "appearance", "backup", "about"]) {
    await page.getByTestId(`settings-section-${section}`).click();
    if (section === "about") await expect(page.getByLabel("更新清单地址", { exact: true })).toHaveCount(0);
    await settleDesign(page);
    await page.screenshot({ animations: "disabled", path: testInfo.outputPath(`settings-${section}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.locator(".settings-nav__exit").click();
  await expect(input).toHaveValue("保留这段未发送的草稿");
  await page.getByTestId("coding-nav-extensions").click();
  await expect(page.getByText("project-review", { exact: true })).toBeVisible();
  await page.screenshot({ animations: "disabled", path: testInfo.outputPath("plugins-skills.png") });
  await page.getByRole("button", { name: "MCP 工具", exact: true }).click();
  await page.screenshot({ animations: "disabled", path: testInfo.outputPath("plugins-mcp.png") });
  await page.getByTestId("coding-new-task").click();
  await page.setViewportSize({ width: 760, height: 900 });
  await expect(page.getByTestId("coding-drawer-tab")).toBeVisible();
  await page.getByTestId("coding-drawer-tab").click();
  await expect(page.getByTestId("coding-open-search")).toBeVisible();
  await expect(page.locator(".app-brand")).toHaveCount(0);
  await page.getByTestId("coding-drawer-close").click();
  await expect(page.getByTestId("coding-sidebar")).toHaveCount(0);
  await settleDesign(page);
  await page.screenshot({ animations: "disabled", path: testInfo.outputPath("home-760.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await settleDesign(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ animations: "disabled", path: testInfo.outputPath("home-390.png") });
  expect(state.unknownRequests).toEqual([]);
  expect(state.writes).toEqual([]);
  expect(state.browserErrors).toEqual([]);
});
