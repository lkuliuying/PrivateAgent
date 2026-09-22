import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createWallpaperController } from "./controller";
import { createPalette } from "./palette";
import type { WallpaperRecord } from "./storage";

const record: WallpaperRecord = {
  version: 1, enabled: true, blob: new Blob(["image"], { type: "image/webp" }), name: "wallpaper.webp",
  width: 1200, height: 800, palette: createPalette("#3858a0", "dark", false),
};
const storage = { read: vi.fn(async (): Promise<WallpaperRecord | null> => null), write: vi.fn(async () => {}), clear: vi.fn(async () => {}) };
let controller: ReturnType<typeof createWallpaperController>;
const revoke = vi.fn();
beforeEach(() => {
  vi.resetAllMocks();
  storage.read.mockResolvedValue(null);
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = vi.fn(() => `blob:${Math.random()}`);
    static revokeObjectURL = revoke;
  });
  controller = createWallpaperController(storage);
});
afterEach(() => { controller.dispose(); vi.unstubAllGlobals(); document.documentElement.removeAttribute("data-theme"); });

describe("壁纸主题事务与生命周期", () => {
  it("首次关闭，保存完成前不切换，停用后保留壁纸并可恢复", async () => {
    document.documentElement.setAttribute("data-theme", "dark");
    document.documentElement.style.setProperty("--color-bg", "pink");
    await controller.restore();
    expect(controller.enabled.value).toBe(false);
    let finish!: () => void;
    storage.write.mockImplementationOnce(() => new Promise(resolve => finish = resolve));
    const pending = controller.apply(record);
    expect(controller.enabled.value).toBe(false);
    expect(document.querySelector("[data-wallpaper-tokens]")).toBeNull();
    finish();
    expect(await pending).toBe(true);
    expect(controller.enabled.value).toBe(true);
    expect(document.documentElement.dataset.wallpaperTheme).toBe("dark");
    expect(await controller.setEnabled(false)).toBe(true);
    expect(controller.saved.value?.blob).toBe(record.blob);
    expect(document.documentElement.hasAttribute("data-wallpaper-theme")).toBe(false);
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.style.getPropertyValue("--color-bg")).toBe("pink");
    document.documentElement.style.removeProperty("--color-bg");
    expect(await controller.setEnabled(true)).toBe(true);
    expect(await controller.reset()).toBe(true);
    expect(controller.saved.value).toBeNull();
    expect(storage.clear).toHaveBeenCalledOnce();
    expect(revoke).toHaveBeenCalled();
  });

  it("写入、停用或清除失败均保留旧配置和显示资源", async () => {
    await controller.apply(record);
    const url = controller.imageUrl.value;
    storage.write.mockRejectedValue(new Error("QuotaExceededError"));
    expect(await controller.apply({ ...record, name: "new.webp" })).toBe(false);
    expect(await controller.setEnabled(false)).toBe(false);
    storage.clear.mockRejectedValue(new Error("I/O"));
    expect(await controller.reset()).toBe(false);
    expect(controller.imageUrl.value).toBe(url);
    expect(controller.saved.value?.name).toBe(record.name);
    expect(controller.enabled.value).toBe(true);
    expect(controller.error.value).toContain("原配置已保留");
    expect(revoke).not.toHaveBeenCalledWith(url);
  });

  it("重启读取 Blob；卸载释放 URL 和自身样式", async () => {
    storage.read.mockResolvedValue(record);
    await Promise.all([controller.restore(), controller.restore()]);
    expect(storage.read).toHaveBeenCalledOnce();
    expect(controller.enabled.value).toBe(true);
    const url = controller.imageUrl.value;
    controller.dispose();
    expect(revoke).toHaveBeenCalledWith(url);
    expect(document.querySelector("[data-wallpaper-tokens]")).toBeNull();
  });

  it("读取错误显示提示，卸载后到达的读取结果不再应用", async () => {
    storage.read.mockRejectedValueOnce(new Error("storage disabled"));
    await controller.restore();
    expect(controller.error.value).toContain("默认外观");
    controller.dispose();
    let finish!: (value: WallpaperRecord) => void;
    storage.read.mockImplementationOnce(() => new Promise(resolve => finish = resolve));
    const pending = controller.restore();
    controller.dispose();
    finish(record);
    await pending;
    expect(controller.enabled.value).toBe(false);
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("阻止重复写操作；写入中卸载不会重新应用主题", async () => {
    let finish!: () => void;
    storage.write.mockImplementationOnce(() => new Promise(resolve => finish = resolve));
    const pending = controller.apply(record);
    expect(await controller.apply(record)).toBe(false);
    controller.dispose();
    finish();
    expect(await pending).toBe(false);
    expect(controller.enabled.value).toBe(false);
    expect(revoke).toHaveBeenCalledOnce();
  });
});
