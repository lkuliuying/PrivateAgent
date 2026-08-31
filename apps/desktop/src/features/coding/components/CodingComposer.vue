<script setup lang="ts">
/**
 * CodingComposer · v0.8.0 W3
 *
 * 多行输入器：Enter 发送/Shift+Enter 换行；`@` 项目文件发现（经注入的
 * searchFiles，API 不进组件）；`/` 命令模板；权限三模式/模型 profile/
 * 推理强度选择（v0.7.0 冻结契约）；上下文 chip；草稿按 thread 本地保存
 * （不跨项目串线）；发送/停止/等待审批禁用态。
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import {
  PhAt,
  PhCommand,
  PhMicrophone,
  PhPaperPlaneRight,
  PhPlus,
  PhProhibit,
  PhShieldCheck,
  PhWaveform,
  PhX,
} from "@phosphor-icons/vue";
import PaSelect from "../../../design/PaSelect.vue";
import ContextUsageRing from "../../agent/ContextUsageRing.vue";
import type { CodingFileHint } from "../model/runContracts";
import { PERMISSION_MODE_META } from "../model/runContracts";
import type { CodingFirstTurnPayload } from "../model/contracts";
import type { CodingWorkspaceStore } from "../model/codingWorkspaceStore";
// v0.9.0 §5.3：full_access 授予查询/撤销 + 有效期显示（产品时区）
import { fetchFullAccessGrant, revokeFullAccessGrant } from "../api/fullAccess";
import { formatDateTime } from "../../../services/timeDisplay";
import { useNotifications } from "../../../stores/notifications";

export interface CodingComposerSendPayload extends CodingFirstTurnPayload {}

const notify = useNotifications();

const props = withDefaults(
  defineProps<{
    store?: CodingWorkspaceStore;
    threadId?: number | null;
    busy?: boolean;
    stopping?: boolean;
    running?: boolean;
    previewMode?: boolean;
    searchFiles?: (query: string) => Promise<CodingFileHint[]>;
    pickAttachment?: () => Promise<CodingFileHint | null>;
    /**
     * v0.9.0 H1-A：发送前守卫（如 full_access 二次确认/授予）。返回 false 时
     * 不发送、不清空输入（不丢失用户草稿），由调用方呈现原因。
     */
    beforeSend?: (payload: CodingComposerSendPayload) => Promise<boolean>;
    /** 当前任务内已提交的用户输入，按时间正序；用于 ↑/↓ 历史导航。 */
    inputHistory?: string[];
    /**
     * v0.9.0 H1-B（计划 §5.5/§5.6）：创建失败留在草稿态——父层把未成功的
     * 输入回填（不丢失输入）；引用变化即应用。
     */
    restoreRequest?: { message: string; seq: number } | null;
  }>(),
  {
    store: undefined,
    threadId: null,
    busy: false,
    stopping: false,
    running: false,
    previewMode: false,
    searchFiles: undefined,
    beforeSend: undefined,
    inputHistory: () => [],
    restoreRequest: null,
  }
);

const emit = defineEmits<{
  send: [payload: CodingComposerSendPayload];
  stop: [];
}>();

// ============ 文本与草稿（按 thread 保存，切换任务互不串线） ============
const text = ref("");
const chips = ref<CodingFileHint[]>([]);
const inputEl = ref<HTMLTextAreaElement | null>(null);
const attaching = ref(false);
let caret = 0;

type ComposerDraft = {
  text: string;
  chips: CodingFileHint[];
};

const historyIndex = ref<number | null>(null);
const historyDraft = ref<ComposerDraft | null>(null);
const availableHistory = computed(() =>
  props.inputHistory.filter((item) => typeof item === "string" && item.trim().length > 0)
);

function resetHistoryNavigation(): void {
  historyIndex.value = null;
  historyDraft.value = null;
}

function draftKey(threadId: number | null): string {
  return `pa_coding_draft_${threadId ?? "none"}`;
}

let restoringDraft = false;

function saveDraft(): void {
  if (props.previewMode || restoringDraft) return;
  try {
    window.localStorage.setItem(
      draftKey(props.threadId),
      JSON.stringify({ text: text.value, chips: chips.value })
    );
  } catch {
    // 本地存储不可用时静默降级（草稿非关键数据）
  }
}

