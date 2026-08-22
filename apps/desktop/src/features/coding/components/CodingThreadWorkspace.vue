<script setup lang="ts">
/**
 * CodingThreadWorkspace · v0.8.0 W1（占位形态）
 *
 * W1 只交付任务页骨架：ThreadHeader 摘要（标题/项目/分支/更新时间）+
 * W2 交付说明。RunTranscript、真实计划浮层（RunPlanPopover）、SSE 恢复
 * 与审批流按计划 §7 W2 接入；W3 交付 ContextDrawer 与 CodingComposer。
 * 全部信息来自 store 的公开事实（DTO 摘要），不猜测 run 状态。
 */
import { computed } from "vue";
import { PhChatsCircle, PhGitBranch } from "@phosphor-icons/vue";
import type { View } from "../../../types";
import PaEmptyState from "../../../design/PaEmptyState.vue";
import PaButton from "../../../design/PaButton.vue";
import { WORKSPACE_STATUS_META } from "../model/contracts";
import { useCodingWorkspace, type CodingWorkspaceStore } from "../model/codingWorkspaceStore";

const props = withDefaults(
  defineProps<{
    store?: CodingWorkspaceStore;
  }>(),
  {
    store: () => useCodingWorkspace(),
  }
);

const emit = defineEmits<{
  navigate: [view: View];
}>();

const thread = computed(() => props.store.selectedThread.value);
const project = computed(() => props.store.selectedProject.value);
const workspace = computed(() => props.store.selectedWorkspace.value);

const branchLabel = computed(() => {
  const current = workspace.value;
  if (!current) return "";
  return current.branchName ?? (current.kind === "root" ? "根工作区" : "工作区");
});

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("zh-CN", { hour12: false });
}

function backToHome(): void {
  props.store.startNewTask();
  emit("navigate", "coding");
}
</script>

<template>
  <section class="coding-thread" data-testid="coding-thread-workspace">
    <PaEmptyState
      v-if="!thread"
      :icon="PhChatsCircle"
      title="未选择任务"
      description="从侧栏选择一个任务，或回到首页新建任务。"
    >
      <PaButton variant="primary" @click="backToHome">回到首页</PaButton>
    </PaEmptyState>

    <template v-else>
      <header class="thread-header" data-testid="coding-thread-header">
        <div class="thread-copy">
          <h1 :title="thread.title">{{ thread.title }}</h1>
          <p class="thread-meta">
            <span>{{ project?.name ?? "未知项目" }}</span>
            <span class="meta-sep" aria-hidden="true">/</span>
            <span class="meta-branch">
              <PhGitBranch :size="13" aria-hidden="true" />
              {{ branchLabel }}
            </span>
            <template v-if="workspace && WORKSPACE_STATUS_META[workspace.status].tone !== 'neutral'">
              <span class="meta-sep" aria-hidden="true">·</span>
              <span :class="`meta-status tone-${WORKSPACE_STATUS_META[workspace.status].tone}`">
                {{ WORKSPACE_STATUS_META[workspace.status].label }}
              </span>
            </template>
            <template v-if="formatUpdatedAt(thread.updatedAt)">
              <span class="meta-sep" aria-hidden="true">·</span>
              <span>更新于 {{ formatUpdatedAt(thread.updatedAt) }}</span>
            </template>
          </p>
        </div>
      </header>

      <div class="thread-body">
        <PaEmptyState
          :icon="PhChatsCircle"
          title="任务页建设中"
          description="任务已创建并保存。执行过程（RunTranscript）、后端真实计划、审批与 Diff 将在 W2 起逐步交付；当前可从侧栏切换任务或回到首页。"
        >
          <PaButton variant="subtle" @click="backToHome">回到首页</PaButton>
        </PaEmptyState>
      </div>
    </template>
  </section>
</template>

<style scoped>
.coding-thread {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  overflow-y: auto;
}
.thread-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-5) var(--space-6);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}
.thread-copy {
  min-width: 0;
}
.thread-header h1 {
  overflow: hidden;
  margin: 0;
  color: var(--color-fg);
  font-size: var(--pa-text-page-title);
  font-weight: var(--font-semibold);
  line-height: var(--leading-tight);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.thread-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
  margin: var(--space-1) 0 0;
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
}
.meta-branch {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.meta-sep {
  color: var(--color-fg-faint);
}
.meta-status.tone-info {
  color: var(--color-accent-soft-fg);
}
.meta-status.tone-warning {
  color: var(--color-warning-fg);
}
.meta-status.tone-danger {
  color: var(--color-danger-fg);
}
.thread-body {
  display: flex;
  flex: 1;
  align-items: flex-start;
  justify-content: center;
  padding: var(--space-10) var(--space-6);
}
</style>
