<script setup lang="ts">
import { ref } from "vue";
import { PhMagnifyingGlass } from "@phosphor-icons/vue";
import { searchProject } from "../api";
import type {
  ContentSearchResult,
  NameSearchResult,
} from "../types";

/**
 * 代码搜索面板 · 第三阶段 M1。
 * 支持文件名(name)/内容(content, 正则)两种搜索；内容结果带行号与上下文。
 * 点击结果触发 select-file（内容结果附带行号）。
 */
const props = defineProps<{ projectId: number }>();
const emit = defineEmits<{
  "select-file": [path: string, line?: number];
}>();

const query = ref("");
const kind = ref<"name" | "content">("name");
const loading = ref(false);
const error = ref("");
const nameResults = ref<NameSearchResult[]>([]);
const contentResults = ref<ContentSearchResult[]>([]);
const truncated = ref(false);

async function runSearch() {
  const q = query.value.trim();
  if (!q) {
    nameResults.value = [];
    contentResults.value = [];
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const res = await searchProject(props.projectId, q, kind.value);
    if (kind.value === "name") {
      nameResults.value = (res as { results: NameSearchResult[] }).results;
      contentResults.value = [];
    } else {
      contentResults.value = (res as { results: ContentSearchResult[]; truncated: boolean }).results;
      truncated.value = (res as { truncated: boolean }).truncated;
      nameResults.value = [];
    }
  } catch (e) {
    error.value = String(e);
    nameResults.value = [];
    contentResults.value = [];
  } finally {
    loading.value = false;
  }
}

function onKey(e: KeyboardEvent) {
  if (e.key === "Enter") runSearch();
}
</script>

<template>
  <div class="search-panel">
    <div class="search-bar">
      <PhMagnifyingGlass :size="14" weight="regular" class="search-icon" />
      <input
        v-model="query"
        class="pa-input search-input"
        :placeholder="kind === 'name' ? '搜索文件名…' : '正则搜索内容…'"
        @keydown="onKey"
      />
      <select v-model="kind" class="pa-input kind-select" @change="runSearch">
        <option value="name">文件名</option>
        <option value="content">内容</option>
      </select>
      <button
        class="pa-btn pa-btn--primary pa-btn--sm"
        :disabled="loading || !query.trim()"
        @click="runSearch"
      >
        搜索
      </button>
    </div>

    <p v-if="error" class="err">{{ error }}</p>

    <div v-if="kind === 'name'" class="results">
      <button
        v-for="r in nameResults"
        :key="r.rel_path"
        class="result-row"
        @click="emit('select-file', r.rel_path)"
      >
        <span class="r-path pa-ellipsis">{{ r.rel_path }}</span>
        <span v-if="r.language" class="r-lang">{{ r.language }}</span>
      </button>
      <p v-if="nameResults.length === 0 && query && !loading" class="empty-hint">
        无匹配文件
      </p>
    </div>

    <div v-else class="results">
      <button
        v-for="(r, i) in contentResults"
        :key="i"
        class="result-row content-row"
        @click="emit('select-file', r.rel_path, r.line)"
      >
        <div class="c-head">
          <span class="r-path pa-ellipsis">{{ r.rel_path }}</span>
          <span class="r-line">:{{ r.line }}</span>
        </div>
        <pre class="c-context">{{ r.context }}</pre>
      </button>
      <p v-if="truncated" class="trunc-hint">结果过多已截断，请细化搜索词</p>
      <p v-if="contentResults.length === 0 && query && !loading" class="empty-hint">
        无匹配内容
      </p>
    </div>
  </div>
</template>

<style scoped>
.search-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.search-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  position: relative;
}
.search-icon {
  position: absolute;
  left: 10px;
  color: var(--color-fg-faint);
  pointer-events: none;
}
.search-input {
  flex: 1;
  height: 32px;
  padding-left: 30px;
}
.kind-select {
  height: 32px;
  width: 90px;
  background: var(--color-surface);
}
.err {
  margin: 0;
  color: var(--color-danger-fg);
  font-size: var(--text-sm);
}
.results {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.result-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
  padding: 6px 8px;
  border-radius: var(--radius);
  font-size: var(--text-sm);
  color: var(--color-fg);
  min-width: 0;
}
.result-row:hover {
  background: var(--color-surface-sunken);
}
.content-row {
  flex-direction: column;
  align-items: stretch;
  gap: 2px;
}
.r-path {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  flex: 1;
  min-width: 0;
}
.r-lang {
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--color-accent-soft-fg);
  background: var(--color-accent-soft);
  padding: 1px 6px;
  border-radius: var(--radius-full);
}
.c-head {
  display: flex;
  gap: 4px;
}
.r-line {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  flex-shrink: 0;
}
.c-context {
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-fg);
  background: var(--color-surface-sunken);
  padding: 4px 6px;
  border-radius: var(--radius);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 80px;
  overflow: auto;
}
.empty-hint,
.trunc-hint {
  margin: 0;
  padding: var(--space-2);
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
  text-align: center;
}
.trunc-hint {
  color: var(--color-warning-fg);
}
</style>