function loadDraft(): void {
  resetHistoryNavigation();
  restoringDraft = true;
  chips.value = [];
  try {
    const raw = window.localStorage.getItem(draftKey(props.threadId));
    if (!raw) {
      text.value = "";
      return;
    }
    const draft = JSON.parse(raw) as { text?: string; chips?: CodingFileHint[] };
    text.value = typeof draft.text === "string" ? draft.text : "";
    chips.value = Array.isArray(draft.chips) ? draft.chips : [];
  } catch {
    text.value = "";
  } finally {
    restoringDraft = false;
  }
}

loadDraft();
watch(() => props.threadId, loadDraft);
// sync：草稿随每次输入立即落盘（不因批量更新时序丢草稿）
watch([text, chips], saveDraft, { flush: "sync" });

// ============ @ 文件发现（列表框键盘可达） ============
const atQuery = ref<string | null>(null);
const atHints = ref<CodingFileHint[]>([]);
const atLoading = ref(false);
const atActive = ref(0);
let atSeq = 0;
let atDebounce: number | null = null;

async function runAtSearch(query: string): Promise<void> {
  const finder = props.searchFiles;
  if (!finder) return;
  const mine = ++atSeq;
  atLoading.value = true;
  try {
    const hints = await finder(query);
    if (mine === atSeq) {
      atHints.value = hints;
      atActive.value = 0;
    }
  } catch {
    if (mine === atSeq) atHints.value = [];
  } finally {
    if (mine === atSeq) atLoading.value = false;
  }
}

function detectAtMention(value: string, position: number): string | null {
  const before = value.slice(0, position);
  const match = before.match(/(?:^|\s)@([\w./\\-]*)$/);
  return match ? match[1] : null;
}

function onInput(event: Event): void {
  const target = event.target as HTMLTextAreaElement;
  resetHistoryNavigation();
  caret = target.selectionStart ?? target.value.length;
  const mention = detectAtMention(target.value, caret);
  atQuery.value = mention;
  slashQuery.value = /^\/([\w-]*)$/.exec(target.value.slice(0, caret)) ? target.value.slice(1, caret) : null;
  if (mention !== null && props.searchFiles) {
    if (atDebounce !== null) window.clearTimeout(atDebounce);
    atDebounce = window.setTimeout(() => {
      atDebounce = null;
      void runAtSearch(mention);
    }, 180);
  }
}

function applyAtHint(hint: CodingFileHint): void {
  if (atQuery.value === null) return;
  const before = text.value.slice(0, caret);
  const after = text.value.slice(caret);
  const replaced = before.replace(/@([\w./\\-]*)$/, "") + after;
  text.value = replaced.trimStart();
  if (!chips.value.some((item) => item.relPath === hint.relPath)) {
    chips.value = [...chips.value, hint];
  }
  atQuery.value = null;
  inputEl.value?.focus();
}

async function openContextPicker(): Promise<void> {
  if (props.busy || props.previewMode) return;
  if (props.pickAttachment) {
    if (attaching.value) return;
    attaching.value = true;
    try {
      const attachment = await props.pickAttachment();
      if (
        attachment &&
        !chips.value.some((item) => item.relPath === attachment.relPath)
      ) {
        chips.value = [...chips.value, attachment];
      }
    } catch (error) {
      notify.error("文件添加失败", errorText(error));
    } finally {
      attaching.value = false;
    }
    return;
  }
  const input = inputEl.value;
  const position = input?.selectionStart ?? text.value.length;
  const before = text.value.slice(0, position);
  const after = text.value.slice(position);
  const prefix = before && !/\s$/.test(before) ? " @" : "@";
  text.value = `${before}${prefix}${after}`;
  caret = position + prefix.length;
  atQuery.value = "";
  atHints.value = [];
  slashQuery.value = null;
  await nextTick();
  inputEl.value?.focus();
  inputEl.value?.setSelectionRange(caret, caret);
  if (props.searchFiles) void runAtSearch("");
}

function errorText(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return String(error);
}

function removeChip(relPath: string): void {
  chips.value = chips.value.filter((item) => item.relPath !== relPath);
}

