import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { cmdCheckForUpdates, cmdDownloadAndInstallUpdate, cmdRelaunchApp } from "../api";
import UpdateChecker from "./UpdateChecker.vue";

const confirm = vi.hoisted(() => vi.fn());
vi.mock("../stores/notifications", () => ({ useNotifications: () => ({ confirm }) }));
vi.mock("../api", () => ({
  cmdCheckForUpdates: vi.fn(),
  cmdDownloadAndInstallUpdate: vi.fn(),
  cmdRelaunchApp: vi.fn(),
}));

const nextVersion = { version: "1.0.1", date: null, body: "修复更新" };

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(cmdCheckForUpdates).mockResolvedValue(nextVersion);
  vi.mocked(cmdDownloadAndInstallUpdate).mockResolvedValue(undefined);
  vi.mocked(cmdRelaunchApp).mockResolvedValue(undefined);
  confirm.mockResolvedValue(true);
});

async function checked() {
  const wrapper = mount(UpdateChecker);
  await wrapper.get(".ghost-btn").trigger("click");
  await flushPromises();
  return wrapper;
}

describe("UpdateChecker", () => {
  it("checks and confirms the displayed version before installing and relaunching", async () => {
    const wrapper = await checked();
    expect(wrapper.text()).toContain("下载并安装 v1.0.1");
    await wrapper.get(".primary-btn").trigger("click");
    await flushPromises();
    expect(confirm).toHaveBeenCalledWith(expect.objectContaining({ title: "安装 PrivateAgent v1.0.1？" }));
    expect(cmdDownloadAndInstallUpdate).toHaveBeenCalledWith("1.0.1");
    expect(cmdRelaunchApp).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("does not install if the user cancels or leaves during confirmation", async () => {
    confirm.mockResolvedValueOnce(false);
    const wrapper = await checked();
    await wrapper.get(".primary-btn").trigger("click");
    await flushPromises();
    expect(cmdDownloadAndInstallUpdate).not.toHaveBeenCalled();
    let resolve!: (accepted: boolean) => void;
    confirm.mockImplementationOnce(() => new Promise<boolean>((done) => { resolve = done; }));
    await wrapper.get(".primary-btn").trigger("click");
    expect(wrapper.get(".ghost-btn").attributes("disabled")).toBeDefined();
    wrapper.unmount();
    resolve(true);
    await flushPromises();
    expect(cmdDownloadAndInstallUpdate).not.toHaveBeenCalled();
  });

  it("prevents concurrent checks or duplicate installation while downloading", async () => {
    let resolve!: () => void;
    vi.mocked(cmdDownloadAndInstallUpdate).mockImplementation(() => new Promise<void>((done) => { resolve = done; }));
    const wrapper = await checked();
    await wrapper.get(".primary-btn").trigger("click");
    await flushPromises();
    expect(wrapper.get(".ghost-btn").attributes("disabled")).toBeDefined();
    expect(wrapper.get(".primary-btn").attributes("disabled")).toBeDefined();
    await wrapper.get(".primary-btn").trigger("click");
    await wrapper.get(".ghost-btn").trigger("click");
    expect(cmdDownloadAndInstallUpdate).toHaveBeenCalledTimes(1);
    expect(cmdCheckForUpdates).toHaveBeenCalledTimes(1);
    resolve();
    await flushPromises();
    wrapper.unmount();
  });

  it.each([
    ["signature verification failed", "更新签名验证失败"],
    ["Download request failed with status: 404", "无法连接更新服务器或下载安装包"],
  ])("keeps the app open and allows retry after %s", async (message, expected) => {
    vi.mocked(cmdDownloadAndInstallUpdate).mockRejectedValue(new Error(message));
    const wrapper = await checked();
    await wrapper.get(".primary-btn").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain(expected);
    expect(wrapper.text()).not.toContain("下载安装完成");
    expect(cmdRelaunchApp).not.toHaveBeenCalled();
    expect(wrapper.get(".ghost-btn").attributes("disabled")).toBeUndefined();
    wrapper.unmount();
  });

  it("reports no update without offering installation", async () => {
    vi.mocked(cmdCheckForUpdates).mockResolvedValue(null);
    const wrapper = await checked();
    expect(wrapper.text()).toContain("当前已是最新版本");
    expect(wrapper.find(".primary-btn").exists()).toBe(false);
    wrapper.unmount();
  });

  it("reports a failed restart without reporting successful restart", async () => {
    vi.mocked(cmdRelaunchApp).mockRejectedValue(new Error("restart failed"));
    const wrapper = await checked();
    await wrapper.get(".primary-btn").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("请手动重启应用");
    expect(wrapper.text()).not.toContain("正在重启");
    wrapper.unmount();
  });
});
