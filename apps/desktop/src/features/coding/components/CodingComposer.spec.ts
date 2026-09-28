import { describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { nextTick } from "vue";
import CodingComposer from "./CodingComposer.vue";
import { createCodingWorkspaceStore } from "../model/codingWorkspaceStore";
import type { CodingFileHint } from "../model/runContracts";
import { listSkills } from "../api/skills";

vi.mock("../api/skills", () => ({ listSkills: vi.fn() }));

const HINTS: CodingFileHint[] = [
  { relPath: "src/features/coding/components/CodingSidebar.vue", name: "CodingSidebar.vue", language: "vue" },
  { relPath: "src/features/coding/components/CodingHome.vue", name: "CodingHome.vue", language: "vue" },
];

function profilesStore() {
  return createCodingWorkspaceStore({
    health: async () => true,
    projects: async () => [{ id: 1, name: "P", status: "active", updatedAt: "" }],
    workspaces: async () => [],
    threads: async () => [],
    modelProfiles: async () => ({
      status: "ok",
      profiles: [
        {
          id: "local-coder",
          provider: "ollama",
          displayName: "Qwen3 Coder",
          modelName: "qwen3-coder:30b",
          isDefault: true,
          isLocal: true,
          contextTokens: 32768,
          reasoningEfforts: ["low", "medium", "high"],
        },
      ],
    }),
  });
}

function mountComposer(props: Record<string, unknown> = {}) {
  const searchFiles = vi.fn(async (query: string) =>
    query ? HINTS.filter((hint) => hint.relPath.includes(query)) : HINTS
  );
  const wrapper = mount(CodingComposer, {
    props: { searchFiles, ...props },
    attachTo: document.body,
  });
  return { wrapper, searchFiles };
}

async function setInputValue(wrapper: ReturnType<typeof mount>, value: string, caret?: number) {
  const input = wrapper.find('[data-testid="coding-composer-input"]');
  await input.setValue(value);
  const el = input.element as HTMLTextAreaElement;
  el.setSelectionRange(caret ?? value.length, caret ?? value.length);
  await input.trigger("input");
}

describe("CodingComposer", () => {
  it("/skill 按需读取技能，选择后插入引用，不发送内置命令", async () => {
    vi.mocked(listSkills).mockResolvedValue({ items: [
      { id: "project:review", name: "project-review", description: "审查项目", scope: "project", version: "v1", enabled: true, missing_dependencies: [], error: null },
      { id: "project:disabled", name: "disabled", description: "停用", scope: "project", version: "v1", enabled: false, missing_dependencies: [], error: null },
    ] });
    const store = profilesStore();
    store.selectedProjectId.value = 1;
    const { wrapper } = mountComposer({ store });
    expect(wrapper.find('[data-testid="composer-skill-pop"]').exists()).toBe(false);
    await setInputValue(wrapper, "/ski");
    await wrapper.get('[data-testid="composer-slash-skill"]').trigger("click");
    await flushPromises();
    expect(listSkills).toHaveBeenCalledWith(1, expect.any(AbortSignal));
    const picker = wrapper.get('[data-testid="composer-skill-pop"]');
    expect(picker.text()).not.toContain("disabled");
    await picker.findAll("button").find(button => button.text() === "project-review")!.trigger("click");
    expect((wrapper.get("textarea").element as HTMLTextAreaElement).value).toBe("$project:review");
    expect(wrapper.emitted("send")).toBeUndefined();
    expect(wrapper.find('[data-testid="composer-skill-pop"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("/skill 回车仅打开选择器，无项目时给出提示", async () => {
    const { wrapper } = mountComposer();
    await setInputValue(wrapper, "/skill");
    await wrapper.get("textarea").trigger("keydown", { key: "Enter" });
    expect(wrapper.text()).toContain("请先选择项目");
    expect(wrapper.emitted("send")).toBeUndefined();
    await wrapper.get("textarea").trigger("keydown", { key: "Escape" });
    expect(wrapper.find('[data-testid="composer-skill-pop"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("模型 ID 使用完整文字，选择默认模型也不显示默认前缀", async () => {
    const store = profilesStore();
    await store.bootstrap();
    const { wrapper } = mountComposer({ store });
    expect(wrapper.get(".model-selection-label").text()).toBe("qwen3-coder:30b");
    expect(wrapper.get('[data-testid="composer-model"] option').text()).toBe("qwen3-coder:30b");
    expect(wrapper.get(".model-select").attributes("title")).toBe("qwen3-coder:30b");
    wrapper.unmount();
  });

  it("切换模型清除不支持的强度，发送新模型和默认强度", async () => {
    const store = profilesStore();
    await store.bootstrap();
    const models = store.modelProfiles.value;
    if (models?.status !== "ok") throw new Error("测试模型能力未加载");
    models.profiles.push({
      ...models.profiles[0], id: "qwen-flash", modelName: "qwen-3.8-flash",
      isDefault: false, reasoningEfforts: ["low"],
    });
    const { wrapper } = mountComposer({ store });
    await wrapper.get('[data-testid="composer-effort"]').trigger("click");
    await wrapper.get('[data-testid="model-strength-slider"]').setValue("3");
    expect(wrapper.get('[data-testid="composer-effort"]').text()).toBe("高");
    await wrapper.get('[data-testid="composer-model"]').setValue("qwen-flash");
    expect(wrapper.get(".model-selection-label").text()).toBe("qwen-3.8-flash");
    expect(wrapper.get('[data-testid="composer-effort"]').text()).toBe("默认");
    expect(wrapper.find('[data-testid="model-strength-popover"]').exists()).toBe(false);
    await setInputValue(wrapper, "检查项目");
    await wrapper.get('[data-testid="coding-composer-send"]').trigger("click");
    expect(wrapper.emitted("send")?.[0]?.[0]).toMatchObject({ modelProfileId: "qwen-flash", reasoningEffort: null });
    wrapper.unmount();
  });

  it("规划能力启用后 /plan 切换真实模式并保留正文", async () => {
    const store = profilesStore();
    store.capabilities.value = { coding_planning_contract_version: "1.0", coding_recovery_contract_version: "1.0" };
    const { wrapper } = mountComposer({ store });
    await setInputValue(wrapper, "/plan 调整模块职责");
    await wrapper.find('[data-testid="coding-composer-send"]').trigger("click");
    expect(wrapper.emitted("send")?.[0]?.[0]).toMatchObject({ message: "调整模块职责", collaborationMode: "plan" });
    wrapper.unmount();
  });

  it("仅输入 /plan 不会创建空任务，修改计划入口保留已有草稿", async () => {
    const store = profilesStore();
    store.capabilities.value = { coding_planning_contract_version: "1.0", coding_recovery_contract_version: "1.0" };
    const { wrapper } = mountComposer({ store });
    await setInputValue(wrapper, "/plan");
    await wrapper.find('[data-testid="coding-composer-send"]').trigger("click");
    expect(wrapper.emitted("send")).toBeUndefined();
    await setInputValue(wrapper, "请保留这段草稿");
    await wrapper.setProps({ restoreRequest: { message: "", seq: 1, collaborationMode: "plan" } });
    expect((wrapper.get('[data-testid="coding-composer-input"]').element as HTMLTextAreaElement).value).toBe("请保留这段草稿");
    wrapper.unmount();
  });
  it("发送载荷：文本 + 权限/模型/推理选择；发送后清空", async () => {
    const store = profilesStore();
    // 直接注入模型能力（store 未 bootstrap，避免网络）
    store.modelProfiles.value = {
      status: "ok",
      profiles: [
        {
          id: "local-coder",
          provider: "ollama",
          displayName: "Qwen3 Coder",
          modelName: "qwen3-coder:30b",
          isDefault: true,
          isLocal: true,
          contextTokens: 32768,
          reasoningEfforts: ["low", "medium", "high"],
        },
      ],
    };
    const { wrapper } = mountComposer({ store });
    const modelOptions = wrapper.findAll('[data-testid="composer-model"] option');
    expect(modelOptions[1].text()).toBe("qwen3-coder:30b");
    expect(modelOptions[1].text()).not.toContain("Qwen3 Coder");
    expect(wrapper.get('[data-testid="composer-effort"]').text()).toBe("默认");
    await setInputValue(wrapper, "修复侧栏遮挡");
    await wrapper.find('[data-testid="composer-permission"]').setValue("confirm");
    await wrapper.find('[data-testid="composer-model"]').setValue("local-coder");
    await wrapper.get('[data-testid="composer-effort"]').trigger("click");
    await wrapper.get('[data-testid="model-strength-slider"]').setValue("3");
    await wrapper.find('[data-testid="coding-composer-send"]').trigger("click");
    const payload = wrapper.emitted("send")?.[0]?.[0];
    expect(payload).toMatchObject({
      message: "修复侧栏遮挡",
      permissionMode: "confirm",
      modelProfileId: "local-coder",
      reasoningEffort: "high",
    });
    expect((wrapper.find('[data-testid="coding-composer-input"]').element as HTMLTextAreaElement).value).toBe("");
  });

  it("@ 发现：输入 @ 触发搜索、选择后以 chip 呈现并附进消息", async () => {
    const { wrapper, searchFiles } = mountComposer();
    await setInputValue(wrapper, "看一下 @Coding");
    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(searchFiles).toHaveBeenCalledWith("Coding");
    const item = wrapper.find('[data-testid="composer-at-item-0"]');
    expect(item.text()).toContain("CodingSidebar.vue");
    await item.trigger("click");
    expect(wrapper.find('[data-testid="composer-chips"]').text()).toContain(
      "src/features/coding/components/CodingSidebar.vue"
    );
    await wrapper.find('[data-testid="coding-composer-send"]').trigger("click");
    const payload = wrapper.emitted("send")?.[0]?.[0] as { message: string };
    expect(payload.message).toContain("@src/features/coding/components/CodingSidebar.vue");
  });

  it("/ 命令模板：/ 触发列表，选择后填入提示词", async () => {
    const { wrapper } = mountComposer();
    await setInputValue(wrapper, "/fix");
    await wrapper.find('[data-testid="composer-slash-fix-test"]').trigger("click");
    const input = wrapper.find('[data-testid="coding-composer-input"]').element as HTMLTextAreaElement;
    expect(input.value).toContain("失败的测试");
  });

  it("草稿按 thread 保存且切换 thread 互不串线", async () => {
    const { wrapper } = mountComposer({ threadId: 11 });
    await setInputValue(wrapper, "线程 11 的草稿");
    await wrapper.setProps({ threadId: 12 });
    expect((wrapper.find('[data-testid="coding-composer-input"]').element as HTMLTextAreaElement).value).toBe("");
    await wrapper.setProps({ threadId: 11 });
    expect((wrapper.find('[data-testid="coding-composer-input"]').element as HTMLTextAreaElement).value).toBe(
      "线程 11 的草稿"
    );
  });

  it("busy/preview 模式禁用发送", async () => {
    const { wrapper } = mountComposer({ busy: true });
    await setInputValue(wrapper, "内容");
    expect(wrapper.find('[data-testid="coding-composer-send"]').attributes("disabled")).toBeDefined();
  });

  it("底部工具栏使用紧凑上下文用量圆环", () => {
    const { wrapper } = mountComposer({ threadId: 11 });
    expect(wrapper.find('[data-testid="coding-composer-input"]').attributes("rows")).toBe("2");
    expect(wrapper.find('[data-testid="coding-composer-send"]').classes()).toContain("pa-btn--sm");
    const ring = wrapper.find('[data-testid="context-usage-ring"]');
    expect(ring.exists()).toBe(true);
    expect(ring.attributes("aria-label")).toContain("上下文用量");
  });

  it("尚未创建对话时保留上下文入口，不伪造用量", () => {
    const { wrapper } = mountComposer({ threadId: null });
    expect(wrapper.get('[data-testid="context-usage-ring"]').attributes("aria-label")).toContain("开始对话后显示用量");
    const controls = wrapper.get(".composer-model-controls");
    expect(controls.element.children[0].getAttribute("data-testid")).toBe("context-usage-ring");
    expect(controls.element.children[1].classList.contains("model-select")).toBe(true);
    expect(controls.element.children[2].classList.contains("model-strength")).toBe(true);
    wrapper.unmount();
  });

  it("加号按钮打开项目文件引用入口", async () => {
    const searchFiles = vi.fn().mockResolvedValue(HINTS);
    const { wrapper } = mountComposer({ searchFiles });
    await wrapper.find('[data-testid="coding-composer-input"]').setValue("");
    await wrapper.find('[data-testid="composer-add-context"]').trigger("click");
    await nextTick();
    const input = wrapper.find('[data-testid="coding-composer-input"]');
    expect((input.element as HTMLTextAreaElement).value).toBe("@");
    expect(wrapper.find('[data-testid="composer-at-pop"]').exists()).toBe(true);
    expect(searchFiles).toHaveBeenCalledWith("");
  });

  it("桌面附件选择成功后直接加入上下文 chip", async () => {
    const pickAttachment = vi.fn().mockResolvedValue({
      relPath: ".privateagent/attachments/a1-report.pdf",
      name: "report.pdf",
      language: null,
    });
    const { wrapper } = mountComposer({ pickAttachment });
    await wrapper.find('[data-testid="composer-add-context"]').trigger("click");
    await nextTick();
    expect(pickAttachment).toHaveBeenCalledOnce();
    expect(wrapper.find('[data-testid="composer-chips"]').text()).toContain("report.pdf");
  });

  it("默认模型显示模型 ID 与推理强度，页面不单独展示上下文上限", async () => {
    const store = profilesStore();
    store.modelProfiles.value = {
      status: "ok",
      profiles: [
        {
          id: "local-coder",
          provider: "ollama",
          displayName: "Qwen3 Coder",
          modelName: "qwen3-coder:30b",
          isDefault: true,
          isLocal: true,
          contextTokens: 32768,
          reasoningEfforts: ["low", "medium", "high"],
        },
      ],
    };
    const { wrapper } = mountComposer({ store });
    await nextTick();
    expect(wrapper.find('[data-testid="composer-model"] option').text()).toContain(
      "qwen3-coder:30b"
    );
    expect(wrapper.find('[data-testid="composer-effort"]').attributes("disabled")).toBeUndefined();
    expect(wrapper.find('[data-testid="composer-context-limit"]').exists()).toBe(false);
    await setInputValue(wrapper, "使用默认模型");
    await wrapper.find('[data-testid="coding-composer-send"]').trigger("click");
    expect(wrapper.emitted("send")?.[0]?.[0]).toMatchObject({
      modelProfileId: "local-coder",
    });
  });

  it("运行时右下角按钮发出暂停，暂停请求期间禁用按钮", async () => {
    const { wrapper } = mountComposer({ running: true });
    const pause = wrapper.get('[data-testid="coding-composer-pause"]');
    expect(pause.attributes("aria-label")).toBe("暂停任务");
    await pause.trigger("click");
    expect(wrapper.emitted("pause")).toHaveLength(1);
    expect(wrapper.emitted("stop")).toBeUndefined();
    await wrapper.setProps({ pausing: true });
    expect(pause.attributes("disabled")).toBeDefined();
    expect(pause.attributes("aria-label")).toBe("正在暂停任务");
    await pause.trigger("click");
    expect(wrapper.emitted("pause")).toHaveLength(1);
    await wrapper.setProps({ pausing: false, paused: true });
    expect(wrapper.find('[data-testid="coding-composer-pause"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("↑/↓ 按时间浏览已提交输入，并在越过最新项后恢复当前草稿", async () => {
    const { wrapper } = mountComposer({
      inputHistory: ["第一次输入", "第二次输入"],
    });
    await setInputValue(wrapper, "尚未发送的草稿");
    const input = wrapper.find('[data-testid="coding-composer-input"]');

    await input.trigger("keydown", { key: "ArrowUp" });
    expect((input.element as HTMLTextAreaElement).value).toBe("第二次输入");
    await input.trigger("keydown", { key: "ArrowUp" });
    expect((input.element as HTMLTextAreaElement).value).toBe("第一次输入");
    await input.trigger("keydown", { key: "ArrowDown" });
    expect((input.element as HTMLTextAreaElement).value).toBe("第二次输入");
    await input.trigger("keydown", { key: "ArrowDown" });
    expect((input.element as HTMLTextAreaElement).value).toBe("尚未发送的草稿");
  });

  it("多行输入只在首行 ↑ 触发历史，历史里的 @ 行恢复为上下文 chip", async () => {
    const { wrapper } = mountComposer({
      inputHistory: ["检查文件\n@src/main.ts"],
    });
    await setInputValue(wrapper, "第一行\n第二行");
    const input = wrapper.find('[data-testid="coding-composer-input"]');
    const element = input.element as HTMLTextAreaElement;

    element.setSelectionRange(element.value.length, element.value.length);
    await input.trigger("keydown", { key: "ArrowUp" });
    expect(element.value).toBe("第一行\n第二行");

    element.setSelectionRange(2, 2);
    await input.trigger("keydown", { key: "ArrowUp" });
    expect(element.value).toBe("检查文件");
    expect(wrapper.find('[data-testid="composer-chips"]').text()).toContain("src/main.ts");
  });
});