// ============ / 命令模板 ============
const COMMAND_TEMPLATES: Array<{ cmd: string; label: string; prompt: string }> = [
  { cmd: "/explain", label: "解释项目结构", prompt: "梳理当前项目的目录结构，并总结每个主要模块的职责与依赖关系。" },
  { cmd: "/fix-test", label: "修复失败测试", prompt: "找出当前失败的测试，定位原因并修复，最后运行相关测试验证。" },
  { cmd: "/review", label: "审查最近改动", prompt: "审查最近一次提交的改动，指出潜在风险与改进建议。" },
  { cmd: "/test", label: "补充单元测试", prompt: "为当前模块补充单元测试，覆盖主要分支与边界情况。" },
];

const slashQuery = ref<string | null>(null);
const slashMatches = computed(() => {
  const query = slashQuery.value;
  if (query === null) return [];
  return COMMAND_TEMPLATES.filter((item) => item.cmd.startsWith(`/${query}`));
});

function applyCommand(prompt: string): void {
  text.value = prompt;
  slashQuery.value = null;
  inputEl.value?.focus();
}

// ============ 权限/模型/推理（v0.7.0 冻结契约） ============
// v0.9.0 H1（计划 §3.1）：产品默认权限为 confirm（不是 workspace/readonly）；
// 服务端未显式指定时仍按最小权限 readonly 失败关闭（后端语义不变）。
// v0.9.0 H1-C（计划 §5.7）：权限选择按会话（thread）持久化，切换对话不丢；
// 只存合法枚举值，能力位不可用时回落 confirm（不静默使用更高权限）。
const PERMISSION_MODE_KEYS = ["readonly", "confirm", "workspace", "full_access"];

function permissionKey(threadId: number | null): string {
  return `pa_coding_permission_${threadId ?? "none"}`;
}

function loadPermissionMode(): string {
  try {
    const stored = window.localStorage.getItem(permissionKey(props.threadId));
    if (stored && PERMISSION_MODE_KEYS.includes(stored)) return stored;
  } catch {
    // 本地存储不可用时静默回落默认值（权限选择非关键数据）
  }
  return "confirm";
}

const permissionMode = ref(loadPermissionMode());
watch(() => props.threadId, () => {
  permissionMode.value = loadPermissionMode();
});
watch(permissionMode, () => {
  if (props.previewMode) return;
  try {
    window.localStorage.setItem(permissionKey(props.threadId), permissionMode.value);
  } catch {
    // 同上：存储不可用时不阻断交互
  }
});
const modelProfileId = ref("");
const reasoningEffort = ref("");

// v0.9.0 H1-A（计划 §5.3）：三档权限选项可用性绑定后端能力位——
// workspace/full_access 仅在 /capabilities 显式声明时可选；能力位缺失时
// 选项置灰说明，不在前端扩大授权（零容忍）。
const workspaceAutoApproveSupported = computed(
  () => props.store?.capabilities.value?.coding_workspace_auto_approve === true
);
// §5.3：审计/撤销独立声明——能力位开启但审计或撤销被显式声明不可用时失败关闭。
const fullAccessSupported = computed(() => {
  const caps = props.store?.capabilities.value;
  return (
    caps?.coding_full_access_supported === true &&
    caps?.coding_full_access_audit !== false &&
    caps?.coding_full_access_revoke !== false
  );
});
const contextBudgetEnabled = computed(
  () => props.store?.capabilities.value?.coding_context_budget_enabled === true
);

const permissionOptions = computed(() => [
  { value: "readonly", label: PERMISSION_MODE_META.readonly.label },
  { value: "confirm", label: PERMISSION_MODE_META.confirm.label },
  {
    value: "workspace",
    // v0.9.0 H1-C（§5.7）：不可用选项必须在项旁说明具体原因，禁止无响应项。
    label: workspaceAutoApproveSupported.value
      ? PERMISSION_MODE_META.workspace.label
      : `${PERMISSION_MODE_META.workspace.label}（不可用：Runtime 未提供自动批准能力）`,
    disabled: !workspaceAutoApproveSupported.value,
  },
  {
    value: "full_access",
    label: fullAccessSupported.value
      ? PERMISSION_MODE_META.full_access.label
      : `${PERMISSION_MODE_META.full_access.label}（不可用：Runtime 未提供完全访问能力）`,
    disabled: !fullAccessSupported.value,
  },
]);

