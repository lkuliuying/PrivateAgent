<script setup lang="ts">
/**
 * CodingComposer · v0.8.0 W3
 *
 * 多行输入器：Enter 发送/Shift+Enter 换行；`@` 项目文件发现（经注入的
 * searchFiles，API 不进组件）；`/` 命令模板；权限三模式/模型 profile/
 * 推理强度选择（v0.7.0 冻结契约）；上下文 chip；草稿按 thread 本地保存
 * （不跨项目串线）；发送/停止/等待审批禁用态。
 */
import { computed, onBeforeUnmount, ref, watch } from "vue";
import {
  PhAt,
  PhCommand,
  PhPaperPlaneRight,
  PhProhibit,
  PhX,
} from "@phosphor-icons/vue";
import PaSelect from "../../../design/PaSelect.vue";
import type { CodingFileHint } from "../model/runContracts";
import { PERMISSION_MODE_META } from "../model/runContracts";
import type { CodingWorkspaceStore } from "../model/codingWorkspaceStore";

export interface CodingComposerSendPayload {
  message: string;
  permissionMode: string;
  modelProfileId: string | null;
  reasoningEffort: string | null;
}

const props = withDefaults(
  defineProps<{
    store?: CodingWorkspaceStore;
    threadId?: number | null;
    busy?: boolean;
    stopping?: boolean;
    running?: boolean;
    previewMode?: boolean;
    searchFiles?: (query: string) => Promise<CodingFileHint[]>;
  }>(),
  {
    store: undefined,
    threadId: null,
    busy: false,
    stopping: false,
    running: false,
    previewMode: false,
    searchFiles: undefined,
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
let caret = 0;

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
const permissionMode = ref("readonly");
const modelProfileId = ref("");
const reasoningEffort = ref("");

const profiles = computed(() => {
  const result = props.store?.modelProfiles.value;
  return result?.status === "ok" ? result.profiles : [];
});

const profileOptions = computed(() => [
  { value: "", label: "默认模型" },
  ...profiles.value.map((profile) => ({
    value: profile.id,
    label: `${profile.displayName}${profile.isLocal ? " · 本地" : ""}`,
  })),
]);

const selectedProfile = computed(
  () => profiles.value.find((profile) => profile.id === modelProfileId.value) ?? null
);

const effortOptions = computed(() => {
  const efforts = selectedProfile.value?.reasoningEfforts ?? [];
  return [
    { value: "", label: "默认强度" },
    ...efforts.map((item) => ({ value: item, label: item })),
  ];
});

watch(profiles, () => {
  if (modelProfileId.value && !profiles.value.some((p) => p.id === modelProfileId.value)) {
    modelProfileId.value = "";
    reasoningEffort.value = "";
  }
});

// ============ 发送/停止 ============
const disabled = computed(() => props.busy || props.previewMode || !buildMessage().trim());

function buildMessage(): string {
  const chipLines = chips.value.map((chip) => `@${chip.relPath}`);
  return [text.value.trim(), ...chipLines].filter(Boolean).join("\n");
}

function send(): void {
  if (disabled.value) return;
  const payload: CodingComposerSendPayload = {
    message: buildMessage(),
    permissionMode: permissionMode.value,
    modelProfileId: modelProfileId.value || null,
    reasoningEffort: reasoningEffort.value || null,
  };
  emit("send", payload);
  text.value = "";
  chips.value = [];
  atQuery.value = null;
  slashQuery.value = null;
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
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    send();
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

    <div class="composer-row">
      <textarea
        ref="inputEl"
        v-model="text"
        class="composer-input"
        data-testid="coding-composer-input"
        rows="3"
        :disabled="busy || previewMode"
        aria-label="任务输入"
        :placeholder="
          previewMode ? '预览模式' : busy ? '任务执行中…' : '描述任务（@ 引用文件 · / 命令模板 · Enter 发送）'
        "
        @input="onInput"
        @keydown="onKeydown"
      />
      <button
        v-if="!running"
        class="pa-btn pa-btn--primary composer-send"
        data-testid="coding-composer-send"
        :disabled="disabled"
        @click="send()"
      >
        <PhPaperPlaneRight :size="15" />
        发送
      </button>
      <button
        v-else
        class="pa-btn pa-btn--ghost composer-stop"
        data-testid="coding-composer-stop"
        :disabled="stopping"
        @click="emit('stop')"
      >
        <PhProhibit :size="15" />
        {{ stopping ? "停止中…" : "停止" }}
      </button>
    </div>

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

    <div class="composer-options">
      <label class="option">
        <span>权限</span>
        <PaSelect
          :model-value="permissionMode"
          :options="[
            { value: 'readonly', label: '只读' },
            { value: 'confirm', label: '写入需确认' },
            { value: 'workspace', label: '工作区自动' },
          ]"
          size="sm"
          data-testid="composer-permission"
          :title="PERMISSION_MODE_META[permissionMode]?.hint"
          @update:model-value="permissionMode = String($event)"
        />
      </label>
      <label class="option">
        <span>模型</span>
        <PaSelect
          :model-value="modelProfileId"
          :options="profileOptions"
          :disabled="!profiles.length"
          size="sm"
          data-testid="composer-model"
          @update:model-value="modelProfileId = String($event)"
        />
      </label>
      <label class="option">
        <span>推理</span>
        <PaSelect
          :model-value="reasoningEffort"
          :options="effortOptions"
          :disabled="!selectedProfile?.reasoningEfforts?.length"
          size="sm"
          data-testid="composer-effort"
          @update:model-value="reasoningEffort = String($event)"
        />
      </label>
      <span class="option-hint">Enter 发送 · Shift+Enter 换行</span>
    </div>
  </div>
</template>

<style scoped>
.coding-composer {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
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
.composer-row {
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
}
.composer-input {
  flex: 1;
  min-height: 60px;
  max-height: 200px;
  resize: none;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-fg);
  font-size: var(--text-sm);
  font-family: inherit;
  line-height: var(--leading-normal);
}
.composer-input:focus-visible {
  outline: var(--focus-ring);
  outline-offset: 0;
}
.composer-input:disabled {
  color: var(--color-fg-faint);
}
.composer-send,
.composer-stop {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  flex-shrink: 0;
}
.composer-stop {
  color: var(--color-danger-fg);
}
.mention-pop {
  position: absolute;
  bottom: calc(100% + var(--space-1) + 44px);
  left: 0;
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
  color: var(--color-fg-faint);
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
  color: var(--color-fg-faint);
}
.composer-options {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}
.option {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.option-hint {
  margin-left: auto;
  color: var(--color-fg-faint);
  font-size: var(--pa-t-11);
}
</style>
