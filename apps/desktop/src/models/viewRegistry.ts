/**
 * 类型化视图注册表（0.4.0 D2）
 *
 * 统一维护：页面名称、图标、导航分组、命令面板关键词、壳行为。
 * 替代 App.vue 中的标题 switch 与 NavRail 内散落的导航数组；
 * 页面定位使用 NavigationTarget 类型化参数，不散落字符串 URL 或 hash。
 */
import type { Component } from "vue";
import {
  PhActivity,
  PhBell,
  PhBooks,
  PhBrain,
  PhChatsCircle,
  PhCode,
  PhDatabase,
  PhFolderSimple,
  PhGearSix,
  PhGraduationCap,
  PhListChecks,
  PhNewspaper,
  PhNotePencil,
  PhPlugs,
  PhPuzzlePiece,
  PhShieldCheck,
  PhSun,
  PhTarget,
  PhTray,
} from "@phosphor-icons/vue";
import type { View } from "../types";

/** 导航分组（D0 冻结，docs/releases/v0.4.0/ui-audit-0.4.0.md §4）；coding 为 v0.8.0 新增、不进入旧 NavRail 分组 */
export type ViewGroup = "daily" | "agent" | "work" | "knowledge" | "connect" | "system" | "coding";

export interface ViewMeta {
  key: View;
  /** 导航/命令面板中的短名 */
  label: string;
  icon: Component;
  group: ViewGroup;
  /** 命令面板搜索关键词 */
  keywords: string[];
  /** 顶部栏行为 */
  showTopbar?: boolean;
  showStatusbar?: boolean;
  /** chat 顶部栏展示任务状态徽标 */
  showsTaskState?: boolean;
}

export const VIEW_GROUP_META: Record<ViewGroup, { label: string }> = {
  daily: { label: "日常" },
  // W6-R3：最近任务随「Agent 执行」分组展示（§4.1）
  agent: { label: "Agent 执行" },
  work: { label: "工作" },
  knowledge: { label: "知识" },
  connect: { label: "连接" },
  system: { label: "系统" },
  coding: { label: "Coding" },
};

export const VIEW_REGISTRY: Record<View, ViewMeta> = {
  coding: {
    key: "coding",
    label: "Coding",
    icon: PhCode,
    group: "coding",
    keywords: ["coding", "代码", "工作台", "项目", "分支", "branch"],
    // v0.8.0 W1：文档式主区（首页/任务页自带头部），不渲染通用顶栏。
    showTopbar: false,
  },
  today: {
    key: "today",
    label: "今日",
    icon: PhSun,
    group: "daily",
    keywords: ["today", "今日", "简报", "待办", "收件箱", "提醒"],
    showTopbar: false,
    showStatusbar: false,
  },
  // v0.8.0 W6-R：今日页六个纵向工作台模块迁入左侧栏独立主区（计划 §4.1/§6.6）
  reminders: {
    key: "reminders",
    label: "提醒",
    icon: PhBell,
    group: "daily",
    keywords: ["reminder", "提醒", "到期", "闹钟", "重复"],
  },
  inbox: {
    key: "inbox",
    label: "收件箱",
    icon: PhTray,
    group: "daily",
    keywords: ["inbox", "收件箱", "待处理", "捕获"],
  },
  goals: {
    key: "goals",
    label: "长期目标",
    icon: PhTarget,
    group: "daily",
    keywords: ["goal", "目标", "长期", "回顾", "checkin"],
  },
  briefings: {
    key: "briefings",
    label: "主动简报",
    icon: PhNewspaper,
    group: "daily",
    keywords: ["briefing", "简报", "今日简报", "周报"],
  },
  capture: {
    key: "capture",
    label: "快速捕获",
    icon: PhNotePencil,
    group: "daily",
    keywords: ["capture", "捕获", "剪贴板", "速记"],
  },
  privacy: {
    key: "privacy",
    label: "隐私与维护",
    icon: PhShieldCheck,
    group: "daily",
    keywords: ["privacy", "隐私", "审计", "维护", "体检"],
  },
  chat: {
    key: "chat",
    label: "Agent",
    icon: PhChatsCircle,
    group: "agent",
    keywords: ["agent", "任务", "对话", "chat", "审批"],
    showsTaskState: true,
  },
  projects: {
    key: "projects",
    label: "项目",
    icon: PhFolderSimple,
    group: "work",
    keywords: ["project", "项目", "目标", "代码"],
  },
  tasks: {
    key: "tasks",
    label: "任务",
    icon: PhListChecks,
    group: "work",
    keywords: ["task", "任务", "目标", "工作区"],
  },
  kb: {
    key: "kb",
    label: "知识库",
    icon: PhBooks,
    group: "knowledge",
    keywords: ["kb", "知识库", "文档", "集合", "搜索"],
  },
  learning: {
    key: "learning",
    label: "学习",
    icon: PhGraduationCap,
    group: "knowledge",
    keywords: ["learning", "学习", "资料"],
  },
  memory: {
    key: "memory",
    label: "记忆",
    icon: PhBrain,
    group: "knowledge",
    keywords: ["memory", "记忆", "draft"],
  },
  integrations: {
    key: "integrations",
    label: "集成",
    icon: PhPlugs,
    group: "connect",
    keywords: ["integration", "集成", "ics", "日历", "导入"],
  },
  extensions: {
    key: "extensions",
    label: "扩展",
    icon: PhPuzzlePiece,
    group: "connect",
    keywords: ["extension", "扩展", "mcp", "server"],
  },
  settings: {
    key: "settings",
    label: "设置",
    icon: PhGearSix,
    group: "system",
    keywords: ["settings", "设置", "状态", "运行状态", "模型", "连接"],
  },
  diagnostics: {
    key: "diagnostics",
    label: "诊断",
    icon: PhActivity,
    group: "system",
    keywords: ["diagnostics", "诊断", "健康", "检查"],
  },
  backup: {
    key: "backup",
    label: "备份",
    icon: PhDatabase,
    group: "system",
    keywords: ["backup", "备份", "恢复", "升级", "更新"],
  },
};

/** 顶部导航分组顺序（系统组固定在底部） */
export const NAV_GROUPS: ViewGroup[] = ["daily", "agent", "work", "knowledge", "connect"];
export const SYSTEM_GROUP: ViewGroup = "system";

/** 服务器级配置与运维入口仅向管理员展示；后端鉴权仍是最终权限边界。 */
export const ADMIN_ONLY_VIEWS = new Set<View>([
  "coding",
  "projects",
  "integrations",
  "extensions",
  "settings",
  "diagnostics",
  "backup",
  "privacy",
]);

export function viewMeta(view: View): ViewMeta {
  return VIEW_REGISTRY[view];
}

export function viewLabel(view: View): string {
  return viewMeta(view).label;
}

export function groupViews(group: ViewGroup): ViewMeta[] {
  return Object.values(VIEW_REGISTRY).filter((meta) => meta.group === group);
}

/** 类型化导航目标：需要定位具体对象时使用，组件不散落字符串 URL。 */
export interface NavigationTarget {
  view: View;
  /** chat 视图定位会话 */
  sessionId?: number;
  /** 未来扩展：页面级定位参数（文档 id、项目 id 等） */
  params?: Record<string, string | number>;
}
