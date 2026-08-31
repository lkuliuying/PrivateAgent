import { invoke, isTauri } from "@tauri-apps/api/core";
import type { ApiConnection } from "../api/tauri";
import { getConnectionProfile, isLocalConnection, usesLocalInference } from "./connectionProfile";
import { getAccessToken } from "../auth/session";
import { requestPrivateRuntime } from "./privateTransport";

type LocalConnection = ApiConnection | { transport: "stdio"; protocol: 2 };
let connection: LocalConnection | null = null;
let starting: Promise<void> | null = null;
let identityQueue: Promise<void> = Promise.resolve();
let projectContextQueue: Promise<void> = Promise.resolve();

export function usesLocalExecutor(): boolean {
  return getConnectionProfile() !== null || import.meta.env.VITE_LOCAL_EXECUTOR === "true";
}

/** 本机项目、运行及授权接口不得回退到服务器文件系统。 */
export function isLocalProjectPath(path: string): boolean {
  return isLocalConnection() || (usesLocalInference() && /^\/agent-model-profiles(\/|$)/.test(path))
    || /^\/(projects|sessions|agent-runs|full-access-grants|local-history|capabilities|chat)(\/|$)/.test(path);
}

export async function startLocalExecutor(serverOrigin: string): Promise<void> {
  if (!usesLocalExecutor()) return;
  if (starting) return starting;
  starting = (async () => {
    if (!isTauri()) throw new Error("本机文件执行需要安装桌面客户端，不能在浏览器中运行");
    const profile = getConnectionProfile();
    const result = await invoke<LocalConnection>("start_local_executor", { serverOrigin, connectionProfile: profile });
    if ("transport" in result ? result.transport !== "stdio" || result.protocol !== 2
      : !Number.isInteger(result.port) || result.port < 1 || result.port > 65535 || result.token.length < 32) {
      throw new Error("本机执行器连接信息无效");
    }
    connection = result;
    for (let attempt = 0; attempt < 150; attempt += 1) {
      try {
        const response = await localRequest("/health", { signal: AbortSignal.timeout(1000) });
        const health = await response.json();
        if (response.ok && health.mode === "desktop-local" && health.protocol === 1) return;
      } catch { /* The bundled process may still be extracting/starting. */ }
      await new Promise((resolve) => window.setTimeout(resolve, 200));
    }
    throw new Error("本机执行器启动超时，请重试；项目请求不会发送到服务器");
  })();
  try {
    await starting;
  } catch (error) {
    connection = null;
    starting = null;
    throw error;
  }
}

export async function stopLocalExecutor(): Promise<void> {
  if (connection) await clearLocalIdentity();
  if (isTauri()) await invoke("stop_local_executor");
  connection = null;
  starting = null;
}

function localRequest(path: string, init: RequestInit): Promise<Response> {
  if (!connection) throw new Error("本机执行器未就绪，请重新启动客户端");
  if ("transport" in connection) return requestPrivateRuntime(path, init);
  const headers = new Headers(init.headers);
  headers.set("X-PrivateAgent-Local", connection.token);
  return fetch(`http://127.0.0.1:${connection.port}${path}`, { ...init, headers, redirect: "error", cache: "no-store" });
}

export async function fetchLocalProject(path: string, init: RequestInit): Promise<Response> {
  if (!isLocalProjectPath(new URL(path, "http://localhost").pathname)) throw new Error("无效的本机项目接口");
  // 切换项目的撤权必须先于后续创建任务、授权与工具审批请求完成。
  if (init.method && !["GET", "HEAD"].includes(init.method.toUpperCase())) await projectContextQueue;
  return localRequest(path, init);
}

export function setLocalProjectContext(projectId: number | null): Promise<void> {
  if (!usesLocalExecutor() || !connection) return Promise.resolve();
  const token = getAccessToken();
  if (!token) return Promise.resolve();
  const operation = async () => {
    const result = await localRequest("/projects/context", { method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ project_id: projectId }), signal: AbortSignal.timeout(15000) });
    if (!result.ok) throw new Error("项目切换撤权失败，请重试或退出客户端；新操作已阻止");
  };
  projectContextQueue = projectContextQueue.then(operation, operation);
  return projectContextQueue;
}

function queueIdentity(operation: () => Promise<void>): Promise<void> {
  const current = identityQueue.then(operation, operation);
  identityQueue = current.catch(() => undefined);
  return current;
}

export function bindLocalIdentity(token: string): Promise<void> {
  if (!usesLocalExecutor()) return Promise.resolve();
  return queueIdentity(async () => {
    const response = await localRequest("/identity", {
      method: "POST", headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      throw new Error(typeof data?.detail === "string" ? data.detail : "无法绑定本机账号，请重试");
    }
  });
}

export function clearLocalIdentity(): Promise<void> {
  if (!connection) return Promise.resolve();
  return queueIdentity(async () => {
    const response = await localRequest("/identity/clear", { method: "POST", signal: AbortSignal.timeout(15000) });
    if (!response.ok) throw new Error("本机任务停止失败，请退出客户端");
    projectContextQueue = Promise.resolve();
  });
}