// 能力位变化导致当前选择不可用时回落 confirm（不静默使用更高权限）
watch([workspaceAutoApproveSupported, fullAccessSupported], () => {
  if (permissionMode.value === "workspace" && !workspaceAutoApproveSupported.value) {
    permissionMode.value = "confirm";
  }
  if (permissionMode.value === "full_access" && !fullAccessSupported.value) {
    permissionMode.value = "confirm";
  }
});

// v0.9.0 §5.3：full_access 授予状态与即时撤销（threadId 即会话 id）
const activeGrant = ref<{ grantId: string; expiresAt: string | null } | null>(null);
const revoking = ref(false);
let grantRequestSequence = 0;

async function refreshGrantState(): Promise<void> {
  const sequence = ++grantRequestSequence;
  if (permissionMode.value !== "full_access" || props.threadId === null) {
    activeGrant.value = null;
    return;
  }
  try {
    const state = await fetchFullAccessGrant(props.threadId);
    if (sequence !== grantRequestSequence) return;
    activeGrant.value =
      state.active && state.grantId
        ? { grantId: state.grantId, expiresAt: state.expiresAt }
        : null;
  } catch {
    if (sequence !== grantRequestSequence) return;
    activeGrant.value = null;
  }
}

watch(
  [() => props.threadId, permissionMode, () => props.busy],
  () => void refreshGrantState(),
  { immediate: true }
);

async function onRevokeFullAccess(): Promise<void> {
  const grant = activeGrant.value;
  if (!grant || revoking.value) return;
  const confirmed = await notify.confirm({
    title: "撤销当前会话的完全访问？",
    impact: "撤销后写入与命令将恢复逐次确认。",
    confirmLabel: "撤销访问",
  });
  if (!confirmed) return;
  revoking.value = true;
  try {
    if (!await revokeFullAccessGrant(grant.grantId)) throw new Error("撤销响应无效");
    activeGrant.value = null;
    permissionMode.value = "confirm";
  } catch {
    notify.error("完全访问未确认撤销，请重试；必要时退出客户端以停止任务");
  } finally {
    revoking.value = false;
  }
}
const profiles = computed(() => {
  const result = props.store?.modelProfiles.value;
  return result?.status === "ok" ? result.profiles : [];
});

const defaultProfile = computed(
  () => profiles.value.find((profile) => profile.isDefault) ?? profiles.value[0] ?? null
);

const profileOptions = computed(() => [
  {
    value: "",
    label: defaultProfile.value
      ? `默认 · ${defaultProfile.value.modelName?.trim() || defaultProfile.value.id}`
      : "默认模型",
  },
  ...profiles.value.map((profile) => ({
    value: profile.id,
    label: profile.providerName
      ? `${profile.providerName} / ${profile.modelName?.trim() || profile.id}`
      : profile.modelName?.trim() || profile.id,
  })),
]);

const selectedProfile = computed(
  () =>
    profiles.value.find((profile) => profile.id === modelProfileId.value) ??
    defaultProfile.value
);

const effortOptions = computed(() => {
  const declared = selectedProfile.value?.reasoningEfforts;
  const efforts = declared?.length ? declared : ["low", "medium", "high", "max"];
  const labels: Record<string, string> = {
    none: "不启用推理",
    minimal: "最低",
    low: "低",
    medium: "中",
    high: "高",
    xhigh: "最高",
    max: "最高",
  };
  return [
    { value: "", label: "默认强度" },
    ...efforts.map((item) => ({ value: item, label: labels[item] ?? "自定义强度" })),
  ];
});

watch(profiles, () => {
  if (modelProfileId.value && !profiles.value.some((p) => p.id === modelProfileId.value)) {
    modelProfileId.value = "";
    reasoningEffort.value = "";
  }
});

watch(selectedProfile, () => {
  const values = effortOptions.value.map((item) => item.value);
  if (reasoningEffort.value && !values.includes(reasoningEffort.value)) {
    reasoningEffort.value = "";
  }
});

// ============ 发送/停止 ============
const disabled = computed(() => props.busy || props.previewMode || !buildMessage().trim());

function buildMessage(): string {
  const chipLines = chips.value.map((chip) => `@${chip.relPath}`);
  return [text.value.trim(), ...chipLines].filter(Boolean).join("\n");
}

