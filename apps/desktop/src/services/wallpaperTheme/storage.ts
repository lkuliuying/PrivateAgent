import type { WallpaperImage } from "./image";
import { createPalette } from "./palette";

export interface WallpaperRecord extends WallpaperImage { version: 1; enabled: boolean }
export interface WallpaperStorage {
  read(): Promise<WallpaperRecord | null>;
  write(record: WallpaperRecord): Promise<void>;
  clear(): Promise<void>;
}

function validateRecord(value: unknown): WallpaperRecord | null {
  if (value === undefined) return null;
  const record = value as WallpaperRecord | null;
  if (!record || record.version !== 1 || typeof record.enabled !== "boolean"
    || !(record.blob instanceof Blob) || !record.blob.size || record.blob.size > 64 * 1024 * 1024
    || !["image/webp", "image/png"].includes(record.blob.type)
    || typeof record.name !== "string" || record.name.length > 255
    || ![record.width, record.height].every(v => Number.isInteger(v) && v > 0 && v <= 3840)
    || !record.palette || !["light", "dark"].includes(record.palette.mode)
    || !/^#[0-9a-f]{6}$/i.test(record.palette.seed) || typeof record.palette.neutral !== "boolean") {
    throw new Error("已保存的壁纸配置无效，请重新选择图片或恢复默认。");
  }
  // 从受限颜色字段重新生成令牌，不把存储内容直接作为 CSS 注入。
  return { ...record, palette: createPalette(record.palette.seed, record.palette.mode, record.palette.neutral) };
}

function transact<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest, parse: (value: unknown) => T): Promise<T> {
  return new Promise((resolve, reject) => {
    if (!globalThis.indexedDB) return reject(new Error("当前环境无法使用本机壁纸存储。"));
    let db: IDBDatabase | undefined, transaction: IDBTransaction | undefined;
    let done = false, result: T;
    const finish = (error?: unknown) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      db?.close();
      error ? reject(error) : resolve(result);
    };
    const timer = setTimeout(() => {
      transaction?.abort();
      finish(new Error("本机壁纸存储超时，请重试。"));
    }, 10_000);
    let request: IDBOpenDBRequest;
    try { request = indexedDB.open("privateagent-wallpaper-theme", 1); }
    catch (error) { finish(error); return; }
    request.onblocked = () => finish(new Error("本机壁纸存储被其他窗口占用，请关闭其他窗口后重试。"));
    request.onerror = () => finish(request.error ?? new Error("无法打开本机壁纸存储。"));
    request.onupgradeneeded = () => {
      if (done) { request.transaction?.abort(); return; }
      request.result.createObjectStore("theme");
    };
    request.onsuccess = () => {
      db = request.result;
      if (done) { db.close(); return; }
      db.onversionchange = () => db?.close();
      try {
        transaction = db.transaction("theme", mode);
        transaction.oncomplete = () => finish();
        transaction.onabort = () => finish(transaction?.error ?? new Error("壁纸保存未完成，原配置已保留。"));
        transaction.onerror = () => finish(transaction?.error ?? new Error("无法访问本机壁纸存储。"));
        const operation = action(transaction.objectStore("theme"));
        operation.onsuccess = () => {
          try { result = parse(operation.result); }
          catch (error) { transaction?.abort(); finish(error); }
        };
      } catch (error) { finish(error); }
    };
  });
}

export const wallpaperStorage: WallpaperStorage = {
  read: () => transact("readonly", store => store.get("current"), validateRecord),
  write: record => transact("readwrite", store => store.put(record, "current"), () => undefined),
  clear: () => transact("readwrite", store => store.delete("current"), () => undefined),
};
