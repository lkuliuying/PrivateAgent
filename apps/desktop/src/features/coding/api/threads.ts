/**
 * v0.8.0 W1 · Coding 任务线程 API（GET/POST /sessions，kind=coding）
 *
 * 会话创建校验链在后端（coding_context_incomplete 422 / coding_mode_disabled
 * 409 / workspace_not_found 404 / workspace_outside_trust 403），前端只把
 * CodingApiError 透传给 store/组件呈现。
 */
import type { Session } from "../../../types";
import type { CodingThreadCreateInput, CodingThreadSummary } from "../model/contracts";
import { codingFetchJson, codingJsonInit } from "./codingHttp";

export function toThreadSummary(dto: Session, projectId: number): CodingThreadSummary {
  return {
    id: dto.id,
    title: dto.title,
    projectId,
    workspaceId: dto.workspace_id ?? null,
    updatedAt: dto.updated_at,
    lastRunId: dto.last_run_id ?? null,
    pinnedAt: dto.pinned_at ?? null,
    archivedAt: dto.archived_at ?? null,
    kind: dto.kind ?? null,
  };
}

/** 按项目拉取 coding 线程（后端按 updated_at 倒序返回） */
export async function fetchCodingThreads(projectId: number): Promise<CodingThreadSummary[]> {
  const list = await codingFetchJson<Session[]>(
    `/sessions?project_id=${projectId}&kind=coding`
  );
  return list.map((dto) => toThreadSummary(dto, projectId));
}

/**
 * 从首页/侧栏发起新任务：创建 coding 会话（kind/project_id/workspace_id
 * 成对出现即 coding 判定）。W1 只建线程；首轮消息与 run 提交在 W2 接入。
 */
export async function createCodingThread(input: CodingThreadCreateInput): Promise<CodingThreadSummary> {
  const dto = await codingFetchJson<Session>(
    "/sessions",
    codingJsonInit("POST", {
      title: input.title,
      project_id: input.projectId,
      workspace_id: input.workspaceId,
      kind: "coding",
    })
  );
  return toThreadSummary(dto, input.projectId);
}

/**
 * v0.9.0 H1：legacy/unbound 会话显式迁移绑定到项目（唯一入口）。
 * 契约（H0 §4.2）：不批量、不按最近项目猜测；已绑定会话拒绝重复绑定。
 */
export async function bindSessionToProject(
  sessionId: number,
  projectId: number,
  workspaceId: number
): Promise<CodingThreadSummary> {
  const dto = await codingFetchJson<Session>(
    `/sessions/${sessionId}/bind-project`,
    codingJsonInit("POST", { project_id: projectId, workspace_id: workspaceId })
  );
  return toThreadSummary(dto, projectId);
}

// ============================================================================
// v0.9.0 H4：线程管理（重命名/归档/置顶/搜索/最近任务）
// ============================================================================

/** 重命名线程标题（后端有界校验）。 */
export async function renameThread(
  sessionId: number,
  title: string
): Promise<Session> {
  return codingFetchJson<Session>(
    `/sessions/${sessionId}/title`,
    codingJsonInit("PATCH", { title })
  );
}

/** 归档/恢复（软删除，不物理删除数据）。 */
export async function setThreadArchived(
  sessionId: number,
  archived: boolean
): Promise<Session> {
  return codingFetchJson<Session>(
    `/sessions/${sessionId}/${archived ? "archive" : "unarchive"}`,
    codingJsonInit("POST", {})
  );
}

/** 置顶/取消置顶（最近任务优先呈现）。 */
export async function setThreadPinned(
  sessionId: number,
  pinned: boolean
): Promise<Session> {
  return codingFetchJson<Session>(
    `/sessions/${sessionId}/${pinned ? "pin" : "unpin"}`,
    codingJsonInit("POST", {})
  );
}

/** 最近任务：置顶优先 → 更新时间倒序（不含已归档）。 */
export async function fetchRecentThreads(
  limit = 10
): Promise<CodingThreadSummary[]> {
  const list = await codingFetchJson<Session[]>(
    `/sessions/recent?kind=coding&limit=${limit}`
  );
  return list.map((dto) => toThreadSummary(dto, dto.project_id ?? 0));
}

/** 按标题搜索线程（不含已归档）。 */
export async function searchThreads(
  keyword: string,
  limit = 30
): Promise<CodingThreadSummary[]> {
  const list = await codingFetchJson<Session[]>(
    `/sessions/search?q=${encodeURIComponent(keyword)}&kind=coding&limit=${limit}`
  );
  return list.map((dto) => toThreadSummary(dto, dto.project_id ?? 0));
}

/** 更多工作区：未绑定的 legacy 会话（次级入口；仅显式绑定迁移）。 */
export async function fetchUnboundLegacyThreads(): Promise<CodingThreadSummary[]> {
  const list = await codingFetchJson<Session[]>("/sessions");
  return list
    .filter((dto) => (dto.kind ?? "legacy") !== "coding" && dto.project_id == null)
    .map((dto) => toThreadSummary(dto, 0));
}
