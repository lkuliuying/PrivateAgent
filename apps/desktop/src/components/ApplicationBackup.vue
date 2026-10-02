<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import { open } from "@tauri-apps/plugin-dialog";
import { exportBackup, importBackup, previewBackup, type BackupPreview } from "../api/backups";
import { homeLayout, setHomeLayout } from "../services/homeLayout";
import { useNotifications } from "../stores/notifications";
const notify = useNotifications();
const preview = ref<BackupPreview | null>(null);
const path = ref("");
const mappings = ref<Record<string, string>>({});
const workspaceMappings = ref<Record<string, string>>({});
const busy = ref(false), error = ref(""), status = ref("");
let alive = true;
const urls: string[] = [];
onBeforeUnmount(() => { alive = false; urls.forEach(value => URL.revokeObjectURL(value)); });
const ready = computed(() => preview.value?.projects.every(item => mappings.value[String(item.id)]) && preview.value?.workspaces.every(item => workspaceMappings.value[String(item.id)]));
async function act(work: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; error.value = ""; status.value = "";
  try { await work(); } catch (cause) { if (alive) error.value = (cause as Error).message || "备份操作未完成，请重试"; }
  finally { if (alive) busy.value = false; }
}
async function download(kind: "configuration" | "application") {
  if (!await notify.confirm({ title: kind === "application" ? "导出应用数据备份？" : "导出普通配置？", impact: "包含所列配置、对话及材料，请保存在可信位置。API Key 和加密草稿不导出。", confirmLabel: "导出" })) return;
  await act(async () => {
    const data = await exportBackup(kind, homeLayout.value);
    if (!alive) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(data)], { type: "application/json" })); urls.push(url);
    const link = document.createElement("a"); link.href = url; link.download = `privateagent-${kind}-backup.json`; link.click();
    status.value = "备份文件已生成，请确认文件已保存。";
  });
}
async function chooseFile() {
  await act(async () => {
    const selected = await open({ multiple: false, filters: [{ name: "PrivateAgent 备份", extensions: ["json"] }] });
    if (!alive || typeof selected !== "string") return;
    preview.value = null; mappings.value = {}; workspaceMappings.value = {}; path.value = selected;
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
  if (!reviewed) return;
  if (!await notify.confirm({ title: part === "configuration" ? "导入所列普通配置？" : "恢复所列应用数据？", impact: part === "configuration" ? "同名供应商保留原配置；新增配置默认禁用。首页模式会替换为备份值，密钥需要重新填写。" : "为所列目录创建新的项目和会话，授权范围以映射目录为准。旧授权不恢复，任务不重放。", confirmLabel: "确认导入" })) return;
  await act(async () => {
    const result = await importBackup(path.value, reviewed.sha256, part, mappings.value, workspaceMappings.value);
    if (!alive) return;
    if (part === "configuration") {
      status.value = `已导入 ${result.imported?.length || 0} 个供应商，保留 ${result.skipped?.length || 0} 个同名配置。请到模型设置补齐密钥并启用。`;
      if (result.home_layout) {
        try { setHomeLayout(result.home_layout); } catch { throw new Error("模型配置已导入，首页偏好保存失败，请在外观设置中重新选择。"); }
      }
    } else status.value = "历史、草稿和附件已恢复。返回工作区刷新项目即可查看；任务没有自动执行。";
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
    <div v-if="preview" class="backup-preview">
      <h4>导入预览</h4><p class="path">{{ path }}</p>
      <p>供应商 {{ preview.providers.length }} 个 · 会话 {{ preview.counts.sessions || 0 }} 个 · 草稿 {{ preview.counts.drafts }} 个 · 草稿附件 {{ preview.counts.draft_attachments }} 个</p>
      <ul><li v-for="warning in preview.warnings" :key="warning">{{ warning }}</li></ul>
      <article v-for="provider in preview.providers" :key="provider.id"><strong>{{ provider.name }}</strong> · {{ provider.conflict ? '同名冲突：保留本机配置' : '新增：缺少凭据，导入后禁用' }}<p class="path">{{ provider.base_url }}</p></article>
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
.path { overflow-wrap: anywhere; white-space: normal; text-align: left; max-width: 100%; }
article { padding: 10px; border: 1px solid var(--color-border); border-radius: 8px; }
[role="alert"] { color: var(--color-danger); }
</style>
