/**
 * v0.8.0 W1 · Coding 领域 HTTP 基座
 *
 * 统一走 api/http.ts 的 apiFetch（Bearer token + sidecar 端口协商），
 * 组件不得拼 URL 或直接 fetch（计划 §5.4）；错误统一解析为
 * {error_code, detail} 契约（core/coding_errors.py）。
 */
import { apiFetch, ensureApiBase } from "../../../api/http";
import type { CodingApiError } from "../model/contracts";

/** 将非 2xx 响应解析为 CodingApiError；非 JSON 错误体按 unknown 处理。 */
export async function toCodingApiError(response: Response): Promise<CodingApiError> {
  let code = "unknown";
  let message = `请求失败（HTTP ${response.status}）`;
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "error_code" in body) {
      const parsed = body as { error_code?: unknown; detail?: unknown };
      if (typeof parsed.error_code === "string") code = parsed.error_code;
      if (typeof parsed.detail === "string" && parsed.detail) message = parsed.detail;
    }
  } catch {
    // 网络中断/HTML 错误页等：保留 HTTP 概括信息，不猜测具体原因
  }
  return { status: response.status, code, message };
}

/** apiFetch 不自动拼 base：领域层统一经此拼装（与 api.ts 惯例一致） */
export async function codingFetch(path: string, init?: RequestInit): Promise<Response> {
  const base = await ensureApiBase();
  return apiFetch(`${base}${path}`, init);
}

export async function codingFetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await codingFetch(path, init);
  if (!response.ok) {
    throw await toCodingApiError(response);
  }
  return (await response.json()) as T;
}

export function codingJsonInit(
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  body: unknown
): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}
