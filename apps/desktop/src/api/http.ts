import { clearAccessToken, getAccessToken } from "../auth/session";
import { fetchLocalProject, isLocalProjectPath, usesLocalExecutor } from "../services/localExecutor";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { getConnectionProfile } from "../services/connectionProfile";

let API_BASE: string | null = null;
/** 保留既有查询接口；当前客户端的业务账号始终由服务器提供。 */
export function hasConfiguredRemoteApi(): boolean { return true; }

/** 地址缺失时明确失败，禁止登录请求回退到本机执行器或默认端口。 */
export async function ensureApiBase(): Promise<string> {
  if (API_BASE) return API_BASE;
  getConnectionProfile();
  const origin = isTauri()
    ? await invoke<string>("account_server_origin")
    : import.meta.env.DEV ? String(import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000") : "";
  let url: URL;
  try { url = new URL(origin); } catch { throw new Error("无法读取内置账号服务，请重新安装客户端或联系管理员"); }
  const loopback = ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
  if ((url.protocol !== "https:" && !(import.meta.env.DEV && !isTauri() && loopback && url.protocol === "http:"))
      || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("内置账号服务地址无效，请联系管理员");
  }
  API_BASE = url.origin;
  return API_BASE;
}

function targetsConfiguredApi(input: RequestInfo | URL): boolean {
  if (!API_BASE) return false;
  try {
    const base = new URL(`${API_BASE}/`);
    const raw = input instanceof Request ? input.url : input.toString();
    const target = new URL(raw, base);
    const basePath = base.pathname.endsWith("/") ? base.pathname : `${base.pathname}/`;
    return (
      target.origin === base.origin &&
      (target.pathname === base.pathname.replace(/\/$/, "") ||
        target.pathname.startsWith(basePath))
    );
  } catch {
    return false;
  }
}

/** 仅项目执行接口进入本机管道，账号和管理接口始终请求服务器，本机模型仅接管模型清单。 */
export async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {}
): Promise<Response> {
  if (!API_BASE) await ensureApiBase();
  const headers = new Headers(input instanceof Request ? input.headers : undefined);
  new Headers(init.headers).forEach((value, key) => headers.set(key, value));
  const accessToken = getAccessToken();
  const isApiRequest = targetsConfiguredApi(input);
  if (accessToken && isApiRequest && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  const url = new URL(input instanceof Request ? input.url : input.toString(), `${API_BASE}/`);
  let response: Response;
  if (usesLocalExecutor() && isApiRequest && isLocalProjectPath(url.pathname)) {
    const requestInit = input instanceof Request
      ? { method: input.method, body: input.body && init.body === undefined ? await input.clone().arrayBuffer() : undefined, signal: input.signal, ...init, headers }
      : { ...init, headers };
    response = await fetchLocalProject(url.pathname + url.search, requestInit);
  } else {
    response = await fetch(input, { ...init, headers, redirect: "error" });
  }
  if (response.status === 401 && accessToken && accessToken === getAccessToken() && isApiRequest) {
    clearAccessToken();
    window.dispatchEvent(new CustomEvent("pa:session-expired"));
  }
  return response;
}

/** 清除源站缓存，由下一次请求重新读取内置服务器。 */
export function resetApiBase(): void {
  API_BASE = null;
}
