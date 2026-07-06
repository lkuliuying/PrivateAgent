<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import {
  PhFolderPlus,
  PhArrowClockwise,
  PhGitDiff,
  PhGitBranch,
  PhFileText,
  PhX,
} from "@phosphor-icons/vue";
import ProjectTree from "./ProjectTree.vue";
import CodeSearchPanel from "./CodeSearchPanel.vue";
import {
  listProjects,
  createProject,
  scanProject,
  getProjectTree,
  getProjectStats,
  readProjectFile,
  getProjectGitStatus,
  getProjectGitDiff,
  pickDirectory,
} from "../api";
import type {
  Project,
  ProjectTree as TreeData,
  ProjectStats,
  CodeFileContent,
  GitStatus,
  GitDiff,
} from "../types";

/**
 * 项目工作区 · 第三阶段 M1。
 * 三栏：左目录树 · 中搜索+文件预览 · 右 git 状态/diff。
 * 授权项目用 Tauri 目录选择器（dev 模式回退手动输入）。所有操作只读。
 */
const projects = ref<Project[]>([]);
const currentId = ref<number | null>(null);
const tree = ref<TreeData | null>(null);
const stats = ref<ProjectStats | null>(null);
const scanning = ref(false);

const selectedPath = ref<string | null>(null);
const fileContent = ref<CodeFileContent | null>(null);
const fileLoading = ref(false);
const fileError = ref("");

const gitStatus = ref<GitStatus | null>(null);
const gitDiff = ref<GitDiff | null>(null);
const gitLoading = ref(false);
const gitError = ref("");
const showGitDiff = ref(false);

// 授权表单
const authorizing = ref(false);
const newName = ref("");
const newPath = ref("");
const authError = ref("");

const currentProject = computed(
  () => projects.value.find((p) => p.id === currentId.value) ?? null
);

const langChips = computed(() => {
  if (!stats.value) return [];
  return Object.entries(stats.value.by_language)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);
});

onMounted(load);

async function load() {
  try {
    projects.value = await listProjects();
    if (projects.value.length > 0 && currentId.value === null) {
      await selectProject(projects.value[0].id);
    }
  } catch {
    projects.value = [];
  }
}

async function selectProject(id: number) {
  currentId.value = id;
  selectedPath.value = null;
  fileContent.value = null;
  tree.value = null;
  stats.value = null;
  gitStatus.value = null;
  gitDiff.value = null;
  await Promise.all([loadTree(), loadStats(), loadGit()]);
}

async function loadTree() {
  if (!currentId.value) return;
  try {
    tree.value = await getProjectTree(currentId.value);
  } catch {
    tree.value = null;
  }
}

async function loadStats() {
  if (!currentId.value) return;
  try {
    stats.value = await getProjectStats(currentId.value);
  } catch {
    stats.value = null;
  }
}

async function loadGit() {
  if (!currentId.value) return;
  gitLoading.value = true;
  gitError.value = "";
  try {
    gitStatus.value = await getProjectGitStatus(currentId.value);
  } catch (e) {
    gitStatus.value = null;
    gitError.value = String(e);
  } finally {
    gitLoading.value = false;
  }
}

async function loadGitDiff() {
  if (!currentId.value) return;
  try {
    gitDiff.value = await getProjectGitDiff(currentId.value);
    showGitDiff.value = true;
  } catch (e) {
    gitError.value = String(e);
  }
}

async function rescan() {
  if (!currentId.value) return;
  scanning.value = true;
  try {
    await scanProject(currentId.value);
    // 后台扫描，轮询树直到更新
    await pollTree();
    await loadStats();
  } catch (e) {
    alert("扫描失败：" + String(e));
  } finally {
    scanning.value = false;
  }
}

async function pollTree(timeoutMs = 10000) {
  const start = Date.now();
  // 注意：Date.now 在主线程可用（workflow 脚本才禁用）
  while (Date.now() - start < timeoutMs) {
    await new Promise((r) => setTimeout(r, 400));
    await loadTree();
    if (stats.value && stats.value.total > 0) break;
  }
}

