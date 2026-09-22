import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ExtensionRegistryPanel from "./ExtensionRegistryPanel.vue";
import { wallpaperTheme } from "../services/wallpaperTheme/controller";
import { processWallpaper } from "../services/wallpaperTheme/image";
import { createPalette } from "../services/wallpaperTheme/palette";

vi.mock("../services/wallpaperTheme/image", () => ({ processWallpaper: vi.fn() }));
vi.mock("../services/wallpaperTheme/storage", () => ({ wallpaperStorage: { read: vi.fn(async () => null), write: vi.fn(async () => {}), clear: vi.fn(async () => {}) } }));
enableAutoUnmount(afterEach);
beforeEach(() => {
  vi.stubGlobal("URL", class extends URL { static createObjectURL = vi.fn(() => "blob:preview"); static revokeObjectURL = vi.fn(); });
});
afterEach(() => { wallpaperTheme.dispose(); vi.unstubAllGlobals(); vi.clearAllMocks(); });
it("壁纸插件首次关闭且不请求旧服务", () => {
  vi.stubGlobal("fetch", vi.fn());
  const wrapper = mount(ExtensionRegistryPanel);
  expect(wrapper.get('[role="status"]').text()).toContain("尚未启用");
  expect(wrapper.get('[role="switch"]').attributes("aria-checked")).toBe("false");
  expect(fetch).not.toHaveBeenCalled();
  wrapper.unmount();
});

it("连续选图只接受最新结果；预览、取消及离开都不改变全局主题", async () => {
  const wrapper = mount(ExtensionRegistryPanel);
  const input = wrapper.get('input[type="file"]');
  const file = new File(["image"], "one.png", { type: "image/png" });
  const image = { name: "one.png", blob: file, width: 100, height: 100, palette: createPalette("#3858a0", "dark", false) };
  let first!: (value: typeof image) => void;
  vi.mocked(processWallpaper).mockImplementationOnce(() => new Promise(resolve => first = resolve));
  vi.mocked(processWallpaper).mockResolvedValueOnce({ ...image, name: "two.png" });
  Object.defineProperty(input.element, "files", { configurable: true, value: [file] });
  await input.trigger("change");
  const signal = vi.mocked(processWallpaper).mock.calls[0][1];
  await input.trigger("change");
  await flushPromises();
  first(image);
  await flushPromises();
  expect(signal.aborted).toBe(true);
  expect(wrapper.get(".wallpaper-name").text()).toBe("two.png");
  expect(wallpaperTheme.enabled.value).toBe(false);
  Object.defineProperty(input.element, "files", { value: [] });
  await input.trigger("change");
  expect(wrapper.get(".wallpaper-name").text()).toBe("two.png");
  wrapper.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview");
  expect(wallpaperTheme.saved.value).toBeNull();
});
