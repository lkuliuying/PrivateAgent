<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import {
  cmdClearProviderSecret,
  cmdPromptProviderSecret,
  cmdProviderSecretStatus,
  cmdRelaunchApp,
  exportBackup,
  getSettings,
  isDesktopRuntime,
  listBackups,
  listProviders,
  previewRestoreBackup,
  testProvider,
  updateProviders,
  updateProviderSecretReference,
  updateSettings,
  type AppSettings,
  type ProviderSecretStatus,
} from "../api";
import type { BackupExportResult, BackupRestorePreview, ProviderStatus } from "../types";
import UpdateChecker from "./UpdateChecker.vue";
import McpServersPanel from "./McpServersPanel.vue";
import HttpProfilesPanel from "./HttpProfilesPanel.vue";
import { useHealth } from "../stores/health";
import { useNotifications } from "../stores/notifications";

const emit = defineEmits<{ (e: "reconfigure"): void }>();
const notify = useNotifications();
const desktopRuntime = isDesktopRuntime();

const settings = ref<AppSettings | null>(null);
const {
  health,
  refreshing: healthLoading,
  error: healthError,
  refresh: refreshHealth,
} = useHealth();
const providers = ref<ProviderStatus | null>(null);
const backups = ref<BackupExportResult[]>([]);
const backupPreview = ref<BackupRestorePreview | null>(null);
const backupPath = ref("");
const saving = ref(false);
const msg = ref("");
const providerMsg = ref("");
const providerSecrets = ref<ProviderSecretStatus | null>(null);
const providerPrompting = ref<"openai" | "claude" | null>(null);
const providerRestartRequired = ref(false);
const backupMsg = ref("");
let timer: ReturnType<typeof setInterval> | undefined;
let msgTimer: ReturnType<typeof setTimeout> | undefined;

async function load() {
  try {
    settings.value = await getSettings();
  } catch {
    settings.value = null;
  }
  await refreshHealth();
  try {
    providers.value = await listProviders();
  } catch {
    providers.value = null;
  }
  if (desktopRuntime) {
    try {
      providerSecrets.value = await cmdProviderSecretStatus();
    } catch {
      providerSecrets.value = null;
    }
  }
  try {
    backups.value = (await listBackups()).items;
    if (!backupPath.value && backups.value.length) backupPath.value = backups.value[0].path;
  } catch {
    backups.value = [];
  }
}
onMounted(() => {
  load();
  // 只轮询健康状态；重复加载整张设置表单会覆盖用户尚未保存的输入。
  timer = setInterval(() => void refreshHealth(), 5000);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
  if (msgTimer) clearTimeout(msgTimer);
});

async function save() {
  if (!settings.value) return;
  saving.value = true;
  msg.value = "";
  try {
    await updateSettings({
      llm_temperature: settings.value.llm_temperature,
      llm_context_length: settings.value.llm_context_length,
      kb_enabled_by_default: settings.value.kb_enabled_by_default,
    });
    msg.value = "✓ 已保存";
  } catch (e) {
    msg.value = "保存失败：" + String(e);
  } finally {
    saving.value = false;
    if (msgTimer) clearTimeout(msgTimer);
    msgTimer = setTimeout(() => (msg.value = ""), 3000);
  }
}

async function saveProvider() {
  if (!settings.value) return;
  saving.value = true;
  providerMsg.value = "";
  try {
    await updateProviders({
      provider_type: settings.value.provider_type,
      remote_provider_enabled: settings.value.remote_provider_enabled,
      openai_base_url: settings.value.openai_base_url,
      openai_model: settings.value.openai_model,
      claude_model: settings.value.claude_model,
    });

    let associatedSecret = false;
    if (providerSecrets.value?.openai_configured && providers.value?.config.openai.storage !== "os_keyring") {
      const result = await updateProviderSecretReference("openai", true);
      providerRestartRequired.value ||= result.restart_required;
      associatedSecret = true;
    }
    if (providerSecrets.value?.claude_configured && providers.value?.config.claude.storage !== "os_keyring") {
      const result = await updateProviderSecretReference("claude", true);
      providerRestartRequired.value ||= result.restart_required;
      associatedSecret = true;
    }
    providers.value = await listProviders();
    settings.value = await getSettings();
    providerMsg.value = associatedSecret
      ? "Provider 已保存并关联系统凭据；重启后注入本地后端"
      : "Provider 已保存";
  } catch (e) {
    providerMsg.value = "Provider 保存失败：" + String(e);
  } finally {
    saving.value = false;
  }
}

