<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { bindMcpService, connectIntegration, createIntegration, discardMcpChange, listIntegrations, listMcpServices,
  logoutMcpService, persistMcpChange, preflightMcpService, prepareMcpService, removeIntegration, removeMcpService, retryMcpCredentialCleanup,
  selectIntegrationTools, type McpChange, type McpConfiguration, type McpIntegration, type McpPermission, type McpService } from "../features/coding/api/integrations";
import { openAuthorizationLink } from "../api/externalLinks";
import { useNotifications } from "../stores/notifications";

const props = defineProps<{ projectId: number }>();
const items = ref<McpIntegration[]>([]), services = ref<McpService[]>([]), pending = ref<McpChange[]>([]);
const cleanupCount = ref(0);
const busy = ref(false), loading = ref(false), error = ref(""), notice = ref("");
const editing = ref<McpService | null>(null), formOpen = ref(false), replaceCredentials = ref(false);
const form = reactive({ name: "", transport: "https", url: "", command: "", arguments: "[]", authMode: "none", oauthPersistence: "persistent", headers: "", environment: "", trust_process: false });
const values = reactive<Record<string, string>>({});
const argumentRows = ref<{ id: number; value: string }[]>([]);
let argumentSequence = 0;
const advancedArguments = ref(false);
const selections = ref<Record<string, McpPermission[]>>({});
const fieldErrors = ref<Record<string, string>>({});
const argumentExample = '["C:\\\\mcp\\\\server.js", "--port", "3000"]';
const names = (value: string) => value.split(/[,\n]/).map(item => item.trim()).filter(Boolean);
const credentialFields = computed(() => form.transport === "stdio" ? names(form.environment).map(name => "env:" + name)
  : form.authMode === "bearer" ? ["bearer"] : form.authMode === "custom_headers" ? names(form.headers).map(name => "header:" + name) : []);
const inputCredentials = computed(() => !editing.value || replaceCredentials.value);
const stateNames: Record<string, string> = { connecting: "连接中", authorization_required: "等待登录", connected: "目录已验证", error: "连接失败", cancelled: "已取消" };
function connectionLabel(source: McpIntegration) {
  const state = source.connection.status ?? "";
  if (["connecting", "authorization_required", "error", "cancelled"].includes(state)) return stateNames[state];
  return source.needs_validation ? "需要重新验证" : stateNames[state] ?? "配置已保存";
}
let timer: ReturnType<typeof setTimeout> | undefined;
let controller: AbortController | undefined;
let generation = 0, loadSequence = 0;

