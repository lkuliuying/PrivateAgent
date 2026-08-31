import { afterEach, describe, expect, it, vi } from "vitest";
import { getConnectionProfile, isLocalConnection, saveConnectionProfile, validateConnectionProfile, type ConnectionProfile } from "./connectionProfile";

vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => true }));
const local: ConnectionProfile = { mode: "local", server_origin: "", model_protocol: "ollama", model_endpoint: "http://127.0.0.1:11434", model_name: "fixture", context_tokens: 8192 };

describe("运行时连接配置", () => {
  afterEach(() => { window.localStorage.clear(); vi.unstubAllEnvs(); });
  it("切换模型只保存连接字段，不保存账号或令牌", () => {
    saveConnectionProfile({ ...local, token: "must-not-persist" } as ConnectionProfile);
    expect(isLocalConnection()).toBe(true);
    const saved = JSON.parse(window.localStorage.getItem("privateagent.connection.v1")!);
    expect(saved).not.toHaveProperty("token");
    expect(JSON.stringify(saved)).not.toContain("must-not-persist");
    saveConnectionProfile({ ...local, model_name: "other" });
    expect(getConnectionProfile()?.model_name).toBe("other");
  });
  it("已保存配置优先于旧版本的构建地址", () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://old.example.test");
    saveConnectionProfile(local);
    expect(getConnectionProfile()?.mode).toBe("local");
  });
  it("显式完整后端兼容构建不加载统一客户端配置", () => {
    saveConnectionProfile(local);
    vi.stubEnv("VITE_LOCAL_EXECUTOR", "false");
    expect(getConnectionProfile()).toBeNull();
  });
  it("拒绝远程明文、嵌入凭据及本地模式外发", () => {
    expect(() => validateConnectionProfile({ ...local, mode: "cloud", server_origin: "http://remote.test" })).toThrow();
    expect(() => validateConnectionProfile({ ...local, model_endpoint: "https://remote.test/v1" })).toThrow();
    expect(() => validateConnectionProfile({ ...local, model_endpoint: "http://user:pass@127.0.0.1" })).toThrow();
    expect(() => validateConnectionProfile({ ...local, context_tokens: 0 })).toThrow();
  });
});
