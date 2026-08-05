<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  cmdClearMcpSecret,
  cmdMcpSecretStatus,
  cmdPromptMcpSecret,
  createMcpServer,
  deleteMcpServer,
  discoverMcpServer,
  listMcpCalls,
  listMcpServers,
  updateMcpServerState,
  type McpCallLog,
  type McpServer,
  type McpTransport,
} from "../api";
import { useNotifications } from "../stores/notifications";

const notify = useNotifications();
const servers = ref<McpServer[]>([]);
const calls = ref<Record<string, McpCallLog[]>>({});
const loading = ref(false);
const busyId = ref<string | null>(null);
const apiAvailable = ref(true);
const showCreate = ref(false);
const name = ref("");
const transport = ref<McpTransport>("stdio");
const command = ref("");
const argsText = ref("");
const workingDirectory = ref("");
const url = ref("");
const allowInsecureLocal = ref(false);
const allowPrivateNetwork = ref(false);
type McpCredentialMode = "none" | "stdio_env" | "http_bearer" | "http_header";
const credentialMode = ref<McpCredentialMode>("none");
const credentialAlias = ref("");
const credentialTargetName = ref("");
const credentialConfigured = ref(false);

const credentialTarget = computed(() => {
  if (credentialMode.value === "stdio_env") {
    return /^[A-Za-z_][A-Za-z0-9_]{0,127}$/.test(credentialTargetName.value.trim())
      ? `env:${credentialTargetName.value.trim()}`
      : "";
  }
  if (credentialMode.value === "http_bearer") return "http-bearer";
  if (credentialMode.value === "http_header") {
    const name = credentialTargetName.value.trim();
    const normalized = name.toLowerCase();
    const looksSensitive = /api.?key|auth|bearer|pass|secret|token/i.test(name);
    const safeNamespace = normalized === "api-key" || normalized.startsWith("x-");
    const reserved =
      normalized.startsWith("x-forwarded-") ||
      normalized === "x-real-ip" ||
      normalized.startsWith("mcp-") ||
      normalized.startsWith("sec-");
    return /^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,64}$/.test(name) &&
      safeNamespace &&
      looksSensitive &&
      !reserved
      ? `http-header:${name}`
      : "";
  }
  return "";
});

const credentialAliasValid = computed(() =>
  /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(credentialAlias.value.trim())
);

const canCreate = computed(() => {
  if (!name.value.trim()) return false;
  const connectionReady =
    transport.value === "stdio" ? Boolean(command.value.trim()) : Boolean(url.value.trim());
  const credentialReady =
    credentialMode.value === "none" ||
    (credentialAliasValid.value && Boolean(credentialTarget.value) && credentialConfigured.value);
  return connectionReady && credentialReady;
});

watch(transport, () => {
  credentialMode.value = "none";
  credentialTargetName.value = "";
  credentialConfigured.value = false;
});

watch(credentialAlias, () => {
  credentialConfigured.value = false;
});

async function configureCredential() {
  if (!credentialAliasValid.value) return;
  try {
    const result = await cmdPromptMcpSecret(credentialAlias.value.trim());
    credentialConfigured.value = result.configured;
    if (!result.cancelled && result.configured) {
      notify.success("MCP 凭据已写入系统凭据库；重启桌面 sidecar 后生效");
    }
  } catch (error) {
    credentialConfigured.value = false;
    notify.error("MCP 凭据配置失败", String(error));
  }
}

async function checkCredential() {
  if (!credentialAliasValid.value) return;
  try {
    const result = await cmdMcpSecretStatus(credentialAlias.value.trim());
    credentialConfigured.value = result.configured;
  } catch (error) {
    credentialConfigured.value = false;
    notify.error("MCP 凭据状态检查失败", String(error));
  }
}

async function clearCredential() {
  if (!credentialAliasValid.value) return;
  try {
    await cmdClearMcpSecret(credentialAlias.value.trim());
    credentialConfigured.value = false;
    notify.success("MCP 凭据已从系统凭据库删除；已登记的引用会继续失败关闭");
  } catch (error) {
    notify.error("MCP 凭据删除失败", String(error));
  }
}

function replaceServer(updated: McpServer) {
  const index = servers.value.findIndex((item) => item.id === updated.id);
  if (index >= 0) servers.value[index] = updated;
}

async function load() {
  loading.value = true;
  try {
    servers.value = await listMcpServers();
    apiAvailable.value = true;
  } catch (error) {
    servers.value = [];
    apiAvailable.value = false;
    if (!String(error).toLowerCase().includes("not found")) {
      notify.error("MCP 配置加载失败", String(error));
    }
  } finally {
    loading.value = false;
  }
}

