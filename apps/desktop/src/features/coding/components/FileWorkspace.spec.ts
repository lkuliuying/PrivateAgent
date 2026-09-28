import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import FileWorkspace from "./FileWorkspace.vue";
import type { WorkspaceFileOpenRequest } from "../model/outputFiles";
const api = vi.hoisted(() => ({ list: vi.fn(), read: vi.fn() }));
vi.mock("../api/workspaceFiles", () => ({ listWorkspaceFiles: api.list, readWorkspaceFile: api.read }));
const entries = [{ name: "src", rel_path: "src", kind: "directory" }, { name: "hello.py", rel_path: "hello.py", kind: "file" }];
const wrappers: ReturnType<typeof mount>[] = [];
function create(openRequest?: WorkspaceFileOpenRequest) { const wrapper = mount(FileWorkspace, { props: { projectId: 1, workspaceId: 2, projectName: "试用项目", openRequest } }); wrappers.push(wrapper); return wrapper; }
beforeEach(() => { vi.clearAllMocks(); api.list.mockResolvedValue({ entries, next_cursor: null, total: 2 }); api.read.mockResolvedValue({ rel_path: "hello.py", content: "print('hello world!')", sha256: "a".repeat(64), offset: 0, next_offset: null, total_chars: 21 }); });
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()));
describe("FileWorkspace", () => {
  it("输出引用直接打开文件并高亮目标行，重复点击复用标签", async () => {
    api.read.mockResolvedValue({ rel_path: "src/app.py", content: "first\nsecond\nthird", sha256: "a".repeat(64), offset: 0, next_offset: null, total_chars: 18 });
    const wrapper = create({ path: "src/app.py", line: 2, requestId: 1 });
    await flushPromises();
    expect(api.read.mock.calls[0].slice(0, 3)).toEqual([1, 2, "src/app.py"]);
    expect(wrapper.get('.code-line--target').text()).toContain("second");
    await wrapper.setProps({ openRequest: { path: "src/app.py", line: 3, requestId: 2 } });
    await flushPromises();
    expect(wrapper.findAll('.file-tab')).toHaveLength(1);
    expect(wrapper.get('.code-line--target').text()).toContain("third");
    expect(api.read).toHaveBeenCalledTimes(1);
  });

  it("目标行未加载或不存在时明确提示，续读仍绑定摘要", async () => {
    api.read.mockResolvedValueOnce({ rel_path: "src/app.py", content: "first\nsecond", sha256: "b".repeat(64), offset: 0, next_offset: 12, total_chars: 18 });
    const wrapper = create({ path: "src/app.py", line: 3, requestId: 1 });
    await flushPromises();
    expect(wrapper.text()).toContain("第 3 行尚未加载，请继续读取");
    api.read.mockResolvedValueOnce({ rel_path: "src/app.py", content: "\nthird", sha256: "b".repeat(64), offset: 12, next_offset: null, total_chars: 18 });
    await wrapper.get('.code-scroll .more').trigger("click");
    await flushPromises();
    expect(api.read.mock.calls[1].slice(2, 5)).toEqual(["src/app.py", 12, "b".repeat(64)]);
    expect(wrapper.get('.code-line--target').text()).toContain("third");
    await wrapper.setProps({ openRequest: { path: "src/app.py", line: 4, requestId: 2 } });
    expect(wrapper.text()).toContain("文件中没有第 4 行");
  });

  it("外部打开请求不能绕过相对路径边界", async () => {
    const wrapper = create({ path: "../outside.txt", requestId: 1 });
    await flushPromises();
    expect(api.read).not.toHaveBeenCalled();
    await wrapper.setProps({ openRequest: { path: "F:/outside.txt", requestId: 2 } });
    expect(api.read).not.toHaveBeenCalled();
  });

  it("多短行文件保留原文，行定位不会按行创建大量节点", async () => {
    const content = "x\n".repeat(12000);
    api.read.mockResolvedValue({ rel_path: "short-lines.txt", content, sha256: "a".repeat(64), offset: 0, next_offset: null, total_chars: content.length });
    const wrapper = create({ path: "short-lines.txt", line: 10000, requestId: 1 });
    await flushPromises();
    expect(wrapper.get("pre code").element.textContent).toBe(content);
    expect(wrapper.get("pre code").element.childElementCount).toBe(1);
    expect(wrapper.get('.code-line--target').attributes("aria-label")).toBe("第 10000 行");
  });

  it("切换工作区时取消输出引用读取，旧请求不会在新工作区重放", async () => {
    let finish!: (value: unknown) => void;
    api.read.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const wrapper = create({ path: "src/app.py", requestId: 1 });
    const signal = api.read.mock.calls[0][5];
    await wrapper.setProps({ workspaceId: 3 });
    expect(signal.aborted).toBe(true);
    finish({ content: "old private content", sha256: "a".repeat(64), next_offset: null, total_chars: 19 });
    await flushPromises();
    expect(api.read).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).not.toContain("old private content");
    expect(wrapper.findAll('.file-tab')).toHaveLength(0);
  });
  it("筛选、打开与关闭文件标签", async () => {
    const wrapper = create(); await flushPromises();
    await wrapper.get('input').setValue("hello"); expect(wrapper.findAll('.file-row')).toHaveLength(1);
    await wrapper.get('.file-row').trigger('click'); await flushPromises();
    expect(wrapper.get('pre').text()).toContain("hello world!");
    await wrapper.get('button[aria-label="关闭 hello.py"]').trigger('click'); expect(wrapper.find('pre').exists()).toBe(false);
  });
  it("续读绑定版本，变化后保留错误原因", async () => {
    api.read.mockResolvedValueOnce({ content: "first", sha256: "b".repeat(64), next_offset: 5, total_chars: 10 });
    const wrapper = create(); await flushPromises(); await wrapper.findAll('.file-row')[1].trigger('click'); await flushPromises();
    api.read.mockRejectedValueOnce({ message: "文件已变化，请刷新后重新预览" });
    await wrapper.get('.code-scroll .more').trigger('click'); await flushPromises();
    expect(api.read.mock.calls[1].slice(2, 5)).toEqual(["hello.py", 5, "b".repeat(64)]);
    expect(wrapper.get('[role="alert"]').text()).toContain("文件已变化");
  });
  it("切换工作区取消在途读取并丢弃旧响应", async () => {
    let finish: (value: unknown) => void = () => {};
    api.list.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const wrapper = create(); const signal = api.list.mock.calls[0][4];
    await wrapper.setProps({ workspaceId: 3 }); await flushPromises(); expect(signal.aborted).toBe(true);
    finish({ entries: [{ name: "stale.txt", rel_path: "stale.txt", kind: "file" }], next_cursor: null }); await flushPromises();
    expect(wrapper.text()).not.toContain("stale.txt"); expect(api.list.mock.lastCall?.[1]).toBe(3);
  });
  it("不可预览错误明确可见并能重试", async () => {
    api.read.mockRejectedValue({ message: "文件过大或包含二进制内容" });
    const wrapper = create(); await flushPromises(); await wrapper.findAll('.file-row')[1].trigger('click'); await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("二进制");
    await wrapper.get('button[aria-label="刷新文件"]').trigger('click'); await flushPromises(); expect(api.read).toHaveBeenCalledTimes(2);
  });
});
