import { flushPromises, mount } from "@vue/test-utils";
import { nextTick } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RootApp from "./RootApp.vue";
import { saveWindowCloseBehavior } from "./services/windowClose";

const desktopMocks = vi.hoisted(() => ({
  closeHandler: null as (() => void | Promise<void>) | null,
  hide: vi.fn(async () => undefined),
  exit: vi.fn(async () => undefined),
  unlisten: vi.fn(),
}));

const backendMocks = vi.hoisted(() => ({
  state: { status: "ready", error: "" },
  retry: vi.fn(async () => undefined),
}));

vi.mock("./api/tauri", () => ({
  cmdHideMainWindow: desktopMocks.hide,
  cmdExitApp: desktopMocks.exit,
  listenForMainWindowClose: vi.fn(
    async (handler: () => void | Promise<void>) => {
      desktopMocks.closeHandler = handler;
      return desktopMocks.unlisten;
    }
  ),
}));

vi.mock("./stores/auth", () => ({
  useAuthStore: () => ({ clearSession: vi.fn() }),
}));

vi.mock("./services/backendStartup", () => ({
  backendStartupState: backendMocks.state,
  retryDesktopBackendStartup: backendMocks.retry,
}));

vi.mock("vue-router", () => ({
  RouterView: { template: '<div data-testid="router-view" />' },
  useRoute: () => ({ name: "login", fullPath: "/login" }),
  useRouter: () => ({ replace: vi.fn() }),
}));

async function mountRoot() {
  const wrapper = mount(RootApp, {
    global: {
      stubs: {
        AConfigProvider: { template: "<div><slot /></div>" },
        Teleport: true,
        Transition: false,
      },
    },
  });
  await flushPromises();
  return wrapper;
}

describe("RootApp window close lifecycle", () => {
  beforeEach(() => {
    window.localStorage.clear();
    desktopMocks.closeHandler = null;
    desktopMocks.hide.mockClear();
    desktopMocks.exit.mockClear();
    desktopMocks.unlisten.mockClear();
    backendMocks.state.status = "ready";
    backendMocks.state.error = "";
    backendMocks.retry.mockClear();
  });

  it("opens the close choice dialog when no preference is saved", async () => {
    const wrapper = await mountRoot();
    await desktopMocks.closeHandler?.();
    await nextTick();

    expect(wrapper.get('[role="dialog"]').text()).toContain("点击关闭按钮以后");
    expect(desktopMocks.hide).not.toHaveBeenCalled();
    expect(desktopMocks.exit).not.toHaveBeenCalled();
  });

  it("hides immediately when background behavior was saved", async () => {
    saveWindowCloseBehavior("background");
    const wrapper = await mountRoot();
    await desktopMocks.closeHandler?.();
    await flushPromises();

    expect(desktopMocks.hide).toHaveBeenCalledTimes(1);
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
  });

  it("exits after confirming the default exit behavior", async () => {
    const wrapper = await mountRoot();
    await desktopMocks.closeHandler?.();
    await nextTick();
    await wrapper.get(".pa-btn--primary").trigger("click");
    await flushPromises();

    expect(desktopMocks.exit).toHaveBeenCalledTimes(1);
  });

  it("removes the native close listener when the root unmounts", async () => {
    const wrapper = await mountRoot();
    wrapper.unmount();
    expect(desktopMocks.unlisten).toHaveBeenCalledTimes(1);
  });

  it("renders a stable startup screen while the router waits for the backend", async () => {
    backendMocks.state.status = "starting";
    const wrapper = await mountRoot();

    expect(wrapper.get(".startup-gate").text()).toContain("正在启动 PrivateAgent");
    expect(wrapper.find('[data-testid="router-view"]').exists()).toBe(false);
  });

  it("shows the sanitized startup error and allows a retry", async () => {
    backendMocks.state.status = "error";
    backendMocks.state.error = "本地数据库正在被另一个 PrivateAgent 使用。";
    const wrapper = await mountRoot();

    expect(wrapper.get(".startup-gate").text()).toContain("本地数据库正在被另一个");
    expect(wrapper.find('[data-testid="router-view"]').exists()).toBe(false);
    await wrapper.get(".startup-gate button").trigger("click");
    await flushPromises();
    expect(backendMocks.retry).toHaveBeenCalledTimes(1);
  });
});
