import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { nextTick } from "vue";
import CodingComposer, { type CodingComposerSendPayload } from "./CodingComposer.vue";
import TaskAttachmentList from "./TaskAttachmentList.vue";
import { createCodingWorkspaceStore } from "../model/codingWorkspaceStore";
import { acknowledgeComposerDraft, composerDraftKey, transferFirstTurnDraft } from "../model/composerDrafts";
import { importTaskAttachment, listDraftAttachments, readTaskAttachment, removeTaskAttachment } from "../api/attachments";
import type { TaskAttachment } from "../../../types";

vi.mock("../api/attachments", () => ({
  listDraftAttachments: vi.fn(), readTaskAttachment: vi.fn(), removeTaskAttachment: vi.fn(), importTaskAttachment: vi.fn(),
}));
const item: TaskAttachment = { id: "a".repeat(32), name: "notes.txt", size_bytes: 12, sha256: "b".repeat(64), language: "txt", project_id: 1, workspace_id: 101 };

function state() {
  const store = createCodingWorkspaceStore();
  store.selectedProjectId.value = 1;
  store.selectedWorkspaceId.value = 101;
  return store;
}
const textOf = (wrapper: ReturnType<typeof mount>) => (wrapper.get("textarea").element as HTMLTextAreaElement).value;
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(listDraftAttachments).mockResolvedValue([]);
  vi.mocked(removeTaskAttachment).mockResolvedValue({ removed: true });
});

