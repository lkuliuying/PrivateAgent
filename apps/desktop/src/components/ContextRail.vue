<script setup lang="ts">
/**
 * ContextRail v2 · 右侧上下文栏（0.4.0 D3 结构）
 * 四类信息：Files（授权文件/修改/Diff 入口）、Context（会话元信息）、
 * Sources（RAG 来源/引用/可信状态）、Artifacts（文档/代码/图片/报告/导出）。
 * 内容与当前任务绑定；无任务时展示全局占位，不展示无关信息。
 */
import { computed, ref, watch } from "vue";
import {
  PhCaretRight,
  PhCheck,
  PhFile,
  PhFileText,
  PhFolder,
  PhImage,
  PhScroll,
  PhTerminal,
  PhX,
} from "@phosphor-icons/vue";
import type { Activity, AgentToolExecution, Session, Source, TrustedPath } from "../types";
import type { AgentWorkspaceMessage } from "../models/agentWorkspace";
import { formatActivityTime } from "../models/agentWorkspace";
import PaBadge from "../design/PaBadge.vue";
import PaDialog from "../design/PaDialog.vue";
import PaEmptyState from "../design/PaEmptyState.vue";
import PaIconButton from "../design/PaIconButton.vue";
import PaInlineNotice from "../design/PaInlineNotice.vue";
import PaTabs from "../design/PaTabs.vue";
import PaTooltip from "../design/PaTooltip.vue";

type RailTab = "files" | "context" | "sources" | "artifacts";

const props = withDefaults(
  defineProps<{
    session: Session | null;
    messages: AgentWorkspaceMessage[];
    activities: Activity[];
    trusted: TrustedPath[];
    patchResults?: AgentToolExecution[];
    chunkId?: number | null;
  }>(),
  { chunkId: null, activities: () => [], trusted: () => [], patchResults: () => [] }
);

const emit = defineEmits<{ close: []; "select-chunk": [chunkId: number] }>();

const tab = ref<RailTab>("files");

// 会话切换时重置到 Files，避免上下文残留
watch(
  () => props.session?.id,
  () => {
    tab.value = "files";
  }
);

const lastSources = computed<Source[]>(() => {
  for (let i = props.messages.length - 1; i >= 0; i--) {
    const sources = props.messages[i].sources;
    if (sources && sources.length) return sources;
  }
  return [];
});

const artifacts = computed<Activity[]>(() =>
  props.activities.filter(
    (activity) => activity.status === "succeeded" && activity.detail_json
  )
);

const filePaths = computed<{ path: string; kind: "file" | "directory" | "tool" }[]>(() => {
  const entries: { path: string; kind: "file" | "directory" | "tool" }[] = [];
  const seen = new Set<string>();
  for (const path of props.trusted) {
    if (!seen.has(path.path)) {
      seen.add(path.path);
      entries.push({ path: path.path, kind: path.kind });
    }
  }
  for (const message of props.messages) {
    const tool = message.tool_call;
    if (!tool) continue;
    const target =
      typeof tool.input_json?.path === "string"
        ? tool.input_json.path
        : tool.input_json?.files;
    if (typeof target === "string" && !seen.has(target)) {
      seen.add(target);
      entries.push({ path: target, kind: "tool" });
    }
  }
  return entries;
});

/**
 * v0.5.0 B1：文件变更摘要——从活动流提取 apply_patch_to_workspace /
 * propose_patch 的结果（rel_path / verified / diff），标记「已修改」并供 Diff 弹窗。
 */
type FileChange = {
  relPath: string;
  verified: boolean;
  diff: string;
  truncated: boolean;
  at: string;
};

