/**
 * v0.9.0 H1 任务 8：会话时间统一显示服务（计划 §5.2 / H0 §5）
 *
 * - 产品时区固定 IANA `Asia/Shanghai`，24 小时制；
 * - 后端返回带 `Z` 的 RFC 3339 UTC（唯一排序事实），本模块统一转换为
 *   上海时区显示；组件禁止各自调用本机 locale（防止操作系统时区漂移）；
 * - 「今天/昨天/更早」分组以 Asia/Shanghai 自然日判断；
 * - 相对时间（刚刚/N 分钟前）与时区无关，按时间差计算。
 */

/** 产品时区常量（与后端 PRODUCT_TIMEZONE 一致）。 */
export const PRODUCT_TIMEZONE = "Asia/Shanghai";

function parse(input: string | Date | null | undefined): Date | null {
  if (!input) return null;
  const date = input instanceof Date ? input : new Date(input);
  return Number.isNaN(date.getTime()) ? null : date;
}

const timeFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: PRODUCT_TIMEZONE,
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const dateTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: PRODUCT_TIMEZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const dateFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: PRODUCT_TIMEZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const weekdayFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: PRODUCT_TIMEZONE,
  weekday: "short",
});

/** 24 小时制 `HH:MM`（上海时区）。 */
export function formatTime(input: string | Date | null | undefined): string {
  const date = parse(input);
  return date ? timeFormatter.format(date) : "—";
}

/** `YYYY/MM/DD HH:MM`（上海时区）。 */
export function formatDateTime(
  input: string | Date | null | undefined
): string {
  const date = parse(input);
  return date ? dateTimeFormatter.format(date).replace(/\//g, "-") : "—";
}

/** `YYYY/MM/DD`（上海时区）。 */
export function formatDate(input: string | Date | null | undefined): string {
  const date = parse(input);
  return date ? dateFormatter.format(date).replace(/\//g, "-") : "—";
}

/** 产品时区下的「自然日键」（YYYY-MM-DD），用于今天/昨天/更早分组。 */
export function calendarDayKey(
  input: string | Date | null | undefined
): string | null {
  const date = parse(input);
  if (!date) return null;
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: PRODUCT_TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return fmt.format(date);
}

/** 相对时间：刚刚 / N 分钟前 / 上海当日 HH:MM / 昨天 / 周内 / 更早日期。 */
export function formatRelative(
  input: string | Date | null | undefined,
  now: Date = new Date()
): string {
  const date = parse(input);
  if (!date) return "—";
  const diffMs = now.getTime() - date.getTime();
  if (diffMs < 60_000) return "刚刚";
  if (diffMs < 3_600_000) return `${Math.floor(diffMs / 60_000)} 分钟前`;
  // 自然日分组以产品时区为准（不受操作系统时区漂移影响）
  const dayKey = calendarDayKey(date);
  const todayKey = calendarDayKey(now);
  if (dayKey === todayKey) return timeFormatter.format(date);
  const yesterdayKey = calendarDayKey(
    new Date(now.getTime() - 24 * 3_600_000)
  );
  if (dayKey === yesterdayKey) {
    return `昨天 ${timeFormatter.format(date)}`;
  }
  if (diffMs < 7 * 24 * 3_600_000) {
    return `${weekdayFormatter.format(date)} ${timeFormatter.format(date)}`;
  }
  const sameYear = dayKey?.slice(0, 4) === todayKey?.slice(0, 4);
  const md = new Intl.DateTimeFormat("zh-CN", {
    timeZone: PRODUCT_TIMEZONE,
    month: "numeric",
    day: "numeric",
  }).format(date);
  return sameYear ? md : `${dateFormatter.format(date).replace(/\//g, "-")}`;
}
