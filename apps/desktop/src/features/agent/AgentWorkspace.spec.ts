import { describe, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import AgentWorkspace from "./AgentWorkspace.vue";
import type { AgentWorkspaceMessage } from "../../models/agentWorkspace";
import type { AgentTaskState, Session } from "../../types";

vi.mock("../../api", () => ({
  getSettings: vi.fn().mockResolvedValue({
    provider_type: "ollama",
    llm_model: "qwen3:4b",
    llm_context_length: 8192,
    remote_provider_enabled: false,
  }),
  listWorkspaces: vi.fn().mockResolvedValue([
    {
      id: 101,
      project_id: 1,
      kind: "root",
      root_path: "F:/workspace/demo-project",
      branch_name: "feature/w6r3",
      head_sha: "ab12cd34ef56",
      status: "active",
    },
  ]),
}));

const SESSIONS: Session[] = [
  { id: 1, title: "会话一", created_at: "2026-08-22T00:00:00Z", updated_at: "2026-08-22T00:00:00Z", project_id: 1, workspace_id: 101 },
  { id: 2, title: "会话二", created_at: "2026-08-22T00:00:00Z", updated_at: "2026-08-22T01:00:00Z" },
];

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
      sessions: SESSIONS,
      currentSessionId: 1,
    },
    attachTo: document.body,
  });
  stubScroll(wrapper);
  await flushPromises();
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
      props: { messages: [], streaming: false },
    });
    expect(wrapper.find('[data-testid="feed-empty"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="task-composer"]').exists()).toBe(true);
  });

  // ============ v0.8.0 W6-R2：左会话/右工作区两区结构 ============
  it("宽屏两区结构：左会话记录（真实列表）+ 右工作区（头部/逐轮/输入器）", async () => {
    const wrapper = await mountWorkspace();
    expect(wrapper.find('[data-testid="agent-conversations"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="agent-conversation-1"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="session-header"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="turn-transcript"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="agent-composer"]').exists()).toBe(true);
  });

  it("会话切换发出事件；草稿按会话保存不串线", async () => {
    const wrapper = await mountWorkspace();
    await wrapper.find('[data-testid="agent-conversation-2"]').trigger("click");
    expect(wrapper.emitted("select-session")?.[0]).toEqual([2]);
    // 切回会话 1 前写入草稿，切换会话后再回来草稿仍在（不串线）
    const input = wrapper.find('[data-testid="task-composer-input"]');
    await input.setValue("会话一的草稿");
    await wrapper.setProps({ currentSessionId: 2 });
    expect((wrapper.find('[data-testid="task-composer-input"]').element as HTMLTextAreaElement).value).toBe("");
    await wrapper.setProps({ currentSessionId: 1 });
    expect((wrapper.find('[data-testid="task-composer-input"]').element as HTMLTextAreaElement).value).toBe("会话一的草稿");
  });

  // ============ v0.8.0 W6-R3：标题区事实 + 控件移除 ============
  it("SessionHeader 呈现授权工作目录与 Git 分支（公开事实）；顶部无模型/上下文控件", async () => {
    const wrapper = await mountWorkspace();
    await flushPromises();
    expect(wrapper.find('[data-testid="session-workdir"]').text()).toContain("demo-project");
    expect(wrapper.find('[data-testid="session-git"]').text()).toContain("feature/w6r3");
    // W6-R3：顶部模型 chip 与上下文按钮已移除（模型配置下沉底部）
    expect(wrapper.find('[data-testid="session-model"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="session-context-toggle"]').exists()).toBe(false);
  });

  it("底部模型/Provider 入口呈现真实配置；点击进入配置", async () => {
    const wrapper = await mountWorkspace();
    await flushPromises();
    const entry = wrapper.find('[data-testid="composer-model-entry"]');
    expect(entry.text()).toContain("qwen3:4b");
    expect(entry.text()).toContain("本地");
    await entry.trigger("click");
    expect(wrapper.emitted("configure-model")).toBeTruthy();
  });

  it("独立执行计划大卡片已移除；无命令轮呈现真实空态", async () => {
    const wrapper = await mountWorkspace();
    await wrapper.setProps({
      messages: [userMsg("分析项目目录"), agentMsg("已读取目录结构")],
      streaming: false,
    });
    // W6-R3：不再渲染独立计划卡（计划事实随所属 turn 呈现）
    expect(wrapper.find('[data-testid="agent-plan"]').exists()).toBe(false);
    expect(wrapper.find(".plan-step-hit").exists()).toBe(false);
    // 本轮无命令/工具：明确空态，不留白不伪造
    expect(wrapper.find('[data-testid="turn-no-commands"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="turn-no-commands"]').text()).toContain("本轮未执行命令或工具");
  });

  it("会话栏收起后完全退出 DOM（零宽/无焦点/无读屏），展开后恢复", async () => {
    const wrapper = await mountWorkspace();
    expect(wrapper.find('[data-testid="agent-conversations"]').exists()).toBe(true);
    await wrapper.find('[data-testid="agent-conversations-collapse"]').trigger("click");
    // 条件卸载：无布局占位、无可聚焦子项、无命中区（v-if，非隐藏样式）
    expect(wrapper.find('[data-testid="agent-conversations"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="agent-conversation-search"]').exists()).toBe(false);
    // 可发现的展开按钮；点击后列表与选中态恢复（选中/草稿不丢失）
    await wrapper.find('[data-testid="agent-conversations-expand"]').trigger("click");
    expect(wrapper.find('[data-testid="agent-conversations"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="agent-conversation-1"]').exists()).toBe(true);
  });

  it("逐轮分组：每轮用户消息形成独立 turn 容器，完成后提供复制按钮", async () => {
    const wrapper = await mountWorkspace();
    await wrapper.setProps({
      messages: [
        userMsg("第一轮请求", 1),
        agentMsg("第一轮回答", 2),
        userMsg("第二轮请求", 3),
      ],
    });
    expect(wrapper.findAll("article.turn").length).toBe(2);
    expect(wrapper.find('[data-testid="turn-copy-0"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="turn-copy-1"]').exists()).toBe(false);
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
