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

describe("CodingThreadWorkspace（W1 占位形态）", () => {
  it("头部摘要：标题 + 项目 + 分支（公开事实，不猜测 run 状态）", async () => {
    const { wrapper } = await mountWorkspace(11);
    const header = wrapper.find('[data-testid="coding-thread-header"]');
    expect(header.text()).toContain("修复窄屏侧栏遮挡问题");
    expect(header.text()).toContain("PrivateAgent");
    // 线程 11 属 root 工作区（无分支名 → 根工作区标签）
    expect(header.text()).toContain("根工作区");
  });

  it("worktree 线程头部呈现分支名", async () => {
    const { wrapper } = await mountWorkspace(12);
    expect(wrapper.find('[data-testid="coding-thread-header"]').text()).toContain(
      "feature/coding-workbench"
    );
  });

  it("正文为 W2 交付说明，不含虚构的执行状态", async () => {
    const { wrapper } = await mountWorkspace(11);
    expect(wrapper.text()).toContain("任务页建设中");
    expect(wrapper.text()).toContain("RunTranscript");
  });

  it("回到首页：清线程选择并导航 coding 视图", async () => {
    const { wrapper, store } = await mountWorkspace(11);
    await wrapper.find("button.pa-button").trigger("click");
    expect(store.selectedThreadId.value).toBeNull();
    expect(wrapper.emitted("navigate")?.[0]).toEqual(["coding"]);
  });

  it("未选择线程时呈现空态", async () => {
    const { wrapper } = await mountWorkspace();
    expect(wrapper.text()).toContain("未选择任务");
  });
});
