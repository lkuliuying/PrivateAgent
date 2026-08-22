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