async function send(): Promise<void> {
  if (disabled.value) return;
  const payload: CodingComposerSendPayload = {
    message: buildMessage(),
    permissionMode: permissionMode.value,
    // “默认”也是一个确定的 Profile。提交实际 ID，避免后端在默认项缺失或
    // 旧配置残留时退回到与界面显示不一致的 legacy 模型。
    modelProfileId: selectedProfile.value?.id ?? null,
    reasoningEffort: reasoningEffort.value || null,
  };
  // v0.9.0 H1-A：发送前守卫（full_access 二次确认/授予）。返回 false 时
  // 不发送、不清空草稿，避免丢失用户输入。
  if (props.beforeSend) {
    const proceed = await props.beforeSend(payload);
    if (!proceed) return;
    await refreshGrantState();
  }
  emit("send", payload);
  resetHistoryNavigation();
  text.value = "";
  chips.value = [];
  atQuery.value = null;
  slashQuery.value = null;
}

function onPrimaryAction(): void {
  if (!buildMessage().trim()) {
    inputEl.value?.focus();
    return;
  }
  void send();
}

// message 末尾的 @relPath 行还原为 chip（与 buildMessage 序列化互逆）。
// 历史浏览不覆盖用户已经持久化的草稿；创建失败回填则正常落盘。
function applySerializedMessage(message: string, persistAsDraft: boolean): void {
  const lines = message.split("\n");
  const restoredChips: CodingFileHint[] = [];
  const textLines: string[] = [];
  for (const line of lines) {
    const chipMatch = /^@([\w./\\-]+)$/.exec(line.trim());
    if (chipMatch) {
      const relPath = chipMatch[1];
      const name = relPath.split(/[\\/]/).pop() ?? relPath;
      restoredChips.push({ relPath, name, language: null });
    } else if (line.trim()) {
      textLines.push(line);
    }
  }
  if (!persistAsDraft) restoringDraft = true;
  text.value = textLines.join("\n");
  chips.value = restoredChips;
  if (!persistAsDraft) restoringDraft = false;
  atQuery.value = null;
  slashQuery.value = null;
  void nextTick(() => {
    const input = inputEl.value;
    if (!input) return;
    input.focus();
    const end = input.value.length;
    input.setSelectionRange(end, end);
    caret = end;
  });
}

// v0.9.0 H1-B（§5.5）：创建失败留在草稿态——父层回填未成功的输入。
watch(
  () => props.restoreRequest,
  (request) => {
    if (!request) return;
    resetHistoryNavigation();
    applySerializedMessage(request.message, true);
  }
);

function isOnFirstLine(input: HTMLTextAreaElement): boolean {
  if (input.selectionStart !== input.selectionEnd) return false;
  return !input.value.slice(0, input.selectionStart).includes("\n");
}

function isOnLastLine(input: HTMLTextAreaElement): boolean {
  if (input.selectionStart !== input.selectionEnd) return false;
  return !input.value.slice(input.selectionEnd).includes("\n");
}

/**
 * 采用终端式历史导航：单行输入任意光标位置均可切换；多行输入仅在首行 ↑、
 * 末行 ↓ 时切换，避免抢占正常的纵向光标移动。浏览到最新一项后恢复原草稿。
 */
function navigateInputHistory(event: KeyboardEvent): boolean {
  if (
    (event.key !== "ArrowUp" && event.key !== "ArrowDown") ||
    event.altKey ||
    event.ctrlKey ||
    event.metaKey ||
    event.shiftKey ||
    atQuery.value !== null ||
    slashQuery.value !== null
  ) {
    return false;
  }
  const input = inputEl.value;
  const history = availableHistory.value;
  if (!input || history.length === 0) return false;

  if (event.key === "ArrowUp") {
    if (!isOnFirstLine(input)) return false;
    if (historyIndex.value === null) {
      historyDraft.value = { text: text.value, chips: [...chips.value] };
      historyIndex.value = history.length - 1;
    } else if (historyIndex.value > 0) {
      historyIndex.value -= 1;
    }
    event.preventDefault();
    applySerializedMessage(history[historyIndex.value], false);
    return true;
  }

  if (historyIndex.value === null || !isOnLastLine(input)) return false;
  event.preventDefault();
  if (historyIndex.value < history.length - 1) {
    historyIndex.value += 1;
    applySerializedMessage(history[historyIndex.value], false);
  } else {
    const draft = historyDraft.value ?? { text: "", chips: [] };
    restoringDraft = true;
    text.value = draft.text;
    chips.value = [...draft.chips];
    restoringDraft = false;
    resetHistoryNavigation();
    atQuery.value = null;
    slashQuery.value = null;
    void nextTick(() => {
      const current = inputEl.value;
      if (!current) return;
      current.focus();
      const end = current.value.length;
      current.setSelectionRange(end, end);
      caret = end;
    });
  }
  return true;
}

