import { ref } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Message, Session, View } from "../types";

const api = vi.hoisted(() => ({
  approveToolCall: vi.fn(),
  candidateMemories: vi.fn(),
  createInbox: vi.fn(),
  createSession: vi.fn(),
  getMessages: vi.fn(),
  listSessions: vi.fn(),
  listToolCalls: vi.fn(),
  planTools: vi.fn(),
  rejectToolCall: vi.fn(),
  streamChat: vi.fn(),
}));

vi.mock("../api", () => api);

import { useChatWorkspace } from "./useChatWorkspace";

const session = {
  id: 7,
  title: "架构审查",
  created_at: "2026-07-25T00:00:00Z",
  updated_at: "2026-07-25T00:00:00Z",
} as Session;

const message = {
  id: 11,
  session_id: 7,
  role: "assistant",
  content: "ready",
  created_at: "2026-07-25T00:00:00Z",
} as Message;

function createNotify() {
  return {
    success: vi.fn(),
    error: vi.fn(),
  };
}

function flushPromises() {
  return new Promise<void>((resolve) => setTimeout(resolve, 0));
}

describe("useChatWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listSessions.mockResolvedValue([session]);
    api.getMessages.mockResolvedValue([message]);
    api.listToolCalls.mockResolvedValue([]);
  });

  it("hydrates the first session without forcing navigation", async () => {
    const view = ref<View>("today");
    const workspace = useChatWorkspace({ view, notify: createNotify() as never });

    await workspace.loadSessions();

    expect(workspace.currentSession.value?.id).toBe(session.id);
    expect(workspace.messages.value).toEqual([message]);
    expect(view.value).toBe("today");
  });

  it("invalidates a pending plan when generation is stopped", async () => {
    let resolvePlan: ((value: { tool_call: null }) => void) | undefined;
    api.planTools.mockReturnValue(
      new Promise((resolve) => {
        resolvePlan = resolve;
      })
    );
    const workspace = useChatWorkspace({
      view: ref<View>("chat"),
      notify: createNotify() as never,
    });
    await workspace.loadSessions();

    workspace.sendMessage("检查竞态");
    workspace.stopGenerate();
    resolvePlan?.({ tool_call: null });
    await flushPromises();

    expect(workspace.streaming.value).toBe(false);
    expect(api.streamChat).not.toHaveBeenCalled();
  });

  it("aborts the active stream during teardown", async () => {
    const controller = new AbortController();
    api.planTools.mockResolvedValue({ tool_call: null });
    api.streamChat.mockReturnValue(controller);
    const workspace = useChatWorkspace({
      view: ref<View>("chat"),
      notify: createNotify() as never,
    });
    await workspace.loadSessions();

    workspace.sendMessage("开始流式输出");
    await flushPromises();
    workspace.destroy();

    expect(api.streamChat).toHaveBeenCalledOnce();
    expect(controller.signal.aborted).toBe(true);
  });
});
