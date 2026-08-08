<script setup lang="ts">
/**
 * MemoryEditorForm · 记忆新建/编辑表单（0.4.0 D4 拆分自 MemoryWorkspace）
 * 表单状态由父层持有（FormState），组件负责渲染与校验提示。
 */
import { PhCheck } from "@phosphor-icons/vue";
import type { MemoryKind } from "../../types";
import PaButton from "../../design/PaButton.vue";

export interface MemoryFormState {
  id?: number;
  kind: MemoryKind;
  title: string;
  content_md: string;
  summary: string;
  tags: string;
  sensitive: boolean;
  confidence: string;
}

defineProps<{
  form: MemoryFormState;
  busy: boolean;
  kinds: MemoryKind[];
  kindLabels: Record<string, string>;
}>();

const emit = defineEmits<{ save: []; cancel: [] }>();
</script>

<template>
  <div class="editor">
    <h2>{{ form.id ? "编辑记忆" : "新建记忆" }}</h2>
    <div class="form-grid">
      <label class="field">
        <span>类型</span>
        <select v-model="form.kind" class="pa-input">
          <option v-for="k in kinds" :key="k" :value="k">{{ kindLabels[k] }}</option>
        </select>
      </label>
      <label class="field">
        <span>标题</span>
        <input v-model="form.title" class="pa-input" placeholder="简短标题" />
      </label>
      <label class="field field--full">
        <span>内容（Markdown）</span>
        <textarea v-model="form.content_md" class="pa-input content-input" rows="8" placeholder="详细内容…"></textarea>
      </label>
      <label class="field field--full">
        <span>摘要（可选）</span>
        <input v-model="form.summary" class="pa-input" placeholder="一句话摘要" />
      </label>
      <label class="field field--full">
        <span>标签（逗号分隔）</span>
        <input v-model="form.tags" class="pa-input" placeholder="os, 类比, 进程" />
      </label>
      <label class="field">
        <span>把握度（0-1，可选）</span>
        <input v-model="form.confidence" class="pa-input" placeholder="0.8" />
      </label>
      <label class="field field--full checkbox">
        <input type="checkbox" v-model="form.sensitive" />
        <span>敏感记忆（不自动进入聊天 prompt）</span>
      </label>
    </div>
    <div class="form-actions">
      <PaButton variant="primary" :disabled="busy" @click="emit('save')">
        <PhCheck :size="15" />
        保存
      </PaButton>
      <PaButton variant="subtle" :disabled="busy" @click="emit('cancel')">
        取消
      </PaButton>
    </div>
  </div>
</template>

<style scoped>
.editor {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.editor h2 {
  margin: 0;
  font-size: var(--pa-text-section);
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--pa-text-meta);
  color: var(--color-fg-muted);
}
.field--full {
  grid-column: 1 / -1;
}
.field.checkbox {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
}
.field input[type="checkbox"] {
  margin: 0;
}
.content-input {
  min-height: 160px;
  font-family: var(--font-mono);
  resize: vertical;
}
.form-actions {
  display: flex;
  gap: var(--space-2);
}
@media (max-width: 640px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