const fileChanges = computed<FileChange[]>(() => {
  const changes: FileChange[] = [];
  const seen = new Set<string>();
  // 事实源 1：v0.5.0 B1 已脱敏持久化的 Runtime 执行结果（apply_patch_to_workspace）
  for (const execution of props.patchResults) {
    if (execution.status !== "succeeded") continue;
    const detail = execution.output ?? {};
    const relPath = detail.rel_path;
    if (typeof relPath !== "string" || !relPath) continue;
    const key = `${relPath}:${String(detail.new_sha256 ?? "")}`;
    if (seen.has(key)) continue;
    seen.add(key);
    changes.push({
      relPath,
      verified: detail.verified === true,
      diff: typeof detail.diff === "string" ? detail.diff : "",
      truncated: detail.truncated === true,
      at: execution.completed_at ?? execution.created_at,
    });
  }
  // 事实源 2：legacy 工具调用结果（兼容路径）
  for (const message of props.messages) {
    const tool = message.tool_call;
    if (!tool || tool.tool_name !== "apply_patch_to_workspace") continue;
    if (tool.status !== "succeeded") continue;
    const detail = tool.output_json ?? {};
    const relPath = detail.rel_path;
    if (typeof relPath !== "string" || !relPath) continue;
    const key = `${relPath}:${String(detail.new_sha256 ?? "")}`;
    if (seen.has(key)) continue;
    seen.add(key);
    changes.push({
      relPath,
      verified: detail.verified === true,
      diff: typeof detail.diff === "string" ? detail.diff : "",
      truncated: detail.truncated === true,
      at: message.created_at,
    });
  }
  return changes;
});

function changeForPath(path: string): FileChange | undefined {
  return fileChanges.value.find((change) => change.relPath === path);
}

const diffDialog = ref<FileChange | null>(null);

function artifactIcon(activity: Activity) {
  const type = String(activity.detail_json?.artifact ?? "");
  if (type === "image") return PhImage;
  if (type === "code") return PhTerminal;
  if (type === "report" || type === "export") return PhFileText;
  return PhFile;
}
</script>

