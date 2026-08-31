import { apiFetch, ensureApiBase } from '../api/http';

export interface ServiceLogSource {
  id: string;
  label: string;
  available: boolean;
  message: string;
}

export interface ServiceLogTail {
  source: string;
  label: string;
  lines: string[];
  truncated: boolean;
  scanned_bytes: number;
  generated_at: string;
}

async function responseJson<T>(response: Response): Promise<T> {
  if (response.ok) return response.json() as Promise<T>;
  const body = await response.json().catch(() => null);
  const message = response.status === 404
    ? '日志接口尚未上线或日志类型不存在，请确认服务器版本'
    : typeof body?.detail === 'string' ? body.detail : `日志请求失败（HTTP ${response.status}）`;
  throw new Error(message);
}

/** 只返回已配置的固定日志类型，不向客户端暴露服务器文件路径。 */
export async function getServiceLogSources(signal?: AbortSignal): Promise<ServiceLogSource[]> {
  const base = await ensureApiBase();
  const data = await responseJson<{ sources: ServiceLogSource[] }>(
    await apiFetch(`${base}/admin/logs`, { signal, cache: 'no-store' })
  );
  return Array.isArray(data.sources) ? data.sources : [];
}

/** 查询最近的有界、已脱敏日志；取消请求不会继续更新页面。 */
export async function getServiceLogTail(
  source: string,
  lines: number,
  search: string,
  signal?: AbortSignal,
): Promise<ServiceLogTail> {
  const base = await ensureApiBase();
  const query = new URLSearchParams({ lines: String(lines), search });
  return responseJson<ServiceLogTail>(await apiFetch(
    `${base}/admin/logs/${encodeURIComponent(source)}?${query}`,
    { signal, cache: 'no-store' },
  ));
}
