import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import McpIntegrationsPanel from "./McpIntegrationsPanel.vue";
import * as api from "../features/coding/api/integrations";

vi.mock("../features/coding/api/integrations", () => ({ listIntegrations: vi.fn(), listMcpServices: vi.fn(), preflightMcpService: vi.fn(),
  createIntegration: vi.fn(), prepareMcpService: vi.fn(), persistMcpChange: vi.fn(), bindMcpService: vi.fn(),
  discardMcpChange: vi.fn(), connectIntegration: vi.fn(), removeIntegration: vi.fn(), removeMcpService: vi.fn(),
  logoutMcpService: vi.fn(), selectIntegrationTools: vi.fn(), retryMcpCredentialCleanup: vi.fn() }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listIntegrations).mockResolvedValue({ items: [] });
  vi.mocked(api.listMcpServices).mockResolvedValue({ items: [], pending_changes: [] });
  vi.mocked(api.preflightMcpService).mockResolvedValue({ valid: true, notice: "配置结构检查通过，尚未连接服务或启动进程。" });
});

describe("MCP 服务库配置", () => {
  it.each([["connecting", "连接中"], ["authorization_required", "等待登录"], ["error", "连接失败"], ["connected", "需要重新验证"]])("待验证状态仍显示当前连接进展 %s", async (status, label) => {
    vi.mocked(api.listIntegrations).mockResolvedValue({ items: [{ id: "source", name: "待验证服务", transport: "https", enabled: false, tools: [],
      needs_validation: true, catalog: null, connection: { status } } as unknown as api.McpIntegration] });
    const wrapper = mount(McpIntegrationsPanel, { props: { projectId: 1 } });
    await flushPromises();
    expect(wrapper.get("article").text()).toContain("工具未启用 · " + label);
    wrapper.unmount();
  });

  it("stdio 参数逐项编辑保留空参数，非法 JSON 不覆盖参数行", async () => {
    const wrapper = mount(McpIntegrationsPanel, { props: { projectId: 1 } });
    await flushPromises();
    await wrapper.get('input[maxlength="80"]').setValue("本机服务");
    await wrapper.findAll("select")[0].setValue("stdio");
    await wrapper.get('input[placeholder="C:/tools/node.exe"]').setValue("C:/tools/node.exe");
    await wrapper.get('input[type="checkbox"]').setValue(true);
    const add = () => wrapper.findAll("button").find(item => item.text() === "添加参数")!.trigger("click");
    await add(); await wrapper.get('input[aria-label="参数 1"]').setValue("C:\\mcp tools\\server.js");
    await add();
    await wrapper.findAll("button").find(item => item.text() === "本地检查配置")!.trigger("click");
    await flushPromises();
    expect(api.preflightMcpService).toHaveBeenLastCalledWith(expect.objectContaining({ args: ["C:\\mcp tools\\server.js", ""] }));
    await wrapper.get('textarea[aria-describedby="mcp-args-help"]').setValue('["valid", 2]');
    await wrapper.findAll("button").find(item => item.text() === "导入为参数行")!.trigger("click");
    expect(wrapper.text()).toContain("原有参数行保持不变");
    expect((wrapper.get('input[aria-label="参数 1"]').element as HTMLInputElement).value).toBe("C:\\mcp tools\\server.js");
    await wrapper.get('textarea[aria-describedby="mcp-args-help"]').setValue('["--stdio", ""]');
    await wrapper.findAll("button").find(item => item.text() === "导入为参数行")!.trigger("click");
    expect((wrapper.get('input[aria-label="参数 2"]').element as HTMLInputElement).value).toBe("");
    await wrapper.get('button[aria-label="移除参数 1"]').trigger("click");
    await wrapper.get("form").trigger("submit"); await flushPromises();
    expect(api.createIntegration).toHaveBeenLastCalledWith(1, expect.objectContaining({ args: [""] }));
    wrapper.unmount();
  });

  it("旧凭据清理失败可重试且成功后移除警示", async () => {
    vi.mocked(api.listMcpServices).mockResolvedValueOnce({ items: [], pending_changes: [], credential_cleanup_pending: [{ id: "cleanup", service_id: "b".repeat(32), revision: "c".repeat(32), slot: "static" }] });
    const wrapper = mount(McpIntegrationsPanel, { props: { projectId: 1 } });
    await flushPromises();
    expect(wrapper.text()).toContain("已停止用于连接");
    await wrapper.findAll("button").find(item => item.text() === "重试清理旧凭据")!.trigger("click");
    await flushPromises();
    expect(api.retryMcpCredentialCleanup).toHaveBeenCalledOnce();
    expect(wrapper.text()).not.toContain("已停止用于连接");
    wrapper.unmount();
  });

  it("本地预检不保存、不连接，OAuth可选择仅当前进程", async () => {
    const wrapper = mount(McpIntegrationsPanel, { props: { projectId: 1 } });
    await flushPromises();
    await wrapper.get('input[maxlength="80"]').setValue("OAuth服务");
    await wrapper.get('input[placeholder="https://example.com/mcp"]').setValue("https://docs.example.test/mcp");
    await wrapper.findAll("select")[1].setValue("oauth");
    await wrapper.findAll("select")[2].setValue("session");
    await wrapper.findAll("button").find(item => item.text() === "本地检查配置")!.trigger("click");
    await flushPromises();
    expect(api.preflightMcpService).toHaveBeenCalledWith(expect.objectContaining({ auth_mode: "oauth", oauth_persistence: "session" }));
    expect(api.connectIntegration).not.toHaveBeenCalled();
    expect(api.createIntegration).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("尚未连接");
    wrapper.unmount();
  });

  it("Bearer正文只交给独立凭据保存函数，配置API没有秘密", async () => {
    const change = { id: "a".repeat(32), service_id: "b".repeat(32), credential_revision: "c".repeat(32), replace_credentials: true,
      required_fields: ["bearer"], binding: { identity: "d".repeat(64), service_id: "b".repeat(32), version: "c".repeat(32), slot: "static" } } as api.McpChange;
    vi.mocked(api.prepareMcpService).mockResolvedValue(change);
    vi.mocked(api.persistMcpChange).mockResolvedValue({ id: change.service_id } as api.McpService);
    const wrapper = mount(McpIntegrationsPanel, { props: { projectId: 7 } });
    await flushPromises();
    await wrapper.get('input[maxlength="80"]').setValue("Bearer服务");
    await wrapper.get('input[placeholder="https://example.com/mcp"]').setValue("https://docs.example.test/mcp");
    await wrapper.findAll("select")[1].setValue("bearer");
    await wrapper.get('input[type="password"]').setValue("synthetic-input-value");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(JSON.stringify(vi.mocked(api.prepareMcpService).mock.calls)).not.toContain("synthetic-input-value");
    expect(JSON.stringify(vi.mocked(api.preflightMcpService).mock.calls)).not.toContain("synthetic-input-value");
    expect(api.persistMcpChange).toHaveBeenCalledWith(change, { bearer: "synthetic-input-value" });
    expect(api.bindMcpService).toHaveBeenCalledWith(7, change.service_id);
    expect(api.connectIntegration).not.toHaveBeenCalled();
    expect(api.selectIntegrationTools).not.toHaveBeenCalled();
    expect(wrapper.find('input[type="password"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("项目切换丢弃旧读取回执和已输入凭据", async () => {
    let resolveOld!: (value: { items: api.McpIntegration[] }) => void;
    vi.mocked(api.listIntegrations).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const wrapper = mount(McpIntegrationsPanel, { props: { projectId: 1 } });
    await wrapper.findAll("select")[1].setValue("bearer");
    await wrapper.get('input[type="password"]').setValue("synthetic-unsaved");
    await wrapper.setProps({ projectId: 2 });
    await flushPromises();
    resolveOld({ items: [{ id: "old", name: "旧项目不应回填", tools: [], connection: {} } as unknown as api.McpIntegration] });
    await flushPromises();
    expect(wrapper.text()).not.toContain("旧项目不应回填");
    expect(wrapper.find('input[type="password"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
