import { mount } from "@vue/test-utils";
import { defineComponent, nextTick, ref } from "vue";
import { afterEach, describe, expect, it } from "vitest";
import { useModalFocus } from "./useModalFocus";

const ModalHarness = defineComponent({
  setup() {
    const open = ref(false);
    const dialog = ref<HTMLElement | null>(null);
    const first = ref<HTMLButtonElement | null>(null);
    useModalFocus({
      container: dialog,
      initialFocus: first,
      active: open,
      onEscape: () => {
        open.value = false;
      },
    });
    return { open, dialog, first };
  },
  template: `
    <button class="trigger" @click="open = true">打开</button>
    <Teleport to="body">
      <div v-if="open" ref="dialog" class="dialog" tabindex="-1">
        <button ref="first" class="first">第一个</button>
        <button class="last">最后一个</button>
      </div>
    </Teleport>
  `,
});

const StackedModalHarness = defineComponent({
  setup() {
    const baseOpen = ref(false);
    const topOpen = ref(false);
    const baseDialog = ref<HTMLElement | null>(null);
    const topDialog = ref<HTMLElement | null>(null);
    const openTop = ref<HTMLButtonElement | null>(null);
    const topClose = ref<HTMLButtonElement | null>(null);
    useModalFocus({
      container: baseDialog,
      initialFocus: openTop,
      active: baseOpen,
      onEscape: () => {
        baseOpen.value = false;
      },
    });
    useModalFocus({
      container: topDialog,
      initialFocus: topClose,
      active: topOpen,
      onEscape: () => {
        topOpen.value = false;
      },
    });
    return { baseOpen, topOpen, baseDialog, topDialog, openTop, topClose };
  },
  template: `
    <button class="stack-trigger" @click="baseOpen = true">打开底层</button>
    <Teleport to="body">
      <div v-if="topOpen" class="top-layer">
        <div ref="topDialog" class="top-dialog" tabindex="-1">
          <button ref="topClose" class="top-close">顶层按钮</button>
        </div>
      </div>
      <div v-if="baseOpen" class="base-layer">
        <div ref="baseDialog" class="base-dialog" tabindex="-1">
          <button ref="openTop" class="open-top" @click="topOpen = true">打开顶层</button>
        </div>
      </div>
    </Teleport>
  `,
});

const HandoffModalHarness = defineComponent({
  setup() {
    const firstOpen = ref(false);
    const secondOpen = ref(false);
    const firstDialog = ref<HTMLElement | null>(null);
    const secondDialog = ref<HTMLElement | null>(null);
    const firstAction = ref<HTMLButtonElement | null>(null);
    const secondClose = ref<HTMLButtonElement | null>(null);

    useModalFocus({
      container: firstDialog,
      initialFocus: firstAction,
      active: firstOpen,
      onEscape: () => {
        firstOpen.value = false;
      },
    });
    useModalFocus({
      container: secondDialog,
      initialFocus: secondClose,
      active: secondOpen,
      onEscape: () => {
        secondOpen.value = false;
      },
    });

    function handoff(): void {
      firstOpen.value = false;
      secondOpen.value = true;
    }

    return {
      firstOpen,
      secondOpen,
      firstDialog,
      secondDialog,
      firstAction,
      secondClose,
      handoff,
    };
  },
  template: `
    <button class="handoff-trigger" @click="firstOpen = true">打开第一层</button>
    <Teleport to="body">
      <div v-if="firstOpen" ref="firstDialog" class="handoff-first" tabindex="-1">
        <button ref="firstAction" class="handoff-action" @click="handoff">切换浮层</button>
      </div>
      <div v-if="secondOpen" ref="secondDialog" class="handoff-second" tabindex="-1">
        <button ref="secondClose" class="handoff-close">关闭第二层</button>
      </div>
    </Teleport>
  `,
});

let appRoot: HTMLElement | null = null;

afterEach(() => {
  appRoot?.remove();
  appRoot = null;
  document.querySelectorAll(".dialog").forEach((element) => element.remove());
  document
    .querySelectorAll(
      ".base-layer, .top-layer, .base-dialog, .top-dialog, .handoff-first, .handoff-second"
    )
    .forEach((element) => element.remove());
});

