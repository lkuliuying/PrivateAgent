export type WindowCloseBehavior = "background" | "exit";

const STORAGE_KEY = "pa_window_close_behavior";

export function getSavedWindowCloseBehavior(): WindowCloseBehavior | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value === "background" || value === "exit" ? value : null;
  } catch {
    return null;
  }
}

export function saveWindowCloseBehavior(behavior: WindowCloseBehavior): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, behavior);
  } catch {
    // localStorage 不可用时退化为每次询问，不影响本次关闭动作。
  }
}

export function clearWindowCloseBehavior(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // 与读取保持相同的无持久化退化策略。
  }
}
