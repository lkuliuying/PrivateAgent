<script setup lang="ts">
/**
 * SessionHeader · v0.8.0 W6-R2（v0.8.0 W6-R3 修订）
 *
 * 标题区：会话标题、运行状态、当前授权工作目录与 Git 分支（公开
 * workspace 事实；组件不调用 git/fetch/invoke）。W6-R3：移除顶部模型
 * chip 与上下文按钮（模型配置下沉底部，上下文自动装配+用量模块反馈）。
 * 长路径截断 + tooltip + 复制（提示不含路径正文）。
 */
import { computed } from "vue";
import { PhCircleNotch, PhCopy, PhFolderOpen, PhGitBranch } from "@phosphor-icons/vue";
import type { AgentWorkspaceFacts } from "./model/workspaceFacts";
import { gitStateLabel, truncatePath } from "./model/workspaceFacts";
import { copyAnswerText } from "./model/copyAnswerText";
import { useNotifications } from "../../stores/notifications";

const props = withDefaults(
  defineProps<{
    title: string;
    running?: boolean;
    waitingApproval?: boolean;
    /** 当前会话的工作目录/Git 事实（切换时由父层原子更新，不沿用旧值） */
    workspaceFacts?: AgentWorkspaceFacts | null;
  }>(),
  { running: false, waitingApproval: false, workspaceFacts: null }
);

const notify = useNotifications();

const gitLabel = computed(() =>
  props.workspaceFacts ? gitStateLabel(props.workspaceFacts.git) : "读取中…"
);

const gitTone = computed(() => {
  const git = props.workspaceFacts?.git;
  if (!git || git.kind === "loading") return "tone-muted";
  switch (git.kind) {
    case "branch":
      return "tone-ok";
    case "detached":
    case "non-git":
      return "tone-warning";
    default:
      return "tone-danger";
  }
});

const rootPath = computed(() => props.workspaceFacts?.rootPath ?? null);
const rootPathDisplay = computed(() => (rootPath.value ? truncatePath(rootPath.value) : null));

async function onCopyPath(): Promise<void> {
  if (!rootPath.value) return;
  const result = await copyAnswerText(rootPath.value);
  if (result === "ok") {
    notify.success("路径已复制");
  } else if (result === "unavailable") {
    notify.error("复制不可用", "当前环境不支持剪贴板");
  } else {
    notify.error("复制失败", "请手动选择路径复制");
  }
}
</script>

<template>
  <header class="session-header" data-testid="session-header">
    <div class="session-title-row">
      <!-- 顶栏已呈现会话标题（h1）；此处不重复使用 heading 角色 -->
      <div class="session-title" :title="title">{{ title || "新任务" }}</div>
      <span v-if="running" class="session-state state-running" data-testid="session-state">
        <PhCircleNotch :size="12" class="spin" aria-hidden="true" />
        运行中
      </span>
      <span v-else-if="waitingApproval" class="session-state state-warning" data-testid="session-state">
        等待审批
      </span>
    </div>

    <!-- W6-R3：当前授权工作目录 + Git 分支（真实降级状态，不沿用旧值） -->
    <div class="session-facts" data-testid="session-facts">
      <span
        class="workdir"
        data-testid="session-workdir"
        :title="rootPath ?? undefined"
      >
        <PhFolderOpen :size="13" aria-hidden="true" />
        <span v-if="rootPathDisplay" class="workdir-path">{{ rootPathDisplay }}</span>
        <span v-else class="workdir-path is-empty">未授权工作目录</span>
        <button
          v-if="rootPath"
          class="workdir-copy"
          type="button"
          title="复制完整路径"
          aria-label="复制完整路径"
          data-testid="session-workdir-copy"
          @click="onCopyPath"
        >
          <PhCopy :size="12" />
        </button>
      </span>
      <span class="git-chip" :class="gitTone" data-testid="session-git">
        <PhGitBranch :size="13" aria-hidden="true" />
        {{ gitLabel }}
      </span>
    </div>
  </header>
</template>

<style scoped>
.session-header {
  display: flex;
  flex-shrink: 0;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}
.session-title-row {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
}
.session-title {
  overflow: hidden;
  min-width: 0;
  flex: 1;
  color: var(--color-fg);
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-state {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  gap: 4px;
  padding: 2px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  font-size: var(--pa-text-meta);
}
.state-running {
  color: var(--color-accent-soft-fg);
}
.state-warning {
  border-color: color-mix(in srgb, var(--color-warning) 40%, var(--color-border));
  color: var(--color-warning-fg);
}
.session-facts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.workdir {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  gap: var(--space-1);
}
.workdir-path {
  overflow: hidden;
  max-width: 420px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.workdir-path.is-empty {
  color: var(--color-fg-subtle);
}
.workdir-copy {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-fg-subtle);
  cursor: pointer;
}
.workdir-copy:hover {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.git-chip {
  display: inline-flex;
  max-width: 260px;
  align-items: center;
  gap: 4px;
  padding: 2px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-panel);
  white-space: nowrap;
}
.git-chip .ph {
  flex-shrink: 0;
}
.tone-ok {
  color: var(--color-fg-muted);
}
.tone-warning {
  border-color: color-mix(in srgb, var(--color-warning) 40%, var(--color-border));
  color: var(--color-warning-fg);
}
.tone-danger {
  border-color: color-mix(in srgb, var(--color-danger) 40%, var(--color-border));
  color: var(--color-danger-fg);
}
.tone-muted {
  color: var(--color-fg-subtle);
}
.spin {
  animation: session-spin 0.9s linear infinite;
}
@keyframes session-spin {
  to { transform: rotate(360deg); }
}
@media (max-width: 900px) {
  .workdir-path {
    max-width: 220px;
  }
  .git-chip {
    max-width: 180px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}
@media (prefers-reduced-motion: reduce) {
  .spin { animation: none; }
}
</style>
