/**
 * v0.9.0 H1：Coding UI 本地遥测（全部本地，不外发）
 *
 * 交接包 §2 最小方案：localStorage 计数，供诊断页聚合呈现；
 * 只记低基数计数（回退原因/进入次数），不记会话/项目/路径正文。
 */

const STORAGE_KEY = "pa_coding_ui_telemetry_v1";

export type CodingFallbackReason =
  | "explicit"
  | "capability_disabled"
  | "error";

interface CodingUiTelemetry {
  coding_view_entries: number;
  legacy_view_entries: number;
  fallbacks: Record<CodingFallbackReason, number>;
}

function empty(): CodingUiTelemetry {
  return {
    coding_view_entries: 0,
    legacy_view_entries: 0,
    fallbacks: { explicit: 0, capability_disabled: 0, error: 0 },
  };
}

function load(): CodingUiTelemetry {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return empty();
    const parsed = JSON.parse(raw) as Partial<CodingUiTelemetry>;
    const base = empty();
    return {
      coding_view_entries: Number(parsed.coding_view_entries ?? 0),
      legacy_view_entries: Number(parsed.legacy_view_entries ?? 0),
      fallbacks: { ...base.fallbacks, ...(parsed.fallbacks ?? {}) },
    };
  } catch {
    return empty();
  }
}

function save(state: CodingUiTelemetry): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* 存储不可用时静默放弃（遥测不阻断 UI） */
  }
}

/** 记录一次视图进入计数。 */
export function recordCodingViewEntry(view: "coding" | "legacy"): void {
  const state = load();
  if (view === "coding") state.coding_view_entries += 1;
  else state.legacy_view_entries += 1;
  save(state);
}

/** 记录一次回退旧 UI（原因低基数）。 */
export function recordCodingFallback(reason: CodingFallbackReason): void {
  const state = load();
  state.fallbacks[reason] = (state.fallbacks[reason] ?? 0) + 1;
  save(state);
}

/** 诊断页聚合读取。 */
export function readCodingUiTelemetry(): CodingUiTelemetry {
  return load();
}
