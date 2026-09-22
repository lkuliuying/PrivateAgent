import { afterEach, describe, expect, it, vi } from "vitest";
import { ref, shallowRef } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import CodingThreadWorkspace from "./CodingThreadWorkspace.vue";
import { createCodingWorkspacePreviewStore } from "../dev/codingHomePreview";
import RunTranscript from "./RunTranscript.vue";
import FileWorkspace from "./FileWorkspace.vue";
import * as workspaceApi from "../api/workspaceFiles";
import * as projectsApi from "../api/projects";
import * as streamApi from "../composables/useRunStream";
import { createRunProjection } from "../model/runProjector";
import { useNotifications } from "../../../stores/notifications";

const mounted: { unmount: () => void }[] = [];
afterEach(() => { mounted.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = ""; vi.restoreAllMocks(); useNotifications().clearToasts(); useNotifications().clearHistory(); });

function mockFileApi() {
  vi.spyOn(workspaceApi, "listWorkspaceFiles").mockResolvedValue({ entries: [], next_cursor: null, total: 0 });
  return vi.spyOn(workspaceApi, "readWorkspaceFile").mockResolvedValue({ rel_path: "src/app.py", content: "first\nsecond", sha256: "a".repeat(64), offset: 0, next_offset: null, total_chars: 12 });
}

