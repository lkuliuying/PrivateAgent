import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import AppShell from "./AppShell.vue";

describe("AppShell", () => {
  it("没有状态栏内容时不保留底部空白区域", () => {
    const wrapper = mount(AppShell, {
      props: { view: "coding", title: "项目" },
      slots: { default: "<div>content</div>" },
    });
    expect(wrapper.find(".appshell-statusbar").exists()).toBe(false);
  });
});
