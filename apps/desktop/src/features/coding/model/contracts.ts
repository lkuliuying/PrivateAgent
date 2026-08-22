/**
 * v0.8.0 W1 · Coding 领域契约
 *
 * 事实源：v0.7.0 交接包 §1（DTO 样本）与后端 routes DTO（ProjectOut /
 * WorkspaceOut / SessionOut / ModelProfileOut）。新契约只进本模块，
 * 不回填全局 types.ts（计划 §5.4）。
 *
 * 敏感字段红线（交接包 §5）：root_path 原文、approval token、Provider
 * secret、完整命令输出、diff 原文、本地绝对路径不得进入 UI——本模块的
 * 契约字段从结构上排除这些字段（映射函数见 features/coding/api/*）。
 */

/** 项目摘要（GET /projects，剔除 root_path/扫描时间等敏感或非呈现字段） */
export interface CodingProjectSummary {
  id: number;
  name: string;
  status: "active" | "archived";
  updatedAt: string;
}

/** 工作区摘要（GET /projects/{id}/workspaces；status 为后端冻结枚举） */
export interface CodingWorkspaceSummary {
  id: number;
  projectId: number;
  kind: "root" | "git_worktree";
  /** root 工作区可能尚未登记分支 */
  branchName: string | null;
  headSha: string | null;
  status: "active" | "missing" | "dirty" | "archived" | "conflict";
  lastUsedAt: string | null;
}

/** 任务线程摘要（GET /sessions?project_id=&kind=coding） */
export interface CodingThreadSummary {
  id: number;
  title: string;
  projectId: number;
  workspaceId: number | null;
  updatedAt: string;
  lastRunId: string | null;
}

/** 模型 profile 摘要（GET /agent-model-profiles，无任何 secret 字段） */
export interface CodingModelProfileSummary {
  id: string;
  provider: "ollama" | "openai" | "claude";
  displayName: string;
  isLocal: boolean;
  reasoningEfforts: string[] | null;
}

/** v0.7.0 冻结的权限三模式（W3 输入器消费，此处先冻结契约） */
export type CodingPermissionMode = "readonly" | "confirm" | "workspace";

/**
 * 后端错误契约：平铺 JSON {error_code, detail}（core/coding_errors.py）。
 * code 为 28 个冻结错误码之一；message 已按「不含本地路径」约束来自后端
 * detail，前端不拼接路径类信息。
 */
export interface CodingApiError {
  status: number;
  code: string;
  message: string;
}

/** 模型 profile 加载结果：409 coding_mode_disabled 是能力未开放而非故障 */
export type CodingModelProfilesResult =
  | { status: "ok"; profiles: CodingModelProfileSummary[] }
  | { status: "disabled" }
  | { status: "error"; message: string };

/**
 * 首页状态（计划 §4.2 + W0 冻结矩阵 §3 第 1–6 项）。
 * 派生优先级见 codingWorkspaceStore.homeState。
 */
export type CodingHomeState =
  | "loading"
  | "sidecar-unavailable"
  | "load-error"
  | "no-projects"
  | "no-workspace"
  | "provider-unconfigured"
  | "workspace-invalid"
  | "ready";

export interface CodingThreadCreateInput {
  projectId: number;
  workspaceId: number;
  title: string;
}

/** store 数据源注入：生产 = REST 封装，测试/预览夹具 = 领域内伪实现 */
export interface CodingWorkspaceFetchers {
  projects: () => Promise<CodingProjectSummary[]>;
  workspaces: (projectId: number) => Promise<CodingWorkspaceSummary[]>;
  threads: (projectId: number) => Promise<CodingThreadSummary[]>;
  modelProfiles: () => Promise<CodingModelProfilesResult>;
  /** /health 可达即视为 sidecar 就绪（依赖项故障由状态栏呈现，不阻断首页） */
  health: () => Promise<boolean>;
  createThread: (input: CodingThreadCreateInput) => Promise<CodingThreadSummary>;
  ensureRootWorkspace: (projectId: number) => Promise<CodingWorkspaceSummary>;
}

/** 侧栏树节点：Project → Workspace/branch → Thread（W0 冻结 §2.1） */
export interface CodingWorkspaceNode {
  workspace: CodingWorkspaceSummary;
  threads: CodingThreadSummary[];
}

export interface CodingProjectNode {
  project: CodingProjectSummary;
  workspaces: CodingWorkspaceNode[];
  /** workspace 已归档/缺失但仍有线程时兜底展示 */
  orphanThreads: CodingThreadSummary[];
}

/** 工作区状态呈现语义（dirty 属正常编码态，用中性强调；异常态用警告色系） */
export const WORKSPACE_STATUS_META: Record<
  CodingWorkspaceSummary["status"],
  { label: string; tone: "neutral" | "info" | "warning" | "danger" }
> = {
  active: { label: "正常", tone: "neutral" },
  dirty: { label: "有未提交更改", tone: "info" },
  missing: { label: "路径缺失", tone: "danger" },
  conflict: { label: "存在冲突", tone: "warning" },
  archived: { label: "已归档", tone: "neutral" },
};

/** 首页可用即认为工作区可发起任务（dirty 允许） */
export function isWorkspaceUsable(workspace: CodingWorkspaceSummary): boolean {
  return workspace.status === "active" || workspace.status === "dirty";
}
