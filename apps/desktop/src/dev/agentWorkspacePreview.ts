import type { Activity, Session, ToolCall, TrustedPath } from "../types";
import type { AgentWorkspaceMessage } from "../models/agentWorkspace";

/**
 * 仅用于本地视觉回归的显式预览夹具。
 * 通过 ?workspace-preview=running 启用；生产构建不会进入该分支。
 */
export function createAgentWorkspacePreview(): {
  session: Session;
  messages: AgentWorkspaceMessage[];
  trusted: TrustedPath[];
  activities: Activity[];
} {
  const base = Date.now() - 12 * 60_000;
  const at = (minutes: number) => new Date(base + minutes * 60_000).toISOString();
  const session: Session = {
    id: -9100,
    title: "重构个人 Agent 工作台界面",
    created_at: at(0),
    updated_at: at(11),
  };
  const readTool: ToolCall = {
    id: -9101,
    session_id: session.id,
    task_id: null,
    step_id: null,
    tool_name: "read_file",
    risk_level: "safe",
    status: "succeeded",
    input_json: { path: "apps/desktop/src/components/WorkspaceShell.vue" },
    output_json: {
      path: "apps/desktop/src/components/WorkspaceShell.vue",
      size_bytes: 8240,
      content: "已读取工作台壳层、导航与响应式布局实现。",
      truncated: false,
    },
    error_message: null,
    created_at: at(3),
    updated_at: at(4),
  };
  const changeTool: ToolCall = {
    id: -9102,
    session_id: session.id,
    task_id: null,
    step_id: null,
    tool_name: "apply_patch",
    risk_level: "confirm",
    status: "running",
    input_json: {
      files: [
        "WorkspaceShell.vue",
        "NavRail.vue",
        "ChatView.vue",
        "InspectorPanel.vue",
      ],
      summary: "重组三栏工作台并接入计划与活动流",
    },
    output_json: null,
    error_message: null,
    created_at: at(9),
    updated_at: at(11),
  };

  return {
    session,
    messages: [
      {
        id: -9201,
        session_id: session.id,
        role: "user",
        content:
          "依据参考图重构个人 Agent 工作台，保留现有本地接口与业务能力，并完善计划、活动流和上下文面板。",
        created_at: at(0),
        clientKey: "preview-user",
      },
      {
        id: -9202,
        session_id: session.id,
        role: "assistant",
        content:
          "已完成项目结构与现有页面检查。当前重点是合并左侧导航与最近任务、扩大中央工作区，并让执行状态更容易扫描。",
        created_at: at(2),
        clientKey: "preview-analysis",
      },
      {
        id: -9203,
        session_id: session.id,
        role: "assistant",
        content: "",
        created_at: at(3),
        tool_call: readTool,
        clientKey: "preview-read-tool",
      },
      {
        id: -9204,
        session_id: session.id,
        role: "assistant",
        content:
          "正在更新设计令牌与工作台组件，三栏将保持独立滚动，1280px 下自动隐藏右侧上下文栏。",
        created_at: at(7),
        clientKey: "preview-progress",
      },
      {
        id: -9205,
        session_id: session.id,
        role: "assistant",
        content: "",
        created_at: at(9),
        tool_call: changeTool,
        clientKey: "preview-change-tool",
      },
    ],
    trusted: [
      {
        id: -9301,
        path: "F:\\Program\\Agent\\apps\\desktop\\src\\components",
        kind: "directory",
        granted_at: at(1),
      },
      {
        id: -9302,
        path: "F:\\Program\\Agent\\apps\\desktop\\src\\design\\tokens.css",
        kind: "file",
        granted_at: at(2),
      },
      {
        id: -9303,
        path: "F:\\Program\\Agent\\docs\\personal-agent-ui-refactor-prompt.md",
        kind: "file",
        granted_at: at(2),
      },
    ],
    activities: [
      {
        id: -9401,
        session_id: session.id,
        kind: "tool",
        title: "界面重构变更摘要",
        status: "succeeded",
        ref_type: "tool_call",
        ref_id: changeTool.id,
        detail_json: {
          files_changed: 10,
          components_added: 3,
          validation: "vue-tsc passed",
        },
        error_message: null,
        started_at: at(4),
        finished_at: at(10),
        created_at: at(4),
        updated_at: at(10),
      },
      {
        id: -9402,
        session_id: session.id,
        kind: "system",
        title: "响应式与可访问性检查",
        status: "succeeded",
        ref_type: "report",
        ref_id: null,
        detail_json: {
          viewports: [1280, 1440, 1920],
          focus_states: "verified",
        },
        error_message: null,
        started_at: at(9),
        finished_at: at(11),
        created_at: at(9),
        updated_at: at(11),
      },
    ],
  };
}
