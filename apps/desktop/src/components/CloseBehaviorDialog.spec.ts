import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import CloseBehaviorDialog from "./CloseBehaviorDialog.vue";

function mountDialog() {
  return mount(CloseBehaviorDialog, {
    props: {
      open: true,
      selected: "exit",
      dontAskAgain: false,
    },
    global: {
      stubs: {
        Teleport: true,
        Transition: false,
      },
    },
  });
}

describe("CloseBehaviorDialog", () => {
  it("defaults to exit and exposes both close behaviors", () => {
    const wrapper = mountDialog();
    const radios = wrapper.findAll<HTMLInputElement>('input[type="radio"]');

    expect(wrapper.text()).toContain("保留后台运行");
    expect(wrapper.text()).toContain("退出应用");
    expect(radios[0].element.checked).toBe(false);
    expect(radios[1].element.checked).toBe(true);
  });

  it("emits the selected behavior, remember flag and confirmation", async () => {
    const wrapper = mountDialog();
    const radios = wrapper.findAll<HTMLInputElement>('input[type="radio"]');
    const remember = wrapper.get<HTMLInputElement>('input[type="checkbox"]');

    await radios[0].setValue(true);
    await remember.setValue(true);
    await wrapper.get(".pa-btn--primary").trigger("click");

    expect(wrapper.emitted("update:selected")?.[0]).toEqual(["background"]);
    expect(wrapper.emitted("update:dontAskAgain")?.[0]).toEqual([true]);
    expect(wrapper.emitted("confirm")).toHaveLength(1);
  });

  it("cancels from the icon-only close button", async () => {
    const wrapper = mountDialog();
    await wrapper.get('[aria-label="取消关闭"]').trigger("click");
    expect(wrapper.emitted("cancel")).toHaveLength(1);
  });
});