<template>
  <div class="context-rail">
    <header class="context-rail-header">
      <PaTabs
        v-model="tab"
        :items="[
          { key: 'files', label: 'Files' },
          { key: 'context', label: 'Context' },
          { key: 'sources', label: 'Sources', badge: lastSources.length || undefined },
          { key: 'artifacts', label: 'Artifacts', badge: artifacts.length || undefined },
        ]"
      />
      <PaIconButton label="关闭上下文栏" size="sm" @click="emit('close')">
        <PhX :size="15" />
      </PaIconButton>
    </header>

    <div class="context-rail-body">
      <!-- Files -->
      <section v-if="tab === 'files'" class="rail-pane" aria-label="任务文件">
        <template v-if="filePaths.length">
          <ul class="file-list">
            <li v-for="entry in filePaths" :key="entry.path" class="file-item">
              <PhFolder v-if="entry.kind === 'directory'" :size="14" class="file-icon" />
              <PhFile v-else-if="entry.kind === 'file'" :size="14" class="file-icon" />
              <PhScroll v-else :size="14" class="file-icon is-tool" />
              <span class="file-path" :title="entry.path">{{ entry.path }}</span>
              <PaBadge
                v-if="changeForPath(entry.path)"
                tone="success"
                :title="`回读校验${changeForPath(entry.path)?.verified ? '通过' : '未完成'} · ${formatActivityTime(changeForPath(entry.path)?.at ?? '')}`"
              >
                <PhCheck :size="11" />
                已修改
              </PaBadge>
              <PaTooltip
                v-if="changeForPath(entry.path)"
                text="查看变更 Diff"
              >
                <PaIconButton
                  label="查看文件变更"
                  size="sm"
                  variant="subtle"
                  @click="diffDialog = changeForPath(entry.path) ?? null"
                >
                  <PhCaretRight :size="13" />
                </PaIconButton>
              </PaTooltip>
            </li>
          </ul>
          <p class="rail-hint">
            {{ fileChanges.length }} 个文件已修改
            <template v-if="fileChanges.length">
              · 回读校验已核对写入内容；点击「已修改」文件可查看完整 Diff。
            </template>
          </p>
        </template>
        <PaEmptyState
          v-else
          :icon="PhFolder"
          title="尚未授权文件"
          description="Agent 读写文件前会先请求授权，授权路径与修改摘要会显示在这里。"
        />
      </section>

      <!-- Context -->
      <section v-else-if="tab === 'context'" class="rail-pane" aria-label="会话上下文">
        <template v-if="session">
          <div class="context-card">
            <h3>当前任务</h3>
            <p class="context-title">{{ session.title }}</p>
            <dl class="context-meta">
              <div><dt>消息</dt><dd>{{ messages.length }}</dd></div>
              <div><dt>创建</dt><dd>{{ formatActivityTime(session.created_at) }}</dd></div>
              <div><dt>更新</dt><dd>{{ formatActivityTime(session.updated_at) }}</dd></div>
            </dl>
          </div>
          <PaBadge tone="muted">模型与模式信息在设置页维护</PaBadge>
        </template>
        <PaEmptyState
          v-else
          :icon="PhFileText"
          title="没有当前任务"
          description="进入一个 Agent 任务后，这里会展示会话上下文与限制信息。"
        />
      </section>

      <!-- Sources -->
      <section v-else-if="tab === 'sources'" class="rail-pane" aria-label="RAG 来源">
        <template v-if="lastSources.length">
          <ul class="source-list">
            <li
              v-for="source in lastSources"
              :key="source.chunk_id"
              class="source-item"
              :class="{ active: chunkId === source.chunk_id }"
            >
              <button
                class="source-hit"
                :aria-pressed="chunkId === source.chunk_id"
                @click="emit('select-chunk', source.chunk_id)"
              >
                <span class="source-name">{{ source.doc_name }}</span>
                <span class="source-heading" v-if="source.heading">{{ source.heading }}</span>
                <span class="source-score">
                  {{ source.score != null ? `${Math.round(source.score * 100)}%` : "" }}
                </span>
              </button>
              <span v-if="source.matched_via?.length" class="source-via">
                {{ source.matched_via.join(" + ") }}
              </span>
            </li>
          </ul>
        </template>
        <PaEmptyState
          v-else
          :icon="PhScroll"
          title="没有知识库来源"
          description="本回答未使用知识库引用；使用知识检索模式后，来源会显示在这里。"
        />
      </section>

      <!-- Artifacts -->
      <section v-else class="rail-pane" aria-label="产物">
        <template v-if="artifacts.length">
          <ul class="artifact-list">
            <li v-for="activity in artifacts" :key="activity.id" class="artifact-item">
              <component :is="artifactIcon(activity)" :size="16" class="artifact-icon" />
              <span class="artifact-copy">
                <strong>{{ activity.title }}</strong>
                <small>
                  {{ formatActivityTime(activity.finished_at ?? activity.created_at) }}
                  <template v-if="activity.detail_json?.size_bytes">
                    · {{ Math.round(Number(activity.detail_json.size_bytes) / 1024) }} KB
                  </template>
                </small>
              </span>
              <PaBadge tone="success">已生成</PaBadge>
            </li>
          </ul>
        </template>
        <PaEmptyState
          v-else
          :icon="PhFileText"
          title="还没有产物"
          description="任务完成后，文档、代码、图片与导出报表会集中出现在这里。"
        />
      </section>
    </div>

    <PaDialog
      v-if="diffDialog"
      :open="true"
      :title="`变更 Diff · ${diffDialog.relPath}`"
      :width="760"
      @close="diffDialog = null"
    >
      <div class="diff-dialog-body">
        <p class="rail-hint">
          写入后回读校验：<strong>{{
            diffDialog.verified ? "通过（磁盘内容与审批参数一致）" : "未通过或未知"
          }}</strong>
          · {{ formatActivityTime(diffDialog.at) }}
        </p>
        <pre class="diff-dialog-pre">{{ diffDialog.diff }}</pre>
        <PaInlineNotice
          v-if="diffDialog.truncated"
          tone="warning"
          title="Diff 预览曾被截断"
        >
          展示内容不完整；实际写入以审批时绑定参数的原始内容为准。
        </PaInlineNotice>
      </div>
    </PaDialog>
  </div>
