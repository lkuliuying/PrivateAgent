<script setup lang="ts">
import { ref, computed, onMounted, watch } from "vue";
import {
  PhGitDiff,
  PhPlus,
  PhTrash,
  PhPlay,
  PhStethoscope,
  PhX,
  PhArrowCounterClockwise,
  PhCheck,
} from "@phosphor-icons/vue";
import {
  listPatchSets,
  getPatchSet,
  createPatchSet,
  submitPatchSet,
  applyPatchSet,
  rejectPatchSet,
  rollbackPatchSet,
  listProjectCommands,
  createProjectCommand,
  updateProjectCommand,
  deleteProjectCommand,
  runProjectCommand,
  diagnoseCommandOutput,
} from "../api";
import type {
  PatchSet,
  PatchFileCreate,
  ProjectCommandProfile,
  CommandProfileKind,
  RunResult,
  DiagnoseResult,
} from "../types";
import { useNotifications } from "../stores/notifications";

const notify = useNotifications();

const props = defineProps<{ projectId: number }>();

const tab = ref<"patches" | "commands">("patches");

// 补丁集
const patchSets = ref<PatchSet[]>([]);
const currentPatchId = ref<number | null>(null);
const currentPatch = ref<PatchSet | null>(null);
const patchBusy = ref(false);
const patchMsg = ref("");

const newPatchOpen = ref(false);
const newPatchTitle = ref("");
const newPatchFiles = ref<Array<PatchFileCreate & { create: boolean }>>([]);

// 命令配置
const commands = ref<ProjectCommandProfile[]>([]);
const currentCmdId = ref<number | null>(null);
const cmdForm = ref({ name: "", kind: "test" as CommandProfileKind, command: "", timeout: 120, enabled: true });
const cmdBusy = ref(false);
const cmdMsg = ref("");
const runResult = ref<RunResult | null>(null);
const runBusy = ref(false);
const diagnoseResult = ref<DiagnoseResult | null>(null);
const diagnoseBusy = ref(false);

const PATCH_STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  waiting_approval: "待审批",
  applied: "已应用",
  rejected: "已拒绝",
  rolled_back: "已回滚",
};
const KIND_LABELS: Record<CommandProfileKind, string> = {
  test: "测试",
  build: "构建",
  lint: "lint",
  format: "格式化",
  typecheck: "类型检查",
  custom: "自定义",
};
const KINDS: CommandProfileKind[] = ["test", "build", "lint", "format", "typecheck", "custom"];

onMounted(load);
watch(() => props.projectId, load);

async function load() {
  await Promise.all([loadPatches(), loadCommands()]);
}

async function loadPatches() {
  try {
    patchSets.value = await listPatchSets(props.projectId);
    if (patchSets.value.length > 0 && currentPatchId.value === null) {
      await selectPatch(patchSets.value[0].id);
    } else if (patchSets.value.length === 0) {
      currentPatch.value = null;
      currentPatchId.value = null;
    }
  } catch {
    patchSets.value = [];
  }
}

async function loadCommands() {
  try {
    commands.value = await listProjectCommands(props.projectId);
  } catch {
    commands.value = [];
  }
}

async function selectPatch(id: number) {
  currentPatchId.value = id;
  try {
    currentPatch.value = await getPatchSet(id);
  } catch (e) {
    currentPatch.value = null;
    patchMsg.value = String(e);
  }
}

// ============ 补丁集创建 ============

function openNewPatch() {
  newPatchOpen.value = true;
  newPatchTitle.value = "";
  newPatchFiles.value = [{ rel_path: "", new_content: "", create: false }];
}

function addPatchFile() {
  newPatchFiles.value.push({ rel_path: "", new_content: "", create: false });
}

function removePatchFile(i: number) {
  newPatchFiles.value.splice(i, 1);
}

