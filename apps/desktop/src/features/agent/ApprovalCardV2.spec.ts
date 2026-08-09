import { describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import ApprovalCardV2 from "./ApprovalCardV2.vue";
import type {
  AgentApprovalPreview,
  AgentRunApproval,
  AgentToolExecution,
  ToolCall,
} from "../../types";
import * as agentRunsApi from "../../api/agentRuns";

function makeApproval(overrides: Partial<AgentRunApproval> = {}): AgentRunApproval {
  return {
    id: "ap-1",
    run_id: "run-1",
    tool_call_id: "tc-1",
    tool_name: "mcp.filesystem.write_file",
    tool_version: "1.0.0",
    arguments_sha256: "a".repeat(64),
    risk_level: "confirm",
    required_capabilities: ["fs.write"],
    status: "pending",
    expires_at: "2026-08-09T00:00:00Z",
    created_at: "2026-08-08T00:00:00Z",
    ...overrides,
  };
}

function makeTool(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    id: 1,
    session_id: 1,
    task_id: null,
    step_id: null,
    tool_name: "run_command",
    risk_level: "confirm",
    status: "pending_approval",
    input_json: { command: "mv screenshot-*.png archive/" },
    output_json: null,
    error_message: null,
    created_at: "2026-08-08T00:00:00Z",
    updated_at: "2026-08-08T00:00:00Z",
    ...overrides,
  };
}

describe("ApprovalCardV2", () => {
  it("Runtime 审批展示动作、范围与过期时间", () => {
    const wrapper = mount(ApprovalCardV2, { props: { approval: makeApproval() } });
    expect(wrapper.text()).toContain("mcp.filesystem.write_file");
    expect(wrapper.text()).toContain("等待审批");
    expect(wrapper.text()).toContain("fs.write");
    expect(wrapper.text()).toContain("2026/8/9");
  });

  it("批准与拒绝发出对应事件", async () => {
    const wrapper = mount(ApprovalCardV2, { props: { approval: makeApproval() } });
    const buttons = wrapper.findAll("button");
    await buttons.find((b) => b.text().includes("批准执行"))!.trigger("click");
    expect(wrapper.emitted("approve-agent")?.[0]).toEqual(["run-1", "ap-1"]);
    await buttons.find((b) => b.text().includes("拒绝"))!.trigger("click");
    expect(wrapper.emitted("reject-agent")?.[0]).toEqual(["run-1", "ap-1"]);
  });

  it("legacy 工具审批发 id 事件；已拒绝状态无操作按钮", async () => {
    const wrapper = mount(ApprovalCardV2, { props: { toolCall: makeTool() } });
    const approveBtn = wrapper.findAll("button").find((b) => b.text().includes("批准执行"));
    expect(approveBtn).toBeTruthy();
    await approveBtn!.trigger("click");
    expect(wrapper.emitted("approve-tool")?.[0]).toEqual([1]);
    const rejected = mount(ApprovalCardV2, {
      props: { toolCall: makeTool({ status: "rejected" }) },
    });
    expect(rejected.text()).toContain("已拒绝");
    expect(rejected.findAll("button").some((b) => b.text().includes("批准"))).toBe(false);
  });

  it("过期状态展示恢复提示", () => {
    const wrapper = mount(ApprovalCardV2, {
      props: { approval: makeApproval({ status: "expired" }) },
    });
    expect(wrapper.text()).toContain("已过期");
    expect(wrapper.text()).toContain("重新发起");
  });
});

