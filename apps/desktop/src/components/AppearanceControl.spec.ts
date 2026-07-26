import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useAppearance } from "../stores/appearance";
import AppearanceControl from "./AppearanceControl.vue";

const appearance = useAppearance();

describe("AppearanceControl", () => {
  beforeEach(() => {
    appearance.setTheme("system");
    appearance.setContrast("normal");
  });

  afterEach(() => {
    appearance.setTheme("system");
    appearance.setContrast("normal");
  });

  it("按 system、light、dark 顺序循环主题", async () => {
    const wrapper = mount(AppearanceControl);
    const theme = wrapper.get(".appearance-theme");

    expect(theme.attributes("aria-label")).toContain("系统");
    await theme.trigger("click");
    expect(appearance.theme.value).toBe("light");
    expect(theme.attributes("aria-label")).toContain("浅色");

    await theme.trigger("click");
    expect(appearance.theme.value).toBe("dark");
    expect(theme.attributes("aria-label")).toContain("深色");
  });

  it("高对比度按钮暴露并更新 aria-pressed", async () => {
    const wrapper = mount(AppearanceControl);
    const contrast = wrapper.get(".appearance-contrast");

    expect(contrast.attributes("aria-pressed")).toBe("false");
    await contrast.trigger("click");
    expect(appearance.contrast.value).toBe("more");
    expect(contrast.attributes("aria-pressed")).toBe("true");
    expect(contrast.attributes("aria-label")).toBe("关闭高对比度");
  });
});
