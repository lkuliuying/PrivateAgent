<script setup lang="ts">
import { ref, computed } from "vue";
import { PhX, PhDownloadSimple, PhSpinner } from "@phosphor-icons/vue";
import { exportMarkdown, pickDirectory } from "../api";
import type { CompareResult } from "../types";

/**
 * 多文档对比面板 · 第三阶段 M4。
 * 展示共同点/差异/冲突/推荐阅读顺序；可把对比结果导出为 Markdown（需授权目录）。
 */
const props = defineProps<{ result: CompareResult | null; loading: boolean }>();
const emit = defineEmits<{ close: [] }>();

const exporting = ref(false);
const exportMsg = ref("");

const mdContent = computed(() => {
  const r = props.result;
  if (!r) return "";
  const lines: string[] = [`# 文档对比\n`, `对比文档：${r.doc_names.join("、")}\n`];
  lines.push("## 共同点\n");
  r.common.forEach((c) => lines.push(`- ${c}`));
  if (!r.common.length) lines.push("- 无");
  lines.push("\n## 差异点\n");
  r.differences.forEach((d) => lines.push(`- **${d.doc}**：${d.point}`));
  if (!r.differences.length) lines.push("- 无");
  lines.push("\n## 冲突点\n");
  r.conflicts.forEach((c) => lines.push(`- ${c}`));
  if (!r.conflicts.length) lines.push("- 无");
  lines.push("\n## 推荐阅读顺序\n");
  r.reading_order.forEach((o) => lines.push(`${o}`));
  return lines.join("\n");
});

async function onExport() {
  if (!mdContent.value) return;
  const dir = await pickDirectory();
  if (!dir) {
    exportMsg.value = "未选择目录（dev 模式请在授权目录中输入路径）";
    return;
  }
  exporting.value = true;
  exportMsg.value = "";
  try {
    const res = await exportMarkdown(mdContent.value, "文档对比", dir);
    exportMsg.value = `已导出：${res.path}`;
  } catch (e) {
    exportMsg.value = "导出失败：" + String(e);
  } finally {
    exporting.value = false;
  }
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="compare-card">
      <div class="compare-head">
        <span>文档对比</span>
        <div class="head-actions">
          <button
            class="pa-btn pa-btn--subtle pa-btn--sm"
            :disabled="exporting || !result"
            @click="onExport"
          >
            <PhDownloadSimple :size="14" />
            {{ exporting ? "导出中…" : "导出 Markdown" }}
          </button>
          <button class="pa-btn pa-btn--ghost pa-btn--icon" @click="emit('close')">
            <PhX :size="14" />
          </button>
        </div>
      </div>

      <div v-if="loading" class="loading">
        <PhSpinner :size="24" weight="bold" class="spin" />
        <p>正在对比文档…</p>
      </div>

      <div v-else-if="result" class="compare-body">
        <p class="doc-names">对比：{{ result.doc_names.join("  ·  ") }}</p>

        <section class="cmp-section">
          <h4>共同点</h4>
          <ul>
            <li v-for="(c, i) in result.common" :key="i">{{ c }}</li>
            <li v-if="!result.common.length" class="muted">无</li>
          </ul>
        </section>

        <section class="cmp-section">
          <h4>差异点</h4>
          <ul>
            <li v-for="(d, i) in result.differences" :key="i">
              <span class="diff-doc">{{ d.doc }}</span>：{{ d.point }}
            </li>
            <li v-if="!result.differences.length" class="muted">无</li>
          </ul>
        </section>

        <section class="cmp-section">
          <h4>冲突点</h4>
          <ul>
            <li v-for="(c, i) in result.conflicts" :key="i" class="conflict">{{ c }}</li>
            <li v-if="!result.conflicts.length" class="muted">无</li>
          </ul>
        </section>

        <section class="cmp-section">
          <h4>推荐阅读顺序</h4>
          <ol>
            <li v-for="(o, i) in result.reading_order" :key="i">{{ o }}</li>
          </ol>
        </section>

        <p v-if="exportMsg" class="export-msg">{{ exportMsg }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.compare-card {
  width: 640px;
  max-width: 92vw;
  max-height: 84vh;
  display: flex;
  flex-direction: column;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}
.compare-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  font-size: var(--text-md);
  font-weight: var(--font-semibold);
}
.head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-8);
  color: var(--color-fg-faint);
}
.spin {
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.compare-body {
  flex: 1;
  overflow: auto;
  padding: var(--space-4);
}
.doc-names {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-fg-subtle);
}
.cmp-section {
  margin-bottom: var(--space-4);
}
.cmp-section h4 {
  margin: 0 0 var(--space-1);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--color-fg);
}
.cmp-section ul,
.cmp-section ol {
  margin: 0;
  padding-left: var(--space-5);
}
.cmp-section li {
  font-size: var(--text-sm);
  color: var(--color-fg-muted);
  margin-bottom: 4px;
}
.diff-doc {
  font-weight: var(--font-medium);
  color: var(--color-accent-soft-fg);
}
.conflict {
  color: var(--color-danger-fg);
}
.muted {
  color: var(--color-fg-faint);
}
.export-msg {
  margin-top: var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-success-fg);
  background: var(--color-success-soft);
  padding: var(--space-2);
  border-radius: var(--radius);
}
</style>
