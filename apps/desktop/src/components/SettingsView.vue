<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import {
  exportBackup,
  getHealth,
  getSettings,
  listBackups,
  listProviders,
  previewRestoreBackup,
  testProvider,
  updateProviders,
  updateSettings,
  type AppSettings,
} from "../api";
import type { BackupExportResult, BackupRestorePreview, ProviderStatus } from "../types";
import UpdateChecker from "./UpdateChecker.vue";

const emit = defineEmits<{ (e: "reconfigure"): void }>();

interface ComponentHealth {
  ok: boolean;
  error?: string;
  [k: string]: unknown;
}
interface HealthResult {
  api: ComponentHealth;
  ollama: ComponentHealth & { base_url?: string };
  mysql: ComponentHealth;
  chroma: ComponentHealth;
}

const settings = ref<AppSettings | null>(null);
const health = ref<HealthResult | null>(null);
const providers = ref<ProviderStatus | null>(null);
const backups = ref<BackupExportResult[]>([]);
const backupPreview = ref<BackupRestorePreview | null>(null);
const backupPath = ref("");
const saving = ref(false);
const msg = ref("");
const providerMsg = ref("");
const backupMsg = ref("");
let timer: ReturnType<typeof setInterval> | undefined;
let msgTimer: ReturnType<typeof setTimeout> | undefined;

async function load() {
  try {
    settings.value = await getSettings();
  } catch {
    settings.value = null;
  }
  try {
    health.value = (await getHealth()) as unknown as HealthResult;
  } catch {
    health.value = null;
  }
  try {
    providers.value = await listProviders();
  } catch {
    providers.value = null;
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
  timer = setInterval(load, 5000);
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
      provider_type: settings.value.provider_type,
      remote_provider_enabled: settings.value.remote_provider_enabled,
      openai_api_key: settings.value.openai_api_key,
      openai_base_url: settings.value.openai_base_url,
      openai_model: settings.value.openai_model,
      claude_api_key: settings.value.claude_api_key,
      claude_model: settings.value.claude_model,
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
    providers.value = await updateProviders({
      provider_type: settings.value.provider_type,
      remote_provider_enabled: settings.value.remote_provider_enabled,
      openai_api_key: settings.value.openai_api_key,
      openai_base_url: settings.value.openai_base_url,
      openai_model: settings.value.openai_model,
      claude_api_key: settings.value.claude_api_key,
      claude_model: settings.value.claude_model,
    });
    providerMsg.value = "Provider 已保存";
  } catch (e) {
    providerMsg.value = "Provider 保存失败：" + String(e);
  } finally {
    saving.value = false;
  }
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
    <h1>设置 / 状态</h1>
    <p class="subtitle">查看依赖状态，调整模型参数。</p>

    <!-- 状态 -->
    <h2 class="section-title">运行状态</h2>
    <div class="status-row">
      <div v-for="s in statusItems" :key="s.label" class="status-pill" :class="s.ok ? 'ok' : 'bad'">
        <span class="dot" />{{ s.label }}{{ s.ok ? " 正常" : " 不可用" }}
      </div>
    </div>
    <div v-if="!health" class="warn-text">⚠ 本地后端未连接，无法获取状态。</div>

    <!-- 模型信息（只读） -->
    <h2 class="section-title">当前模型</h2>
    <div class="info-grid">
      <div><span class="k">LLM 模型</span><span class="v">{{ settings?.llm_model || "—" }}</span></div>
      <div><span class="k">嵌入模型</span><span class="v">{{ settings?.embed_model || "—" }}</span></div>
      <div><span class="k">Ollama 地址</span><span class="v">{{ health?.ollama?.base_url || "—" }}</span></div>
    </div>

    <!-- 可调参数 -->
    <h2 class="section-title">模型参数</h2>
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

    <!-- Provider -->
    <h2 class="section-title">Provider 与隐私范围</h2>
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
        <input v-model="settings.openai_api_key" type="password" autocomplete="off" />
      </div>
      <div class="field">
        <label>Claude Model</label>
        <input v-model="settings.claude_model" placeholder="claude-3-5-sonnet-latest" />
      </div>
      <div class="field">
        <label>Claude API Key</label>
        <input v-model="settings.claude_api_key" type="password" autocomplete="off" />
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
      <pre v-if="providerMsg" class="small-pre">{{ providerMsg }}</pre>
    </div>

    <!-- 备份 -->
    <h2 class="section-title">备份 / 恢复预览</h2>
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

    <!-- 连接配置 -->
    <h2 class="section-title">连接配置</h2>
    <p class="hint">
      修改 MySQL / Ollama 连接信息需重新配置。保存后会重启应用以加载新配置。
    </p>
    <button class="save-btn" @click="emit('reconfigure')">重新配置连接</button>

    <!-- 关于 / 更新 -->
    <h2 class="section-title">关于 / 更新</h2>
    <UpdateChecker />
  </section>
</template>

<style scoped>
.content {
  padding: 28px 32px;
  overflow: auto;
  flex: 1;
}
h1 {
  margin: 0 0 4px;
  font-size: 22px;
}
.subtitle {
  margin: 0 0 20px;
  color: #6a6b6e;
  font-size: 13px;
}
.section-title {
  font-size: 14px;
  font-weight: 600;
  margin: 22px 0 10px;
  color: #3a3b3e;
}
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
  border: 1px solid #e5e6e8;
  background: #fff;
}
.status-pill.ok {
  color: #1b5e20;
  border-color: #c8e6c9;
}
.status-pill.bad {
  color: #b71c1c;
  border-color: #f5c6c2;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.status-pill.ok .dot {
  background: #2e7d32;
}
.status-pill.bad .dot {
  background: #c62828;
}
.warn-text {
  margin-top: 10px;
  color: #b71c1c;
  font-size: 13px;
}
.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
}
.info-grid > div {
  background: #fff;
  border: 1px solid #e5e6e8;
  border-radius: 8px;
  padding: 12px 14px;
}
.k {
  display: block;
  font-size: 12px;
  color: #9a9b9e;
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
  max-width: 480px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field label {
  font-size: 13px;
  color: #545659;
}
.field input,
.field select {
  padding: 8px 12px;
  border: 1px solid #d8d9da;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  width: min(420px, 100%);
  background: #fff;
}
.field input:focus,
.field select:focus {
  border-color: #1a1b1e;
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
  background: #1a1b1e;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 8px 20px;
  font-size: 14px;
  cursor: pointer;
}
.save-btn:disabled {
  background: #c0c1c4;
  cursor: not-allowed;
}
.save-btn.secondary {
  background: #f4f5f6;
  color: #1a1b1e;
  border: 1px solid #d8d9da;
}
.msg {
  font-size: 13px;
  color: #2e7d32;
}
.provider-form {
  max-width: 680px;
}
.provider-scope {
  border: 1px solid #e5e6e8;
  border-radius: 8px;
  background: #fff;
  padding: 10px 12px;
}
.backup-list {
  display: grid;
  gap: 8px;
}
.backup-row {
  border: 1px solid #e5e6e8;
  border-radius: 8px;
  background: #fff;
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
  color: #9a9b9e;
  flex: none;
}
.small-pre {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  border: 1px solid #e5e6e8;
  border-radius: 8px;
  padding: 10px 12px;
  background: #f8f9fa;
  font-size: 12px;
}
.hint {
  font-size: 12px;
  color: #9a9b9e;
  margin-top: 8px;
}
</style>