async function onSelectFile(path: string, line?: number) {
  if (!currentId.value) return;
  selectedPath.value = path;
  fileLoading.value = true;
  fileError.value = "";
  fileContent.value = null;
  try {
    // 内容搜索命中时从命中行附近开始读，便于定位
    const startLine = line ? Math.max(1, line - 10) : 1;
    fileContent.value = await readProjectFile(currentId.value, path, { startLine });
  } catch (e) {
    fileError.value = String(e);
  } finally {
    fileLoading.value = false;
  }
}

// ============ 授权 ============

async function startAuthorize() {
  authorizing.value = true;
  authError.value = "";
  newName.value = "";
  newPath.value = "";
  // 优先用 Tauri 目录选择器
  const picked = await pickDirectory();
  if (picked) {
    newPath.value = picked;
    newName.value = picked.split(/[\\/]/).pop() || picked;
  }
}

async function submitAuthorize() {
  if (!newName.value.trim() || !newPath.value.trim()) {
    authError.value = "名称和路径不能为空";
    return;
  }
  try {
    const p = await createProject(newName.value.trim(), newPath.value.trim());
    projects.value.unshift(p);
    authorizing.value = false;
    await selectProject(p.id);
    await rescan();
  } catch (e) {
    authError.value = String(e);
  }
}

function cancelAuthorize() {
  authorizing.value = false;
  authError.value = "";
}

