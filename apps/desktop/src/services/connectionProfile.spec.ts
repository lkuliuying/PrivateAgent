import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defaultConnectionProfile, getConnectionProfile, modelConfigurationError, saveConnectionProfile, validateConnectionProfile, type ConnectionProfile } from "./connectionProfile";

vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => true }));

describe("模型参数与账号连接隔离", () => {
  beforeEach(() => { window.localStorage.clear(); window.sessionStorage.clear(); });
  afterEach(() => { window.localStorage.clear(); window.sessionStorage.clear(); vi.unstubAllEnvs(); });

  it("默认使用服务器模型，配置中没有服务器地址或账号模式", () => {
    expect(getConnectionProfile()).toEqual(defaultConnectionProfile());
    expect(getConnectionProfile()).not.toHaveProperty("server_origin");
    expect(getConnectionProfile()).not.toHaveProperty("mode");
  });
  it.each(["local", "cloud", "self_hosted"])("迁移旧 %s 模式时只保留本机模型参数，清除旧身份", (mode) => {
    window.localStorage.setItem("privateagent.connection.v1", JSON.stringify({
      mode, server_origin: "https://old.example.test", inference_mode: "local", model_protocol: "openai",
      model_endpoint: "http://127.0.0.1:9000/v1", model_name: "kept-model", context_tokens: 4096,
    }));
    window.localStorage.setItem("unrelated-record", "preserve");
    window.sessionStorage.setItem("pa_access_token", "obsolete-session");
    expect(getConnectionProfile()).toEqual({
      inference_mode: "local", model_protocol: "openai", model_endpoint: "http://127.0.0.1:9000/v1",
      model_name: "kept-model", context_tokens: 4096,
    });
    expect(window.sessionStorage.getItem("pa_access_token")).toBeNull();
    expect(window.localStorage.getItem("privateagent.connection.v1")).toBeNull();
    expect(window.localStorage.getItem("unrelated-record")).toBe("preserve");
    expect(window.localStorage.getItem("privateagent.local-model.v1")).not.toContain("server_origin");
  });
  it("丢弃旧的服务器地址覆盖，不删除任务记录", () => {
    window.localStorage.setItem("privateagent.server.v2", '{"server_origin":"https://other.example.test"}');
    window.sessionStorage.setItem("pa_access_token", "old-server-session");
    expect(getConnectionProfile()).toEqual(defaultConnectionProfile());
    expect(window.localStorage.getItem("privateagent.server.v2")).toBeNull();
    expect(window.sessionStorage.getItem("pa_access_token")).toBeNull();
  });
  it("模型保存不会改变当前账号，也不会保存地址覆盖或凭据", () => {
    window.sessionStorage.setItem("pa_access_token", "keep-session");
    saveConnectionProfile({ ...defaultConnectionProfile(), token: "must-not-persist", server_origin: "https://other.example.test", mode: "local" } as ConnectionProfile);
    expect(window.sessionStorage.getItem("pa_access_token")).toBe("keep-session");
    const saved = window.localStorage.getItem("privateagent.local-model.v1")!;
    expect(saved).not.toContain("must-not-persist");
    expect(saved).not.toContain("server_origin");
  });
  it("损坏的模型配置不阻断服务器登录，设置页明确提示修复", () => {
    window.localStorage.setItem("privateagent.local-model.v1", "{broken");
    expect(getConnectionProfile()).toEqual({ ...defaultConnectionProfile(), inference_mode: "local" });
    expect(modelConfigurationError()).toContain("已暂停模型执行");
  });
  it.each(["http://remote.test", "https://remote.test/v1", "http://user:secret@127.0.0.1", "http://127.0.0.1?token=secret", "http://127.0.0.1/#secret", "http://127.0.0.1:0"])("拒绝非本机或包含敏感参数的模型地址", (model_endpoint) => {
    expect(() => validateConnectionProfile({ ...defaultConnectionProfile(), model_endpoint })).toThrow();
  });
  it("接受本机 OpenAI 兼容地址及未知上下文容量", () => {
    expect(validateConnectionProfile({ ...defaultConnectionProfile(), model_protocol: "openai", model_endpoint: "http://localhost:9000/v1/", context_tokens: null }).model_endpoint).toBe("http://localhost:9000/v1");
  });
});
