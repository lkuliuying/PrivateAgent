import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import WorkspaceShell from "./WorkspaceShell.vue";

describe("WorkspaceShell", () => {
  it("提供主工作区、辅助区、状态区和跳转链接语义", () => {
    const wrapper = mount(WorkspaceShell, {
      props: {
        title: "对话工作区",
        showList: true,
        inspectorOpen: true,
        inspectorToggleable: true,
      },
      slots: {
        list: "会话列表内容",
        default: "主要内容",
        inspector: "检查器内容",
        statusbar: "服务正常",
      },
    });

    expect(wrapper.get(".workspace-skip-link").attributes("href")).toBe(
      "#workspace-main"
    );
    expect(wrapper.get("main").attributes()).toMatchObject({
      id: "workspace-main",
      tabindex: "-1",
      "aria-labelledby": "workspace-title",
    });
    expect(wrapper.get("h1").text()).toBe("对话工作区");
    expect(wrapper.get(".workspace-list").element.tagName).toBe("ASIDE");
    expect(wrapper.get(".workspace-inspector").attributes()).toMatchObject({
      id: "workspace-inspector",
      "aria-label": "检查器",
    });
    expect(wrapper.get(".workspace-statusbar").element.tagName).toBe("FOOTER");
    expect(wrapper.get(".inspector-toggle").attributes("aria-controls")).toBe(
      "workspace-inspector"
    );
  });

  it("没有顶栏时直接用标题标记 main", () => {
    const wrapper = mount(WorkspaceShell, {
      props: { title: "今日", showTopbar: false, showStatusbar: false },
    });

    expect(wrapper.get("main").attributes("aria-label")).toBe("今日");
    expect(wrapper.find("#workspace-title").exists()).toBe(false);
    expect(wrapper.find("footer").exists()).toBe(false);
  });

  it("检查器按钮保持既有事件边界", async () => {
    const wrapper = mount(WorkspaceShell, {
      props: {
        title: "对话",
        inspectorOpen: false,
        inspectorToggleable: true,
      },
    });

    await wrapper.get(".inspector-toggle").trigger("click");
    expect(wrapper.emitted("toggle-inspector")).toHaveLength(1);
  });
});
