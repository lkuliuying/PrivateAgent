<script setup lang="ts">
import { onMounted, ref } from "vue";
import { apiFetch, ensureApiBase } from "../api/http";
import { isLocalConnection } from "../services/connectionProfile";
import { useNotifications } from "../stores/notifications";

interface Preview { sha256: string; counts: Record<string, number>; projects: { id: number; name: string; root_path: string }[]; warnings: string[] }
interface Imported { id: string; created_at: string; counts: Record<string, number>; imported_counts: Record<string, number> }
const path = ref("");
const preview = ref<Preview | null>(null);
const mappings = ref<Record<string, string>>({});
const imports = ref<Imported[]>([]);
const busy = ref(false);
const error = ref("");
const records = ref<{ total: number; items: unknown[] } | null>(null);
const selectedImport = ref("");
const selectedKind = ref("agent_tasks");
const offset = ref(0);
const notify = useNotifications();
const local = isLocalConnection();

async function request<T>(url: string, body?: object): Promise<T> {
  const base = await ensureApiBase();
  const result = await apiFetch(`${base}${url}`, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  if (!result.ok) {
    const response = await result.json().catch(() => null);
    throw new Error(typeof response?.detail === "string" ? response.detail : `历史操作失败（${result.status}），请确认账号和服务版本`);
  }
  return result.json();
}

async function act(work: () => Promise<void>): Promise<void> {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try { await work(); } catch (reason) { error.value = reason instanceof Error ? reason.message : "历史操作失败"; }
  finally { busy.value = false; }
}
async function refresh(): Promise<void> { imports.value = await request<Imported[]>("/local-history/imports"); }
onMounted(() => void act(refresh));

async function chooseFile(): Promise<void> {
  await act(async () => {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({ multiple: false, directory: false, filters: [{ name: "PrivateAgent 历史", extensions: ["json", "sqlite3", "sqlite", "db"] }] });
    if (typeof selected !== "string") return;
    path.value = selected; preview.value = null; mappings.value = {};
    preview.value = await request<Preview>("/local-history/preview", { path: selected });
  });
}
async function chooseRoot(id: number): Promise<void> {
  await act(async () => {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({ multiple: false, directory: true });
    if (typeof selected === "string") mappings.value = { ...mappings.value, [String(id)]: selected };
  });
}
async function importHistory(): Promise<void> {
  if (!preview.value) return;
  const confirmed = await notify.confirm({ title: "导入当前账号的历史？", impact: "所选本机目录将授权给导入的 Coding 任务。未选择目录的记录和旧 AgentTask 仅归档。不会恢复完全访问授权、审批或执行中的命令。", confirmLabel: "确认导入" });
  if (!confirmed) return;
  await act(async () => {
    await request("/local-history/import", { path: path.value, sha256: preview.value!.sha256, mappings: mappings.value });
    preview.value = null;
    await refresh();
    notify.success("历史已导入", "重新进入项目页即可刷新任务列表；只读归档可在下方查看。");
  });
}
async function rollback(item: Imported): Promise<void> {
  if (!await notify.confirm({ title: "回滚这次历史导入？", impact: "只有导入后没有其他本机修改时才允许自动回滚。备份会保留。", confirmLabel: "核对并回滚", danger: true })) return;
  await act(async () => { await request(`/local-history/imports/${item.id}/rollback`, {}); records.value = null; await refresh(); });
}
async function browse(item: Imported, nextOffset = 0): Promise<void> {
  await act(async () => {
    selectedImport.value = item.id; offset.value = nextOffset;
    records.value = await request(`/local-history/imports/${item.id}/records?kind=${selectedKind.value}&offset=${nextOffset}&limit=20`);
  });
}
async function download(server = false, importId?: string): Promise<void> {
  if (!await notify.confirm({ title: "导出当前账号的历史？", impact: "文件包含对话、代码片段和工具记录，请保存在可信位置。不会包含供应商配置或有效授权令牌。", confirmLabel: "导出历史" })) return;
  await act(async () => {
    const data = await request(importId ? `/local-history/imports/${importId}/export` : server ? "/desktop/history/export" : "/local-history/export");
    const blob = new Blob([JSON.stringify(data)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a"); link.href = url; link.download = "privateagent-history.json"; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 60000);
  });
}
</script>

<template>
  <section class="history-migration" aria-label="本机历史迁移">
    <p>SQLite 按账号保存本机记录。项目文件不包含在历史包内；跨版本迁移需重新选择本机目录。</p>
    <div class="actions">
      <button :disabled="busy" @click="chooseFile">选择旧 SQLite / 历史 JSON</button>
      <button :disabled="busy" @click="download(false)">导出当前工作记录</button>
      <button v-if="!local" :disabled="busy" @click="download(true)">导出旧完整后端历史</button>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="preview">
      <p>{{ path }}</p><p class="digest">SHA-256：{{ preview.sha256 }}</p>
      <ul><li v-for="warning in preview.warnings" :key="warning">{{ warning }}</li></ul>
      <dl><template v-for="(count, kind) in preview.counts" :key="kind"><dt>{{ kind }}</dt><dd>{{ count }}</dd></template></dl>
      <div v-for="project in preview.projects" :key="project.id" class="project-mapping">
        <span>{{ project.name }} · 原目录 {{ project.root_path }}</span>
        <button :disabled="busy" @click="chooseRoot(project.id)">{{ mappings[String(project.id)] || "选择本机目录（不选则仅归档）" }}</button>
        <button v-if="mappings[String(project.id)]" :disabled="busy" @click="delete mappings[String(project.id)]">仅归档</button>
      </div>
      <button :disabled="busy" @click="importHistory">确认导入所选历史</button>
    </template>
    <h3 v-if="imports.length">迁移记录与只读归档</h3>
    <article v-for="item in imports" :key="item.id">
      <p>{{ item.created_at }} · 导入 Coding 会话 {{ item.imported_counts.sessions || 0 }} · 归档旧 AgentTask {{ item.counts.agent_tasks || 0 }}</p>
      <div class="actions"><select v-model="selectedKind" aria-label="历史记录类型"><option v-for="(_, kind) in item.counts" :key="kind" :value="kind">{{ kind }}</option></select>
        <button :disabled="busy" @click="browse(item)">只读查看</button><button :disabled="busy" @click="download(false, item.id)">导出原始归档</button><button :disabled="busy" @click="rollback(item)">核对并回滚</button></div>
      <template v-if="records && selectedImport === item.id">
        <p>共 {{ records.total }} 条，本页从第 {{ offset + 1 }} 条开始；归档内容不会执行。</p>
        <pre>{{ JSON.stringify(records.items, null, 2) }}</pre>
        <button :disabled="busy || offset === 0" @click="browse(item, Math.max(0, offset - 20))">上一页</button>
        <button :disabled="busy || offset + 20 >= records.total" @click="browse(item, offset + 20)">下一页</button>
      </template>
    </article>
  </section>
</template>

<style scoped>
.history-migration { display: grid; gap: 12px; font-size: 13px; }
.actions, .project-mapping { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
button, select { font: inherit; padding: 7px 10px; border: 1px solid var(--color-border); border-radius: 6px; background: var(--color-surface); color: inherit; }
button:disabled { opacity: .5; }
dl { display: grid; grid-template-columns: 1fr 1fr; max-width: 320px; margin: 0; }
dd { margin: 0; }
pre { max-height: 400px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; background: var(--color-surface-sunken); padding: 12px; }
.digest { overflow-wrap: anywhere; }
[role="alert"] { color: var(--color-danger); }
</style>
