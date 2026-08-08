<script setup lang="ts">
/**
 * DocListItem · 知识库文档行（0.4.0 D4 拆分自 KnowledgeView）
 * 展示：选择框 / 名称与元数据 / 状态徽标 / 操作区（摘要/OCR/元数据/启用/重建/重试/删除）。
 * 状态与文案集中在组件内，父层只处理业务动作与确认。
 */
import { computed } from "vue";
import type { DocumentItem } from "../../types";
import PaBadge from "../../design/PaBadge.vue";

const props = defineProps<{
  doc: DocumentItem;
  selected: boolean;
}>();

const emit = defineEmits<{
  "toggle-select": [id: number];
  summary: [doc: DocumentItem];
  ocr: [doc: DocumentItem];
  "edit-metadata": [doc: DocumentItem];
  "toggle-enabled": [doc: DocumentItem];
  reindex: [doc: DocumentItem];
  retry: [id: number];
  remove: [id: number];
}>();

const STATUS_TEXT: Record<string, string> = {
  pending: "等待中",
  processing: "处理中",
  ready: "已就绪",
  failed: "失败",
  deleting: "删除中",
  needs_ocr: "需要 OCR",
};

const STATUS_TONE: Record<
  string,
  "neutral" | "success" | "warning" | "danger"
> = {
  ready: "success",
  failed: "danger",
  processing: "warning",
  pending: "warning",
  deleting: "warning",
  needs_ocr: "warning",
};

const statusText = computed(
  () => STATUS_TEXT[props.doc.status] ?? props.doc.status
);
const statusTone = computed(() => STATUS_TONE[props.doc.status] ?? "neutral");

function fmtSize(b: number | null): string {
  if (!b) return "-";
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
}
</script>

<template>
  <div
    class="doc-item"
    :class="{ disabled: !doc.enabled, selected }"
    data-testid="kb-doc-item"
  >
    <div class="doc-select">
      <input
        type="checkbox"
        :checked="selected"
        :aria-label="`选择文档：${doc.name}`"
        :title="'选择以对比'"
        @change="emit('toggle-select', doc.id)"
      />
    </div>
    <div class="doc-main">
      <div class="doc-name">{{ doc.name }}</div>
      <div class="doc-meta">
        <PaBadge :tone="statusTone">{{ statusText }}</PaBadge>
        <span v-if="doc.doc_type" class="meta-chip">{{ doc.doc_type }}</span>
        <span class="meta-chip">{{ fmtSize(doc.size_bytes) }}</span>
        <span v-if="doc.chunk_count" class="meta-chip">切片 {{ doc.chunk_count }}</span>
        <span v-if="doc.topic" class="meta-chip topic">主题：{{ doc.topic }}</span>
        <span v-if="doc.language" class="meta-chip">{{ doc.language }}</span>
        <span v-for="t in doc.tags_json || []" :key="t" class="meta-chip tag">#{{ t }}</span>
      </div>
      <div v-if="doc.error_message" class="doc-err" role="alert">
        失败原因：{{ doc.error_message }}
      </div>
    </div>
    <div class="doc-actions">
      <button class="icon-btn" title="章节摘要" @click="emit('summary', doc)">摘要</button>
      <button class="icon-btn" title="OCR（预留接口）" @click="emit('ocr', doc)">OCR</button>
      <button class="icon-btn" title="编辑元数据" @click="emit('edit-metadata', doc)">元数据</button>
      <label class="enable-toggle" :title="doc.enabled ? '已启用，参与检索' : '已禁用，不参与检索'">
        <input type="checkbox" :checked="doc.enabled" @change="emit('toggle-enabled', doc)" />
        <span>{{ doc.enabled ? "启用" : "禁用" }}</span>
      </label>
      <button v-if="doc.status === 'ready'" class="icon-btn" title="重建索引" @click="emit('reindex', doc)">
        重建
      </button>
      <button v-if="doc.status === 'failed'" class="icon-btn" title="重试" @click="emit('retry', doc.id)">
        重试
      </button>
      <button class="icon-btn del" title="删除" @click="emit('remove', doc.id)">删除</button>
    </div>
  </div>
</template>

<style scoped>
.doc-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  transition: border-color var(--pa-motion-fast) var(--ease),
    background var(--pa-motion-fast) var(--ease);
}
.doc-item.disabled {
  opacity: 0.55;
}
.doc-item.selected {
  border-color: var(--color-accent);
  background: var(--color-accent-soft);
}
.doc-select {
  display: flex;
  flex-shrink: 0;
  align-items: center;
}
.doc-select input {
  margin: 0;
  cursor: pointer;
}
.doc-main {
  min-width: 0;
  flex: 1;
}
.doc-name {
  overflow-wrap: anywhere;
  font-size: var(--pa-text-body);
  font-weight: var(--font-medium);
}
.doc-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-1);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-compact);
}
.meta-chip {
  padding: 1px 6px;
  border-radius: var(--radius-full);
  background: var(--color-surface-sunken);
  color: var(--color-fg-muted);
  font-size: var(--pa-t-11);
}
.meta-chip.topic {
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
}
.meta-chip.tag {
  color: var(--color-fg-subtle);
}
.doc-err {
  margin-top: var(--space-1);
  color: var(--color-danger-fg);
  font-size: var(--pa-text-compact);
}
.doc-actions {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
}
.enable-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-compact);
  cursor: pointer;
  user-select: none;
}
.enable-toggle input {
  margin: 0;
}
.icon-btn {
  padding: 5px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-compact);
  cursor: pointer;
}
.icon-btn:hover {
  background: var(--color-surface-sunken);
}
.icon-btn:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.icon-btn.del {
  color: var(--color-danger-fg);
}
@media (max-width: 920px) {
  .doc-item {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .doc-actions {
    width: 100%;
    padding-left: 28px;
    justify-content: flex-start;
  }
}
</style>