async function createServer() {
  if (!canCreate.value) return;
  loading.value = true;
  try {
    const created = await createMcpServer({
      name: name.value.trim(),
      transport: transport.value,
      command: transport.value === "stdio" ? command.value.trim() : null,
      args:
        transport.value === "stdio"
          ? argsText.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
          : [],
      working_directory:
        transport.value === "stdio" ? workingDirectory.value.trim() || null : null,
      url: transport.value === "streamable_http" ? url.value.trim() : null,
      allow_insecure_local: allowInsecureLocal.value,
      allow_private_network: allowPrivateNetwork.value,
      secret_refs:
        credentialMode.value === "none"
          ? {}
          : {
              [credentialTarget.value]: `secret://os-keyring/mcp/${credentialAlias.value.trim()}`,
            },
      trusted: false,
      enabled: false,
    });
    servers.value.push(created);
    showCreate.value = false;
    name.value = "";
    command.value = "";
    argsText.value = "";
    workingDirectory.value = "";
    url.value = "";
    credentialMode.value = "none";
    credentialAlias.value = "";
    credentialTargetName.value = "";
    credentialConfigured.value = false;
    notify.success("MCP Server 已登记，默认未信任且未启用");
  } catch (error) {
    notify.error("MCP Server 登记失败", String(error));
  } finally {
    loading.value = false;
  }
}

async function saveState(server: McpServer) {
  busyId.value = server.id;
  if (!server.trusted) server.enabled = false;
  try {
    replaceServer(await updateMcpServerState(server));
    notify.success(`${server.name} 的信任、启用与工具白名单已保存`);
  } catch (error) {
    notify.error("MCP 状态保存失败", String(error));
    await load();
  } finally {
    busyId.value = null;
  }
}

async function discover(server: McpServer) {
  if (!server.trusted || !server.enabled) {
    notify.error("无法连接", "请先明确设为信任、启用并保存状态。");
    return;
  }
  busyId.value = server.id;
  try {
    replaceServer(await discoverMcpServer(server.id));
    notify.success(`${server.name} 已完成工具、Resources 与 Prompts 发现`);
  } catch (error) {
    notify.error("MCP 发现失败", String(error));
    await load();
  } finally {
    busyId.value = null;
  }
}

async function loadCalls(server: McpServer) {
  busyId.value = server.id;
  try {
    calls.value[server.id] = await listMcpCalls(server.id);
  } catch (error) {
    notify.error("MCP 调用日志加载失败", String(error));
  } finally {
    busyId.value = null;
  }
}

async function remove(server: McpServer) {
  const confirmed = await notify.confirm({
    title: `删除 MCP Server「${server.name}」？`,
    danger: true,
    impact: "该 Server 的注册信息和元数据调用日志会被删除，Agent 将无法再调用它。",
  });
  if (!confirmed) return;
  busyId.value = server.id;
  try {
    await deleteMcpServer(server.id);
    servers.value = servers.value.filter((item) => item.id !== server.id);
    notify.success(`${server.name} 已删除`);
  } catch (error) {
    notify.error("MCP Server 删除失败", String(error));
  } finally {
    busyId.value = null;
  }
}

function toggleAllowedTool(server: McpServer, toolName: string, checked: boolean) {
  const selected = new Set(server.allowed_tools);
  if (checked) selected.add(toolName);
  else selected.delete(toolName);
  server.allowed_tools = [...selected].sort();
}

function changeAllowedTool(server: McpServer, toolName: string, event: Event) {
  const target = event.target;
  if (target instanceof HTMLInputElement) {
    toggleAllowedTool(server, toolName, target.checked);
  }
}

onMounted(load);
</script>

