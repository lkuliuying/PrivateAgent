export type SettingsSection =
  | "current-model"
  | "provider"
  | "mcp"
  | "profile"
  | "backup"
  | "about";

export type SettingsSectionGroup = "system" | "capabilities" | "application";

export interface SettingsSectionMeta {
  key: SettingsSection;
  index: string;
  label: string;
  description: string;
  group: SettingsSectionGroup;
}

export const SETTINGS_SECTION_GROUPS: Array<{
  key: SettingsSectionGroup;
  label: string;
}> = [
  { key: "system", label: "系统与模型" },
  { key: "capabilities", label: "能力与数据" },
  { key: "application", label: "应用" },
];

export const SETTINGS_SECTIONS: SettingsSectionMeta[] = [
  { key: "current-model", index: "02", label: "当前模型", description: "推理与向量模型", group: "system" },
  { key: "provider", index: "03", label: "模型设置", description: "管理模型供应商与 Ollama 本地参数", group: "system" },
  { key: "mcp", index: "04", label: "MCP 外部能力", description: "联网工具与授权", group: "capabilities" },
  { key: "profile", index: "05", label: "个人资料", description: "头像与账号信息", group: "application" },
  { key: "backup", index: "06", label: "备份与恢复", description: "本地数据安全", group: "application" },
  { key: "about", index: "07", label: "关于与更新", description: "版本与更新", group: "application" },
];

export function settingsSectionMeta(section: SettingsSection): SettingsSectionMeta {
  return SETTINGS_SECTIONS.find((item) => item.key === section) ?? SETTINGS_SECTIONS[0];
}