async function configureProviderSecret(provider: "openai" | "claude") {
  providerPrompting.value = provider;
  providerMsg.value = "";
  try {
    const result = await cmdPromptProviderSecret(provider);
    providerSecrets.value = {
      openai_configured: result.openai_configured,
      claude_configured: result.claude_configured,
    };
    if (result.cancelled) return;

    const reference = await updateProviderSecretReference(provider, true);
    providerRestartRequired.value ||= reference.restart_required;
    providers.value = await listProviders();
    settings.value = await getSettings();
    providerMsg.value = `${provider === "openai" ? "OpenAI" : "Claude"} 凭据已保存到 Windows 凭据管理器并完成关联`;
  } catch (e) {
    providerMsg.value = "Provider 凭据保存失败：" + String(e);
  } finally {
    providerPrompting.value = null;
  }
}

async function clearProviderSecret(provider: "openai" | "claude") {
  const confirmed = await notify.confirm({
    title: `清除 ${provider === "openai" ? "OpenAI" : "Claude"} 凭据？`,
    danger: true,
    impact: "将从系统凭据库删除密钥，并停用对应的凭据引用。",
  });
  if (!confirmed) return;

  saving.value = true;
  providerMsg.value = "";
  try {
    providerSecrets.value = await cmdClearProviderSecret(provider);
    await updateProviderSecretReference(provider, false);
    providers.value = await listProviders();
    settings.value = await getSettings();
    providerRestartRequired.value = true;
    providerMsg.value = "凭据已清除；请重启应用以清理 sidecar 进程环境";
  } catch (e) {
    providerMsg.value = "凭据清除失败：" + String(e);
  } finally {
    saving.value = false;
  }
}

async function restartForProviderSecrets() {
  const confirmed = await notify.confirm({
    title: "立即重启以应用 Provider 凭据？",
    impact: "当前本地后端会停止并由桌面应用重新启动。",
  });
  if (confirmed) await cmdRelaunchApp();
}

async function runProviderTest() {
  providerMsg.value = "";
  try {
    const res = await testProvider();
    providerMsg.value = JSON.stringify(res, null, 2);
  } catch (e) {
    providerMsg.value = "Provider 测试失败：" + String(e);
  }
}

async function doBackup() {
  backupMsg.value = "";
  try {
    const res = await exportBackup();
    backupMsg.value = `已创建备份：${res.path}`;
    backupPath.value = res.path;
    await load();
  } catch (e) {
    backupMsg.value = "备份失败：" + String(e);
  }
}

async function previewBackup() {
  if (!backupPath.value.trim()) return;
  backupMsg.value = "";
  try {
    backupPreview.value = await previewRestoreBackup(backupPath.value.trim());
  } catch (e) {
    backupMsg.value = "恢复预览失败：" + String(e);
  }
}

const statusItems = computed(() => {
  const h = health.value;
  if (!h) return [];
  return [
    { label: "本地后端 API", ok: h.api.ok },
    { label: "Ollama", ok: h.ollama.ok },
    { label: "MySQL", ok: h.mysql.ok },
    { label: "ChromaDB", ok: h.chroma.ok },
  ];
});
</script>

