import { describe, expect, it, vi } from "vitest";
vi.mock("../App.vue", () => ({ default: { template: "<div />" } }));
vi.mock("../services/backendStartup", () => ({ ensureDesktopBackendReady: vi.fn().mockResolvedValue(undefined) }));
import router from "./index";
import { ensureDesktopBackendReady } from "../services/backendStartup";
describe("单一工作台入口", () => {
  it.each(["/", "/login", "/register", "/admin"])("旧路径 %s 直接进入工作台", async (path) => {
    await router.push(path);
    expect(router.currentRoute.value.name).toBe("workspace");
    expect(router.hasRoute("login")).toBe(false);
    expect(router.hasRoute("register")).toBe(false);
    expect(router.hasRoute("admin")).toBe(false);
  });
  it("启动失败保留目标地址，由根组件提供重试", async () => {
    vi.mocked(ensureDesktopBackendReady).mockRejectedValueOnce(new Error("本机连接失败"));
    await router.push("/app?view=settings&section=mcp");
    expect(router.currentRoute.value.fullPath).toBe("/app?view=settings&section=mcp");
  });
});
