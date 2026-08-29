<script setup lang="ts">
/**
 * CodingHome · v0.8.0 W1
 *
 * W0 冻结 §2.1 首页：项目/workspace 选择 + 主任务输入 + 推荐任务 +
 * 空态与配置错误引导。六状态（W0 矩阵 §3 第 1–6 项）由 store.homeState
 * 派生，本组件只呈现与发起动作；W1 的输入提交创建 coding 线程，
 * 首轮消息与 run 流在 W2 接入（CodingComposer 在 W3 交付）。
 */
import { computed, ref, watch } from "vue";
import {
  PhChatsCircle,
  PhDownloadSimple,
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
  CodingProfileImportStatus,
  CodingThreadSummary,
} from "../model/contracts";
import { WORKSPACE_STATUS_META } from "../model/contracts";
import { useCodingWorkspace, type CodingWorkspaceStore } from "../model/codingWorkspaceStore";
import {
  fetchCodingProfileImportStatus,
  importCodingModelProfile,
} from "../api/modelProfiles";
import CodingComposer, { type CodingComposerSendPayload } from "./CodingComposer.vue";
// v0.9.0 H1：新建项目对话框（选目录+授权；空态与侧栏共用）
import NewProjectDialog from "./NewProjectDialog.vue";

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
  /**
   * v0.9.0 H1-D（§5.8）：进入同一模型管理区（带 returnTo，由 App 接线；
   * 往返保留项目/会话/草稿，保存后原位解除阻塞）。
   */
  "configure-provider": [];
}>();

const homeState = computed(() => props.store.homeState.value);

// v0.9.0 H1-D（§5.8）：拆分笼统的「模型 Provider 未配置」：
// feature_disabled = 能力位关闭；profile_missing = 有配置但无 Coding profile。
const profileBlocker = computed<"feature_disabled" | "profile_missing" | null>(() => {
  if (homeState.value !== "provider-unconfigured") return null;
  const result = props.store.modelProfiles.value;
  return result?.status === "disabled" ? "feature_disabled" : "profile_missing";
});

// 一次性导入向导：旧全局配置 → 默认 Coding profile（幂等；失败显示精确原因）
const importState = ref<CodingProfileImportStatus | null>(null);
const importing = ref(false);
const importError = ref("");

watch(
  profileBlocker,
  async (blocker) => {
    importError.value = "";
    if (blocker !== "profile_missing") {
      importState.value = null;
      return;
    }
    try {
      importState.value = await fetchCodingProfileImportStatus();
    } catch {
      importState.value = null;
    }
  },
  { immediate: true }
);

const importPossible = computed(() => {
  const state = importState.value;
  if (!state) return false;
  return state.importState === "pending" || state.importState === "wizard";
});

function importErrorText(error: unknown): string {
  if (error && typeof error === "object") {
    const coded = error as { code?: unknown; message?: unknown };
    const message = typeof coded.message === "string" ? coded.message : "";
    switch (coded.code) {
      case "provider_unreachable":
        return "Provider 不可达：请确认 Ollama 已启动后重试。";
      case "model_missing":
        return "Provider 可达，但配置的模型不存在：请先拉取模型或修改配置。";
      case "credentials_missing":
        return "远程凭据缺失：请先在设置中配置系统凭据。";
      case "feature_disabled":
        return "远程 Provider 未启用：请先在设置中开启。";
      case "no_global_provider":
        return "全局 Provider 尚未配置模型：请先在设置中配置。";
      default:
        return message || "导入失败，请重试";
    }
  }
  return "导入失败，请重试";
}

async function onImportProfile(): Promise<void> {
  if (importing.value) return;
  importing.value = true;
  importError.value = "";
  try {
    await importCodingModelProfile();
    await props.store.refresh();
  } catch (error) {
    importError.value = importErrorText(error);
  } finally {
    importing.value = false;
  }
}
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

// 新对话保持草稿态；用户首次发送时才创建 durable 会话并进入任务页。
const creating = ref(false);
const createError = ref<CodingApiError | null>(null);
const restoreRequest = ref<{ message: string; seq: number } | null>(null);
let restoreSeq = 0;

// v0.9.0 H1：空态新建项目对话框；创建成功后刷新并选中新项目。
const newProjectOpen = ref(false);

async function onProjectCreated(projectId: number): Promise<void> {
  newProjectOpen.value = false;
  await props.store.refresh();
  if (projectId > 0) props.store.selectProject(projectId);
}

