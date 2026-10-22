import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MemorySettingsPanel from "./MemorySettingsPanel.vue";
import * as api from "../api/memories";

vi.mock("../api/memories", () => ({ memorySettings: vi.fn(), memoryStatus: vi.fn(), memoryProjects: vi.fn(),
  memoryItems: vi.fn(), saveMemorySettings: vi.fn(), createMemory: vi.fn(), editMemory: vi.fn(), forgetMemory: vi.fn(),
  reviewMemory: vi.fn(), searchMemories: vi.fn(), memoryRevisions: vi.fn(), memorySource: vi.fn() }));
vi.mock("../features/coding/api/modelProfiles", () => ({ fetchCodingModelProfiles: vi.fn().mockResolvedValue({ status: "ok", profiles: [] }) }));
const confirm = vi.hoisted(() => vi.fn());
vi.mock("../stores/notifications", () => ({ useNotifications: () => ({ confirm }) }));
const config: api.MemorySettings = { enabled: false, use_memories: true, generate_memories: true, exclude_external_context: true,
  model_profile_id: null, idle_seconds: 300, max_calls_per_day: 12, version: 1, generation_since: "" };
const item: api.MemoryItem = { id: "memory", project_id: null, title: "语言", content: "中文回答", scope: "user", kind: "preference",
  version: 1, origin: "user", updated_at: "", source_session_id: null, source_item_ids: [] };
