import { beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import ConnectionSettings from "./ConnectionSettings.vue";
import { defaultConnectionProfile, saveConnectionProfile } from "../services/connectionProfile";

vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => true }));
vi.mock("../services/localExecutor", () => ({ stopLocalExecutor: vi.fn() }));

describe("模型设置界面", () => {
  beforeEach(() => { window.localStorage.clear(); window.sessionStorage.clear(); });
  it("仅提供模型执行选择，没有账号模式或服务器地址设置", async () => {
    const wrapper = mount(ConnectionSettings);
    expect(wrapper.text()).toContain("模型执行设置");
    expect(wrapper.text()).not.toContain("自托管");
    expect(wrapper.text()).not.toContain("无需云端账号");
    expect(wrapper.findAll("input")).toHaveLength(0);
    await wrapper.get("select").setValue("local");
    expect(wrapper.text()).toContain("本机模型地址");
    expect(wrapper.text()).toContain("始终使用服务器账号登录");
    expect(wrapper.findAll("input")).toHaveLength(3);
    wrapper.unmount();
  });
  it("恢复本机模型参数，未填写模型时显示错误而不清除账号", async () => {
    saveConnectionProfile({ ...defaultConnectionProfile(), inference_mode: "local", model_name: "" });
    window.sessionStorage.setItem("pa_access_token", "keep-session");
    const wrapper = mount(ConnectionSettings);
    await wrapper.get("form").trigger("submit");
    expect(wrapper.get('[role="alert"]').text()).toContain("请填写本机模型名称");
    expect(window.sessionStorage.getItem("pa_access_token")).toBe("keep-session");
    wrapper.unmount();
  });
  it("损坏的模型配置有明确提示且仍可编辑", () => {
    window.localStorage.setItem("privateagent.local-model.v1", "{broken");
    const wrapper = mount(ConnectionSettings);
    expect(wrapper.get('[role="alert"]').text()).toContain("配置无效");
    expect(wrapper.find("select").exists()).toBe(true);
    wrapper.unmount();
  });
});
