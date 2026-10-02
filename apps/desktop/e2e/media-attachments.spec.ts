import { test, expect } from "@playwright/test";
import { prepareRedesignFixture } from "./redesign-fixture";

for (const [width, height, scale] of [[1280, 720, 1.25], [1440, 900, 1.5], [390, 844, 1]]) {
  test.describe(`图片和 PDF 预览 ${width}@${scale}`, () => {
    test.use({ viewport: { width, height }, deviceScaleFactor: scale, reducedMotion: "reduce" });
    test("页面图片、翻页和底部操作可见，关闭返回焦点", async ({ page }, info) => {
      const state = await prepareRedesignFixture(page);
      const imageUrl = await page.evaluate(() => {
        const canvas = document.createElement("canvas");
        canvas.width = 600; canvas.height = 800;
        const context = canvas.getContext("2d")!;
        context.fillStyle = "#ffffff"; context.fillRect(0, 0, 600, 800);
        context.fillStyle = "#182e3b"; context.font = "32px sans-serif"; context.fillText("PDF preview fixture", 40, 70);
        context.font = "18px sans-serif"; context.fillText("Text and image content", 40, 110);
        context.fillStyle = "#cde9e5"; context.fillRect(40, 160, 520, 250);
        context.fillStyle = "#376d6c"; context.fillRect(80, 200, 110, 170); context.fillRect(230, 250, 110, 120); context.fillRect(380, 280, 110, 90);
        return canvas.toDataURL("image/jpeg");
      });
      const item = { id: "a".repeat(32), name: "样例报告.pdf", size_bytes: 32768, sha256: "b".repeat(64),
        language: "pdf", kind: "pdf", page_count: 2, requires_vision: false, project_id: 1, workspace_id: 101 };
      const draftId = "c".repeat(32);
      await page.addInitScript(data => localStorage.setItem("pa_coding_draft_v2_1_101_new", JSON.stringify(data)),
        { text: "请概括 PDF 的内容", chips: [], attachments: [item], draftId });
      await page.route("**://127.0.0.1:8000/task-attachments**", async route => {
        const url = new URL(route.request().url());
        if (url.pathname.endsWith("/content")) return route.fulfill({ json: { ...item, image_data_url: imageUrl,
          page: Number(url.searchParams.get("page") ?? 1), offset: 0, next_offset: null,
          content: "这是本机提取的第 " + url.searchParams.get("page") + " 页文字。", total_chars: 18 } });
        return route.fulfill({ json: [item] });
      });
      await page.goto("/#/app");
      const trigger = page.locator(".task-attachment button").first();
      await trigger.click();
      const dialog = page.getByRole("dialog", { name: item.name });
      await expect(dialog.locator("img")).toBeVisible();
      await expect(dialog.getByRole("button", { name: "导入项目…" })).toBeInViewport();
      await dialog.getByRole("button", { name: "下一页" }).click();
      await expect(dialog).toContainText("第 2 / 2 页");
      await expect(dialog.locator(".attachment-content")).toContainText("第 2 页");
      await dialog.getByRole("button", { name: "上一页" }).focus();
      await page.keyboard.press("Shift+Tab");
      await expect(dialog.getByRole("button", { name: "确认创建项目文件" })).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: info.outputPath("pdf-preview.png"), animations: "disabled" });
      await page.keyboard.press("Escape");
      await expect(dialog).not.toBeVisible();
      await expect(trigger).toBeFocused();
      expect(state.writes).toEqual([]);
      expect(state.unknownRequests).toEqual([]);
      expect(state.browserErrors).toEqual([]);
    });
  });
}

test("模型视觉能力为显式声明，配置行不溢出", async ({ page }, info) => {
  await prepareRedesignFixture(page);
  await page.addInitScript(() => {
    const surface = window as unknown as { __TAURI_INTERNALS__: { invoke: (command: string, args: unknown) => Promise<unknown> } };
    const invoke = surface.__TAURI_INTERNALS__.invoke;
    surface.__TAURI_INTERNALS__.invoke = (command, args) => command === "read_model_provider_draft" ? Promise.resolve(null) : invoke(command, args);
  });
  await page.goto("/#/app");
  await page.locator(".workspace-header__profile").click();
  await page.getByTestId("settings-section-provider").click();
  await page.getByLabel("deepseek-flash 支持视觉输入", { exact: true }).check();
  await expect(page.getByLabel("deepseek-flash 支持视觉输入", { exact: true })).toBeChecked();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("vision-setting.png"), animations: "disabled" });
});
