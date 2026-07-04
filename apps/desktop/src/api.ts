import { invoke, isTauri } from "@tauri-apps/api/core";
import type { ChatEvent, DocumentItem, Message, Session } from "./types";

let API_BASE: string | null = null;

/**
 * 获取后端 API base：
 * - Tauri 打包模式：用 Rust sidecar 协商的端口（get_api_port 命令）。
 * - 开发模式 / 浏览器：回退到 http://127.0.0.1:8000（手动启动的后端）。
 * 结果缓存，后续调用直接返回。
 */
export async function ensureApiBase(): Promise<string> {
  if (API_BASE) return API_BASE;
  if (isTauri()) {
    try {
      const port = await invoke<number | null>("get_api_port");
      if (port) {
        API_BASE = `http://127.0.0.1:${port}`;
        return API_BASE;
      }
    } catch {
      // 命令失败，回退默认端口
    }
  }
  API_BASE = "http://127.0.0.1:8000";
  return API_BASE;
}

/** 直接指定后端端口（start_sidecar 返回端口后用，绕过缓存）。 */
export function setApiBase(port: number): void {
  API_BASE = `http://127.0.0.1:${port}`;
}

/** 回退到默认手动后端 127.0.0.1:8000（dev 模式）。 */
export function setApiBaseDefault(): void {
  API_BASE = "http://127.0.0.1:8000";
}

/** 清除缓存的 base，下次 ensureApiBase 重新解析。 */
export function resetApiBase(): void {
  API_BASE = null;
}

export async function getHealth(): Promise<Record<string, unknown>> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/health`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function listSessions(): Promise<Session[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/sessions`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createSession(): Promise<Session> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/sessions`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getMessages(sessionId: number): Promise<Message[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/sessions/${sessionId}/messages`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 文档 / 知识库 ----
export async function listDocuments(): Promise<DocumentItem[]> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/documents`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function importDocument(file: File): Promise<DocumentItem> {
  const base = await ensureApiBase();
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${base}/documents/import`, { method: "POST", body: fd });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function deleteDocument(id: number): Promise<void> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/documents/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
}

export async function retryDocument(id: number): Promise<DocumentItem> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/documents/${id}/retry`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 设置 ----
export interface AppSettings {
  llm_model: string;
  embed_model: string;
  llm_temperature: number;
  llm_context_length: number;
  kb_enabled_by_default: boolean;
  openai_api_key: string;
  openai_base_url: string;
  claude_api_key: string;
}

export async function getSettings(): Promise<AppSettings> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/settings`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function updateSettings(
  data: Partial<AppSettings>
): Promise<AppSettings> {
  const base = await ensureApiBase();
  const r = await fetch(`${base}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

/**
 * SSE 流式对话。fetch + ReadableStream 解析。返回 AbortController 用于停止生成。
 */
export function streamChat(
  sessionId: number,
  message: string,
  knowledgeBase: boolean,
  onEvent: (e: ChatEvent) => void,
  onError: (err: string) => void,
  onClose?: () => void
): AbortController {
  const controller = new AbortController();

  ensureApiBase()
    .then((base) =>
      fetch(`${base}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message,
          knowledge_base: knowledgeBase,
        }),
        signal: controller.signal,
      }).then(async (resp) => {
        if (!resp.ok || !resp.body) {
          onError(`HTTP ${resp.status}`);
          return;
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buffer.indexOf("\n\n")) >= 0) {
            const raw = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            const line = raw.split("\n").find((l) => l.startsWith("data:"));
            if (!line) continue;
            try {
              onEvent(JSON.parse(line.slice(5).trim()));
            } catch {
              // 忽略解析失败的事件
            }
          }
        }
        onClose?.();
      })
    )
    .catch((e) => {
      if (e?.name === "AbortError") {
        onClose?.();
      } else {
        onError(String(e));
      }
    });

  return controller;
}

// ============ 引导 / 配置 / sidecar / 更新（第五阶段） ============
// 这些命令只在 Tauri 打包/桌面环境可用；浏览器开发模式 invoke 会抛错，调用方需 try/catch。

/** 连接配置（对应 Rust ConfigData，字段与 .env 的 PA_ 项对齐）。 */
export interface ConfigData {
  db_host: string;
  db_port: number;
  db_user: string;
  db_password: string;
  db_name: string;
  ollama_base_url: string;
  llm_model: string;
  embed_model: string;
}

export interface DepResult {
  mysql_reachable: boolean;
  ollama_reachable: boolean;
}

export interface ConnResult {
  mysql_ok: boolean;
  mysql_error: string | null;
  ollama_ok: boolean;
  ollama_error: string | null;
  ollama_models: string[];
  llm_model_available: boolean;
  embed_model_available: boolean;
}

export interface SidecarStartResult {
  ok: boolean;
  dev_mode: boolean;
  port: number | null;
  error: string | null;
}

export interface UpdateInfo {
  version: string;
  date: string | null;
  body: string | null;
}

/** 是否已存在连接配置（%APPDATA%/personal-assistant/.env）。 */
export async function cmdConfigExists(): Promise<boolean> {
  return invoke<boolean>("config_exists");
}

/** 读取配置；不存在时返回默认值。 */
export async function cmdReadConfig(): Promise<ConfigData> {
  return invoke<ConfigData>("read_config");
}

/** 写入配置（生成 .env）。 */
export async function cmdWriteConfig(cfg: ConfigData): Promise<void> {
  return invoke<void>("write_config", { cfg });
}

/** 默认端口探测 MySQL/Ollama 是否在跑（向导首屏环境提示）。 */
export async function cmdCheckDependencies(): Promise<DepResult> {
  return invoke<DepResult>("check_dependencies");
}

/** 按配置测试 MySQL + Ollama 连接，并校验模型是否已拉取。 */
export async function cmdTestConnections(cfg: ConfigData): Promise<ConnResult> {
  return invoke<ConnResult>("test_connections", { cfg });
}

/** 启动 sidecar；dev 模式返回 dev_mode=true。 */
export async function cmdStartSidecar(): Promise<SidecarStartResult> {
  return invoke<SidecarStartResult>("start_sidecar");
}

/** 检查更新；无更新返回 null。 */
export async function cmdCheckForUpdates(): Promise<UpdateInfo | null> {
  return invoke<UpdateInfo | null>("check_for_updates");
}

/** 下载并安装更新（安装后需 relaunch）。 */
export async function cmdDownloadAndInstallUpdate(): Promise<void> {
  return invoke<void>("download_and_install_update");
}

/** 重启应用以应用更新。 */
export async function cmdRelaunchApp(): Promise<void> {
  return invoke<void>("relaunch_app");
}
