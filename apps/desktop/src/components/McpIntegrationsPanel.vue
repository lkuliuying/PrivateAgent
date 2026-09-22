<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from "vue";
import { connectIntegration, createIntegration, listIntegrations, removeIntegration, selectIntegrationTools, type McpIntegration, type McpPermission } from "../features/coding/api/integrations";
import { openAuthorizationLink } from "../api/externalLinks";
import { useNotifications } from "../stores/notifications";
const props = defineProps<{ projectId: number }>();
const items = ref<McpIntegration[]>([]), busy = ref(false), error = ref("");
const form = reactive({ name: "", transport: "https", url: "", command: "", arguments: "[]", oauth: false, trust_process: false });
const selections = ref<Record<string, McpPermission[]>>({});
let timer: ReturnType<typeof setTimeout> | undefined;
let controller: AbortController | undefined;
let generation = 0, loadSequence = 0;
async function load() {
  const mine = generation, request = ++loadSequence; controller?.abort(); const current = controller = new AbortController();
  try {
    const result = await listIntegrations(props.projectId, current.signal);
    if (mine !== generation || request !== loadSequence) return;
    for (const source of result.items) if (!selections.value[source.id] || items.value.find(v => v.id === source.id)?.version !== source.version) selections.value[source.id] = source.tools.map(tool => ({ ...tool }));
    items.value = result.items;
  } catch (cause) { if (mine === generation && request === loadSequence && !current.signal.aborted) error.value = (cause as { message?: string }).message || "MCP 配置读取失败"; }
  finally { if (mine === generation && request === loadSequence) { clearTimeout(timer); if (items.value.some(item => ['connecting', 'authorization_required'].includes(item.connection.status ?? ''))) timer = setTimeout(() => void load(), 1000); } }
}
async function action(work: () => Promise<unknown>) {
  if (busy.value) return; busy.value = true; error.value = "";
  const mine = generation;
  try { await work(); if (mine === generation) await load(); }
  catch (cause) { if (mine === generation) error.value = (cause as { message?: string }).message || "操作失败，请重试"; }
  finally { if (mine === generation) busy.value = false; }
}
function add() {
  void action(async () => {
    const args: unknown = form.transport === "stdio" ? JSON.parse(form.arguments) : [];
    if (!Array.isArray(args) || args.some(value => typeof value !== "string")) throw new Error("参数须为字符串组成的 JSON 数组");
    await createIntegration(props.projectId, { name: form.name, transport: form.transport, url: form.transport === "https" ? form.url : "", command: form.transport === "stdio" ? form.command : "", args: form.transport === "stdio" ? args : [], oauth: form.transport === "https" && form.oauth, trust_process: form.transport === "stdio" && form.trust_process });
    form.name = ""; form.url = ""; form.command = ""; form.arguments = "[]"; form.trust_process = false;
  });
}
function permission(source: McpIntegration, name: string) { return selections.value[source.id]?.find(item => item.name === name); }
function toggle(source: McpIntegration, name: string, enabled: boolean) {
  const previous = selections.value[source.id] ?? [];
  selections.value[source.id] = enabled ? [...previous, { name, readonly: false, approval: "always" }] : previous.filter(item => item.name !== name);
}
async function remove(source: McpIntegration) {
  if (await useNotifications().confirm({ title: "移除此 MCP 服务？", message: "将撤销当前授权并取消正在进行的连接。", confirmLabel: "移除" })) void action(() => removeIntegration(props.projectId, source.id));
}
watch(() => props.projectId, () => { generation++; controller?.abort(); clearTimeout(timer); items.value = []; selections.value = {}; busy.value = false; error.value = ""; void load(); }, { immediate: true });
onBeforeUnmount(() => { generation++; controller?.abort(); clearTimeout(timer); });
</script>
<template>
  <section class="mcp-integrations" aria-label="通用 MCP 服务"><header><h2>MCP 工具</h2><p>连接 HTTPS 或本机 stdio 服务，检查工具后逐项启用。OAuth 登录只在本次应用进程内保存，退出后需重新登录。</p><button class="pa-btn pa-btn--ghost" @click="load">刷新状态</button></header>
    <p v-if="error" role="alert">{{ error }}</p>
    <details><summary>添加 MCP 服务</summary><form class="mcp-form" @submit.prevent="add"><label>名称<input v-model="form.name" class="pa-input" required maxlength="80" /></label><label>传输<select v-model="form.transport" class="pa-input"><option value="https">HTTPS</option><option value="stdio">本机进程（stdio）</option></select></label><template v-if="form.transport === 'https'"><label>服务地址<input v-model="form.url" class="pa-input" required placeholder="https://example.com/mcp" /></label><label><input v-model="form.oauth" type="checkbox" />使用 OAuth 登录</label></template><template v-else><label>可执行文件绝对路径<input v-model="form.command" class="pa-input" required placeholder="C:\\...\\node.exe" /></label><label>参数（JSON 数组）<textarea v-model="form.arguments" class="pa-input" rows="3" /></label><label class="process-trust"><input v-model="form.trust_process" type="checkbox" required />我信任此程序：它以当前用户权限运行，可访问本机和网络。不要在参数中填写密钥。</label></template><button class="pa-btn pa-btn--primary" :disabled="busy">保存配置</button></form></details>
    <p v-if="!items.length">暂无通用 MCP 服务。</p>
    <article v-for="source in items" :key="source.id"><div class="mcp-row"><div><strong>{{ source.name }}</strong><p>{{ source.transport }} · {{ source.enabled ? '工具已启用' : '工具未启用' }} · {{ ({ connecting: '连接中', authorization_required: '等待登录', connected: '已连接', error: '连接失败', cancelled: '已取消' } as Record<string, string>)[source.connection.status ?? ''] ?? '尚未连接' }}</p></div><button class="pa-btn pa-btn--subtle" :disabled="busy || ['connecting', 'authorization_required'].includes(source.connection.status ?? '')" @click="action(() => connectIntegration(projectId, source.id))">连接并发现</button><button class="pa-btn pa-btn--ghost" :disabled="busy" @click="remove(source)">移除</button></div><p v-if="source.connection.error" role="alert">{{ source.connection.error }}</p><a v-if="source.connection.authorization_url" :href="source.connection.authorization_url" @click.prevent="action(() => openAuthorizationLink(source.connection.authorization_url!))" class="pa-btn pa-btn--primary">在浏览器完成 OAuth 登录</a>
      <details v-if="source.catalog"><summary>检查并选择工具（{{ source.catalog.tools.length }}）</summary><div v-for="tool in source.catalog.tools" :key="tool.name" class="mcp-tool"><label><input type="checkbox" :checked="!!permission(source, tool.name)" @change="toggle(source, tool.name, ($event.target as HTMLInputElement).checked)" />{{ tool.name }}</label><p>{{ tool.description }}</p><details><summary>参数结构</summary><pre>{{ JSON.stringify(tool.input_schema, null, 2) }}</pre></details><template v-if="permission(source, tool.name)"><label><input v-model="permission(source, tool.name)!.readonly" type="checkbox" @change="permission(source, tool.name)!.approval = 'always'" />我已核对这是只读工具</label><select v-model="permission(source, tool.name)!.approval" class="pa-input" :aria-label="`${tool.name} 授权范围`"><option value="always">每次询问</option><option v-if="permission(source, tool.name)!.readonly" value="session">首次同意后允许当前会话</option></select></template></div><div class="mcp-row"><button class="pa-btn pa-btn--primary" :disabled="busy" @click="action(() => selectIntegrationTools(projectId, source, true, selections[source.id] ?? []))">保存并启用所选工具</button><button v-if="source.enabled" class="pa-btn pa-btn--ghost" :disabled="busy" @click="action(() => selectIntegrationTools(projectId, source, false, []))">停用全部</button></div></details>
    </article>
  </section>