function clearValues() { for (const key of Object.keys(values)) delete values[key]; }
function resetForm() {
  editing.value = null; replaceCredentials.value = false; clearValues(); fieldErrors.value = {};
  Object.assign(form, { name: "", transport: "https", url: "", command: "", arguments: "[]", authMode: "none", oauthPersistence: "persistent", headers: "", environment: "", trust_process: false });
  argumentRows.value = []; advancedArguments.value = false;
}
function syncArguments() { form.arguments = JSON.stringify(argumentRows.value.map(item => item.value)); }
function addArgument() { argumentRows.value.push({ id: ++argumentSequence, value: "" }); syncArguments(); }
function removeArgument(id: number) { argumentRows.value = argumentRows.value.filter(item => item.id !== id); syncArguments(); }
function importArguments() {
  try {
    const parsed: unknown = JSON.parse(form.arguments);
    if (!Array.isArray(parsed) || parsed.some(item => typeof item !== "string") || parsed.length > 32) throw new Error();
    argumentRows.value = parsed.map(value => ({ id: ++argumentSequence, value }));
    delete fieldErrors.value.arguments;
    notice.value = "JSON 参数已导入逐项编辑；空字符串保留为一个独立参数。";
  } catch { fieldErrors.value.arguments = "参数必须是最多 32 项的字符串 JSON 数组；原有参数行保持不变。"; }
}
function verifiedTime(value?: string | null) {
  if (!value) return "尚未验证";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "验证时间不可用" : parsed.toLocaleString("zh-CN");
}
async function load() {
  const mine = generation, request = ++loadSequence; controller?.abort(); const current = controller = new AbortController(); loading.value = true;
  try {
    const [project, library] = await Promise.all([listIntegrations(props.projectId, current.signal), listMcpServices(current.signal)]);
    if (mine !== generation || request !== loadSequence) return;
    for (const source of project.items) if (!selections.value[source.id] || items.value.find(item => item.id === source.id)?.version !== source.version) selections.value[source.id] = source.tools.map(tool => ({ ...tool }));
    items.value = project.items; services.value = library.items; pending.value = library.pending_changes;
    cleanupCount.value = library.credential_cleanup_pending?.length ?? 0;
  } catch (cause) {
    if (mine === generation && request === loadSequence && !current.signal.aborted) error.value = (cause as { message?: string }).message || "MCP 配置读取失败";
  } finally {
    if (mine === generation && request === loadSequence) {
      loading.value = false; clearTimeout(timer);
      if (items.value.some(item => ["connecting", "authorization_required"].includes(item.connection.status ?? ""))) timer = setTimeout(() => void load(), 1000);
    }
  }
}
async function action(work: () => Promise<unknown>) {
  if (busy.value) return; busy.value = true; error.value = ""; notice.value = "";
  const mine = generation;
  try { await work(); if (mine === generation) await load(); }
  catch (cause) { if (mine === generation) error.value = (cause as { message?: string }).message || "操作失败，请重试"; }
  finally { if (mine === generation) busy.value = false; }
}
function configuration(): McpConfiguration | null {
  fieldErrors.value = {};
  if (!form.name.trim()) fieldErrors.value.name = "请填写服务名称";
  let args: string[] = [];
  if (form.transport === "https") {
    try {
      const url = new URL(form.url.trim());
      if (url.protocol !== "https:" || !url.hostname || url.username || url.password || url.hash || (url.port && url.port !== "443")) throw new Error();
    } catch { fieldErrors.value.url = "请填写完整 HTTPS 地址，地址中不能包含账号或密码。例如 https://example.com/mcp"; }
  } else {
    if (!/^(?:[A-Za-z]:[\\/]|\/|\\\\)/.test(form.command.trim())) fieldErrors.value.command = "请填写可执行文件的绝对路径，例如 C:\\tools\\node.exe";
    try {
      const parsed: unknown = JSON.parse(form.arguments);
      if (!Array.isArray(parsed) || parsed.some(value => typeof value !== "string")) throw new Error();
      args = parsed;
    } catch { fieldErrors.value.arguments = "参数必须是字符串 JSON 数组；每个参数单独加双引号，Windows 路径中的反斜杠需要写成两个。"; }
    if (!form.trust_process) fieldErrors.value.trust = "保存前请确认你信任此本机程序";
  }
  if (Object.keys(fieldErrors.value).length) { error.value = "配置尚未保存，请修正标出的字段。"; return null; }
  return { name: form.name.trim(), transport: form.transport as "https" | "stdio", url: form.transport === "https" ? form.url.trim() : "",
    command: form.transport === "stdio" ? form.command.trim() : "", args, oauth: form.transport === "https" && form.authMode === "oauth",
    auth_mode: (form.transport === "https" ? form.authMode : "none") as McpConfiguration["auth_mode"],
    oauth_persistence: form.oauthPersistence as "persistent" | "session",
    header_names: form.transport === "https" && form.authMode === "custom_headers" ? names(form.headers) : [],
    env_names: form.transport === "stdio" ? names(form.environment) : [], trust_process: form.transport === "stdio" && form.trust_process };
}
async function preflight() {
  const data = configuration(); if (!data) return;
  const mine = generation;
  await action(async () => { const result = await preflightMcpService(data); if (mine === generation) notice.value = result.notice; });
}
async function add() {
  const data = configuration(); if (!data || busy.value) return;
  const target = editing.value, project = props.projectId, mine = generation;
  const fields = [...credentialFields.value], replace = inputCredentials.value && fields.length > 0;
  const entered = replace ? Object.fromEntries(fields.map(key => [key, values[key] ?? ""])) : undefined;
  if (replace && fields.some(key => !entered?.[key])) { error.value = "请填写全部认证字段；凭据只保存到系统凭据库。"; return; }
  if (target && target.projects.length && !await useNotifications().confirm({ title: "更新个人 MCP 服务？", message: "以下项目需要重新发现工具和确认授权：" + target.projects.map(item => item.project_name).join("、"), confirmLabel: "保存并使旧授权失效" })) return;
  if (mine !== generation) return;
  await action(async () => {
    await preflightMcpService(data);
    if (!target && !fields.length) {
      await createIntegration(project, data);
    } else {
      const change = await prepareMcpService({ request_id: crypto.randomUUID().replace(/-/g, ""), service_id: target?.id,
        expected_version: target?.version, configuration: data, replace_credentials: replace });
      const service = await persistMcpChange(change, change.replace_credentials ? entered : undefined);
      if (!target) await bindMcpService(project, service.id);
    }
    if (mine === generation) { resetForm(); formOpen.value = false; notice.value = "配置已保存。请连接并发现工具，然后在当前项目逐项启用。"; }
  });
}
function edit(service: McpService) {
  resetForm(); editing.value = service; formOpen.value = true;
  Object.assign(form, { name: service.name, transport: service.transport, url: service.url, command: service.command, arguments: JSON.stringify(service.args),
    authMode: service.auth_mode ?? (service.oauth ? "oauth" : "none"), oauthPersistence: service.oauth_persistence ?? "persistent",
    headers: (service.header_names ?? []).join("\n"), environment: (service.env_names ?? []).join("\n"), trust_process: service.trust_process });
  argumentRows.value = service.args.map(value => ({ id: ++argumentSequence, value }));
}
function permission(source: McpIntegration, name: string) { return selections.value[source.id]?.find(item => item.name === name); }
function toggle(source: McpIntegration, name: string, enabled: boolean) {
  const previous = selections.value[source.id] ?? [];
  selections.value[source.id] = enabled ? [...previous, { name, readonly: false, approval: "always" }] : previous.filter(item => item.name !== name);
}
async function remove(source: McpIntegration) {
  const project = props.projectId, mine = generation;
  if (await useNotifications().confirm({ title: "解除当前项目绑定？", message: "当前项目的工具授权将失效，个人库服务与其他项目保持可用。", confirmLabel: "解除绑定" }) && mine === generation) await action(() => removeIntegration(project, source.id));
}
async function deleteService(service: McpService) {
  const mine = generation;
  if (await useNotifications().confirm({ title: "删除个人 MCP 服务？", message: "将移除服务和该服务保存的认证凭据。仍有项目绑定时不能删除。", confirmLabel: "删除服务" }) && mine === generation) await action(() => removeMcpService(service));
}
async function logout(service: McpService) {
  const mine = generation;
  if (await useNotifications().confirm({ title: "退出共享 OAuth 登录？", message: "这些项目需要重新登录和授权：" + (service.projects.map(item => item.project_name).join("、") || "无项目绑定"), confirmLabel: "退出登录" }) && mine === generation) await action(() => logoutMcpService(service));
}
async function resume(change: McpChange) {
  await action(async () => { const prepared = await prepareMcpService(change.request); await persistMcpChange(prepared); });
}
watch(() => [form.transport, form.authMode], () => clearValues());
watch(() => props.projectId, () => { generation++; controller?.abort(); clearTimeout(timer); items.value = []; services.value = []; pending.value = []; cleanupCount.value = 0; selections.value = {}; busy.value = false; error.value = ""; resetForm(); void load(); }, { immediate: true });
onBeforeUnmount(() => { generation++; controller?.abort(); clearTimeout(timer); clearValues(); });
</script>
<template>
  <section class="mcp-integrations" aria-label="通用 MCP 服务">
    <header class="mcp-row"><div><h2>MCP 工具</h2><p>个人服务库维护连接与登录；每个项目独立选择工具和批准调用。</p></div><button class="pa-btn pa-btn--ghost" :disabled="busy || loading" @click="load">刷新状态</button></header>
    <p v-if="loading && !items.length" role="status">正在读取 MCP 配置…</p>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="notice" role="status">{{ notice }}</p>
    <div v-if="cleanupCount" class="mcp-row" role="status"><p>{{ cleanupCount }} 项旧凭据尚未从系统凭据库清除，已停止用于连接。请在桌面端重试清理。</p><button class="pa-btn pa-btn--subtle" :disabled="busy" @click="action(() => retryMcpCredentialCleanup())">重试清理旧凭据</button></div>
    <details :open="formOpen" @toggle="formOpen = ($event.target as HTMLDetailsElement).open">
      <summary>{{ editing ? '编辑个人 MCP 服务' : '添加 MCP 服务' }}</summary>
      <form class="mcp-form" novalidate @submit.prevent="add">
        <p>① 本地检查配置　② 保存到个人库　③ 连接并发现　④ 在当前项目选择工具。保存不会启动服务。</p>
        <label>名称<input v-model="form.name" class="pa-input" maxlength="80" :disabled="busy" :aria-invalid="!!fieldErrors.name" /><span v-if="fieldErrors.name" class="mcp-field-error">{{ fieldErrors.name }}</span></label>
        <label>连接类型<select v-model="form.transport" class="pa-input" :disabled="busy" @change="fieldErrors = {}"><option value="https">HTTPS 服务</option><option value="stdio">本机进程（stdio）</option></select></label>
        <template v-if="form.transport === 'https'">
          <label>服务地址<input v-model="form.url" class="pa-input" placeholder="https://example.com/mcp" :disabled="busy" :aria-invalid="!!fieldErrors.url" aria-describedby="mcp-url-help" /><span id="mcp-url-help">{{ fieldErrors.url || '使用公开 HTTPS 地址，端口为 443。' }}</span></label>
          <label>认证方式<select v-model="form.authMode" class="pa-input" :disabled="busy"><option value="none">无需认证</option><option value="oauth">OAuth 登录</option><option value="bearer">Bearer Token</option><option value="custom_headers">自定义请求头</option></select></label>
          <label v-if="form.authMode === 'oauth'">登录保存范围<select v-model="form.oauthPersistence" class="pa-input" :disabled="busy"><option value="persistent">系统凭据库（下次可复用）</option><option value="session">仅当前应用进程</option></select></label>
          <label v-if="form.authMode === 'custom_headers'">请求头名称<textarea v-model="form.headers" class="pa-input" rows="2" placeholder="X-API-Key" :disabled="busy" /><span>每行一个名称。Authorization 和协议管理字段不能自定义。</span></label>
        </template>
        <template v-else>
          <label>可执行文件绝对路径<input v-model="form.command" class="pa-input" placeholder="C:/tools/node.exe" :disabled="busy" :aria-invalid="!!fieldErrors.command" /><span v-if="fieldErrors.command" class="mcp-field-error">{{ fieldErrors.command }}</span></label>
          <fieldset class="mcp-arguments"><legend>启动参数</legend><p>每行传递一个参数，路径无需额外加引号；空参数会保留。</p><div v-for="(argument, index) in argumentRows" :key="argument.id" class="mcp-row"><input v-model="argument.value" class="pa-input" :aria-label="'参数 ' + (index + 1)" :disabled="busy" @input="syncArguments" /><button type="button" class="pa-btn pa-btn--ghost" :disabled="busy" :aria-label="'移除参数 ' + (index + 1)" @click="removeArgument(argument.id)">移除</button></div><button type="button" class="pa-btn pa-btn--subtle" :disabled="busy || argumentRows.length >= 32" @click="addArgument">添加参数</button></fieldset>
          <details :open="advancedArguments" @toggle="advancedArguments = ($event.target as HTMLDetailsElement).open"><summary>高级：JSON 参数</summary><label>参数（JSON 数组）<textarea v-model="form.arguments" class="pa-input" rows="3" :disabled="busy" :aria-invalid="!!fieldErrors.arguments" aria-describedby="mcp-args-help" /><span id="mcp-args-help">{{ fieldErrors.arguments || '没有参数时填写 []。高级 JSON 编辑会用于本次保存；可导入为参数行继续编辑。' }}</span><code>{{ argumentExample }}</code></label><button type="button" class="pa-btn pa-btn--subtle" :disabled="busy" @click="importArguments">导入为参数行</button></details>
          <label class="mcp-process-trust"><input v-model="form.trust_process" type="checkbox" :disabled="busy" />我信任此程序：它以当前用户权限运行，可访问本机和网络。不要在参数中填写密钥。</label><span v-if="fieldErrors.trust" class="mcp-field-error">{{ fieldErrors.trust }}</span>
          <label>环境变量名称<textarea v-model="form.environment" class="pa-input" rows="2" placeholder="MY_API_KEY" :disabled="busy" /><span>每行一个名称；值保存到系统凭据库。启动目录使用当前项目根目录。</span></label>
        </template>
        <template v-if="credentialFields.length">
          <label v-if="editing"><input v-model="replaceCredentials" type="checkbox" :disabled="busy" />替换全部认证值（未勾选时保留同目标已保存凭据）</label>
          <template v-if="inputCredentials"><label v-for="key in credentialFields" :key="key">{{ key === 'bearer' ? 'Bearer Token' : key.replace(/^(header|env):/, '') }}<input v-model="values[key]" type="password" class="pa-input" autocomplete="new-password" :disabled="busy" /></label></template>
          <p>认证值只进入系统凭据库，不写入项目配置、历史或导出包。</p>
        </template>
        <div class="mcp-row"><button type="button" class="pa-btn pa-btn--subtle" :disabled="busy" @click="preflight">本地检查配置</button><button class="pa-btn pa-btn--primary" :disabled="busy">{{ busy ? '保存中…' : '保存配置' }}</button><button v-if="editing" type="button" class="pa-btn pa-btn--ghost" :disabled="busy" @click="resetForm">取消编辑</button></div>
      </form>
    </details>
    <details v-if="pending.length" open><summary>待完成的保存（{{ pending.length }}）</summary><div v-for="change in pending" :key="change.id" class="mcp-row mcp-library-row"><div>{{ change.configuration.name }}<p>原活动配置仍然有效。凭据已经保存时可继续提交；否则请放弃后重新配置。</p></div><button class="pa-btn pa-btn--subtle" :disabled="busy" @click="resume(change)">继续保存</button><button class="pa-btn pa-btn--ghost" :disabled="busy" @click="action(() => discardMcpChange(change.id))">放弃</button></div></details>
    <details><summary>个人服务库（{{ services.length }}）</summary><p v-if="!services.length">添加服务后可在其他项目复用连接与登录。</p><div v-for="service in services" :key="service.id" class="mcp-row mcp-library-row"><div><strong>{{ service.name }}</strong><p>{{ service.transport }} · {{ service.projects.map(item => item.project_name).join('、') || '尚无项目绑定' }}</p></div><button v-if="!items.some(item => item.service_id === service.id)" class="pa-btn pa-btn--subtle" :disabled="busy" @click="action(() => bindMcpService(projectId, service.id))">绑定当前项目</button><button class="pa-btn pa-btn--ghost" :disabled="busy" @click="edit(service)">编辑</button><button v-if="service.oauth" class="pa-btn pa-btn--ghost" :disabled="busy" @click="logout(service)">退出登录</button><button class="pa-btn pa-btn--ghost" :disabled="busy || service.projects.length > 0" @click="deleteService(service)">删除</button></div></details>
    <h3>当前项目的工具</h3><p v-if="!items.length">尚未绑定服务。添加新服务，或从个人服务库绑定后再选择工具。</p>
    <article v-for="source in items" :key="source.id"><div class="mcp-row"><div><strong>{{ source.name }}</strong><p>{{ source.transport }} · {{ source.enabled ? '工具已启用' : '工具未启用' }} · {{ connectionLabel(source) }}</p></div><button class="pa-btn pa-btn--subtle" :disabled="busy || ['connecting', 'authorization_required'].includes(source.connection.status ?? '')" @click="action(() => connectIntegration(projectId, source.id))">连接并发现</button><button class="pa-btn pa-btn--ghost" :disabled="busy" @click="remove(source)">解除绑定</button></div>
      <p>最近验证：{{ verifiedTime(source.discovered_at) }}</p>
      <p v-if="source.connection.error" role="alert">{{ source.connection.error }}<span v-if="source.connection.error_code">（{{ source.connection.error_code }}）</span></p><p v-if="source.connection.warning" role="status">{{ source.connection.warning }}</p>
      <a v-if="source.connection.authorization_url" :href="source.connection.authorization_url" @click.prevent="action(() => openAuthorizationLink(source.connection.authorization_url!))" class="pa-btn pa-btn--primary">在浏览器完成 OAuth 登录</a>
      <details v-if="source.catalog"><summary>检查并选择工具（{{ source.catalog.tools.length }}）</summary><p v-if="source.needs_validation">服务配置已经变化，旧工具选择保留供核对；重新发现后才能启用。</p>
        <div v-for="tool in source.catalog.tools" :key="tool.name" class="mcp-tool"><label><input type="checkbox" :checked="!!permission(source, tool.name)" :disabled="busy || source.needs_validation" @change="toggle(source, tool.name, ($event.target as HTMLInputElement).checked)" />{{ tool.name }}</label><p>{{ tool.description }}</p><details><summary>参数结构</summary><pre>{{ JSON.stringify(tool.input_schema, null, 2) }}</pre></details><template v-if="permission(source, tool.name)"><label><input v-model="permission(source, tool.name)!.readonly" type="checkbox" :disabled="busy || source.needs_validation" @change="permission(source, tool.name)!.approval = 'always'" />我已核对这是只读工具</label><select v-model="permission(source, tool.name)!.approval" class="pa-input" :disabled="busy || source.needs_validation" :aria-label="tool.name + ' 授权范围'"><option value="always">每次询问</option><option v-if="permission(source, tool.name)!.readonly" value="session">首次同意后允许当前项目会话</option></select></template></div>
        <p v-for="tool in source.catalog.unavailable_tools ?? []" :key="'unsupported-' + tool.name">{{ tool.name }}：暂不可用，{{ tool.reason }}</p>
        <div class="mcp-row"><button class="pa-btn pa-btn--primary" :disabled="busy || source.needs_validation" @click="action(() => selectIntegrationTools(projectId, source, true, selections[source.id] ?? []))">保存并启用所选工具</button><button v-if="source.enabled" class="pa-btn pa-btn--ghost" :disabled="busy" @click="action(() => selectIntegrationTools(projectId, source, false, []))">停用全部</button></div>
      </details>
    </article>
  </section>
