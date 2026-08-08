/**
 * ui_v2 功能开关（0.4.0 兼容策略）
 *
 * alpha.1：默认兼容页面（v1），新壳需显式开启（?ui=v2 或 localStorage pa_ui_v2=1）；
 * alpha.2：默认新 UI，关闭开关可回退（?ui=v1 或 pa_ui_v2=0）。
 * 开关只影响 renderer 呈现，不改变后端数据与执行路径。
 */
const DEFAULT_UI_V2 = false;

export type UiMode = "v1" | "v2";

export function uiMode(): UiMode {
  const param = new URLSearchParams(window.location.search).get("ui");
  if (param === "v2") return "v2";
  if (param === "v1") return "v1";
  const stored = window.localStorage.getItem("pa_ui_v2");
  if (stored === "1") return "v2";
  if (stored === "0") return "v1";
  return DEFAULT_UI_V2 ? "v2" : "v1";
}

export function isUiV2(): boolean {
  return uiMode() === "v2";
}
