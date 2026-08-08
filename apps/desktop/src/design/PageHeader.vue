<script setup lang="ts">
/**
 * PageHeader · 统一页面层级（0.4.0 D4，计划 §4.3）
 * 面包屑/工作上下文 → 页面标题 → 一行状态摘要 → 主要操作/次要菜单 → 主体。
 */
import type { Component } from "vue";

withDefaults(
  defineProps<{
    title: string;
    icon?: Component;
    /** 面包屑：["知识库", "集合"] 等 */
    breadcrumb?: string[];
    /** 一行状态摘要（右侧） */
    summary?: string;
  }>(),
  { icon: undefined, breadcrumb: () => [], summary: "" }
);
</script>

<template>
  <header class="page-header">
    <div class="page-header-main">
      <div v-if="breadcrumb.length" class="page-breadcrumb" aria-label="位置">
        <template v-for="(crumb, index) in breadcrumb" :key="crumb">
          <span>{{ crumb }}</span>
          <span v-if="index < breadcrumb.length - 1" class="crumb-sep" aria-hidden="true">/</span>
        </template>
      </div>
      <div class="page-title-row">
        <component :is="icon" v-if="icon" :size="22" weight="duotone" class="page-title-icon" />
        <h1 class="page-title">{{ title }}</h1>
      </div>
    </div>
    <div class="page-header-side">
      <span v-if="summary" class="page-summary">{{ summary }}</span>
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex;
  flex-shrink: 0;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6) var(--space-3);
}
.page-header-main {
  min-width: 0;
}
.page-breadcrumb {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-1);
  margin-bottom: 4px;
  color: var(--color-fg-faint);
  font-size: var(--pa-text-meta);
  overflow: hidden;
  white-space: nowrap;
}
.page-breadcrumb span {
  overflow: hidden;
  text-overflow: ellipsis;
}
.crumb-sep {
  color: var(--color-border-strong);
}
.page-title-row {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
}
.page-title {
  margin: 0;
  overflow: hidden;
  color: var(--color-fg);
  font-size: var(--pa-text-page-title);
  font-weight: var(--font-semibold);
  line-height: var(--leading-tight);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.page-title-icon {
  flex-shrink: 0;
  color: var(--color-accent-soft-fg);
}
.page-header-side {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: var(--space-2);
}
.page-summary {
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-compact);
  white-space: nowrap;
}
@media (max-width: 900px) {
  .page-header {
    padding: var(--space-4) var(--space-4) var(--space-3);
  }
  .page-summary {
    display: none;
  }
}
</style>
