<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { getHealth, getSettings, updateSettings, type AppSettings } from "../api";
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
const saving = ref(false);
const msg = ref("");
let timer: ReturnType<typeof setInterval> | undefined;

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
}
onMounted(() => {
  load();
  timer = setInterval(load, 5000);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
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
    setTimeout(() => (msg.value = ""), 3000);
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

    <!-- Provider 接口位（预留） -->
    <h2 class="section-title">云端 Provider（预留，第一阶段未启用）</h2>
    <div class="info-grid muted">
      <div><span class="k">OpenAI</span><span class="v">{{ settings?.openai_base_url ? "已配置" : "未配置" }}</span></div>
      <div><span class="k">Claude</span><span class="v">{{ settings?.claude_api_key ? "已配置" : "未配置" }}</span></div>
    </div>
    <p class="hint">第一阶段只实现本地 Ollama；OpenAI/Claude 字段已预留，后续阶段再开放。</p>

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
.field input[type="number"] {
  padding: 8px 12px;
  border: 1px solid #d8d9da;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  width: 200px;
}
.field input[type="number"]:focus {
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
.msg {
  font-size: 13px;
  color: #2e7d32;
}
.muted .v {
  color: #9a9b9e;
}
.hint {
  font-size: 12px;
  color: #9a9b9e;
  margin-top: 8px;
}
</style>