</template>
<style scoped>
.mcp-integrations { display: grid; gap: var(--space-5); font-size: var(--pa-text-body); overflow-wrap: anywhere; }
.mcp-integrations h2 { margin: 0; font-size: 18px; }
p { color: var(--color-fg-muted); line-height: 1.6; margin: var(--space-2) 0; }
summary { cursor: pointer; padding: var(--space-3) 0; font-weight: var(--font-medium); }
.mcp-integrations > details { border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: 0 var(--space-4); background: var(--color-surface-muted); }
.mcp-form { display: grid; gap: var(--space-4); max-width: 680px; padding-block: var(--space-3) var(--space-5); }
.mcp-form > button { justify-self: start; }
label { display: flex; gap: var(--space-2); align-items: center; flex-wrap: wrap; }
.mcp-form label > .pa-input { width: 100%; }
.process-trust { line-height: 1.5; }
.mcp-row { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
.mcp-row > div { flex: 1; min-width: 160px; }
article { border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: var(--space-4); }
article strong { font-size: 16px; }
.mcp-tool { padding: var(--space-3); border-top: 1px solid var(--color-border); }
.mcp-tool > select { width: auto; max-width: 100%; margin: var(--space-2) 0; }
pre { max-height: 220px; overflow: auto; padding: var(--space-3); border-radius: var(--radius-md); background: var(--color-surface-sunken); font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
[role="alert"] { color: var(--color-danger-fg); }
</style>
