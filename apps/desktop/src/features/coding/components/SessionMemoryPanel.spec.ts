import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import SessionMemoryPanel from "./SessionMemoryPanel.vue";
import * as api from "../../../api/memories";

vi.mock("../../../api/memories", () => ({ sessionMemorySettings: vi.fn(), saveSessionMemorySettings: vi.fn(), memorySource: vi.fn(), memoryRevisions: vi.fn(), memoryItem: vi.fn(), editMemory: vi.fn(), forgetMemory: vi.fn() }));
const confirm = vi.hoisted(() => vi.fn());
vi.mock("../../../stores/notifications", () => ({ useNotifications: () => ({ confirm }) }));
const state: api.SessionMemorySettings = { version: 1, use_memories: true, generate_memories: true,
  effective_use: false, effective_generate: false, last_recall: { recalled_ids: ["memory"], omitted_ids: [] } };
beforeEach(() => { vi.resetAllMocks(); vi.mocked(api.sessionMemorySettings).mockResolvedValue({ ...state }); });

it("区分全局生效状态与会话选项，保留未保存的编辑", async () => {
  const wrapper = mount(SessionMemoryPanel, { props: { sessionId: 7, revision: 1 } });
  await flushPromises();
  expect(wrapper.text()).toContain("使用关 · 生成关");
  expect(wrapper.text()).toContain("引用 1 条");
  await wrapper.find('input').setValue(false);
  await wrapper.setProps({ revision: 2 });
  await flushPromises();
  expect(api.sessionMemorySettings).toHaveBeenCalledTimes(1);
  vi.mocked(api.saveSessionMemorySettings).mockResolvedValue({ ...state, use_memories: false, version: 2 });
  await wrapper.find('button').trigger('click');
  await flushPromises();
  expect(api.saveSessionMemorySettings).toHaveBeenCalledWith(7, expect.objectContaining({ use_memories: false, version: 1 }), expect.any(AbortSignal));
  wrapper.unmount();
});

it("切换会话和卸载使旧响应失效", async () => {
  let resolve: (value: api.SessionMemorySettings) => void = () => {};
  vi.mocked(api.sessionMemorySettings).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  const wrapper = mount(SessionMemoryPanel, { props: { sessionId: 7 } });
  await wrapper.setProps({ sessionId: 8 });
  await flushPromises();
  resolve({ ...state, effective_use: true });
  await flushPromises();
  expect(wrapper.text()).toContain("使用关");
  const calls = vi.mocked(api.sessionMemorySettings).mock.calls;
  expect(calls[0][1].aborted).toBe(true);
  wrapper.unmount();
  expect(calls[1][1].aborted).toBe(true);
});

it("展示逐条命中和预算省略原因，遗忘记录不再提供正文入口", async () => {
  vi.mocked(api.sessionMemorySettings).mockResolvedValue({ ...state, last_recall: { recalled_ids: [], omitted_ids: ["m"], entries: [{ memory_id: "m", version: 1, scope: "project", title: "语言", matched_terms: ["中文"], source_session_id: 11, source_item_ids: [], decision: "omitted", reason: "context_budget", available: false }] } });
  const wrapper = mount(SessionMemoryPanel, { props: { sessionId: 7 } });
  await flushPromises();
  expect(wrapper.text()).toContain("上下文预算不足：中文");
  expect(wrapper.find("details").exists()).toBe(false);
  wrapper.unmount();
});

it("本轮条目就地编辑，409 保留草稿，遗忘停止后续引用", async () => {
  const item: api.MemoryItem = { id: "m", project_id: 3, version: 3, title: "语言", content: "中文", scope: "project", kind: "preference", origin: "user", updated_at: "", source_session_id: null, source_item_ids: [] };
  vi.mocked(api.sessionMemorySettings).mockResolvedValue({ ...state, last_recall: { recalled_ids: ["m"], omitted_ids: [], entries: [{ memory_id: "m", version: 1, scope: "project", project_id: 3, title: "语言", updated_at: "2026-01-01", matched_terms: ["中文"], source_session_id: null, source_item_ids: [], decision: "included", reason: "keyword_match" }] } });
  vi.mocked(api.memoryItem).mockResolvedValue(item);
  const wrapper = mount(SessionMemoryPanel, { props: { sessionId: 7 } });
  const button = (name: string) => wrapper.findAll("button").find(node => node.text() === name)!;
  await flushPromises();
  await button("编辑此条").trigger("click");
  await flushPromises();
  expect(api.memoryItem).toHaveBeenCalledWith(3, "m", expect.any(AbortSignal));
  expect(wrapper.text()).toContain("本轮引用版本 1；正在编辑最新版本 3");
  await wrapper.get('form[aria-label="编辑本轮记忆"] textarea').setValue("保留未提交内容");
  vi.mocked(api.editMemory).mockRejectedValueOnce(new Error("记忆已变化，请刷新后重新编辑"));
  await wrapper.get('form').trigger("submit");
  await flushPromises();
  expect(wrapper.get('textarea').element.value).toBe("保留未提交内容");
  expect(wrapper.get('[role="alert"]').text()).toContain("未提交的编辑已保留");
  vi.mocked(api.editMemory).mockResolvedValueOnce({ ...item, content: "保留未提交内容", version: 4 });
  await wrapper.get('form').trigger("submit");
  await flushPromises();
  expect(api.editMemory).toHaveBeenLastCalledWith(3, item, expect.objectContaining({ content: "保留未提交内容" }), expect.any(AbortSignal));
  expect(wrapper.text()).toContain("本轮引用版本 1 · 更新时间 2026-01-01");
  expect(wrapper.text()).toContain("从下一次请求起使用新内容");
  vi.mocked(api.memoryItem).mockResolvedValue({ ...item, version: 4 });
  confirm.mockResolvedValueOnce(true);
  await button("遗忘此条").trigger("click");
  await flushPromises();
  expect(confirm.mock.calls[0][0].impact).toContain("会话原文和本轮历史引用记录保持不变");
  expect(api.forgetMemory).toHaveBeenCalledWith(3, expect.objectContaining({ id: "m", version: 4 }), expect.any(AbortSignal));
  expect(wrapper.text()).toContain("该记忆已遗忘或不可用");
  expect(wrapper.find('form').exists()).toBe(false);
  wrapper.unmount();
});

it("切换会话使就地编辑的迟到读取失效", async () => {
  vi.mocked(api.sessionMemorySettings).mockResolvedValueOnce({ ...state, last_recall: { recalled_ids: ["m"], omitted_ids: [], entries: [{ memory_id: "m", version: 1, scope: "project", project_id: 3, matched_terms: [], source_session_id: null, source_item_ids: [], decision: "included", reason: "manual_reference" }] } });
  let resolve: (item: api.MemoryItem) => void = () => {};
  vi.mocked(api.memoryItem).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  const wrapper = mount(SessionMemoryPanel, { props: { sessionId: 7 } });
  await flushPromises();
  await wrapper.findAll("button").find(node => node.text() === "编辑此条")!.trigger("click");
  await wrapper.setProps({ sessionId: 8 });
  resolve({ id: "m", title: "旧会话", content: "不能显示" } as api.MemoryItem);
  await flushPromises();
  expect(api.memoryItem).toHaveBeenCalledWith(3, "m", expect.objectContaining({ aborted: true }));
  expect(wrapper.text()).not.toContain("旧会话");
  wrapper.unmount();
});
