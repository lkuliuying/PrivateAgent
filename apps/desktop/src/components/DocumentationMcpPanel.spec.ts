import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DocumentationMcpPanel from "./DocumentationMcpPanel.vue";
import * as api from "../api/documentationMcp";

vi.mock("../api/documentationMcp", () => ({
  documentationProjects: vi.fn(), documentationSources: vi.fn(), createDocumentationSource: vi.fn(),
  discoverDocumentationSource: vi.fn(), selectDocumentationTools: vi.fn(), deleteDocumentationSource: vi.fn(),
}));
const confirm = vi.hoisted(() => vi.fn());
vi.mock("../stores/notifications", () => ({ useNotifications: () => ({ confirm }) }));

const source: api.DocumentationSource = {
  id: "abc", name: "文档测试", url: "https://docs.example.test/mcp", version: "v1", enabled: false,
  tools: [], catalog: null, discovered_at: null,
};
const discovered: api.DocumentationSource = { ...source, version: "v2", discovered_at: new Date().toISOString(),
  catalog: { sha256: "hash", tools: [{ name: "search_docs", description: "搜索技术文档", input_schema: {}, output_schema: null }] } };

function button(wrapper: ReturnType<typeof mount>, text: string) {
  return wrapper.findAll("button").find(item => item.text() === text)!;
}

describe("项目文档 MCP", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(api.documentationProjects).mockResolvedValue([{ id: 7, name: "项目甲" }, { id: 8, name: "项目乙" }]);
    vi.mocked(api.documentationSources).mockResolvedValue([]);
    confirm.mockResolvedValue(true);
  });

  it("保存后发现工具，明确选择并启用，支持停用和移除", async () => {
    vi.mocked(api.createDocumentationSource).mockResolvedValue(source);
    vi.mocked(api.discoverDocumentationSource).mockResolvedValue(discovered);
    vi.mocked(api.selectDocumentationTools).mockResolvedValue({ ...discovered, version: "v3", tools: ["search_docs"], enabled: true });
    const wrapper = mount(DocumentationMcpPanel);
    await flushPromises();
    expect(wrapper.text()).toContain("尚未配置文档服务");
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    expect(api.createDocumentationSource).toHaveBeenCalledWith(7, expect.objectContaining({ url: "https://learn.microsoft.com/api/mcp" }), expect.any(AbortSignal));
    expect(api.discoverDocumentationSource).not.toHaveBeenCalled();
    await button(wrapper, "发现工具").trigger("click");
    await flushPromises();
    expect(button(wrapper, "启用所选工具").attributes("disabled")).toBeDefined();
    await wrapper.find('input[type="checkbox"]').setValue(true);
    await button(wrapper, "启用所选工具").trigger("click");
    await flushPromises();
    expect(api.selectDocumentationTools).toHaveBeenCalledWith(7, discovered, ["search_docs"], true, expect.any(AbortSignal));
    expect(wrapper.text()).toContain("已启用");
    await button(wrapper, "停用").trigger("click");
    await flushPromises();
    expect(api.selectDocumentationTools).toHaveBeenLastCalledWith(7, expect.objectContaining({ version: "v3" }), ["search_docs"], false, expect.any(AbortSignal));
    await button(wrapper, "移除").trigger("click");
    await flushPromises();
    expect(api.deleteDocumentationSource).toHaveBeenCalled();
    expect(wrapper.find("article").exists()).toBe(false);
    wrapper.unmount();
  });

  it("拒绝连接后不发现，错误可见且不会自动启用", async () => {
    vi.mocked(api.documentationSources).mockResolvedValue([source]);
    const wrapper = mount(DocumentationMcpPanel);
    await flushPromises();
    confirm.mockResolvedValueOnce(false);
    await button(wrapper, "发现工具").trigger("click");
    await flushPromises();
    expect(api.discoverDocumentationSource).not.toHaveBeenCalled();
    vi.mocked(api.discoverDocumentationSource).mockRejectedValueOnce(new Error("文档服务连接超时"));
    await button(wrapper, "发现工具").trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("连接超时");
    expect(api.selectDocumentationTools).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("项目切换只显示新项目配置，卸载会取消请求", async () => {
    vi.mocked(api.documentationSources).mockResolvedValueOnce([source]).mockResolvedValueOnce([]);
    const wrapper = mount(DocumentationMcpPanel);
    await flushPromises();
    await wrapper.find("select").setValue(8);
    await flushPromises();
    expect(api.documentationSources).toHaveBeenLastCalledWith(8, expect.any(AbortSignal));
    expect(wrapper.find("article").exists()).toBe(false);
    const calls = vi.mocked(api.documentationSources).mock.calls;
    const signal = calls[calls.length - 1][1];
    wrapper.unmount();
    expect(signal.aborted).toBe(true);
  });
});
