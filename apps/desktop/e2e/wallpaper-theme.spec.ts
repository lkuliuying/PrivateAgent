import { test, expect, type Page } from "@playwright/test";
import { prepareCodingFixture } from "./coding-auth-fixture";

test.use({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });

async function prepare(page: Page) {
  const requests: string[] = [];
  await prepareCodingFixture(page);
  await page.route("**://127.0.0.1:8000/**", async route => {
    const path = new URL(route.request().url()).pathname;
    requests.push(`${route.request().method()} ${path}`);
    let body: unknown = [];
    if (path === "/capabilities") body = { coding_agent_ui_enabled: true, project_bound_runs_enabled: true };
    if (path === "/model-settings") body = { llm_temperature: 0.2, llm_context_length: 8192, kb_enabled_by_default: false };
    await route.fulfill({ json: body });
  });
  await page.goto("/#/app");
  await page.goto("/#/app?view=settings&section=appearance");
  await reloadAppearance(page);
  await expect(page.getByTestId("wallpaper-plugin")).toBeVisible();
  await expect(page.getByRole("button", { name: "选择图片", exact: true })).toBeEnabled();
  return requests;
}

async function reloadAppearance(page: Page) {
  await page.reload();
  await page.getByTestId("settings-section-appearance").click();
}

async function picture(page: Page, color: string, width = 960, height = 600, mimeType = "image/png") {
  const data = await page.evaluate(({ color, width, height, mimeType }) => {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d")!;
    if (color !== "transparent") {
      const gradient = ctx.createLinearGradient(0, 0, width, height);
      gradient.addColorStop(0, color);
      gradient.addColorStop(1, color === "#18264c" ? "#633078" : color);
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, width, height);
    }
    return canvas.toDataURL(mimeType).split(",")[1];
  }, { color, width, height, mimeType });
  return { name: `wallpaper.${mimeType.split("/")[1]}`, mimeType, buffer: Buffer.from(data, "base64") };
}

async function select(page: Page, file: Awaited<ReturnType<typeof picture>>) {
  await page.getByLabel("选择壁纸文件").setInputFiles(file);
  await expect(page.getByRole("button", { name: "应用主题", exact: true })).toBeEnabled();
}

async function apply(page: Page) {
  await page.getByRole("button", { name: "应用主题", exact: true }).click();
  await expect(page.locator(".wallpaper-status")).toHaveText("已应用 · 全局生效");
  await expect(page.getByTestId("app-wallpaper")).toBeAttached();
}

async function geometry(page: Page) {
  return page.evaluate(() => Object.fromEntries([
    ".appshell", ".appshell-rail", ".appshell-main", ".appshell-content", ".coding-sidebar", ".coding-home",
    ".coding-thread", ".thread-composer", ".profile-panel", ".profile-field .pa-input", ".profile-save",
    "[data-testid=model-provider-manager]", ".ant-modal-content", ".cp-card",
  ].flatMap(selector => {
    const el = document.querySelector<HTMLElement>(selector);
    if (!el) return [];
    const rect = el.getBoundingClientRect(), css = getComputedStyle(el);
    return [[selector, { x: rect.x, y: rect.y, width: rect.width, height: rect.height,
      scrollWidth: el.scrollWidth, scrollHeight: el.scrollHeight, font: css.fontSize, radius: css.borderRadius }]];
  })));
}

async function setEnabled(page: Page, enabled: boolean) {
  const committed = await page.evaluate(async value => {
    // Vite 热更新会给真实模块添加版本查询串，必须使用页面已加载的同一个实例。
    const moduleUrl = performance.getEntriesByType("resource").map(entry => entry.name)
      .find(url => url.includes("/src/services/wallpaperTheme/controller.ts"));
    if (!moduleUrl) throw new Error("页面未加载壁纸主题控制器");
    const { wallpaperTheme } = await import(/* @vite-ignore */ moduleUrl);
    return wallpaperTheme.setEnabled(value);
  }, enabled);
  expect(committed).toBe(true);
}

