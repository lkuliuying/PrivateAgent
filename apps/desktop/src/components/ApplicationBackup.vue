<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import { open } from "@tauri-apps/plugin-dialog";
import { exportBackup, importBackup, previewBackup, type BackupPreview, type BackupImportResult, type BackupModelIdentity } from "../api/backups";
import { homeLayout, setHomeLayout } from "../services/homeLayout";
import { useNotifications } from "../stores/notifications";
const notify = useNotifications();
const emit = defineEmits<{ imported: [part: "configuration" | "data", result: BackupImportResult] }>();
const preview = ref<BackupPreview | null>(null);
const path = ref("");
const mappings = ref<Record<string, string>>({});
const workspaceMappings = ref<Record<string, string>>({});
const busy = ref(false), error = ref(""), status = ref("");
const configurationResult = ref<BackupImportResult | null>(null);
const dataResult = ref<BackupImportResult | null>(null);
let alive = true;
const urls = new Map<string, ReturnType<typeof setTimeout>>();
onBeforeUnmount(() => { alive = false; urls.forEach((timer, url) => { clearTimeout(timer); URL.revokeObjectURL(url); }); urls.clear(); });
const ready = computed(() => preview.value?.projects.every(item => mappings.value[String(item.id)]) && preview.value?.workspaces.every(item => workspaceMappings.value[String(item.id)]));
const countLabels: Record<string, string> = { projects: "项目", workspaces: "工作区", sessions: "会话", messages: "消息", runs: "运行记录", attachments: "附件总数", sent_attachments: "已发送附件", drafts: "草稿", draft_attachments: "未发送附件", model_selections: "模型选择", models_pending_confirmation: "待确认模型选择" };
function bytes(value?: number) { return value === undefined ? "未知" : value < 1024 ? `${value} B` : value < 1048576 ? `${(value / 1024).toFixed(1)} KiB` : `${(value / 1048576).toFixed(1)} MiB`; }
function identity(value: BackupModelIdentity | null) { return value ? `${value.provider_id} · ${value.protocol}/${value.api_format} · ${value.base_url} · ${value.model_id}` : "来源未记录，需重新确认"; }
async function act(work: () => Promise<void>) {
  if (!alive || busy.value) return;
  busy.value = true; error.value = ""; status.value = "";
  try { await work(); } catch (cause) { if (alive) error.value = (cause as Error).message || "备份操作未完成，请重试"; }
  finally { if (alive) busy.value = false; }
}
async function download(kind: "configuration" | "application") {
  await act(async () => {
    if (!await notify.confirm({ title: kind === "application" ? "导出应用数据备份？" : "导出普通配置？", impact: "包含所列配置、对话及材料，请保存在可信位置。API Key 和加密草稿不导出。", confirmLabel: "导出" }) || !alive) return;
    const blob = await exportBackup(kind, homeLayout.value);
    if (!alive) return;
    const url = URL.createObjectURL(blob);
    urls.set(url, setTimeout(() => { URL.revokeObjectURL(url); urls.delete(url); }, 60000));
    const link = document.createElement("a"); link.href = url; link.download = `privateagent-${kind}-backup.json`; link.click();
    status.value = "备份文件已生成，请确认文件已保存。";
  });
}
async function chooseFile() {
  await act(async () => {
    const selected = await open({ multiple: false, filters: [{ name: "PrivateAgent 备份", extensions: ["json"] }] });
    if (!alive || typeof selected !== "string") return;
    preview.value = null; configurationResult.value = null; dataResult.value = null; mappings.value = {}; workspaceMappings.value = {}; path.value = selected;
    const result = await previewBackup(selected); if (alive) preview.value = result;
  });
}
async function chooseDirectory(kind: "project" | "workspace", id: number) {
  await act(async () => {
    const selected = await open({ multiple: false, directory: true });
    if (!alive || typeof selected !== "string") return;
    if (kind === "project") {
      mappings.value[String(id)] = selected;
      for (const workspace of preview.value?.workspaces || []) if (workspace.project_id === id && workspace.kind === "root") workspaceMappings.value[String(workspace.id)] = selected;
    } else workspaceMappings.value[String(id)] = selected;
  });
}
async function restore(part: "configuration" | "data") {
  const reviewed = preview.value;
  if (!reviewed || (part === "data" && !ready.value)) return;
  const reviewedPath = path.value, reviewedMappings = { ...mappings.value }, reviewedWorkspaces = { ...workspaceMappings.value };
  await act(async () => {
    if (!await notify.confirm({ title: part === "configuration" ? "导入所列普通配置？" : "恢复所列应用数据？", impact: part === "configuration" ? "供应商 ID 相同则保留原配置；新增配置默认禁用。首页模式会替换为备份值，密钥需要重新填写。" : "为所列目录创建新的项目和会话，授权范围以映射目录为准。旧授权不恢复，任务不重放；待确认的模型选择必须在工作区重新选择后才能发送。", confirmLabel: "确认导入" }) || !alive) return;
    const result = await importBackup(reviewedPath, reviewed.sha256, part, reviewedMappings, reviewedWorkspaces);
    if (!alive) return;
    if (part === "configuration") {
      configurationResult.value = result;
      emit("imported", part, result);
      if (result.home_layout) {
        try { setHomeLayout(result.home_layout); } catch { throw new Error("模型配置已导入，首页偏好保存失败，请在外观设置中重新选择。"); }
      }
    } else {
      dataResult.value = result;
      emit("imported", part, result);
    }
  });
}
</script>
<template>
  <section class="application-backup" aria-label="配置与应用数据备份">
    <h3>配置与应用数据备份</h3>
    <p>普通配置包含供应商、模型 ID、请求地址、模型参数和首页模式；应用数据备份再包含历史、未发送草稿、项目引用和附件。总量上限 64 MiB。</p>
    <p>API Key、加密设置草稿、项目文件、长期记忆、Skills、MCP 和界面资源需另行保管，旧授权与运行现场不恢复。</p>
    <div class="backup-actions"><button class="pa-btn pa-btn--secondary" :disabled="busy" @click="download('configuration')">导出普通配置</button><button class="pa-btn pa-btn--secondary" :disabled="busy" @click="download('application')">导出应用数据备份</button><button class="pa-btn pa-btn--ghost" :disabled="busy" @click="chooseFile">选择备份并预览</button></div>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="status" role="status">{{ status }}</p>
    <article v-if="configurationResult" aria-label="普通配置导入结果" role="status">
      <h4>普通配置已导入</h4><p>新增供应商 {{ configurationResult.imported?.length ?? '未知' }} 个 · 保留相同 ID 配置 {{ configurationResult.skipped?.length ?? '未知' }} 个</p>
      <p v-if="configurationResult.imported?.length" class="path">新增供应商 ID：{{ configurationResult.imported.join('、') }}</p>
      <p v-if="configurationResult.skipped?.length" class="path">保留本机配置的供应商 ID：{{ configurationResult.skipped.join('、') }}</p>
      <p>请到模型设置补齐密钥并启用。应用数据回滚不会撤销本次配置导入。</p>
    </article>
    <article v-if="dataResult" aria-label="应用数据恢复结果" role="status">
      <h4>{{ dataResult.already_imported ? '此备份已导入，沿用原结果' : '应用数据已恢复' }}</h4>
      <p class="path">导入记录：{{ dataResult.id || '旧版接口未提供' }} · 格式：{{ dataResult.backup_format || preview?.format || '未知' }}</p>
      <dl><template v-for="(label, key) in countLabels" :key="key"><dt>{{ label }}</dt><dd>{{ dataResult.imported_counts?.[key] ?? '未知' }}</dd></template></dl>
      <p v-if="!dataResult.skipped_counts">跳过数量：旧版接口未提供</p>
      <template v-else><h4>本次未导入数量</h4><dl><template v-for="(count, key) in dataResult.skipped_counts" :key="key"><dt>{{ countLabels[key] || key }}</dt><dd>{{ count }}</dd></template></dl></template>
      <p>任务没有自动执行。待确认的模型选择需到对应项目或会话重新选择；导入记录与回滚入口见下方，回滚仅影响应用数据。</p>
    </article>
    <div v-if="preview" class="backup-preview">
      <h4>导入预览</h4><p class="path">{{ path }}</p>
      <p>格式 {{ preview.format || '未知（旧版接口）' }} · 创建时间 {{ preview.created_at || '未知' }} · 文件大小 {{ bytes(preview.size_bytes) }}</p>
      <p>覆盖范围：{{ preview.coverage?.join('、') || '旧版接口未提供，请核对下方清单与说明' }}</p>
      <p>供应商 {{ preview.providers.length }} 个 · 会话 {{ preview.counts.sessions ?? '未知' }} 个 · 消息 {{ preview.counts.messages ?? '未知' }} 条 · 已发送附件 {{ preview.counts.attachments ?? '未知' }} 个 · 草稿 {{ preview.counts.drafts ?? '未知' }} 个 · 草稿附件 {{ preview.counts.draft_attachments ?? '未知' }} 个</p>
      <p>导入配置后的首页模式：{{ preview.home_layout === 'compact' ? '紧凑' : '标准' }}</p>
      <ul><li v-for="warning in preview.warnings" :key="warning">{{ warning }}</li></ul>
      <article v-for="provider in preview.providers" :key="provider.id"><strong>{{ provider.name }}</strong> · {{ provider.conflict ? '供应商 ID 冲突：保留本机配置' : '新增：缺少凭据，导入后禁用' }}<p class="path">{{ provider.id }} · {{ provider.base_url }}</p></article>
      <article v-for="selection in preview.model_selections || []" :key="`${selection.scope}:${selection.id}`" aria-label="恢复模型选择核对">
        <strong>{{ selection.scope === 'project' ? '项目' : '会话' }} {{ selection.id }} · {{ selection.requires_confirmation ? '需重新确认模型' : '模型身份一致' }}</strong>
        <p class="path">原模型：{{ identity(selection.source_identity) }}</p><p v-if="selection.target_identity" class="path">{{ selection.source_scope === 'global' ? '本机全局默认' : '本机模型' }}：{{ identity(selection.target_identity) }}</p>
        <p v-if="selection.reason">{{ selection.reason }}</p>
      </article>
      <button class="pa-btn pa-btn--secondary" :disabled="busy" @click="restore('configuration')">确认导入普通配置</button>
      <template v-if="preview.kind === 'application'">
        <h4>项目与工作区目录映射</h4>
        <article v-for="project in preview.projects" :key="project.id"><p class="path">{{ project.name }} · {{ project.root_path }}</p><button class="pa-btn pa-btn--ghost path" :disabled="busy" @click="chooseDirectory('project', project.id)">{{ mappings[String(project.id)] || '选择项目目录' }}</button></article>
        <article v-for="workspace in preview.workspaces" :key="workspace.id"><p class="path">工作区 {{ workspace.id }} · {{ workspace.root_path }}</p><button class="pa-btn pa-btn--ghost path" :disabled="busy" @click="chooseDirectory('workspace', workspace.id)">{{ workspaceMappings[String(workspace.id)] || '选择工作区目录' }}</button></article>
        <button class="pa-btn pa-btn--primary" :disabled="busy || !ready" @click="restore('data')">确认恢复历史、草稿和附件</button>
      </template>
    </div>
  </section>
</template>
<style scoped>
.application-backup, .backup-preview { display: grid; gap: 12px; font-size: 13px; line-height: 1.6; }
.backup-actions { display: flex; flex-wrap: wrap; gap: 8px; }
h3, h4, p { margin: 0; }
dl { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 12px; margin: 8px 0; max-width: 360px; }
dd { margin: 0; }
.path { overflow-wrap: anywhere; white-space: normal; text-align: left; max-width: 100%; }
article { padding: 10px; border: 1px solid var(--color-border); border-radius: 8px; }
[role="alert"] { color: var(--color-danger); }
</style>