<template>
  <section class="content">
    <header class="settings-hero">
      <div>
        <span class="eyebrow">LOCAL CONTROL CENTER</span>
        <h1>设置与状态</h1>
        <p class="subtitle">管理本地模型、隐私边界与数据安全。</p>
      </div>
      <span class="privacy-badge">数据默认留在本机</span>
    </header>

    <div class="settings-grid">

    <!-- 状态 -->
    <section class="setting-card wide status-card">
      <div class="card-heading"><span>01</span><div><h2>运行状态</h2><p>关键依赖与本地服务连通性</p></div></div>
      <div class="status-row">
        <div v-for="s in statusItems" :key="s.label" class="status-pill" :class="s.ok ? 'ok' : 'bad'">
          <span class="dot" />{{ s.label }}{{ s.ok ? " 正常" : " 不可用" }}
        </div>
      </div>
      <div v-if="healthError" class="warn-text">⚠ 本地后端暂时未连接，当前显示上次状态。</div>
      <div v-else-if="healthLoading && !health" class="loading-text">正在检查系统状态…</div>
    </section>

    <!-- 模型信息（只读） -->
    <section class="setting-card wide">
      <div class="card-heading"><span>02</span><div><h2>当前模型</h2><p>正在使用的推理与向量模型</p></div></div>
      <div class="info-grid">
        <div><span class="k">LLM 模型</span><span class="v">{{ settings?.llm_model || "—" }}</span></div>
        <div><span class="k">嵌入模型</span><span class="v">{{ settings?.embed_model || "—" }}</span></div>
        <div><span class="k">Ollama 地址</span><span class="v">{{ health?.ollama?.base_url || "—" }}</span></div>
      </div>
    </section>

    <!-- 可调参数 -->
    <section class="setting-card">
      <div class="card-heading"><span>03</span><div><h2>模型参数</h2><p>控制回答发散度与上下文窗口</p></div></div>
      <div class="form" v-if="settings">
      <div class="field">
        <label>温度（0~1）</label>
        <input type="number" step="0.1" min="0" max="1" v-model.number="settings.llm_temperature" :disabled="!settings" />
      </div>
      <div class="field">
        <label>上下文长度</label>
        <input type="number" step="512" min="512" v-model.number="settings.llm_context_length" :disabled="!settings" />
      </div>
      <div class="field field-check">
        <label>
          <input type="checkbox" v-model="settings.kb_enabled_by_default" :disabled="!settings" />
          默认启用知识库
        </label>
      </div>
      <div class="form-actions">
        <button class="save-btn" @click="save" :disabled="saving || !settings">
          {{ saving ? "保存中…" : "保存" }}
        </button>
        <span class="msg">{{ msg }}</span>
      </div>
      </div>
    </section>

    <!-- Provider -->
    <section class="setting-card">
      <div class="card-heading"><span>04</span><div><h2>Provider 与隐私</h2><p>远程模型仅在明确开启后接收上下文</p></div></div>
      <div class="form provider-form" v-if="settings">
      <div class="field">
        <label>当前 Provider</label>
        <select v-model="settings.provider_type">
          <option value="ollama">Ollama（本地默认）</option>
          <option value="openai">OpenAI-compatible</option>
          <option value="claude">Claude</option>
        </select>
      </div>
      <div class="field field-check">
        <label>
          <input type="checkbox" v-model="settings.remote_provider_enabled" />
          允许远程 Provider 发送上下文
        </label>
      </div>
      <div class="field">
        <label>OpenAI Base URL</label>
        <input v-model="settings.openai_base_url" placeholder="https://api.openai.com/v1" />
      </div>
      <div class="field">
        <label>OpenAI Model</label>
        <input v-model="settings.openai_model" placeholder="gpt-4o-mini" />
      </div>
      <div class="field">
        <label>OpenAI API Key</label>
        <button
          type="button"
          class="save-btn secondary secret-configure"
          :disabled="!desktopRuntime || providerPrompting !== null"
          @click="configureProviderSecret('openai')"
        >
          {{ providerPrompting === "openai" ? "等待系统凭据窗口…" : "输入或更新 OpenAI 密钥…" }}
        </button>
        <small class="secret-status">
          {{
            providers?.config.openai.storage === "legacy"
              ? "检测到旧明文配置：请重新输入并保存以迁移"
              : providers?.config.openai.storage === "os_keyring"
                ? "已使用系统凭据库"
                : providerSecrets?.openai_configured
                  ? "系统凭据已存在"
                  : desktopRuntime
                    ? "尚未配置"
                    : "仅桌面应用可写入系统凭据库"
          }}
        </small>
        <button
          v-if="providers?.config.openai.configured || providerSecrets?.openai_configured"
          type="button"
          class="secret-clear"
          :disabled="saving || !desktopRuntime"
          @click="clearProviderSecret('openai')"
        >
          清除凭据
        </button>
      </div>
      <div class="field">
        <label>Claude Model</label>
        <input v-model="settings.claude_model" placeholder="claude-3-5-sonnet-latest" />
      </div>
      <div class="field">
        <label>Claude API Key</label>
        <button
          type="button"
          class="save-btn secondary secret-configure"
          :disabled="!desktopRuntime || providerPrompting !== null"
          @click="configureProviderSecret('claude')"
        >
          {{ providerPrompting === "claude" ? "等待系统凭据窗口…" : "输入或更新 Claude 密钥…" }}
        </button>
        <small class="secret-status">
          {{
            providers?.config.claude.storage === "legacy"
              ? "检测到旧明文配置：请重新输入并保存以迁移"
              : providers?.config.claude.storage === "os_keyring"
                ? "已使用系统凭据库"
                : providerSecrets?.claude_configured
                  ? "系统凭据已存在"
                  : desktopRuntime
                    ? "尚未配置"
                    : "仅桌面应用可写入系统凭据库"
          }}
        </small>
        <button
          v-if="providers?.config.claude.configured || providerSecrets?.claude_configured"
          type="button"
          class="secret-clear"
          :disabled="saving || !desktopRuntime"
          @click="clearProviderSecret('claude')"
        >
          清除凭据
        </button>
      </div>
      <div class="provider-scope">
        <span class="k">远程发送范围</span>
        <span class="v">
          {{
            providers?.privacy?.sends?.length
              ? providers.privacy.sends.join(" / ")
              : "本地 Ollama 或远程关闭，不发送"
          }}
        </span>
      </div>
      <div class="form-actions">
        <button class="save-btn" @click="saveProvider" :disabled="saving">保存 Provider</button>
        <button class="save-btn secondary" @click="runProviderTest" :disabled="saving">
          测试 Provider
        </button>
      </div>
      <div v-if="providerRestartRequired" class="provider-restart">
        <span>Provider 凭据状态已变化，需要重启本地后端后完全生效。</span>
        <button class="save-btn secondary" @click="restartForProviderSecrets">立即重启</button>
      </div>
      <pre v-if="providerMsg" class="small-pre">{{ providerMsg }}</pre>
      </div>
    </section>

    <!-- MCP -->
    <section class="setting-card wide">
      <div class="card-heading"><span>05</span><div><h2>MCP 外部能力</h2><p>登记、发现并按白名单授权跨进程工具</p></div></div>
      <McpServersPanel />
    </section>

    <!-- v0.5.0 B3：HTTP 端点 -->
    <section class="setting-card wide">
      <div class="card-heading"><span>06</span><div><h2>HTTP 端点</h2><p>固定目标与方法的可信 API 调用配置</p></div></div>
      <HttpProfilesPanel />
    </section>

    <!-- 备份 -->
    <section class="setting-card">
      <div class="card-heading"><span>07</span><div><h2>备份与恢复</h2><p>先预览，再决定是否恢复本地数据</p></div></div>
      <div class="form">
      <div class="form-actions">
        <button class="save-btn" @click="doBackup">创建备份包</button>
      </div>
      <div class="field">
        <label>备份包路径</label>
        <input v-model="backupPath" placeholder="data/backups/..." />
      </div>
      <div class="form-actions">
        <button class="save-btn secondary" @click="previewBackup">恢复预览</button>
      </div>
      <p v-if="backupMsg" class="hint">{{ backupMsg }}</p>
      <div v-if="backups.length" class="backup-list">
        <button
          v-for="b in backups.slice(0, 5)"
          :key="b.path"
          class="backup-row"
          @click="backupPath = b.path"
        >
          <span>{{ b.path }}</span>
          <small>{{ Math.round(b.size_bytes / 1024) }} KB</small>
        </button>
      </div>
      <pre v-if="backupPreview" class="small-pre">{{ JSON.stringify(backupPreview, null, 2) }}</pre>
      </div>
    </section>

    <!-- 连接配置 -->
    <section class="setting-card compact-card">
      <div class="card-heading"><span>08</span><div><h2>连接配置</h2><p>MySQL 与 Ollama 的本机连接</p></div></div>
      <p class="hint">修改连接信息后，应用会重启并加载新配置。</p>
      <button class="save-btn secondary" @click="emit('reconfigure')">重新配置连接</button>
    </section>

    <!-- 关于 / 更新 -->
    <section class="setting-card compact-card">
      <div class="card-heading"><span>09</span><div><h2>关于与更新</h2><p>检查桌面端的新版本</p></div></div>
      <UpdateChecker />
    </section>
    </div>
  </section>
