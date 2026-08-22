<script setup lang="ts">
/**
 * CodingHome · v0.8.0 W1
 *
 * W0 冻结 §2.1 首页：项目/workspace 选择 + 主任务输入 + 推荐任务 +
 * 空态与配置错误引导。六状态（W0 矩阵 §3 第 1–6 项）由 store.homeState
 * 派生，本组件只呈现与发起动作；W1 的输入提交创建 coding 线程，
 * 首轮消息与 run 流在 W2 接入（CodingComposer 在 W3 交付）。
 */
import { computed, ref } from "vue";
import {
  PhArrowRight,
  PhFolderPlus,
  PhFolderSimple,
  PhGitBranch,
  PhLightning,
} from "@phosphor-icons/vue";
import type { View } from "../../../types";
import PaButton from "../../../design/PaButton.vue";
import PaEmptyState from "../../../design/PaEmptyState.vue";
import PaErrorState from "../../../design/PaErrorState.vue";
import PaInlineNotice from "../../../design/PaInlineNotice.vue";
import PaSelect from "../../../design/PaSelect.vue";
import PaSkeleton from "../../../design/PaSkeleton.vue";
import type {
  CodingApiError,
  CodingThreadSummary,
} from "../model/contracts";
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
  "thread-created": [thread: CodingThreadSummary];
}>();

const homeState = computed(() => props.store.homeState.value);
const projects = computed(() => props.store.projects.value);
const selectedProjectId = computed(() => props.store.selectedProjectId.value);
const selectedWorkspaceId = computed(() => props.store.selectedWorkspaceId.value);
const selectedWorkspace = computed(() => props.store.selectedWorkspace.value);
const loadError = computed(() => props.store.loadError.value);

const projectOptions = computed(() =>
  projects.value.map((project) => ({ value: project.id, label: project.name }))
);

const workspaceOptions = computed(() => {
  const projectId = selectedProjectId.value;
  if (projectId === null) return [];
  return (props.store.workspacesByProject.value[projectId] ?? []).map((workspace) => ({
    value: workspace.id,
    label:
      workspace.branchName ?? (workspace.kind === "root" ? "根工作区" : "工作区") +
      (WORKSPACE_STATUS_META[workspace.status].tone === "neutral"
        ? ""
        : ` · ${WORKSPACE_STATUS_META[workspace.status].label}`),
  }));
});

function onProjectChange(value: string | number): void {
  props.store.selectProject(Number(value));
}

function onWorkspaceChange(value: string | number): void {
  props.store.selectWorkspace(Number(value));
}

// 主任务输入：Enter 提交（Shift+Enter 换行）；W1 只创建线程
const taskInput = ref("");
const creating = ref(false);
const createError = ref<CodingApiError | null>(null);

async function submitTask(): Promise<void> {
  if (creating.value || !taskInput.value.trim()) return;
  creating.value = true;
  createError.value = null;
  try {
    const thread = await props.store.createThreadFromInput(taskInput.value);
    taskInput.value = "";
    emit("thread-created", thread);
  } catch (cause) {
    createError.value = asCodingApiError(cause);
  } finally {
    creating.value = false;
  }
}

function onInputKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void submitTask();
  }
}

/** 推荐任务模板（本地静态；不虚构后端状态，仅作为输入预填） */
const TASK_TEMPLATES = [
  "梳理项目结构，总结各模块职责",
  "找出失败的测试并修复",
  "审查最近的改动并给出风险提示",
  "为当前模块补充单元测试",
];

function applyTemplate(template: string): void {
  taskInput.value = template;
}

// 「有项目无 workspace」引导：幂等补建根工作区
const ensuring = ref(false);
const ensureError = ref("");

async function ensureWorkspace(): Promise<void> {
  const projectId = selectedProjectId.value ?? projects.value[0]?.id;
  if (projectId === null || ensuring.value) return;
  ensuring.value = true;
  ensureError.value = "";
  try {
    await props.store.ensureWorkspaceForProject(projectId);
  } catch (cause) {
    ensureError.value = asCodingApiError(cause).message;
  } finally {
    ensuring.value = false;
  }
}

function asCodingApiError(cause: unknown): CodingApiError {
  const error = cause as CodingApiError;
  if (error && typeof error.status === "number" && typeof error.code === "string") {
    return error;
  }
  return { status: 0, code: "network_error", message: "本地服务连接失败，请稍后重试" };
}
</script>

