/** 当前本机工作台的通知、确认和输入状态；仅保存本次启动中的摘要。 */
import { computed, ref } from "vue";
import type { NotificationLevel } from "../types";

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
}
function closeCenter(): void {
  centerOpen.value = false;
}
async function markAllRead(): Promise<void> {
  for (const h of history.value) h.read = true;

}
function clearHistory(): void {
  history.value = [];
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
  };
}
