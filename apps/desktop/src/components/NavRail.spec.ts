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
    const wrapper = shallowMount(NavRail, { props: { active: "today" } });
    const toggle = wrapper.get(".utility-toggle");
    expect(toggle.attributes("aria-controls")).toBe("navrail-advanced-items");
    await toggle.trigger("click");
    expect(wrapper.find(".advanced-items").exists()).toBe(true);
    expect(wrapper.get(".advanced-items").attributes("id")).toBe(
      "navrail-advanced-items"
    );
    expect(wrapper.text()).toContain("诊断");
    expect(wrapper.text()).toContain("备份");

    await wrapper.get(".advanced-items button").trigger("keydown", {
      key: "Escape",
    });
    expect(wrapper.find(".advanced-items").exists()).toBe(false);
  });

  it("设置仍是直接可达入口", async () => {
    const wrapper = shallowMount(NavRail, { props: { active: "today" } });
    const settings = wrapper
      .findAll("button")
      .find((button) => button.text().includes("设置"));
    expect(settings).toBeDefined();
    await settings!.trigger("click");
    expect(wrapper.emitted("navigate")).toEqual([["settings"]]);
  });

  it("窄 rail 隐藏文字后仍为每个导航入口提供可访问名称", () => {
    const wrapper = shallowMount(NavRail, { props: { active: "today" } });
    const navItems = wrapper.findAll(".nav-item");

    expect(navItems.length).toBeGreaterThan(0);
    expect(navItems.every((button) => Boolean(button.attributes("aria-label")))).toBe(
      true
    );
  });

  it("设置激活时暴露 aria-current", () => {
    const wrapper = shallowMount(NavRail, { props: { active: "settings" } });
    const settings = wrapper
      .findAll(".nav-item")
      .find((button) => button.attributes("aria-label") === "设置");

    expect(settings?.attributes("aria-current")).toBe("page");
  });
});
