import { describe, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import AgentWorkspace from "./AgentWorkspace.vue";
import type { AgentWorkspaceMessage } from "../../models/agentWorkspace";
import type { AgentTaskState } from "../../types";

function userMsg(content: string, id = 1): AgentWorkspaceMessage {
  return {
    id,
    session_id: 1,
    role: "user",
    content,
    created_at: new Date().toISOString(),
    clientKey: `u-${id}`,
  };
}

function agentMsg(content: string, id = 2): AgentWorkspaceMessage {
  return {
    id,
    session_id: 1,
    role: "assistant",
    content,
    created_at: new Date().toISOString(),
    clientKey: `a-${id}`,
  };
}

async function mountWorkspace() {
  const wrapper = mount(AgentWorkspace, {
    props: {
      messages: [] as AgentWorkspaceMessage[],
      streaming: false,
      knowledgeBase: false,
      pendingTool: false,
      taskState: "idle" as AgentTaskState,
    },
    attachTo: document.body,
  });
  stubScroll(wrapper);
  return wrapper;
}

/** jsdom 的 Element 无 scrollTo：为滚动容器注入桩，避免跟随逻辑报未处理异常。 */
function stubScroll(wrapper: ReturnType<typeof mount>) {
  const el = wrapper.find(".agent-scroll").element as HTMLElement;
  Object.defineProperty(el, "scrollTo", { value: vi.fn(), configurable: true });
}

describe("AgentWorkspace", () => {
  it("空任务渲染空状态与引导提示", () => {
    const wrapper = mount(AgentWorkspace, {
      props: { messages: [], streaming: false, knowledgeBase: false },
    });
    expect(wrapper.find('[data-testid="feed-empty"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="task-composer"]').exists()).toBe(true);
  });

  it("发送消息事件透传并清空输入", async () => {
    const wrapper = await mountWorkspace();
    const input = wrapper.find('[data-testid="task-composer-input"]');
    await input.setValue("帮我整理进展");
    await wrapper.find('[data-testid="task-composer-submit"]').trigger("click");
    expect(wrapper.emitted("send")?.[0]).toEqual(["帮我整理进展"]);
  });

  it("流式时停止按钮出现，点击后进入「正在停止…」并发出 stop", async () => {
    const wrapper = await mountWorkspace();
    await wrapper.setProps({ messages: [userMsg("x"), agentMsg("y")], streaming: true });
    const stop = wrapper.find('[data-testid="task-composer-stop"]');
    expect(stop.exists()).toBe(true);
    await stop.trigger("click");
    expect(wrapper.emitted("stop")).toBeTruthy();
    expect(stop.text()).toContain("正在停止…");
  });

  it("停止请求结束后恢复输入并短暂显示「已停止」", async () => {
    vi.useFakeTimers();
    const wrapper = await mountWorkspace();
    await wrapper.setProps({ messages: [userMsg("x"), agentMsg("y")], streaming: true });
    await wrapper.find('[data-testid="task-composer-stop"]').trigger("click");
    await wrapper.setProps({ streaming: false });
    // 「正在停止…」至少呈现 700ms 后转为「已停止」
    await vi.advanceTimersByTimeAsync(700);
    expect(wrapper.text()).toContain("已停止本轮生成");
    await vi.advanceTimersByTimeAsync(4100);
    expect(wrapper.text()).not.toContain("已停止本轮生成");
    vi.useRealTimers();
  });

  it("计划步骤可点击定位活动（滚动到对应条目）", async () => {
    const wrapper = await mountWorkspace();
    await wrapper.setProps({
      messages: [userMsg("分析项目目录"), agentMsg("已读取目录结构")],
      streaming: false,
    });
    const scrollEl = wrapper.find(".agent-scroll").element as HTMLElement;
    const scrollSpy = vi.fn();
    Object.defineProperty(scrollEl, "scrollTo", { value: scrollSpy, configurable: true });
    const step = wrapper.findAll(".plan-step-hit")[0];
    await step.trigger("click");
    await flushPromises();
    expect(scrollSpy).toHaveBeenCalled();
  });

  it("离开底部时出现「有新活动」入口，点击后消失", async () => {
    const wrapper = await mountWorkspace();
    await wrapper.setProps({ messages: [userMsg("a")] });
    const scrollEl = wrapper.find(".agent-scroll").element as HTMLElement;
    Object.defineProperty(scrollEl, "scrollHeight", { value: 2000 });
    Object.defineProperty(scrollEl, "clientHeight", { value: 600 });
    Object.defineProperty(scrollEl, "scrollTop", { value: 200 });
    Object.defineProperty(scrollEl, "scrollTo", { value: vi.fn(), configurable: true });
    scrollEl.dispatchEvent(new Event("scroll"));
    await flushPromises();
    await wrapper.setProps({ messages: [userMsg("a"), agentMsg("新内容")] });
    await flushPromises();
    expect(wrapper.find('[data-testid="new-activity-pill"]').exists()).toBe(true);
    await wrapper.find('[data-testid="new-activity-pill"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="new-activity-pill"]').exists()).toBe(false);
  });
});
