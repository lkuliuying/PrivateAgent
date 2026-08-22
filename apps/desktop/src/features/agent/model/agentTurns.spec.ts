import { describe, expect, it } from "vitest";
import { groupAgentTurns, turnPublicStatusLabel } from "./agentTurns";
import type { AgentWorkspaceMessage } from "../../../models/agentWorkspace";

function msg(partial: Partial<AgentWorkspaceMessage> & { role: AgentWorkspaceMessage["role"] }): AgentWorkspaceMessage {
  return {
    id: 0,
    session_id: 1,
    content: "",
    created_at: "",
    ...partial,
  } as AgentWorkspaceMessage;
}

describe("groupAgentTurns（W6-R2 turn 分组）", () => {
  it("每条用户消息创建稳定 turn；过程与最终回答归入该轮", () => {
    const turns = groupAgentTurns(
      [
        msg({ role: "user", id: 1, content: "第一轮请求", clientKey: "u1" }),
        msg({ role: "assistant", id: 2, content: "最终回答一" }),
        msg({ role: "user", id: 3, content: "第二轮请求", clientKey: "u2" }),
        msg({ role: "assistant", id: 4, content: "", tool_call: { id: 5, tool_name: "t", arguments: {}, status: "succeeded" } as never }),
        msg({ role: "assistant", id: 6, content: "最终回答二" }),
      ],
      false
    );
    expect(turns.length).toBe(2);
    expect(turns[0].key).toBe("u1");
    expect(turns[0].finalAnswer?.content).toBe("最终回答一");
    expect(turns[1].key).toBe("u2");
    expect(turns[1].process.length).toBe(1);
    expect(turns[1].finalAnswer?.content).toBe("最终回答二");
  });

  it("同一轮更晚的最终回答覆盖早先候选，早先候选降回公开过程（顺序保留）", () => {
    const turns = groupAgentTurns(
      [
        msg({ role: "user", id: 1, content: "请求", clientKey: "u1" }),
        msg({ role: "assistant", id: 2, content: "中间公开说明" }),
        msg({ role: "assistant", id: 3, content: "真正的最终回答" }),
      ],
      false
    );
    expect(turns[0].finalAnswer?.content).toBe("真正的最终回答");
    expect(turns[0].process.map((m) => m.content)).toContain("中间公开说明");
  });

  it("用户消息之前的公开过程归入 pre 分组（不按时间猜归属）", () => {
    const turns = groupAgentTurns(
      [msg({ role: "assistant", id: 9, content: "", tool_call: { id: 9, tool_name: "t", arguments: {}, status: "succeeded" } as never })],
      false
    );
    expect(turns.length).toBe(1);
    expect(turns[0].key).toBe("pre");
    expect(turns[0].userMessage).toBeNull();
  });

  it("待审批事实使末轮进入 waiting_approval（公开事实，不虚构）", () => {
    const turns = groupAgentTurns(
      [
        msg({ role: "user", id: 1, content: "请求", clientKey: "u1" }),
        msg({ role: "assistant", id: 2, content: "", agent_approval: { id: "ap", run_id: "r", tool_call_id: "tc", tool_name: "t", status: "pending" } as never }),
      ],
      true
    );
    expect(turns[0].phase).toBe("waiting_approval");
    expect(turnPublicStatusLabel(turns[0])).toBe("等待审批");
  });

  it("流式中无最终回答：按工具/流式事实呈现真实状态标签", () => {
    const running = groupAgentTurns(
      [msg({ role: "user", id: 1, content: "请求", clientKey: "u1" })],
      true
    );
    expect(running[0].phase).toBe("running");
    expect(turnPublicStatusLabel(running[0])).toBe("正在分析");

    const executing = groupAgentTurns(
      [
        msg({ role: "user", id: 1, content: "请求", clientKey: "u1" }),
        msg({ role: "assistant", id: 2, content: "", tool_call: { id: 2, tool_name: "t", arguments: {}, status: "running" } as never }),
      ],
      true
    );
    expect(turnPublicStatusLabel(executing[0])).toBe("正在执行工具");
  });

  it("已有最终回答的轮不呈现状态标签；历史轮不因全局流式误标", () => {
    const turns = groupAgentTurns(
      [
        msg({ role: "user", id: 1, content: "第一轮", clientKey: "u1" }),
        msg({ role: "assistant", id: 2, content: "回答一" }),
        msg({ role: "user", id: 3, content: "第二轮", clientKey: "u2" }),
      ],
      true
    );
    expect(turnPublicStatusLabel(turns[0])).toBeNull();
    expect(turns[0].phase).toBe("settled");
    expect(turns[1].phase).toBe("running");
  });

  it("空内容助手消息不算最终回答（不根据文案猜完成）", () => {
    const turns = groupAgentTurns(
      [
        msg({ role: "user", id: 1, content: "请求", clientKey: "u1" }),
        msg({ role: "assistant", id: 2, content: "   " }),
      ],
      false
    );
    expect(turns[0].finalAnswer).toBeNull();
  });
});
