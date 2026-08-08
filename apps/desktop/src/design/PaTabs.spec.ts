import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import PaTabs from "./PaTabs.vue";
import PaSegmentedControl from "./PaSegmentedControl.vue";
import PaDisclosure from "./PaDisclosure.vue";

describe("PaTabs", () => {
  const items = [
    { key: "files", label: "Files", badge: 3 },
    { key: "context", label: "Context" },
    { key: "sources", label: "Sources", disabled: true },
  ];

  it("渲染页签与选中态", () => {
    const wrapper = mount(PaTabs, { props: { modelValue: "files", items } });
    const tabs = wrapper.findAll('[role="tab"]');
    expect(tabs).toHaveLength(3);
    expect(tabs[0].attributes("aria-selected")).toBe("true");
    expect(tabs[1].attributes("aria-selected")).toBe("false");
    expect(wrapper.text()).toContain("3");
  });

  it("点击切换并发出事件", async () => {
    const wrapper = mount(PaTabs, { props: { modelValue: "files", items } });
    await wrapper.findAll('[role="tab"]')[1].trigger("click");
    expect(wrapper.emitted("update:modelValue")?.[0]).toEqual(["context"]);
  });

  it("方向键切换页签，跳过禁用项", async () => {
    const wrapper = mount(PaTabs, { props: { modelValue: "files", items } });
    const tabs = wrapper.findAll('[role="tab"]');
    await tabs[0].trigger("keydown", { key: "ArrowRight" });
    // files -> context（sources 禁用被跳过）
    expect(wrapper.emitted("update:modelValue")?.[0]).toEqual(["context"]);
  });
});

describe("PaSegmentedControl", () => {
  it("渲染单选按钮组并发出事件", async () => {
    const wrapper = mount(PaSegmentedControl, {
      props: {
        modelValue: "a",
        options: [
          { value: "a", label: "A" },
          { value: "b", label: "B" },
        ],
      },
    });
    const radios = wrapper.findAll('[role="radio"]');
    expect(radios[0].attributes("aria-checked")).toBe("true");
    await radios[1].trigger("click");
    expect(wrapper.emitted("update:modelValue")?.[0]).toEqual(["b"]);
  });
});

describe("PaDisclosure", () => {
  it("默认折叠，点击展开内容", async () => {
    const wrapper = mount(PaDisclosure, {
      props: { title: "运行日志" },
      slots: { default: "<p>日志内容</p>" },
    });
    expect(wrapper.find(".pa-disclosure-body").exists()).toBe(false);
    expect(wrapper.attributes("aria-expanded")).toBeUndefined();
    await wrapper.find(".pa-disclosure-trigger").trigger("click");
    expect(wrapper.find(".pa-disclosure-body").exists()).toBe(true);
    expect(wrapper.emitted("toggle")?.[0]).toEqual([true]);
  });

  it("展开按钮 aria-expanded 同步", async () => {
    const wrapper = mount(PaDisclosure, { props: { title: "x" } });
    await wrapper.find(".pa-disclosure-trigger").trigger("click");
    expect(wrapper.find(".pa-disclosure-trigger").attributes("aria-expanded")).toBe("true");
  });
});
