import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import SessionMemoryPanel from "./SessionMemoryPanel.vue";
import * as api from "../../../api/memories";

vi.mock("../../../api/memories", () => ({ sessionMemorySettings: vi.fn(), saveSessionMemorySettings: vi.fn() }));
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
