import { mount, type VueWrapper } from "@vue/test-utils";
import { nextTick } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import DocumentComparePanel from "./DocumentComparePanel.vue";

vi.mock("../api", () => ({
  exportMarkdown: vi.fn(),
  pickDirectory: vi.fn(),
}));

let appRoot: HTMLElement | null = null;
let wrapper: VueWrapper | null = null;

afterEach(async () => {
  wrapper?.unmount();
  wrapper = null;
  await nextTick();
  appRoot?.remove();
  appRoot = null;
  document.querySelectorAll(".modal-overlay").forEach((element) => element.remove());
});

describe("DocumentComparePanel modal boundary", () => {
  it("teleports, locks focus, closes with Escape and restores the trigger", async () => {
    appRoot = document.createElement("div");
    appRoot.id = "app";
    const trigger = document.createElement("button");
    trigger.textContent = "open compare";
    appRoot.appendChild(trigger);
    document.body.appendChild(appRoot);
    trigger.focus();

    wrapper = mount(DocumentComparePanel, {
      attachTo: appRoot,
      props: { result: null, loading: true },
    });
    await nextTick();

    const overlay = document.querySelector<HTMLElement>(".modal-overlay")!;
    const dialog = document.querySelector<HTMLElement>(".compare-card")!;
    const close = dialog.querySelector<HTMLButtonElement>(
      '[aria-label="关闭文档对比"]'
    )!;

    expect(overlay.parentElement).toBe(document.body);
    expect(dialog.getAttribute("role")).toBe("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.getAttribute("aria-busy")).toBe("true");
    expect(document.activeElement).toBe(close);
    expect(appRoot.inert).toBe(true);
    expect(appRoot.getAttribute("aria-hidden")).toBe("true");

    close.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })
    );
    expect(wrapper.emitted("close")).toHaveLength(1);

    wrapper.unmount();
    wrapper = null;
    await nextTick();
    expect(appRoot.inert).toBe(false);
    expect(appRoot.hasAttribute("aria-hidden")).toBe(false);
    expect(document.activeElement).toBe(trigger);
  });
});
