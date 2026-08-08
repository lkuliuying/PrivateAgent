import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import MemoryRow from "./MemoryRow.vue";
import MemoryEditorForm from "./MemoryEditorForm.vue";
import type { MemoryItem, MemoryKind } from "../../types";

function makeMemory(overrides: Partial<MemoryItem> = {}): MemoryItem {
  return {
    id: 1,
    title: "每周五复盘",
    kind: "learning",
    summary: null,
    content_md: "…",
    source_type: null,
    source_id: null,
    project_id: null,
    topic_id: null,
    tags_json: [],
    confidence: null,
    sensitive: false,
    enabled: true,
    status: "confirmed",
    created_at: "",
    updated_at: "",
    ...overrides,
  };
}

describe("MemoryRow", () => {
  it("渲染标题与状态文案，点击发出 select", async () => {
    const wrapper = mount(MemoryRow, {
      props: {
        memory: makeMemory(),
        active: true,
        kindLabel: "学习",
        statusLabel: "已确认",
        statusTone: "ok",
      },
    });
    expect(wrapper.text()).toContain("每周五复盘");
    expect(wrapper.text()).toContain("学习 · 已确认");
    expect(wrapper.classes()).toContain("active");
    await wrapper.trigger("click");
    expect(wrapper.emitted("select")?.[0]).toEqual([1]);
  });

  it("禁用与敏感标记", () => {
    const wrapper = mount(MemoryRow, {
      props: {
        memory: makeMemory({ enabled: false, sensitive: true }),
        active: false,
        kindLabel: "偏好",
        statusLabel: "待确认",
        statusTone: "warn",
      },
    });
    expect(wrapper.classes()).toContain("disabled");
    expect(wrapper.text()).toContain("已禁用");
    expect(wrapper.text()).toContain("敏感");
  });
});

describe("MemoryEditorForm", () => {
  const form = {
    kind: "preference" as const,
    title: "新记忆",
    content_md: "",
    summary: "",
    tags: "",
    sensitive: false,
    confidence: "",
  };
  const kinds: MemoryKind[] = ["preference", "learning"];
  const kindLabels = { preference: "偏好", learning: "学习" };

  it("渲染表单并发出 save/cancel", async () => {
    const wrapper = mount(MemoryEditorForm, {
      props: { form, busy: false, kinds, kindLabels },
    });
    expect(wrapper.text()).toContain("新建记忆");
    await wrapper.findAll("button").find((b) => b.text().includes("保存"))!.trigger("click");
    expect(wrapper.emitted("save")).toBeTruthy();
    await wrapper.findAll("button").find((b) => b.text().includes("取消"))!.trigger("click");
    expect(wrapper.emitted("cancel")).toBeTruthy();
  });

  it("v-model 双向绑定到 form", async () => {
    const wrapper = mount(MemoryEditorForm, {
      props: { form, busy: false, kinds, kindLabels },
    });
    const input = wrapper.find('input[placeholder="简短标题"]');
    await input.setValue("复盘习惯");
    expect(form.title).toBe("复盘习惯");
  });
});
