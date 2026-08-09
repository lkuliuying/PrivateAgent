import type {
  Activity,
  AgentRunApproval,
  Session,
  Source,
  ToolCall,
  TrustedPath,
} from "../types";
import type { AgentWorkspaceMessage } from "../models/agentWorkspace";

/**
 * 0.4.0 D0 全状态 fixture 集（仅开发模式 / UI Lab / 测试使用，生产构建不引用）。
 * 覆盖 docs/releases/v0.4.0/ui-state-matrix-0.4.0.md 的全部核心场景，使用真实公开 DTO 类型，
 * 与 v0.3.0-public-contracts.md 冻结的状态语义一一对应，禁止虚构后端状态。
 */

export interface WorkspaceFixture {
  key: string;
  label: string;
  description: string;
  session: Session;
  messages: AgentWorkspaceMessage[];
  streaming: boolean;
  trusted: TrustedPath[];
  activities: Activity[];
  sources?: Source[];
}

const BASE = Date.now() - 18 * 60_000;
const at = (minutes: number) => new Date(BASE + minutes * 60_000).toISOString();

function makeSession(id: number, title: string): Session {
  return { id, title, created_at: at(0), updated_at: at(10) };
}

function userMsg(sessionId: number, id: number, content: string, min = 0): AgentWorkspaceMessage {
  return {
    id,
    session_id: sessionId,
    role: "user",
    content,
    created_at: at(min),
    clientKey: `fx-user-${id}`,
  };
}

function agentMsg(
  sessionId: number,
  id: number,
  content: string,
  min = 1,
  extra?: Partial<AgentWorkspaceMessage>
): AgentWorkspaceMessage {
  return {
    id,
    session_id: sessionId,
    role: "assistant",
    content,
    created_at: at(min),
    clientKey: `fx-agent-${id}`,
    ...extra,
  };
}

function toolCall(
  sessionId: number,
  id: number,
  toolName: string,
  status: ToolCall["status"],
  risk: ToolCall["risk_level"],
  input: Record<string, unknown>,
  output: Record<string, unknown> | null = null,
  error: string | null = null,
  min = 2
): ToolCall {
  return {
    id,
    session_id: sessionId,
    task_id: null,
    step_id: null,
    tool_name: toolName,
    risk_level: risk,
    status,
    input_json: input,
    output_json: output,
    error_message: error,
    created_at: at(min),
    updated_at: at(min + 1),
  };
}

function runApproval(
  id: string,
  runId: string,
  status: AgentRunApproval["status"],
  toolName = "mcp.filesystem.write_file"
): AgentRunApproval {
  return {
    id,
    run_id: runId,
    tool_call_id: `tc-${id}`,
    tool_name: toolName,
    tool_version: "1.0.0",
    arguments_sha256: "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    risk_level: "confirm",
    required_capabilities: ["fs.write"],
    status,
    expires_at: at(30),
    created_at: at(4),
  };
}

const DEFAULT_TRUSTED: TrustedPath[] = [
  {
    id: -8001,
    path: "F:\\Program\\Agent\\apps\\desktop\\src",
    kind: "directory",
    granted_at: at(0),
  },
  {
    id: -8002,
    path: "F:\\Program\\Agent\\docs\\releases\\v0.4.0\\v0.4.0-ui-ux-redesign-plan.md",
    kind: "file",
    granted_at: at(1),
  },
];

function fixture(partial: Partial<WorkspaceFixture> & Pick<WorkspaceFixture, "key" | "label" | "description" | "session" | "messages">): WorkspaceFixture {
  return {
    streaming: false,
    trusted: DEFAULT_TRUSTED,
    activities: [],
    ...partial,
  };
}

/* ============ 各场景 fixture ============ */

const emptySession = makeSession(-7001, "新任务");

const streamingSession = makeSession(-7002, "整理本周项目进展");
const streamingMessages: AgentWorkspaceMessage[] = [
  userMsg(streamingSession.id, -7101, "帮我把本周的项目进展整理成一份简报。"),
  agentMsg(
    streamingSession.id,
    -7102,
    "好的，我先梳理本周的活动记录与任务完成情况，然后输出结构化简报。目前已找到 4 条相关任务记录，正在汇总关键结论",
    2,
    { runId: "run-fx-stream" }
  ),
];

const toolSession = makeSession(-7003, "检查桌面端构建配置");
const toolRunning = toolCall(
  toolSession.id,
  -7201,
  "read_file",
  "running",
  "safe",
  { path: "apps/desktop/vite.config.ts" }
);
const toolSucceeded = toolCall(
  toolSession.id,
  -7202,
  "search_files",
  "succeeded",
  "safe",
  { query: "manualChunks" },
  { matches: 3, files: ["vite.config.ts", "src-tauri/tauri.conf.json"] },
  null,
  0
);

