import { shallowMount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import NavRailV2 from "./NavRailV2.vue";

describe("NavRailV2 permissions", () => {
  it("普通用户不展示服务器管理入口", () => {
    const wrapper = shallowMount(NavRailV2, { props: { active: "today" } });

    expect(wrapper.text()).not.toContain("项目");
    expect(wrapper.text()).not.toContain("集成");
    expect(wrapper.text()).not.toContain("设置");
    expect(wrapper.text()).not.toContain("诊断");
    expect(wrapper.text()).not.toContain("备份");
  });

  it("管理员保留服务器管理入口", () => {
    const wrapper = shallowMount(NavRailV2, {
      props: { active: "today", isAdmin: true },
    });

    expect(wrapper.text()).toContain("项目");
    expect(wrapper.text()).toContain("集成");
    expect(wrapper.text()).toContain("设置");
    expect(wrapper.text()).toContain("诊断");
    expect(wrapper.text()).toContain("备份");
  });
});