<template>
  <section class="coding-home" data-testid="coding-home">
    <div class="home-column" :data-testid="`coding-home-${homeState}`">
      <PaSkeleton v-if="homeState === 'loading'" :lines="5" />

      <PaErrorState
        v-else-if="homeState === 'sidecar-unavailable'"
        title="本地后端未就绪"
        message="无法连接本地 sidecar。本地数据不受影响，可稍后重试。"
        retry-label="重试连接"
        data-testid="coding-home-retry"
        @retry="props.store.refresh()"
      />

      <PaErrorState
        v-else-if="homeState === 'load-error'"
        :message="loadError?.message || '项目信息加载失败'"
        @retry="props.store.refresh()"
      />

      <PaEmptyState
        v-else-if="homeState === 'no-projects'"
        :icon="PhFolderPlus"
        title="还没有项目"
        description="先在项目页添加一个本地项目文件夹并授权，之后就可以在这里直接发起 Coding 任务。"
      >
        <PaButton variant="primary" @click="emit('navigate', 'projects')">打开项目页</PaButton>
      </PaEmptyState>

      <template v-else-if="homeState === 'no-workspace'">
        <PaEmptyState
          :icon="PhFolderSimple"
          title="项目还没有可用工作区"
          description="Coding 任务在项目工作区中执行。可为项目创建根工作区（对应默认分支的仓库根目录）。"
        >
          <PaButton variant="primary" :loading="ensuring" @click="ensureWorkspace()">
            创建根工作区
          </PaButton>
        </PaEmptyState>
        <PaInlineNotice
          v-if="ensureError"
          tone="danger"
          title="创建失败"
          class="home-notice"
        >
          {{ ensureError }}
        </PaInlineNotice>
      </template>

      <template v-else-if="homeState === 'provider-unconfigured'">
        <PaEmptyState
          :icon="PhLightning"
          title="模型 Provider 未配置"
          description="Coding 任务需要可用的模型 profile。请先在设置中配置本地或远程 Provider。"
        >
          <PaButton variant="primary" @click="emit('navigate', 'settings')">前往设置</PaButton>
        </PaEmptyState>
      </template>

      <template v-else-if="homeState === 'workspace-invalid'">
        <PaEmptyState
          :icon="PhGitBranch"
          title="当前工作区状态异常"
          :description="`工作区「${selectedWorkspace ? (selectedWorkspace.branchName ?? '根工作区') : ''}」当前不可用（${
            selectedWorkspace ? WORKSPACE_STATUS_META[selectedWorkspace.status].label : '状态未知'
          }）。请检查路径授权或 Git 状态后重试。`"
        >
          <PaButton variant="primary" @click="emit('navigate', 'projects')">打开项目页</PaButton>
        </PaEmptyState>
      </template>

      <template v-else>
        <header class="home-header">
          <p class="home-kicker">CODING WORKBENCH</p>
          <h1>开始一个新任务</h1>
          <p class="home-sub">选择项目与分支，描述要完成的事情；执行计划与审批都会逐步展示。</p>
        </header>

        <div class="home-selectors">
          <label class="selector">
            <span>项目</span>
            <PaSelect
              :model-value="selectedProjectId ?? ''"
              :options="projectOptions"
              data-testid="coding-home-project-select"
              @update:model-value="onProjectChange"
            />
          </label>
          <label class="selector">
            <span>工作区 / 分支</span>
            <PaSelect
              :model-value="selectedWorkspaceId ?? ''"
              :options="workspaceOptions"
              data-testid="coding-home-workspace-select"
              @update:model-value="onWorkspaceChange"
            />
          </label>
        </div>

        <div class="home-composer">
          <textarea
            v-model="taskInput"
            class="home-input"
            data-testid="coding-home-input"
            rows="3"
            placeholder="描述要完成的任务，例如：修复登录页在窄屏下的布局问题…"
            :disabled="creating"
            @keydown="onInputKeydown"
          />
          <div class="composer-row">
            <span class="composer-hint">Enter 发送 · Shift+Enter 换行</span>
            <button
              class="pa-btn pa-btn--primary home-submit"
              data-testid="coding-home-submit"
              :disabled="creating || !taskInput.trim()"
              @click="submitTask()"
            >
              <template v-if="creating">创建中…</template>
              <template v-else>创建任务</template>
              <PhArrowRight v-if="!creating" :size="15" />
            </button>
          </div>
        </div>

        <PaInlineNotice
          v-if="createError"
          tone="danger"
          title="任务创建失败"
          class="home-notice"
        >
          {{ createError.message }}
        </PaInlineNotice>

        <section class="home-templates" aria-labelledby="home-templates-title">
          <h2 id="home-templates-title">推荐任务</h2>
          <div class="template-list">
            <button
              v-for="(template, index) in TASK_TEMPLATES"
              :key="template"
              class="template-chip"
              :data-testid="`coding-home-template-${index}`"
              @click="applyTemplate(template)"
            >
              {{ template }}
            </button>
          </div>
        </section>
      </template>
    </div>
  </section>
</template>

<style scoped>
.coding-home {
  display: flex;
  flex: 1;
  min-height: 0;
  justify-content: center;
  overflow-y: auto;
  padding: var(--space-8) var(--space-6) var(--space-10);
}
.home-column {
  display: flex;
  width: 100%;
  max-width: 720px;
  flex-direction: column;
  gap: var(--space-4);
}

.home-header {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.home-kicker {
  margin: 0;
  color: var(--color-accent-soft-fg);
  font-size: var(--pa-text-meta);
  font-weight: var(--font-semibold);
  letter-spacing: 0.12em;
}
.home-header h1 {
  margin: 0;
  color: var(--color-fg);
  font-size: var(--text-2xl);
  font-weight: var(--font-semibold);
}
.home-sub {
  margin: 0;
  color: var(--color-fg-subtle);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
}

.home-selectors {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}
.selector {
  display: flex;
  min-width: 220px;
  flex: 1;
  flex-direction: column;
  gap: var(--space-1);
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
}

.home-composer {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}
.home-input {
  width: 100%;
  resize: vertical;
  min-height: 72px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-fg);
  font-size: var(--text-sm);
  font-family: inherit;
  line-height: var(--leading-normal);
}
.home-input:focus-visible {
  outline: var(--focus-ring);
  outline-offset: 0;
}
.composer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.composer-hint {
  color: var(--color-fg-faint);
  font-size: var(--pa-text-meta);
}
.home-submit {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.home-notice {
  margin-top: var(--space-1);
}

.home-templates {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
.home-templates h2 {
  margin: 0;
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
}
.template-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.template-chip {
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
  cursor: pointer;
}
.template-chip:hover {
  border-color: color-mix(in srgb, var(--color-accent) 40%, var(--color-border));
  color: var(--color-accent-soft-fg);
}

@media (max-width: 600px) {
  .coding-home {
    padding: var(--space-5) var(--space-4);
  }
  .home-selectors {
    flex-direction: column;
  }
}
</style>
