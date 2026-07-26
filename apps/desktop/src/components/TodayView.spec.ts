import { flushPromises, shallowMount } from "@vue/test-utils";
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

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

  it("筛选请求乱序返回时保留最后一次结果", async () => {
    const wrapper = await mountToday();
    const slow = deferred<typeof snapshot>();
    const fast = deferred<typeof snapshot>();
    getToday
      .mockImplementationOnce(() => slow.promise)
      .mockImplementationOnce(() => fast.promise);

    const filters = wrapper.findAll(".filter-select");
    await filters[0].setValue("task");
    await filters[1].setValue("high");

    fast.resolve({
      ...snapshot,
      summary: { ...snapshot.summary, attention_tasks: 22 },
    });
    await flushPromises();
    slow.resolve({
      ...snapshot,
      summary: { ...snapshot.summary, attention_tasks: 11 },
    });
    await flushPromises();

    expect(wrapper.findAll(".overview-item strong")[0].text()).toBe("22");
    wrapper.unmount();
  });
});
