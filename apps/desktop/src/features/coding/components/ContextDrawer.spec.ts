import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import ContextDrawer from "./ContextDrawer.vue";
import { applyRunFrame, createRunProjection } from "../model/runProjector";
import type { RunApprovalPreviewRecord } from "../model/runContracts";

const PREVIEW: RunApprovalPreviewRecord = {
  tool_name: "apply_patch_to_workspace",
  previewable: true,
  rel_path: "src/sidebar.ts",
  creates_file: true,
  old_sha256: null,
  new_sha256: null,
  diff: "@@ -1 +1 @@",
  truncated: false,
  reason: null,
};

function projectionWithArtifact() {
  const projection = createRunProjection("run-1", "任务");
  applyRunFrame(projection, { sequence: 1, type: "artifact.created", payload: { artifact_id: "art-1", kind: "test_report", title: "测试报告", step_id: null } });
  applyRunFrame(projection, { sequence: 2, type: "run.completed", payload: { output: "完成", error_code: null, tool_call_count: 2, input_tokens: 1000, output_tokens: 200, cached_tokens: 0, cost_usd: null } });
  return projection;
}

function mountDrawer(props: Record<string, unknown> = {}) {
  return mount(ContextDrawer, {
    props: {
      projection: projectionWithArtifact(),
      previews: { "ap-1": PREVIEW },
      permissionMode: "confirm",
      ...props,
    },
  });
}

describe("ContextDrawer", () => {
  it("Files：审批预览涉及的文件（含新建标记）", () => {
    const wrapper = mountDrawer();
    expect(wrapper.find('[data-testid="context-pane-files"]').text()).toContain("src/sidebar.ts");
    expect(wrapper.find('[data-testid="context-pane-files"]').text()).toContain("新建");
  });

  it("Context：run 元信息与权限语义", async () => {
    const wrapper = mountDrawer();
    await wrapper.find('[data-testid="context-tab-context"]').trigger("click");
    const pane = wrapper.find('[data-testid="context-pane-context"]');
    expect(pane.text()).toContain("已完成");
    // v0.9.0 §5.3：confirm 档呈现词汇为「总是询问」
    expect(pane.text()).toContain("总是询问");
    expect(pane.text()).toContain("1,000");
  });

  it("Sources：如实空态（Coding 不使用 RAG 来源）", async () => {
    const wrapper = mountDrawer();
    await wrapper.find('[data-testid="context-tab-sources"]').trigger("click");
    expect(wrapper.find('[data-testid="context-pane-sources"]').text()).toContain("不使用 RAG 来源");
  });

  it("Artifacts：产出 kind 与标题", async () => {
    const wrapper = mountDrawer();
    await wrapper.find('[data-testid="context-tab-artifacts"]').trigger("click");
    const pane = wrapper.find('[data-testid="context-pane-artifacts"]');
    expect(pane.text()).toContain("test_report");
    expect(pane.text()).toContain("测试报告");
  });

  it("关闭按钮发出 close", async () => {
    const wrapper = mountDrawer();
    await wrapper.find('[data-testid="context-drawer-close"]').trigger("click");
    expect(wrapper.emitted("close")).toBeTruthy();
  });
});