describe("ApprovalCardV2 · v0.5.0 B1 文件变更预览", () => {
  function makePatchApproval(): AgentRunApproval {
    return makeApproval({ tool_name: "apply_patch_to_workspace" });
  }

  const preview: AgentApprovalPreview = {
    tool_name: "apply_patch_to_workspace",
    previewable: true,
    rel_path: "src/main.py",
    creates_file: false,
    old_sha256: "a".repeat(64),
    new_sha256: "b".repeat(64),
    diff: "--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-old\n+new",
    truncated: false,
    reason: null,
  };

  it("patch 工具审批时展示文件、SHA 与完整 diff", async () => {
    const spy = vi
      .spyOn(agentRunsApi, "getAgentApprovalPreview")
      .mockResolvedValue(preview);
    const wrapper = mount(ApprovalCardV2, {
      props: { approval: makePatchApproval() },
    });
    await flushPromises();
    expect(spy).toHaveBeenCalledWith("run-1", "ap-1");
    expect(wrapper.text()).toContain("变更预览");
    expect(wrapper.text()).toContain("src/main.py");
    expect(wrapper.text()).toContain(preview.diff);
    expect(wrapper.text()).toContain("旧 SHA");
    expect(wrapper.text()).toContain("新 SHA");
    spy.mockRestore();
  });

  it("不可预览时显示原因且不阻塞审批按钮", async () => {
    const spy = vi
      .spyOn(agentRunsApi, "getAgentApprovalPreview")
      .mockResolvedValue({
        ...preview,
        previewable: false,
        diff: null,
        reason: "审批参数不完整，无法生成预览",
      });
    const wrapper = mount(ApprovalCardV2, {
      props: { approval: makePatchApproval() },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("无法生成预览");
    expect(
      wrapper.findAll("button").some((b) => b.text().includes("批准执行"))
    ).toBe(true);
    spy.mockRestore();
  });

  it("加载失败静默降级，不抛错不阻塞", async () => {
    const spy = vi
      .spyOn(agentRunsApi, "getAgentApprovalPreview")
      .mockRejectedValue(new Error("network down"));
    const wrapper = mount(ApprovalCardV2, {
      props: { approval: makePatchApproval() },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("无法加载变更预览");
    spy.mockRestore();
  });

  it("非文件类工具不发起预览请求", () => {
    const spy = vi
      .spyOn(agentRunsApi, "getAgentApprovalPreview")
      .mockResolvedValue(preview);
    mount(ApprovalCardV2, { props: { approval: makeApproval() } });
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});

describe("ApprovalCardV2 · v0.5.0 B2 命令实时输出", () => {
  const execution: AgentToolExecution = {
    id: "exec-1",
    tool_name: "run_whitelisted_command",
    tool_version: "1.0.0",
    status: "running",
    error_code: null,
    error_message: null,
    output: {
      args: ["pytest", "-q"],
      cwd: "F:\\project",
      returncode: 0,
      succeeded: true,
      processes_remaining: 0,
    },
    created_at: "2026-08-09T00:00:00Z",
    completed_at: null,
  };

  function makeCommandApproval(status: AgentRunApproval["status"]): AgentRunApproval {
    return makeApproval({ tool_name: "run_whitelisted_command", status });
  }

  it("审批通过后拉取 executions 并轮询展示流式输出与退出码", async () => {
    vi.spyOn(agentRunsApi, "listAgentRunExecutions").mockResolvedValue([execution]);
    const pageSpy = vi
      .spyOn(agentRunsApi, "getAgentToolOutput")
      .mockResolvedValueOnce({
        lines: [
          { seq: 0, kind: "stdout", text: "collecting..." },
          { seq: 1, kind: "stdout", text: "1 passed" },
        ],
        last_seq: 1,
        finished: false,
      })
      .mockResolvedValueOnce({
        lines: [],
        last_seq: 1,
        finished: true,
      });
    const wrapper = mount(ApprovalCardV2, {
      props: { approval: makeCommandApproval("approved") },
    });
    await flushPromises();
    await flushPromises();
    expect(pageSpy).toHaveBeenCalledWith("run-1", "exec-1", -1);
    expect(wrapper.text()).toContain("pytest -q");
    expect(wrapper.text()).toContain("collecting...");
    expect(wrapper.text()).toContain("1 passed");
    vi.restoreAllMocks();
  });

  it("完成后展示退出码徽标与进程树残留", async () => {
    vi.spyOn(agentRunsApi, "listAgentRunExecutions").mockResolvedValue([
      { ...execution, status: "succeeded" },
    ]);
    vi.spyOn(agentRunsApi, "getAgentToolOutput").mockResolvedValue({
      lines: [{ seq: 0, kind: "stdout", text: "1 passed" }],
      last_seq: 0,
      finished: true,
    });
    const wrapper = mount(ApprovalCardV2, {
      props: { approval: makeCommandApproval("consumed") },
    });
    await flushPromises();
    await flushPromises();
    expect(wrapper.text()).toContain("成功");
    expect(wrapper.text()).toContain("F:\\project");
    vi.restoreAllMocks();
  });

  it("非命令工具不发起命令轮询", () => {
    const spy = vi.spyOn(agentRunsApi, "listAgentRunExecutions");
    mount(ApprovalCardV2, {
      props: { approval: makeApproval({ status: "approved" }) },
    });
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});