</template>

<style scoped>
.content {
  padding: 34px clamp(28px, 4vw, 64px) 54px;
  overflow: auto;
  flex: 1;
  background:
    radial-gradient(circle at 94% 0%, color-mix(in srgb, var(--color-accent) 7%, transparent), transparent 24%),
    var(--color-bg);
}
.settings-hero {
  max-width: 1120px;
  margin: 0 auto 26px;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
}
.eyebrow {
  color: var(--color-accent);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .16em;
}
h1 {
  margin: 4px 0 5px;
  font-size: 32px;
  letter-spacing: -.045em;
}
.subtitle {
  margin: 0;
  color: var(--color-fg-muted);
  font-size: 14px;
}
.privacy-badge {
  padding: 8px 12px;
  border: 1px solid color-mix(in srgb, var(--color-accent) 28%, var(--color-border));
  border-radius: 999px;
  color: var(--color-accent);
  background: var(--color-accent-soft);
  font-size: 12px;
}
.settings-grid {
  max-width: 1120px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.setting-card {
  padding: 20px;
  border: 1px solid var(--color-border);
  border-radius: 18px;
  background: color-mix(in srgb, var(--color-surface) 94%, transparent);
  box-shadow: var(--shadow-xs);
}
.setting-card.wide { grid-column: 1 / -1; }
.card-heading {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  margin-bottom: 16px;
}
.card-heading > span {
  padding-top: 3px;
  color: var(--color-accent);
  font: 700 10px/1 var(--font-mono);
}
.card-heading h2 { margin: 0; font-size: 16px; letter-spacing: -.02em; }
.card-heading p { margin: 3px 0 0; color: var(--color-fg-faint); font-size: 12px; }
.status-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.status-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 16px;
  font-size: 13px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}