test("预览隔离、真实存储恢复、停用和默认恢复，全程无上传", async ({ page }, info) => {
  const requests = await prepare(page);
  const original = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--color-bg"));
  await select(page, await picture(page, "#18264c"));
  await expect(page.locator("html")).not.toHaveAttribute("data-wallpaper-theme");
  await expect(page.getByText("深色主题", { exact: true })).toBeVisible();
  const before = await geometry(page);
  const requestCount = requests.length;
  await apply(page);
  expect(requests.slice(requestCount)).toEqual([]);
  expect(await geometry(page)).toEqual(before);
  await expect(page.locator("html")).toHaveAttribute("data-wallpaper-theme", "dark");
  await page.screenshot({ path: info.outputPath("wallpaper-dark.png") });
  await reloadAppearance(page);
  await expect(page.locator(".wallpaper-status")).toHaveText("已应用 · 全局生效");
  await expect(page.getByAltText("壁纸预览")).toBeVisible();
  await page.getByRole("switch").click();
  await expect(page.getByTestId("app-wallpaper")).toHaveCount(0);
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--color-bg"))).toBe(original);
  await reloadAppearance(page);
  await expect(page.locator(".wallpaper-status")).toHaveText("已停用，壁纸已保留。");
  await page.getByRole("switch").click();
  await expect(page.locator("html")).toHaveAttribute("data-wallpaper-theme", "dark");
  await page.getByRole("button", { name: "恢复默认", exact: true }).click();
  await expect(page.locator(".wallpaper-status")).toContainText("尚未启用");
  await reloadAppearance(page);
  await expect(page.locator(".wallpaper-status")).toContainText("尚未启用");
  await expect(page.getByAltText("壁纸预览")).toHaveCount(0);
  expect(requests.some(path => /extensions|wallpaper|upload/.test(path))).toBe(false);
});

test("首页、会话输出、个人资料、模型设置与窄窗口保持布局", async ({ page }, info) => {
  await prepare(page);
  await select(page, await picture(page, "#18264c"));
  await apply(page);
  const routes = [
    "/?coding-preview=ready#/app", "/?coding-preview=ready&coding-run-preview=command-output#/app",
    "/?settings-preview=providers-v2#/app?view=settings", "/#/app?view=settings&section=provider",
  ];
  for (const [index, url] of routes.entries()) {
    await page.evaluate(() => localStorage.setItem("pa_last_view", "coding"));
    await page.goto(url);
    await page.reload();
    if (index === 0) await expect(page.getByTestId("coding-home-ready")).toBeVisible();
    if (index === 1) {
      await page.getByTestId(/^coding-thread-\d+$/).first().click();
      await expect(page.getByTestId("tool-command")).toBeAttached();
      const processToggle = page.getByTestId("run-duration-toggle");
      if (await processToggle.getAttribute("aria-expanded") === "false") await processToggle.click();
      await page.locator(".tool-disclosure").filter({ has: page.getByTestId("tool-command") }).getByTestId("tool-toggle").click();
      await expect(page.getByTestId("tool-command")).toBeVisible();
      await page.getByTestId("command-output-toggle").click();
      await expect(page.getByTestId("command-line")).toBeVisible();
    }
    if (index === 2) await page.getByRole("button", { name: "个人资料", exact: true }).click();
    await expect(page.locator("html")).toHaveAttribute("data-wallpaper-theme", "dark");
    await expect(page.locator(".appshell")).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: info.outputPath(`wallpaper-page-${index}.png`) });
    const themed = await geometry(page);
    // 通过插件公开控制器停用，观察原页面；不触发路由或修改布局。
    await setEnabled(page, false);
    await expect(page.getByTestId("app-wallpaper")).toHaveCount(0);
    expect(await geometry(page)).toEqual(themed);
    await setEnabled(page, true);
  }
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog", { name: "搜索与命令" });
  await expect(dialog).toBeVisible();
  await page.getByRole("button", { name: "导航命令", exact: true }).click();
  const dialogGeometry = await geometry(page);
  await page.getByLabel("搜索内容", { exact: true }).fill("模型");
  const dialogColor = await dialog.evaluate(el => getComputedStyle(el).backgroundColor);
  expect(dialogColor).toMatch(/^rgb\(/);
  await setEnabled(page, false);
  await expect(dialog).toBeVisible();
  await expect(page.getByLabel("搜索内容", { exact: true })).toHaveValue("模型");
  await setEnabled(page, true);
  await page.getByLabel("搜索内容", { exact: true }).fill("");
  expect(await geometry(page)).toEqual(dialogGeometry);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "返回应用", exact: true }).click();
  await page.goto("/#/app?view=settings&section=appearance");
  await reloadAppearance(page);
  await page.setViewportSize({ width: 600, height: 800 });
  await expect(page.getByTestId("wallpaper-plugin")).toBeVisible();
  await expect(page.locator(".appshell-rail")).toHaveCSS("width", "0px");
  const narrow = await geometry(page);
  await page.getByRole("switch").focus();
  await page.keyboard.press("Space");
  await expect(page.getByTestId("app-wallpaper")).toHaveCount(0);
  expect(await geometry(page)).toEqual(narrow);
  await expect(page.getByRole("switch")).toBeFocused();
  await expect(page.getByRole("switch")).toHaveAttribute("aria-disabled", "false");
  await page.keyboard.press("Space");
  await expect(page.getByTestId("app-wallpaper")).toBeAttached();
  await expect(page.getByRole("switch")).toBeFocused();
  await page.screenshot({ path: info.outputPath("wallpaper-narrow.png") });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(600);
});