<template>
  <section class="mcp-panel">
    <div class="panel-head">
      <div>
        <h3>MCP Server</h3>
        <p>外部能力默认不信任、不启用；每个工具还必须进入显式白名单并逐次审批。</p>
      </div>
      <div class="head-actions">
        <button class="mcp-button secondary" :disabled="loading" @click="load">刷新</button>
        <button v-if="apiAvailable" class="mcp-button" @click="showCreate = !showCreate">
          {{ showCreate ? "收起" : "登记 Server" }}
        </button>
      </div>
    </div>

    <div v-if="!apiAvailable" class="feature-off">
      MCP API 当前关闭。确认完成数据库迁移后，通过 <code>PA_MCP_ENABLED=true</code> 显式启用。
    </div>

    <form v-else-if="showCreate" class="create-form" @submit.prevent="createServer">
      <label>
        显示名称
        <input v-model="name" maxlength="128" placeholder="例如：本地文件索引服务" />
      </label>
      <label>
        连接方式
        <select v-model="transport">
          <option value="stdio">stdio 子进程</option>
          <option value="streamable_http">Streamable HTTP</option>
        </select>
      </label>
      <template v-if="transport === 'stdio'">
        <label>
          可执行文件
          <input v-model="command" placeholder="已存在的可执行文件绝对路径" />
        </label>
        <label>
          参数（每行一个，不经过 Shell）
          <textarea v-model="argsText" rows="3" />
        </label>
        <label>
          工作目录（可选，必须是已存在的绝对路径）
          <input v-model="workingDirectory" />
        </label>
      </template>
      <template v-else>
        <label>
          Server URL
          <input v-model="url" placeholder="https://example.com/mcp" />
        </label>
        <label class="check-row">
          <input v-model="allowInsecureLocal" type="checkbox" />
          明确允许 loopback HTTP
        </label>
        <label class="check-row">
          <input v-model="allowPrivateNetwork" type="checkbox" />
          明确允许私有网络目标
        </label>
      </template>
      <label>
        凭据注入（可选）
        <select v-model="credentialMode">
          <option value="none">无凭据</option>
          <option v-if="transport === 'stdio'" value="stdio_env">stdio 环境变量</option>
          <option v-if="transport === 'streamable_http'" value="http_bearer">HTTP Bearer</option>
          <option v-if="transport === 'streamable_http'" value="http_header">HTTP API-key 请求头</option>
        </select>
      </label>
      <template v-if="credentialMode !== 'none'">
        <label>
          凭据别名
          <input v-model="credentialAlias" maxlength="64" placeholder="例如：github-prod" autocomplete="off" />
        </label>
        <label v-if="credentialMode === 'stdio_env'">
          目标环境变量名
          <input v-model="credentialTargetName" maxlength="128" placeholder="例如：GITHUB_TOKEN" />
        </label>
        <label v-if="credentialMode === 'http_header'">
          目标请求头名
          <input v-model="credentialTargetName" maxlength="64" placeholder="例如：X-API-Key" />
        </label>
        <div class="credential-actions">
          <button
            class="mcp-button secondary"
            type="button"
            :disabled="!credentialAliasValid"
            @click="configureCredential"
          >
            在系统凭据库中设置
          </button>
          <button
            class="mcp-button secondary"
            type="button"
            :disabled="!credentialAliasValid"
            @click="checkCredential"
          >
            检查状态
          </button>
          <button
            v-if="credentialConfigured"
            class="text-button danger"
            type="button"
            @click="clearCredential"
          >
            删除凭据
          </button>
          <span>{{ credentialConfigured ? "已配置" : "尚未配置" }}</span>
        </div>
      </template>
      <p class="security-note">
        凭据值只在原生系统对话框中输入；数据库和此页面仅保存引用。新凭据需重启桌面 sidecar 后用于连接。
      </p>
      <button class="mcp-button" type="submit" :disabled="loading || !canCreate">登记为禁用状态</button>
    </form>

    <div v-if="apiAvailable && !loading && servers.length === 0" class="empty-state">
      尚未登记 MCP Server。
    </div>

    <article v-for="server in servers" :key="server.id" class="server-card">
      <div class="server-title">
        <div>
          <strong>{{ server.name }}</strong>
          <span class="transport">{{ server.transport }}</span>
        </div>
        <span class="health" :class="server.status">{{ server.status }}</span>
      </div>
      <code class="endpoint">{{ server.command || server.url }}</code>
      <p v-if="server.last_error_code" class="error-code">错误代码：{{ server.last_error_code }}</p>

      <div class="state-controls">
        <label class="check-row">
          <input v-model="server.trusted" type="checkbox" @change="!server.trusted && (server.enabled = false)" />
          我信任此 Server 配置
        </label>
        <label class="check-row">
          <input v-model="server.enabled" type="checkbox" :disabled="!server.trusted" />
          启用连接
        </label>
        <button class="mcp-button secondary" :disabled="busyId === server.id" @click="saveState(server)">
          保存状态
        </button>
        <button class="mcp-button secondary" :disabled="busyId === server.id" @click="discover(server)">
          发现 / 健康检查
        </button>
      </div>

      <div class="discovery-summary">
        <span>Tools {{ server.tools.length }}</span>
        <span>Resources {{ server.resources.length }}</span>
        <span>Prompts {{ server.prompts.length }}</span>
        <span v-if="server.last_checked_at">检查于 {{ new Date(server.last_checked_at).toLocaleString() }}</span>
      </div>

      <fieldset v-if="server.tools.length" class="allowlist">
        <legend>Agent 工具白名单</legend>
        <label v-for="tool in server.tools" :key="tool.name" class="tool-row">
          <input
            type="checkbox"
            :checked="server.allowed_tools.includes(tool.name)"
            @change="changeAllowedTool(server, tool.name, $event)"
          />
          <span>
            <strong>{{ tool.title || tool.name }}</strong>
            <small>{{ tool.description || "无描述" }}</small>
          </span>
        </label>
        <button class="mcp-button secondary" :disabled="busyId === server.id" @click="saveState(server)">
          保存白名单
        </button>
      </fieldset>

      <div class="audit-actions">
        <button class="text-button" :disabled="busyId === server.id" @click="loadCalls(server)">查看元数据日志</button>
        <button class="text-button danger" :disabled="busyId === server.id" @click="remove(server)">删除</button>
      </div>
      <div v-if="calls[server.id]" class="call-list">
        <div v-if="calls[server.id].length === 0">暂无调用记录</div>
        <div v-for="call in calls[server.id]" :key="call.id" class="call-row">
          <code>{{ call.tool_name }}</code>
          <span>{{ call.status }} · {{ call.duration_ms }} ms · {{ call.output_bytes }} B</span>
          <span>{{ new Date(call.created_at).toLocaleString() }}</span>
        </div>
      </div>
    </article>
  </section>
