<script setup lang="ts">
/**
 * TaskComposerV2 · 任务输入组合器（0.4.0 D3；v0.8.0 W6-R3 重排）
 *
 * 底部输入区：输入/附件/发送停止。W6-R3：删除「知识检索」「生成记忆」手动按钮、
 * 快捷键与空占位（能力改为自动运行，见 model/autoContext.ts）；工具栏提供
 * toolbar-left（权限下拉位）与 toolbar-right（模型入口/上下文用量位）插槽；
 * 控制行在 1280/150%/长模型名下有序换行，不遮挡执行按钮。
 */
import { computed } from "vue";
import {
  PhPaperclip,
  PhPlay,
  PhStop,
} from "@phosphor-icons/vue";
import PaStatusIndicator from "../../design/PaStatusIndicator.vue";

const model = defineModel<string>({ default: "" });
const props = withDefaults(
  defineProps<{
    streaming: boolean;
    pendingTool: boolean;
    providerLabel?: string;
    stopRequested?: boolean;
    stopped?: boolean;
    /**
     * v0.9.0 H1-B（计划 §5.6）：模型/Provider 阻塞原因（如未配置）；
     * 非空时执行按钮禁用并紧邻说明原因，配置完成后无需新建会话即可执行。
     */
    blockedReason?: string | null;
  }>(),
  { providerLabel: "本地", stopRequested: false, stopped: false, blockedReason: null }
);
const emit = defineEmits<{
  send: [text: string];
  stop: [];
}>();

const canSend = computed(
  () =>
    Boolean(model.value.trim()) &&
    !props.streaming &&
    !props.pendingTool &&
    !props.blockedReason
);

function submit() {
  const text = model.value.trim();
  if (!text || props.streaming || props.pendingTool || props.blockedReason) return;
  emit("send", text);
  model.value = "";
}
</script>

<template>
  <div class="composer-wrap" data-testid="task-composer">
    <div class="composer" :class="{ 'is-busy': streaming, 'is-stopping': stopRequested }">
      <div v-if="pendingTool" class="composer-context" aria-label="已引用上下文">
        <span class="context-chip context-chip--warning">等待工具审批</span>
      </div>

      <textarea
        data-testid="task-composer-input"
        v-model="model"
        rows="2"
        :disabled="streaming || pendingTool"
        :placeholder="pendingTool ? '请先处理上方的授权请求…' : '让 PrivateAgent 构建、分析或处理任务…'"
        aria-label="任务说明"
        @keydown.enter.exact.prevent="submit"
      />

      <div class="composer-toolbar">
        <button
          class="composer-icon"
          type="button"
          disabled
          aria-label="添加附件（请先在授权路径中选择文件）"
          title="请先在授权文件或目录中选择"
        >
          <PhPaperclip :size="18" />
        </button>
        <!-- W6-R3：原知识检索位 = 命令权限下拉（由父层插槽提供） -->
        <slot name="toolbar-left" />

        <!-- W6-R3：模型/Provider 入口与上下文用量（由父层插槽提供） -->
        <slot name="toolbar-right" />

        <PaStatusIndicator
          class="composer-mode"
          :tone="streaming ? 'info' : 'ok'"
          :pulse="streaming"
          :label="streaming ? `PrivateAgent · 运行中` : `PrivateAgent · ${providerLabel}`"
        />
        <!-- v0.9.0 H1-A：PrivateAgent 状态旁的紧凑上下文用量圆环（父层插槽） -->
        <slot name="context-ring" />

        <button
          v-if="streaming || stopRequested"
          class="execute-btn execute-btn--stop"
          :class="{ 'is-requesting': stopRequested }"
          data-testid="task-composer-stop"
          :disabled="stopRequested"
          @click="emit('stop')"
        >
          <PhStop :size="16" weight="fill" />
          <span>{{ stopRequested ? "正在停止…" : "停止" }}</span>
        </button>
        <button
          v-else
          class="execute-btn"
          data-testid="task-composer-submit"
          :disabled="!canSend"
          @click="submit"
        >
          <PhPlay :size="16" weight="fill" />
          <span>执行</span>
        </button>
        <!-- v0.9.0 H1-B（§5.6）：阻塞原因紧邻执行按钮（未配置等） -->
        <span
          v-if="blockedReason && !streaming && !stopRequested"
          class="blocked-reason"
          data-testid="task-composer-blocked"
        >{{ blockedReason }}</span>
      </div>
    </div>
    <div class="composer-hint">
      <span>Enter 发送 · Shift + Enter 换行</span>
      <span v-if="stopped" class="hint-stopped">已停止本轮生成，可重新发送</span>
      <span v-else>本地优先处理</span>
    </div>
  </div>
