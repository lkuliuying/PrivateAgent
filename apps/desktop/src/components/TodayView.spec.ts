import { shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import TodayView from "./TodayView.vue";

const getToday = vi.fn();
const createTodayBriefing = vi.fn();
const createInbox = vi.fn();

vi.mock("../api", () => ({
  getToday: (...args: unknown[]) => getToday(...args),
  createInbox: (...args: unknown[]) => createInbox(...args),
  createTodayBriefing: (...args: unknown[]) => createTodayBriefing(...args),
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
  createTodayBriefing.mockReset();
  createTodayBriefing.mockResolvedValue(undefined);
  createInbox.mockReset();
  createInbox.mockResolvedValue(undefined);
});

// ============ v0.8.0 W6-R2：今日页二次精简（计划 §4.2/§6.7） ============
describe("TodayView W6-R2 二次精简", () => {
  it("不再存在 Agent 输入框/发送按钮与 submit 事件（对话统一进 Agent 页）", async () => {
    const wrapper = await mountToday();
    expect(wrapper.find("#today-composer-input").exists()).toBe(false);
    expect(wrapper.find(".today-composer").exists()).toBe(false);
    expect(wrapper.find(".send").exists()).toBe(false);
    expect(wrapper.emitted("submit")).toBeUndefined();
    wrapper.unmount();
  });

  it("搜索入口保留命令面板语义与键盘可达（按钮可聚焦）", async () => {
    const wrapper = await mountToday();
    const entry = wrapper.find(".command-entry");
    expect(entry.exists()).toBe(true);
    expect(entry.text()).toContain("Ctrl K");
    await entry.trigger("click");
    expect(wrapper.emitted("open-command")).toBeTruthy();
    wrapper.unmount();
  });

  it("提醒摘要位于上下文中心下方：有界条目 + 查看全部/新建提醒导航", async () => {
    getToday.mockResolvedValue({
      ...snapshot,
      summary: { ...snapshot.summary, due_reminders: 5 },
      due_reminders: [
        { id: 1, title: "提醒一", status: "active", due_at: "2026-08-22T09:00:00" },
        { id: 2, title: "提醒二", status: "active", due_at: "2026-08-22T10:00:00" },
        { id: 3, title: "提醒三", status: "active", due_at: "2026-08-22T11:00:00" },
        { id: 4, title: "提醒四", status: "active", due_at: "2026-08-22T12:00:00" },
      ],
    });
    const wrapper = await mountToday();
    await Promise.resolve();
    await nextTick();
    const summary = wrapper.find('[data-testid="today-reminder-summary"]');
    expect(summary.exists()).toBe(true);
    // 摘要位于 today-context 侧栏（上下文中心之后），不在主滚动区
    expect(wrapper.find(".today-context [data-testid='today-reminder-summary']").exists()).toBe(true);
    // 有界：最多 3 条（不重复完整提醒管理）
    expect(wrapper.findAll('[data-testid="today-reminder-item"]').length).toBe(3);
    expect(wrapper.find('[data-testid="today-reminder-count"]').text()).toContain("5");
    await wrapper.find('[data-testid="today-reminder-all"]').trigger("click");
    let navigations = wrapper.emitted("navigate") ?? [];
    expect(navigations[navigations.length - 1]).toEqual(["reminders"]);
    await wrapper.find('[data-testid="today-reminder-new"]').trigger("click");
    navigations = wrapper.emitted("navigate") ?? [];
    expect(navigations[navigations.length - 1]).toEqual(["reminders"]);
    wrapper.unmount();
  });

  it("无到期提醒时摘要呈现空态文案", async () => {
    const wrapper = await mountToday();
    expect(wrapper.find(".reminder-summary-empty").exists()).toBe(true);
    wrapper.unmount();
  });
});

// ============ v0.8.0 W6-R：六模块迁出今日页（计划 §4.2/§6.6） ============
describe("TodayView W6-R 迁移", () => {
  it("不再内嵌六个完整工作台面板（今日主滚动区在概览/最近活动后结束）", async () => {
    const wrapper = await mountToday();
    expect(wrapper.find(".workbench-modules").exists()).toBe(false);
    // W6-R2：Agent 对话框也已移除；概览/优先事项/最近活动仍在（当日概览保留）
    expect(wrapper.find("#today-composer-input").exists()).toBe(false);
    expect(wrapper.find(".today-main").exists()).toBe(true);
    wrapper.unmount();
  });

  it("到期提醒/收件箱快捷链接指向独立主区（不再停留今日页）", async () => {
    getToday.mockResolvedValue({
      ...snapshot,
      summary: { ...snapshot.summary, due_reminders: 2, open_inbox: 1 },
      due_reminders: [
        { id: 901, title: "给医生打电话", status: "active", due_at: "2026-08-22T09:00:00" },
      ],
    });
    const wrapper = await mountToday();
    await Promise.resolve();
    await nextTick();
    const chips = wrapper.findAll(".chip");
    const reminderChip = chips.find((chip) => chip.text().includes("到期提醒"));
    const inboxChip = chips.find((chip) => chip.text().includes("收件箱"));
    expect(reminderChip).toBeTruthy();
    await reminderChip!.trigger("click");
    expect(wrapper.emitted("navigate")?.[wrapper.emitted("navigate")!.length - 1]).toEqual(["reminders"]);
    await inboxChip!.trigger("click");
    expect(wrapper.emitted("navigate")?.[wrapper.emitted("navigate")!.length - 1]).toEqual(["inbox"]);
    wrapper.unmount();
  });

  it("「今日简报」创建后导航到主动简报独立页（创建/通知语义保真）", async () => {
    const wrapper = await mountToday();
    await wrapper.get(".primary-action").trigger("click");
    await Promise.resolve();
    await nextTick();
    expect(createTodayBriefing).toHaveBeenCalledTimes(1);
    const navigations = wrapper.emitted("navigate") ?? [];
    expect(navigations[navigations.length - 1]).toEqual(["briefings"]);
    wrapper.unmount();
  });

  it("优先事项的「新建提醒/快速捕获」动作导航到对应独立页", async () => {
    const wrapper = await mountToday();
    const priority = wrapper.findComponent({ name: "PriorityList" });
    expect(priority.exists()).toBe(true);
    priority.vm.$emit("new-reminder");
    await nextTick();
    let navigations = wrapper.emitted("navigate") ?? [];
    expect(navigations[navigations.length - 1]).toEqual(["reminders"]);
    priority.vm.$emit("quick-capture");
    await nextTick();
    navigations = wrapper.emitted("navigate") ?? [];
    expect(navigations[navigations.length - 1]).toEqual(["capture"]);
    wrapper.unmount();
  });
});
