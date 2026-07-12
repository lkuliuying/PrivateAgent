import { shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import TodayView from "./TodayView.vue";

const getToday = vi.fn();

vi.mock("../api", () => ({
  getToday: (...args: unknown[]) => getToday(...args),
  createInbox: vi.fn(),
  createTodayBriefing: vi.fn(),
}));

vi.mock("../stores/notifications", () => ({
  useNotifications: () => ({
    success: vi.fn(),
    error: vi.fn(),
  }),
}));

const snapshot = {
  generated_at: "2026-07-11T08:00:00+08:00",
  summary: {
    due_cards: 0,
    attention_tasks: 0,
    failed_activities: 0,
    draft_memories: 0,
    due_reminders: 0,
    open_inbox: 0,
    last_backup_at: null,
  },
  due_cards: [],
  attention_tasks: [],
  failed_activities: [],
  draft_memories: [],
  due_reminders: [],
  open_inbox: [],
  backup: { last_backup_at: null, count: 0 },
  recent_checkins: [],
  recent_briefings: [],
  recent_docs: [],
  recent_sessions: [],
  maintenance: {
    last_backup_at: null,
    backup_count: 0,
    failed_activities: 0,
    draft_memories: 0,
    orphan_evidence: 0,
  },
};

async function mountToday() {
  const wrapper = shallowMount(TodayView);
  await Promise.resolve();
  await nextTick();
  return wrapper;
}

beforeEach(() => {
  getToday.mockReset();
  getToday.mockResolvedValue(snapshot);
});

describe("TodayView composer", () => {
  it("直接提交智能对话", async () => {
    const wrapper = await mountToday();
    const input = wrapper.get("#today-composer-input");
    await input.setValue("帮我安排今天");
    await input.trigger("keydown", { key: "Enter" });

    expect(wrapper.emitted("submit")).toEqual([["帮我安排今天", "chat"]]);
    wrapper.unmount();
  });

  it("切换计划模式后提交对应模式", async () => {
    const wrapper = await mountToday();
    await wrapper.get(".mode-trigger").trigger("click");
    const modeButtons = wrapper.findAll(".mode-menu button");
    await modeButtons[2].trigger("click");
    await wrapper.get("#today-composer-input").setValue("准备下一版发布");
    await wrapper.get(".send").trigger("click");

    expect(wrapper.emitted("submit")).toEqual([["准备下一版发布", "plan"]]);
    wrapper.unmount();
  });

  it("空输入不会提交", async () => {
    const wrapper = await mountToday();
    await wrapper.get(".send").trigger("click");
    expect(wrapper.emitted("submit")).toBeUndefined();
    wrapper.unmount();
  });
});
