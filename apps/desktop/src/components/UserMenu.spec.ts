import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import UserMenu from "./UserMenu.vue";
const options = { props: { inline: true }, global: { stubs: { "a-dropdown": { template: '<div><slot /><slot name="overlay" /></div>' } } } };
describe("本机工作区菜单", () => {
  it("只显示 API Key 模式和设置，没有平台账号操作", () => {
    const wrapper = mount(UserMenu, options);
    expect(wrapper.text()).toContain("API Key 模式");
    expect(wrapper.text()).not.toMatch(/登录|注册|账号/);
    expect(wrapper.findAll('[role="menuitem"]')).toHaveLength(1);
    wrapper.unmount();
  });
  it("设置入口保持可用", async () => {
    const wrapper = mount(UserMenu, options);
    await wrapper.get('[data-testid="user-menu-settings"]').trigger("click");
    expect(wrapper.emitted("settings")).toHaveLength(1);
    wrapper.unmount();
  });
});
