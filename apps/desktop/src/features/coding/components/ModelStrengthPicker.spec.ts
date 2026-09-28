import { mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";
import ModelStrengthPicker from "./ModelStrengthPicker.vue";

let wrapper: VueWrapper;
afterEach(() => wrapper?.unmount());
function create(efforts: string[] | null = ["low", "medium", "high", "max"]) {
  wrapper = mount(ModelStrengthPicker, { attachTo: document.body, props: {
    modelValue: "", modelLabel: "deepseek-flash", efforts,
    "onUpdate:modelValue": value => wrapper.setProps({ modelValue: value }),
  } });
}
describe("ModelStrengthPicker", () => {
  it("分档选择发送模型声明的原值，重置使用默认值", async () => {
    create();
    await wrapper.get('[data-testid="composer-effort"]').trigger("click");
    const slider = wrapper.get('input[type="range"]');
    expect(document.activeElement).toBe(slider.element);
    expect(slider.attributes("max")).toBe("4");
    await slider.setValue("4");
    expect(wrapper.emitted("update:modelValue")?.slice(-1)[0]).toEqual(["max"]);
    expect(slider.attributes("aria-valuetext")).toBe("最高");
    await wrapper.get('[aria-label="恢复默认强度"]').trigger("click");
    expect(wrapper.emitted("update:modelValue")?.slice(-1)[0]).toEqual([""]);
    expect(slider.attributes("aria-valuetext")).toBe("默认");
    expect(document.activeElement).toBe(slider.element);
  });
  it("未声明能力时不虚构档位，模型变化和 Escape 关闭浮层", async () => {
    create(null);
    await wrapper.get('[data-testid="composer-effort"]').trigger("click");
    expect(wrapper.text()).toContain("未提供可调节");
    expect(wrapper.find('input[type="range"]').exists()).toBe(false);
    await wrapper.get('[role="dialog"]').trigger("keydown", { key: "Escape" });
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    expect(document.activeElement).toBe(wrapper.get('[data-testid="composer-effort"]').element);
    await wrapper.get('[data-testid="composer-effort"]').trigger("click");
    await wrapper.setProps({ modelLabel: "qwen-3.8-flash", efforts: ["low", "high"] });
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    expect(wrapper.emitted("update:modelValue")).toBeUndefined();
  });
  it("点击外部关闭，禁用时不打开", async () => {
    create();
    await wrapper.get('[data-testid="composer-effort"]').trigger("click");
    document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    await wrapper.vm.$nextTick();
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    await wrapper.setProps({ disabled: true });
    await wrapper.get('[data-testid="composer-effort"]').trigger("click");
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
  });
});
