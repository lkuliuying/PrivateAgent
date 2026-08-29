import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { nextTick } from "vue";
import SettingsModuleNav from "./SettingsModuleNav.vue";

describe("SettingsModuleNav", () => {
  it("按模块呈现设置入口并只高亮当前模块", async () => {
    const wrapper = mount(SettingsModuleNav, { props: { active: "status" } });

    expect(wrapper.findAll(".settings-nav__item")).toHaveLength(10);
    expect(wrapper.find('[data-testid="settings-section-model-profiles"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="settings-section-status"]').attributes("aria-current")).toBe("page");
    expect(wrapper.find('[data-testid="settings-section-provider"]').attributes("aria-current")).toBeUndefined();

    await wrapper.find('[data-testid="settings-section-provider"]').trigger("click");
    expect(wrapper.emitted("select")?.[0]).toEqual(["provider"]);
  });

  it("提供返回工作台入口", async () => {
    const wrapper = mount(SettingsModuleNav, { props: { active: "about" } });
    await wrapper.get(".settings-nav__exit").trigger("click");
    expect(wrapper.emitted("exit")).toHaveLength(1);
  });

  it("窄窗口隐藏模块栏，并通过浮动入口打开与关闭抽屉", async () => {
    const wrapper = mount(SettingsModuleNav, {
      props: { active: "status", narrow: true },
      attachTo: document.body,
    });

    const tab = document.querySelector<HTMLButtonElement>('[data-testid="settings-drawer-tab"]');
    expect(tab).not.toBeNull();
    expect(document.querySelector('[data-testid="settings-module-nav"]')).toBeNull();

    tab?.click();
    await nextTick();
    expect(document.querySelector('[data-testid="settings-module-nav"]')).not.toBeNull();

    document.querySelector<HTMLButtonElement>('[data-testid="settings-drawer-close"]')?.click();
    await nextTick();
    expect(document.querySelector('[data-testid="settings-module-nav"]')).toBeNull();
    wrapper.unmount();
  });
});
