import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { mount, type VueWrapper } from "@vue/test-utils";
import { useShortcuts } from "./useShortcuts";

interface HandlerBag {
  openCommand: ReturnType<typeof vi.fn>;
  newSession: ReturnType<typeof vi.fn>;
  goBack: ReturnType<typeof vi.fn>;
  goForward: ReturnType<typeof vi.fn>;
}

const Host = defineComponent({
  setup() {
    const handlers: HandlerBag = {
      openCommand: vi.fn(),
      newSession: vi.fn(),
      goBack: vi.fn(),
      goForward: vi.fn(),
    };
    useShortcuts(handlers);
    return { handlers };
  },
  render() {
    return h("input", { "data-testid": "input" });
  },
});

function fire(key: string, init: KeyboardEventInit = {}) {
  window.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, ...init }));
}

describe("useShortcuts", () => {
  let wrapper: VueWrapper<InstanceType<typeof Host>> | null = null;
  afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
  });

  function mountHost() {
    wrapper = mount(Host, { attachTo: document.body });
  }

  it("Ctrl/Cmd+K 打开命令面板", () => {
    mountHost();
    fire("k", { ctrlKey: true });
    expect(wrapper!.vm.handlers.openCommand).toHaveBeenCalledTimes(1);
    fire("k", { metaKey: true });
    expect(wrapper!.vm.handlers.openCommand).toHaveBeenCalledTimes(2);
  });

  it("Ctrl/Cmd+N 新建任务", () => {
    mountHost();
    fire("n", { ctrlKey: true });
    expect(wrapper!.vm.handlers.newSession).toHaveBeenCalledTimes(1);
  });

  it("Alt+左右方向键触发视图历史", () => {
    mountHost();
    fire("ArrowLeft", { altKey: true });
    expect(wrapper!.vm.handlers.goBack).toHaveBeenCalledTimes(1);
    fire("ArrowRight", { altKey: true });
    expect(wrapper!.vm.handlers.goForward).toHaveBeenCalledTimes(1);
  });

  it("输入框内 Ctrl+K 仍打开命令面板（不覆盖输入编辑行为）", () => {
    mountHost();
    const input = wrapper!.element as HTMLInputElement;
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true })
    );
    expect(wrapper!.vm.handlers.openCommand).toHaveBeenCalledTimes(1);
  });

  it("卸载后监听器移除", () => {
    mountHost();
    const handlers = wrapper!.vm.handlers;
    wrapper!.unmount();
    wrapper = null;
    fire("k", { ctrlKey: true });
    expect(handlers.openCommand).toHaveBeenCalledTimes(0);
  });
});