function fmtSize(n: number | null | undefined): string {
  if (!n) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
</script>

<template>
  <section class="pw">
    <!-- 顶栏：项目选择 + 操作 -->
    <header class="pw-header">
      <select
        v-if="projects.length > 0"
        v-model="currentId"
        class="pa-input project-select"
        @change="selectProject(Number(currentId))"
      >
        <option v-for="p in projects" :key="p.id" :value="p.id">
          {{ p.name }}{{ p.language ? ` · ${p.language}` : "" }}
        </option>
      </select>
      <button class="pa-btn pa-btn--primary pa-btn--sm" @click="startAuthorize">
        <PhFolderPlus :size="14" weight="regular" />
        <span>授权项目</span>
      </button>
      <button
        v-if="currentProject"
        class="pa-btn pa-btn--subtle pa-btn--sm"
        :disabled="scanning"
        @click="rescan"
      >
        <PhArrowClockwise :size="14" weight="regular" />
        <span>{{ scanning ? "扫描中…" : "重新扫描" }}</span>
      </button>
      <div class="pw-spacer" />
      <div v-if="currentProject" class="pw-meta">
        <span v-if="currentProject.framework" class="chip">{{ currentProject.framework }}</span>
        <span v-if="stats" class="meta-text">{{ stats.total }} 文件</span>
      </div>
    </header>

    <!-- 授权浮层 -->
    <div v-if="authorizing" class="auth-card">
      <div class="auth-head">
        <span>授权项目目录</span>
        <button class="pa-btn pa-btn--ghost pa-btn--icon" @click="cancelAuthorize">
          <PhX :size="14" />
        </button>
      </div>
      <label class="auth-label">名称</label>
      <input v-model="newName" class="pa-input" placeholder="项目名称" />
      <label class="auth-label">根目录（绝对路径）</label>
      <input v-model="newPath" class="pa-input" placeholder="C:\\path\\to\\project 或 /home/user/proj" />
      <p class="auth-hint">授权后助手仅可读取该目录内文件，写入仍需逐次审批。</p>
      <p v-if="authError" class="auth-err">{{ authError }}</p>
      <div class="auth-actions">
        <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="cancelAuthorize">取消</button>
        <button class="pa-btn pa-btn--primary pa-btn--sm" @click="submitAuthorize">授权并扫描</button>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="projects.length === 0 && !authorizing" class="empty">
      <PhFolderPlus :size="40" weight="duotone" />
      <p>尚未授权项目</p>
      <p class="hint">点击「授权项目」选择一个代码目录，助手将扫描结构并支持搜索与 git 查看</p>
    </div>

    <!-- 三栏工作区 -->
    <div v-else-if="currentProject" class="pw-body">
      <!-- 左：目录树 -->
      <aside class="pw-tree">
        <div class="pane-head">
          <span>目录树</span>
          <span v-if="stats" class="pane-count">{{ stats.total }}</span>
        </div>
        <div class="pane-scroll">
          <ProjectTree
            v-if="tree"
            :dirs="tree.dirs"
            :files="tree.files"
            :selected-path="selectedPath || undefined"
            @select-file="onSelectFile($event)"
          />
          <p v-else-if="!scanning" class="pane-empty">
            尚未扫描，点击「重新扫描」
          </p>
          <p v-else class="pane-empty">扫描中…</p>
        </div>
        <div v-if="langChips.length > 0" class="lang-chips">
          <span v-for="[lang, n] in langChips" :key="lang" class="lang-chip">
            {{ lang }} · {{ n }}
          </span>
        </div>
      </aside>

      <!-- 中：搜索 + 文件预览 -->
      <main class="pw-center">
        <div class="center-search">
          <CodeSearchPanel
            v-if="currentId"
            :project-id="currentId"
            @select-file="onSelectFile"
          />
        </div>
        <div class="center-preview">
          <div v-if="!selectedPath" class="preview-empty">
            <PhFileText :size="32" weight="duotone" />
            <p>选择左侧文件或搜索结果查看内容</p>
          </div>
          <div v-else class="preview-content">
            <div class="preview-head">
              <span class="preview-path pa-ellipsis">{{ selectedPath }}</span>
              <span v-if="fileContent?.language" class="preview-lang">{{ fileContent.language }}</span>
              <span v-if="fileContent" class="preview-size">{{ fmtSize(fileContent.size_bytes) }}</span>
            </div>
            <p v-if="fileError" class="preview-err">{{ fileError }}</p>
            <pre v-else-if="fileContent" class="code-block">{{ fileContent.content }}</pre>
            <p v-else class="preview-loading">读取中…</p>
          </div>
        </div>
      </main>

      <!-- 右：git -->
      <aside class="pw-git">
        <div class="pane-head">
          <PhGitBranch :size="14" weight="regular" />
          <span>Git</span>
        </div>
        <div class="pane-scroll">
          <p v-if="gitError" class="git-err">{{ gitError }}</p>
          <p v-else-if="gitLoading" class="pane-empty">读取 git…</p>
          <div v-else-if="gitStatus" class="git-body">
            <div class="git-branch">
              <PhGitBranch :size="12" weight="fill" />
              <span>{{ gitStatus.branch || "（无分支）" }}</span>
              <span v-if="gitStatus.ahead" class="ahead-behind">↑{{ gitStatus.ahead }}</span>
              <span v-if="gitStatus.behind" class="ahead-behind">↓{{ gitStatus.behind }}</span>
            </div>
            <p v-if="gitStatus.clean" class="git-clean">工作区干净</p>
            <div v-else class="git-changed">
              <div class="git-changed-head">
                <span>{{ gitStatus.changed.length }} 个改动</span>
                <button class="link-btn" @click="loadGitDiff">
                  <PhGitDiff :size="12" weight="regular" />
                  查看 diff
                </button>
              </div>
              <div class="git-files">
                <div
                  v-for="(c, i) in gitStatus.changed"
                  :key="i"
                  class="git-file"
                  @click="onSelectFile(c.path)"
                >
                  <span class="git-xy">{{ c.status.trim() || "??" }}</span>
                  <span class="git-path pa-ellipsis">{{ c.path }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div v-if="showGitDiff && gitDiff" class="git-diff-overlay">
          <div class="diff-head">
            <span>git diff</span>
            <button class="pa-btn pa-btn--ghost pa-btn--icon" @click="showGitDiff = false">
              <PhX :size="12" />
            </button>
          </div>
          <pre class="diff-block">{{ gitDiff.diff }}</pre>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.pw {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.pw-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}
.project-select {
  height: 30px;
  min-width: 200px;
  background: var(--color-surface);
}
.pw-spacer {
  flex: 1;
}
.pw-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.chip {
  font-size: var(--text-xs);
  color: var(--color-accent-soft-fg);
  background: var(--color-accent-soft);
  padding: 2px 8px;
  border-radius: var(--radius-full);
}
.meta-text {
  font-size: var(--text-sm);
  color: var(--color-fg-faint);
}

/* 授权浮层 */
.auth-card {
  position: absolute;
  top: 60px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 20;
  width: 420px;
  max-width: 90vw;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  box-shadow: var(--shadow-md, 0 8px 24px rgba(0, 0, 0, 0.12));
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.auth-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--text-md);
  font-weight: var(--font-semibold);
  margin-bottom: var(--space-1);
}
.auth-label {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  margin-top: var(--space-2);
}
.auth-hint {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  margin: var(--space-1) 0;
}
.auth-err {
  font-size: var(--text-sm);
  color: var(--color-danger-fg);
}
.auth-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

/* 空状态 */
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 0;
  color: var(--color-fg-faint);
  gap: var(--space-2);
  flex: 1;
}
.empty p {
  margin: 0;
  font-size: var(--text-base);
}
.empty .hint {
  font-size: var(--text-sm);
  max-width: 360px;
  text-align: center;
}

