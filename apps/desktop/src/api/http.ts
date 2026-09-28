import { clearLocalSession, getWorkspaceAccessToken } from "../auth/session";
import { fetchLocalProject, isLocalProjectPath, usesLocalExecutor } from "../services/localExecutor";

// 只用于标识内部请求，不解析 DNS，也不作为网络请求目标。
const API_BASE = "http://privateagent.localhost";

export async function ensureApiBase(): Promise<string> {
  return API_BASE;
}

export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(input instanceof Request ? input.headers : undefined);
  new Headers(init.headers).forEach((value, key) => headers.set(key, value));
  const url = new URL(input instanceof Request ? input.url : input.toString(), `${API_BASE}/`);
  if (url.origin !== API_BASE) {
    if (headers.get("Authorization")?.startsWith("Bearer local-session:")) {
      throw new Error("本机使用凭证不能发送到外部服务");
    }
    return fetch(input, { ...init, headers, redirect: "error" });
  }
  if (!isLocalProjectPath(url.pathname)) {
    return new Response(JSON.stringify({ error_code: "feature_removed", detail: "此功能已移除，请更新客户端" }), {
      status: 410, headers: { "Content-Type": "application/json" },
    });
  }
  if (!usesLocalExecutor()) throw new Error("请使用桌面客户端打开本机工作区");
  const token = getWorkspaceAccessToken();
  if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
  const requestInit = input instanceof Request
    ? { method: input.method, body: input.body && init.body === undefined ? await input.clone().arrayBuffer() : undefined, signal: input.signal, ...init, headers }
    : { ...init, headers };
  const response = await fetchLocalProject(url.pathname + url.search, requestInit);
  // 供应商的 401 属于模型配置错误，只有执行器明确失效的会话才需要重新绑定。
  if (response.status === 401 && response.headers.get("X-PrivateAgent-Session") === "expired"
      && token && token === getWorkspaceAccessToken() && headers.get("Authorization") === `Bearer ${token}`) {
    clearLocalSession();
    window.dispatchEvent(new CustomEvent("pa:session-expired"));
  }
  return response;
}
