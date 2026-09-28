import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import ProjectObserverSettings from "./ProjectObserverSettings.vue";
import { fetchProjectObserverConfig, saveProjectObserverConfig, type ProjectObserverConfig } from "../api/observer";

vi.mock("../api/observer", () => ({ fetchProjectObserverConfig: vi.fn(), saveProjectObserverConfig: vi.fn() }));
let wrapper: VueWrapper;
const initial: ProjectObserverConfig = { version: 0, enabled: false, checks: [] };
const configured: ProjectObserverConfig = { version: 2, enabled: true, checks: [{ id: "artifact", kind: "artifact", scope: "dist/result.json" }] };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchProjectObserverConfig).mockResolvedValue(initial);
  vi.mocked(saveProjectObserverConfig).mockResolvedValue({ version: 1, enabled: true, checks: [{ id: "check-1", kind: "artifact", scope: "dist/result.json" }] });
});
afterEach(() => wrapper?.unmount());

async function open() {
  wrapper = mount(ProjectObserverSettings, { props: { projectId: 7 } });
  await flushPromises();
}

describe("项目验收检查", () => {
  it("默认关闭，编辑后独立保存版本与范围，不运行命令", async () => {
    await open();
    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.text()).toContain("不会自动执行命令");
    expect(wrapper.text()).toContain("项目根目录验收");
    expect(wrapper.get('[data-testid="observer-config-save"]').attributes("disabled")).toBeDefined();
    await wrapper.get('[data-testid="observer-config-enabled"]').setValue(true);
    expect(wrapper.text()).toContain("至少一项检查");
    await wrapper.get('[data-testid="observer-config-add"]').trigger("click");
    await wrapper.get('[data-testid="observer-check-scope"]').setValue(" dist/result.json ");
    await wrapper.get('[data-testid="observer-config-save"]').trigger("click");
    await flushPromises();
    expect(saveProjectObserverConfig).toHaveBeenCalledWith(7, { expected_version: 0, enabled: true, checks: [{ id: "check-1", kind: "artifact", scope: "dist/result.json" }] }, expect.any(AbortSignal));
    expect(wrapper.text()).toContain("配置 v1");
    expect(wrapper.text()).toContain("验收检查已保存");
    expect(wrapper.emitted("busy-change")).toEqual([[false], [true], [false]]);
  });

  it("无效或重复标识、空范围均阻止提交，并限制八项", async () => {
    await open();
    await wrapper.get('[data-testid="observer-config-add"]').trigger("click");
    await wrapper.get('[data-testid="observer-check-id"]').setValue("Invalid");
    await wrapper.get('[data-testid="observer-check-scope"]').setValue("file.txt");
    expect(wrapper.text()).toContain("以小写字母开头");
    expect(wrapper.get('[data-testid="observer-config-save"]').attributes("disabled")).toBeDefined();
    await wrapper.get('[data-testid="observer-check-id"]').setValue("artifact");
    await wrapper.get('[data-testid="observer-check-scope"]').setValue(" ");
    expect(wrapper.text()).toContain("1 至 1000");
    await wrapper.get('[data-testid="observer-check-scope"]').setValue("file.txt");
    await wrapper.get('[data-testid="observer-config-add"]').trigger("click");
    await wrapper.findAll('[data-testid="observer-check-id"]')[1].setValue("artifact");
    expect(wrapper.text()).toContain("不能重复");
    for (let index = 2; index < 8; index++) await wrapper.get('[data-testid="observer-config-add"]').trigger("click");
    expect(wrapper.findAll('[data-testid="observer-config-check"]')).toHaveLength(8);
    expect(wrapper.get('[data-testid="observer-config-add"]').attributes("disabled")).toBeDefined();
    expect(saveProjectObserverConfig).not.toHaveBeenCalled();
  });

  it("配置版本冲突保留草稿，必须显式重读后再编辑", async () => {
    vi.mocked(fetchProjectObserverConfig).mockResolvedValue(configured);
    vi.mocked(saveProjectObserverConfig).mockRejectedValueOnce({ status: 422, code: "observer_config_changed" });
    await open();
    await wrapper.get('[data-testid="observer-check-scope"]').setValue("draft.json");
    await wrapper.get('[data-testid="observer-config-save"]').trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("草稿已保留");
    expect((wrapper.get('[data-testid="observer-check-scope"]').element as HTMLTextAreaElement).value).toBe("draft.json");
    expect(wrapper.get('[data-testid="observer-config-save"]').attributes("disabled")).toBeDefined();
    vi.mocked(fetchProjectObserverConfig).mockResolvedValueOnce({ ...configured, version: 3 });
    await wrapper.get('[data-testid="observer-config-reload"]').trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("配置 v3");
    expect((wrapper.get('[data-testid="observer-check-scope"]').element as HTMLTextAreaElement).value).toBe("dist/result.json");
    expect(saveProjectObserverConfig).toHaveBeenCalledOnce();
  });

  it("保存未确认时不丢草稿，重复点击和禁用状态不产生第二次请求", async () => {
    vi.mocked(fetchProjectObserverConfig).mockResolvedValue(configured);
    let rejectSave!: (cause: unknown) => void;
    vi.mocked(saveProjectObserverConfig).mockReturnValueOnce(new Promise((_resolve, reject) => { rejectSave = reject; }));
    await open();
    await wrapper.get('[data-testid="observer-check-scope"]').setValue("changed.json");
    await wrapper.get('[data-testid="observer-config-save"]').trigger("click");
    await wrapper.get('[data-testid="observer-config-save"]').trigger("click");
    expect(saveProjectObserverConfig).toHaveBeenCalledOnce();
    expect(wrapper.get('[data-testid="observer-config-reload"]').attributes("disabled")).toBeDefined();
    rejectSave(new Error("private backend error"));
    await flushPromises();
    expect(wrapper.text()).toContain("保存未确认");
    expect(wrapper.text()).not.toContain("private backend error");
    expect((wrapper.get('[data-testid="observer-check-scope"]').element as HTMLTextAreaElement).value).toBe("changed.json");
    await wrapper.setProps({ disabled: true });
    expect(wrapper.get('[data-testid="observer-config-save"]').attributes("disabled")).toBeDefined();
  });

  it("切换项目取消旧读取并拒绝迟到配置，卸载释放请求", async () => {
    let resolveOld!: (value: ProjectObserverConfig) => void;
    vi.mocked(fetchProjectObserverConfig).mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
    wrapper = mount(ProjectObserverSettings, { props: { projectId: 7 } });
    const oldSignal = vi.mocked(fetchProjectObserverConfig).mock.calls[0][1];
    vi.mocked(fetchProjectObserverConfig).mockResolvedValueOnce({ ...configured, version: 8 });
    await wrapper.setProps({ projectId: 8 });
    await flushPromises();
    resolveOld(initial);
    await flushPromises();
    expect(oldSignal?.aborted).toBe(true);
    expect(wrapper.text()).toContain("配置 v8");
    const signal = vi.mocked(fetchProjectObserverConfig).mock.calls[1][1];
    wrapper.unmount();
    expect(signal?.aborted).toBe(true);
  });

  it("读取失败可重试，独立输入 Enter 不提交外层表单", async () => {
    vi.mocked(fetchProjectObserverConfig).mockRejectedValueOnce(new Error("network"));
    await open();
    expect(wrapper.text()).toContain("读取失败");
    expect(wrapper.get('[data-testid="observer-config-save"]').attributes("disabled")).toBeDefined();
    vi.mocked(fetchProjectObserverConfig).mockResolvedValueOnce(configured);
    await wrapper.get('[data-testid="observer-config-reload"]').trigger("click");
    await flushPromises();
    const event = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    wrapper.get('[data-testid="observer-check-id"]').element.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(saveProjectObserverConfig).not.toHaveBeenCalled();
  });

  it("后端拒绝检查范围时显示校验失败，保留草稿供修正", async () => {
    vi.mocked(fetchProjectObserverConfig).mockResolvedValue(configured);
    vi.mocked(saveProjectObserverConfig).mockRejectedValueOnce({ status: 422, code: "unknown", message: "private error" });
    await open();
    await wrapper.get('[data-testid="observer-check-scope"]').setValue("/outside/result.json");
    await wrapper.get('[data-testid="observer-config-save"]').trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("未通过校验");
    expect(wrapper.text()).not.toContain("保存未确认");
    expect(wrapper.text()).not.toContain("private error");
    expect((wrapper.get('[data-testid="observer-check-scope"]').element as HTMLTextAreaElement).value).toBe("/outside/result.json");
  });
});