test("JPG、WebP、透明图片与长边限制使用真实解码", async ({ page }, info) => {
  await prepare(page);
  for (const [color, mime] of [["#f8dfb0", "image/jpeg"], ["#aaaaaa", "image/webp"], ["transparent", "image/png"]]) {
    await select(page, await picture(page, color, 4200, 900, mime));
    await expect(page.getByText("浅色主题", { exact: true })).toBeVisible();
    await apply(page);
    const stored = await page.evaluate(async () => {
      const { wallpaperStorage } = await import(/* @vite-ignore */ "/src/services/wallpaperTheme/storage.ts");
      const item = await wallpaperStorage.read();
      return { width: item.width, height: item.height, type: item.blob.type, neutral: item.palette.neutral };
    });
    expect(stored.width).toBe(3840);
    expect(stored.height).toBe(823);
    expect(stored.type).toBe("image/webp");
    if (color !== "#f8dfb0") expect(stored.neutral).toBe(true);
  }
  await page.screenshot({ path: info.outputPath("wallpaper-light.png") });
  const oriented = await picture(page, "#ff0000", 640, 320, "image/jpeg");
  const orientation = Buffer.from("ffe1002245786966000049492a0008000000010012010300010000000600000000000000", "hex");
  oriented.buffer = Buffer.concat([oriented.buffer.subarray(0, 2), orientation, oriented.buffer.subarray(2)]);
  await select(page, oriented);
  await apply(page);
  const dimensions = await page.getByAltText("壁纸预览").evaluate((img: HTMLImageElement) => [img.naturalWidth, img.naturalHeight]);
  expect(dimensions).toEqual([320, 640]);
});

