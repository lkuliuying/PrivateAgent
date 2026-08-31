import { isTauri } from "@tauri-apps/api/core";
import { clearAccessToken } from "../auth/session";

export interface ConnectionProfile {
  inference_mode: "service" | "local";
  model_protocol: "ollama" | "openai";
  model_endpoint: string;
  model_name: string;
  context_tokens: number | null;
}

const KEY = "privateagent.local-model.v1";
const LEGACY_KEYS = ["privateagent.connection.v1", "privateagent.server.v2"];

export function validateConnectionProfile(profile: ConnectionProfile): ConnectionProfile {
  if (!["service", "local"].includes(profile.inference_mode)) throw new Error("模型执行位置无效");
  if (!["ollama", "openai"].includes(profile.model_protocol)) throw new Error("模型协议无效");
  let url: URL;
  try { url = new URL(profile.model_endpoint.trim()); } catch { throw new Error("请输入完整的本机模型地址"); }
  const loopback = ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
  if (!loopback || url.port === "0" || !["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error("本机模型仅允许回环地址，不能包含凭据、查询参数或片段");
  }
  if (profile.model_protocol === "ollama" && url.pathname !== "/") throw new Error("Ollama 地址不包含 /api 路径");
  if (profile.context_tokens !== null && (!Number.isInteger(profile.context_tokens) || profile.context_tokens < 1 || profile.context_tokens > 1_000_000_000)) {
    throw new Error("上下文容量必须为正整数；未知时留空");
  }
  if (typeof profile.model_name !== "string" || profile.model_name.trim().length > 200) throw new Error("模型名称无效");
  return {
    inference_mode: profile.inference_mode, model_protocol: profile.model_protocol,
    model_endpoint: url.href.replace(/\/$/, ""), model_name: profile.model_name.trim(), context_tokens: profile.context_tokens,
  };
}

export function defaultConnectionProfile(): ConnectionProfile {
  return { inference_mode: "service", model_protocol: "ollama", model_endpoint: "http://127.0.0.1:11434", model_name: "", context_tokens: 8192 };
}

/** 升级只保留模型参数，旧账号模式及可编辑服务器源站不再生效。 */
export function getConnectionProfile(): ConnectionProfile {
  const saved = window.localStorage.getItem(KEY);
  let profile = defaultConnectionProfile();
  const legacy = window.localStorage.getItem(LEGACY_KEYS[0]);
  if (legacy !== null) {
    try {
      const old = JSON.parse(legacy);
      profile = validateConnectionProfile({ ...profile, ...old, inference_mode: old.mode === "local" ? "local" : old.inference_mode ?? "service" });
    } catch {
      // 模型配置损坏时暂停推理；不影响服务器登录，也不转发内容到另一服务。
      profile = { ...defaultConnectionProfile(), inference_mode: "local" };
    }
  }
  if (LEGACY_KEYS.some((key) => window.localStorage.getItem(key) !== null)) {
    clearAccessToken();
    LEGACY_KEYS.forEach((key) => window.localStorage.removeItem(key));
    if (!saved) saveConnectionProfile(profile);
  }
  if (saved) {
    try { return validateConnectionProfile(JSON.parse(saved)); }
    catch { return { ...defaultConnectionProfile(), inference_mode: "local" }; }
  }
  return profile;
}

/** 只保存模型参数，不允许混入服务器地址、账号模式或凭据。 */
export function saveConnectionProfile(profile: ConnectionProfile): void {
  window.localStorage.setItem(KEY, JSON.stringify(validateConnectionProfile(profile)));
}

export function usesLocalInference(): boolean {
  return (isTauri() || import.meta.env.VITE_LOCAL_EXECUTOR === "true") && getConnectionProfile().inference_mode === "local";
}

/** 无效模型参数不能阻断服务器登录，设置页仍明确提示修复。 */
export function modelConfigurationError(): string {
  const saved = window.localStorage.getItem(KEY);
  if (!saved) return "";
  try { validateConnectionProfile(JSON.parse(saved)); return ""; }
  catch { return "保存的本机模型配置无效，已暂停模型执行；请修正后重新保存"; }
}
