import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { defineComponent, h } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

function mountAdminPage(pinia = createPinia()) {
  return mount(AdminPage, {
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
        "a-table": {
          props: ["columns", "dataSource"],
          template: `<div data-testid="admin-table">
            <template v-for="record in dataSource" :key="record.id">
              <template v-for="column in columns" :key="column.key">
                <div
                  v-if="column.key === 'created_at' || column.key === 'last_login_at'"
                  :data-time-field="column.key"
                >
                  <slot name="bodyCell" :column="column" :record="record" />
                </div>
              </template>
            </template>
          </div>`,
        },
      },
    },
  });
}

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
      health: {
        api: { ok: true },
        mysql: { ok: true },
        chroma: { ok: false },
      },
      generated_at: "2026-08-30T16:49:02.123Z",
    });
    adminService.getAdminUsers.mockResolvedValue({ total: 0, results: [] });
    adminService.getAuditLogs.mockResolvedValue({ total: 0, results: [] });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("exposes system, user and log modules and keeps the create form inside its modal", async () => {
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

    const wrapper = mountAdminPage(pinia);
    await flushPromises();

    const modules = wrapper.findAll(".admin-nav__item");
    expect(modules).toHaveLength(3);
    expect(modules.map((item) => item.text())).toEqual([
      "系统运行监控与操作审计",
      "用户账号、角色与访问状态",
      "日志Supervisor 与 Nginx",
    ]);
    expect(wrapper.get(".admin-content__heading h1").text()).toBe("系统总览");
    const healthPanel = wrapper.get(".admin-panel--health");
    expect(healthPanel.text()).toContain("服务器运行状态");
    expect(healthPanel.text()).toContain("仅管理员可见");
    expect(healthPanel.findAll(".health-item strong").map((item) => item.text())).toEqual([
      "服务器 API", "服务器 MySQL", "服务器 ChromaDB",
    ]);
    expect(healthPanel.findAll(".health-item > div > span").map((item) => item.text())).toEqual([
      "运行正常", "运行正常", "需要检查",
    ]);
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);

    await modules[1].trigger("click");
    expect(wrapper.get(".admin-content__heading h1").text()).toBe("用户管理");
    expect(wrapper.find(".admin-panel--health").exists()).toBe(false);
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

  it.each(["UTC", "Asia/Shanghai", "America/Los_Angeles"])(
    "shows overview, audit and login times in Shanghai when the client timezone is %s",
    async (timezone) => {
      vi.stubEnv("TZ", timezone);
      expect(new Intl.DateTimeFormat().resolvedOptions().timeZone).toBe(timezone);
      adminService.getAuditLogs.mockResolvedValue({
        total: 1,
        results: [{ id: 1, created_at: "2026-08-30T06:49:00.000Z" }],
      });
      adminService.getAdminUsers.mockResolvedValue({
        total: 2,
        results: [
          { id: 1, last_login_at: "2026-08-30T22:49:02+08:00" },
          { id: 2, last_login_at: null },
        ],
      });

      const wrapper = mountAdminPage();
      try {
        await flushPromises();
        expect(wrapper.get(".admin-topbar__time").text()).toBe(
          "更新于 2026年8月31日 00:49:02"
        );
        expect(wrapper.get('[data-time-field="created_at"]').text()).toBe(
          "2026年8月30日 14:49:00"
        );

        await wrapper.findAll(".admin-nav__item")[1].trigger("click");
        expect(
          wrapper.findAll('[data-time-field="last_login_at"]').map((cell) => cell.text())
        ).toEqual(["2026年8月30日 22:49:02", "--"]);
      } finally {
        wrapper.unmount();
      }
    }
  );
});
