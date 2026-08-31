import { isTauri } from "@tauri-apps/api/core";

export interface ConnectionProfile {
  mode: "local" | "cloud" | "self_hosted";
  server_origin: string;
  inference_mode?: "service" | "local";
  model_protocol: "ollama" | "openai";
  model_endpoint: string;
  model_name: string;
  context_tokens: number | null;
}

const KEY = "privateagent.connection.v1";

export function validateConnectionProfile(profile: ConnectionProfile): ConnectionProfile {
  if (!["local", "cloud", "self_hosted"].includes(profile.mode)) throw new Error("连接模式无效");
  if (!["ollama", "openai"].includes(profile.model_protocol)) throw new Error("模型协议无效");
  if (profile.inference_mode && !["service", "local"].includes(profile.inference_mode)) throw new Error("推理位置无效");
  const validateUrl = (value: string, localOnly: boolean): URL => {
    let url: URL;
    try { url = new URL(value.trim()); } catch { throw new Error("请输入完整的服务地址"); }
    const local = ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
      throw new Error("地址不能包含凭据、查询参数或片段");
    }
    if ((localOnly && !local) || (url.protocol === "http:" && !local)) throw new Error("本地模型限回环地址；远程服务必须使用 HTTPS");
    return url;
  };
  const model = validateUrl(profile.model_endpoint, true);
  if (profile.model_protocol === "ollama" && model.pathname !== "/") throw new Error("Ollama 地址不包含 /api 路径");
  const server = profile.mode === "local" ? null : validateUrl(profile.server_origin, false);
  if (server && server.pathname !== "/") throw new Error("账号服务地址必须为源站");
  if (profile.context_tokens !== null && (!Number.isInteger(profile.context_tokens) || profile.context_tokens < 1 || profile.context_tokens > 1_000_000_000)) {
    throw new Error("上下文容量必须为正整数；未知时留空");
  }
  if (profile.model_name.trim().length > 200) throw new Error("模型名称过长");
  return {
    mode: profile.mode, server_origin: server?.origin ?? "",
    inference_mode: profile.inference_mode ?? "service",
    model_protocol: profile.model_protocol, model_endpoint: model.href.replace(/\/$/, ""),
    model_name: profile.model_name.trim(), context_tokens: profile.context_tokens,
  };
}

export function defaultConnectionProfile(): ConnectionProfile {
  const server = String(import.meta.env.VITE_API_BASE_URL || "").trim();
  return { mode: server ? "cloud" : "local", server_origin: server, inference_mode: "service", model_protocol: "ollama",
    model_endpoint: "http://127.0.0.1:11434", model_name: "", context_tokens: 8192 };
}

export function getConnectionProfile(): ConnectionProfile | null {
  if (!isTauri() || import.meta.env.VITE_LOCAL_EXECUTOR === "false") return null;
  const saved = window.localStorage.getItem(KEY);
  if (saved) {
    try { return validateConnectionProfile(JSON.parse(saved) as ConnectionProfile); }
    catch { throw new Error("保存的连接配置无效，请在连接设置中修正"); }
  }
  // 统一客户端默认使用轻量运行时；旧完整后端仅由显式兼容构建保留。
  return validateConnectionProfile(defaultConnectionProfile());
}

/** 仅保存白名单内的非敏感配置；不持久化访问令牌或模型密钥。 */
export function saveConnectionProfile(profile: ConnectionProfile): void {
  window.localStorage.setItem(KEY, JSON.stringify(validateConnectionProfile(profile)));
}

export function isLocalConnection(): boolean {
  return getConnectionProfile()?.mode === "local";
}

export function usesLocalInference(): boolean {
  const profile = getConnectionProfile();
  return profile?.mode === "local" || profile?.inference_mode === "local";
}
