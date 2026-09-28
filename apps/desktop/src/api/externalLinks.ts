import { isTauri } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
/** 登录链接只允许公开 HTTPS；桌面端使用系统浏览器，网页预览使用独立窗口。 */
export async function openAuthorizationLink(value: string): Promise<void> {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password) throw new Error("登录链接无效");
  if (isTauri()) await openUrl(url.href);
  else window.open(url.href, "_blank", "noopener,noreferrer");
}
