import { readonly, ref, type Ref } from "vue";

export type ThemePreference = "system" | "light" | "dark";
export type ContrastPreference = "normal" | "more";
export type ResolvedTheme = Exclude<ThemePreference, "system">;

export const APPEARANCE_THEME_KEY = "private-agent.appearance.theme";
export const APPEARANCE_CONTRAST_KEY = "private-agent.appearance.contrast";

interface AppearanceStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

interface AppearanceMediaQuery {
  readonly matches: boolean;
  addEventListener?: (
    type: "change",
    listener: (event: MediaQueryListEvent) => void
  ) => void;
  removeEventListener?: (
    type: "change",
    listener: (event: MediaQueryListEvent) => void
  ) => void;
  addListener?: (listener: (event: MediaQueryListEvent) => void) => void;
  removeListener?: (listener: (event: MediaQueryListEvent) => void) => void;
}

export interface AppearanceRuntime {
  root?: HTMLElement | null;
  storage?: AppearanceStorage | null;
  matchMedia?: ((query: string) => AppearanceMediaQuery) | null;
}

export interface AppearanceStore {
  theme: Readonly<Ref<ThemePreference>>;
  contrast: Readonly<Ref<ContrastPreference>>;
  resolvedTheme: Readonly<Ref<ResolvedTheme>>;
  setTheme: (value: ThemePreference) => void;
  cycleTheme: () => void;
  setContrast: (value: ContrastPreference) => void;
  toggleContrast: () => void;
  start: () => void;
  stop: () => void;
}

const THEME_VALUES: readonly ThemePreference[] = ["system", "light", "dark"];
const CONTRAST_VALUES: readonly ContrastPreference[] = ["normal", "more"];

function browserRuntime(): AppearanceRuntime {
  let storage: AppearanceStorage | null = null;
  try {
    storage = typeof window === "undefined" ? null : window.localStorage;
  } catch {
    // Sandboxed desktop webviews can deny storage; appearance must still boot.
  }

  return {
    root: typeof document === "undefined" ? null : document.documentElement,
    storage,
    matchMedia:
      typeof window !== "undefined" && typeof window.matchMedia === "function"
        ? window.matchMedia.bind(window)
        : null,
  };
}

function readPreference<T extends string>(
  storage: AppearanceStorage | null | undefined,
  key: string,
  allowed: readonly T[],
  fallback: T
): T {
  try {
    const stored = storage?.getItem(key);
    return stored && allowed.includes(stored as T) ? (stored as T) : fallback;
  } catch {
    return fallback;
  }
}

function writePreference(
  storage: AppearanceStorage | null | undefined,
  key: string,
  value: string
): void {
  try {
    storage?.setItem(key, value);
  } catch {
    // Appearance remains usable when persistence is unavailable.
  }
}

function createMediaQuery(
  matchMedia: AppearanceRuntime["matchMedia"],
  query: string
): AppearanceMediaQuery | null {
  try {
    return matchMedia?.(query) ?? null;
  } catch {
    return null;
  }
}

function resolveThemePreference(
  preference: ThemePreference,
  systemDark: boolean
): ResolvedTheme {
  if (preference === "system") return systemDark ? "dark" : "light";
  return preference;
}

function listenToMediaQuery(
  query: AppearanceMediaQuery,
  listener: (event: MediaQueryListEvent) => void
): () => void {
  if (query.addEventListener) {
    query.addEventListener("change", listener);
    return () => query.removeEventListener?.("change", listener);
  }

  query.addListener?.(listener);
  return () => query.removeListener?.(listener);
}

function syncThemeColor(root: HTMLElement): void {
  const ownerDocument = root.ownerDocument;
  const meta = ownerDocument?.querySelector<HTMLMetaElement>(
    'meta[name="theme-color"]'
  );
  const background = ownerDocument?.defaultView
    ?.getComputedStyle(root)
    .getPropertyValue("--color-bg")
    .trim();
  if (meta && background) meta.content = background;
}

export function createAppearanceStore(
  runtime: AppearanceRuntime = browserRuntime()
): AppearanceStore {
  const theme = ref<ThemePreference>(
    readPreference(runtime.storage, APPEARANCE_THEME_KEY, THEME_VALUES, "system")
  );
  const contrast = ref<ContrastPreference>(
    readPreference(
      runtime.storage,
      APPEARANCE_CONTRAST_KEY,
      CONTRAST_VALUES,
      "normal"
    )
  );
  const darkQuery = createMediaQuery(
    runtime.matchMedia,
    "(prefers-color-scheme: dark)"
  );
  const resolvedTheme = ref<ResolvedTheme>(
    resolveThemePreference(theme.value, darkQuery?.matches ?? false)
  );

  let started = false;
  let removeThemeListener: (() => void) | null = null;

  function apply(): void {
    resolvedTheme.value = resolveThemePreference(
      theme.value,
      darkQuery?.matches ?? false
    );

    const root = runtime.root;
    if (!root) return;
    root.dataset.theme = resolvedTheme.value;
    root.dataset.themePreference = theme.value;
    root.dataset.contrast = contrast.value;
    root.dataset.appearanceReady = "true";
    root.style.setProperty("color-scheme", resolvedTheme.value);
    syncThemeColor(root);
  }

  function setTheme(value: ThemePreference): void {
    theme.value = value;
    writePreference(runtime.storage, APPEARANCE_THEME_KEY, value);
    apply();
  }

  function cycleTheme(): void {
    const index = THEME_VALUES.indexOf(theme.value);
    setTheme(THEME_VALUES[(index + 1) % THEME_VALUES.length]);
  }

  function setContrast(value: ContrastPreference): void {
    contrast.value = value;
    writePreference(runtime.storage, APPEARANCE_CONTRAST_KEY, value);
    apply();
  }

  function toggleContrast(): void {
    setContrast(contrast.value === "more" ? "normal" : "more");
  }

  function start(): void {
    apply();
    if (started) return;
    started = true;
    if (darkQuery) {
      removeThemeListener = listenToMediaQuery(darkQuery, apply);
    }
  }

  function stop(): void {
    if (!started) return;
    started = false;
    removeThemeListener?.();
    removeThemeListener = null;
  }

  return {
    theme: readonly(theme),
    contrast: readonly(contrast),
    resolvedTheme: readonly(resolvedTheme),
    setTheme,
    cycleTheme,
    setContrast,
    toggleContrast,
    start,
    stop,
  };
}

const appearanceStore = createAppearanceStore();

export function useAppearance(): AppearanceStore {
  return appearanceStore;
}
