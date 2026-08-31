import { afterEach, describe, expect, it, vi } from "vitest";
import {
  PRODUCT_TIMEZONE,
  calendarDayKey,
  formatAdminDateTime,
  formatDate,
  formatDateTime,
  formatRelative,
  formatTime,
} from "./timeDisplay";

describe("timeDisplay（v0.9.0 H0 §5：UTC 事实 + Asia/Shanghai 显示）", () => {
  it("产品时区固定 Asia/Shanghai", () => {
    expect(PRODUCT_TIMEZONE).toBe("Asia/Shanghai");
  });

  it("带 Z 的 RFC 3339 UTC 按上海时区 24 小时制格式化", () => {
    // UTC 16:00 == 上海次日 00:00（UTC+8，无 DST）：跨日语义正确
    expect(formatTime("2026-08-23T16:00:00.000Z")).toBe("00:00");
    expect(formatDateTime("2026-08-23T16:00:00.000Z")).toBe(
      "2026-08-24 00:00"
    );
    expect(formatDate("2026-08-23T16:00:00.000Z")).toBe("2026-08-24");
  });

  it("上海零点与 UTC 跨日的自然日键一致", () => {
    // 上海 2026-08-24 00:00 == UTC 2026-08-23 16:00
    expect(calendarDayKey("2026-08-23T16:00:00.000Z")).toBe("2026-08-24");
    expect(calendarDayKey("2026-08-23T15:59:59.999Z")).toBe("2026-08-23");
  });

  it("非法/空输入返回占位不抛错", () => {
    expect(formatTime(null)).toBe("—");
    expect(formatDateTime(undefined)).toBe("—");
    expect(formatRelative("not-a-date")).toBe("—");
    expect(calendarDayKey("")).toBeNull();
  });

  it("相对时间按差值计算且当日显示上海时间", () => {
    const now = new Date("2026-08-24T04:00:00.000Z"); // 上海 12:00
    const justNow = new Date("2026-08-24T03:59:30.000Z");
    const minutesAgo = new Date("2026-08-24T03:47:00.000Z");
    const todayEarlier = new Date("2026-08-24T01:00:00.000Z"); // 上海 09:00
    const yesterday = new Date("2026-08-23T02:00:00.000Z"); // 上海昨日 10:00

    expect(formatRelative(justNow, now)).toBe("刚刚");
    expect(formatRelative(minutesAgo, now)).toBe("13 分钟前");
    // 超过 1 小时但仍是上海当日 → HH:MM
    expect(formatRelative(todayEarlier, now)).toBe("09:00");
    expect(formatRelative(yesterday, now)).toBe("昨天 10:00");
  });

  it("无 Z 后缀的 naive 字符串按 JS 本地解析兜底（不崩溃）", () => {
    // 旧数据兼容：后端已统一带 Z；此处只保证不抛异常
    expect(() => formatDateTime("2026-08-23T10:00:00")).not.toThrow();
  });
});

describe("管理员时间兼容旧管理 API", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it.each(["UTC", "Asia/Shanghai", "America/Los_Angeles"])(
    "客户端时区为 %s 时，UTC、旧无时区和显式偏移表示同一上海时间",
    (timezone) => {
      vi.stubEnv("TZ", timezone);
      for (const input of [
        "2026-08-30T16:08:04.123Z",
        "2026-08-30T16:08:04",
        "2026-08-30 16:08:04.123456",
        "2026-08-31T00:08:04+08:00",
        "2026-08-30T09:08:04-07:00",
        new Date("2026-08-30T16:08:04Z"),
      ]) {
        expect(formatAdminDateTime(input)).toBe("2026年8月31日 00:08:04");
      }
    }
  );

  it.each([null, undefined, "", "  ", "not-a-date", new Date(NaN)])(
    "空值或非法时间 %s 返回占位而不影响页面渲染",
    (input) => {
      expect(formatAdminDateTime(input)).toBe("--");
    }
  );
});