async function submitNewPatch() {
  if (!newPatchTitle.value.trim()) return;
  const files = newPatchFiles.value.filter((f) => f.rel_path.trim() && f.new_content);
  if (files.length === 0) return;
  patchBusy.value = true;
  patchMsg.value = "";
  try {
    const ps = await createPatchSet(props.projectId, {
      title: newPatchTitle.value.trim(),
      files: files.map((f) => ({ rel_path: f.rel_path.trim(), new_content: f.new_content, create: f.create })),
    });
    newPatchOpen.value = false;
    await loadPatches();
    await selectPatch(ps.id);
    patchMsg.value = "补丁集已创建";
  } catch (e) {
    patchMsg.value = "创建失败：" + String(e);
  } finally {
    patchBusy.value = false;
  }
}

// ============ 补丁集操作 ============

async function doSubmit() {
  if (!currentPatchId.value) return;
  patchBusy.value = true;
  try {
    await submitPatchSet(currentPatchId.value);
    await selectPatch(currentPatchId.value);
  } catch (e) {
    patchMsg.value = String(e);
  } finally {
    patchBusy.value = false;
  }
}

async function doApply() {
  if (!currentPatchId.value) return;
  if (!await notify.confirm({ title: "确认应用该补丁集？", danger: true, impact: "将把补丁集中所有文件变更写入项目工作区" })) return;
  patchBusy.value = true;
  try {
    await applyPatchSet(currentPatchId.value);
    await selectPatch(currentPatchId.value);
    patchMsg.value = "已应用";
  } catch (e) {
    patchMsg.value = "应用失败：" + String(e);
  } finally {
    patchBusy.value = false;
  }
}

async function doReject() {
  if (!currentPatchId.value) return;
  patchBusy.value = true;
  try {
    await rejectPatchSet(currentPatchId.value);
    await selectPatch(currentPatchId.value);
  } catch (e) {
    patchMsg.value = String(e);
  } finally {
    patchBusy.value = false;
  }
}

async function doRollback() {
  if (!currentPatchId.value) return;
  if (!await notify.confirm({ title: "确认回滚该补丁集？", danger: true, impact: "将恢复该补丁集写入的文件为旧内容" })) return;
  patchBusy.value = true;
  try {
    await rollbackPatchSet(currentPatchId.value);
    await selectPatch(currentPatchId.value);
    patchMsg.value = "已回滚";
  } catch (e) {
    patchMsg.value = "回滚失败：" + String(e);
  } finally {
    patchBusy.value = false;
  }
}

// ============ 命令配置 ============

async function submitNewCmd() {
  if (!cmdForm.value.name.trim() || !cmdForm.value.command.trim()) return;
  cmdBusy.value = true;
  cmdMsg.value = "";
  try {
    await createProjectCommand(props.projectId, {
      name: cmdForm.value.name.trim(),
      kind: cmdForm.value.kind,
      command_json: { command: cmdForm.value.command.trim() },
      timeout_seconds: cmdForm.value.timeout,
      enabled: cmdForm.value.enabled,
    });
    cmdForm.value = { name: "", kind: "test", command: "", timeout: 120, enabled: true };
    await loadCommands();
    cmdMsg.value = "命令配置已创建";
  } catch (e) {
    cmdMsg.value = "创建失败：" + String(e);
  } finally {
    cmdBusy.value = false;
  }
}

async function toggleCmd(c: ProjectCommandProfile) {
  try {
    await updateProjectCommand(props.projectId, c.id, { enabled: !c.enabled });
    await loadCommands();
  } catch (e) {
    cmdMsg.value = String(e);
  }
}

async function removeCmd(id: number) {
  if (!await notify.confirm({ title: "删除该命令配置？", danger: true, impact: "该操作不可撤销，命令配置将被永久删除" })) return;
  try {
    await deleteProjectCommand(props.projectId, id);
    await loadCommands();
  } catch (e) {
    cmdMsg.value = String(e);
  }
}