describe("useModalFocus", () => {
  it("锁定背景、循环 Tab，并在 Esc 关闭后恢复触发点", async () => {
    appRoot = document.createElement("div");
    appRoot.id = "app";
    document.body.appendChild(appRoot);
    const wrapper = mount(ModalHarness, { attachTo: appRoot });

    const trigger = wrapper.get<HTMLButtonElement>(".trigger");
    trigger.element.focus();
    await trigger.trigger("click");
    await nextTick();

    const first = document.querySelector<HTMLButtonElement>(".first")!;
    const last = document.querySelector<HTMLButtonElement>(".last")!;
    expect(document.activeElement).toBe(first);
    expect(appRoot.inert).toBe(true);
    expect(appRoot.getAttribute("aria-hidden")).toBe("true");

    last.focus();
    last.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true })
    );
    expect(document.activeElement).toBe(first);

    first.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Tab",
        shiftKey: true,
        bubbles: true,
        cancelable: true,
      })
    );
    expect(document.activeElement).toBe(last);

    last.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })
    );
    await nextTick();
    await nextTick();

    expect(document.querySelector(".dialog")).toBeNull();
    expect(appRoot.inert).toBe(false);
    expect(appRoot.hasAttribute("aria-hidden")).toBe(false);
    expect(document.activeElement).toBe(trigger.element);
    wrapper.unmount();
  });

  it("嵌套浮层只让栈顶响应 Escape，并保持背景锁定", async () => {
    appRoot = document.createElement("div");
    appRoot.id = "app";
    document.body.appendChild(appRoot);
    const wrapper = mount(StackedModalHarness, { attachTo: appRoot });

    const trigger = wrapper.get<HTMLButtonElement>(".stack-trigger");
    trigger.element.focus();
    await trigger.trigger("click");
    await nextTick();
    const openTop = document.querySelector<HTMLButtonElement>(".open-top")!;
    openTop.click();
    await nextTick();
    await nextTick();
    expect(document.querySelector(".top-dialog")).not.toBeNull();
    const baseDialog = document.querySelector<HTMLElement>(".base-dialog")!;
    const topDialog = document.querySelector<HTMLElement>(".top-dialog")!;
    const baseLayer = document.querySelector<HTMLElement>(".base-layer")!;
    const topLayer = document.querySelector<HTMLElement>(".top-layer")!;
    expect(baseDialog.inert).toBe(true);
    expect(baseDialog.getAttribute("aria-hidden")).toBe("true");
    expect(topDialog.inert).not.toBe(true);
    expect(topDialog.hasAttribute("aria-hidden")).toBe(false);
    expect(
      Array.from(document.body.children).indexOf(topLayer)
    ).toBeLessThan(Array.from(document.body.children).indexOf(baseLayer));
    expect(baseLayer.style.zIndex).toBe("calc(var(--z-overlay) + 0)");
    expect(topLayer.style.zIndex).toBe("calc(var(--z-overlay) + 1)");

    document.querySelector<HTMLButtonElement>(".top-close")!.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })
    );
    await nextTick();
    await nextTick();

    expect(document.querySelector(".top-dialog")).toBeNull();
    expect(document.querySelector(".base-dialog")).not.toBeNull();
    expect(baseDialog.inert).toBe(false);
    expect(baseDialog.hasAttribute("aria-hidden")).toBe(false);
    expect(baseLayer.style.zIndex).toBe("calc(var(--z-overlay) + 0)");
    expect(appRoot.inert).toBe(true);
    expect(document.activeElement).toBe(openTop);

    openTop.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })
    );
    await nextTick();
    await nextTick();
    expect(document.querySelector(".base-dialog")).toBeNull();
    expect(appRoot.inert).toBe(false);
    expect(document.activeElement).toBe(trigger.element);
    wrapper.unmount();
  });

  it("浮层交接后仍把焦点恢复到最初的工作区触发点", async () => {
    appRoot = document.createElement("div");
    appRoot.id = "app";
    document.body.appendChild(appRoot);
    const wrapper = mount(HandoffModalHarness, { attachTo: appRoot });

    const trigger = wrapper.get<HTMLButtonElement>(".handoff-trigger");
    trigger.element.focus();
    await trigger.trigger("click");
    await nextTick();

    const firstAction = document.querySelector<HTMLButtonElement>(".handoff-action")!;
    expect(document.activeElement).toBe(firstAction);
    firstAction.click();
    await nextTick();
    await nextTick();

    const secondClose = document.querySelector<HTMLButtonElement>(".handoff-close")!;
    expect(document.activeElement).toBe(secondClose);
    secondClose.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })
    );
    await nextTick();
    await nextTick();

    expect(document.querySelector(".handoff-second")).toBeNull();
    expect(appRoot.inert).toBe(false);
    expect(document.activeElement).toBe(trigger.element);
    wrapper.unmount();
  });
});
