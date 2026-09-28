import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DOMWrapper, flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import EditProjectDialog from "./EditProjectDialog.vue";

const api = vi.hoisted(() => ({ get: vi.fn(), update: vi.fn(), pick: vi.fn(), confirm: vi.fn(), configGet: vi.fn(), configSave: vi.fn() }));
vi.mock("../api/projects", () => ({ fetchCodingProjectDetails: api.get, updateCodingProject: api.update }));
vi.mock("../../../api/tauri", () => ({ pickDirectory: api.pick }));
vi.mock("../../../stores/notifications", () => ({ useNotifications: () => ({ confirm: api.confirm }) }));
vi.mock("../api/observer", () => ({ fetchProjectObserverConfig: api.configGet, saveProjectObserverConfig: api.configSave }));
let wrapper: VueWrapper;
beforeEach(() => { vi.resetAllMocks(); api.get.mockResolvedValue({ id: 1, name: "原项目", root_path: "C:\\old" }); api.configGet.mockResolvedValue({ version: 0, enabled: false, checks: [] }); });
afterEach(() => { wrapper?.unmount(); });

async function open() {
  wrapper = mount(EditProjectDialog, { props: { projectId: 1 }, global: { stubs: { teleport: true } }, attachTo: document.body });
  await flushPromises();
  return wrapper;
}

describe("EditProjectDialog", () => {
  it("正式项目弹窗接入独立验收配置，保存检查期间阻止关闭或提交名称目录", async () => {
    // 使用真实 Teleport 验证子面板生命周期，避免插槽测试替身在父层更新时重建子组件。
    wrapper = mount(EditProjectDialog, { props: { projectId: 1 }, attachTo: document.body });
    await flushPromises();
    const body = new DOMWrapper(document.body);
    expect(api.configGet).toHaveBeenCalledWith(1, expect.any(AbortSignal));
    expect(body.findAll("form")).toHaveLength(1);
    await body.get('[data-testid="observer-config-enabled"]').setValue(true);
    await body.get('[data-testid="observer-config-add"]').trigger("click");
    await body.get('[data-testid="observer-check-scope"]').setValue("result.json");
    let resolveSave!: (value: unknown) => void;
    api.configSave.mockReturnValueOnce(new Promise(resolve => { resolveSave = resolve; }));
    await body.get('[data-testid="observer-config-save"]').trigger("click");
    await flushPromises();
    expect(api.configSave).toHaveBeenCalledOnce();
    expect(api.configGet).toHaveBeenCalledOnce();
    expect(body.get('[data-testid="edit-project-save"]').attributes("disabled")).toBeDefined();
    await body.get("form").trigger("submit");
    await body.get("form").trigger("keydown", { key: "Escape" });
    expect(api.update).not.toHaveBeenCalled();
    expect(wrapper.emitted("close")).toBeUndefined();
    resolveSave({ version: 1, enabled: true, checks: [{ id: "check-1", kind: "artifact", scope: "result.json" }] });
    await flushPromises();
    expect(body.text()).toContain("验收检查已保存");
    expect(body.get('[data-testid="edit-project-save"]').attributes("disabled")).toBeUndefined();
  });

  it("预填名称和目录，只改名称不重新授权", async () => {
    await open();
    expect(wrapper.get('[data-testid="edit-project-directory"]').text()).toContain("C:\\old");
    expect(document.activeElement).toBe(wrapper.get("input").element);
    await wrapper.get("input").setValue("  新名称  ");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(api.update).toHaveBeenCalledWith(1, { name: "新名称" });
    expect(api.confirm).not.toHaveBeenCalled();
    expect(wrapper.emitted("saved")).toHaveLength(1);
  });

  it("更换目录需要确认，取消保留表单，确认后提交授权和名称", async () => {
    await open();
    api.pick.mockResolvedValue("C:\\new");
    await wrapper.get('[data-testid="edit-project-directory"]').trigger("click");
    await flushPromises();
    api.confirm.mockResolvedValueOnce(false);
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(api.update).not.toHaveBeenCalled();
    expect(wrapper.emitted("saved")).toBeUndefined();
    api.confirm.mockResolvedValueOnce(true);
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(api.confirm).toHaveBeenCalledWith(expect.objectContaining({ danger: true, impact: expect.stringContaining("旧的完全访问授权") }));
    expect(api.update).toHaveBeenCalledWith(1, { name: "原项目", root_path: "C:\\new", authorize_scope: true });
  });

  it("空名称禁止保存，取消目录选择不修改路径", async () => {
    await open();
    api.pick.mockResolvedValue(null);
    await wrapper.get('[data-testid="edit-project-directory"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="edit-project-directory"]').text()).toContain("C:\\old");
    await wrapper.get("input").setValue(" ");
    expect(wrapper.get('[data-testid="edit-project-save"]').attributes("disabled")).toBeDefined();
    await wrapper.get("form").trigger("submit");
    expect(api.update).not.toHaveBeenCalled();
  });

  it("保存失败显示后端原因并保留编辑内容", async () => {
    await open();
    api.update.mockRejectedValueOnce({ message: "此目录已属于另一个项目" });
    await wrapper.get("input").setValue("修改后");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe("此目录已属于另一个项目");
    expect((wrapper.get("input").element as HTMLInputElement).value).toBe("修改后");
    expect(wrapper.emitted("saved")).toBeUndefined();
  });

  it("等待确认时禁止重复提交，卸载后不提交写入", async () => {
    await open();
    api.pick.mockResolvedValue("C:\\new");
    await wrapper.get('[data-testid="edit-project-directory"]').trigger("click");
    await flushPromises();
    let resolve: (accepted: boolean) => void = () => {};
    api.confirm.mockImplementation(() => new Promise((done) => { resolve = done; }));
    await wrapper.get("form").trigger("submit");
    await wrapper.get("form").trigger("submit");
    expect(api.confirm).toHaveBeenCalledOnce();
    wrapper.unmount();
    resolve(true);
    await flushPromises();
    expect(api.update).not.toHaveBeenCalled();
  });

  it("读取失败不允许保存，重试成功后可编辑", async () => {
    api.get.mockRejectedValueOnce({ message: "暂时不可用" });
    await open();
    expect(wrapper.get('[role="alert"]').text()).toBe("暂时不可用");
    expect(wrapper.get('[data-testid="edit-project-save"]').attributes("disabled")).toBeDefined();
    await wrapper.findAll("button").find((button) => button.text() === "重新读取")!.trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="edit-project-save"]').attributes("disabled")).toBeUndefined();
  });
});
