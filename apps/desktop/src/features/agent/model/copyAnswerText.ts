/**
 * v0.8.0 W6-R2 · 最终回答复制（纯函数，无 DOM 副作用）
 *
 * 复制内容 = 该轮完整最终回答正文（保留换行）；不混入按钮文案、过程或
 * 隐藏 DOM（调用方只传可见最终回答文本，计划 §4.4/§6.7）。
 * 返回结果种类供组件区分提示：成功只提示「回答已复制」，失败/不可用给出
 * 可恢复指引；通知与提示中一律不含回答正文（零容忍：敏感正文不进通知）。
 */

export type CopyResult = "ok" | "failed" | "unavailable";

export async function copyAnswerText(text: string): Promise<CopyResult> {
  const value = text.replace(/\s+$/, "");
  if (!value.trim()) return "failed";

  // 首选：异步剪贴板 API（Tauri webview/现代浏览器）
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return "ok";
    }
  } catch {
    /* 权限拒绝/安全上下文限制 → 走回退 */
  }

  // 回退：临时 textarea + execCommand（不保留在 DOM 中）
  try {
    if (typeof document === "undefined") return "unavailable";
    const holder = document.createElement("textarea");
    holder.value = value;
    holder.setAttribute("readonly", "");
    holder.setAttribute("aria-hidden", "true");
    holder.style.position = "fixed";
    holder.style.left = "-9999px";
    document.body.appendChild(holder);
    holder.select();
    const copied = document.execCommand("copy");
    document.body.removeChild(holder);
    return copied ? "ok" : "failed";
  } catch {
    return "unavailable";
  }
}

/** 提示文案（不含回答正文）。 */
export const COPY_SUCCESS_MESSAGE = "回答已复制";
export const COPY_FAILED_MESSAGE = "复制失败，请手动选择回答文本复制";
export const COPY_UNAVAILABLE_MESSAGE = "当前环境不支持剪贴板，请手动选择回答文本复制";