</template>
<style scoped>
.mcp-integrations { display: grid; gap: var(--space-5); font-size: var(--pa-text-body); overflow-wrap: anywhere; }
.mcp-integrations h2, .mcp-integrations h3 { margin: 0; font-size: 18px; }
.mcp-integrations p { color: var(--color-fg-muted); line-height: 1.6; margin: var(--space-2) 0; }
.mcp-integrations summary { cursor: pointer; padding: var(--space-3) 0; font-weight: var(--font-medium); }
.mcp-integrations > details { border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: 0 var(--space-4); background: var(--color-surface-muted); }
.mcp-form { display: grid; gap: var(--space-4); max-width: 680px; padding-block: var(--space-3) var(--space-5); }
.mcp-integrations label { display: flex; gap: var(--space-2); align-items: center; flex-wrap: wrap; }
.mcp-form label > .pa-input { width: 100%; }
.mcp-process-trust { line-height: 1.5; }
.mcp-arguments { display: grid; gap: var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-md); min-width: 0; }
.mcp-arguments .pa-input { flex: 1; min-width: 120px; }
.mcp-arguments > button { justify-self: start; }
.mcp-row { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
.mcp-row > div { flex: 1; min-width: 160px; }
.mcp-library-row { padding-block: var(--space-3); border-top: 1px solid var(--color-border); }
.mcp-integrations article { border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: var(--space-4); }
.mcp-integrations article strong { font-size: 16px; }
.mcp-tool { padding: var(--space-3); border-top: 1px solid var(--color-border); }
.mcp-tool > select { width: auto; max-width: 100%; margin: var(--space-2) 0; }
.mcp-integrations pre { max-height: 220px; overflow: auto; padding: var(--space-3); border-radius: var(--radius-md); background: var(--color-surface-sunken); font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
.mcp-field-error { color: var(--color-danger-fg); }
.mcp-form span, .mcp-form code { font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.mcp-integrations [aria-invalid="true"] { border-color: var(--color-danger-fg); }
.mcp-integrations [role="alert"] { color: var(--color-danger-fg); }
</style>