test("损坏、超限与保存失败保留旧主题；离开未保存预览不生效", async ({ page }) => {
  await prepare(page);
  await select(page, await picture(page, "#18264c"));
  await apply(page);
  const old = await page.getByTestId("app-wallpaper").getAttribute("style");
  await page.getByLabel("选择壁纸文件").setInputFiles({ name: "broken.png", mimeType: "image/png", buffer: Buffer.from("broken") });
  await expect(page.locator(".wallpaper-error")).toContainText("损坏");
  await page.getByLabel("选择壁纸文件").setInputFiles({ name: "large.png", mimeType: "image/png", buffer: Buffer.alloc(10 * 1024 * 1024 + 1) });
  await expect(page.locator(".wallpaper-error")).toContainText("10 MB");
  expect(await page.getByTestId("app-wallpaper").getAttribute("style")).toBe(old);
  await select(page, await picture(page, "#ffffaa"));
  await page.evaluate(() => { IDBObjectStore.prototype.put = () => { throw new DOMException("quota", "QuotaExceededError"); }; });
  await page.getByRole("button", { name: "应用主题", exact: true }).click();
  await expect(page.locator(".wallpaper-error")).toContainText("原配置已保留");
  expect(await page.getByTestId("app-wallpaper").getAttribute("style")).toBe(old);
  await reloadAppearance(page);
  await expect(page.locator("html")).toHaveAttribute("data-wallpaper-theme", "dark");
  await select(page, await picture(page, "#ffffaa"));
  await page.goto("/#/app?view=settings");
  await reloadAppearance(page);
  await page.getByRole("button", { name: "个人资料", exact: true }).click();
  await expect(page.getByTestId("profile-settings-panel")).toBeVisible();
  await page.getByRole("button", { name: "返回应用", exact: true }).click();
  await page.goto("/#/app?view=settings&section=appearance");
  await reloadAppearance(page);
  await expect(page.locator(".wallpaper-status")).toHaveText("已应用 · 全局生效");
  await expect(page.getByText("深色主题", { exact: true })).toBeVisible();
});

test("存储不可用时启动不被阻塞且提示可见", async ({ page }) => {
  await page.addInitScript(() => { Object.defineProperty(window, "indexedDB", { value: undefined }); });
  await prepare(page);
  await expect(page.locator(".wallpaper-error")).toContainText("默认外观");
  await expect(page.getByTestId("app-wallpaper")).toHaveCount(0);
  await select(page, await picture(page, "#18264c"));
  await page.getByRole("button", { name: "应用主题", exact: true }).click();
  await expect(page.locator(".wallpaper-error")).toContainText("原配置已保留");
});

test("事务中止保留旧记录，损坏配置可提示并恢复默认", async ({ page }) => {
  await prepare(page);
  await select(page, await picture(page, "#18264c"));
  await apply(page);
  await select(page, await picture(page, "#ffffaa"));
  await page.evaluate(() => {
    const put = IDBObjectStore.prototype.put;
    IDBObjectStore.prototype.put = function (...args) {
      const request = put.apply(this, args);
      request.addEventListener("success", () => this.transaction.abort());
      return request;
    };
  });
  await page.getByRole("button", { name: "应用主题", exact: true }).click();
  await expect(page.locator(".wallpaper-error")).toContainText("原配置已保留");
  await reloadAppearance(page);
  await expect(page.locator("html")).toHaveAttribute("data-wallpaper-theme", "dark");
  await page.evaluate(() => new Promise<void>((resolve, reject) => {
    const open = indexedDB.open("privateagent-wallpaper-theme", 1);
    open.onerror = () => reject(open.error);
    open.onsuccess = () => {
      const db = open.result, transaction = db.transaction("theme", "readwrite");
      transaction.objectStore("theme").put({ version: 999 }, "current");
      transaction.oncomplete = () => { db.close(); resolve(); };
      transaction.onabort = () => { db.close(); reject(transaction.error); };
    };
  }));
  await reloadAppearance(page);
  await expect(page.locator(".wallpaper-error")).toContainText("默认外观");
  await expect(page.getByTestId("app-wallpaper")).toHaveCount(0);
  await page.getByRole("button", { name: "恢复默认", exact: true }).click();
  await expect(page.locator(".wallpaper-error")).toHaveCount(0);
});