</template>

<style scoped>
.mcp-panel { display: grid; gap: 14px; }
.panel-head, .server-title, .state-controls, .audit-actions, .discovery-summary {
  display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;
}
.panel-head h3 { margin: 0 0 4px; font-size: 17px; }
.panel-head p { margin: 0; color: var(--color-fg-muted); font-size: 12px; }
.head-actions { display: flex; gap: 8px; }
.feature-off, .empty-state, .security-note {
  margin: 0; padding: 12px; border-radius: 10px; color: var(--color-fg-muted);
  background: var(--color-bg); border: 1px solid var(--color-border); font-size: 12px;
}
.create-form { display: grid; gap: 10px; padding: 14px; border-radius: 12px; background: var(--color-bg); }
.create-form label { display: grid; gap: 5px; color: var(--color-fg-muted); font-size: 12px; }
.create-form input, .create-form select, .create-form textarea {
  width: 100%; box-sizing: border-box; border: 1px solid var(--color-border); border-radius: 8px;
  background: var(--color-surface); color: var(--color-fg); padding: 8px 10px; font: inherit;
}
.create-form textarea { resize: vertical; }
.credential-actions { display: flex; align-items: center; gap: 10px; color: var(--color-fg-muted); font-size: 12px; }
.check-row { display: inline-flex !important; grid-template-columns: none !important; align-items: center; gap: 7px !important; }
.check-row input { width: auto; }
.mcp-button { border: 0; border-radius: 8px; padding: 7px 11px; cursor: pointer; color: white; background: var(--color-accent); }
.mcp-button.secondary { color: var(--color-fg); background: var(--color-surface); border: 1px solid var(--color-border); }
.mcp-button:disabled { opacity: .5; cursor: default; }
.server-card { display: grid; gap: 11px; padding: 14px; border: 1px solid var(--color-border); border-radius: 13px; background: var(--color-bg); }
.server-title > div { display: flex; align-items: center; gap: 8px; }
.transport, .health { font-size: 10px; padding: 3px 7px; border-radius: 999px; background: var(--color-surface); color: var(--color-fg-muted); }
.health.healthy { color: #1d7a54; background: color-mix(in srgb, #2bb673 14%, transparent); }
.health.error, .error-code { color: var(--color-danger, #b42318); }
.endpoint { overflow-wrap: anywhere; color: var(--color-fg-muted); font-size: 11px; }
.state-controls { justify-content: flex-start; }
.state-controls .check-row { color: var(--color-fg-muted); font-size: 12px; }
.discovery-summary { justify-content: flex-start; color: var(--color-fg-faint); font-size: 11px; }
.allowlist { display: grid; gap: 8px; margin: 0; padding: 11px; border: 1px solid var(--color-border); border-radius: 10px; }
.allowlist legend { padding: 0 5px; color: var(--color-fg-muted); font-size: 12px; }
.tool-row { display: flex; align-items: flex-start; gap: 8px; }
.tool-row span { display: grid; gap: 2px; }
.tool-row strong { font-size: 12px; }
.tool-row small { color: var(--color-fg-muted); font-size: 11px; }
.audit-actions { justify-content: flex-end; }
.text-button { border: 0; background: transparent; color: var(--color-accent); cursor: pointer; font-size: 11px; }
.text-button.danger { color: var(--color-danger, #b42318); }
.call-list { display: grid; gap: 5px; padding-top: 8px; border-top: 1px solid var(--color-border); color: var(--color-fg-muted); font-size: 10px; }
.call-row { display: grid; grid-template-columns: minmax(100px, 1fr) auto auto; gap: 8px; }
@media (max-width: 720px) { .call-row { grid-template-columns: 1fr; } }
</style>
