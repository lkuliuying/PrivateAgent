<script setup lang="ts">
import { ref } from "vue";
import { PhFolder, PhFolderOpen, PhFileText } from "@phosphor-icons/vue";
import type { TreeNode, TreeFile } from "../types";

/**
 * 项目目录树 · 第三阶段 M1。
 * 递归渲染：目录可展开/折叠，文件点击触发 select-file。
 * 组件以名称 ProjectTree 自引用实现递归。
 */
defineProps<{
  dirs?: TreeNode[];
  files?: TreeFile[];
  selectedPath?: string;
}>();
const emit = defineEmits<{ "select-file": [path: string] }>();

// 展开状态按目录 path 索引；默认目录收起，用户点击展开。
const expanded = ref<Set<string>>(new Set());

function toggle(path: string) {
  if (expanded.value.has(path)) expanded.value.delete(path);
  else expanded.value.add(path);
  // 触发响应式更新（Set 修改不自动触发）
  expanded.value = new Set(expanded.value);
}

function fileIcon(lang: string | null | undefined): string {
  if (!lang) return "📄";
  return (
    ({
      Python: "🐍",
      TypeScript: "🔷",
      JavaScript: "🟨",
      Vue: "💚",
      Rust: "🦀",
      Go: "🐹",
      Java: "☕",
      Markdown: "📝",
      JSON: "🔧",
      YAML: "🔧",
      HTML: "🌐",
      CSS: "🎨",
    } as Record<string, string>)[lang] || "📄"
  );
}
</script>

<template>
  <div class="tree">
    <div v-for="d in dirs" :key="d.path" class="tree-node">
      <button class="tree-row dir" @click="toggle(d.path)">
        <component
          :is="expanded.has(d.path) ? PhFolderOpen : PhFolder"
          :size="14"
          weight="fill"
          class="tree-icon"
        />
        <span class="tree-label pa-ellipsis" :title="d.name">{{ d.name }}</span>
      </button>
      <div v-if="expanded.has(d.path)" class="tree-children">
        <ProjectTree
          :dirs="d.dirs"
          :files="d.files"
          :selected-path="selectedPath"
          @select-file="emit('select-file', $event)"
        />
      </div>
    </div>
    <button
      v-for="f in files"
      :key="f.path"
      class="tree-row file"
      :class="{ active: selectedPath === f.path }"
      :title="f.path"
      @click="emit('select-file', f.path)"
    >
      <PhFileText :size="14" weight="regular" class="tree-icon" />
      <span class="tree-icon-emoji">{{ fileIcon(f.language) }}</span>
      <span class="tree-label pa-ellipsis">{{ f.name }}</span>
    </button>
  </div>
</template>

<style scoped>
.tree {
  display: flex;
  flex-direction: column;
}
.tree-children {
  padding-left: var(--space-3);
  border-left: 1px solid var(--color-border);
  margin-left: 10px;
}
.tree-row {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  border: none;
  background: transparent;
  color: var(--color-fg);
  cursor: pointer;
  padding: 3px 6px;
  border-radius: var(--radius);
  font-size: var(--text-sm);
  text-align: left;
  min-width: 0;
}
.tree-row:hover {
  background: var(--color-surface-sunken);
}
.tree-row.active {
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
}
.tree-icon {
  flex-shrink: 0;
  color: var(--color-fg-muted);
}
.tree-row.dir .tree-icon {
  color: var(--color-warning);
}
.tree-icon-emoji {
  font-size: 10px;
  flex-shrink: 0;
}
.tree-label {
  flex: 1;
  min-width: 0;
}
</style>
