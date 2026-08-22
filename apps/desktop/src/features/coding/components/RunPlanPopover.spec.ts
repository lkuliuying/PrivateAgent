import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import RunPlanPopover from "./RunPlanPopover.vue";

const PLAN = {
  version: 3,
  items: [
    { item_key: "read", ordinal: 1, title: "阅读目标模块", detail: "侧栏与壳层组件", status: "completed" as const },
    { item_key: "edit", ordinal: 2, title: "修改布局样式", detail: null, status: "in_progress" as const },
    { item_key: "test", ordinal: 3, title: "运行测试", detail: null, status: "pending" as const },
  ],
};

describe("RunPlanPopover", () => {
  it("呈现版本与条目，当前项高亮", () => {
    const wrapper = mount(RunPlanPopover, { props: { plan: PLAN } });
    expect(wrapper.text()).toContain("v3");
    expect(wrapper.find('[data-testid="plan-item-read"]').attributes("data-status")).toBe("completed");
    expect(wrapper.find('[data-testid="plan-item-edit"]').attributes("data-status")).toBe("in_progress");
    expect(wrapper.find('[data-testid="plan-item-edit"]').classes()).toContain("current");
  });

  it("无计划时说明后端尚未建立（不虚构）", () => {
    const wrapper = mount(RunPlanPopover, { props: { plan: null } });
    expect(wrapper.text()).toContain("后端尚未建立计划");
  });

  it("关闭按钮发出 close", async () => {
    const wrapper = mount(RunPlanPopover, { props: { plan: PLAN } });
    await wrapper.find('[data-testid="plan-close"]').trigger("click");
    expect(wrapper.emitted("close")).toBeTruthy();
  });
});
