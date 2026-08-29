import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { defineComponent, h } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "../stores/auth";
import AdminPage from "./AdminPage.vue";

const replace = vi.hoisted(() => vi.fn());
const adminService = vi.hoisted(() => ({
  createAdminUser: vi.fn(),
  getAdminOverview: vi.fn(),
  getAdminUsers: vi.fn(),
  getAuditLogs: vi.fn(),
  updateAdminUser: vi.fn(),
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ replace }),
}));
vi.mock("../services/admin", () => adminService);

const ModalStub = defineComponent({
  name: "AModal",
  props: { open: Boolean },
  setup(props, { slots }) {
    return () =>
      props.open
        ? h("section", { role: "dialog" }, slots.default?.())
        : null;
  },
});

const ButtonStub = defineComponent({
  emits: ["click"],
  setup(_, { emit, slots }) {
    return () => h("button", { onClick: () => emit("click") }, slots.default?.());
  },
});

const FormItemStub = defineComponent({
  props: { label: String },
  setup(props, { slots }) {
    return () => h("label", [props.label, slots.default?.()]);
  },
});

describe("AdminPage layout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    adminService.getAdminOverview.mockResolvedValue({
      users_total: 2,
      users_active: 2,
      admins_total: 1,
      sessions_total: 3,
      projects_total: 4,
      documents_total: 5,
      operations_24h: 6,
      errors_24h: 0,
      health: {},
      generated_at: "2026-08-29T00:00:00Z",
    });
    adminService.getAdminUsers.mockResolvedValue({ total: 0, results: [] });
    adminService.getAuditLogs.mockResolvedValue({ total: 0, results: [] });
  });

  it("only exposes system and user modules and keeps the create form inside its modal", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const authStore = useAuthStore();
    authStore.user = {
      id: 1,
      email: "admin@example.test",
      username: "admin",
      display_name: "admin",
      role: "admin",
      status: "active",
      last_login_at: null,
      created_at: "2026-08-29T00:00:00Z",
    };

    const wrapper = mount(AdminPage, {
      global: {
        plugins: [pinia],
        stubs: {
          AModal: ModalStub,
          ARow: { template: "<div><slot /></div>" },
          ACol: { template: "<div><slot /></div>" },
          ASelect: { template: "<div />" },
          "a-alert": { template: "<div />" },
          "a-avatar": { template: "<div><slot /></div>" },
          "a-badge": { template: "<div />" },
          "a-button": ButtonStub,
          "a-empty": { template: "<div />" },
          "a-form": { template: "<form><slot /></form>" },
          "a-form-item": FormItemStub,
          "a-input": { template: "<input />" },
          "a-input-password": { template: "<input />" },
          "a-tag": { template: "<span><slot /></span>" },
          "a-table": { template: "<div data-testid=\"admin-table\" />" },
        },
      },
    });
    await flushPromises();

    const modules = wrapper.findAll(".admin-nav__item");
    expect(modules).toHaveLength(2);
    expect(modules.map((item) => item.text())).toEqual([
      "系统运行监控与操作审计",
      "用户账号、角色与访问状态",
    ]);
    expect(wrapper.get(".admin-content__heading h1").text()).toBe("系统总览");
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);

    await modules[1].trigger("click");
    expect(wrapper.get(".admin-content__heading h1").text()).toBe("用户管理");
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);

    await wrapper.get(".admin-content__heading button").trigger("click");
    const dialog = wrapper.get('[role="dialog"]');
    expect(dialog.text()).toContain("用户名");
    expect(dialog.text()).toContain("角色");
    expect(dialog.text()).toContain("邮箱");
    expect(dialog.text()).toContain("初始密码");
    expect(dialog.text()).toContain("确认密码");

    wrapper.unmount();
  });
});