async function mountWorkspace(selectThreadId?: number) {
  const store = createCodingWorkspacePreviewStore("ready");
  await flushPromises();
  if (selectThreadId !== undefined) store.selectThread(selectThreadId);
  const wrapper = mount(CodingThreadWorkspace, { props: { store }, attachTo: document.body });
  mounted.push(wrapper);
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
  it("输出文件点击在任务工作区打开，只在绝对引用时查询路径", async () => {
    const read = mockFileApi();
    const root = vi.spyOn(projectsApi, "fetchCodingWorkspacePath").mockResolvedValue("F:/My Project");
    const { wrapper } = await mountWorkspace(11);
    try {
      wrapper.getComponent(RunTranscript).vm.$emit("open-file", { path: "src/app.py", line: 2 });
      await flushPromises();
      expect(root).not.toHaveBeenCalled();
      expect(read.mock.calls[0].slice(0, 3)).toEqual([1, 101, "src/app.py"]);
      expect(wrapper.getComponent(FileWorkspace).get('.code-line--target').text()).toContain("second");
      wrapper.getComponent(RunTranscript).vm.$emit("open-file", { path: "F:/My Project/docs/readme.md", line: 1 });
      await flushPromises();
      expect(root).toHaveBeenCalledWith(1, 101);
      expect(read.mock.lastCall?.slice(0, 3)).toEqual([1, 101, "docs/readme.md"]);
    } finally { wrapper.unmount(); }
  });

  it("产物使用运行绑定工作区，不跟随当前目录选择", async () => {
    const read = mockFileApi();
    const projection = createRunProjection("bound-run");
    projection.projectId = 1;
    projection.workspaceId = 102;
    projection.sessionId = 11;
    vi.spyOn(streamApi, "useRunStream").mockReturnValue({ projection: shallowRef(projection), phase: ref("idle"), connectionError: ref(null), createErrorCode: ref(null), startRun: vi.fn(), attachRun: vi.fn(), cancelActive: vi.fn(), retryConnection: vi.fn(), detach: vi.fn() });
    const { wrapper } = await mountWorkspace(11);
    try {
      wrapper.getComponent(RunTranscript).vm.$emit("open-file", { path: "src/app.py" });
      await flushPromises();
      expect(read.mock.calls[0].slice(0, 3)).toEqual([1, 102, "src/app.py"]);
    } finally { wrapper.unmount(); }
  });

  it("工作区外引用不读取文件，通知不保存本机绝对路径", async () => {
    const read = mockFileApi();
    vi.spyOn(projectsApi, "fetchCodingWorkspacePath").mockResolvedValue("F:/My Project");
    const { wrapper } = await mountWorkspace(11);
    try {
      wrapper.getComponent(RunTranscript).vm.$emit("open-file", { path: "F:/Private/account.txt" });
      await flushPromises();
      expect(read).not.toHaveBeenCalled();
      expect(wrapper.findComponent(FileWorkspace).exists()).toBe(false);
      const history = JSON.stringify(useNotifications().history.value);
      expect(history).toContain("工作区之外");
      expect(history).not.toContain("F:/Private");
    } finally { wrapper.unmount(); }
  });

  it("绝对路径读取未完成时切换任务，旧结果不能重新打开文件面板", async () => {
    const read = mockFileApi();
    let finish!: (path: string) => void;
    vi.spyOn(projectsApi, "fetchCodingWorkspacePath").mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const { wrapper, store } = await mountWorkspace(11);
    try {
      wrapper.getComponent(RunTranscript).vm.$emit("open-file", { path: "F:/Old/src/app.py" });
      store.selectThread(12);
      await flushPromises();
      finish("F:/Old");
      await flushPromises();
      expect(read).not.toHaveBeenCalled();
      expect(wrapper.findComponent(FileWorkspace).exists()).toBe(false);
    } finally { wrapper.unmount(); }
  });

  it("获取绝对目录失败时明确反馈，不尝试猜测相对路径", async () => {
    const read = mockFileApi();
    vi.spyOn(projectsApi, "fetchCodingWorkspacePath").mockRejectedValue(new Error("unavailable"));
    const { wrapper } = await mountWorkspace(11);
    try {
      wrapper.getComponent(RunTranscript).vm.$emit("open-file", { path: "F:/Project/src/app.py" });
      await flushPromises();
      expect(read).not.toHaveBeenCalled();
      expect(useNotifications().toasts.value.some(toast => toast.message?.includes("任务工作区暂不可用"))).toBe(true);
    } finally { wrapper.unmount(); }
  });
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
    expect(input.attributes("placeholder")).toBe("描述你希望完成的任务");
  });

  it("无 run 时无状态徽标/停止按钮；计划入口仅在计划存在时出现", async () => {
    const { wrapper } = await mountWorkspace(11);
    expect(wrapper.find('[data-testid="thread-run-status"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="thread-cancel"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="thread-plan-toggle"]').exists()).toBe(false);
  });

  it("无 run 时正式观察入口显示空态，不请求虚构运行", async () => {
    const { wrapper } = await mountWorkspace(11);
    await wrapper.get('[data-testid="thread-environment-toggle"]').trigger("click");
    await wrapper.get('[data-testid="thread-menu-toggle"]').trigger("click");
    await wrapper.findAll('[role="menuitem"]').find(item => item.text() === "观察诊断")!.trigger("click");
    expect(wrapper.get('[role="tabpanel"]').text()).toContain("任务运行后可查看验收结论与关联事件");
    expect(wrapper.find('[data-testid="run-observer-panel"]').exists()).toBe(false);
    wrapper.unmount();
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
      expect(wrapper.find('[data-testid="coding-instruction-index"]').exists()).toBe(true);
      const instruction = wrapper.find('[data-testid="coding-instruction-0"]');
      expect(instruction.exists()).toBe(true);
      expect(instruction.text()).toBe("");
      expect(instruction.attributes("aria-label")).toContain("定位到用户指令");
      expect(instruction.find(".instruction-index__tick").exists()).toBe(true);
      await instruction.trigger("click");
      expect(instruction.classes()).toContain("active");
      expect(wrapper.find('[data-testid="tool-command"]').exists()).toBe(true);
      // W6-R：命令文本/目录在详情折叠区，展开后呈现。
      await wrapper.find('[data-testid="command-output-toggle"]').trigger("click");
      expect(wrapper.find('[data-testid="command-line"]').exists()).toBe(true);
      expect(wrapper.find('[data-testid="command-cwd"]').exists()).toBe(true);
      // 上下文已归入环境面板，继续验证当前入口能呈现事实内容。
      await wrapper.get('[data-testid="thread-environment-toggle"]').trigger("click");
      expect(wrapper.find(".worktree-panel").exists()).toBe(false);
      await wrapper.get("#environment-tab-context").trigger("click");
      await flushPromises();
      expect(wrapper.find('.environment-panel [data-testid="context-drawer"]').exists()).toBe(true);
      wrapper.unmount();
    } finally {
      history.replaceState(null, "", "/");
    }
  });
});
