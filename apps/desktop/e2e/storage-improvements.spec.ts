import { test, expect, type Page } from "@playwright/test";
import { prepareRedesignFixture, settleDesign } from "./redesign-fixture";

async function fixture(page: Page) {
  const state = await prepareRedesignFixture(page);
  const saved = new Map<string, { revision: number; mutation_id: string | null; data: unknown; updated_at: string | null }>();
  let scope = "global";
  const item = { id: "a".repeat(32), name: "项目设计说明.txt", size_bytes: 128, sha256: "b".repeat(64), language: "txt", project_id: 1, workspace_id: 101, project_name: "PrivateAgent", read_status: "可预览；预览时校验摘要", drafts: [{ id: "c".repeat(32), title: "首页草稿", session_id: null, scope_key: "pa_coding_draft_v2_1_101_new", revision: 1 }], sessions: [{ id: 11, title: "优化页面布局", messages: 1 }] };
  await page.route("**://127.0.0.1:8000/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path === "/capabilities") return route.fulfill({ json: { coding_agent_ui_enabled: true, agent_runs_api_enabled: true, project_bound_runs_enabled: true, coding_worktree_enabled: true, coding_context_budget_enabled: true, coding_recovery_contract_version: "1.0", coding_durable_drafts_enabled: true, coding_model_scopes_enabled: true, coding_app_backups_enabled: true, coding_attachment_storage_enabled: true, coding_model_save_recovery_enabled: true } });
    if (path.startsWith("/composer-drafts/")) {
      let value = saved.get(path) || { revision: 0, mutation_id: null, data: null, updated_at: null };
      if (request.method() === "PUT") {
        const input = request.postDataJSON();
        if (input.revision !== value.revision) return route.fulfill({ status: 409, json: { detail: "草稿冲突" } });
        value = { revision: value.revision + 1, mutation_id: input.mutation_id, data: input.data, updated_at: "2026-10-02T01:00:00Z" }; saved.set(path, value);
      }
      return route.fulfill({ json: value });
    }
    if (path === "/model-preferences") {
      if (request.method() === "PUT") scope = request.postDataJSON().scope;
      return route.fulfill({ json: { profile_id: "fixture-model", source: scope, available: true, overrides: { global: "fixture-model", project: scope === "project" ? "fixture-model" : null, session: null } } });
    }
    if (path === "/task-attachments") return route.fulfill({ json: [] });
    if (path === "/model-save-operations") return route.fulfill({ json: [] });
    if (path === "/attachment-storage") return route.fulfill({ json: { items: [item], total: 1, offset: 0, size_bytes: 128, cache_bytes: 0, cache_policy: "图片和 PDF 页面按需解码，当前没有可单独清理的持久化解析缓存。", retention: "未发送材料持续保留，原始文件不受影响。" } });
    if (path === "/attachment-storage/preview") return route.fulfill({ json: { version: "d".repeat(64), attachment_id: item.id, draft_id: item.drafts[0].id, name: item.name, draft: item.drafts[0], remaining_drafts: 0, sessions: item.sessions, reclaim_bytes: 0 } });
    return route.fallback();
  });
  return { state, saved };
}

for (const [width, height, scale] of [[1280, 720, 1.25], [1440, 900, 1.5], [1920, 1080, 1], [390, 844, 1]]) {
  test.describe(`存储体验 ${width}@${scale}`, () => {
    test.use({ viewport: { width, height }, deviceScaleFactor: scale, reducedMotion: "reduce" });
    test("模型作用域、备份及附件管理可见，弹窗键盘焦点返回", async ({ page }, info) => {
      const { state } = await fixture(page);
      await page.goto("/#/app");
      const model = page.getByTestId("model-scope-picker");
      await expect(model).toContainText("全局默认");
      await model.click();
      const dialog = page.getByRole("dialog", { name: "模型选择与作用范围" });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByLabel("模型应用范围")).toBeFocused();
      await page.keyboard.press("Shift+Tab");
      await expect(dialog.getByRole("button", { name: "保存选择" })).toBeFocused();
      await page.screenshot({ path: info.outputPath("model-scope.png"), animations: "disabled" });
      await page.keyboard.press("Escape"); await expect(model).toBeFocused();
      await page.locator(".workspace-header__profile").click();
      if (width < 700) await page.getByRole("button", { name: "打开设置模块" }).click();
      await page.getByTestId("settings-section-backup").click();
      await expect(page.getByRole("button", { name: "导出普通配置", exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: "附件与存储", exact: true })).toBeVisible();
      await expect(page.getByText("项目设计说明.txt", { exact: false })).toBeVisible();
      await page.getByRole("button", { name: "预览移除影响" }).scrollIntoViewIfNeeded();
      await settleDesign(page);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: info.outputPath("backup-storage.png"), animations: "disabled" });
      await page.getByRole("button", { name: "预览移除影响" }).click();
      const confirm = page.getByRole("dialog", { name: /移除 项目设计说明/ });
      await expect(confirm).toContainText("预计释放 0 B");
      await page.keyboard.press("Escape");
      expect(state.unknownRequests).toEqual([]);
      expect(state.browserErrors).toEqual([]);
    });
  });
}

test("本机草稿在浏览器缓存清空后恢复，不自动发送", async ({ page }) => {
  const { state, saved } = await fixture(page);
  await page.goto("/#/app");
  const input = page.getByTestId("coding-composer-input");
  await expect(input).toBeEnabled(); await input.fill("本机草稿数据库恢复验证");
  await page.clock.runFor(500);
  await expect.poll(() => [...saved.values()].some(value => (value.data as { text?: string })?.text === "本机草稿数据库恢复验证")).toBe(true);
  await page.evaluate(() => Object.keys(localStorage).filter(key => key.startsWith("pa_coding_draft_")).forEach(key => localStorage.removeItem(key)));
  await page.reload(); await expect(input).toHaveValue("本机草稿数据库恢复验证");
  expect(state.writes).toEqual([]); expect(state.unknownRequests).toEqual([]);
});
