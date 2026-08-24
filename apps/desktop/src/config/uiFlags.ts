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
 * v0.9.0 CodingWorkbench 默认切换（计划 §3.1 / H1 任务 1）
 *
 * - 新安装/升级默认显示 Coding Home（DEFAULT_CODING_WORKBENCH=true）；
 * - 显式回退键常驻：?coding=0 或 localStorage pa_coding_workbench=0；
 * - 后端能力位回退：/capabilities.coding_agent_ui_enabled === false
 *   （PA_CODING_AGENT_UI_ENABLED=false 短期回退）→ 非显式开启时回落旧 UI；
 * - 开关只切 renderer 的侧栏与主区，不改变后端数据与执行路径；
 * - 旧壳回退入口（?ui=v1 / pa_ui_v2=0）不受影响。
 */
const DEFAULT_CODING_WORKBENCH = true;

/** 后端能力位（启动后注入；null=尚未获取，按默认值呈现）。 */
let codingUiCapability: boolean | null = null;

export function setCodingUiCapability(enabled: boolean): void {
  codingUiCapability = enabled;
}

/** 用户是否显式选择了 coding 开/关（显式选择不被能力位覆盖）。 */
export function hasExplicitCodingChoice(): boolean {
  const param = new URLSearchParams(window.location.search).get("coding");
  if (param === "1" || param === "0") return true;
  const stored = window.localStorage.getItem("pa_coding_workbench");
  return stored === "1" || stored === "0";
}

export function isCodingWorkbench(): boolean {
  const param = new URLSearchParams(window.location.search).get("coding");
  if (param === "1") return true;
  if (param === "0") return false;
  const stored = window.localStorage.getItem("pa_coding_workbench");
  if (stored === "1") return true;
  if (stored === "0") return false;
  // 非显式选择：后端显式声明关闭 → 回退旧 UI（计划 §3.3 短期回退）
  if (codingUiCapability === false) return false;
  return DEFAULT_CODING_WORKBENCH;
}