const approvalSession = makeSession(-7004, "同步笔记到本地知识库");
const pendingApproval = runApproval("fx-approval-1", "run-fx-approval", "pending");

const legacySession = makeSession(-7005, "批量重命名下载目录截图");
const legacyPending = toolCall(
  legacySession.id,
  -7301,
  "run_command",
  "pending_approval",
  "confirm",
  { command: "mv screenshot-*.png archive/" }
);

const resolvedSession = makeSession(-7006, "导出月度支出报表");
const consumedApproval = runApproval("fx-approval-2", "run-fx-done", "consumed", "mcp.exporter.run");

const failedSession = makeSession(-7007, "扫描照片目录并去重");
const failedTool = toolCall(
  failedSession.id,
  -7401,
  "scan_directory",
  "failed",
  "safe",
  { path: "D:\\Photos" },
  null,
  "目录不存在或已被移动：D:\\Photos",
  2
);

const stoppedSession = makeSession(-7008, "写一篇季度复盘草稿");

const ragSession = makeSession(-7009, "我们的数据库备份策略是什么");
const ragSources: Source[] = [
  {
    doc_name: "运维手册-备份章节.md",
    ordinal: 3,
    chunk_id: 418,
    heading: "每日备份",
    score: 0.86,
    fusion_score: 0.81,
    matched_via: ["dense", "bm25"],
  },
  {
    doc_name: "database-upgrade-runbook.md",
    ordinal: 1,
    chunk_id: 87,
    heading: "回滚路径",
    score: 0.74,
    fusion_score: 0.7,
    matched_via: ["dense"],
  },
];

const refusalSession = makeSession(-7010, "公司下一季度的营收目标是多少");

const reconnectSession = makeSession(-7011, "持续跟进今天的任务清单");

const artifactSession = makeSession(-7012, "生成工作台视觉审计报告");
const artifactActivities: Activity[] = [
  {
    id: -7501,
    session_id: artifactSession.id,
    kind: "system",
    title: "视觉审计报告.md",
    status: "succeeded",
    ref_type: "report",
    ref_id: null,
    detail_json: { artifact: "document", size_bytes: 18432, pages: 6 },
    error_message: null,
    started_at: at(6),
    finished_at: at(9),
    created_at: at(6),
    updated_at: at(9),
  },
  {
    id: -7502,
    session_id: artifactSession.id,
    kind: "system",
    title: "token-coverage.csv",
    status: "succeeded",
    ref_type: "export",
    ref_id: null,
    detail_json: { artifact: "report", rows: 214 },
    error_message: null,
    started_at: at(8),
    finished_at: at(10),
    created_at: at(8),
    updated_at: at(10),
  },
];

