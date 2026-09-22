import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MemorySettingsPanel from "./MemorySettingsPanel.vue";
import * as api from "../api/memories";

vi.mock("../api/memories", () => ({ memorySettings: vi.fn(), memoryStatus: vi.fn(), memoryProjects: vi.fn(),
  memoryItems: vi.fn(), saveMemorySettings: vi.fn(), createMemory: vi.fn(), editMemory: vi.fn(), forgetMemory: vi.fn() }));
vi.mock("../features/coding/api/modelProfiles", () => ({ fetchCodingModelProfiles: vi.fn().mockResolvedValue({ status: "ok", profiles: [] }) }));
const confirm = vi.hoisted(() => vi.fn());
vi.mock("../stores/notifications", () => ({ useNotifications: () => ({ confirm }) }));
const config: api.MemorySettings = { enabled: false, use_memories: true, generate_memories: true, exclude_external_context: true,
  model_profile_id: null, idle_seconds: 300, max_calls_per_day: 12, version: 1, generation_since: "" };
const item: api.MemoryItem = { id: "memory", project_id: null, title: "语言", content: "中文回答", scope: "user", kind: "preference",
  version: 1, origin: "user", updated_at: "", source_session_id: null, source_item_ids: [] };
function button(wrapper: ReturnType<typeof mount>, text: string) {
  return wrapper.findAll("button").find(node => node.text() === text)!;
}

describe("本机记忆设置", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.memorySettings).mockResolvedValue({ ...config });
    vi.mocked(api.memoryStatus).mockResolvedValue({ calls_today: 0, worker_running: false, error: null, last_attempt: null });
    vi.mocked(api.memoryProjects).mockResolvedValue([{ id: 7, name: "项目甲" }]);
    vi.mocked(api.memoryItems).mockResolvedValue([]);
    confirm.mockResolvedValue(true);
  });

  it("开启自动生成前说明模型费用，取消不保存，确认后携带版本保存", async () => {
    const wrapper = mount(MemorySettingsPanel);
    await flushPromises();
    expect(wrapper.text()).toContain("此范围暂无记忆");
    await wrapper.find('input[type="checkbox"]').setValue(true);
    confirm.mockResolvedValueOnce(false);
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    expect(confirm.mock.calls[0][0].message).toContain("费用");
    expect(api.saveMemorySettings).not.toHaveBeenCalled();
    vi.mocked(api.saveMemorySettings).mockResolvedValue({ ...config, enabled: true, version: 2 });
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    expect(api.saveMemorySettings).toHaveBeenCalledWith(expect.objectContaining({ enabled: true }), 1, expect.any(AbortSignal));
    expect(wrapper.text()).toContain("记忆设置已保存");
    wrapper.unmount();
  });

  it("支持添加、编辑、遗忘，拒绝遗忘时保留原记录", async () => {
    vi.mocked(api.createMemory).mockResolvedValue(item);
    vi.mocked(api.editMemory).mockResolvedValue({ ...item, content: "先中文再英文", version: 2 });
    const wrapper = mount(MemorySettingsPanel);
    await flushPromises();
    const editor = wrapper.findAll("form")[1];
    await editor.get('input').setValue("语言");
    await editor.get('textarea').setValue("中文回答");
    await editor.trigger("submit");
    await flushPromises();
    expect(wrapper.find("article").text()).toContain("中文回答");
    await button(wrapper, "编辑").trigger("click");
    await editor.get('textarea').setValue("先中文再英文");
    await editor.trigger("submit");
    await flushPromises();
    expect(api.editMemory).toHaveBeenCalledWith(null, item, expect.objectContaining({ content: "先中文再英文" }), expect.any(AbortSignal));
    confirm.mockResolvedValueOnce(false);
    await button(wrapper, "遗忘").trigger("click");
    await flushPromises();
    expect(api.forgetMemory).not.toHaveBeenCalled();
    await button(wrapper, "遗忘").trigger("click");
    await flushPromises();
    expect(api.forgetMemory).toHaveBeenCalledWith(null, expect.objectContaining({ version: 2 }), expect.any(AbortSignal));
    expect(wrapper.find("article").exists()).toBe(false);
    wrapper.unmount();
  });

  it("项目切换清空旧内容，版本冲突可见，卸载取消请求", async () => {
    vi.mocked(api.memoryItems).mockResolvedValueOnce([item]).mockResolvedValueOnce([]);
    const wrapper = mount(MemorySettingsPanel);
    await flushPromises();
    const scope = wrapper.find('section[aria-label="管理长期记忆"] > label select');
    await scope.setValue(7);
    await flushPromises();
    expect(api.memoryItems).toHaveBeenLastCalledWith(7, expect.any(AbortSignal));
    expect(wrapper.find("article").exists()).toBe(false);
    vi.mocked(api.saveMemorySettings).mockRejectedValueOnce(new Error("记忆设置已变化，请刷新后重试"));
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("已变化");
    const signal = vi.mocked(api.saveMemorySettings).mock.calls[0][2];
    wrapper.unmount();
    expect(signal.aborted).toBe(true);
  });

  it("卸载后的确认不能开启付费后台调用", async () => {
    let resolve: (value: boolean) => void = () => {};
    confirm.mockImplementationOnce(() => new Promise<boolean>(done => { resolve = done; }));
    const wrapper = mount(MemorySettingsPanel);
    await flushPromises();
    await wrapper.find('input[type="checkbox"]').setValue(true);
    await wrapper.find("form").trigger("submit");
    wrapper.unmount();
    resolve(true);
    await flushPromises();
    expect(api.saveMemorySettings).not.toHaveBeenCalled();
  });
});
