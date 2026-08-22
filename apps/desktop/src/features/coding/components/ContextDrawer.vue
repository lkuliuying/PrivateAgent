<script setup lang="ts">
/**
 * ContextDrawer · v0.8.0 W3
 *
 * 任务页右侧可折叠抽屉：Files（审批预览涉及的文件）/ Context（run 元信息
 * 与权限快照）/ Sources（Coding 任务不使用 RAG 来源——如实空态）/
 * Artifacts（run 快照产出的 11 种 kind 摘要）。全部来自公开事实。
 */
import { computed, ref } from "vue";
import { PhSidebarSimple, PhX } from "@phosphor-icons/vue";
import type { RunApprovalPreviewRecord } from "../model/runContracts";
import { RUN_STATUS_META } from "../model/runContracts";
import type { RunProjection } from "../model/runProjector";
import { PERMISSION_MODE_META } from "../model/runContracts";

const props = withDefaults(
  defineProps<{
    projection: RunProjection | null;
    previews: Record<string, RunApprovalPreviewRecord | null>;
    permissionMode?: string | null;
  }>(),
  {
    permissionMode: null,
  }
);

const emit = defineEmits<{
  close: [];
}>();

type TabKey = "files" | "context" | "sources" | "artifacts";
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "files", label: "Files" },
  { key: "context", label: "Context" },
  { key: "sources", label: "Sources" },
  { key: "artifacts", label: "Artifacts" },
];
const activeTab = ref<TabKey>("files");

const changedFiles = computed(() => {
  const files: Array<{ relPath: string; creates: boolean | null }> = [];
  const seen = new Set<string>();
  for (const preview of Object.values(props.previews)) {
    if (preview?.previewable && preview.rel_path && !seen.has(preview.rel_path)) {
      seen.add(preview.rel_path);
      files.push({ relPath: preview.rel_path, creates: preview.creates_file });
    }
  }
  return files;
});

const artifacts = computed(() =>
  (props.projection?.entries ?? []).filter((entry) => entry.kind === "artifact")
);

const statusMeta = computed(() => {
  const status = props.projection?.status;
  return status ? RUN_STATUS_META[status] : null;
});

const usage = computed(() => props.projection?.usage);
</script>

<template>
  <aside class="context-drawer" data-testid="context-drawer" aria-label="任务上下文">
    <header class="drawer-head">
      <strong>上下文</strong>
      <button class="icon-btn" aria-label="收起上下文" data-testid="context-drawer-close" @click="emit('close')">
        <PhX :size="15" />
      </button>
    </header>

    <div class="drawer-tabs" role="tablist" aria-label="上下文分类">
      <button
        v-for="tab in TABS"
        :key="tab.key"
        role="tab"
        class="drawer-tab"
        :class="{ active: activeTab === tab.key }"
        :aria-selected="activeTab === tab.key"
        :data-testid="`context-tab-${tab.key}`"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="drawer-body">
      <!-- Files -->
      <div v-if="activeTab === 'files'" class="pane" data-testid="context-pane-files">
        <div v-if="!changedFiles.length" class="pane-empty">本次任务尚无文件变更（审批预览加载后显示）</div>
        <ul v-else class="file-list">
          <li v-for="file in changedFiles" :key="file.relPath" class="mono file-item" :title="file.relPath">
            <span class="file-path">{{ file.relPath }}</span>
            <span v-if="file.creates" class="file-creates">新建</span>
          </li>
        </ul>
      </div>

      <!-- Context -->
      <div v-else-if="activeTab === 'context'" class="pane" data-testid="context-pane-context">
        <dl class="meta-list">
          <div class="meta-row"><dt>任务状态</dt><dd>{{ statusMeta?.label ?? "未开始" }}</dd></div>
          <div class="meta-row"><dt>权限模式</dt><dd>{{ permissionMode ? (PERMISSION_MODE_META[permissionMode]?.label ?? permissionMode) : "未指定" }}</dd></div>
          <div class="meta-row"><dt>工具调用</dt><dd>{{ usage?.toolCallCount ?? 0 }}</dd></div>
          <div class="meta-row"><dt>输入 tokens</dt><dd>{{ (usage?.inputTokens ?? 0).toLocaleString() }}</dd></div>
          <div class="meta-row"><dt>输出 tokens</dt><dd>{{ (usage?.outputTokens ?? 0).toLocaleString() }}</dd></div>
          <div class="meta-row"><dt>计划版本</dt><dd>{{ projection?.plan ? `v${projection.plan.version} · ${projection.plan.items.length} 项` : "无" }}</dd></div>
        </dl>
      </div>

      <!-- Sources -->
      <div v-else-if="activeTab === 'sources'" class="pane" data-testid="context-pane-sources">
        <div class="pane-empty">Coding 任务不使用 RAG 来源；知识库引用属于聊天模式。</div>
      </div>

      <!-- Artifacts -->
      <div v-else class="pane" data-testid="context-pane-artifacts">
        <div v-if="!artifacts.length" class="pane-empty">本次任务尚无产出</div>
        <ul v-else class="file-list">
          <li v-for="entry in artifacts" :key="entry.key" class="file-item" :title="entry.kind === 'artifact' ? entry.title : ''">
            <span v-if="entry.kind === 'artifact'" class="artifact-kind mono">{{ entry.artifactKind }}</span>
            <span v-if="entry.kind === 'artifact'" class="file-path">{{ entry.title }}</span>
          </li>
        </ul>
      </div>
    </div>

    <footer class="drawer-foot">
      <PhSidebarSimple :size="14" aria-hidden="true" />
      <span>事实来自 run 快照与审批预览</span>
    </footer>
  </aside>
</template>

<style scoped>
.context-drawer {
  display: flex;
  width: 320px;
  flex-shrink: 0;
  flex-direction: column;
  overflow: hidden;
  border-left: 1px solid var(--color-border);
  background: var(--color-panel);
}
.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3);
  border-bottom: 1px solid var(--color-border);
  color: var(--color-fg);
  font-size: var(--text-sm);
}
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-fg-muted);
  cursor: pointer;
}
.icon-btn:hover {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.drawer-tabs {
  display: flex;
  gap: 2px;
  padding: var(--space-2) var(--space-2) 0;
}
.drawer-tab {
  flex: 1;
  height: 28px;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.drawer-tab.active {
  border-bottom-color: var(--color-accent);
  color: var(--color-fg);
  font-weight: var(--font-medium);
}
.drawer-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-3);
}
.pane-empty {
  padding: var(--space-3) 0;
  color: var(--color-fg-faint);
  font-size: var(--pa-text-meta);
  line-height: var(--leading-normal);
}
.file-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}
.file-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.file-path {
  overflow: hidden;
  min-width: 0;
  flex: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-creates {
  flex-shrink: 0;
  color: var(--color-success-fg);
}
.artifact-kind {
  flex-shrink: 0;
  padding: 1px var(--space-1);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.meta-list {
  margin: 0;
}
.meta-row {
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-1) 0;
  border-bottom: 1px solid var(--color-border);
  font-size: var(--pa-text-meta);
}
.meta-row dt {
  color: var(--color-fg-faint);
}
.meta-row dd {
  margin: 0;
  color: var(--color-fg);
}
.drawer-foot {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border-top: 1px solid var(--color-border);
  color: var(--color-fg-faint);
  font-size: var(--pa-t-11);
}
</style>
