<script setup lang="ts">
import {
  PhBrain,
  PhDatabase,
  PhPaperclip,
  PhPlay,
  PhStop,
  PhX,
} from "@phosphor-icons/vue";

const model = defineModel<string>({ default: "" });
const props = defineProps<{
  streaming: boolean;
  pendingTool: boolean;
  knowledgeBase: boolean;
}>();
const emit = defineEmits<{
  send: [text: string];
  stop: [];
  "toggle-kb": [];
  "gen-candidates": [];
}>();

function submit() {
  const text = model.value.trim();
  if (!text || props.streaming || props.pendingTool) return;
  emit("send", text);
  model.value = "";
}
</script>

<template>
  <div class="task-composer-wrap" data-testid="task-composer">
    <div class="task-composer" :class="{ 'is-busy': streaming }">
      <div v-if="knowledgeBase || pendingTool" class="composer-context" aria-label="已引用上下文">
        <button v-if="knowledgeBase" class="context-chip" @click="emit('toggle-kb')">
          <PhDatabase :size="13" />
          <span>本地知识库</span>
          <PhX :size="11" />
        </button>
        <span v-if="pendingTool" class="context-chip context-chip--warning">等待工具审批</span>
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
          aria-label="添加附件（请先在右侧 Files 授权路径）"
          title="请先在右侧 Files 授权文件或目录"
        >
          <PhPaperclip :size="18" />
        </button>
        <button
          class="composer-chip"
          :class="{ active: knowledgeBase }"
          type="button"
          :aria-pressed="knowledgeBase"
          @click="emit('toggle-kb')"
        >
          <PhDatabase :size="14" />
          <span>知识检索</span>
        </button>
        <button
          class="composer-chip"
          type="button"
          :disabled="streaming"
          @click="emit('gen-candidates')"
        >
          <PhBrain :size="14" />
          <span>生成记忆</span>
        </button>

        <div class="composer-mode">
          <span class="pa-status-dot" :class="streaming ? 'pa-status-dot--pulse pa-status-dot--info' : 'pa-status-dot--ok'" />
          <span>PrivateAgent · 本地</span>
        </div>

        <button v-if="streaming" class="execute-btn execute-btn--stop" data-testid="task-composer-stop" @click="emit('stop')">
          <PhStop :size="16" weight="fill" />
          <span>停止</span>
        </button>
        <button
          v-else
          class="execute-btn"
          data-testid="task-composer-submit"
          :disabled="!model.trim() || pendingTool"
          @click="submit"
        >
          <PhPlay :size="16" weight="fill" />
          <span>执行</span>
        </button>
      </div>
    </div>
    <div class="composer-hint">
      <span>Enter 发送 · Shift + Enter 换行</span>
      <span>本地优先处理</span>
    </div>
  </div>
</template>

<style scoped>
.task-composer-wrap {
  flex-shrink: 0;
  padding: var(--space-3) var(--space-5) var(--space-4);
  background: var(--color-bg);
}
.task-composer {
  max-width: 920px;
  margin: 0 auto;
  overflow: hidden;
  border: 1px solid var(--color-border-strong);
  border-radius: 16px;
  background: var(--color-surface);
  box-shadow: var(--shadow-lg);
  transition: border-color var(--duration) var(--ease), box-shadow var(--duration) var(--ease);
}
.task-composer:focus-within {
  border-color: color-mix(in srgb, var(--color-accent) 68%, var(--color-border));
  box-shadow: 0 12px 36px rgba(8, 40, 50, 0.11), 0 0 0 3px var(--color-accent-soft);
}
.task-composer.is-busy { border-color: color-mix(in srgb, var(--color-accent) 45%, var(--color-border)); }
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
  font-size: var(--text-xs);
  cursor: pointer;
}
.context-chip--warning { border-color: var(--color-warning-soft); background: var(--color-warning-soft); color: var(--color-warning-fg); cursor: default; }
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
  font-size: var(--text-md);
  line-height: 1.55;
}
textarea::placeholder { color: var(--color-fg-faint); }
textarea:disabled { cursor: not-allowed; }
.composer-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3) var(--space-3);
}
.composer-icon,
.composer-chip,
.execute-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  height: 34px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease), color var(--duration-fast) var(--ease), border-color var(--duration-fast) var(--ease), transform var(--duration-fast) var(--ease);
}
.composer-icon { width: 36px; }
.composer-icon:disabled { color: var(--color-fg-faint); cursor: help; }
.composer-chip { padding: 0 var(--space-3); font-size: var(--text-xs); }
.composer-chip:hover:not(:disabled), .composer-chip.active { border-color: color-mix(in srgb, var(--color-accent) 35%, var(--color-border)); background: var(--color-accent-soft); color: var(--color-accent-soft-fg); }
.composer-chip:disabled { opacity: .55; cursor: not-allowed; }
.composer-mode {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
  margin-left: auto;
  color: var(--color-fg-subtle);
  font-size: var(--text-xs);
  white-space: nowrap;
}
.execute-btn {
  min-width: 92px;
  padding: 0 var(--space-4);
  border-color: var(--pa-btn-primary-bg);
  background: var(--pa-btn-primary-bg);
  color: var(--color-accent-fg);
  font-weight: var(--font-semibold);
}
.execute-btn:hover:not(:disabled) { background: var(--pa-btn-primary-bg-hover); transform: translateY(-1px); }
.execute-btn:active:not(:disabled) { transform: translateY(0); }
.execute-btn:disabled { border-color: var(--color-border); background: var(--color-surface-sunken); color: var(--color-fg-faint); cursor: not-allowed; }
.execute-btn--stop { border-color: var(--color-danger); background: var(--color-danger); color: var(--pa-btn-danger-fg); }
.composer-icon:focus-visible, .composer-chip:focus-visible, .execute-btn:focus-visible, .context-chip:focus-visible { outline: none; box-shadow: var(--focus-ring); }
.composer-hint {
  display: flex;
  max-width: 920px;
  margin: var(--space-2) auto 0;
  justify-content: space-between;
  color: var(--color-fg-faint);
  font-size: 10px;
}
@media (max-width: 760px) {
  .composer-chip span, .composer-mode { display: none; }
  .composer-chip { width: 36px; padding: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .task-composer, .composer-icon, .composer-chip, .execute-btn { transition: none; }
}
</style>