async function runCmd(c: ProjectCommandProfile) {
  runBusy.value = true;
  runResult.value = null;
  diagnoseResult.value = null;
  cmdMsg.value = "";
  try {
    runResult.value = await runProjectCommand(props.projectId, c.id);
  } catch (e) {
    cmdMsg.value = "运行失败：" + String(e);
  } finally {
    runBusy.value = false;
  }
}

async function doDiagnose() {
  if (!runResult.value) return;
  diagnoseBusy.value = true;
  diagnoseResult.value = null;
  try {
    diagnoseResult.value = await diagnoseCommandOutput(props.projectId, {
      output: runResult.value.output,
      returncode: runResult.value.returncode,
      args: runResult.value.args,
    });
  } catch (e) {
    cmdMsg.value = "诊断失败：" + String(e);
  } finally {
    diagnoseBusy.value = false;
  }
}

const canSubmit = computed(() => currentPatch.value?.status === "draft");
const canApply = computed(
  () => currentPatch.value?.status === "draft" || currentPatch.value?.status === "waiting_approval"
);
const canReject = computed(
  () => currentPatch.value?.status === "draft" || currentPatch.value?.status === "waiting_approval"
);
const canRollback = computed(() => currentPatch.value?.status === "applied");

function cmdText(c: ProjectCommandProfile): string {
  return (c.command_json.command as string) || JSON.stringify(c.command_json.args || []);
}
</script>

