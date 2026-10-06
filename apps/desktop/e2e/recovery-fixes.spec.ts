import { expect, test, type Page } from "@playwright/test";
import { prepareRedesignFixture } from "./redesign-fixture";

interface RecoveryFixture {
  dead: boolean;
  starts: number;
  failStart: boolean;
  failIdentity: boolean;
  contexts: number[];
  cleared: string[];
}

async function recoveryFixture(page: Page, failIdentity = false) {
  const state = await prepareRedesignFixture(page);
  await page.addInitScript(({ failIdentity }) => {
    const surface = window as unknown as {
      __recoveryFixture: RecoveryFixture;
      __TAURI_INTERNALS__: { invoke: (command: string, args: { alias?: string; request?: { path: string; body?: string } }) => Promise<unknown> };
    };
    const fixture = surface.__recoveryFixture = { dead: false, starts: 0, failStart: false, failIdentity, contexts: [], cleared: [] };
    const invoke = surface.__TAURI_INTERNALS__.invoke;
    // 只模拟私有 IPC 生命周期和凭据删除，不启动执行器或访问系统凭据。
    surface.__TAURI_INTERNALS__.invoke = async (command, args) => {
      if (command === "start_local_executor") {
        fixture.starts += 1;
        if (fixture.failStart) { fixture.failStart = false; throw new Error("模拟启动失败"); }
        fixture.dead = false;
      }
      if (command === "clear_model_provider_secret") {
        fixture.cleared.push(args.alias!);
        return { configured: false, reference: args.alias };
      }
      if (command === "local_executor_request") {
        if (fixture.dead) throw new Error("模拟执行器已退出");
        if (args.request?.path === "/identity/local" && fixture.failIdentity) {
          fixture.failIdentity = false; fixture.dead = true;
          throw new Error("模拟健康检查后执行器退出");
        }
        if (args.request?.path === "/projects/context") fixture.contexts.push(JSON.parse(args.request.body || "{}").project_id);
      }
      return invoke(command, args);
    };
  }, { failIdentity });
  return state;
}

async function readFixture(page: Page): Promise<RecoveryFixture> {
  return page.evaluate(() => (window as unknown as { __recoveryFixture: RecoveryFixture }).__recoveryFixture);
}

test("健康检查后身份绑定前退出，可以通过启动页再次连接", async ({ page }) => {
  const state = await recoveryFixture(page, true);
  await page.goto("/#/app");
  await expect(page.getByRole("heading", { name: "本地服务未能启动" })).toBeVisible();
  expect((await readFixture(page)).starts).toBe(1);
  await page.getByRole("button", { name: "重试连接", exact: true }).click();
  await expect(page.getByTestId("coding-composer-input")).toBeEnabled();
  expect((await readFixture(page)).starts).toBe(2);
  expect(state.writes).toEqual([]);
  expect(state.unknownRequests).toEqual([]);
});

test("工作台退出后显式重连可再次重试，保留选择与草稿且不重放任务", async ({ page }) => {
  const state = await recoveryFixture(page);
  await page.goto("/#/app");
  const input = page.getByTestId("coding-composer-input");
  await expect(input).toBeEnabled();
  await input.fill("断线后保留的草稿，不自动发送");
  await page.clock.runFor(500);
  await page.evaluate(() => {
    document.querySelector(".appshell")?.setAttribute("data-recovery-mounted", "original");
    const fixture = (window as unknown as { __recoveryFixture: RecoveryFixture }).__recoveryFixture;
    fixture.dead = true; fixture.failStart = true;
  });
  await page.getByTestId("coding-refresh").click();
  const retry = page.getByRole("button", { name: "重试连接", exact: true });
  await expect(retry).toBeVisible();
  expect((await readFixture(page)).starts).toBe(1);
  await retry.click();
  await expect(page.getByText("模拟启动失败", { exact: false })).toBeVisible();
  await retry.click();
  await expect(input).toHaveValue("断线后保留的草稿，不自动发送");
  await expect(input).toBeEnabled();
  await expect(page.locator(".appshell")).toHaveAttribute("data-recovery-mounted", "original");
  const fixture = await readFixture(page);
  expect(fixture.starts).toBe(3);
  expect(fixture.contexts[fixture.contexts.length - 1]).toBe(1);
  expect(state.writes).toEqual([]);
  expect(state.unknownRequests).toEqual([]);
});

