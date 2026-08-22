/**
 * ui_v2 功能开关（0.4.0 兼容策略）
 *
 * alpha.1：默认兼容页面（v1），新壳需显式开启（?ui=v2 或 localStorage pa_ui_v2=1）；
 * alpha.2：默认新 UI，关闭开关可回退（?ui=v1 或 pa_ui_v2=0）。
 * 开关只影响 renderer 呈现，不改变后端数据与执行路径。
 */
const DEFAULT_UI_V2 = true;

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

/**
 * v0.8.0 CodingWorkbench 内部启用开关（W0 冻结 §5）
 *
 * 不是 ui_v3 版本开关：新代码只落在 features/coding/；开关只切换 renderer
 * 的侧栏与主区（AppShell rail 换 CodingSidebar），不改变后端执行与数据。
 * 内部启用（默认关闭）：?coding=1 或 localStorage pa_coding_workbench=1；
 * 旧壳回退入口（?ui=v1 / pa_ui_v2=0）不受影响。
 */
export function isCodingWorkbench(): boolean {
  const param = new URLSearchParams(window.location.search).get("coding");
  if (param === "1") return true;
  if (param === "0") return false;
  return window.localStorage.getItem("pa_coding_workbench") === "1";
}
