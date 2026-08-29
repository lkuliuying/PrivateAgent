<script setup lang="ts">
/**
 * NewProjectDialog · v0.9.0 H1（新建项目/新建对话拆分，计划 §5.1）
 *
 * 「新建项目」负责选择并授权工作目录：
 * - 自定义目录：名称 + 通过资源管理器选择目录，提交即授权（后端同事务建 project +
 *   root workspace + trusted path，失败不留半绑定项目）；
 * - 「当前用户目录」候选：只解决归属与起始目录，首次使用前需显式确认
 *   授权范围（不自动扩大 trusted path，H0 §4.2 第 3 条）。
 * 组件不自取列表数据；创建成功后由父层刷新 store。
 */
import { computed, ref, watch } from "vue";
import { PhFolderSimple, PhHouse, PhWarningCircle } from "@phosphor-icons/vue";
import { pickDirectory } from "../../../api/tauri";
import {
  authorizeProjectScope,
  createCodingProject,
  ensureUserHomeProject,
  type UserHomeCandidate,
} from "../api/projects";
import type { CodingApiError } from "../model/contracts";

/** 把抛出的 CodingApiError/未知异常收敛为可呈现文案（不猜具体原因）。 */
function toErrorMessage(error: unknown, fallback: string): string {
  const apiError = error as Partial<CodingApiError> | null;
  if (apiError && typeof apiError.message === "string" && apiError.message) {
    return apiError.message;
  }
  return fallback;
}

const emit = defineEmits<{
  close: [];
  created: [projectId: number];
}>();

type Mode = "directory" | "user-home";

const mode = ref<Mode>("directory");
const name = ref("");
const rootPath = ref("");
const busy = ref(false);
const directoryPicking = ref(false);
const errorMessage = ref<string | null>(null);
// 用户目录候选：创建后若未授权 → 进入范围确认步骤（显式二次确认）
const pendingHome = ref<UserHomeCandidate | null>(null);

const canSubmit = computed(() => {
  if (busy.value || directoryPicking.value) return false;
  if (mode.value === "user-home") return true;
  return name.value.trim().length > 0 && rootPath.value.trim().length > 0;
});

async function chooseDirectory(): Promise<void> {
  if (directoryPicking.value || busy.value) return;
  mode.value = "directory";
  directoryPicking.value = true;
  errorMessage.value = null;
  try {
    const selected = await pickDirectory();
    if (selected) rootPath.value = selected;
  } finally {
    directoryPicking.value = false;
  }
}

watch(mode, () => {
  errorMessage.value = null;
  pendingHome.value = null;
});

async function submit(): Promise<void> {
  if (!canSubmit.value) return;
  busy.value = true;
  errorMessage.value = null;
  try {
    if (mode.value === "user-home") {
      const candidate = await ensureUserHomeProject();
      if (candidate.projectId === null) {
        errorMessage.value = "候选项目创建失败，请稍后重试";
        return;
      }
      if (candidate.authorized) {
        emit("created", candidate.projectId);
        return;
      }
      // 未授权 → 进入范围确认步骤（不自动扩大授权）
      pendingHome.value = candidate;
      return;
    }
    const project = await createCodingProject(
      name.value.trim(),
      rootPath.value.trim()
    );
    emit("created", project.id);
  } catch (error) {
    errorMessage.value = toErrorMessage(
      error,
      "项目创建失败，请检查目录路径后重试"
    );
  } finally {
    busy.value = false;
  }
}