function onKeydown(event: KeyboardEvent): void {
  if (atQuery.value !== null && atHints.value.length) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      atActive.value = (atActive.value + 1) % atHints.value.length;
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      atActive.value = (atActive.value - 1 + atHints.value.length) % atHints.value.length;
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      applyAtHint(atHints.value[atActive.value]);
      return;
    }
    if (event.key === "Escape") {
      atQuery.value = null;
      return;
    }
  }
  if (navigateInputHistory(event)) return;
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void send();
  }
}

onBeforeUnmount(() => {
  if (atDebounce !== null) window.clearTimeout(atDebounce);
});
</script>

<template>
  <div class="coding-composer" data-testid="coding-composer">
    <div v-if="chips.length" class="chip-row" data-testid="composer-chips">
      <span v-for="chip in chips" :key="chip.relPath" class="chip">
        <PhAt :size="12" aria-hidden="true" />
        <span class="mono">{{ chip.relPath }}</span>
        <button class="chip-remove" :aria-label="`移除 ${chip.relPath}`" @click="removeChip(chip.relPath)">
          <PhX :size="11" />
        </button>
      </span>
    </div>

    <textarea
      ref="inputEl"
      v-model="text"
      class="composer-input"
      data-testid="coding-composer-input"
      rows="2"
      :disabled="busy || previewMode"
      aria-label="任务输入"
      :placeholder="previewMode ? '预览模式' : busy ? '任务执行中…' : '随心输入'"
      @input="onInput"
      @keydown="onKeydown"
    />

    <!-- @ 文件发现列表框 -->
    <div
      v-if="atQuery !== null"
      class="mention-pop"
      data-testid="composer-at-pop"
      role="listbox"
      aria-label="项目文件"
    >
      <div v-if="atLoading" class="pop-hint">搜索中…</div>
      <div v-else-if="!atHints.length" class="pop-hint">无匹配文件</div>
      <button
        v-for="(hint, index) in atHints"
        :key="hint.relPath"
        class="pop-item"
        role="option"
        :aria-selected="index === atActive"
        :data-testid="`composer-at-item-${index}`"
        @click="applyAtHint(hint)"
        @mousemove="atActive = index"
      >
        <PhAt :size="12" aria-hidden="true" />
        <span class="mono pop-path">{{ hint.relPath }}</span>
        <small v-if="hint.language">{{ hint.language }}</small>
      </button>
    </div>

    <!-- / 命令模板列表框 -->
    <div
      v-if="slashQuery !== null && slashMatches.length"
      class="mention-pop slash"
      data-testid="composer-slash-pop"
      role="listbox"
      aria-label="命令模板"
    >
      <button
        v-for="item in slashMatches"
        :key="item.cmd"
        class="pop-item"
        role="option"
        :aria-selected="false"
        :data-testid="`composer-slash-${item.cmd.slice(1)}`"
        @click="applyCommand(item.prompt)"
      >
        <PhCommand :size="12" aria-hidden="true" />
        <span class="mono pop-cmd">{{ item.cmd }}</span>
        <small>{{ item.label }}</small>
      </button>
    </div>

    <div class="composer-toolbar">
      <div class="toolbar-group toolbar-left">
        <button
          type="button"
          class="composer-icon-btn add-context"
          data-testid="composer-add-context"
          :disabled="busy || previewMode || attaching"
          :title="pickAttachment ? '从本机添加文件' : '引用项目文件'"
          :aria-label="pickAttachment ? '从本机添加文件' : '引用项目文件'"
          @click="void openContextPicker()"
        >
          <PhPlus :size="20" aria-hidden="true" />
        </button>

        <label class="toolbar-select permission-select">
          <span class="visually-hidden">权限</span>
          <PhShieldCheck :size="17" aria-hidden="true" />
          <PaSelect
            :model-value="permissionMode"
            :options="permissionOptions"
            size="sm"
            data-testid="composer-permission"
            aria-label="权限模式"
            :title="PERMISSION_MODE_META[permissionMode]?.hint"
            @update:model-value="permissionMode = String($event)"
          />
        </label>

        <!-- v0.9.0 §5.3：full_access 授予状态与即时撤销（显示有效期，可一键撤销） -->
        <button
          v-if="activeGrant"
          type="button"
          class="grant-revoke"
          data-testid="composer-grant-revoke"
          :disabled="revoking"
          :title="activeGrant.expiresAt ? `有效期至 ${formatDateTime(activeGrant.expiresAt)}；点击撤销` : '点击撤销完全访问'"
          @click="void onRevokeFullAccess()"
        >
          完全访问 · 撤销
        </button>
      </div>

      <div class="toolbar-group toolbar-right">
        <label class="toolbar-select model-select">
          <span class="visually-hidden">模型</span>
          <PaSelect
            :model-value="modelProfileId"
            :options="profileOptions"
            :disabled="!profiles.length"
            size="sm"
            data-testid="composer-model"
            aria-label="模型"
            @update:model-value="modelProfileId = String($event)"
          />
        </label>
        <label class="toolbar-select effort-select">
          <span class="visually-hidden">推理强度</span>
          <PaSelect
            :model-value="reasoningEffort"
            :options="effortOptions"
            :disabled="!selectedProfile"
            size="sm"
            data-testid="composer-effort"
            aria-label="推理强度"
            @update:model-value="reasoningEffort = String($event)"
          />
        </label>
        <ContextUsageRing
          v-if="threadId !== null"
          class="composer-context-ring"
          :session-id="threadId"
          :model-profile-id="selectedProfile?.id ?? null"
          :enabled="contextBudgetEnabled"
        />
        <button
          type="button"
          class="composer-icon-btn voice-input"
          disabled
          title="语音输入将在后续版本开放"
          aria-label="语音输入暂不可用"
        >
          <PhMicrophone :size="20" aria-hidden="true" />
        </button>
        <button
          v-if="!running"
          type="button"
          class="pa-btn pa-btn--primary pa-btn--sm composer-send"
          data-testid="coding-composer-send"
          :disabled="busy || previewMode"
          :title="buildMessage().trim() ? '发送任务' : '输入内容后发送'"
          :aria-label="buildMessage().trim() ? '发送任务' : '输入内容后发送'"
          @click="onPrimaryAction"
        >
          <PhPaperPlaneRight v-if="buildMessage().trim()" :size="18" weight="fill" aria-hidden="true" />
          <PhWaveform v-else :size="20" weight="bold" aria-hidden="true" />
        </button>
        <button
          v-else
          type="button"
          class="pa-btn pa-btn--ghost pa-btn--sm composer-stop"
          data-testid="coding-composer-stop"
          :disabled="stopping"
          :title="stopping ? '正在停止任务' : '停止任务'"
          :aria-label="stopping ? '正在停止任务' : '停止任务'"
          @click="emit('stop')"
        >
          <PhProhibit :size="19" weight="bold" aria-hidden="true" />
        </button>
      </div>
      <span class="visually-hidden">Enter 发送，Shift+Enter 换行，上下键浏览历史输入</span>
    </div>
  </div>
