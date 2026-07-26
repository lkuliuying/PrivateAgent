import { describe, expect, it, vi } from "vitest";
import {
  APPEARANCE_CONTRAST_KEY,
  APPEARANCE_THEME_KEY,
  createAppearanceStore,
  type AppearanceRuntime,
} from "./appearance";

class MemoryStorage {
  readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

class ThemeMediaQuery {
  matches: boolean;
  private readonly listeners = new Set<(event: MediaQueryListEvent) => void>();

  constructor(matches: boolean) {
    this.matches = matches;
  }

  addEventListener(
    _type: "change",
    listener: (event: MediaQueryListEvent) => void
  ): void {
    this.listeners.add(listener);
  }

  removeEventListener(
    _type: "change",
    listener: (event: MediaQueryListEvent) => void
  ): void {
    this.listeners.delete(listener);
  }

  setMatches(matches: boolean): void {
    this.matches = matches;
    const event = { matches } as MediaQueryListEvent;
    this.listeners.forEach((listener) => listener(event));
  }

  get listenerCount(): number {
    return this.listeners.size;
  }
}

function createRuntime(
  storage: MemoryStorage,
  media: ThemeMediaQuery,
  root = document.createElement("html")
): AppearanceRuntime {
  return {
    root,
    storage,
    matchMedia: vi.fn(() => media),
  };
}

describe("appearance store", () => {
  it("同步应用已持久化的主题和独立高对比偏好", () => {
    const storage = new MemoryStorage();
    storage.values.set(APPEARANCE_THEME_KEY, "dark");
    storage.values.set(APPEARANCE_CONTRAST_KEY, "more");
    const root = document.createElement("html");
    const store = createAppearanceStore(
      createRuntime(storage, new ThemeMediaQuery(false), root)
    );

    store.start();

    expect(store.theme.value).toBe("dark");
    expect(store.resolvedTheme.value).toBe("dark");
    expect(store.contrast.value).toBe("more");
    expect(root.dataset).toMatchObject({
      theme: "dark",
      themePreference: "dark",
      contrast: "more",
      appearanceReady: "true",
    });
    expect(root.style.getPropertyValue("color-scheme")).toBe("dark");
  });

  it("同步 WebView theme-color 与当前背景 token", () => {
    const storage = new MemoryStorage();
    const root = document.createElement("html");
    root.style.setProperty("--color-bg", "#151917");
    const meta = document.createElement("meta");
    meta.name = "theme-color";
    meta.content = "#ffffff";
    document.head.append(meta);

    try {
      const store = createAppearanceStore(
        createRuntime(storage, new ThemeMediaQuery(true), root)
      );
      store.start();
      expect(meta.content).toBe("#151917");
    } finally {
      meta.remove();
    }
  });

  it("跟随系统配色变化，并在 stop 后清理监听", () => {
    const storage = new MemoryStorage();
    const media = new ThemeMediaQuery(false);
    const root = document.createElement("html");
    const store = createAppearanceStore(createRuntime(storage, media, root));

    store.start();
    store.start();
    expect(root.dataset.theme).toBe("light");
    expect(media.listenerCount).toBe(1);

    media.setMatches(true);
    expect(store.resolvedTheme.value).toBe("dark");
    expect(root.dataset.theme).toBe("dark");

    store.stop();
    expect(media.listenerCount).toBe(0);
    media.setMatches(false);
    expect(root.dataset.theme).toBe("dark");
  });

  it("显式主题优先于系统，并持久化循环与对比设置", () => {
    const storage = new MemoryStorage();
    const media = new ThemeMediaQuery(true);
    const store = createAppearanceStore(createRuntime(storage, media));
    store.start();

    store.cycleTheme();
    expect(store.theme.value).toBe("light");
    expect(store.resolvedTheme.value).toBe("light");
    expect(storage.getItem(APPEARANCE_THEME_KEY)).toBe("light");

    media.setMatches(false);
    expect(store.resolvedTheme.value).toBe("light");

    store.toggleContrast();
    expect(store.contrast.value).toBe("more");
    expect(storage.getItem(APPEARANCE_CONTRAST_KEY)).toBe("more");
  });

  it("存储不可用或值无效时仍以安全默认值启动", () => {
    const storage = {
      getItem: vi.fn(() => {
        throw new DOMException("denied");
      }),
      setItem: vi.fn(() => {
        throw new DOMException("denied");
      }),
    };
    const root = document.createElement("html");
    const store = createAppearanceStore({
      root,
      storage,
      matchMedia: () => new ThemeMediaQuery(false),
    });

    expect(() => store.start()).not.toThrow();
    expect(() => store.setTheme("dark")).not.toThrow();
    expect(store.theme.value).toBe("dark");
    expect(root.dataset.contrast).toBe("normal");
  });
});
