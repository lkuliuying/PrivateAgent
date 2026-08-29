import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProfileSettingsPanel from "./ProfileSettingsPanel.vue";

const auth = vi.hoisted(() => ({
  user: {
    id: 8,
    username: "sanyueqi",
    display_name: "三月七",
    email: "sanyueqi@example.com",
    role: "user" as const,
    status: "active" as const,
  },
}));

vi.mock("../stores/auth", () => ({
  useAuthStore: () => auth,
}));

describe("ProfileSettingsPanel", () => {
  beforeEach(() => window.localStorage.clear());

  it("显示账号基本信息并把个性资料保存在当前账号的本机空间", async () => {
    const wrapper = mount(ProfileSettingsPanel);

    expect(wrapper.text()).toContain("sanyueqi");
    expect(wrapper.text()).toContain("sanyueqi@example.com");
    expect(wrapper.text()).toContain("普通用户");

    await wrapper.get('input[autocomplete="nickname"]').setValue("三月七");
    await wrapper.get("textarea").setValue("本地工作台用户");
    await wrapper.get('[data-testid="profile-save"]').trigger("click");

    expect(JSON.parse(window.localStorage.getItem("pa.local-profile.8") ?? "{}")).toMatchObject({
      nickname: "三月七",
      bio: "本地工作台用户",
    });
    expect(wrapper.text()).toContain("个人资料已保存在当前设备");
  });

  it("选择有效图片后显示头像预览", async () => {
    const wrapper = mount(ProfileSettingsPanel);
    const input = wrapper.get('[data-testid="profile-avatar-input"]');
    const file = new File([new Uint8Array([137, 80, 78, 71])], "avatar.png", {
      type: "image/png",
    });
    Object.defineProperty(input.element, "files", { configurable: true, value: [file] });
    await input.trigger("change");
    await vi.waitFor(() => {
      expect(wrapper.find('img[alt="当前头像"]').exists()).toBe(true);
    });
  });
});