/* 三栏 */
.pw-body {
  flex: 1;
  display: flex;
  min-height: 0;
}
.pw-tree {
  flex-shrink: 0;
  width: 280px;
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  background: var(--color-surface);
  min-width: 0;
}
.pw-center {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.pw-git {
  flex-shrink: 0;
  width: 300px;
  border-left: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  background: var(--color-surface);
  min-width: 0;
  position: relative;
}
.pane-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-border);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--color-fg-muted);
}
.pane-count {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
}
.pane-scroll {
  flex: 1;
  overflow: auto;
  padding: var(--space-2);
}
.pane-empty {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
  text-align: center;
  padding: var(--space-4);
}
.lang-chips {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: var(--space-2);
  border-top: 1px solid var(--color-border);
}
.lang-chip {
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  background: var(--color-surface-sunken);
  padding: 2px 6px;
  border-radius: var(--radius);
}

/* 中栏 */
.center-search {
  flex-shrink: 0;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}
.center-preview {
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: var(--color-bg);
}
.preview-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--color-fg-faint);
  gap: var(--space-2);
  font-size: var(--text-sm);
}
.preview-content {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.preview-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}
.preview-path {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  flex: 1;
  min-width: 0;
}
.preview-lang {
  font-size: var(--text-xs);
  color: var(--color-accent-soft-fg);
  background: var(--color-accent-soft);
  padding: 1px 6px;
  border-radius: var(--radius-full);
}
.preview-size {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
}
.code-block {
  flex: 1;
  margin: 0;
  padding: var(--space-3);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  line-height: 1.5;
  color: var(--color-fg);
  white-space: pre;
  overflow: auto;
}
.preview-err,
.preview-loading {
  padding: var(--space-3);
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.preview-err {
  color: var(--color-danger-fg);
}

/* git 面板 */
.git-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.git-branch {
  display: flex;
  align-items: center;
  gap: 4px;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--color-fg);
}
.ahead-behind {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
}
.git-clean {
  color: var(--color-success-fg);
  font-size: var(--text-sm);
}
.git-changed-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  margin-top: var(--space-1);
}
.link-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  color: var(--color-accent);
  cursor: pointer;
  font-size: var(--text-xs);
  padding: 0;
}
.link-btn:hover {
  text-decoration: underline;
}
.git-files {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.git-file {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 4px;
  border-radius: var(--radius);
  cursor: pointer;
  font-size: var(--text-xs);
}
.git-file:hover {
  background: var(--color-surface-sunken);
}
.git-xy {
  font-family: var(--font-mono);
  color: var(--color-warning-fg);
  flex-shrink: 0;
  width: 18px;
}
.git-path {
  font-family: var(--font-mono);
  color: var(--color-fg-muted);
  min-width: 0;
}
.git-err {
  color: var(--color-danger-fg);
  font-size: var(--text-sm);
  padding: var(--space-2);
}
.git-diff-overlay {
  position: absolute;
  inset: 0;
  background: var(--color-surface);
  display: flex;
  flex-direction: column;
  z-index: 10;
}
.diff-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-border);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
}
.diff-block {
  flex: 1;
  margin: 0;
  padding: var(--space-2);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1.4;
  white-space: pre;
  overflow: auto;
  color: var(--color-fg);
}
</style>
