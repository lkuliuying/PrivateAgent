import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import UserMenu from "./UserMenu.vue";

const replace = vi.hoisted(() => vi.fn());
const logout = vi.hoisted(() => vi.fn());
const auth = vi.hoisted(() => ({
  user: { username: "liuying", role: "user" },
  loading: false,
  logout,
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ replace }),
}));
vi.mock("ant-design-vue", () => ({
  message: { warning: vi.fn() },
}));
vi.mock("../stores/auth", () => ({
  useAuthStore: () => auth,
}));

const DropdownStub = {
  template: '<div><slot /><slot name="overlay" /></div>',
};

describe("UserMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.loading = false;
    logout.mockResolvedValue(undefined);
  });

  it("显示当前用户名，菜单暂时只提供设置和退出登录", () => {
    const wrapper = mount(UserMenu, {
      props: { inline: true },
      global: { stubs: { "a-dropdown": DropdownStub } },
    });

    expect(wrapper.text()).toContain("liuying");
    expect(wrapper.text()).toContain("设置");
    expect(wrapper.text()).toContain("退出登录");
    expect(wrapper.text()).not.toContain("管理员端");
    expect(wrapper.findAll('[role="menuitem"]')).toHaveLength(2);
  });

  it("点击账号入口不直接进入设置，选择设置后才触发导航", async () => {
    const wrapper = mount(UserMenu, {
      props: { inline: true },
      global: { stubs: { "a-dropdown": DropdownStub } },
    });

    await wrapper.get('[data-testid="user-menu-trigger"]').trigger("click");
    expect(wrapper.emitted("settings")).toBeUndefined();

    await wrapper.get('[data-testid="user-menu-settings"]').trigger("click");
    expect(wrapper.emitted("settings")).toHaveLength(1);
  });

  it("退出登录调用服务并返回登录页", async () => {
    const wrapper = mount(UserMenu, {
      global: { stubs: { "a-dropdown": DropdownStub } },
    });

    await wrapper.get('[data-testid="user-menu-logout"]').trigger("click");
    await flushPromises();

    expect(logout).toHaveBeenCalledTimes(1);
    expect(replace).toHaveBeenCalledWith({ name: "login" });
  });
});
