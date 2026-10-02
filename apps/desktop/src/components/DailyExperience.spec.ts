import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import SkillsPanel from "./SkillsPanel.vue";
import McpIntegrationsPanel from "./McpIntegrationsPanel.vue";
import HomeLayoutSettings from "./HomeLayoutSettings.vue";
import { createSkill, enableSkill, listSkills } from "../features/coding/api/skills";
import { connectIntegration, createIntegration, listIntegrations, listMcpServices, preflightMcpService, selectIntegrationTools } from "../features/coding/api/integrations";
import { homeLayout, setHomeLayout } from "../services/homeLayout";

vi.mock("../features/coding/api/skills", () => ({ createSkill: vi.fn(), enableSkill: vi.fn(), listSkills: vi.fn(), readSkill: vi.fn() }));
vi.mock("../features/coding/api/integrations", () => ({ connectIntegration: vi.fn(), createIntegration: vi.fn(), listIntegrations: vi.fn(), listMcpServices: vi.fn(), preflightMcpService: vi.fn(), removeIntegration: vi.fn(), selectIntegrationTools: vi.fn() }));
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  setHomeLayout("standard");
  vi.mocked(listSkills).mockResolvedValue({ items: [] });
  vi.mocked(listIntegrations).mockResolvedValue({ items: [] });
  vi.mocked(listMcpServices).mockResolvedValue({ items: [], pending_changes: [] });
  vi.mocked(preflightMcpService).mockResolvedValue({ valid: true, notice: "配置结构检查通过" });
});

describe("日常配置体验", () => {
  it("三类技能模板可编辑，填入与保存都不自动启用", async () => {
    const wrapper = mount(SkillsPanel, { props: { projectId: 1 } });
    await flushPromises();
    await wrapper.findAll("button").find(item => item.text() === "新建技能")!.trigger("click");
    const selector = wrapper.get('[data-testid="skill-template"]');
    expect(selector.findAll("option").map(item => item.text())).toEqual(["项目说明", "代码审查", "测试建议"]);
    for (const id of ["review", "tests", "guide"]) {
      await selector.setValue(id);
      await wrapper.findAll("button").find(item => item.text() === "填入模板")!.trigger("click");
      await flushPromises();
      expect((wrapper.get("textarea").element as HTMLTextAreaElement).value).toContain("\nname: ");
    }
    expect(createSkill).not.toHaveBeenCalled();
    await wrapper.get("textarea").setValue("---\nname: custom\ndescription: 自定义测试\n---\n只检查指定目录。");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(createSkill).toHaveBeenCalledWith(1, expect.objectContaining({ content: expect.stringContaining("只检查指定目录") }));
    expect(enableSkill).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("HTTPS 地址错误原位显示，保存成功不触发连接或启用", async () => {
    const wrapper = mount(McpIntegrationsPanel, { props: { projectId: 1 } });
    await flushPromises();
    await wrapper.get('input[maxlength="80"]').setValue("文档服务");
    const url = wrapper.get('input[placeholder="https://example.com/mcp"]');
    await url.setValue("http://example.com/mcp");
    await wrapper.get("form").trigger("submit");
    expect(createIntegration).not.toHaveBeenCalled();
    expect(url.attributes("aria-invalid")).toBe("true");
    expect(wrapper.text()).toContain("配置尚未保存");
    await url.setValue("https://example.com/mcp");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(createIntegration).toHaveBeenCalledWith(1, expect.objectContaining({ transport: "https", url: "https://example.com/mcp", args: [] }));
    expect(connectIntegration).not.toHaveBeenCalled();
    expect(selectIntegrationTools).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("stdio 参数使用可理解的校验错误并保留原输入", async () => {
    const wrapper = mount(McpIntegrationsPanel, { props: { projectId: 1 } });
    await flushPromises();
    await wrapper.get("select").setValue("stdio");
    await wrapper.get('input[maxlength="80"]').setValue("本机测试");
    const fields = wrapper.findAll("input.pa-input");
    await fields[1].setValue("C:\\tools\\node.exe");
    await wrapper.get('textarea[aria-describedby="mcp-args-help"]').setValue("[bad]");
    await wrapper.get('input[type="checkbox"]').setValue(true);
    await wrapper.get("form").trigger("submit");
    expect(createIntegration).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("字符串 JSON 数组");
    expect((wrapper.get('textarea[aria-describedby="mcp-args-help"]').element as HTMLTextAreaElement).value).toBe("[bad]");
    await wrapper.get('textarea[aria-describedby="mcp-args-help"]').setValue(JSON.stringify(["C:\\mcp\\server.js"]));
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(createIntegration).toHaveBeenCalledWith(1, expect.objectContaining({ transport: "stdio", command: "C:\\tools\\node.exe", args: ["C:\\mcp\\server.js"], trust_process: true }));
    expect(connectIntegration).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("首页布局默认标准，选择紧凑后只保存本机偏好", async () => {
    const wrapper = mount(HomeLayoutSettings);
    expect(homeLayout.value).toBe("standard");
    expect((wrapper.get('input[value="standard"]').element as HTMLInputElement).checked).toBe(true);
    await wrapper.get('input[value="compact"]').setValue(true);
    expect(homeLayout.value).toBe("compact");
    expect(localStorage.getItem("pa_home_layout_v1")).toBe("compact");
    await wrapper.get('input[value="standard"]').setValue(true);
    expect(homeLayout.value).toBe("standard");
    wrapper.unmount();
  });
});
