import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import ThreadHeader from "./ThreadHeader.vue";

function mountHeader(props: Record<string, unknown> = {}) {
  return mount(ThreadHeader, {
    props: {
      title: "修复窄屏侧栏遮挡",
      projectName: "PrivateAgent",
      branchLabel: "feature/coding-workbench",
      headSha: "abcdef1234567890",
      gitDirty: true,
      ...props,
    },
  });
}

describe("ThreadHeader", () => {
  it("标题 + 项目/分支/HEAD/dirty 摘要", () => {
    const wrapper = mountHeader({ runStatus: "running" });
    expect(wrapper.find('[data-testid="coding-thread-header"]').text()).toContain("修复窄屏侧栏遮挡");
    expect(wrapper.text()).toContain("PrivateAgent");
    expect(wrapper.text()).toContain("feature/coding-workbench");
    expect(wrapper.text()).toContain("abcdef12");
    expect(wrapper.text()).toContain("有未提交更改");
  });

  it.each([
    ["running", "执行中"],
    ["waiting_approval", "等待审批"],
    ["completed", "已完成"],
    ["failed", "失败"],
    ["limit_exceeded", "达到上限"],
  ] as const)("run 状态 %s 徽标为 %s", (status, label) => {
    const wrapper = mountHeader({ runStatus: status });
    expect(wrapper.find('[data-testid="thread-run-status"]').text()).toContain(label);
  });

  it("运行中可取消、有计划可切换浮层", async () => {
    const wrapper = mountHeader({ runStatus: "waiting_approval", planAvailable: true, planOpen: false, cancellable: true });
    await wrapper.find('[data-testid="thread-cancel"]').trigger("click");
    expect(wrapper.emitted("cancel")).toBeTruthy();
    const toggle = wrapper.find('[data-testid="thread-plan-toggle"]');
    expect(toggle.attributes("aria-expanded")).toBe("false");
    await toggle.trigger("click");
    expect(wrapper.emitted("toggle-plan")).toBeTruthy();
  });

  it("终态隐藏停止按钮；返回首页事件", async () => {
    const wrapper = mountHeader({ runStatus: "completed" });
    expect(wrapper.find('[data-testid="thread-cancel"]').exists()).toBe(false);
    await wrapper.find('[data-testid="thread-back-home"]').trigger("click");
    expect(wrapper.emitted("back-home")).toBeTruthy();
  });
});
