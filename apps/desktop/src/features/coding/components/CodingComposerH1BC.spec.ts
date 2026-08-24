/**
 * v0.9.0 H1-B/H1-C（计划 §5.6/§5.7）· CodingComposer 纠偏行为测试
 *
 * 覆盖：
 * - 权限选择按会话持久化（切换对话不丢；只存合法枚举值）；
 * - 能力位不可用时选项在项旁说明原因（禁止无响应项）；
 * - 创建失败草稿回填（不丢失输入；@ 行还原为 chip）。
 */
import { beforeEach, describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import CodingComposer from "./CodingComposer.vue";
import { createCodingWorkspaceStore } from "../model/codingWorkspaceStore";

function baseStore() {
  return createCodingWorkspaceStore({
    health: async () => true,
    projects: async () => [],
    workspaces: async () => [],
    threads: async () => [],
    modelProfiles: async () => ({ status: "ok", profiles: [] }),
  });
}

function mountComposer(props: Record<string, unknown> = {}) {
  return mount(CodingComposer, {
    props: { store: baseStore(), ...props },
    attachTo: document.body,
  });
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("CodingComposer · H1-C 权限选择持久化", () => {
  it("权限选择写入会话级存储并在重新挂载后恢复", async () => {
    const store = baseStore();
    store.capabilities.value = {
      chat_execution_mode: "legacy",
      legacy_tool_planner_enabled: true,
      agent_read_only_tools_enabled: false,
      rag_chat_runtime_enabled: false,
      coding_workspace_auto_approve: true,
      coding_full_access_supported: true,
    };
    const wrapper = mountComposer({ store, threadId: 7 });
    await wrapper.find('[data-testid="composer-permission"]').setValue("workspace");
    expect(window.localStorage.getItem("pa_coding_permission_7")).toBe("workspace");
    wrapper.unmount();

    // 同一 thread 重新挂载：恢复会话级选择（不回到默认值）
    const store2 = baseStore();
    store2.capabilities.value = store.capabilities.value;
    const remounted = mountComposer({ store: store2, threadId: 7 });
    const select = remounted.find(
      '[data-testid="composer-permission"] select'
    ).exists()
      ? remounted.find('[data-testid="composer-permission"] select')
      : remounted.find('[data-testid="composer-permission"]');
    expect((select.element as HTMLSelectElement).value).toBe("workspace");
    remounted.unmount();
  });

  it("存储的非法值回落 confirm（不静默使用更高权限）", () => {
    window.localStorage.setItem("pa_coding_permission_9", "root");
    const wrapper = mountComposer({ threadId: 9 });
    const select = wrapper.find('[data-testid="composer-permission"]');
    expect((select.element as HTMLSelectElement).value).toBe("confirm");
    wrapper.unmount();
  });

  it("能力位缺失时不可用选项在项旁说明原因", () => {
    const wrapper = mountComposer({ threadId: 11 });
    const options = wrapper.findAll('[data-testid="composer-permission"] option');
    const workspaceOption = options.find((o) => o.attributes("value") === "workspace");
    const fullAccessOption = options.find((o) => o.attributes("value") === "full_access");
    expect(workspaceOption?.attributes("disabled")).toBeDefined();
    expect(workspaceOption?.text()).toContain("不可用");
    expect(fullAccessOption?.attributes("disabled")).toBeDefined();
    expect(fullAccessOption?.text()).toContain("不可用");
    wrapper.unmount();
  });
});

describe("CodingComposer · H1-B 创建失败草稿回填", () => {
  it("回填文本与 @ chip（不丢失输入）", async () => {
    const wrapper = mountComposer({ threadId: 21 });
    await wrapper.setProps({
      restoreRequest: { message: "检查本机服务状态\n@src/main.ts", seq: 1 },
    });
    const input = wrapper.find('[data-testid="coding-composer-input"]');
    expect((input.element as HTMLTextAreaElement).value).toBe("检查本机服务状态");
    expect(wrapper.find('[data-testid="composer-chips"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("src/main.ts");
    wrapper.unmount();
  });

  it("相同消息的重复回填通过 seq 触发（引用变化即应用）", async () => {
    const wrapper = mountComposer({ threadId: 22 });
    await wrapper.setProps({ restoreRequest: { message: "任务A", seq: 1 } });
    await wrapper.find('[data-testid="coding-composer-input"]').setValue("");
    await wrapper.setProps({ restoreRequest: { message: "任务A", seq: 2 } });
    const input = wrapper.find('[data-testid="coding-composer-input"]');
    expect((input.element as HTMLTextAreaElement).value).toBe("任务A");
    wrapper.unmount();
  });
});