for (const failSecondBatch of [false, true]) {
  test(`65 项旧凭据${failSecondBatch ? "第二批失败后重新核对剩余项" : "经确认后分批完成"}`, async ({ page }) => {
    const state = await recoveryFixture(page);
    const remaining = new Set(Array.from({ length: 65 }, (_, index) => `fixture-retired-${index}`));
    const batches: string[][] = [];
    let reads = 0;
    await page.route("**://127.0.0.1:8000/**", async route => {
      const request = route.request(), path = new URL(request.url()).pathname;
      if (path === "/capabilities") return route.fulfill({ json: { coding_agent_ui_enabled: true, agent_runs_api_enabled: true,
        project_bound_runs_enabled: true, coding_worktree_enabled: true, coding_context_budget_enabled: true,
        coding_recovery_contract_version: "1.0", coding_model_save_recovery_enabled: true } });
      if (path === "/model-save-operations") return route.fulfill({ json: [] });
      if (path === "/model-save-operations/credentials/unused") {
        reads += 1; return route.fulfill({ json: { aliases: [...remaining] } });
      }
      if (path === "/model-save-operations/credentials/cleanup") {
        const aliases = request.postDataJSON().aliases as string[];
        batches.push(aliases);
        if (aliases.length > 64) return route.fulfill({ status: 422, json: { detail: "每批最多 64 项" } });
        if (failSecondBatch && batches.length === 2) return route.fulfill({ status: 409, json: { detail: "模拟第二批登记失败" } });
        return route.fulfill({ json: { aliases } });
      }
      const cleared = path.match(/^\/model-save-operations\/credentials\/(fixture-retired-\d+)\/cleared$/);
      if (cleared) {
        remaining.delete(cleared[1]); return route.fulfill({ json: { cleared: true } });
      }
      return route.fallback();
    });
    await page.goto("/#/app");
    await expect(page.getByTestId("coding-composer-input")).toBeEnabled();
    await page.locator(".workspace-header__profile").click();
    await page.getByTestId("settings-section-provider").click();
    const clean = page.getByRole("button", { name: "检查并清理旧凭据", exact: true });
    await clean.click();
    const confirmation = page.getByRole("dialog", { name: "清理 65 项旧凭据？", exact: true });
    await expect(confirmation).toBeVisible();
    await confirmation.getByRole("button", { name: "确认清理", exact: true }).click();
    if (failSecondBatch) {
      await expect(page.locator(".model-save-recovery [role=alert]")).toContainText("已确认清理 64 项");
      expect(remaining.size).toBe(1);
      expect((await readFixture(page)).cleared).toHaveLength(64);
      await clean.click();
      const retry = page.getByRole("dialog", { name: "清理 1 项旧凭据？", exact: true });
      await expect(retry).toBeVisible();
      await retry.getByRole("button", { name: "确认清理", exact: true }).click();
    }
    await expect(page.locator(".model-save-recovery [role=status]")).toHaveText(`已清理 ${failSecondBatch ? 1 : 65} 项旧凭据。`);
    expect(batches.map(batch => batch.length)).toEqual(failSecondBatch ? [64, 1, 1] : [64, 1]);
    expect(reads).toBe(failSecondBatch ? 2 : 1);
    expect(remaining.size).toBe(0);
    expect((await readFixture(page)).cleared).toEqual(Array.from({ length: 65 }, (_, index) => `fixture-retired-${index}`));
    expect(state.writes).toEqual([]);
    expect(state.unknownRequests).toEqual([]);
    expect(state.browserErrors).toEqual(failSecondBatch ? [expect.stringContaining("409")] : []);
  });
}
