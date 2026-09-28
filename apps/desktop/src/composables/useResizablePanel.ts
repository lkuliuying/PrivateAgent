import { onBeforeUnmount, ref } from "vue";

/** 宽度按设备保存，拖动与键盘共享边界，卸载时撤销全局监听。 */
export function useResizablePanel(key: string, initial: number, min: number, max: number, direction = 1) {
  const clamp = (value: number) => Math.max(min, Math.min(max, Number.isFinite(value) ? value : initial));
  const width = ref(initial);
  try { const saved = localStorage.getItem(key); if (saved) width.value = clamp(Number(saved)); } catch { /* 存储不可用时保留本次宽度。 */ }
  let origin = 0;
  let startWidth = 0;
  function save() { try { localStorage.setItem(key, String(width.value)); } catch { /* 窗口内仍可调整。 */ } }
  function move(event: PointerEvent) { width.value = clamp(startWidth + (event.clientX - origin) * direction); }
  function stop() { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", stop); window.removeEventListener("pointercancel", stop); save(); }
  function start(event: PointerEvent) {
    if (event.button !== 0) return;
    event.preventDefault(); origin = event.clientX; startWidth = width.value;
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", stop); window.addEventListener("pointercancel", stop);
  }
  function keyboard(event: KeyboardEvent) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    width.value = clamp(event.key === "Home" ? min : event.key === "End" ? max : width.value + (event.key === "ArrowRight" ? 16 : -16) * direction);
    save();
  }
  onBeforeUnmount(stop);
  return { width, start, keyboard };
}