</template>

<style scoped>
.context-rail {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
}
.context-rail-header {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2) 0;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}
.context-rail-header :deep(.pa-tabs) {
  min-width: 0;
  flex: 1;
  border-bottom: none;
}
.context-rail-header :deep(.pa-tab) {
  padding: 0 var(--space-2);
  font-size: var(--pa-text-compact);
}
.context-rail-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
}
.rail-pane {
  display: flex;
  min-height: 100%;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
}
.file-list,
.source-list,
.artifact-list {
  display: flex;
  margin: 0;
  padding: 0;
  flex-direction: column;
  gap: var(--space-2);
  list-style: none;
}
.file-item {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-1);
  border-radius: var(--radius-md);
}
.file-item:hover {
  background: var(--color-surface-hover);
}
.file-icon {
  flex-shrink: 0;
  color: var(--color-fg-faint);
}
.file-icon.is-tool {
  color: var(--color-accent-soft-fg);
}
.file-path {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  color: var(--color-fg-muted);
  font-family: var(--font-mono);
  font-size: var(--pa-text-mono);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rail-hint {
  margin: 0;
  color: var(--color-fg-faint);
  font-size: var(--pa-text-meta);
  line-height: var(--leading-normal);
}
.context-card {
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.context-card h3 {
  margin: 0 0 var(--space-1);
  color: var(--color-fg-faint);
  font-size: var(--pa-t-11);
  font-weight: var(--font-semibold);
  letter-spacing: 0.06em;
}
.context-title {
  margin: 0 0 var(--space-3);
  color: var(--color-fg);
  font-size: var(--pa-text-compact);
  font-weight: var(--font-medium);
  line-height: var(--leading-normal);
}
.context-meta {
  display: grid;
  margin: 0;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-2);
}
.context-meta div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.context-meta dt {
  color: var(--color-fg-faint);
  font-size: var(--pa-t-11);
}
.context-meta dd {
  margin: 0;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.source-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.source-item.active {
  border-color: var(--color-accent);
}
.source-hit {
  display: flex;
  width: 100%;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
  padding: 0;
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.source-hit:focus-visible {
  outline: none;
  box-shadow: inset var(--focus-ring);
}
.source-name {
  overflow: hidden;
  color: var(--color-fg);
  font-size: var(--pa-text-compact);
  font-weight: var(--font-medium);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.source-heading {
  overflow: hidden;
  color: var(--color-fg-faint);
  font-size: var(--pa-t-11);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.source-score {
  align-self: flex-start;
  color: var(--color-accent-soft-fg);
  font-size: var(--pa-t-11);
}
.source-via {
  color: var(--color-fg-faint);
  font-size: var(--pa-t-11);
}
.artifact-item {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.artifact-icon {
  flex-shrink: 0;
  color: var(--color-success-fg);
}
.artifact-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 1px;
}
.artifact-copy strong {
  overflow: hidden;
  color: var(--color-fg);
  font-size: var(--pa-text-compact);
  font-weight: var(--font-medium);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.artifact-copy small {
  color: var(--color-fg-faint);
  font-size: var(--pa-t-11);
}
.diff-dialog-body {
  display: grid;
  gap: var(--space-3);
}
.diff-dialog-pre {
  margin: 0;
  max-height: 60vh;
  overflow: auto;
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background: var(--color-surface-sunken);
  color: var(--color-fg-muted);
  font-family: var(--font-mono);
  font-size: var(--pa-text-mono);
  line-height: 1.55;
  white-space: pre;
}
</style>
