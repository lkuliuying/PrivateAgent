/**
 * v0.8.0 W6-R3 · Agent 标题区工作目录 / Git 分支事实（typed contract）
 *
 * 数据来源：当前 session 绑定的 workspace 公开 DTO（GET /projects/{pid}/workspaces）。
 * 组件不调用 git/fetch/invoke；状态推导为纯函数，迟到响应由调用方以
 * generation id 拒绝（防止显示上一会话的目录与分支）。
 */

export interface WorkspaceDtoLike {
  kind: string;
  branch_name: string | null;
  head_sha: string | null;
  status: string;
  root_path: string | null;
}

export type AgentGitState =
  /** 正常分支（含 root 工作区已登记分支） */
  | { kind: "branch"; branch: string; headShort: string | null }
  /** 有 HEAD 但无分支名：detached HEAD */
  | { kind: "detached"; headShort: string }
  /** 无分支且无 HEAD：非 Git 目录 */
  | { kind: "non-git" }
  /** workspace 缺失/归档/路径缺失 */
  | { kind: "path-invalid"; reason: string }
  /** 读取失败（网络/后端异常） */
  | { kind: "read-failed" }
  /** session 未绑定项目 */
  | { kind: "no-project" }
  /** 加载中（切换期间不得沿用旧值） */
  | { kind: "loading" };

export interface AgentWorkspaceFacts {
  /** 当前授权工作目录（公开 workspace 事实；呈现层截断/复制） */
  rootPath: string | null;
  git: AgentGitState;
}

export function shortSha(headSha: string | null): string | null {
  if (!headSha) return null;
  return headSha.slice(0, 7);
}

/** 从公开 workspace DTO 推导工作目录与 Git 状态（不猜测、不执行 git）。 */
export function deriveAgentWorkspaceFacts(input: {
  hasProject: boolean;
  workspace: WorkspaceDtoLike | null;
}): AgentWorkspaceFacts {
  if (!input.hasProject) {
    return { rootPath: null, git: { kind: "no-project" } };
  }
  const workspace = input.workspace;
  if (!workspace) {
    return {
      rootPath: null,
      git: { kind: "path-invalid", reason: "工作区不可用" },
    };
  }
  if (workspace.status === "archived" || workspace.status === "missing") {
    return {
      rootPath: workspace.root_path,
      git: {
        kind: "path-invalid",
        reason: workspace.status === "missing" ? "路径缺失" : "工作区已归档",
      },
    };
  }
  if (workspace.branch_name) {
    return {
      rootPath: workspace.root_path,
      git: { kind: "branch", branch: workspace.branch_name, headShort: shortSha(workspace.head_sha) },
    };
  }
  if (workspace.head_sha) {
    return {
      rootPath: workspace.root_path,
      git: { kind: "detached", headShort: shortSha(workspace.head_sha) ?? "" },
    };
  }
  return { rootPath: workspace.root_path, git: { kind: "non-git" } };
}

/** Git 状态呈现文案（真实降级，不沿用旧值）。 */
export function gitStateLabel(state: AgentGitState): string {
  switch (state.kind) {
    case "branch":
      return state.branch;
    case "detached":
      return `detached · ${state.headShort}`;
    case "non-git":
      return "非 Git 目录";
    case "path-invalid":
      return state.reason;
    case "read-failed":
      return "读取失败";
    case "no-project":
      return "未关联授权项目";
    case "loading":
      return "读取中…";
  }
}

/** 长路径展示：保留首段与末两段，中间省略（完整值经 tooltip/复制提供）。 */
export function truncatePath(path: string, max = 46): string {
  if (path.length <= max) return path;
  const normalized = path.replace(/\\/g, "/");
  const segments = normalized.split("/").filter(Boolean);
  if (segments.length <= 3) return `${normalized.slice(0, max - 1)}…`;
  const head = segments[0];
  const tail = segments.slice(-2).join("/");
  return `${head}/…/${tail}`;
}
