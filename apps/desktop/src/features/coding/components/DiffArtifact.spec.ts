import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import DiffArtifact from "./DiffArtifact.vue";
import type { RunApprovalPreviewRecord } from "../model/runContracts";

function preview(overrides: Partial<RunApprovalPreviewRecord> = {}): RunApprovalPreviewRecord {
  return {
    tool_name: "apply_patch_to_workspace",
    previewable: true,
    rel_path: "src/sidebar.ts",
    creates_file: false,
    old_sha256: null,
    new_sha256: null,
    diff: ["@@ -1,3 +1,4 @@", " context", "-removed", "+added", "+added2"].join("\n"),
    truncated: false,
    reason: null,
    ...overrides,
  };
}

describe("DiffArtifact", () => {
  it("文件头含路径与 +/- 统计，折叠时不渲染正文", async () => {
    const wrapper = mount(DiffArtifact, { props: { preview: preview() } });
    const head = wrapper.find('[data-testid="diff-artifact-toggle"]');
    expect(head.text()).toContain("src/sidebar.ts");
    expect(head.text()).toContain("+2");
    expect(head.text()).toContain("-1");
    expect(wrapper.find('[data-testid="diff-artifact-body"]').exists()).toBe(false);
    await head.trigger("click");
    expect(wrapper.find('[data-testid="diff-artifact-body"]').exists()).toBe(true);
    const body = wrapper.find('[data-testid="diff-artifact-body"]');
    expect(body.text()).toContain("+added");
    expect(body.text()).toContain("-removed");
  });

  it("新建文件标记", () => {
    const wrapper = mount(DiffArtifact, {
      props: { preview: preview({ creates_file: true }) },
    });
    expect(wrapper.find('[data-testid="diff-artifact-toggle"]').text()).toContain("新建");
  });

  it("previewable=false 只呈现后端 reason，不猜测内容", () => {
    const wrapper = mount(DiffArtifact, {
      props: { preview: preview({ previewable: false, diff: null, reason: "该工具不提供文件预览" }) },
    });
    expect(wrapper.text()).toContain("该工具不提供文件预览");
    expect(wrapper.find('[data-testid="diff-artifact-body"]').exists()).toBe(false);
  });

  it("截断标记呈现", () => {
    const wrapper = mount(DiffArtifact, {
      props: { preview: preview({ truncated: true }) },
    });
    expect(wrapper.text()).toContain("后端已截断");
  });
});
