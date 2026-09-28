import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount, type VueWrapper } from "@vue/test-utils";
import { nextTick } from "vue";
import ButtonTooltipHost from "./ButtonTooltipHost.vue";

let wrapper: VueWrapper;
function button(markup = '<button aria-label="打开侧边栏"><svg><path /></svg></button>'): HTMLElement {
  const region = document.createElement("div");
  region.innerHTML = markup;
  document.body.append(region);
  return region.firstElementChild as HTMLElement;
}
function over(element: Element): void {
  element.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
}
async function settle(): Promise<void> {
  await vi.advanceTimersByTimeAsync(350);
  await nextTick();
}
const hint = () => document.getElementById("pa-button-tooltip");

beforeEach(() => {
  vi.useFakeTimers();
  wrapper = mount(ButtonTooltipHost, { attachTo: document.body });
});
afterEach(() => {
  wrapper.unmount();
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("应用按钮提示", () => {
  it("悬停图标后显示功能名称，并保留已有辅助说明", async () => {
    const element = button();
    element.setAttribute("aria-describedby", "existing-help");
    over(element.querySelector("path")!);
    expect(hint()).toBeNull();
    await settle();
    expect(hint()?.textContent).toBe("打开侧边栏");
    expect(element.getAttribute("aria-describedby")).toBe("existing-help pa-button-tooltip");
    element.dispatchEvent(new MouseEvent("pointerout", { bubbles: true }));
    await nextTick();
    expect(hint()).toBeNull();
    expect(element.getAttribute("aria-describedby")).toBe("existing-help");
  });

  it("文字按钮、禁用按钮与后来插入的弹窗按钮均有提示", async () => {
    const element = button('<button disabled><svg><title>图标</title></svg>创建工作区<kbd>Ctrl+N</kbd></button>');
    over(element);
    await settle();
    expect(hint()?.textContent).toBe("创建工作区（当前不可用）");
    element.remove();
    await nextTick();
    await nextTick();
    expect(hint()).toBeNull();
    const dynamic = button('<button data-tooltip="保存当前设置">保存</button>');
    over(dynamic);
    await settle();
    expect(hint()?.textContent).toBe("保存当前设置");
  });

  it("支持键盘聚焦和 Esc 关闭，不改变按钮行为", async () => {
    const element = button('<button aria-labelledby="save-label"></button>');
    const label = document.createElement("span");
    label.id = "save-label";
    label.textContent = "保存设置";
    document.body.append(label);
    element.focus();
    await settle();
    expect(hint()?.textContent).toBe("保存设置");
    const escape = new KeyboardEvent("keydown", { key: "Escape", cancelable: true, bubbles: true });
    element.dispatchEvent(escape);
    await nextTick();
    expect(hint()).toBeNull();
    expect(document.activeElement).toBe(element);
    expect(escape.defaultPrevented).toBe(false);
  });

  it("保留原生与专用提示，避免重复展示", async () => {
    const native = button('<button title="刷新项目列表" aria-label="刷新"></button>');
    over(native);
    await settle();
    expect(hint()).toBeNull();
    expect(native.title).toBe("刷新项目列表");
    const dedicated = button('<span class="pa-tooltip" data-tip="已有说明"><button>新建</button></span>');
    over(dedicated.querySelector("button")!);
    await settle();
    expect(hint()).toBeNull();
    const described = button('<button aria-describedby="existing-tooltip">任务名称</button>');
    const existing = button('<span id="existing-tooltip" role="tooltip">已有任务详情</span>');
    over(described);
    await settle();
    expect(hint()).toBeNull();
    expect(existing.isConnected).toBe(true);
  });

  it("按钮名称和禁用状态变化时更新说明", async () => {
    const element = button();
    over(element);
    await settle();
    element.setAttribute("aria-label", "收起侧边栏");
    element.setAttribute("aria-disabled", "true");
    await nextTick();
    await nextTick();
    expect(hint()?.textContent).toBe("收起侧边栏（当前不可用）");
    element.setAttribute("title", "专用提示");
    await nextTick();
    await nextTick();
    expect(hint()).toBeNull();
  });

  it("快速移出或切换按钮时，不显示过期提示", async () => {
    const first = button();
    over(first);
    first.dispatchEvent(new MouseEvent("pointerout", { bubbles: true }));
    await settle();
    expect(hint()).toBeNull();
    over(first);
    const second = button('<button>取消</button>');
    over(second);
    await settle();
    expect(hint()?.textContent).toBe("取消");
    expect(first.hasAttribute("aria-describedby")).toBe(false);
    second.remove();
    await nextTick();
    await nextTick();
    expect(hint()).toBeNull();
  });

  it.each(["scroll", "resize", "blur", "pointerdown"])("%s 时及时关闭提示", async eventName => {
    const element = button();
    over(element);
    await settle();
    (eventName === "resize" || eventName === "blur" ? window : document).dispatchEvent(new Event(eventName));
    await nextTick();
    expect(hint()).toBeNull();
  });

  it("无名称的控件不生成误导说明，卸载清理定时器和监听", async () => {
    const unnamed = button('<button><svg /></button>');
    over(unnamed);
    await settle();
    expect(hint()).toBeNull();
    const element = button();
    over(element);
    wrapper.unmount();
    await settle();
    expect(hint()).toBeNull();
    over(element);
    expect(vi.getTimerCount()).toBe(0);
    expect(element.hasAttribute("aria-describedby")).toBe(false);
  });
});