export const workspaceFixtures: WorkspaceFixture[] = [
  fixture({
    key: "empty",
    label: "空任务",
    description: "idle：无消息的空会话，展示空状态引导与任务输入。",
    session: emptySession,
    messages: [],
  }),
  fixture({
    key: "planning",
    label: "正在规划",
    description: "legacy planner 规划阶段：已发送请求，plan 尚未返回。",
    session: makeSession(-7013, "规划一次数据迁移"),
    messages: [userMsg(-7013, -7151, "帮我规划一次从旧库到新库的数据迁移。")],
    streaming: true,
  }),
  fixture({
    key: "streaming",
    label: "流式回答",
    description: "running：无工具调用的普通流式生成。",
    session: streamingSession,
    messages: streamingMessages,
    streaming: true,
  }),
  fixture({
    key: "tool-running",
    label: "工具执行中",
    description: "running：一个工具已完成搜索，另一个正在读取文件。",
    session: toolSession,
    messages: [
      userMsg(toolSession.id, -7203, "检查桌面端构建配置里手动分包是否正确。"),
      agentMsg(toolSession.id, -7204, "", 1, { tool_call: toolSucceeded }),
      agentMsg(toolSession.id, -7205, "已定位到 3 处分包配置，继续读取主配置确认。", 2),
      agentMsg(toolSession.id, -7206, "", 2, { tool_call: toolRunning }),
    ],
    streaming: true,
  }),
  fixture({
    key: "approval-pending",
    label: "等待审批（Runtime）",
    description: "waiting：Runtime 审批卡待处理，含参数指纹与过期时间。",
    session: approvalSession,
    messages: [
      userMsg(approvalSession.id, -7251, "把今天的三篇笔记同步到本地知识库。"),
      agentMsg(approvalSession.id, -7252, "已整理 3 篇笔记，写入前需要你的确认。", 3),
      agentMsg(approvalSession.id, -7253, "", 4, {
        agent_approval: pendingApproval,
        runId: pendingApproval.run_id,
      }),
    ],
  }),
  fixture({
    key: "legacy-tool-pending",
    label: "等待审批（legacy 工具）",
    description: "waiting：legacy planner 的 run_command 待审批。",
    session: legacySession,
    messages: [
      userMsg(legacySession.id, -7302, "把下载目录里这个月的截图批量移到 archive。"),
      agentMsg(legacySession.id, -7303, "", 2, { tool_call: legacyPending }),
    ],
  }),
  fixture({
    key: "approval-resolved",
    label: "审批已消费",
    description: "审批批准后原位转为 consumed，并给出最终结果。",
    session: resolvedSession,
    messages: [
      userMsg(resolvedSession.id, -7351, "导出上个月的家庭支出报表。"),
      agentMsg(resolvedSession.id, -7352, "", 4, {
        agent_approval: consumedApproval,
        runId: consumedApproval.run_id,
      }),
      agentMsg(
        resolvedSession.id,
        -7353,
        "报表已导出到「文档/exports/2026-07-支出.csv」，共 87 行，合计 12,480 元。",
        8,
        { runId: consumedApproval.run_id }
      ),
    ],
  }),
  fixture({
    key: "failed",
    label: "执行失败",
    description: "failed：工具执行失败，错误块给出原因与恢复动作。",
    session: failedSession,
    messages: [
      userMsg(failedSession.id, -7402, "扫描 D:\\Photos 并找出重复照片。"),
      agentMsg(failedSession.id, -7403, "", 2, { tool_call: failedTool }),
      agentMsg(
        failedSession.id,
        -7404,
        "扫描中断：目标目录不存在。已完成的步骤：解析任务目标。你可以确认路径后重试，或先授权新的照片目录。",
        3
      ),
    ],
  }),
  fixture({
    key: "stopped",
    label: "已停止",
    description: "stopped：用户在生成中点击停止，保留已完成的部分内容。",
    session: stoppedSession,
    messages: [
      userMsg(stoppedSession.id, -7451, "写一篇季度复盘草稿，先从工作部分开始。"),
      agentMsg(
        stoppedSession.id,
        -7452,
        "本季度主要推进了三件事：工作台重构、知识库索引优化……（已停止）",
        2
      ),
    ],
  }),
  fixture({
    key: "rag-answer",
    label: "RAG 带来源回答",
    description: "completed：回答附 RAG 来源，右栏 Sources 可核对引用。",
    session: ragSession,
    messages: [
      userMsg(ragSession.id, -7503, "我们的数据库备份策略是什么？"),
      agentMsg(
        ragSession.id,
        -7504,
        "根据运维手册：数据库每日 02:00 全量备份，保留 30 天；升级前必须执行一次手动备份并验证回滚路径。[1][2]",
        3,
        { sources: ragSources }
      ),
    ],
    sources: ragSources,
  }),
  fixture({
    key: "rag-refusal",
    label: "RAG 引用拒答",
    description: "知识库无可信来源时明确拒答，不编造。",
    session: refusalSession,
    messages: [
      userMsg(refusalSession.id, -7551, "公司下一季度的营收目标是多少？"),
      agentMsg(
        refusalSession.id,
        -7552,
        "本地知识库中没有找到与此相关的可信来源，我无法可靠回答。你可以先导入经营计划相关文档，或关闭知识检索后让我基于一般方法给建议。",
        3
      ),
    ],
  }),
  fixture({
    key: "reconnecting",
    label: "断线重连",
    description: "sidecar 断开后展示连接提示，恢复后续传，不伪造终态。",
    session: reconnectSession,
    messages: [
      userMsg(reconnectSession.id, -7601, "持续跟进今天的任务清单，有变化随时告诉我。"),
      agentMsg(
        reconnectSession.id,
        -7602,
        "连接中断后已自动恢复，以下为断开前已确认的内容：今日有 2 个任务待处理……\n\n[连接已恢复]",
        2
      ),
    ],
  }),
  fixture({
    key: "artifacts",
    label: "完成与多产物",
    description: "completed：任务完成后 Artifacts 列出文档与导出报表。",
    session: artifactSession,
    messages: [
      userMsg(artifactSession.id, -7505, "生成工作台视觉审计报告，并导出令牌覆盖数据。"),
      agentMsg(
        artifactSession.id,
        -7506,
        "审计完成。报告共 6 页，覆盖 54 个组件；令牌覆盖率 78%，明细已导出 CSV。",
        10
      ),
    ],
    activities: artifactActivities,
  }),
];

export function getWorkspaceFixture(key: string): WorkspaceFixture | null {
  return workspaceFixtures.find((item) => item.key === key) ?? null;
}
