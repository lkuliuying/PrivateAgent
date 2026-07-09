/**
 * 统一通知 store（第七阶段 M4 基建）。
 *
 * 设计取舍：项目一贯极简依赖（无 router/pinia），这里采用模块级响应式单例，
 * 任意组件 `import { useNotifications }` 共享同一实例，无需注册插件。
 * 提供：
 * - toast 队列（ToastHost 渲染，自动消失，error/warning 默认常驻）。
 * - 危险操作确认（promise-based，替代 window.confirm，ConfirmDialog 渲染）。
 * - 历史记录（NotificationCenter 回看；M4 接入 app_notifications 后以 DB 为准合并）。
 *
 * 通知只保存摘要，不保存敏感正文（聊天全文/文档原文/敏感记忆）。
 */
import { computed, ref } from "vue";
import type { NotificationLevel } from "../types";
import { listNotifications, readAllNotifications } from "../api";

export interface ToastAction {
  label: string;
  run: () => void;
}

export interface Toast {
  id: number;
  level: NotificationLevel;
  title: string;
  message?: string;
  timeout: number; // 0 = 常驻，需手动关闭
  action?: ToastAction;
}

export interface ConfirmOptions {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** 危险操作（删除/恢复/命令/补丁）置 true，确认按钮走 danger 色。 */
  danger?: boolean;
  /** 影响范围描述（M4 要求危险操作显示影响范围与撤销/恢复路径）。 */
  impact?: string;
}

export interface PromptOptions {
  title: string;
  message?: string;
  placeholder?: string;
  defaultValue?: string;
  confirmLabel?: string;
  cancelLabel?: string;
}

export interface HistoryEntry {
  id: number;
  level: NotificationLevel;
  kind: string;
  title: string;
  message?: string;
  source_type?: string;
  source_id?: number;
  created_at: string; // ISO
  read: boolean;
}

export interface PushOptions {
  timeout?: number;
  action?: ToastAction;
  kind?: string;
  source_type?: string;
  source_id?: number;
}

// ---- 模块级单例状态 ----
const toasts = ref<Toast[]>([]);
const history = ref<HistoryEntry[]>([]);
const centerOpen = ref(false);
const confirmState = ref<{
  open: boolean;
  opts: ConfirmOptions;
  resolve: ((v: boolean) => void) | null;
}>({ open: false, opts: { title: "" }, resolve: null });

const promptState = ref<{
  open: boolean;
  opts: PromptOptions;
  resolve: ((v: string | null) => void) | null;
}>({ open: false, opts: { title: "" }, resolve: null });

let nextId = 1;

function nowIso(): string {
  return new Date().toISOString();
}

function push(
  level: NotificationLevel,
  title: string,
  message?: string,
  opts?: PushOptions
): number {
  const id = nextId++;
  const kind = opts?.kind ?? level;
  // error/warning 默认常驻（需用户关注），info/success 自动消失。
  const timeout =
    opts?.timeout ?? (level === "error" || level === "warning" ? 0 : 4500);
  toasts.value.push({ id, level, title, message, timeout, action: opts?.action });
  // 同步入历史，供通知中心回看。
  history.value.unshift({
    id,
    level,
    kind,
    title,
    message,
    source_type: opts?.source_type,
    source_id: opts?.source_id,
    created_at: nowIso(),
    read: false,
  });
  if (history.value.length > 200) history.value.length = 200;
  if (timeout > 0) window.setTimeout(() => dismiss(id), timeout);
  return id;
}

const info = (t: string, m?: string, opts?: PushOptions) => push("info", t, m, opts);
const success = (t: string, m?: string, opts?: PushOptions) =>
  push("success", t, m, opts);
const warning = (t: string, m?: string, opts?: PushOptions) =>
  push("warning", t, m, opts);
const error = (t: string, m?: string, opts?: PushOptions) =>
  push("error", t, m, opts);

function dismiss(id: number): void {
  const i = toasts.value.findIndex((x) => x.id === id);
  if (i >= 0) toasts.value.splice(i, 1);
}

function clearToasts(): void {
  toasts.value = [];
}

/** 危险/重要操作确认（promise-based，替代同步 window.confirm）。 */
function confirm(opts: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    confirmState.value = { open: true, opts, resolve };
  });
}

function resolveConfirm(ok: boolean): void {
  confirmState.value.resolve?.(ok);
  confirmState.value = { open: false, opts: { title: "" }, resolve: null };
}

/** 输入对话框（替代同步 window.prompt）。返回输入值或 null（取消）。 */
function prompt(opts: PromptOptions): Promise<string | null> {
  return new Promise((resolve) => {
    promptState.value = { open: true, opts, resolve };
  });
}

function resolvePrompt(value: string | null): void {
  promptState.value.resolve?.(value);
  promptState.value = { open: false, opts: { title: "" }, resolve: null };
}

function openCenter(): void {
  centerOpen.value = true;
  void loadPersisted();
}
function closeCenter(): void {
  centerOpen.value = false;
}
async function markAllRead(): Promise<void> {
  for (const h of history.value) h.read = true;
  try {
    await readAllNotifications();
  } catch {
    // 后端不可用时仅标记内存
  }
}
function clearHistory(): void {
  history.value = [];
}

/** 从后端拉取持久化通知（导入/备份等异步结果），合并入历史。
 * 后端条目用负 id 区分（避免与内存正 id 冲突），按时间倒序合并。 */
async function loadPersisted(): Promise<void> {
  try {
    const items = await listNotifications({ limit: 100 });
    // 移除旧的后端条目（id < 0），保留内存条目（id > 0）
    const mem = history.value.filter((h) => h.id > 0);
    const backend: HistoryEntry[] = items.map((n) => ({
      id: -n.id,
      level: n.level,
      kind: n.kind,
      title: n.title,
      message: n.message ?? undefined,
      source_type: n.source_type ?? undefined,
      source_id: n.source_id ?? undefined,
      created_at: n.created_at,
      read: n.status !== "unread",
    }));
    history.value = [...mem, ...backend].sort((a, b) =>
      b.created_at.localeCompare(a.created_at)
    );
    if (history.value.length > 200) history.value.length = 200;
  } catch {
    // 后端未就绪：静默，仅显示内存历史
  }
}

const unreadCount = computed(() => history.value.filter((h) => !h.read).length);

export function useNotifications() {
  return {
    toasts,
    history,
    centerOpen,
    confirmState,
    promptState,
    unreadCount,
    info,
    success,
    warning,
    error,
    push,
    dismiss,
    clearToasts,
    confirm,
    resolveConfirm,
    prompt,
    resolvePrompt,
    openCenter,
    closeCenter,
    markAllRead,
    clearHistory,
    loadPersisted,
  };
}
