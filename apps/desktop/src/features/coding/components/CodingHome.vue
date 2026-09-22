<script setup lang="ts">
/**
 * CodingHome · v0.8.0 W1
 *
 * W0 冻结 §2.1 首页：项目/workspace 选择 + 主任务输入 + 推荐任务 +
 * 空态与配置错误引导。六状态（W0 矩阵 §3 第 1–6 项）由 store.homeState
 * 派生，本组件只呈现与发起动作；W1 的输入提交创建 coding 线程，
 * 首轮消息与 run 流在 W2 接入（CodingComposer 在 W3 交付）。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  PhArrowRight,
  PhBookOpen,
  PhCode,
  PhDownloadSimple,
  PhFolderPlus,
  PhFolderSimple,
  PhGitBranch,
  PhLightning,
  PhWrench,
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
import heroImage from "../../../assets/companion/home-hero.png";
import { useLocalProfile } from "../../../services/localProfile";

const { profile } = useLocalProfile();

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
const projectCards = computed(() => projects.value.filter((project) => project.status === "active").slice(0, 3));
function projectBranch(projectId: number): string {
  const branches = props.store.branchesByProject.value[projectId];
  return branches?.currentBranch ?? props.store.workspacesByProject.value[projectId]?.find((workspace) => workspace.kind === "root")?.branchName ?? "本机工作区";
}
const selectedProjectId = computed(() => props.store.selectedProjectId.value);
const selectedWorkspaceId = computed(() => props.store.selectedWorkspaceId.value);
const selectedBranchName = computed(() => props.store.selectedBranchName.value);
const selectedWorkspace = computed(() => props.store.selectedWorkspace.value);
const loadError = computed(() => props.store.loadError.value);

const projectOptions = computed(() =>
  projects.value.map((project) => ({ value: project.id, label: project.name }))
);

const workspaceOptions = computed(() => {
  const projectId = selectedProjectId.value;
  if (projectId === null) return [];
  const branchState = props.store.branchesByProject.value[projectId];
  if (branchState?.isGit && branchState.branches.length) {
    return [...branchState.branches.map((branch) => ({
      value: `branch:${branch.name}`,
      label: branch.name,
    })), ...(props.store.workspacesByProject.value[projectId] ?? []).filter(w => w.kind === "git_worktree" && w.status !== "archived").map(w => ({ value: w.id, label: `独立 worktree · ${w.id}` }))];
  }
  return (props.store.workspacesByProject.value[projectId] ?? []).map((workspace) => ({
    value: workspace.id,
    label:
      workspace.branchName ?? (workspace.kind === "root" ? "根工作区" : "工作区") +
      (WORKSPACE_STATUS_META[workspace.status].tone === "neutral"
        ? ""
        : ` · ${WORKSPACE_STATUS_META[workspace.status].label}`),
  }));
});

const workspaceSelection = computed(() =>
  selectedWorkspace.value?.kind === "git_worktree" ? selectedWorkspaceId.value ?? "" : selectedBranchName.value ? `branch:${selectedBranchName.value}` : (selectedWorkspaceId.value ?? "")
);

function onProjectChange(value: string | number): void {
  props.store.selectProject(Number(value));
}

const branchSwitching = ref(false);
const branchSwitchError = ref("");

async function onWorkspaceChange(value: string | number): Promise<void> {
  if (typeof value === "string" && value.startsWith("branch:")) {
    if (branchSwitching.value) return;
    branchSwitching.value = true;
    branchSwitchError.value = "";
    try {
      await props.store.selectBranch(value.slice("branch:".length));
    } catch (cause) {
      branchSwitchError.value = asCodingApiError(cause).message;
    } finally {
      branchSwitching.value = false;
    }
    return;
  }
  props.store.selectWorkspace(Number(value));
}

// 新对话保持草稿态；用户首次发送时才创建 durable 会话并进入任务页。
const creating = ref(false);
const starters = [
  { label: "读懂项目", description: "梳理代码结构，快速了解项目", icon: PhBookOpen, prompt: "请先阅读项目说明与目录，解释核心模块、运行方式和关键数据流，并指出需要确认的事项。" },
  { label: "修复问题", description: "分析报错并提供修复方案", icon: PhWrench, prompt: "请先定位并复现以下问题，再以最小改动修复，并运行相关验证：\n" },
  { label: "审查改动", description: "检查代码变更，给出改进建议", icon: PhCode, prompt: "请审查当前工作区的未提交改动，按影响排序列出可复现的问题，附文件和行号。先不要修改文件。" },
];
function useStarter(prompt: string) { restoreRequest.value = { message: prompt, seq: ++restoreSeq }; }

const createError = ref<CodingApiError | null>(null);
const restoreRequest = ref<{ message: string; seq: number } | null>(null);
let restoreSeq = 0;
const draftDock = ref<HTMLElement | null>(null);
let resizeFrame = 0;
function keepEditingVisible(): void {
  if (!draftDock.value?.contains(document.activeElement)) return;
  cancelAnimationFrame(resizeFrame);
  // 卡片在窄窗口换行后，继续保留正在编辑的输入区和发送按钮。
  resizeFrame = requestAnimationFrame(() => draftDock.value?.scrollIntoView({ block: "end", inline: "nearest" }));
}
onMounted(() => window.addEventListener("resize", keepEditingVisible));
onBeforeUnmount(() => {
  window.removeEventListener("resize", keepEditingVisible);
  cancelAnimationFrame(resizeFrame);
});

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
      <header class="home-hero" data-testid="home-hero">
        <img :src="heroImage" class="home-hero__art" alt="" fetchpriority="high" />
        <div class="home-hero__copy">
          <p class="home-hero__greeting">你好，{{ profile.nickname || '开发者' }}</p>
          <h1>让 AI 成为你<br />最可靠的<span>开发搭档</span></h1>
          <p class="home-hero__description">在本地项目中，一起阅读代码、修改文件、验证想法。</p>
        </div>
      </header>
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
          <PaButton variant="primary" @click="newProjectOpen = true">新建项目</PaButton>
        </PaEmptyState>
      </template>

      <template v-else>
        <div class="draft-stage" data-testid="coding-home-empty-chat">
          <section class="home-projects" aria-labelledby="home-projects-title">
            <div class="home-section-heading">
              <h2 id="home-projects-title">继续你的项目</h2>
              <PaButton variant="ghost" @click="newProjectOpen = true"><PhFolderSimple :size="17" />打开项目</PaButton>
            </div>
            <div class="home-project-grid">
              <button v-for="project in projectCards" :key="project.id" type="button" class="home-project" :class="{ 'is-selected': project.id === selectedProjectId }" :aria-pressed="project.id === selectedProjectId" :data-testid="`home-project-${project.id}`" :disabled="creating" @click="onProjectChange(project.id)">
                <span class="home-project__icon"><PhFolderSimple :size="25" aria-hidden="true" /></span>
                <span class="home-project__copy"><strong :title="project.name">{{ project.name }}</strong><span>本机项目</span><span class="home-project__branch"><PhGitBranch :size="13" aria-hidden="true" />{{ projectBranch(project.id) }}</span></span>
              </button>
            </div>
          </section>
          <div class="task-starters" aria-label="任务示例">
            <button v-for="item in starters" :key="item.label" type="button" class="task-starter" :aria-label="item.label" :disabled="creating" @click="useStarter(item.prompt)">
              <span class="task-starter__icon"><component :is="item.icon" :size="23" aria-hidden="true" /></span>
              <span class="task-starter__copy"><strong>{{ item.label }}</strong><span>{{ item.description }}</span></span>
              <PhArrowRight :size="17" aria-hidden="true" />
            </button>
          </div>

          <div ref="draftDock" class="draft-dock">
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
                  :model-value="workspaceSelection"
                  :options="workspaceOptions"
                  size="sm"
                  data-testid="coding-home-workspace-select"
                  aria-label="工作区 / 分支"
                  @update:model-value="void onWorkspaceChange($event)"
                />
              </label>
            </div>
            <PaInlineNotice
              v-if="branchSwitchError"
              tone="danger"
              title="分支切换未完成"
              data-testid="coding-home-branch-error"
            >
              {{ branchSwitchError }}
            </PaInlineNotice>
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
  padding: 0 var(--space-6) var(--space-4);
}
.coding-home.is-ready {
  overflow-y: auto;
}
.home-column {
  display: flex;
  width: 100%;
  max-width: var(--pa-page-max-w);
  flex-direction: column;
  gap: var(--space-6);
}
.home-column.is-ready {
  min-height: min-content;
  gap: var(--space-6);
}

.home-notice {
  margin: 0 var(--space-2) var(--space-2);
}
.draft-stage {
  display: flex;
  min-height: 0;
  flex: 1 0 auto;
  flex-direction: column;
  justify-content: space-between;
  gap: var(--space-4);
}
.draft-dock {
  width: 100%;
  margin: 0;
  overflow: visible;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow);
}
.draft-dock:focus-within { border-color: var(--color-accent); }
.home-hero { position: relative; display: flex; align-items: center; min-height: clamp(280px, 34vh, 350px); flex-shrink: 0; overflow: hidden; border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-hero-bg); }
.home-hero__art { position: absolute; inset: 0; width: 100%; height: 116%; top: -8%; object-fit: contain; object-position: right center; mask-image: linear-gradient(to right, transparent, #000 32%); }
.home-hero__copy { position: relative; z-index: 1; width: 55%; padding: var(--space-8); color: var(--color-hero-fg); }
.home-hero__greeting { overflow: hidden; margin: 0 0 var(--space-4); color: var(--color-hero-muted); font-size: var(--pa-text-body); text-overflow: ellipsis; white-space: nowrap; }
.home-hero h1 { margin: 0; font-size: var(--pa-text-hero); font-weight: 700; line-height: 1.35; letter-spacing: -.035em; }
.home-hero h1 span { color: var(--color-hero-accent); }
.home-hero__description { max-width: 370px; margin: var(--space-4) 0 0; font-size: var(--pa-text-body); line-height: 1.7; color: var(--color-hero-muted); }
.home-section-heading { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-3); }
.home-section-heading h2 { margin: 0; font-size: var(--pa-text-section); font-weight: var(--font-semibold); }
.home-project-grid, .task-starters { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); }
.home-project, .task-starter { display: flex; min-width: 0; align-items: center; gap: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); color: var(--color-fg); text-align: left; cursor: pointer; transition: border-color var(--pa-motion-fast), background var(--pa-motion-fast); }
.home-project { min-height: 128px; padding: var(--space-4); }
.home-project:hover, .task-starter:hover { border-color: var(--color-accent); background: var(--color-surface-hover); }
.home-project.is-selected { border-color: color-mix(in srgb, var(--color-accent) 40%, var(--color-border)); }
.home-project:focus-visible, .task-starter:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; }
.home-project:disabled, .task-starter:disabled { cursor: default; opacity: .55; }
.home-project__icon, .task-starter__icon { display: grid; flex-shrink: 0; place-items: center; border-radius: var(--radius-lg); background: var(--color-accent-soft); color: var(--color-accent-soft-fg); }
.home-project__icon { width: 48px; height: 48px; }
.home-project__copy, .task-starter__copy { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: var(--space-1); }
.home-project__copy strong, .task-starter__copy strong { overflow: hidden; font-size: 16px; text-overflow: ellipsis; white-space: nowrap; }
.home-project__copy > span, .task-starter__copy > span { overflow: hidden; color: var(--color-fg-subtle); font-size: var(--pa-text-compact); text-overflow: ellipsis; white-space: nowrap; }
.home-project__branch { display: flex; align-items: center; gap: var(--space-1); margin-top: var(--space-1); }
.task-starter { min-height: 84px; padding: var(--space-3); }
.task-starter > svg { flex-shrink: 0; color: var(--color-fg-muted); }
.task-starter__icon { width: 40px; height: 40px; }
.draft-dock :deep(.coding-composer) { min-height: 176px; border: 0; box-shadow: none; }
.draft-dock :deep(.coding-composer:focus-within) { box-shadow: none; }
.draft-dock :deep(.composer-input) { min-height: 92px; }
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
  .coding-home { padding: 0 var(--space-3) var(--space-4); }
  .home-hero { min-height: 210px; }
  .home-hero__copy { width: 100%; padding: var(--space-5); background: color-mix(in srgb, var(--color-hero-bg) 88%, transparent); }
  .home-project-grid, .task-starters { grid-template-columns: minmax(0, 1fr); }
  .home-project { min-height: 84px; }
  .draft-selectors {
    align-items: stretch;
    flex-direction: column;
    gap: var(--space-1);
  }
}
@media (min-width: 601px) and (max-width: 900px) { .home-hero__copy { width: 64%; padding: var(--space-5); } .home-hero { min-height: 240px; } .task-starter__copy > span { display: none; } .home-project__icon { width: 36px; height: 36px; } .home-project { padding: var(--space-3); } }
@media (min-height: 801px) and (max-height: 950px) and (min-width: 901px) {
  .home-hero { min-height: 32vh; }
  .home-project { min-height: 104px; }
  .task-starter { min-height: 72px; }
  .draft-dock :deep(.coding-composer) { min-height: 148px; }
  .draft-dock :deep(.composer-input) { min-height: 64px; }
}
@media (max-height: 800px) and (min-width: 901px) {
  .coding-home { padding-bottom: var(--space-4); }
  .home-column.is-ready, .draft-stage { gap: var(--space-3); }
  .home-hero { min-height: 200px; }
  .home-hero__copy { padding: var(--space-3) var(--space-6); }
  .home-hero h1 { font-size: 28px; line-height: 1.3; }
  .home-hero__greeting, .home-hero__description { margin-block: 0; font-size: 14px; line-height: 1.5; }
  .home-hero__greeting { margin-bottom: var(--space-2); }
  .home-hero__description { margin-top: var(--space-2); }
  .home-section-heading { margin-bottom: var(--space-2); }
  .home-project { min-height: 80px; padding: var(--space-3); }
  .home-project__icon { width: 40px; height: 40px; }
  .home-project__copy > span:not(.home-project__branch) { display: none; }
  .task-starter { min-height: 64px; padding: var(--space-2) var(--space-3); }
  .draft-dock :deep(.coding-composer) { min-height: 112px; }
  .draft-dock :deep(.composer-input) { min-height: 48px; }
}
</style>
