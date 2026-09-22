import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProfileSettingsPanel from "./ProfileSettingsPanel.vue";
import WorkspaceHeader from "./WorkspaceHeader.vue";
import { defineComponent } from "vue";

describe("ProfileSettingsPanel", () => {
  beforeEach(() => window.localStorage.clear());

  it("在本机空间保存个人资料，不显示平台账号信息", async () => {
    const wrapper = mount(ProfileSettingsPanel);

    expect(wrapper.text()).toContain("API Key 模式");
    expect(wrapper.text()).not.toMatch(/邮箱|账号角色|账号状态/);

    await wrapper.get('input[autocomplete="nickname"]').setValue("三月七");
    await wrapper.get("textarea").setValue("本地工作台用户");
    await wrapper.get('[data-testid="profile-save"]').trigger("click");

    expect(JSON.parse(window.localStorage.getItem("pa.local-profile.local") ?? "{}")).toMatchObject({
      nickname: "三月七",
      bio: "本地工作台用户",
    });
    expect(wrapper.text()).toContain("个人资料已保存在当前设备");
    wrapper.unmount();
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
      expect(wrapper.get('img[alt="当前头像"]').attributes("src")).toMatch(/^data:image\/png;base64,/);
    });
    wrapper.unmount();
  });

  it("保存资料后顶栏立即同步，保存失败时不显示未保存称呼", async () => {
    const wrapper = mount(defineComponent({ components: { ProfileSettingsPanel, WorkspaceHeader }, template: '<WorkspaceHeader title="工作台" /><ProfileSettingsPanel />' }));
    const title = wrapper.get('.workspace-header__profile');
    await wrapper.get('input[autocomplete="nickname"]').setValue("开发搭档");
    expect(title.text()).toContain("本机用户");
    await wrapper.get('[data-testid="profile-save"]').trigger("click");
    expect(title.text()).toContain("开发搭档");
    const write = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); });
    await wrapper.get('input[autocomplete="nickname"]').setValue("未保存称呼");
    await wrapper.get('[data-testid="profile-save"]').trigger("click");
    expect(title.text()).toContain("开发搭档");
    expect(wrapper.text()).toContain("个人资料未保存");
    write.mockRestore();
    wrapper.unmount();
  });
});