/** 组件根与局部区域都能按文本查找按钮。 */
type ButtonHost = { findAll: (selector: string) => Array<{ text: () => string; trigger: (event: string) => Promise<unknown> }> };
function button(wrapper: ButtonHost, text: string) {
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

  it("默认管理当前项目并标明迁移的历史自动记忆", async () => {
    vi.mocked(api.memoryItems).mockResolvedValue([{ ...item, origin: "generated", legacy: true }]);
    const wrapper = mount(MemorySettingsPanel, { props: { initialProjectId: 7 } });
    await flushPromises();
    expect(api.memoryItems).toHaveBeenCalledWith(7, expect.any(AbortSignal));
    expect(wrapper.get<HTMLSelectElement>('form[aria-label="编辑记忆"] select').element.value).toBe("project");
    expect(wrapper.text()).toContain("历史自动记忆");
    wrapper.unmount();
  });

  it("工作区项目迟到时采用项目默认范围，已有输入不被切换", async () => {
    const wrapper = mount(MemorySettingsPanel, { props: { initialProjectId: null } });
    await flushPromises();
    await wrapper.setProps({ initialProjectId: 7 });
    await flushPromises();
    expect(api.memoryItems).toHaveBeenLastCalledWith(7, expect.any(AbortSignal));
    const editor = wrapper.get('form[aria-label="编辑记忆"]');
    expect(editor.get('select').element.value).toBe("project");
    await editor.get('input').setValue("还未保存的标题");
    await wrapper.setProps({ initialProjectId: null });
    await flushPromises();
    expect(editor.get('input').element.value).toBe("还未保存的标题");
    expect(editor.get('select').element.value).toBe("project");
    wrapper.unmount();
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
    const editor = wrapper.get('form[aria-label="编辑记忆"]');
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

  it("待复核内容确认后刷新，编辑冲突保留用户输入", async () => {
    vi.mocked(api.memoryItems).mockResolvedValueOnce([{ ...item, status: "pending_review", review_reason: "volatile" }]).mockResolvedValue([{ ...item, status: "active", version: 2 }]);
    vi.mocked(api.reviewMemory).mockResolvedValue({ ...item, status: "active", version: 2 });
    const wrapper = mount(MemorySettingsPanel);
    await flushPromises();
    expect(wrapper.text()).toContain("当前列表有 1 条待复核记忆");
    await button(wrapper, "确认使用").trigger("click");
    await flushPromises();
    expect(api.reviewMemory).toHaveBeenCalledWith(null, expect.objectContaining({ version: 1 }), "accept", expect.any(AbortSignal));
    expect(wrapper.text()).not.toContain("当前列表有 1 条待复核记忆");
    await button(wrapper, "编辑").trigger("click");
    const editor = wrapper.get('form[aria-label="编辑记忆"]');
    await editor.get("textarea").setValue("用户刚输入的纠正");
    vi.mocked(api.editMemory).mockRejectedValueOnce(new Error("记忆已变化，请刷新后重新编辑"));
    await editor.trigger("submit");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("记忆已变化");
    expect(editor.get<HTMLTextAreaElement>("textarea").element.value).toBe("用户刚输入的纠正");
    wrapper.unmount();
  });

  it("同主题对照并列展示当前条目与新候选，操作沿用既有复核接口", async () => {
    const previous = { ...item, id: "old", title: "发布流程", content: "先合并后发布", version: 3,
      updated_at: "2026-10-01T00:00:00Z", topic_key: "topic:release", status: "active" as const };
    const candidate = { ...item, id: "new", title: "发布流程", content: "先发布后合并", version: 1, origin: "generated" as const,
      status: "pending_review" as const, review_reason: "conflict", updated_at: "2026-10-02T00:00:00Z",
      supersedes_id: "old", supersedes_version: 3, topic_key: "topic:release",
      source_item_ids: ["item-1", "item-2"], source_session_id: 11 };
    vi.mocked(api.memoryItems).mockResolvedValue([previous, candidate]);
    vi.mocked(api.reviewMemory).mockResolvedValue({ ...candidate, status: "active", version: 2 });
    const wrapper = mount(MemorySettingsPanel);
    await flushPromises();
    const compare = wrapper.get('[data-testid="memory-conflicts"]');
    expect(compare.text()).toContain("当前条目");
    expect(compare.text()).toContain("新候选");
    expect(compare.text()).toContain("先合并后发布");
    expect(compare.text()).toContain("先发布后合并");
    expect(compare.text()).toContain("版本 3");
    expect(compare.text()).toContain("自动提取");
    // 来源只作为可追溯引用展示，不宣称已验证。
    expect(compare.text()).toContain("新候选有 2 个会话来源");
    expect(compare.text()).not.toContain("已验证");
    await button(compare, "采用新值").trigger("click");
    await flushPromises();
    expect(api.reviewMemory).toHaveBeenCalledWith(null, expect.objectContaining({ id: "new" }), "accept", expect.any(AbortSignal));
    wrapper.unmount();
  });

  it("疑似重复按主题、标题与正文分组提示，不自动合并", async () => {
    const first = { ...item, id: "a", title: "语言偏好", content: "默认中文", topic_key: "topic:lang", updated_at: "2026-10-01" };
    const second = { ...item, id: "b", title: "语言偏好 ", content: "默认英文", topic_key: "topic:lang2", updated_at: "2026-10-02" };
    const third = { ...item, id: "c", title: "提交前测试", content: "默认中文", topic_key: "topic:test", updated_at: "2026-10-03" };
    const unrelated = { ...item, id: "d", title: "构建目录", content: "产物在 dist", topic_key: "topic:build" };
    // 同标题但不同 scope：跨项目偏好与项目事实不误合并。
    const crossProject = { ...item, id: "e", scope: "user" as const, title: "语言偏好", content: "默认中文", topic_key: "topic:lang" };
    vi.mocked(api.memoryItems).mockResolvedValue([first, second, third, unrelated, crossProject]);
    const wrapper = mount(MemorySettingsPanel);
    await flushPromises();
    const panel = wrapper.get('[data-testid="memory-duplicates"]');
    // 规范化标题相同（忽略末尾空格）与规范化正文相同各成一组。
    expect(panel.text()).toContain("规范化标题相同");
    expect(panel.text()).toContain("规范化正文相同");
    expect(panel.findAll("details").length).toBeGreaterThanOrEqual(2);
    // 不相关条目不成组；跨 scope 的同名条目不与项目条目合并。
    expect(panel.text()).not.toContain("构建目录");
    expect(panel.findAll("details").every(group => !group.text().includes("跨项目偏好"))).toBe(true);
    expect(api.editMemory).not.toHaveBeenCalled();
    expect(api.forgetMemory).not.toHaveBeenCalled();
    expect(api.createMemory).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("状态筛选只影响展示，无来源条目不显示为已验证", async () => {
    const active = { ...item, id: "active", title: "当前约定", status: "active" as const,
      source_item_ids: ["item-9"], source_updated_at: "2026-10-01T00:00:00Z" };
    const stale = { ...item, id: "stale", title: "过时约定", status: "stale" as const };
    vi.mocked(api.memoryItems).mockResolvedValue([active, stale]);
    const wrapper = mount(MemorySettingsPanel);
    await flushPromises();
    expect(wrapper.text()).toContain("当前约定");
    expect(wrapper.text()).toContain("过时约定");
    expect(wrapper.text()).toContain("来源时间 2026-10-01T00:00:00Z");
    expect(wrapper.text()).toContain("无会话来源（可能由设置页手动创建），不显示为已验证");
    await wrapper.get('[data-testid="memory-status-filter"]').setValue("stale");
    await flushPromises();
    expect(wrapper.text()).toContain("过时约定");
    expect(wrapper.text()).not.toContain("当前约定");
    // 筛选不写入数据、不改变条目状态。
    expect(api.reviewMemory).not.toHaveBeenCalled();
    expect(api.editMemory).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
