import { invoke, isTauri } from "@tauri-apps/api/core";
import { getConnectionProfile } from "./connectionProfile";
import { getWorkspaceAccessToken } from "../auth/session";
import { requestPrivateRuntime } from "./privateTransport";

type LocalConnection = { port: number; token: string } | { transport: "stdio"; protocol: 2 };
let connection: LocalConnection | null = null;
let starting: Promise<void> | null = null;
let identityQueue: Promise<void> = Promise.resolve();
let projectContextQueue: Promise<void> = Promise.resolve();

export function usesLocalExecutor(): boolean {
  return isTauri() || import.meta.env.VITE_LOCAL_EXECUTOR === "true";
}

/** 项目执行与所有模型接口均由本机处理，失败时不回退服务器。 */
export function isLocalProjectPath(path: string): boolean {
  return /^\/(projects|sessions|agent-runs|full-access-grants|local-history|local-models|local-memories|capabilities|workspace-search|chat)(\/|$)/.test(path) || isLocalModelPath(path);
}

export function isLocalModelPath(path: string): boolean {
  return /^\/(model-providers|agent-model-profiles|model-settings|model-evaluation|providers|desktop\/model)(\/|$)/.test(path);
}

export async function startLocalExecutor(): Promise<void> {
  if (!usesLocalExecutor()) return;
  if (starting) return starting;
  starting = (async () => {
    if (!isTauri()) throw new Error("本机文件执行需要安装桌面客户端，不能在浏览器中运行");
    // 迁移旧模型参数，推理路由只由所选模型配置决定。
    getConnectionProfile();
    const result = await invoke<LocalConnection>("start_local_executor", { modelConfig: { inference_mode: "auto" } });
    if ("transport" in result ? result.transport !== "stdio" || result.protocol !== 2
      : !Number.isInteger(result.port) || result.port < 1 || result.port > 65535 || result.token.length < 32) {
      throw new Error("本机执行器连接信息无效");
    }
    connection = result;
    for (let attempt = 0; attempt < 150; attempt += 1) {
      try {
        if (await checkLocalExecutorHealth(AbortSignal.timeout(1000))) return;
      } catch { /* 捆绑进程可能仍在解包或启动，按有界次数重试。 */ }
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

/** 工作区就绪只检查本机运行时，避免受平台登录状态或服务器故障影响。 */
export async function checkLocalExecutorHealth(signal = AbortSignal.timeout(5000)): Promise<boolean> {
  const response = await localRequest("/health", { signal });
  if (!response.ok) return false;
  const health = await response.json();
  return health?.mode === "desktop-local" && health.protocol === 1;
}

export async function fetchLocalProject(path: string, init: RequestInit): Promise<Response> {
  if (!isLocalProjectPath(new URL(path, "http://localhost").pathname)) throw new Error("无效的本机项目接口");
  // 切换项目的撤权必须先于后续创建任务、授权与工具审批请求完成。
  if (init.method && !["GET", "HEAD"].includes(init.method.toUpperCase())) await projectContextQueue;
  return localRequest(path, init);
}

export function setLocalProjectContext(projectId: number | null): Promise<void> {
  if (!usesLocalExecutor() || !connection) return Promise.resolve();
  const token = getWorkspaceAccessToken();
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

function queueIdentity<T>(operation: () => Promise<T>): Promise<T> {
  const current = identityQueue.then(operation, operation);
  identityQueue = current.then(() => undefined, () => undefined);
  return current;
}

export function bindLocalAccess(): Promise<string> {
  if (!usesLocalExecutor()) return Promise.reject(new Error("使用 API Key 需要桌面客户端"));
  return queueIdentity(async () => {
    // 等待旧项目撤权结束后恢复身份；旧会话失败不应永久阻断新会话。
    await projectContextQueue.catch(() => undefined);
    const response = await localRequest("/identity/local", {
      method: "POST", signal: AbortSignal.timeout(20000),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "无法打开本机工作区，请重试");
    if (data?.ready !== true || typeof data.access_token !== "string"
        || !/^local-session:[A-Za-z0-9_-]{43}$/.test(data.access_token)) {
      throw new Error("本机使用凭证无效，请升级客户端后重试");
    }
    projectContextQueue = Promise.resolve();
    return data.access_token;
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
