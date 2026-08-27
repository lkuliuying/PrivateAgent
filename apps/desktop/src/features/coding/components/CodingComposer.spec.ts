import { describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { nextTick } from "vue";
import CodingComposer from "./CodingComposer.vue";
import { createCodingWorkspaceStore } from "../model/codingWorkspaceStore";
import type { CodingFileHint } from "../model/runContracts";

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
          isLocal: true,
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
          isLocal: true,
          reasoningEfforts: ["low", "medium", "high"],
        },
      ],
    };
    const { wrapper } = mountComposer({ store });
    await setInputValue(wrapper, "修复侧栏遮挡");
    await wrapper.find('[data-testid="composer-permission"]').setValue("confirm");
    await wrapper.find('[data-testid="composer-model"]').setValue("local-coder");
    await wrapper.find('[data-testid="composer-effort"]').setValue("high");
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

  it("running 时显示停止按钮并发出 stop", async () => {
    const { wrapper } = mountComposer({ running: true });
    const stop = wrapper.find('[data-testid="coding-composer-stop"]');
    expect(stop.exists()).toBe(true);
    await stop.trigger("click");
    expect(wrapper.emitted("stop")).toBeTruthy();
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
