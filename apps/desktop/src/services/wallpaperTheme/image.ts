import { extractPalette, type WallpaperPalette } from "./palette";

export const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
export const MAX_IMAGE_EDGE = 3840;
export interface WallpaperImage {
  blob: Blob;
  name: string;
  width: number;
  height: number;
  palette: WallpaperPalette;
}

export function validateImage(file: File): void {
  if (!file.size) throw new Error("图片文件为空，请重新选择。");
  if (file.size > MAX_IMAGE_BYTES) throw new Error("图片不能超过 10 MB。");
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
    throw new Error("请选择 PNG、JPG 或 WebP 图片。");
  }
}

export async function processWallpaper(file: File, signal: AbortSignal): Promise<WallpaperImage> {
  validateImage(file);
  signal.throwIfAborted();
  const url = URL.createObjectURL(file);
  const image = new Image();
  const canvas = document.createElement("canvas");
  const sample = document.createElement("canvas");
  try {
    await new Promise<void>((resolve, reject) => {
      const finish = (error?: Error) => {
        clearTimeout(timer);
        signal.removeEventListener("abort", abort);
        image.onload = null;
        image.onerror = null;
        error ? reject(error) : resolve();
      };
      const abort = () => finish(new DOMException("图片处理已取消", "AbortError"));
      const timer = setTimeout(() => finish(new Error("图片解码超时，请换一张图片。")), 15_000);
      signal.addEventListener("abort", abort, { once: true });
      image.onload = () => finish();
      image.onerror = () => finish(new Error("无法解码图片，文件可能已损坏。"));
      // 浏览器按 EXIF 方向解码；绘制为静态帧后不再依赖原图方向或动画。
      image.src = url;
    });
    signal.throwIfAborted();
    const { naturalWidth: width, naturalHeight: height } = image;
    if (!width || !height) throw new Error("图片尺寸无效。");
    const scale = Math.min(1, MAX_IMAGE_EDGE / Math.max(width, height));
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const context = canvas.getContext("2d");
    const sampling = sample.getContext("2d", { willReadFrequently: true });
    if (!context || !sampling) throw new Error("当前环境不支持图片处理。");
    // 透明像素统一合成到白底，取色与最终壁纸使用同一份静态结果。
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const sampleScale = Math.min(1, 64 / Math.max(canvas.width, canvas.height));
    sample.width = Math.max(1, Math.round(canvas.width * sampleScale));
    sample.height = Math.max(1, Math.round(canvas.height * sampleScale));
    sampling.drawImage(canvas, 0, 0, sample.width, sample.height);
    const palette = extractPalette(sampling.getImageData(0, 0, sample.width, sample.height).data);
    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(value => value ? resolve(value) : reject(new Error("图片处理失败，请重试。")), "image/webp", 0.9);
    });
    signal.throwIfAborted();
    return { blob, palette, name: file.name.slice(0, 255), width: canvas.width, height: canvas.height };
  } finally {
    image.src = "";
    URL.revokeObjectURL(url);
    canvas.width = canvas.height = sample.width = sample.height = 0;
  }
}