describe("附件与草稿", () => {
  it("图片需要明确的视觉能力，发送被阻止时材料和正文仍保留", async () => {
    const submit = vi.fn(async () => true);
    const picture = { ...item, name: "sample.png", kind: "image" as const, requires_vision: true };
    const wrapper = mount(CodingComposer, { props: { store: state(), threadId: 11, pickAttachment: async () => picture, submit } });
    await wrapper.get("textarea").setValue("理解这张图片");
    await wrapper.get('[aria-label="从本机添加文件"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-testid="coding-composer-send"]').trigger("click");
    await flushPromises();
    expect(submit).not.toHaveBeenCalled();
    expect(textOf(wrapper)).toBe("理解这张图片");
    expect(wrapper.text()).toContain("确认视觉能力");
    expect(wrapper.text()).toContain("sample.png");
    wrapper.unmount();
  });

  it("PDF 预览按页加载并保留显式导入入口", async () => {
    const pdf = { ...item, name: "sample.pdf", kind: "pdf" as const, page_count: 2 };
    vi.mocked(readTaskAttachment).mockImplementation(async (_id, _owner, _offset, page) => ({
      ...pdf, content: page === 2 ? "第二页" : "第一页", offset: 0, next_offset: null, total_chars: 3,
      image_data_url: "data:image/jpeg;base64,/9j/2Q==",
    }));
    const wrapper = mount(TaskAttachmentList, { props: { items: [pdf], draftId: "c".repeat(32) }, attachTo: document.body });
    await wrapper.get(".task-attachment button").trigger("click");
    await flushPromises();
    const next = [...document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find(button => button.textContent === "下一页")!;
    next.click();
    await flushPromises();
    expect(readTaskAttachment).toHaveBeenLastCalledWith(pdf.id, { draft_id: "c".repeat(32) }, 0, 2);
    expect(document.querySelector(".attachment-content")?.textContent).toBe("第二页");
    expect(importTaskAttachment).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("失败与重启保留结构化正文、附件和同一请求标识", async () => {
    const store = state();
    const submit = vi.fn(async (_payload: CodingComposerSendPayload) => false);
    let wrapper = mount(CodingComposer, { props: { store, threadId: 11, pickAttachment: async () => item, submit } });
    await wrapper.get("textarea").setValue("参考这个材料");
    await wrapper.get('[aria-label="从本机添加文件"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-testid="coding-composer-send"]').trigger("click");
    await flushPromises();
    const first = submit.mock.calls[0]?.[0] as unknown as { message: string; clientRequestId: string; attachments: TaskAttachment[] };
    expect(first.message).toBe("参考这个材料");
    expect(first.attachments).toEqual([item]);
    expect(textOf(wrapper)).toBe("参考这个材料");
    wrapper.unmount();
    wrapper = mount(CodingComposer, { props: { store, threadId: 11, submit } });
    await flushPromises();
    expect(wrapper.text()).toContain("notes.txt");
    await wrapper.get('[data-testid="coding-composer-send"]').trigger("click");
    await flushPromises();
    expect(submit.mock.calls[1]?.[0]).toMatchObject({ clientRequestId: first.clientRequestId, attachments: [item] });
    wrapper.unmount();
  });

  it("发送成功才清空；等待期间的新正文不清空", async () => {
    let finish!: (value: boolean) => void;
    const submit = vi.fn(() => new Promise<boolean>(resolve => { finish = resolve; }));
    const wrapper = mount(CodingComposer, { props: { store: state(), threadId: 11, submit } });
    await wrapper.get("textarea").setValue("第一条");
    await wrapper.get('[data-testid="coding-composer-send"]').trigger("click");
    expect(textOf(wrapper)).toBe("第一条");
    await wrapper.get("textarea").setValue("之后的草稿");
    finish(true);
    await flushPromises();
    expect(textOf(wrapper)).toBe("之后的草稿");
    await wrapper.setProps({ submit: async () => true });
    await wrapper.get('[data-testid="coding-composer-send"]').trigger("click");
    await flushPromises();
    expect(textOf(wrapper)).toBe("");
    wrapper.unmount();
  });

  it("发送前确认期间切换会话，不把原输入提交到新会话", async () => {
    let finish!: (value: boolean) => void;
    const submit = vi.fn(async () => true);
    const beforeSend = () => new Promise<boolean>(resolve => { finish = resolve; });
    const wrapper = mount(CodingComposer, { props: { store: state(), threadId: 11, submit, beforeSend } });
    await wrapper.get("textarea").setValue("会话一的草稿");
    await wrapper.get('[data-testid="coding-composer-send"]').trigger("click");
    await wrapper.setProps({ threadId: 12 });
    finish(true);
    await flushPromises();
    expect(submit).not.toHaveBeenCalled();
    expect(textOf(wrapper)).toBe("");
    expect(JSON.parse(localStorage.getItem(composerDraftKey(1, 101, 11))!).text).toBe("会话一的草稿");
    wrapper.unmount();
  });

  it("首页草稿按项目和工作区隔离，切换后恢复各自材料", async () => {
    const store = state();
    const wrapper = mount(CodingComposer, { props: { store, pickAttachment: async () => item } });
    await wrapper.get("textarea").setValue("项目一");
    await wrapper.get('[aria-label="从本机添加文件"]').trigger("click");
    await flushPromises();
    store.selectedProjectId.value = 2;
    store.selectedWorkspaceId.value = 202;
    await nextTick();
    expect(textOf(wrapper)).toBe("");
    expect(wrapper.text()).not.toContain("notes.txt");
    await wrapper.get("textarea").setValue("项目二");
    store.selectedProjectId.value = 1;
    store.selectedWorkspaceId.value = 101;
    await flushPromises();
    expect(textOf(wrapper)).toBe("项目一");
    expect(wrapper.text()).toContain("notes.txt");
    expect(JSON.parse(localStorage.getItem(composerDraftKey(2, 202, null))!).text).toBe("项目二");
    wrapper.unmount();
  });

  it("选择响应丢失后根据草稿标识找回服务端副本", async () => {
    localStorage.setItem(composerDraftKey(1, 101, null), JSON.stringify({ text: "未发", draftId: "c".repeat(32), attachments: [] }));
    vi.mocked(listDraftAttachments).mockResolvedValue([item]);
    const wrapper = mount(CodingComposer, { props: { store: state() } });
    await flushPromises();
    expect(listDraftAttachments).toHaveBeenCalledWith("c".repeat(32));
    expect(wrapper.text()).toContain("notes.txt");
    await wrapper.get('[aria-label="移除附件 notes.txt"]').trigger("click");
    await flushPromises();
    expect(removeTaskAttachment).toHaveBeenCalledWith(item.id, "c".repeat(32));
    expect(wrapper.text()).not.toContain("notes.txt");
    wrapper.unmount();
  });

  it("移除成功后迟到的草稿列表不能重新添加已移除附件", async () => {
    localStorage.setItem(composerDraftKey(1, 101, null), JSON.stringify({ text: "未发", draftId: "c".repeat(32), attachments: [item] }));
    let finish!: (value: TaskAttachment[]) => void;
    vi.mocked(listDraftAttachments).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const wrapper = mount(CodingComposer, { props: { store: state() } });
    await wrapper.get('[aria-label="移除附件 notes.txt"]').trigger("click");
    await flushPromises();
    finish([item]);
    await flushPromises();
    expect(wrapper.text()).not.toContain("notes.txt");
    expect(JSON.parse(localStorage.getItem(composerDraftKey(1, 101, null))!).attachments).toEqual([]);
    wrapper.unmount();
  });

  it("首次会话转移后，只有匹配服务确认的正文才解除草稿", () => {
    const payload = { message: "正文", text: "正文", permissionMode: "confirm" as const, modelProfileId: null, reasoningEffort: null, draftId: "c".repeat(32), attachments: [item], clientRequestId: "once", draftStorageKey: composerDraftKey(1, 101, null) };
    localStorage.setItem(payload.draftStorageKey, JSON.stringify(payload));
    transferFirstTurnDraft(payload, 1, 101, 11);
    const key = composerDraftKey(1, 101, 11);
    expect(localStorage.getItem(payload.draftStorageKey)).toBeNull();
    acknowledgeComposerDraft(key, "other", "正文", [item.id]);
    expect(JSON.parse(localStorage.getItem(key)!).text).toBe("正文");
    acknowledgeComposerDraft(key, "once", "正文", [item.id]);
    expect(JSON.parse(localStorage.getItem(key)!).attachments).toEqual([]);
  });

  it("预览仅读取；显式确认导入才创建项目文件，失败保留目标路径", async () => {
    vi.mocked(readTaskAttachment).mockResolvedValue({ ...item, content: "参考材料", offset: 0, next_offset: null, total_chars: 4 });
    vi.mocked(importTaskAttachment).mockRejectedValue({ message: "目标文件已经存在，请改名" });
    const wrapper = mount(TaskAttachmentList, { props: { items: [item], draftId: "c".repeat(32) }, attachTo: document.body });
    await wrapper.get(".task-attachment button").trigger("click");
    await flushPromises();
    expect(readTaskAttachment).toHaveBeenCalledWith(item.id, { draft_id: "c".repeat(32) }, 0, 1);
    expect(importTaskAttachment).not.toHaveBeenCalled();
    const button = (label: string) => [...document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find(node => node.textContent?.includes(label))!;
    button("导入项目").click();
    await nextTick();
    button("确认创建项目文件").click();
    await flushPromises();
    expect(importTaskAttachment).toHaveBeenCalledWith(item.id, { draft_id: "c".repeat(32) }, "notes.txt");
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("请改名");
    expect((document.querySelector('[aria-label="附件导入目标路径"]') as HTMLInputElement).value).toBe("notes.txt");
    wrapper.unmount();
  });
});
