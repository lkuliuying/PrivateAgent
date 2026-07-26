import { mount, type VueWrapper } from "@vue/test-utils";
import { nextTick } from "vue";
import { afterEach, describe, expect, it } from "vitest";
import OverlayAsyncState from "./OverlayAsyncState.vue";

let appRoot: HTMLElement | null = null;
let wrapper: VueWrapper | null = null;

afterEach(async () => {
  wrapper?.unmount();
  wrapper = null;
  await nextTick();
  appRoot?.remove();
  appRoot = null;
  document.querySelectorAll(".async-overlay").forEach((element) => element.remove());
});

function mountState(error?: Error): VueWrapper {
  appRoot = document.createElement("div");
  appRoot.id = "app";
  document.body.appendChild(appRoot);
  wrapper = mount(OverlayAsyncState, {
    attachTo: appRoot,
    props: { error },
  });
  return wrapper;
}

describe("OverlayAsyncState", () => {
  it("加载期间立即锁定背景、聚焦浮层并允许 Esc 关闭", async () => {
    const state = mountState();
    await nextTick();

    const dialog = document.querySelector<HTMLElement>(".async-overlay-card")!;
    expect(dialog.getAttribute("role")).toBe("dialog");
    expect(dialog.getAttribute("aria-busy")).toBe("true");
    expect(document.activeElement).toBe(dialog);
    expect(appRoot?.inert).toBe(true);
    expect(appRoot?.getAttribute("aria-hidden")).toBe("true");

    dialog.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })
    );
    expect(state.emitted("close")).toHaveLength(1);
  });

  it("失败时使用 alertdialog、聚焦恢复按钮并保持 Esc 退出路径", async () => {
    const state = mountState(new Error("chunk failed"));
    await nextTick();

    const dialog = document.querySelector<HTMLElement>(".async-overlay-card")!;
    const reload = document.querySelector<HTMLButtonElement>(".async-overlay-card button")!;
    expect(dialog.getAttribute("role")).toBe("alertdialog");
    expect(dialog.getAttribute("aria-labelledby")).toBe("async-overlay-title");
    expect(document.activeElement).toBe(reload);

    reload.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })
    );
    expect(state.emitted("close")).toHaveLength(1);
  });
});
