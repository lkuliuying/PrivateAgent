import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import ToolDiagnosticsPanel from "./ToolDiagnosticsPanel.vue";
import { fetchToolDiagnostics } from "../api/toolDiagnostics";

vi.mock("../api/toolDiagnostics", async () => {
  const actual = await vi.importActual<typeof import("../api/toolDiagnostics")>(
    "../api/toolDiagnostics"
  );
  return { ...actual, fetchToolDiagnostics: vi.fn() };
});

const mockedFetch = vi.mocked(fetchToolDiagnostics);

const SNAPSHOT = {
  generated_at: "2026-08-25T03:00:00Z",
  tool_plan_id: "tp-" + "0".repeat(32),
  intent_tags: ["file.mutate"],
  direct_total: 1,
  deferred_total: 1,
  hidden_total: 2,
  catalog_hash: "a".repeat(64),
  visible_hash: "b".repeat(64),
  model_profile_hash: "c".repeat(20),
  policy_hash: "d".repeat(20),
  tools: [
    {
      namespace: "builtin",
      canonical_name: "apply_patch_to_workspace",
      version: "1.0.0",
      exposure: "direct",
      risk_level: "confirm",
      approval_mode: "prompt",
      executor_kind: "python",
      side_effect_class: "filesystem",
      health_check_id: null,
    },
    {
      namespace: "builtin",
      canonical_name: "search_tools",
      version: "1.0.0",
      exposure: "deferred",
      risk_level: "safe",
      approval_mode: "auto",
      executor_kind: "python",
      side_effect_class: "none",
      health_check_id: null,
    },
    {
      namespace: "builtin",
      canonical_name: "apply_patch_set",
      version: "1.0.0",
      exposure: "hidden:feature_disabled",
      risk_level: "confirm",
      approval_mode: "prompt",
      executor_kind: "python",
      side_effect_class: "filesystem",
      health_check_id: null,
    },
    {
      namespace: "builtin",
      canonical_name: "read_code_file",
      version: "1.0.0",
      exposure: "hidden:not_relevant",
      risk_level: "confirm",
      approval_mode: "prompt",
      executor_kind: "python",
      side_effect_class: "filesystem",
      health_check_id: null,
    },
  ],
};

function mountPanel(props: Record<string, unknown> = {}) {
  return mount(ToolDiagnosticsPanel, { props });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("ToolDiagnosticsPanel", () => {
  it("加载快照：计数、四组 hash（截断）与逐工具暴露状态", async () => {
    mockedFetch.mockResolvedValue(SNAPSHOT);
    const wrapper = mountPanel();
    await flushPromises();

    expect(wrapper.find('[data-testid="count-direct"]').text()).toContain("1");
    expect(wrapper.find('[data-testid="count-deferred"]').text()).toContain("1");
    expect(wrapper.find('[data-testid="count-hidden"]').text()).toContain("2");

    expect(wrapper.find('[data-testid="hashes"]').text()).toContain(
      SNAPSHOT.catalog_hash.slice(0, 16)
    );

    expect(wrapper.find('[data-testid="exposure-apply_patch_to_workspace"]').text()).toBe(
      "direct"
    );
    expect(wrapper.find('[data-testid="exposure-search_tools"]').text()).toBe(
      "deferred"
    );
    expect(wrapper.find('[data-testid="exposure-apply_patch_set"]').text()).toBe(
      "hidden"
    );
  });

  it("隐藏原因映射为中文标签（feature_disabled / not_relevant）", async () => {
    mockedFetch.mockResolvedValue(SNAPSHOT);
    const wrapper = mountPanel();
    await flushPromises();

    const rowPatchSet = wrapper.find(
      '[data-testid="tool-row-apply_patch_set"]'
    );
    expect(rowPatchSet.text()).toContain("功能开关未启用");

    const rowReadCode = wrapper.find('[data-testid="tool-row-read_code_file"]');
    expect(rowReadCode.text()).toContain("与本轮意图无关");
  });

  it("脱敏说明可见；输出不含 schema/描述全文", async () => {
    mockedFetch.mockResolvedValue(SNAPSHOT);
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="redaction-note"]').exists()).toBe(true);
    expect(wrapper.html()).not.toContain("input_schema");
  });

  it("intent_tags 输入经查询按钮传给 API", async () => {
    mockedFetch.mockResolvedValue(SNAPSHOT);
    const wrapper = mountPanel({ initialTags: "" });
    await flushPromises();
    expect(mockedFetch).toHaveBeenLastCalledWith([]);

    await wrapper.find('[data-testid="tags-input"]').setValue("file.mutate, code.inspect");
    await wrapper.find('[data-testid="apply-tags"]').trigger("click");
    await flushPromises();
    expect(mockedFetch).toHaveBeenLastCalledWith(["file.mutate", "code.inspect"]);
  });

  it("404 → 端点未启用提示", async () => {
    mockedFetch.mockRejectedValue({ status: 404 });
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="endpoint-disabled"]').text()).toContain(
      "PA_AGENT_V2_TOOL_SNAPSHOT_ENABLED"
    );
  });

  it("其他错误 → 一般错误文案", async () => {
    mockedFetch.mockRejectedValue({ message: "网络中断" });
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="load-error"]').text()).toContain("网络中断");
  });

  it("空工具列表 → 空态提示", async () => {
    mockedFetch.mockResolvedValue({ ...SNAPSHOT, tools: [], direct_total: 0, deferred_total: 0, hidden_total: 0 });
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="empty-tools"]').exists()).toBe(true);
  });

  it("parseExposure：hidden:<reason> 拆分与未知原因回退", async () => {
    const { parseExposure, hiddenReasonLabel } = await import(
      "../api/toolDiagnostics"
    );
    expect(parseExposure("direct")).toEqual({ state: "direct", reason: null });
    expect(parseExposure("hidden:health_failed")).toEqual({
      state: "hidden",
      reason: "health_failed",
    });
    expect(hiddenReasonLabel("health_failed")).toBe("健康检查失败");
    // 未知原因回退为原始字符串，不伪造中文标签。
    expect(hiddenReasonLabel("future_reason")).toBe("future_reason");
  });
});