async function confirmHomeScope(): Promise<void> {
  const candidate = pendingHome.value;
  if (!candidate || candidate.projectId === null) return;
  busy.value = true;
  errorMessage.value = null;
  try {
    await authorizeProjectScope(candidate.projectId);
    emit("created", candidate.projectId);
  } catch (error) {
    errorMessage.value = toErrorMessage(
      error,
      "授权范围确认失败，请稍后重试"
    );
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="overlay" role="presentation" @click.self="emit('close')">
    <div
      class="dialog"
      role="dialog"
      aria-modal="true"
      aria-label="新建项目"
      data-testid="new-project-dialog"
    >
      <header class="dialog-head">
        <strong>新建项目</strong>
        <span class="head-hint">选择并授权工作目录；对话将绑定到项目</span>
      </header>

      <!-- 步骤 2：用户目录候选的范围确认（显式二次确认，不自动授权） -->
      <div v-if="pendingHome" class="scope-confirm" data-testid="home-scope-confirm">
        <PhWarningCircle :size="18" class="scope-icon" aria-hidden="true" />
        <p class="scope-title">确认授权范围</p>
        <p class="scope-text">
          「当前用户目录」候选已建立，但尚未授权。确认后将以你的用户主目录
          作为该项目的可信工作范围；不确认则项目仅作为归属与起始目录，
          写入与命令仍会逐次征求同意。
        </p>
        <div class="scope-actions">
          <button
            type="button"
            class="btn btn-ghost"
            :disabled="busy"
            data-testid="home-scope-later"
            @click="emit('created', pendingHome.projectId ?? 0)"
          >
            暂不授权
          </button>
          <button
            type="button"
            class="btn btn-primary"
            :disabled="busy"
            data-testid="home-scope-confirm-btn"
            @click="void confirmHomeScope()"
          >
            {{ busy ? "处理中…" : "确认授权范围" }}
          </button>
        </div>
      </div>

      <!-- 步骤 1：选择创建方式 -->
      <template v-else>
        <div class="mode-tabs" role="tablist" aria-label="项目来源">
          <button
            type="button"
            role="tab"
            class="mode-tab"
            :class="{ active: mode === 'directory' }"
            :aria-selected="mode === 'directory'"
            data-testid="new-project-mode-directory"
            :disabled="directoryPicking || busy"
            @click="void chooseDirectory()"
          >
            <PhFolderSimple :size="14" aria-hidden="true" />
            {{ directoryPicking ? "正在打开…" : rootPath ? "更换目录" : "选择目录" }}
          </button>
          <button
            type="button"
            role="tab"
            class="mode-tab"
            :class="{ active: mode === 'user-home' }"
            :aria-selected="mode === 'user-home'"
            data-testid="new-project-mode-user-home"
            @click="mode = 'user-home'"
          >
            <PhHouse :size="14" aria-hidden="true" />
            当前用户目录
          </button>
        </div>

        <div v-if="mode === 'directory'" class="form-fields">
          <label class="field">
            <span class="field-label">项目名称</span>
            <input
              v-model="name"
              type="text"
              class="field-input"
              maxlength="255"
              placeholder="例如：我的网站"
              data-testid="new-project-name"
            />
          </label>
          <div class="field">
            <span class="field-label">工作目录</span>
            <button
              type="button"
              class="directory-field"
              data-testid="new-project-pick-directory"
              :disabled="directoryPicking || busy"
              :title="rootPath || '从资源管理器选择工作目录'"
              @click="void chooseDirectory()"
            >
              <PhFolderSimple :size="17" aria-hidden="true" />
              <span :class="{ placeholder: !rootPath }">
                {{ rootPath || "从资源管理器选择目录" }}
              </span>
              <strong>{{ rootPath ? "重新选择" : "浏览…" }}</strong>
            </button>
            <span class="field-hint">
              目录必须存在；创建即授权该目录为可信工作范围。
            </span>
          </div>
        </div>

        <div v-else class="home-note">
          <p>
            以当前系统的用户主目录建立候选项目，用于快速开始。该默认值只解决
            归属与起始目录：<strong>不会自动授权整个用户目录</strong>；
            下一步会请你确认授权范围。
          </p>
        </div>

        <p
          v-if="errorMessage"
          class="error-line"
          role="alert"
          data-testid="new-project-error"
        >
          {{ errorMessage }}
        </p>

        <footer class="dialog-foot">
          <button type="button" class="btn btn-ghost" @click="emit('close')">
            取消
          </button>
          <button
            type="button"
            class="btn btn-primary"
            :disabled="!canSubmit"
            data-testid="new-project-submit"
            @click="void submit()"
          >
            {{ busy ? "创建中…" : "创建项目" }}
          </button>
        </footer>
      </template>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: color-mix(in srgb, #020608 55%, transparent);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 90;
}

.dialog {
  width: min(560px, calc(100vw - 48px));
  background: var(--color-panel);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 18px 20px 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.35);
}

.dialog-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.dialog-head strong {
  color: var(--color-fg);
  font-size: 15px;
}

.head-hint {
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta, 12px);
}

.mode-tabs {
  display: flex;
  gap: 8px;
}

.mode-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--text-sm);
  cursor: pointer;
}

.mode-tab:disabled {
  cursor: wait;
  opacity: 0.65;
}

.mode-tab.active {
  background: var(--color-accent-soft);
  border-color: color-mix(in srgb, var(--color-accent) 36%, var(--color-border));
  color: var(--color-fg);
}

.form-fields {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field-label {
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta, 12px);
}

.field-input {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
  color: var(--color-fg);
  padding: 7px 10px;
  font-size: var(--text-sm);
}

.field-input:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--color-accent) 60%, transparent);
  outline-offset: 1px;
}

.directory-field {
  display: grid;
  width: 100%;
  min-height: 42px;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  padding: 7px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
  color: var(--color-fg-muted);
  text-align: left;
  cursor: pointer;
}

.directory-field:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--color-accent) 55%, var(--color-border));
  background: var(--color-surface-hover);
}

.directory-field:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--color-accent) 60%, transparent);
  outline-offset: 1px;
}

.directory-field:disabled {
  cursor: wait;
  opacity: 0.65;
}

.directory-field span {
  overflow: hidden;
  color: var(--color-fg);
  font-family: var(--font-mono);
  font-size: var(--pa-text-meta, 12px);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.directory-field span.placeholder {
  color: var(--color-fg-subtle);
  font-family: inherit;
}

.directory-field strong {
  color: var(--color-accent);
  font-size: var(--pa-text-meta, 12px);
  font-weight: 600;
}

.field-hint {
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta, 12px);
}

.home-note {
  color: var(--color-fg-muted);
  font-size: var(--text-sm);
  line-height: 1.6;
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
}

.scope-confirm {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.scope-icon {
  color: var(--color-accent);
}

.scope-title {
  color: var(--color-fg);
  font-weight: 600;
}

.scope-text {
  color: var(--color-fg-muted);
  font-size: var(--text-sm);
  line-height: 1.6;
}

.scope-actions,
.dialog-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.btn {
  border-radius: var(--radius-sm);
  padding: 6px 14px;
  font-size: var(--text-sm);
  cursor: pointer;
  border: 1px solid var(--color-border);
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-ghost {
  background: transparent;
  color: var(--color-fg-muted);
}

.btn-primary {
  background: var(--color-accent);
  border-color: var(--color-accent);
  color: #fff;
}

.error-line {
  color: var(--color-danger, #d4636f);
  font-size: var(--text-sm);
}
</style>
