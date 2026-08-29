import { shallowMount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import NavRail from "./NavRail.vue";

describe("NavRail", () => {
  it("快捷命令按钮发出 open-command", async () => {
    const wrapper = shallowMount(NavRail, { props: { active: "today" } });
    await wrapper.get(".command-shortcut").trigger("click");
    expect(wrapper.emitted("open-command")).toHaveLength(1);
  });

  it("更多工具可展开且保留高级入口", async () => {
    const wrapper = shallowMount(NavRail, {
      props: { active: "today", isAdmin: true },
    });
    await wrapper.get(".utility-toggle").trigger("click");
    expect(wrapper.find(".advanced-items").exists()).toBe(true);
    expect(wrapper.text()).toContain("诊断");
    expect(wrapper.text()).toContain("备份");
  });

  it("设置仍是直接可达入口", async () => {
    const wrapper = shallowMount(NavRail, {
      props: { active: "today", isAdmin: true },
    });
    const settings = wrapper
      .findAll("button")
      .find((button) => button.text().includes("设置"));
    expect(settings).toBeDefined();
    await settings!.trigger("click");
    expect(wrapper.emitted("navigate")).toEqual([["settings"]]);
  });

  it("普通用户不展示服务器管理入口", async () => {
    const wrapper = shallowMount(NavRail, { props: { active: "today" } });
    await wrapper.get(".utility-toggle").trigger("click");

    expect(wrapper.text()).not.toContain("设置");
    expect(wrapper.text()).not.toContain("项目");
    expect(wrapper.text()).not.toContain("诊断");
    expect(wrapper.text()).not.toContain("备份");
  });
});