.status-pill.ok {
  color: var(--color-success-fg);
  border-color: var(--color-success-soft);
}
.status-pill.bad {
  color: var(--color-danger-fg);
  border-color: var(--color-danger-soft);
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.status-pill.ok .dot {
  background: var(--color-success);
}
.status-pill.bad .dot {
  background: var(--color-danger);
}
.warn-text {
  margin-top: 10px;
  color: var(--color-danger-fg);
  font-size: 13px;
}
.loading-text {
  margin-top: 10px;
  color: var(--color-fg-muted);
  font-size: 13px;
}
.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
}
.info-grid > div {
  background: var(--color-surface-sunken);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  padding: 14px;
}
.k {
  display: block;
  font-size: 12px;
  color: var(--color-fg-subtle);
}
.v {
  display: block;
  font-size: 14px;
  margin-top: 3px;
  word-break: break-all;
}
.form {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: none;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field label {
  font-size: 13px;
  color: var(--color-fg-muted);
}
.field input,
.field select {
  padding: 8px 12px;
  border: 1px solid var(--color-border-strong);
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  width: 100%;
  background: var(--color-surface);
}
.field input:focus,
.field select:focus {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px var(--color-accent-soft);
}
.field-check label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.form-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}
.save-btn {
  background: var(--pa-btn-primary-bg);
  color: var(--color-accent-fg);
  border: none;
  border-radius: 8px;
  padding: 8px 20px;
  font-size: 14px;
  cursor: pointer;
}
.save-btn:disabled {
  background: var(--color-fg-disabled);
  cursor: not-allowed;
}
.save-btn.secondary {
  background: var(--color-surface-sunken);
  color: var(--color-fg);
  border: 1px solid var(--color-border);
}
.msg {
  font-size: 13px;
  color: var(--color-success-fg);
}
.provider-form {
  max-width: none;
}
.provider-scope {
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  padding: 10px 12px;
}
.secret-status {
  color: var(--color-fg-muted);
  font-size: 11px;
}
.secret-configure {
  align-self: flex-start;
  text-align: left;
}
.secret-clear {
  align-self: flex-start;
  border: 0;
  background: transparent;
  color: var(--color-danger-fg);
  cursor: pointer;
  padding: 0;
  font-size: 12px;
}
.secret-clear:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.provider-restart {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid var(--color-warning-soft);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 12px;
}
.backup-list {
  display: grid;
  gap: 8px;
}
.backup-row {
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  padding: 10px 12px;
  text-align: left;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  cursor: pointer;
}
.backup-row span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.backup-row small {
  color: var(--color-fg-subtle);
  flex: none;
}
.small-pre {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--color-surface-sunken);
  font-size: 12px;
}
.hint {
  font-size: 12px;
  color: var(--color-fg-subtle);
  margin-top: 8px;
}
@media (max-width: 940px) {
  .settings-grid { grid-template-columns: 1fr; }
  .setting-card.wide { grid-column: auto; }
}
</style>
