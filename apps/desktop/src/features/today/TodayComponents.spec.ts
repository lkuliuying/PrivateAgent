import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import OverviewCards from "./OverviewCards.vue";
import PriorityList from "./PriorityList.vue";

describe("OverviewCards", () => {
  const items = [
    { label: "待处理", value: 3, hint: "任务与收件箱", view: "tasks" as const },
    { label: "运行关注", value: 1, hint: "失败活动", view: "diagnostics" as const, tone: "danger" },
  ];

  it("渲染数值与提示，danger 项带强调类", () => {
    const wrapper = mount(OverviewCards, { props: { items } });
    const cards = wrapper.findAll("button.overview-item");
    expect(cards).toHaveLength(2);
    expect(cards[0].text()).toContain("待处理");
    expect(cards[0].text()).toContain("3");
    expect(cards[1].classes()).toContain("danger");
  });

  it("点击发出 navigate", async () => {
    const wrapper = mount(OverviewCards, { props: { items } });
    await wrapper.findAll("button")[0].trigger("click");
    expect(wrapper.emitted("navigate")?.[0]).toEqual(["tasks"]);
  });
});

describe("PriorityList", () => {
  const entries = [
    {
      key: "tasks-1",
      title: "发布检查",
      meta: "今天 14:00",
      sectionTitle: "任务",
      error: null,
      item: { id: 1 } as never,
      itemType: "todo" as const,
    },
  ];

  it("渲染优先事项与收件箱动作", async () => {
    const wrapper = mount(PriorityList, { props: { entries, busy: false } });
    expect(wrapper.text()).toContain("发布检查");
    expect(wrapper.text()).toContain("任务 · 今天 14:00");
    await wrapper.find(".row-action").trigger("click");
    expect(wrapper.emitted("save-inbox")).toBeTruthy();
  });

  it("空态展示引导动作", async () => {
    const wrapper = mount(PriorityList, { props: { entries: [], busy: false } });
    expect(wrapper.text()).toContain("当前没有必须马上处理的事项");
    await wrapper.findAll(".quiet-actions button")[0].trigger("click");
    expect(wrapper.emitted("new-reminder")).toBeTruthy();
    await wrapper.findAll(".quiet-actions button")[2].trigger("click");
    expect(wrapper.emitted("import-document")).toBeTruthy();
  });
});