<template>
  <section class="cwf">
    <nav class="cwf-tabs">
      <button :class="{ active: tab === 'patches' }" @click="tab = 'patches'">
        <PhGitDiff :size="14" /> 补丁集
      </button>
      <button :class="{ active: tab === 'commands' }" @click="tab = 'commands'">
        <PhPlay :size="14" /> 命令配置
      </button>
    </nav>

    <!-- 补丁集 -->
    <div v-if="tab === 'patches'" class="cwf-body">
      <aside class="cwf-list">
        <div class="pane-head">
          <span>补丁集（{{ patchSets.length }}）</span>
          <button class="pa-btn pa-btn--primary pa-btn--icon" title="新建补丁集" @click="openNewPatch">
            <PhPlus :size="14" />
          </button>
        </div>
        <div class="list-scroll">
          <button
            v-for="p in patchSets"
            :key="p.id"
            class="list-item"
            :class="{ active: p.id === currentPatchId }"
            @click="selectPatch(p.id)"
          >
            <span class="li-title pa-ellipsis">{{ p.title }}</span>
            <span class="li-status" :class="p.status">{{ PATCH_STATUS_LABEL[p.status] || p.status }}</span>
            <span class="li-meta">{{ p.files.length }} 文件</span>
          </button>
          <div v-if="patchSets.length === 0" class="pane-empty">尚无补丁集</div>
        </div>
      </aside>

      <div class="cwf-detail">
        <p v-if="patchMsg" class="msg">{{ patchMsg }}</p>
        <div v-if="!currentPatch" class="empty">
          <PhGitDiff :size="36" weight="duotone" />
          <p>选择或创建一个补丁集</p>
          <p class="hint">多文件变更，审批后写入，失败可回滚</p>
        </div>
        <template v-else>
          <header class="detail-head">
            <div>
              <h2>{{ currentPatch.title }}</h2>
              <span class="li-status" :class="currentPatch.status">{{ PATCH_STATUS_LABEL[currentPatch.status] }}</span>
            </div>
            <div class="head-actions">
              <button v-if="canSubmit" class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="patchBusy" @click="doSubmit">提交审批</button>
              <button v-if="canApply" class="pa-btn pa-btn--primary pa-btn--sm" :disabled="patchBusy" @click="doApply">
                <PhCheck :size="14" /> 应用
              </button>
              <button v-if="canReject" class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="patchBusy" @click="doReject">拒绝</button>
              <button v-if="canRollback" class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="patchBusy" @click="doRollback">
                <PhArrowCounterClockwise :size="14" /> 回滚
              </button>
            </div>
          </header>
          <div class="file-list">
            <div v-for="f in currentPatch.files" :key="f.id" class="file-item">
              <div class="file-head">
                <PhGitDiff :size="13" />
                <span class="file-path pa-ellipsis">{{ f.rel_path }}</span>
                <span class="li-status sm" :class="f.status">{{ f.status }}</span>
              </div>
              <pre v-if="f.diff_text" class="diff-block">{{ f.diff_text }}</pre>
              <p v-else class="no-diff">（无变化）</p>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- 命令配置 -->
    <div v-else class="cwf-body">
      <aside class="cwf-list">
        <div class="pane-head">
          <span>命令配置（{{ commands.length }}）</span>
        </div>
        <div class="list-scroll">
          <button
            v-for="c in commands"
            :key="c.id"
            class="list-item"
            :class="{ active: c.id === currentCmdId, disabled: !c.enabled }"
            @click="currentCmdId = c.id"
          >
            <span class="li-title pa-ellipsis">{{ c.name }}</span>
            <span class="li-meta">{{ KIND_LABELS[c.kind as CommandProfileKind] || c.kind }}</span>
          </button>
          <div v-if="commands.length === 0" class="pane-empty">尚无命令配置</div>
        </div>
      </aside>

      <div class="cwf-detail">
        <p v-if="cmdMsg" class="msg">{{ cmdMsg }}</p>

        <!-- 新建表单 -->
        <section class="block">
          <div class="block-head">新建命令配置</div>
          <div class="cmd-form">
            <input v-model="cmdForm.name" class="pa-input" placeholder="名称（如：跑测试）" />
            <select v-model="cmdForm.kind" class="pa-input">
              <option v-for="k in KINDS" :key="k" :value="k">{{ KIND_LABELS[k] }}</option>
            </select>
            <input v-model="cmdForm.command" class="pa-input cmd-str" placeholder="命令（如：pytest -q）" />
            <input v-model.number="cmdForm.timeout" type="number" class="pa-input timeout" placeholder="超时秒" />
            <label class="en-toggle">
              <input type="checkbox" v-model="cmdForm.enabled" /> 启用
            </label>
            <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="cmdBusy || !cmdForm.name.trim() || !cmdForm.command.trim()" @click="submitNewCmd">
              添加
            </button>
          </div>
        </section>

        <!-- 命令列表 + 运行 -->
        <section class="block">
          <div class="block-head">已配置命令</div>
          <div v-if="commands.length === 0" class="block-empty">尚无命令配置</div>
          <div v-else class="cmd-list">
            <div v-for="c in commands" :key="c.id" class="cmd-item">
              <div class="cmd-main">
                <span class="cmd-name">{{ c.name }}</span>
                <span class="cmd-kind">{{ KIND_LABELS[c.kind as CommandProfileKind] || c.kind }}</span>
                <code class="cmd-cmd">{{ cmdText(c) }}</code>
              </div>
              <div class="cmd-actions">
                <button class="icon-btn" :title="c.enabled ? '禁用' : '启用'" @click="toggleCmd(c)">
                  {{ c.enabled ? "禁用" : "启用" }}
                </button>
                <button class="icon-btn run" :disabled="runBusy" @click="runCmd(c)">
                  <PhPlay :size="12" /> 运行
                </button>
                <button class="icon-btn del" @click="removeCmd(c.id)">
                  <PhTrash :size="12" />
                </button>
              </div>
            </div>
          </div>
        </section>

        <!-- 运行结果 + 诊断 -->
        <section v-if="runResult || runBusy" class="block">
          <div class="block-head">
            <span>运行结果</span>
            <button
              v-if="runResult && !runResult.succeeded"
              class="pa-btn pa-btn--subtle pa-btn--sm"
              :disabled="diagnoseBusy"
              @click="doDiagnose"
            >
              <PhStethoscope :size="13" /> {{ diagnoseBusy ? "诊断中…" : "诊断失败" }}
            </button>
          </div>
          <p v-if="runBusy" class="block-empty">运行中…</p>
          <template v-else-if="runResult">
            <div class="run-meta">
              <span class="li-status" :class="runResult.succeeded ? 'applied' : 'rejected'">
                {{ runResult.succeeded ? "成功" : "失败" }}（返回码 {{ runResult.returncode }}）
              </span>
              <code class="cmd-cmd">{{ runResult.args.join(" ") }}</code>
            </div>
            <pre class="output-block">{{ runResult.output }}</pre>
            <div v-if="diagnoseResult" class="diagnose">
              <div class="dia-summary">{{ diagnoseResult.summary }}</div>
              <div v-if="diagnoseResult.error_files.length" class="dia-files">
                <div v-for="(ef, i) in diagnoseResult.error_files" :key="i" class="dia-file">
                  <code>{{ ef.file }}{{ ef.line ? `:${ef.line}` : "" }}</code>
                  <span>{{ ef.message }}</span>
                </div>
              </div>
              <div v-if="diagnoseResult.suggestion" class="dia-sug">建议：{{ diagnoseResult.suggestion }}</div>
            </div>
          </template>
        </section>
      </div>
    </div>

    <!-- 新建补丁集浮层 -->
    <div v-if="newPatchOpen" class="modal-overlay" @click.self="newPatchOpen = false">
      <div class="modal-card">
        <div class="modal-head">
          <span>新建补丁集</span>
          <button class="pa-btn pa-btn--ghost pa-btn--icon" @click="newPatchOpen = false">
            <PhX :size="14" />
          </button>
        </div>
        <label class="modal-label">标题</label>
        <input v-model="newPatchTitle" class="pa-input" placeholder="补丁集标题" />
        <div v-for="(f, i) in newPatchFiles" :key="i" class="patch-file-row">
          <input v-model="f.rel_path" class="pa-input pf-path" placeholder="相对路径，如 src/app.py" />
          <label class="pf-create"><input type="checkbox" v-model="f.create" /> 新建</label>
          <textarea v-model="f.new_content" class="pa-input pf-content" placeholder="新内容" rows="3"></textarea>
          <button class="icon-btn del" @click="removePatchFile(i)"><PhTrash :size="12" /></button>
        </div>
        <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="addPatchFile">
          <PhPlus :size="13" /> 添加文件
        </button>
        <div class="modal-actions">
          <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="newPatchOpen = false">取消</button>
          <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="patchBusy || !newPatchTitle.trim()" @click="submitNewPatch">创建</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.cwf {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.cwf-tabs {
  flex-shrink: 0;
  display: flex;
  gap: 2px;
  padding: var(--space-2) var(--space-4) 0;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}
.cwf-tabs button {
  display: flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  color: var(--color-fg-muted);
  cursor: pointer;
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
  border-bottom: 2px solid transparent;
}
.cwf-tabs button.active {
  color: var(--color-accent);
  border-bottom-color: var(--color-accent);
}
.cwf-body {
  flex: 1;
  min-height: 0;
  display: flex;
}
.cwf-list {
  flex-shrink: 0;
  width: 240px;
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  background: var(--color-surface);
}
.pane-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-border);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--color-fg-muted);
}
.list-scroll {
  flex: 1;
  overflow: auto;
  padding: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.list-item {
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius);
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.list-item:hover {
  background: var(--color-surface-sunken);
}
.list-item.active {
  background: var(--color-accent-soft);
}
.list-item.disabled {
  opacity: 0.5;
}
.li-title {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
}
.li-meta {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
}
.li-status {
  align-self: flex-start;
  font-size: var(--text-xs);
  padding: 1px 6px;
  border-radius: var(--radius-full);
  color: var(--color-fg-faint);
  background: var(--color-surface-sunken);
}
.li-status.sm {
  font-size: 10px;
  padding: 0 5px;
}
.li-status.draft {
  color: var(--color-fg-muted);
}
.li-status.waiting_approval {
  color: var(--color-warning-fg);
  background: var(--color-warning-soft);
}
.li-status.applied {
  color: var(--color-success-fg);
  background: var(--color-success-soft);
}
.li-status.rejected {
  color: var(--color-danger-fg);
  background: var(--color-danger-soft);
}
.li-status.rolled_back {
  color: var(--color-fg-muted);
}
.pane-empty {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
  text-align: center;
  padding: var(--space-4);
}

.cwf-detail {
  flex: 1;
  min-width: 0;
  overflow: auto;
  padding: var(--space-4);
  background: var(--color-bg);
}
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--color-fg-faint);
  gap: var(--space-2);
}
.empty p {
  margin: 0;
}
.empty .hint {
  font-size: var(--text-sm);
}
.msg {
  font-size: var(--text-sm);
  color: var(--color-fg-muted);
  margin-bottom: var(--space-3);
}
.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}
.detail-head h2 {
  margin: 0 0 4px;
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
}
.head-actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.file-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.file-item {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
}
.file-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-1);
}
.file-path {
  flex: 1;
  min-width: 0;
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
}
.diff-block {
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 280px;
  overflow: auto;
  background: var(--color-surface-sunken);
  padding: var(--space-2);
  border-radius: var(--radius);
}
.no-diff {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
}

