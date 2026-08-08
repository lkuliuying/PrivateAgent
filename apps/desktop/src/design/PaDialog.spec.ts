import { afterEach, describe, expect, it } from "vitest";
import { mount, type VueWrapper } from "@vue/test-utils";
import PaDialog from "./PaDialog.vue";
import PaInlineNotice from "./PaInlineNotice.vue";
import PaDropdownMenu from "./PaDropdownMenu.vue";

function dialogInBody() {
  return document.body.querySelector('[role="dialog"]') as HTMLElement | null;
}

describe("PaDialog", () => {
  let mounted: VueWrapper[] = [];

  function mountDialog(
    props: { open: boolean; title: string; width?: number; dismissible?: boolean },
    slots?: Record<string, string>
  ) {
    const wrapper = mount(PaDialog, { props, slots });
    mounted.push(wrapper);
    return wrapper;
  }

  afterEach(() => {
    for (const wrapper of mounted) wrapper.unmount();
    mounted = [];
    document.body.innerHTML = "";
  });

  it("关闭时不渲染内容", () => {
    mountDialog({ open: false, title: "确认" });
    expect(dialogInBody()).toBeNull();
  });

  it("打开时渲染 dialog 到 body 并标记模态", async () => {
    mountDialog(
      { open: true, title: "确认" },
      { default: "<button id='first'>确定</button><button id='second'>取消</button>" }
    );
    await Promise.resolve();
    const dialog = dialogInBody();
    expect(dialog).not.toBeNull();
    expect(dialog!.getAttribute("aria-modal")).toBe("true");
    expect(dialog!.getAttribute("aria-label")).toBe("确认");
  });

  it("Esc 触发 close（可关闭时）", async () => {
    const wrapper = mountDialog({ open: true, title: "确认" });
    await Promise.resolve();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(wrapper.emitted("close")).toBeTruthy();
  });

  it("destroy 后清理 body 内容", () => {
    mountDialog({ open: true, title: "确认" });
    for (const wrapper of mounted) wrapper.unmount();
    mounted = [];
    expect(dialogInBody()).toBeNull();
  });
});

describe("PaInlineNotice", () => {
  it("danger 使用 alert 角色", () => {
    const wrapper = mount(PaInlineNotice, { props: { tone: "danger" }, slots: { default: "出错" } });
    expect(wrapper.attributes("role")).toBe("alert");
  });
  it("info 使用 status 角色", () => {
    const wrapper = mount(PaInlineNotice, { props: { tone: "info" }, slots: { default: "提示" } });
    expect(wrapper.attributes("role")).toBe("status");
  });
});

describe("PaDropdownMenu", () => {
  const items = [
    { key: "a", label: "导出" },
    { key: "b", label: "删除", danger: true },
  ];

  it("选择菜单项发出事件并关闭", async () => {
    const wrapper = mount(PaDropdownMenu, { props: { label: "更多", items } });
    await wrapper.find(".pa-menu-trigger").trigger("click");
    const menuItems = wrapper.findAll('[role="menuitem"]');
    expect(menuItems).toHaveLength(2);
    await menuItems[1].trigger("click");
    expect(wrapper.emitted("select")?.[0]).toEqual(["b"]);
    expect(wrapper.find(".pa-menu-list").exists()).toBe(false);
  });

  it("触发按钮 aria-haspopup 与展开态", async () => {
    const wrapper = mount(PaDropdownMenu, { props: { label: "更多", items } });
    expect(wrapper.find(".pa-menu-trigger").attributes("aria-haspopup")).toBe("menu");
    await wrapper.find(".pa-menu-trigger").trigger("click");
    expect(wrapper.find(".pa-menu-trigger").attributes("aria-expanded")).toBe("true");
  });
});
