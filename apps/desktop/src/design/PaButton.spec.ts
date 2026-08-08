import { describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import PaButton from "./PaButton.vue";
import PaIconButton from "./PaIconButton.vue";
import PaSpinner from "./PaSpinner.vue";
import PaStatusIndicator from "./PaStatusIndicator.vue";

describe("PaButton", () => {
  it("渲染标签并触发 click", async () => {
    const onClick = vi.fn();
    const wrapper = mount(PaButton, { props: { onClick } as never, slots: { default: "保存" } });
    expect(wrapper.text()).toContain("保存");
    await wrapper.trigger("click");
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("loading 时禁用且不触发 click", async () => {
    const onClick = vi.fn();
    const wrapper = mount(PaButton, {
      props: { loading: true, onClick } as never,
      slots: { default: "加载" },
    });
    expect(wrapper.attributes("aria-busy")).toBe("true");
    expect(wrapper.attributes("disabled")).toBeDefined();
    await wrapper.trigger("click");
    expect(onClick).not.toHaveBeenCalled();
  });

  it("disabled 时禁用", () => {
    const wrapper = mount(PaButton, { props: { disabled: true } });
    expect(wrapper.attributes("disabled")).toBeDefined();
  });

  it("变体与尺寸 class 正确", () => {
    const wrapper = mount(PaButton, { props: { variant: "danger", size: "sm" } });
    expect(wrapper.classes()).toContain("is-danger");
    expect(wrapper.classes()).toContain("is-sm");
  });
});

describe("PaIconButton", () => {
  it("必填 aria-label 生效", () => {
    const wrapper = mount(PaIconButton, { props: { label: "删除" } });
    expect(wrapper.attributes("aria-label")).toBe("删除");
    expect(wrapper.attributes("title")).toBe("删除");
  });
});

describe("PaSpinner", () => {
  it("提供 role=status 与默认标签", () => {
    const wrapper = mount(PaSpinner);
    expect(wrapper.attributes("role")).toBe("status");
    expect(wrapper.attributes("aria-label")).toBe("加载中");
  });
});

describe("PaStatusIndicator", () => {
  it("渲染文字与语义 tone", () => {
    const wrapper = mount(PaStatusIndicator, { props: { tone: "warn", label: "Ollama 离线", pulse: true } });
    expect(wrapper.text()).toContain("Ollama 离线");
    expect(wrapper.find(".pa-status-dot").classes()).toContain("is-pulse");
    const noPulse = mount(PaStatusIndicator, { props: { tone: "ok", label: "在线" } });
    expect(noPulse.find(".pa-status-dot").classes()).not.toContain("is-pulse");
  });
});
