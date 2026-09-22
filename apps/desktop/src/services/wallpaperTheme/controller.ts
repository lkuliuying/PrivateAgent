import { computed, readonly, ref, shallowRef } from "vue";
import { themeVariables } from "./palette";
import type { WallpaperImage } from "./image";
import { wallpaperStorage, type WallpaperRecord, type WallpaperStorage } from "./storage";

export function createWallpaperController(storage: WallpaperStorage = wallpaperStorage) {
  const saved = shallowRef<WallpaperRecord | null>(null);
  const imageUrl = ref("");
  const loading = ref(false);
  const busy = ref(false);
  const error = ref("");
  const enabled = computed(() => Boolean(saved.value?.enabled));
  const palette = computed(() => enabled.value ? saved.value?.palette : undefined);
  let revision = 0;
  let restorePromise: Promise<void> | undefined;
  let style: HTMLStyleElement | undefined;
  let previousAttribute: string | null = null;

  function removeOverrides() {
    if (!style) return;
    style.remove();
    style = undefined;
    if (previousAttribute === null) document.documentElement.removeAttribute("data-wallpaper-theme");
    else document.documentElement.setAttribute("data-wallpaper-theme", previousAttribute);
  }

  function display(record: WallpaperRecord | null, url: string) {
    const oldUrl = imageUrl.value;
    removeOverrides();
    if (record?.enabled) {
      previousAttribute = document.documentElement.getAttribute("data-wallpaper-theme");
      style = document.createElement("style");
      style.dataset.wallpaperTokens = "";
      style.textContent = `:root[data-wallpaper-theme] {${Object.entries(themeVariables(record.palette))
        .map(([key, value]) => `${key}:${value};`).join("")}}`;
      document.head.append(style);
      document.documentElement.setAttribute("data-wallpaper-theme", record.palette.mode);
    }
    saved.value = record;
    imageUrl.value = url;
    if (oldUrl) URL.revokeObjectURL(oldUrl);
  }

  function restore(): Promise<void> {
    if (restorePromise) return restorePromise;
    const current = ++revision;
    loading.value = true;
    restorePromise = (async () => {
      try {
        const record = await storage.read();
        if (current !== revision) return;
        const url = record ? URL.createObjectURL(record.blob) : "";
        display(record, url);
        error.value = "";
      } catch {
        if (current === revision) error.value = "无法读取本机壁纸主题，已使用默认外观。可在插件页重新选择图片或恢复默认。";
      } finally {
        if (current === revision) loading.value = false;
      }
    })();
    return restorePromise;
  }

  async function commit(record: WallpaperRecord | null): Promise<boolean> {
    if (busy.value || loading.value) return false;
    const current = ++revision;
    busy.value = true;
    error.value = "";
    let url = "";
    try {
      // 先准备显示资源、再提交事务；事务失败时不触碰正在使用的主题。
      url = record ? URL.createObjectURL(record.blob) : "";
      if (record) await storage.write(record);
      else await storage.clear();
      if (current !== revision) { if (url) URL.revokeObjectURL(url); return false; }
      display(record, url);
      return true;
    } catch {
      if (url) URL.revokeObjectURL(url);
      if (current === revision) error.value = "无法保存壁纸主题，原配置已保留。请检查本机存储空间或稍后重试。";
      return false;
    } finally {
      if (current === revision) busy.value = false;
    }
  }

  function dispose() {
    revision++;
    removeOverrides();
    if (imageUrl.value) URL.revokeObjectURL(imageUrl.value);
    imageUrl.value = "";
    saved.value = null;
    restorePromise = undefined;
    busy.value = loading.value = false;
    error.value = "";
  }

  return {
    saved: readonly(saved), imageUrl: readonly(imageUrl), loading: readonly(loading), busy: readonly(busy),
    error: readonly(error), enabled, palette, restore, dispose,
    apply: (image: WallpaperImage) => commit({ ...image, version: 1, enabled: true }),
    setEnabled: (value: boolean) => saved.value ? commit({ ...saved.value, enabled: value }) : Promise.resolve(false),
    reset: () => commit(null),
  };
}

export const wallpaperTheme = createWallpaperController();
