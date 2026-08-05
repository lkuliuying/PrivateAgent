import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  cmdPromptMcpSecret,
  createMcpServer,
  listMcpServers,
  updateMcpServerState,
  type McpServer,
} from "../api";
import McpServersPanel from "./McpServersPanel.vue";

vi.mock("../api", () => ({
  cmdClearMcpSecret: vi.fn(),
  cmdMcpSecretStatus: vi.fn(),
  cmdPromptMcpSecret: vi.fn(),
  createMcpServer: vi.fn(),
  deleteMcpServer: vi.fn(),
  discoverMcpServer: vi.fn(),
  listMcpCalls: vi.fn(),
  listMcpServers: vi.fn(),
  updateMcpServerState: vi.fn(),
}));
vi.mock("../stores/notifications", () => ({
  useNotifications: () => ({
    confirm: vi.fn(),
    success: vi.fn(),
    error: vi.fn(),
  }),
}));

const server: McpServer = {
  id: "server-1",
  name: "Local tools",
  transport: "stdio",
  command: "python",
  args: ["server.py"],
  working_directory: null,
  url: null,
  env_names: [],
  secret_ref_names: [],
  allow_insecure_local: false,
  allow_private_network: false,
  trusted: false,
  enabled: false,
  allowed_tools: [],
  timeout_ms: 30_000,
  max_output_bytes: 262_144,
  status: "disabled",
  last_error_code: null,
  tools: [
    {
      name: "echo",
      title: "Echo",
      description: "Read-only echo",
      input_schema: { type: "object" },
    },
  ],
  resources: [],
  prompts: [],
  discovery_sha256: "abc",
  last_checked_at: null,
  discovered_at: null,
  created_at: "2026-08-02T00:00:00",
  updated_at: "2026-08-02T00:00:00",
};

beforeEach(() => vi.clearAllMocks());

describe("McpServersPanel", () => {
  it("shows the default-off boundary without surfacing a noisy error", async () => {
    vi.mocked(listMcpServers).mockRejectedValue(new Error("Not found"));
    const wrapper = mount(McpServersPanel);
    await flushPromises();

    expect(wrapper.text()).toContain("PA_MCP_ENABLED=true");
    wrapper.unmount();
  });

  it("persists explicit trust, enablement, and a discovered-tool allowlist", async () => {
    vi.mocked(listMcpServers).mockResolvedValue([{ ...server }]);
    vi.mocked(updateMcpServerState).mockImplementation(async (value) => ({
      ...server,
      ...value,
    }));
    const wrapper = mount(McpServersPanel);
    await flushPromises();

    const checks = wrapper.findAll('input[type="checkbox"]');
    await checks[0].setValue(true);
    await checks[1].setValue(true);
    await checks[2].setValue(true);
    const save = wrapper.findAll("button").find((button) => button.text() === "保存白名单");
    expect(save).toBeDefined();
    await save!.trigger("click");
    await flushPromises();

    expect(updateMcpServerState).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "server-1",
        trusted: true,
        enabled: true,
        allowed_tools: ["echo"],
      })
    );
    wrapper.unmount();
  });

  it("stores only an OS-keyring reference for a stdio credential", async () => {
    vi.mocked(listMcpServers).mockResolvedValue([]);
    vi.mocked(cmdPromptMcpSecret).mockResolvedValue({
      reference: "secret://os-keyring/mcp/github-prod",
      configured: true,
      cancelled: false,
    });
    vi.mocked(createMcpServer).mockResolvedValue({ ...server, id: "created" });
    const wrapper = mount(McpServersPanel);
    await flushPromises();

    const open = wrapper.findAll("button").find((button) => button.text() === "登记 Server");
    await open!.trigger("click");
    const inputs = wrapper.findAll("input");
    await inputs.find((input) => input.attributes("placeholder")?.includes("本地文件"))!.setValue("GitHub MCP");
    await inputs.find((input) => input.attributes("placeholder")?.includes("绝对路径"))!.setValue("C:\\mcp.exe");
    await wrapper.findAll("select")[1].setValue("stdio_env");
    await wrapper.find('input[placeholder="例如：github-prod"]').setValue("github-prod");
    await wrapper.find('input[placeholder="例如：GITHUB_TOKEN"]').setValue("GITHUB_TOKEN");
    const configure = wrapper
      .findAll("button")
      .find((button) => button.text() === "在系统凭据库中设置");
    await configure!.trigger("click");
    await flushPromises();
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(createMcpServer).toHaveBeenCalledWith(
      expect.objectContaining({
        secret_refs: {
          "env:GITHUB_TOKEN": "secret://os-keyring/mcp/github-prod",
        },
      })
    );
    wrapper.unmount();
  });
});
