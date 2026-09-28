import { expect, test } from "@playwright/test";
import { prepareCodingFixture } from "./coding-auth-fixture";

test("项目编辑、目录确认、置顶持久展示和会话删除", async ({ page }, testInfo) => {
  await prepareCodingFixture(page);
  await page.addInitScript(() => {
    const native = (window as unknown as { __TAURI_INTERNALS__: { invoke: (command: string, args: unknown) => Promise<unknown> } }).__TAURI_INTERNALS__;
    const invoke = native.invoke;
    native.invoke = async (command, args) => command === "plugin:dialog|open" ? "C:\\projects\\new-root" : invoke(command, args);
  });
  const stamp = "2026-09-19T00:00:00Z";
  let projects = [2, 1].map((id) => ({ id, name: id === 1 ? "需要管理的项目" : "保留项目", root_path: `C:\\projects\\${id}`, status: "active", pinned_at: null as string | null, updated_at: stamp, created_at: stamp }));
  let sessions = [{ id: 11, project_id: 1, workspace_id: 101, title: "可删除的会话", kind: "coding", last_run_id: null, updated_at: stamp, created_at: stamp }];
  const writes: string[] = [];
  await page.route("**://127.0.0.1:8000/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    if (method !== "GET") writes.push(`${method} ${path}`);
    if (path === "/capabilities") return route.fulfill({ json: { coding_agent_ui_enabled: true, coding_worktree_enabled: false } });
    if (path === "/agent-model-profiles") return route.fulfill({ json: [] });
    if (path === "/projects") return route.fulfill({ json: projects });
    if (path === "/projects/1" && method === "GET") return route.fulfill({ json: projects.find((item) => item.id === 1) });
    if (path === "/projects/1" && method === "PATCH") {
      const body = request.postDataJSON();
      if (body.root_path) expect(body.authorize_scope).toBe(true);
      projects = projects.map((project) => project.id === 1 ? { ...project, name: body.name, root_path: body.root_path ?? project.root_path } : project);
      return route.fulfill({ json: projects.find((item) => item.id === 1) });
    }
    if (path === "/projects/1/pin" || path === "/projects/1/unpin") {
      projects = projects.map((project) => project.id === 1 ? { ...project, pinned_at: path.endsWith("/pin") ? stamp : null } : project);
      return route.fulfill({ json: projects.find((item) => item.id === 1) });
    }
    if (path === "/projects/1" && method === "DELETE") {
      projects = projects.filter((item) => item.id !== 1);
      sessions = [];
      return route.fulfill({ json: { deleted: true } });
    }
    if (/^\/projects\/\d+\/workspaces$/.test(path)) {
      const projectId = Number(path.split("/")[2]);
      return route.fulfill({ json: [{ id: projectId * 100 + 1, project_id: projectId, kind: "root", status: "active", branch_name: null, head_sha: null, last_used_at: stamp }] });
    }
    if (path.endsWith("/git/branches")) return route.fulfill({ json: { is_git: false, current_branch: null, head_sha: null, dirty: false, branches: [] } });
    if (path === "/sessions") return route.fulfill({ json: sessions.filter((item) => !url.searchParams.has("project_id") || item.project_id === Number(url.searchParams.get("project_id"))) });
    if (path === "/sessions/11" && method === "DELETE") { sessions = []; return route.fulfill({ json: { deleted: true } }); }
    if (path.endsWith("/latest-agent-run")) return route.fulfill({ json: { run_id: null } });
    if (path.endsWith("/messages") || path === "/sessions/recent" || path === "/sessions/search") return route.fulfill({ json: [] });
    if (path.endsWith("/context-budget")) return route.fulfill({ json: {} });
    return route.fulfill({ status: 404, json: { error_code: "test_unhandled", detail: "此测试不支持此接口" } });
  });
  await page.setViewportSize({ width: 1440, height: 950 });
  await page.goto("/app?view=coding");
  await expect(page.getByTestId("coding-project-1")).toBeVisible();
  await page.getByTestId("coding-project-1").locator("summary").click();
  await page.getByTestId("coding-project-edit-1").click();
  const editor = page.getByRole("dialog", { name: "编辑项目", exact: true });
  await expect(editor.getByTestId("edit-project-name")).toHaveValue("需要管理的项目");
  await editor.getByTestId("edit-project-name").fill("修改后的项目");
  await editor.getByTestId("edit-project-directory").click();
  await expect(editor.getByTestId("edit-project-directory")).toContainText("new-root");
  await editor.getByTestId("edit-project-save").click();
  const confirmation = page.getByRole("dialog", { name: "确认更换项目目录？", exact: true });
  await expect(confirmation).toContainText("已有文件不会移动");
  await confirmation.getByRole("button", { name: "确认更换", exact: true }).click();
  await expect(editor).not.toBeVisible();
  await expect(page.getByTestId("coding-project-1")).toContainText("修改后的项目");
  await page.getByTestId("coding-project-1").locator("summary").click();
  await page.getByTestId("coding-project-pin-1").click();
  await expect(page.locator(".project-row").first()).toHaveAttribute("data-testid", "coding-project-1");
  await page.reload();
  await expect(page.locator(".project-row").first()).toHaveAttribute("data-testid", "coding-project-1");
  await page.screenshot({ path: testInfo.outputPath("project-management-wide.png"), fullPage: true });
  await page.getByTestId("coding-project-1").locator("summary").click();
  await page.getByTestId("coding-project-pin-1").click();
  await expect(page.locator(".project-row").first()).toHaveAttribute("data-testid", "coding-project-2");
  await page.getByTestId("coding-thread-11").click();
  await expect(page.getByTestId("thread-menu-toggle")).toBeVisible();
  await page.getByTestId("thread-menu-toggle").click();
  await expect(page.getByRole("menu")).toContainText("归档");
  await page.getByTestId("thread-menu-delete").click();
  await page.getByRole("dialog", { name: "删除对话？" }).getByRole("button", { name: "取消", exact: true }).click();
  expect(writes).not.toContain("DELETE /sessions/11");
  await page.getByTestId("coding-thread-11").locator("summary").click();
  await page.getByTestId("coding-thread-delete-11").click();
  await page.getByRole("dialog", { name: "删除对话？" }).getByRole("button", { name: "删除", exact: true }).click();
  await expect(page.getByTestId("coding-thread-11")).not.toBeVisible();
  await expect(page.getByTestId("thread-menu-toggle")).not.toBeVisible();
  await page.setViewportSize({ width: 760, height: 900 });
  await page.getByTestId("coding-drawer-tab").click();
  await expect(page.getByTestId("coding-project-1").locator("summary")).toBeVisible();
  await page.getByTestId("coding-project-1").locator("summary").click();
  await page.getByTestId("coding-project-edit-1").click();
  await expect(editor.getByTestId("edit-project-directory")).toContainText("new-root");
  await page.screenshot({ path: testInfo.outputPath("project-management-narrow.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await editor.getByRole("button", { name: "取消", exact: true }).click();
  await page.getByTestId("coding-project-1").locator("summary").click();
  await page.getByTestId("coding-project-delete-1").click();
  const removal = page.getByRole("dialog", { name: "删除项目？", exact: true });
  await expect(removal).toContainText("项目目录和文件保持不变");
  await removal.getByRole("button", { name: "删除项目", exact: true }).click();
  await expect(page.getByTestId("coding-project-1")).not.toBeVisible();
  await expect(page.getByTestId("coding-project-2")).toBeVisible();
  expect(writes).toContain("PATCH /projects/1");
  expect(writes).toContain("DELETE /sessions/11");
  expect(writes).toContain("DELETE /projects/1");
  expect(writes.some((path) => path.includes("archive"))).toBe(false);
});
