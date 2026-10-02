import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import MemoryEvidence from "./MemoryEvidence.vue";
import * as api from "../api/memories";

vi.mock("../api/memories", () => ({ memorySource: vi.fn(), memoryRevisions: vi.fn() }));
beforeEach(() => vi.resetAllMocks());

it("按来源分页显示公开原文并携带项目与消息定位事件", async () => {
  vi.mocked(api.memorySource).mockResolvedValue({ item_id: "source", content: '{"content":"请记住中文"}', offset: 0, next_offset: null, total_chars: 20, session_id: 11, project_id: 7, message_id: 5, run_id: "run" });
  const wrapper = mount(MemoryEvidence, { props: { memoryId: "m", projectId: 7, sourceItemIds: ["source"] } });
  await wrapper.get("button").trigger("click");
  await flushPromises();
  expect(wrapper.get("pre").text()).toBe("请记住中文");
  await wrapper.findAll("button").find(button => button.text() === "打开来源会话")!.trigger("click");
  expect(wrapper.emitted("open-source")).toEqual([[{ projectId: 7, sessionId: 11, messageId: 5 }]]);
  const signal = vi.mocked(api.memorySource).mock.calls[0][4];
  wrapper.unmount();
  expect(signal.aborted).toBe(true);
});

it("切换记忆后旧来源响应不能覆盖当前内容", async () => {
  let complete: (value: api.MemorySource) => void = () => {};
  vi.mocked(api.memorySource).mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
  const wrapper = mount(MemoryEvidence, { props: { memoryId: "old", projectId: 7, sourceItemIds: ["source"] } });
  await wrapper.get("button").trigger("click");
  await wrapper.setProps({ memoryId: "new" });
  complete({ item_id: "source", content: "旧数据", offset: 0, next_offset: null, total_chars: 3, session_id: 11, project_id: 7, message_id: 5, run_id: "run" });
  await flushPromises();
  expect(wrapper.text()).not.toContain("旧数据");
  wrapper.unmount();
});
