import { describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import DocListItem from "./DocListItem.vue";
import type { DocumentItem } from "../../types";

function makeDoc(overrides: Partial<DocumentItem> = {}): DocumentItem {
  return {
    id: 1,
    name: "运维手册.md",
    mime_type: "text/markdown",
    size_bytes: 4096,
    content_hash: "hash-1",
    embedding_model: "test",
    chunk_count: 8,
    status: "ready",
    enabled: true,
    error_message: null,
    last_error_at: null,
    indexed_at: null,
    doc_type: "markdown",
    topic: "运维",
    tags_json: ["备份", "恢复"],
    language: "zh",
    project_id: null,
    created_at: "",
    updated_at: "",
    ...overrides,
  };
}

describe("DocListItem", () => {
  it("渲染名称、状态徽标与元数据", () => {
    const wrapper = mount(DocListItem, {
      props: { doc: makeDoc(), selected: false },
    });
    expect(wrapper.text()).toContain("运维手册.md");
    expect(wrapper.text()).toContain("已就绪");
    expect(wrapper.text()).toContain("4.0 KB");
    expect(wrapper.text()).toContain("切片 8");
    expect(wrapper.text()).toContain("主题：运维");
    expect(wrapper.text()).toContain("#备份");
  });

  it("failed 状态展示错误原因与重试按钮", () => {
    const wrapper = mount(DocListItem, {
      props: {
        doc: makeDoc({ status: "failed", error_message: "解析超时" }),
        selected: false,
      },
    });
    expect(wrapper.text()).toContain("失败");
    expect(wrapper.text()).toContain("解析超时");
    const retry = wrapper.findAll("button").find((b) => b.text() === "重试");
    expect(retry).toBeTruthy();
    retry!.trigger("click");
    expect(wrapper.emitted("retry")).toEqual([[1]]);
  });

  it("操作按钮发出对应事件", async () => {
    const wrapper = mount(DocListItem, {
      props: { doc: makeDoc(), selected: true },
    });
    const buttons = wrapper.findAll("button");
    const byText = (text: string) => buttons.find((b) => b.text() === text)!;
    await byText("摘要").trigger("click");
    expect(wrapper.emitted("summary")?.[0]?.[0]?.id).toBe(1);
    await byText("删除").trigger("click");
    expect(wrapper.emitted("remove")?.[0]).toEqual([1]);
    await byText("重建").trigger("click");
    expect(wrapper.emitted("reindex")?.[0]?.[0]?.id).toBe(1);
    await byText("OCR").trigger("click");
    expect(wrapper.emitted("ocr")?.[0]?.[0]?.id).toBe(1);
  });

  it("选择框切换与禁用态", async () => {
    const wrapper = mount(DocListItem, {
      props: { doc: makeDoc(), selected: false },
    });
    await wrapper.find('input[type="checkbox"]').trigger("change");
    expect(wrapper.emitted("toggle-select")?.[0]).toEqual([1]);
    const disabled = mount(DocListItem, {
      props: { doc: makeDoc({ enabled: false }), selected: false },
    });
    expect(disabled.classes()).toContain("disabled");
  });
});