.block {
  margin-bottom: var(--space-4);
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--color-fg-muted);
  margin-bottom: var(--space-2);
}
.block-empty {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
  padding: var(--space-2) 0;
}
.cmd-form {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.cmd-form .pa-input {
  height: 30px;
  font-size: var(--text-sm);
}
.cmd-form .cmd-str {
  flex: 1;
  min-width: 180px;
}
.cmd-form .timeout {
  width: 80px;
}
.en-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-sm);
  color: var(--color-fg-muted);
}
.cmd-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.cmd-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-2) var(--space-3);
}
.cmd-main {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  flex: 1;
}
.cmd-name {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
}
.cmd-kind {
  font-size: var(--text-xs);
  color: var(--color-accent-soft-fg);
  background: var(--color-accent-soft);
  padding: 1px 6px;
  border-radius: var(--radius-full);
}
.cmd-cmd {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  background: var(--color-surface-sunken);
  padding: 1px 6px;
  border-radius: var(--radius);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cmd-actions {
  display: flex;
  gap: var(--space-1);
  flex-shrink: 0;
}
.icon-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
  padding: 3px 8px;
  border-radius: var(--radius);
  cursor: pointer;
}
.icon-btn:hover {
  background: var(--color-surface-sunken);
}
.icon-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.icon-btn.run {
  color: var(--color-success-fg);
}
.icon-btn.del {
  color: var(--color-danger-fg);
}
.run-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
  flex-wrap: wrap;
}
.output-block {
  margin: 0 0 var(--space-2);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow: auto;
  background: var(--color-surface-sunken);
  padding: var(--space-2);
  border-radius: var(--radius);
}
.diagnose {
  background: var(--color-warning-soft);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  font-size: var(--text-sm);
}
.dia-summary {
  font-weight: var(--font-medium);
  margin-bottom: var(--space-1);
}
.dia-files {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: var(--space-1);
}
.dia-file {
  display: flex;
  gap: var(--space-2);
  font-size: var(--text-xs);
}
.dia-sug {
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
}

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal-card {
  width: 560px;
  max-width: 92vw;
  max-height: 88vh;
  overflow: auto;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--text-md);
  font-weight: var(--font-semibold);
  margin-bottom: var(--space-2);
}
.modal-label {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  margin-top: var(--space-2);
}
.patch-file-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: var(--space-1);
  align-items: center;
  margin-top: var(--space-2);
}
.pf-path {
  height: 28px;
  font-size: var(--text-sm);
}
.pf-create {
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  display: flex;
  align-items: center;
  gap: 3px;
}
.pf-content {
  grid-column: 1 / -1;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  resize: vertical;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-3);
}
</style>
