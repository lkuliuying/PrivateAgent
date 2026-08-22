import { describe, expect, it } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import CodingThreadWorkspace from "./CodingThreadWorkspace.vue";
import { createCodingWorkspacePreviewStore } from "../dev/codingHomePreview";

async function mountWorkspace(selectThreadId?: number) {
  const store = createCodingWorkspacePreviewStore("ready");
  await flushPromises();
  if (selectThreadId !== undefined) store.selectThread(selectThreadId);
  const wrapper = mount(CodingThreadWorkspace, { props: { store }, attachTo: document.body });
  return { wrapper, store };
}

describe("CodingThreadWorkspace（W2 组装）", () => {
  it("头部摘要：标题 + 项目 + 分支（公开事实）", async () => {
    const { wrapper } = await mountWorkspace(11);
    const header = wrapper.find('[data-testid="coding-thread-header"]');
    expect(header.text()).toContain("修复窄屏侧栏遮挡问题");
    expect(header.text()).toContain("PrivateAgent");
    expect(header.text()).toContain("根工作区");
  });

  it("无 run 时：transcript 空态 + 输入器可用（Enter 发送语义存在）", async () => {
    const { wrapper } = await mountWorkspace(11);
    expect(wrapper.find('[data-testid="transcript-empty"]').exists()).toBe(true);
    const input = wrapper.find('[data-testid="coding-thread-composer-input"]');
    expect(input.exists()).toBe(true);
    expect(input.attributes("placeholder")).toContain("Enter 发送");
  });

  it("无 run 时无状态徽标/停止按钮；计划入口仅在计划存在时出现", async () => {
    const { wrapper } = await mountWorkspace(11);
    expect(wrapper.find('[data-testid="thread-run-status"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="thread-cancel"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="thread-plan-toggle"]').exists()).toBe(false);
  });

  it("回到首页：清线程选择并导航 coding 视图", async () => {
    const { wrapper, store } = await mountWorkspace(11);
    await wrapper.find('[data-testid="thread-back-home"]').trigger("click");
    expect(store.selectedThreadId.value).toBeNull();
    expect(wrapper.emitted("navigate")?.[0]).toEqual(["coding"]);
  });

  it("未选择线程时呈现空态", async () => {
    const { wrapper } = await mountWorkspace();
    expect(wrapper.text()).toContain("未选择任务");
  });
});
