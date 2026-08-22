<script setup lang="ts">
/**
 * DiffArtifact · v0.8.0 W3
 *
 * 统一 diff 渲染（审批影响范围预览 / patch 摘要）：默认折叠为文件头与
 * 统计行，展开渲染 +/- 行（独立滚动、行数上限防长输出阻塞主区）。
 * previewable=false 时仅呈现后端 reason（不猜测内容）。
 */
import { computed, ref } from "vue";
import { PhCaretDown, PhFilePlus, PhGitDiff, PhWarning } from "@phosphor-icons/vue";
import type { RunApprovalPreviewRecord } from "../model/runContracts";

const props = defineProps<{
  preview: RunApprovalPreviewRecord | null;
  loading?: boolean;
}>();

const open = ref(false);

interface DiffLine {
  kind: "add" | "del" | "hunk" | "context";
  text: string;
}

const diffLines = computed<DiffLine[]>(() => {
  const diff = props.preview?.diff;
  if (!diff) return [];
  return diff
    .split("\n")
    .filter((line) => line.trim() !== "")
    .map((line) => {
      if (line.startsWith("@@")) return { kind: "hunk" as const, text: line };
      if (line.startsWith("+")) return { kind: "add" as const, text: line };
      if (line.startsWith("-")) return { kind: "del" as const, text: line };
      return { kind: "context" as const, text: line };
    });
});

const stats = computed(() => {
  let additions = 0;
  let deletions = 0;
  for (const line of diffLines.value) {
    if (line.kind === "add") additions += 1;
    if (line.kind === "del") deletions += 1;
  }
  return { additions, deletions };
});

const MAX_RENDER_LINES = 800;
const renderedLines = computed(() => diffLines.value.slice(0, MAX_RENDER_LINES));
</script>

<template>
  <div class="diff-artifact" data-testid="diff-artifact">
    <button
      class="diff-head"
      :aria-expanded="open"
      data-testid="diff-artifact-toggle"
      @click="open = !open"
    >
      <PhGitDiff :size="15" aria-hidden="true" />
      <span class="diff-path mono">{{ preview?.rel_path ?? "文件变更预览" }}</span>
      <span v-if="preview?.creates_file" class="diff-creates">
        <PhFilePlus :size="13" aria-hidden="true" />新建
      </span>
      <template v-if="preview?.previewable && diffLines.length">
        <span class="diff-stats">
          <span class="stat-add">+{{ stats.additions }}</span>
          <span class="stat-del">-{{ stats.deletions }}</span>
        </span>
      </template>
      <PhCaretDown :size="13" class="diff-caret" :class="{ open }" aria-hidden="true" />
    </button>

    <div v-if="loading" class="diff-loading">正在加载影响范围…</div>
    <div v-else-if="!preview" class="diff-reason">尚未加载预览</div>
    <div v-else-if="!preview.previewable" class="diff-reason">
      <PhWarning :size="13" aria-hidden="true" />
      {{ preview.reason || "该工具不提供文件预览" }}
    </div>
    <div v-else-if="!diffLines.length" class="diff-reason">无文本差异</div>

    <pre v-else-if="open" class="diff-body" data-testid="diff-artifact-body"><code
      ><span
        v-for="(line, index) in renderedLines"
        :key="index"
        class="diff-line"
        :class="`kind-${line.kind}`"
      >{{ line.text }}
</span></code></pre>
    <div v-if="open && diffLines.length > MAX_RENDER_LINES" class="diff-truncated">
      diff 过长，仅渲染前 {{ MAX_RENDER_LINES }} 行
    </div>
    <div v-if="preview?.truncated" class="diff-truncated">后端已截断（diff 超出预览上限）</div>
  </div>
</template>

<style scoped>
.diff-artifact {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin-top: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  overflow: hidden;
}
.diff-head {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: none;
  background: transparent;
  color: var(--color-fg);
  font-size: var(--pa-text-meta);
  text-align: left;
  cursor: pointer;
}
.diff-head:hover {
  background: var(--color-surface-muted);
}
.diff-path {
  overflow: hidden;
  min-width: 0;
  flex: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.diff-creates {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: var(--color-success-fg);
}
.diff-stats {
  display: inline-flex;
  gap: var(--space-2);
  font-family: var(--font-mono, monospace);
}
.stat-add { color: var(--color-success-fg); }
.stat-del { color: var(--color-danger-fg); }
.diff-caret {
  transition: transform var(--pa-motion-fast) var(--ease);
}
.diff-caret.open {
  transform: rotate(90deg);
}
.diff-body {
  max-height: 320px;
  overflow: auto;
  margin: 0;
  padding: var(--space-2) 0;
  background: var(--color-bg);
  font-size: var(--pa-text-meta);
  line-height: var(--leading-normal);
}
.diff-line {
  display: block;
  padding: 0 var(--space-3);
  white-space: pre;
}
.diff-line.kind-add {
  background: var(--color-success-soft);
  color: var(--color-success-fg);
}
.diff-line.kind-del {
  background: var(--color-danger-soft);
  color: var(--color-danger-fg);
}
.diff-line.kind-hunk {
  color: var(--color-accent-soft-fg);
}
.diff-line.kind-context {
  color: var(--color-fg-muted);
}
.diff-reason {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.diff-loading {
  padding: var(--space-2) var(--space-3);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.diff-truncated {
  padding: var(--space-1) var(--space-3);
  border-top: 1px solid var(--color-border);
  color: var(--color-warning-fg);
  font-size: var(--pa-t-11);
}
@media (prefers-reduced-motion: reduce) {
  .diff-caret { transition: none; }
}
</style>