async function submitFirstTurn(payload: CodingComposerSendPayload): Promise<void> {
  if (creating.value || !payload.message.trim()) return;
  creating.value = true;
  createError.value = null;
  try {
    const thread = await props.store.createThreadFromFirstTurn(payload);
    emit("thread-created", thread);
  } catch (cause) {
    createError.value = asCodingApiError(cause);
    restoreSeq += 1;
    restoreRequest.value = { message: payload.message, seq: restoreSeq };
  } finally {
    creating.value = false;
  }
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
  <section class="coding-home" :class="{ 'is-ready': homeState === 'ready' }" data-testid="coding-home">
    <div class="home-column" :class="{ 'is-ready': homeState === 'ready' }" :data-testid="`coding-home-${homeState}`">
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
        description="新建项目需要选择并授权一个工作目录；也可以选择内置的「当前用户目录」候选快速开始（不会自动扩大授权）。项目就绪后就可以在这里发起对话。"
      >
        <PaButton variant="primary" data-testid="home-new-project" @click="newProjectOpen = true">新建项目</PaButton>
        <PaButton variant="ghost" @click="emit('navigate', 'projects')">打开项目页</PaButton>
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
        <!-- v0.9.0 H1-D（§5.8）：能力位关闭与 profile 缺失分别呈现 -->
        <PaEmptyState
          v-if="profileBlocker === 'feature_disabled'"
          :icon="PhLightning"
          title="模型能力未开启"
          description="Runtime 未启用 Coding 模型能力位（或版本过旧）。请更新 Runtime 或在配置中启用后重试。"
        >
          <PaButton variant="primary" data-testid="home-provider-retry" @click="props.store.refresh()">重试</PaButton>
          <PaButton variant="ghost" @click="emit('configure-provider')">前往设置</PaButton>
        </PaEmptyState>
        <PaEmptyState
          v-else
          :icon="PhLightning"
          title="尚无 Coding 模型"
          description="Coding 任务需要一个模型 profile（具体模型标识与能力声明）。可一键导入当前全局配置，或在设置中创建并验证。"
        >
          <PaButton
            v-if="importPossible"
            variant="primary"
            data-testid="home-provider-import"
            :loading="importing"
            @click="void onImportProfile()"
          >
            <PhDownloadSimple :size="14" aria-hidden="true" />
            验证并导入当前模型配置
          </PaButton>
          <PaButton
            :variant="importPossible ? 'ghost' : 'primary'"
            data-testid="home-provider-create"
            @click="emit('configure-provider')"
          >创建 Coding 模型</PaButton>
          <PaButton variant="ghost" @click="emit('configure-provider')">前往设置</PaButton>
        </PaEmptyState>
        <PaInlineNotice
          v-if="importError"
          tone="danger"
          title="导入未完成"
          class="home-notice"
          data-testid="home-provider-import-error"
        >
          {{ importError }}
        </PaInlineNotice>
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
        <div class="draft-stage">
          <div class="draft-empty" data-testid="coding-home-empty-chat">
            <PhChatsCircle :size="48" weight="thin" aria-hidden="true" />
            <h1>你想在 {{ props.store.selectedProject.value?.name ?? "当前项目" }} 中构建什么？</h1>
            <p>选择项目与分支，然后直接输入第一条指令。</p>
          </div>

          <div class="draft-dock">
            <div class="draft-selectors">
              <label class="draft-selector">
                <PhFolderSimple :size="16" aria-hidden="true" />
                <span class="visually-hidden">项目</span>
                <PaSelect
                  :model-value="selectedProjectId ?? ''"
                  :options="projectOptions"
                  size="sm"
                  data-testid="coding-home-project-select"
                  aria-label="项目"
                  @update:model-value="onProjectChange"
                />
              </label>
              <label class="draft-selector">
                <PhGitBranch :size="16" aria-hidden="true" />
                <span class="visually-hidden">工作区 / 分支</span>
                <PaSelect
                  :model-value="selectedWorkspaceId ?? ''"
                  :options="workspaceOptions"
                  size="sm"
                  data-testid="coding-home-workspace-select"
                  aria-label="工作区 / 分支"
                  @update:model-value="onWorkspaceChange"
                />
              </label>
            </div>
            <CodingComposer
              :store="store"
              :thread-id="null"
              :busy="creating"
              :restore-request="restoreRequest"
              @send="submitFirstTurn"
            />
            <PaInlineNotice
              v-if="createError"
              tone="danger"
              title="对话创建失败"
              class="home-notice"
            >
              {{ createError.message }}
            </PaInlineNotice>
          </div>
        </div>
      </template>
    </div>

    <!-- v0.9.0 H1：新建项目对话框（选择并授权工作目录 / 用户目录候选） -->
    <NewProjectDialog
      v-if="newProjectOpen"
      @close="newProjectOpen = false"
      @created="(id) => void onProjectCreated(id)"
    />
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
.coding-home.is-ready {
  padding: 0;
  overflow: hidden;
}
.home-column {
  display: flex;
  width: 100%;
  max-width: 720px;
  flex-direction: column;
  gap: var(--space-4);
}
.home-column.is-ready {
  max-width: none;
  gap: 0;
}

.home-notice {
  margin: 0 var(--space-2) var(--space-2);
}
.draft-stage {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
}
.draft-empty {
  display: flex;
  min-height: 240px;
  flex: 1;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-8);
  color: var(--color-fg-faint);
  text-align: center;
}
.draft-empty h1 {
  margin: 0;
  color: var(--color-fg);
  font-size: var(--text-xl);
  font-weight: var(--font-medium);
}
.draft-empty p {
  margin: 0;
  color: var(--color-fg-subtle);
  font-size: var(--text-sm);
}
.draft-dock {
  width: min(820px, calc(100% - 32px));
  margin: 0 auto var(--space-4);
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}
.draft-selectors {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3) 0;
}
.draft-selector {
  display: inline-flex;
  min-width: 190px;
  align-items: center;
  gap: var(--space-1);
  color: var(--color-fg-muted);
}
.draft-selector:nth-child(2) { min-width: 250px; }
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  clip-path: inset(50%);
}

@media (max-width: 600px) {
  .coding-home:not(.is-ready) {
    padding: var(--space-5) var(--space-4);
  }
  .draft-dock {
    width: calc(100% - 20px);
    margin-bottom: var(--space-2);
  }
  .draft-selectors {
    align-items: stretch;
    flex-direction: column;
    gap: var(--space-1);
  }
}
</style>
