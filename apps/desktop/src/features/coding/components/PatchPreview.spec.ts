import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PatchPreview from "./PatchPreview.vue";
import { fetchPatchPage } from "../api/patches";

vi.mock("../api/patches", async importOriginal => ({ ...await importOriginal<typeof import("../api/patches")>(), fetchPatchPage: vi.fn() }));
const props = { runId: "run", patchId: "patch", previewSha: "sha", changes: [
  { change_id: "file", operation: "update", rel_path: "src/中文.ts", before_kind: "file", after_kind: "file", diff_chars: 6 },
] };
beforeEach(() => vi.clearAllMocks());

describe("完整补丁分页", () => {
  it("按文件读取完整页并允许前后翻页", async () => {
    vi.mocked(fetchPatchPage).mockImplementation(async (_run, _patch, _file, offset) => ({
      offset, content: offset === 0 ? "abc" : "def", next_offset: offset === 0 ? 3 : null, total_chars: 6, preview_sha256: "sha",
    }));
    const wrapper = mount(PatchPreview, { props });
    expect(fetchPatchPage).not.toHaveBeenCalled();
    await wrapper.get("select").setValue("file");
    await flushPromises();
    expect(wrapper.get("pre").text()).toBe("abc");
    await wrapper.findAll("button").find(item => item.text() === "下一页")!.trigger("click");
    await flushPromises();
    expect(wrapper.get("pre").text()).toBe("def");
    expect(wrapper.findAll("button").find(item => item.text() === "下一页")!.attributes("disabled")).toBeDefined();
    await wrapper.findAll("button").find(item => item.text() === "上一页")!.trigger("click");
    await flushPromises();
    expect(wrapper.get("pre").text()).toBe("abc");
    wrapper.unmount();
  });
  it("切换任务会取消旧请求并忽略迟到内容", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof fetchPatchPage>>) => void;
    vi.mocked(fetchPatchPage).mockReturnValue(new Promise(done => { resolve = done; }));
    const wrapper = mount(PatchPreview, { props });
    await wrapper.get("select").setValue("file");
    const signal = vi.mocked(fetchPatchPage).mock.calls[0]![4];
    await wrapper.setProps({ runId: "other" });
    expect(signal?.aborted).toBe(true);
    resolve({ content: "old", offset: 0, next_offset: null, total_chars: 3, preview_sha256: "sha" });
    await flushPromises();
    expect(wrapper.text()).not.toContain("old");
    expect(wrapper.find("pre").exists()).toBe(false);
    wrapper.unmount();
  });
  it("翻页失败保留当前位置，重试成功后才更新页历史", async () => {
    vi.mocked(fetchPatchPage)
      .mockResolvedValueOnce({ offset: 0, content: "abc", next_offset: 3, total_chars: 6, preview_sha256: "sha" })
      .mockRejectedValueOnce(new Error("断网"))
      .mockResolvedValueOnce({ offset: 3, content: "def", next_offset: null, total_chars: 6, preview_sha256: "sha" })
      .mockResolvedValueOnce({ offset: 0, content: "abc", next_offset: 3, total_chars: 6, preview_sha256: "sha" });
    const wrapper = mount(PatchPreview, { props });
    const button = (label: string) => wrapper.findAll("button").find(item => item.text() === label)!;
    await wrapper.get("select").setValue("file");
    await flushPromises();
    await button("下一页").trigger("click");
    await flushPromises();
    expect(wrapper.get("pre").text()).toBe("abc");
    expect(button("上一页").attributes("disabled")).toBeDefined();
    await button("重试").trigger("click");
    await flushPromises();
    expect(wrapper.get("pre").text()).toBe("def");
    expect(vi.mocked(fetchPatchPage).mock.calls[2]![3]).toBe(3);
    await button("上一页").trigger("click");
    await flushPromises();
    expect(wrapper.get("pre").text()).toBe("abc");
    expect(button("上一页").attributes("disabled")).toBeDefined();
    wrapper.unmount();
  });
  it("摘要不匹配时明确报错，不展示旧内容", async () => {
    vi.mocked(fetchPatchPage).mockResolvedValue({ content: "unapproved", offset: 0, next_offset: null, total_chars: 10, preview_sha256: "wrong" });
    const wrapper = mount(PatchPreview, { props });
    await wrapper.get("select").setValue("file");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("预览已变化");
    expect(wrapper.text()).not.toContain("unapproved");
    wrapper.unmount();
  });
});