</template>

<style scoped>
.composer-wrap {
  flex-shrink: 0;
  padding: var(--space-3) var(--space-5) var(--space-4);
  background: var(--color-bg);
}
.composer {
  max-width: 920px;
  margin: 0 auto;
  overflow: hidden;
  border: 1px solid var(--color-border-strong);
  border-radius: 16px;
  background: var(--color-surface);
  box-shadow: var(--shadow-lg);
  transition: border-color var(--pa-motion-standard) var(--ease),
    box-shadow var(--pa-motion-standard) var(--ease);
}
.composer:focus-within {
  border-color: color-mix(in srgb, var(--color-accent) 68%, var(--color-border));
  box-shadow: 0 12px 36px rgba(8, 40, 50, 0.11), 0 0 0 3px var(--color-accent-soft);
}
.composer.is-busy {
  border-color: color-mix(in srgb, var(--color-accent) 45%, var(--color-border));
}
.composer.is-stopping {
  border-color: color-mix(in srgb, var(--color-danger) 45%, var(--color-border));
}
.composer-context {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4) 0;
}
.context-chip {
  display: inline-flex;
  height: 24px;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-2);
  border: 1px solid color-mix(in srgb, var(--color-accent) 30%, var(--color-border));
  border-radius: var(--radius-full);
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.context-chip--warning {
  border-color: var(--color-warning-soft);
  background: var(--color-warning-soft);
  color: var(--color-warning-fg);
  cursor: default;
}
textarea {
  display: block;
  width: 100%;
  min-height: 78px;
  max-height: 160px;
  resize: none;
  padding: var(--space-4) var(--space-5) var(--space-2);
  border: none;
  outline: none;
  background: transparent;
  color: var(--color-fg);
  font: inherit;
  font-size: var(--pa-text-body);
  line-height: 1.55;
}
textarea::placeholder {
  color: var(--color-fg-faint);
}
textarea:disabled {
  cursor: not-allowed;
}
.composer-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3) var(--space-3);
}
.composer-icon,
.composer-chip,
.execute-btn {
  display: inline-flex;
  height: 34px;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  cursor: pointer;
  transition: background var(--pa-motion-fast) var(--ease),
    color var(--pa-motion-fast) var(--ease),
    border-color var(--pa-motion-fast) var(--ease),
    transform var(--pa-motion-instant) var(--ease);
}
.composer-icon {
  width: 36px;
}
.composer-icon:disabled {
  color: var(--color-fg-faint);
  cursor: help;
}
.composer-chip {
  padding: 0 var(--space-3);
  font-size: var(--pa-text-meta);
}
.composer-chip:hover:not(:disabled),
.composer-chip.active {
  border-color: color-mix(in srgb, var(--color-accent) 35%, var(--color-border));
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
}
.composer-chip:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.composer-mode {
  margin-left: auto;
}
.execute-btn {
  min-width: 92px;
  padding: 0 var(--space-4);
  border-color: var(--pa-btn-primary-bg);
  background: var(--pa-btn-primary-bg);
  color: var(--color-accent-fg);
  font-weight: var(--font-semibold);
}
.execute-btn:hover:not(:disabled) {
  background: var(--pa-btn-primary-bg-hover);
  transform: translateY(-1px);
}
.execute-btn:active:not(:disabled) {
  transform: translateY(0);
}
.execute-btn:disabled {
  border-color: var(--color-border);
  background: var(--color-surface-sunken);
  color: var(--color-fg-faint);
  cursor: not-allowed;
}
.execute-btn--stop {
  border-color: var(--color-danger);
  background: var(--color-danger);
  color: var(--pa-btn-danger-fg);
}
.execute-btn--stop.is-requesting {
  opacity: 0.75;
  cursor: progress;
}
.blocked-reason {
  max-width: 260px;
  overflow: hidden;
  color: var(--color-warning-fg);
  font-size: var(--pa-text-meta);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.composer-icon:focus-visible,
.composer-chip:focus-visible,
.execute-btn:focus-visible,
.context-chip:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.composer-hint {
  display: flex;
  max-width: 920px;
  margin: var(--space-2) auto 0;
  justify-content: space-between;
  color: var(--color-fg-subtle);
  font-size: var(--pa-t-11);
}
.hint-stopped {
  color: var(--color-fg-subtle);
}
@media (max-width: 760px) {
  .composer-chip span,
  .composer-mode :deep(.pa-status-label) {
    display: none;
  }
  .composer-chip {
    width: 36px;
    padding: 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .composer,
  .composer-icon,
  .composer-chip,
  .execute-btn {
    transition: none;
  }
}
</style>
