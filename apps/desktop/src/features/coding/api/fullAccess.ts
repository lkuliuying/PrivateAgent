/**
 * v0.9.0 H1-A · full_access 独立 capability 授予 API（H0 §6.3）
 *
 * - 授予必须来自用户显式二次确认（调用方把关）；
 * - 到期/撤销/应用退出自动失效（后端语义），前端每次执行前重新查询；
 * - 与「替我批准」（workspace）互相独立，不是别名。
 */
import { codingFetchJson, codingJsonInit } from "./codingHttp";

export interface FullAccessGrantState {
  active: boolean;
  grantId: string | null;
  sessionId: number | null;
  projectId: number | null;
  grantedAt: string | null;
  expiresAt: string | null;
}

interface FullAccessGrantDto {
  active: boolean;
  grant_id: string | null;
  session_id: number | null;
  project_id: number | null;
  granted_at: string | null;
  expires_at: string | null;
}

function toGrantState(dto: FullAccessGrantDto): FullAccessGrantState {
  return {
    active: dto.active,
    grantId: dto.grant_id,
    sessionId: dto.session_id,
    projectId: dto.project_id,
    grantedAt: dto.granted_at,
    expiresAt: dto.expires_at,
  };
}

/** 查询会话当前有效授予（无/能力位关闭 → active=false）。 */
export async function fetchFullAccessGrant(
  sessionId: number
): Promise<FullAccessGrantState> {
  const dto = await codingFetchJson<FullAccessGrantDto>(
    `/sessions/${sessionId}/full-access-grant`
  );
  return toGrantState(dto);
}

/** 显式创建授予（调用方必须已完成用户二次确认）。 */
export async function createFullAccessGrant(
  sessionId: number
): Promise<FullAccessGrantState> {
  const dto = await codingFetchJson<FullAccessGrantDto>(
    `/sessions/${sessionId}/full-access-grant`,
    codingJsonInit("POST", {})
  );
  return toGrantState(dto);
}

/** 即时撤销（幂等）。 */
export async function revokeFullAccessGrant(grantId: string): Promise<boolean> {
  const body = await codingFetchJson<{ revoked?: boolean }>(
    `/full-access-grants/${grantId}`,
    { method: "DELETE" }
  );
  // 已经撤销也视为幂等成功；网络和接口失败必须保留授权状态并向用户报告。
  return body.revoked === true || body.revoked === false;
}
