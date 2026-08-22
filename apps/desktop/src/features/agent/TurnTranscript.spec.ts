import { describe, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import TurnTranscript from "./TurnTranscript.vue";
import { groupAgentTurns } from "./model/agentTurns";
import type { AgentWorkspaceMessage } from "../../models/agentWorkspace";

const notifySuccess = vi.fn();
const notifyError = vi.fn();

vi.mock("../../stores/notifications", () => ({
  useNotifications: () => ({
    success: (...args: unknown[]) => notifySuccess(...args),
    error: (...args: unknown[]) => notifyError(...args),
  }),
}));

function msg(partial: Partial<AgentWorkspaceMessage> & { role: AgentWorkspaceMessage["role"] }): AgentWorkspaceMessage {
  return {
    id: 0,
    session_id: 1,
    content: "",
    created_at: "",
    ...partial,
  } as AgentWorkspaceMessage;
}

function mountTranscript(messages: AgentWorkspaceMessage[], streaming = false) {
  return mount(TurnTranscript, {
    props: { turns: groupAgentTurns(messages, streaming), streaming },
    attachTo: document.body,
  });
}

describe("TurnTranscript（W6-R2 逐轮分组与回答复制）", () => {
  it("每轮用户消息形成稳定 turn 容器", () => {
    const wrapper = mountTranscript([
      msg({ role: "user", id: 1, content: "第一轮", clientKey: "u1" }),
      msg({ role: "assistant", id: 2, content: "回答一" }),
      msg({ role: "user", id: 3, content: "第二轮", clientKey: "u2" }),
      msg({ role: "assistant", id: 4, content: "回答二" }),
    ]);
    expect(wrapper.findAll("article.turn").length).toBe(2);
    expect(wrapper.find('[data-testid="turn-0"]').attributes("data-turn-key")).toBe("u1");
    expect(wrapper.find('[data-testid="turn-1"]').attributes("data-turn-key")).toBe("u2");
  });

  it("完成轮提供复制按钮；流式轮不出现复制按钮（定格后才可复查）", () => {
    const wrapper = mountTranscript(
      [
        msg({ role: "user", id: 1, content: "第一轮", clientKey: "u1" }),
        msg({ role: "assistant", id: 2, content: "回答一" }),
        msg({ role: "user", id: 3, content: "第二轮", clientKey: "u2" }),
      ],
      true
    );
    expect(wrapper.find('[data-testid="turn-copy-0"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="turn-copy-1"]').exists()).toBe(false);
  });

  it("无公开摘要时只呈现真实状态（不虚构思考内容）", () => {
    const wrapper = mountTranscript(
      [msg({ role: "user", id: 1, content: "请求", clientKey: "u1" })],
      true
    );
    const status = wrapper.find('[data-testid="turn-public-status"]');
    expect(status.exists()).toBe(true);
    expect(["正在分析", "正在执行工具", "等待审批"]).toContain(status.text());
  });

  it("复制成功：只提示「回答已复制」，通知不含回答正文", async () => {
    notifySuccess.mockReset();
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
      configurable: true,
    });
    const wrapper = mountTranscript([
      msg({ role: "user", id: 1, content: "请求", clientKey: "u1" }),
      msg({ role: "assistant", id: 2, content: "完整最终回答正文" }),
    ]);
    await wrapper.find('[data-testid="turn-copy-0"]').trigger("click");
    await flushPromises();
    expect(notifySuccess).toHaveBeenCalledWith("回答已复制");
    expect(String(notifySuccess.mock.calls[0])).not.toContain("完整最终回答正文");
  });

  it("剪贴板失败：呈现可恢复提示，不保存回答正文到通知", async () => {
    notifyError.mockReset();
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
      configurable: true,
    });
    document.execCommand = vi.fn().mockReturnValue(false);
    const wrapper = mountTranscript([
      msg({ role: "user", id: 1, content: "请求", clientKey: "u1" }),
      msg({ role: "assistant", id: 2, content: "敏感回答正文" }),
    ]);
    await wrapper.find('[data-testid="turn-copy-0"]').trigger("click");
    await flushPromises();
    expect(notifyError).toHaveBeenCalled();
    const callText = notifyError.mock.calls.flat().join(" ");
    expect(callText).not.toContain("敏感回答正文");
    expect(callText).toContain("手动");
  });

  it("空消息呈现起始引导（沿用既有空态）", () => {
    const wrapper = mountTranscript([]);
    expect(wrapper.find('[data-testid="feed-empty"]').exists()).toBe(true);
  });
});
