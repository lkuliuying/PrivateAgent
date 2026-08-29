export type SettingsSection =
  | "status"
  | "current-model"
  | "model-parameters"
  | "provider"
  | "mcp"
  | "http"
  | "sql"
  | "backup"
  | "connection"
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
  { key: "status", index: "01", label: "运行状态", description: "本地服务连通性", group: "system" },
  { key: "current-model", index: "02", label: "当前模型", description: "推理与向量模型", group: "system" },
  { key: "model-parameters", index: "03", label: "模型参数", description: "温度与上下文", group: "system" },
  { key: "provider", index: "04", label: "模型设置", description: "管理自定义模型供应商，配置后可在聊天时选择使用", group: "system" },
  { key: "mcp", index: "05", label: "MCP 外部能力", description: "工具与授权", group: "capabilities" },
  { key: "http", index: "06", label: "HTTP 端点", description: "可信 API 调用", group: "capabilities" },
  { key: "sql", index: "07", label: "只读数据库", description: "查询连接配置", group: "capabilities" },
  { key: "backup", index: "08", label: "备份与恢复", description: "本地数据安全", group: "application" },
  { key: "connection", index: "09", label: "连接配置", description: "MySQL 与 Ollama", group: "application" },
  { key: "about", index: "10", label: "关于与更新", description: "版本与更新", group: "application" },
];

export function settingsSectionMeta(section: SettingsSection): SettingsSectionMeta {
  return SETTINGS_SECTIONS.find((item) => item.key === section) ?? SETTINGS_SECTIONS[0];
}
