import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import ProjectWorktreeSettings from "./ProjectWorktreeSettings.vue";
import { createIsolatedWorkspace, fetchCodingBranches } from "../api/projects";

vi.mock("../api/projects", () => ({ createIsolatedWorkspace: vi.fn(), fetchCodingBranches: vi.fn() }));
let wrapper: VueWrapper;
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(fetchCodingBranches).mockResolvedValue({ isGit: true, currentBranch: "main", headSha: "abc", dirty: true, branches: [{ name: "main", headSha: "abc", current: true }, { name: "dev", headSha: "def", current: false }] });
  vi.mocked(createIsolatedWorkspace).mockResolvedValue({ id: 12, projectId: 1, kind: "git_worktree", branchName: "codex/example", headSha: "abc", status: "active", lastUsedAt: null });
});
afterEach(() => wrapper?.unmount());
async function open() { wrapper = mount(ProjectWorktreeSettings, { props: { projectId: 1 } }); await flushPromises(); }

describe("ProjectWorktreeSettings", () => {
  it("显式创建使用所选分支，失败重试复用幂等标识", async () => {
    await open();
    expect(createIsolatedWorkspace).not.toHaveBeenCalled();
    await wrapper.get("select").setValue("dev");
    vi.mocked(createIsolatedWorkspace).mockRejectedValueOnce({ message: "连接中断" });
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe("连接中断");
    const request = vi.mocked(createIsolatedWorkspace).mock.calls[0];
    expect(request).toEqual([1, "dev", expect.any(String)]);
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(vi.mocked(createIsolatedWorkspace).mock.calls[1]).toEqual(request);
    expect(wrapper.emitted("created")).toEqual([[12]]);
  });

  it("创建期间防止重复提交，卸载后不跳转工作区", async () => {
    await open();
    let resolve!: (value: Awaited<ReturnType<typeof createIsolatedWorkspace>>) => void;
    vi.mocked(createIsolatedWorkspace).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    await wrapper.get("button").trigger("click");
    await wrapper.get("button").trigger("click");
    expect(createIsolatedWorkspace).toHaveBeenCalledOnce();
    expect(wrapper.get("select").attributes("disabled")).toBeDefined();
    expect(wrapper.emitted("busy-change")).toEqual([[true]]);
    wrapper.unmount();
    resolve({ id: 12, projectId: 1, kind: "git_worktree", branchName: "codex/example", headSha: "abc", status: "active", lastUsedAt: null });
    await flushPromises();
    expect(wrapper.emitted("created")).toBeUndefined();
  });

  it("非 Git 项目不提供创建动作，读取失败可重试", async () => {
    vi.mocked(fetchCodingBranches).mockRejectedValueOnce({ message: "读取失败" });
    await open();
    expect(wrapper.get('[role="alert"]').text()).toBe("读取失败");
    vi.mocked(fetchCodingBranches).mockResolvedValueOnce({ isGit: false, currentBranch: null, headSha: null, dirty: false, branches: [] });
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("不是 Git 仓库");
    expect(wrapper.find("button").exists()).toBe(false);
    expect(createIsolatedWorkspace).not.toHaveBeenCalled();
  });
});