</template>

<style scoped>
.coding-composer {
  position: relative;
  display: flex;
  min-height: 124px;
  box-sizing: border-box;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4) var(--space-2);
  border: 1px solid color-mix(in srgb, var(--color-fg) 12%, transparent);
  border-radius: calc(var(--radius-lg) + var(--space-2));
  background: var(--color-surface);
  box-shadow: var(--shadow);
  transition: border-color var(--pa-motion-fast) var(--ease),
    box-shadow var(--pa-motion-fast) var(--ease);
}
.coding-composer:focus-within {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow), var(--pa-input-ring);
}
.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  max-width: 100%;
  padding: 2px var(--space-2);
  border: 1px solid color-mix(in srgb, var(--color-accent) 32%, var(--color-border));
  border-radius: var(--radius-full);
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
  font-size: var(--pa-text-meta);
}
.chip .mono {
  overflow: hidden;
  max-width: 260px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chip-remove {
  display: inline-flex;
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  padding: 0;
}
.composer-input {
  flex: 1;
  width: 100%;
  min-width: 0;
  min-height: 52px;
  max-height: 144px;
  box-sizing: border-box;
  resize: none;
  padding: 2px 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--color-fg);
  font-size: var(--pa-text-body);
  font-family: inherit;
  line-height: var(--leading-normal);
}
.composer-input:focus-visible {
  outline: none;
}
.composer-input:disabled {
  color: var(--color-fg-subtle);
}
.composer-input::placeholder {
  color: var(--color-fg-faint);
  font-size: var(--text-lg);
}
.composer-toolbar {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.toolbar-group {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-1);
}
.toolbar-right {
  justify-content: flex-end;
  margin-left: auto;
}
.composer-icon-btn {
  display: inline-flex;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--color-fg-muted);
  cursor: pointer;
}
.composer-icon-btn:not(:disabled):hover {
  background: var(--color-surface-hover);
  color: var(--color-fg);
}
.composer-icon-btn:focus-visible {
  outline: var(--focus-ring);
  outline-offset: 1px;
}
.composer-icon-btn:disabled {
  color: var(--color-fg-faint);
  cursor: not-allowed;
}
.voice-input:disabled {
  color: var(--color-fg);
  opacity: 1;
}
.toolbar-select {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 2px;
  color: var(--color-fg-muted);
}
.toolbar-select :deep(.pa-select) {
  height: 30px;
  padding: 0 22px 0 var(--space-1);
  border: 0;
  background-color: transparent;
  color: var(--color-fg);
  font-size: var(--pa-text-body);
  box-shadow: none;
}
.toolbar-select :deep(.pa-select:hover:not(:disabled)) {
  background-color: var(--color-surface-hover);
}
.toolbar-select :deep(.pa-select:focus) {
  box-shadow: var(--focus-ring);
}
.permission-select :deep(.pa-select) {
  width: 118px;
}
.model-select :deep(.pa-select) {
  width: 148px;
}
.effort-select :deep(.pa-select) {
  width: 94px;
}
.composer-send,
.composer-stop {
  display: inline-flex;
  width: 36px;
  height: 36px;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  flex-shrink: 0;
  min-height: 36px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-full);
  background: var(--color-fg);
  color: var(--color-surface);
  box-shadow: none;
}
.composer-send:hover:not(:disabled),
.composer-stop:hover:not(:disabled) {
  background: var(--color-fg-muted);
  color: var(--color-surface);
}
.composer-send:disabled,
.composer-stop:disabled {
  background: var(--color-fg);
  color: var(--color-surface);
  opacity: 0.42;
}
.composer-stop {
  background: var(--color-danger-strong);
  color: var(--color-surface);
}
.mention-pop {
  position: absolute;
  bottom: calc(100% + var(--space-2));
  left: var(--space-3);
  z-index: var(--z-raised);
  display: flex;
  width: min(440px, 100%);
  max-height: 240px;
  overflow-y: auto;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-1);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-lg);
}
.pop-hint {
  padding: var(--space-2);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.pop-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  padding: var(--space-1) var(--space-2);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-fg);
  font-size: var(--pa-text-meta);
  text-align: left;
  cursor: pointer;
}
.pop-item[aria-selected="true"],
.pop-item:hover {
  background: var(--color-surface-muted);
}
.pop-path {
  overflow: hidden;
  min-width: 0;
  flex: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pop-cmd {
  flex-shrink: 0;
}
.pop-item small {
  color: var(--color-fg-subtle);
}
.composer-context-ring {
  margin: 0 var(--space-1);
}
/* v0.9.0 §5.3：full_access 授予状态与撤销入口 */
.grant-revoke {
  display: inline-flex;
  align-items: center;
  height: 28px;
  padding: 0 var(--space-2);
  border: 1px solid color-mix(in srgb, var(--color-warning) 45%, var(--color-border));
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-warning) 12%, transparent);
  color: var(--color-warning-fg);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.grant-revoke:hover {
  border-color: var(--color-warning);
}
.grant-revoke:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
@media (max-width: 1080px) {
  .model-select :deep(.pa-select) {
    width: 126px;
  }
  .permission-select :deep(.pa-select) {
    width: 104px;
  }
  .effort-select :deep(.pa-select) {
    width: 82px;
  }
}
@media (max-width: 920px) {
  .coding-composer {
    padding-inline: var(--space-3);
  }
  .composer-toolbar {
    gap: var(--space-1);
  }
  .toolbar-group {
    gap: 0;
  }
}
</style>
