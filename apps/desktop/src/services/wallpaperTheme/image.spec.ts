import { afterEach, expect, it, vi } from "vitest";
import { MAX_IMAGE_BYTES, processWallpaper, validateImage } from "./image";

afterEach(() => vi.unstubAllGlobals());

it("检查空文件、类型及 10 MB 边界", () => {
  expect(() => validateImage(new File([], "empty.png", { type: "image/png" }))).toThrow("为空");
  expect(() => validateImage(new File(["gif"], "image.gif", { type: "image/gif" }))).toThrow("PNG");
  expect(() => validateImage(new File([new Uint8Array(MAX_IMAGE_BYTES + 1)], "large.png", { type: "image/png" }))).toThrow("10 MB");
  expect(() => validateImage(new File([new Uint8Array(MAX_IMAGE_BYTES)], "valid.png", { type: "image/png" }))).not.toThrow();
});

it("损坏图片和取消处理均释放对象 URL", async () => {
  const revoke = vi.fn();
  vi.stubGlobal("URL", class extends URL { static createObjectURL = () => "blob:test"; static revokeObjectURL = revoke; });
  const file = new File(["broken"], "image.png", { type: "image/png" });
  vi.stubGlobal("Image", class {
    onerror: (() => void) | null = null;
    set src(value: string) { if (value) queueMicrotask(() => this.onerror?.()); }
  });
  await expect(processWallpaper(file, new AbortController().signal)).rejects.toThrow("损坏");
  expect(revoke).toHaveBeenCalledWith("blob:test");
  vi.stubGlobal("Image", class { set src(_value: string) {} });
  const controller = new AbortController();
  const pending = processWallpaper(file, controller.signal);
  controller.abort();
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  expect(revoke).toHaveBeenCalledTimes(2);
});
