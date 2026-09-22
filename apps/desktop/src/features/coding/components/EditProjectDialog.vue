<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { PhFolderSimple } from "@phosphor-icons/vue";
import { pickDirectory } from "../../../api/tauri";
import { useNotifications } from "../../../stores/notifications";
import { fetchCodingProjectDetails, updateCodingProject } from "../api/projects";
import ProjectObserverSettings from "./ProjectObserverSettings.vue";
import ProjectWorktreeSettings from "./ProjectWorktreeSettings.vue";

const props = defineProps<{ projectId: number; worktreeEnabled?: boolean }>();
const emit = defineEmits<{ close: []; saved: []; "workspace-created": [workspaceId: number] }>();
const notify = useNotifications();
const panel = ref<HTMLElement>();
const nameInput = ref<HTMLInputElement>();
const name = ref("");
const originalName = ref("");
const rootPath = ref("");
const originalPath = ref("");
const loading = ref(true);
const saving = ref(false);
const picking = ref(false);
const observerSaving = ref(false);
const worktreeCreating = ref(false);
const error = ref("");
const busy = computed(() => loading.value || saving.value || picking.value || observerSaving.value || worktreeCreating.value);
const canSave = computed(() => !busy.value && name.value.trim().length > 0 && name.value.trim().length <= 255 && !!rootPath.value);
let alive = true;
let previousFocus: HTMLElement | null = null;

function message(cause: unknown, fallback: string): string {
  return (cause as { message?: string } | null)?.message || fallback;
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const project = await fetchCodingProjectDetails(props.projectId);
    if (!alive) return;
    name.value = originalName.value = project.name;
    rootPath.value = originalPath.value = project.root_path;
  } catch (cause) {
    if (alive) error.value = message(cause, "项目读取失败，请重试");
  } finally {
    if (alive) {
      loading.value = false;
      await nextTick();
      nameInput.value?.focus();
    }
  }
}

async function chooseDirectory(): Promise<void> {
  if (busy.value) return;
  picking.value = true;
  error.value = "";
  try {
    const selected = await pickDirectory();
    if (alive && selected) rootPath.value = selected;
  } catch (cause) {
    if (alive) error.value = message(cause, "目录选择失败，请重试");
  } finally {
    if (alive) picking.value = false;
  }
}

async function save(): Promise<void> {
  if (!canSave.value) return;
  saving.value = true;
  error.value = "";
  try {
    const changed = rootPath.value !== originalPath.value;
    if (changed) {
      const accepted = await notify.confirm({
        title: "确认更换项目目录？",
        message: "此项目根工作区中的对话，后续将在新目录执行。独立 worktree 保留原目录。",
        impact: "将授权新目录并撤销旧的完全访问授权及指令信任；已有文件不会移动，历史执行现场不会迁移。",
        confirmLabel: "确认更换",
        danger: true,
      });
      if (!alive || !accepted) return;
    }
    await updateCodingProject(props.projectId, {
      name: name.value.trim(),
      ...(changed ? { root_path: rootPath.value, authorize_scope: true } : {}),
    });
    if (alive) emit("saved");
  } catch (cause) {
    if (alive) error.value = message(cause, "项目保存失败，请重试");
  } finally {
    if (alive) saving.value = false;
  }
}

function keyboard(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.stopPropagation();
    if (!busy.value) emit("close");
  } else if (event.key === "Tab") {
    const focusable = [...(panel.value?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)') ?? [])];
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (!first) { event.preventDefault(); return; }
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
}

onMounted(() => { previousFocus = document.activeElement as HTMLElement | null; panel.value?.focus(); void load(); });
onBeforeUnmount(() => { alive = false; if (previousFocus?.isConnected) previousFocus.focus(); });
</script>

<template>
  <Teleport to="body">
    <div class="edit-project-overlay" @click.self="!busy && emit('close')">
      <form ref="panel" class="edit-project-dialog" role="dialog" aria-modal="true" aria-label="编辑项目" tabindex="-1" data-testid="edit-project-dialog" @submit.prevent="save" @keydown="keyboard">
        <header><strong>编辑项目</strong><span>修改名称或选择新的工作目录</span></header>
        <p v-if="loading" role="status">正在读取项目…</p>
        <template v-else>
          <label>项目名称<input ref="nameInput" v-model="name" class="pa-input" maxlength="255" :disabled="busy || !originalPath" data-testid="edit-project-name" /></label>
          <label>工作目录<button type="button" class="edit-project-directory pa-btn pa-btn--subtle" :disabled="busy || !originalPath" :title="rootPath" data-testid="edit-project-directory" @click="chooseDirectory"><PhFolderSimple :size="18" /><span>{{ rootPath || "尚未读取目录" }}</span><strong>{{ picking ? "选择中…" : "更换目录" }}</strong></button></label>
          <p class="edit-project-hint">更换目录后，原目录的文件保持不变。根工作区中的对话将使用新目录，独立 worktree 保持原位置。</p>
          <ProjectWorktreeSettings v-if="originalPath && worktreeEnabled" :project-id="projectId" :disabled="saving || picking || observerSaving || name.trim() !== originalName || rootPath !== originalPath" @busy-change="worktreeCreating = $event" @created="emit('workspace-created', $event)" />
          <p v-if="worktreeEnabled && (name.trim() !== originalName || rootPath !== originalPath)" class="edit-project-hint">请先保存项目修改，再创建 worktree。</p>
          <ProjectObserverSettings v-if="originalPath" :project-id="projectId" :disabled="saving || picking || worktreeCreating" @busy-change="observerSaving = $event" />
        </template>
        <p v-if="error" role="alert" class="edit-project-error">{{ error }}</p>
        <footer>
          <button v-if="!originalPath && !loading" type="button" class="pa-btn pa-btn--subtle" @click="load">重新读取</button>
          <button type="button" class="pa-btn pa-btn--ghost" :disabled="saving || picking || observerSaving || worktreeCreating" @click="emit('close')">取消</button>
          <button type="submit" class="pa-btn pa-btn--primary" :disabled="!canSave" data-testid="edit-project-save">{{ saving ? "保存中…" : "保存" }}</button>
        </footer>
      </form>
    </div>
  </Teleport>
</template>

<style scoped>
.edit-project-overlay { position: fixed; inset: 0; z-index: calc(var(--z-overlay) + 1); display: grid; place-items: center; padding: var(--space-4); background: color-mix(in srgb, #020608 55%, transparent); }
.edit-project-dialog { display: flex; flex-direction: column; gap: var(--space-4); width: min(540px, 100%); max-height: calc(100dvh - 32px); overflow-y: auto; padding: var(--space-5); border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-panel); color: var(--color-fg); box-shadow: var(--shadow-lg); }
.edit-project-dialog header, .edit-project-dialog label { display: flex; flex-direction: column; gap: var(--space-2); }
.edit-project-dialog header span, .edit-project-hint { color: var(--color-fg-muted); font-size: var(--text-sm); line-height: 1.6; }
.edit-project-directory { width: 100%; min-width: 0; justify-content: flex-start; }
.edit-project-directory svg, .edit-project-directory strong { flex-shrink: 0; }
.edit-project-directory span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; }
.edit-project-dialog footer { display: flex; justify-content: flex-end; gap: var(--space-2); }
.edit-project-error { color: var(--color-danger); font-size: var(--text-sm); }
</style>
