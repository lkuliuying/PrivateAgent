<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { apiFetch, ensureApiBase } from "../api/http";
import { exportHistoryArchive } from "../api/backups";
import { useNotifications } from "../stores/notifications";

interface Preview { sha256: string; counts: Record<string, number>; projects: { id: number; name: string; root_path: string }[]; warnings: string[] }
interface Imported { id: string; created_at: string; counts: Record<string, number>; imported_counts: Record<string, number>; source_kind?: string; backup_format?: string }
const emit = defineEmits<{ changed: [] }>();
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
let alive = true;
const downloads = new Map<string, ReturnType<typeof setTimeout>>();
onBeforeUnmount(() => { alive = false; downloads.forEach((timer, url) => { clearTimeout(timer); URL.revokeObjectURL(url); }); downloads.clear(); });

async function request<T>(url: string, body?: object): Promise<T> {
  const base = await ensureApiBase();
  const result = await apiFetch(`${base}${url}`, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  if (!result.ok) {
    const response = await result.json().catch(() => null);
    throw new Error(typeof response?.detail === "string" ? response.detail : `历史操作失败（${result.status}），请确认本机连接和客户端版本`);
  }
  return result.json();
}

async function act(work: () => Promise<void>): Promise<void> {
  if (!alive || busy.value) return;
  busy.value = true; error.value = "";
  try { await work(); } catch (reason) { if (alive) error.value = reason instanceof Error ? reason.message : "历史操作失败"; }
  finally { if (alive) busy.value = false; }
}
async function refresh(): Promise<void> { const value = await request<Imported[]>("/local-history/imports"); if (alive) imports.value = value; }
onMounted(() => void act(refresh));

async function chooseFile(): Promise<void> {
  await act(async () => {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({ multiple: false, directory: false, filters: [{ name: "PrivateAgent 历史", extensions: ["json", "sqlite3", "sqlite", "db"] }] });
    if (!alive || typeof selected !== "string") return;
    path.value = selected; preview.value = null; mappings.value = {};
    const value = await request<Preview>("/local-history/preview", { path: selected }); if (alive) preview.value = value;
  });
}
async function chooseRoot(id: number): Promise<void> {
  await act(async () => {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({ multiple: false, directory: true });
    if (alive && typeof selected === "string") mappings.value = { ...mappings.value, [String(id)]: selected };
  });
}
async function importHistory(): Promise<void> {
  if (!preview.value) return;
  const reviewed = { path: path.value, sha256: preview.value.sha256, mappings: { ...mappings.value } };
  await act(async () => {
    const confirmed = await notify.confirm({ title: "导入本机工作区的历史？", impact: "所选本机目录将授权给导入的 Coding 任务。未选择目录的记录和旧 AgentTask 仅归档。不会恢复完全访问授权、审批或执行中的命令。", confirmLabel: "确认导入" });
    if (!confirmed || !alive) return;
    await request("/local-history/import", reviewed);
    if (!alive) return;
    preview.value = null;
    emit("changed");
    await refresh();
    if (alive) notify.success("历史已导入", "工作区已请求刷新，导入记录与只读归档可在下方查看。");
  });
}
async function rollback(item: Imported): Promise<void> {
  await act(async () => {
    if (!await notify.confirm({ title: "回滚这次数据导入？", impact: "仅回滚历史、草稿与附件等应用数据，不撤销单独导入的模型配置。只有导入后没有其他本机修改时才允许自动回滚，备份会保留。", confirmLabel: "核对并回滚", danger: true }) || !alive) return;
    await request(`/local-history/imports/${item.id}/rollback`, {});
    if (!alive) return;
    records.value = null; emit("changed"); await refresh();
  });
}
async function browse(item: Imported, nextOffset = 0): Promise<void> {
  await act(async () => {
    selectedImport.value = item.id; offset.value = nextOffset;
    const value = await request<{ total: number; items: unknown[] }>(`/local-history/imports/${item.id}/records?kind=${selectedKind.value}&offset=${nextOffset}&limit=20`);
    if (alive) records.value = value;
  });
}
async function download(importId?: string): Promise<void> {
  await act(async () => {
    if (!await notify.confirm({ title: "导出历史归档？", impact: "文件只包含历史、已发送附件及工具记录，不含配置、草稿、未发送附件和模型选择，不能替代完整应用备份。请保存在可信位置。", confirmLabel: "导出历史" }) || !alive) return;
    const blob = await exportHistoryArchive(importId);
    if (!alive) return;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a"); link.href = url; link.download = "privateagent-history.json"; link.click();
    downloads.set(url, setTimeout(() => { URL.revokeObjectURL(url); downloads.delete(url); }, 60000));
  });
}
</script>

<template>
  <section class="history-migration" aria-label="本机历史迁移">
    <p>SQLite 保存当前本机工作区的记录。项目文件不包含在历史包内；跨版本迁移需重新选择本机目录。</p>
    <div class="actions">
      <button :disabled="busy" @click="chooseFile">选择旧 SQLite / 历史 JSON</button>
      <button :disabled="busy" @click="download()">导出当前工作记录</button>
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
    <div class="actions"><h3>导入记录与只读历史归档</h3><button :disabled="busy" @click="act(refresh)">刷新导入记录</button></div>
    <p v-if="!imports.length && !busy">暂无数据导入记录。普通配置导入不在此列表中。</p>
    <article v-for="item in imports" :key="item.id">
      <p>{{ item.source_kind === 'application' ? '应用数据备份' : item.source_kind === 'history' ? '历史迁移' : '旧导入记录（来源类型未知）' }} · {{ item.created_at }} · {{ item.backup_format || '格式未记录' }}</p>
      <p>导入 Coding 会话 {{ item.imported_counts.sessions ?? '未知' }} · 归档旧 AgentTask {{ item.counts.agent_tasks ?? '未知' }}</p>
      <p v-if="item.source_kind === 'application'">草稿 {{ item.imported_counts.drafts ?? '未知' }} 个 · 未发送附件 {{ item.imported_counts.draft_attachments ?? '未知' }} 个 · 模型选择 {{ item.imported_counts.model_selections ?? '未知' }} 个 · 待确认模型 {{ item.imported_counts.models_pending_confirmation ?? '未知' }} 个</p>
      <p>这里保留的是历史子集，重新导出不包含配置、草稿、未发送附件和模型选择。数据回滚也不会撤销模型配置导入。</p>
      <div class="actions"><select v-model="selectedKind" aria-label="历史记录类型"><option v-for="(_, kind) in item.counts" :key="kind" :value="kind">{{ kind }}</option></select>
        <button :disabled="busy" @click="browse(item)">只读查看</button><button :disabled="busy" @click="download(item.id)">导出历史归档（不含配置和草稿）</button><button :disabled="busy" @click="rollback(item)">核对并回滚数据</button></div>
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
