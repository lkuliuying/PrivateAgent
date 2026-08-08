/**
 * 全局快捷键（0.4.0 D2）
 * Ctrl/Cmd+K 命令面板；Ctrl/Cmd+N 新建任务；Alt+←/→ 视图返回/前进。
 * 输入框/文本域内不拦截编辑键；Esc 由各浮层自行处理。
 */
import { onBeforeUnmount, onMounted } from "vue";

export interface ShortcutHandlers {
  openCommand?: () => void;
  newSession?: () => void;
  goBack?: () => void;
  goForward?: () => void;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    target.isContentEditable
  );
}

export function useShortcuts(handlers: ShortcutHandlers) {
  function onKeydown(event: KeyboardEvent) {
    const meta = event.ctrlKey || event.metaKey;
    if (meta && event.key.toLowerCase() === "k") {
      event.preventDefault();
      handlers.openCommand?.();
      return;
    }
    if (meta && event.key.toLowerCase() === "n") {
      // 输入框内 Ctrl/Cmd+N 仍新建任务（Windows 无冲突，macOS 也在菜单之外）
      event.preventDefault();
      handlers.newSession?.();
      return;
    }
    if (event.altKey && event.key === "ArrowLeft") {
      event.preventDefault();
      handlers.goBack?.();
      return;
    }
    if (event.altKey && event.key === "ArrowRight") {
      event.preventDefault();
      handlers.goForward?.();
      return;
    }
    // 其余全局快捷键不得覆盖输入编辑行为
    if (meta && isEditableTarget(event.target)) return;
  }

  onMounted(() => window.addEventListener("keydown", onKeydown));
  onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown));

  return { onKeydown };
}
