<script setup lang="ts">
/**
 * PriorityList · 今日优先事项（0.4.0 D4 拆分自 TodayView）
 * 展示 top 优先级条目；父层负责筛选与展示字段计算。
 */
import {
  PhBell,
  PhCheckCircle,
  PhLightning,
  PhPlus,
  PhUploadSimple,
} from "@phosphor-icons/vue";
import type { InboxItemType, TodayItem, View } from "../../types";

export interface PriorityEntry {
  key: string;
  title: string;
  meta: string;
  sectionTitle: string;
  error?: string | null;
  item: TodayItem;
  itemType: InboxItemType;
}

defineProps<{
  entries: PriorityEntry[];
  busy: boolean;
}>();

const emit = defineEmits<{
  "save-inbox": [item: TodayItem, itemType: InboxItemType];
  "new-reminder": [];
  "quick-capture": [];
  "import-document": [];
  navigate: [view: View];
}>();
</script>

<template>
  <section class="focus-section priority-card">
    <div class="section-head">
      <h2>优先事项</h2>
      <button class="text-action" @click="emit('navigate', 'tasks')">
        <span>添加任务</span>
        <PhPlus :size="14" />
      </button>
    </div>

    <div v-if="entries.length" class="priority-list">
      <div v-for="entry in entries" :key="entry.key" class="priority-row">
        <span class="fake-check" aria-hidden="true" />
        <div class="priority-copy">
          <strong>{{ entry.title }}</strong>
          <span>{{ entry.sectionTitle }} · {{ entry.meta || "需要处理" }}</span>
          <em v-if="entry.error">{{ entry.error }}</em>
        </div>
        <button
          class="row-action"
          :disabled="busy"
          title="保存到收件箱"
          @click="emit('save-inbox', entry.item, entry.itemType)"
        >
          收件箱
        </button>
      </div>
    </div>

    <div v-else class="quiet-empty">
      <PhCheckCircle :size="20" weight="fill" />
      <div>
        <strong>当前没有必须马上处理的事项。</strong>
        <span>你可以从提醒、捕获或简报开始今天。</span>
      </div>
      <div class="quiet-actions">
        <button title="新建提醒" @click="emit('new-reminder')"><PhBell :size="15" />提醒</button>
        <button title="快速捕获" @click="emit('quick-capture')"><PhLightning :size="15" />捕获</button>
        <button title="导入文档" @click="emit('import-document')"><PhUploadSimple :size="15" />文档</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.focus-section {
  margin-bottom: var(--space-4);
}
.priority-card {
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.section-head h2 {
  margin: 0;
  font-size: var(--pa-text-section);
}
.text-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  color: var(--color-accent-soft-fg);
  font-size: var(--pa-text-compact);
  cursor: pointer;
}
.text-action:hover {
  color: var(--color-accent);
}
.priority-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.priority-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) 0;
}
.priority-row + .priority-row {
  border-top: 1px solid var(--color-border);
}
.fake-check {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  border: 1.5px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
}
.priority-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}
.priority-copy strong {
  overflow: hidden;
  font-size: var(--pa-text-compact);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.priority-copy span {
  overflow: hidden;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.priority-copy em {
  color: var(--color-danger-fg);
  font-size: var(--pa-text-meta);
  font-style: normal;
}
.row-action {
  padding: 5px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.row-action:hover:not(:disabled) {
  background: var(--color-surface-sunken);
}
.row-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.quiet-empty {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-md);
  color: var(--color-success-fg);
}
.quiet-empty > div {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}
.quiet-empty strong {
  color: var(--color-fg);
  font-size: var(--pa-text-compact);
}
.quiet-empty span {
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.quiet-actions {
  display: flex;
  gap: var(--space-1);
}
.quiet-actions button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 8px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.quiet-actions button:hover {
  background: var(--color-surface-sunken);
}
@media (max-width: 700px) {
  .quiet-empty {
    flex-wrap: wrap;
  }
}
</style>
