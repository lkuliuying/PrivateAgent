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

/** 基于 DOM 条件的有界等待（替代固定延时：动态 import 完成时机随套件负载漂移）。*/
async function waitForCondition(
  check: () => boolean,
  timeoutMs = 4000,
  stepMs = 10
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await flushPromises();
    if (check()) return;
    await new Promise((resolve) => setTimeout(resolve, stepMs));
  }
  await flushPromises();
  if (!check()) throw new Error(`waitForCondition 超时（${timeoutMs}ms）`);
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
    const input = wrapper.find('[data-testid="coding-composer-input"]');
    expect(input.exists()).toBe(true);
    expect(input.attributes("placeholder")).toBe("随心输入");
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

  it("?coding-run-preview=command-output：预览夹具投影到工具卡与命令卡（E2E 阻断1 守护）", async () => {
    history.replaceState(null, "", "?coding=1&coding-run-preview=command-output");
    try {
      const { wrapper } = await mountWorkspace(11);
      // 预览为动态 import：等待工具卡渲染（状态条件，非固定延时）。
      await waitForCondition(() =>
        wrapper.find('[data-testid="tool-command"]').exists()
      );
      expect(wrapper.find('[data-testid="transcript-empty"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="tool-command"]').exists()).toBe(true);
      // W6-R：命令文本/目录在详情折叠区，展开后呈现。
      await wrapper.find('[data-testid="command-output-toggle"]').trigger("click");
      expect(wrapper.find('[data-testid="command-line"]').exists()).toBe(true);
      expect(wrapper.find('[data-testid="command-cwd"]').exists()).toBe(true);
      // 上下文抽屉：头部开关打开后呈现事实面板（E2E 阻断1 同案复现位）
      await wrapper.find('[data-testid="thread-context-toggle"]').trigger("click");
      await flushPromises();
      expect(wrapper.find('[data-testid="context-drawer"]').exists()).toBe(true);
    } finally {
      history.replaceState(null, "", "/");
    }
  });
});
