import { apiFetch, ensureApiBase } from "../api/http";
import type {
  AdminOverview,
  AdminUserRow,
  AuditLogRow,
  PagedResult,
} from "../types/auth";

async function responseJson<T>(response: Response): Promise<T> {
  if (response.ok) return response.json() as Promise<T>;
  const body = await response.json().catch(() => null);
  throw new Error(
    typeof body?.detail === "string" ? body.detail : `请求失败（${response.status}）`
  );
}

export async function getAdminOverview(): Promise<AdminOverview> {
  const base = await ensureApiBase();
  return responseJson<AdminOverview>(await apiFetch(`${base}/admin/overview`));
}

export async function getAdminUsers(params: {
  page: number;
  size: number;
  search?: string;
}): Promise<PagedResult<AdminUserRow>> {
  const base = await ensureApiBase();
  const query = new URLSearchParams({
    page: String(params.page),
    size: String(params.size),
  });
  if (params.search) query.set("search", params.search);
  return responseJson<PagedResult<AdminUserRow>>(
    await apiFetch(`${base}/admin/users?${query}`)
  );
}

export async function getAuditLogs(params: {
  page: number;
  size: number;
  actorUserId?: number;
  statusCode?: number;
}): Promise<PagedResult<AuditLogRow>> {
  const base = await ensureApiBase();
  const query = new URLSearchParams({
    page: String(params.page),
    size: String(params.size),
  });
  if (params.actorUserId) query.set("actor_user_id", String(params.actorUserId));
  if (params.statusCode) query.set("status_code", String(params.statusCode));
  return responseJson<PagedResult<AuditLogRow>>(
    await apiFetch(`${base}/admin/audit-logs?${query}`)
  );
}
