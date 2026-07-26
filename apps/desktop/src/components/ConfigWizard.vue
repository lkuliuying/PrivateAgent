<script setup lang="ts">
import { ref, onMounted } from "vue";
import {
  cmdCheckDependencies,
  cmdReadConfig,
  cmdWriteConfig,
  cmdTestConnections,
  type ConfigData,
  type ConnResult,
  type DepResult,
} from "../api";

const props = withDefaults(defineProps<{ mode?: "first" | "reconfigure" }>(), {
  mode: "first",
});
const emit = defineEmits<{ (e: "done"): void }>();

const step = ref<1 | 2>(1);
const cfg = ref<ConfigData>(makeDefault());
const deps = ref<DepResult | null>(null);
const depChecking = ref(false);
const testing = ref(false);
const conn = ref<ConnResult | null>(null);
const saving = ref(false);
const error = ref("");

function makeDefault(): ConfigData {
  return {
    db_host: "127.0.0.1",
    db_port: 3306,
    db_user: "root",
    db_password: "",
    db_name: "personal_assistant",
    ollama_base_url: "http://127.0.0.1:11434",
    llm_model: "qwen2.5:14b-instruct-q4_K_M",
    embed_model: "bge-m3",
  };
}

onMounted(async () => {
  // 读取已有配置（不存在则默认值），并探测默认端口环境。
  try {
    cfg.value = await cmdReadConfig();
  } catch {
    cfg.value = makeDefault();
  }
  await checkDeps();
});

async function checkDeps() {
  depChecking.value = true;
  try {
    deps.value = await cmdCheckDependencies();
  } catch {
    deps.value = null;
  } finally {
    depChecking.value = false;
  }
}

/** 校验并规整端口；无效时设置 error 并返回 null。 */
function coercePort(): number | null {
  const port = Number(cfg.value.db_port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    error.value = "请输入有效的 MySQL 端口（1-65535）";
    return null;
  }
  cfg.value.db_port = port;
  return port;
}

async function testConn() {
  error.value = "";
  if (coercePort() === null) return;
  testing.value = true;
  conn.value = null;
  try {
    conn.value = await cmdTestConnections({ ...cfg.value });
  } catch (e) {
    error.value = "测试失败：" + String(e);
  } finally {
    testing.value = false;
  }
}

async function saveAndStart() {
  error.value = "";
  if (coercePort() === null) return;
  saving.value = true;
  try {
    await cmdWriteConfig({ ...cfg.value });
    emit("done");
  } catch (e) {
    error.value = "保存失败：" + String(e);
  } finally {
    saving.value = false;
  }
}

const saveLabel = props.mode === "reconfigure" ? "保存并重启应用" : "保存并启动后端";
</script>

<template>
  <section class="wizard">
    <div class="wizard-card">
      <h1>连接配置向导</h1>
      <p class="subtitle">
        私人助手需要连接本地的 <b>MySQL</b> 与 <b>Ollama</b>。请确认二者已安装并运行，再填写连接信息。
      </p>

      <!-- 步骤指示 -->
      <div class="steps">
        <span :class="['step', step >= 1 ? 'active' : '']">① 环境检测</span>
        <span class="sep">→</span>
        <span :class="['step', step >= 2 ? 'active' : '']">② 填写连接</span>
      </div>

      <!-- 步骤 1：环境检测 -->
      <div v-if="step === 1" class="step-body">
        <div class="dep-row">
          <div class="dep-pill" :class="deps?.mysql_reachable ? 'ok' : 'bad'">
            <span class="dot" />MySQL（127.0.0.1:3306）
            <span class="state">{{ deps ? (deps.mysql_reachable ? "可达" : "未检测到") : "检测中…" }}</span>
          </div>
          <div class="dep-pill" :class="deps?.ollama_reachable ? 'ok' : 'bad'">
            <span class="dot" />Ollama（127.0.0.1:11434）
            <span class="state">{{ deps ? (deps.ollama_reachable ? "可达" : "未检测到") : "检测中…" }}</span>
          </div>
        </div>
        <button class="link-btn" @click="checkDeps" :disabled="depChecking">
          {{ depChecking ? "检测中…" : "重新检测" }}
        </button>
        <p v-if="deps && (!deps.mysql_reachable || !deps.ollama_reachable)" class="warn">
          ⚠ 部分依赖未检测到。请先启动对应服务，或确认端口后继续（仍可在下一步自定义地址）。
        </p>
        <div class="actions">
          <button class="primary-btn" @click="step = 2">下一步</button>
        </div>
      </div>

      <!-- 步骤 2：填写连接 -->
      <div v-else class="step-body">
        <h2 class="group-title">MySQL</h2>
        <div class="grid">
          <label class="field"><span>主机</span><input v-model="cfg.db_host" /></label>
          <label class="field"><span>端口</span><input type="number" v-model.number="cfg.db_port" /></label>
          <label class="field"><span>用户名</span><input v-model="cfg.db_user" /></label>
          <label class="field"><span>密码</span><input type="password" v-model="cfg.db_password" /></label>
          <label class="field"><span>数据库名</span><input v-model="cfg.db_name" /></label>
        </div>

        <h2 class="group-title">Ollama</h2>
        <div class="grid">
          <label class="field field-wide"><span>Base URL</span><input v-model="cfg.ollama_base_url" /></label>
          <label class="field"><span>LLM 模型</span><input v-model="cfg.llm_model" /></label>
          <label class="field"><span>嵌入模型</span><input v-model="cfg.embed_model" /></label>
        </div>

        <div class="actions">
          <button class="ghost-btn" @click="step = 1">上一步</button>
          <button class="ghost-btn" @click="testConn" :disabled="testing">
            {{ testing ? "测试中…" : "测试连接" }}
          </button>
          <button class="primary-btn" @click="saveAndStart" :disabled="saving">
            {{ saving ? "保存中…" : saveLabel }}
          </button>
        </div>

        <!-- 测试结果 -->
        <div v-if="conn" class="conn-result">
          <div class="conn-line">
            <span :class="['badge', conn.mysql_ok ? 'ok' : 'bad']">{{ conn.mysql_ok ? "✓" : "✗" }}</span>
            MySQL {{ conn.mysql_ok ? "连接成功" : "连接失败" }}
            <span v-if="conn.mysql_error" class="err">{{ conn.mysql_error }}</span>
          </div>
          <div class="conn-line">
            <span :class="['badge', conn.ollama_ok ? 'ok' : 'bad']">{{ conn.ollama_ok ? "✓" : "✗" }}</span>
            Ollama {{ conn.ollama_ok ? "连接成功" : "连接失败" }}
            <span v-if="conn.ollama_error" class="err">{{ conn.ollama_error }}</span>
          </div>
          <div v-if="conn.ollama_ok" class="conn-line">
            <span class="badge ok">✓</span>
            已拉取模型（{{ conn.ollama_models.length }}）：
            <span v-if="conn.ollama_models.length" class="models">{{ conn.ollama_models.join("、") }}</span>
            <span v-else class="err">无</span>
          </div>
          <div v-if="conn.ollama_ok && !conn.llm_model_available" class="warn">
            ⚠ LLM 模型「{{ cfg.llm_model }}」未在 Ollama 中找到，请先 <code>ollama pull {{ cfg.llm_model }}</code>
          </div>
          <div v-if="conn.ollama_ok && !conn.embed_model_available" class="warn">
            ⚠ 嵌入模型「{{ cfg.embed_model }}」未在 Ollama 中找到，请先 <code>ollama pull {{ cfg.embed_model }}</code>
          </div>
        </div>
        <p v-if="error" class="warn">{{ error }}</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.wizard {
  flex: 1;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 20px;
  overflow: auto;
  background: var(--color-bg);
}
.wizard-card {
  width: 100%;
  max-width: 680px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  padding: 28px 32px;
  box-shadow: var(--shadow-sm);
}
h1 {
  margin: 0 0 4px;
  font-size: 22px;
}
.subtitle {
  margin: 0 0 18px;
  color: var(--color-fg-muted);
  font-size: 13px;
}
.steps {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 22px;
  font-size: 13px;
}
.step {
  color: var(--color-fg-faint);
}
.step.active {
  color: var(--color-fg);
  font-weight: 600;
}
.sep {
  color: var(--color-fg-disabled);
}
.step-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.dep-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.dep-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  font-size: 13px;
}
.dep-pill.ok {
  color: var(--color-success-fg);
  border-color: var(--color-success-border);
  background: var(--color-success-soft);
}
.dep-pill.bad {
  color: var(--color-danger-fg);
  border-color: var(--color-danger-border);
  background: var(--color-danger-soft);
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.dep-pill.ok .dot {
  background: var(--color-success);
}
.dep-pill.bad .dot {
  background: var(--color-danger);
}
.state {
  color: inherit;
  opacity: 0.8;
}
.link-btn {
  align-self: flex-start;
  background: none;
  border: none;
  color: var(--color-accent);
  text-decoration: underline;
  cursor: pointer;
  font-size: 13px;
  padding: 0;
}
.warn {
  color: var(--color-danger-fg);
  font-size: 13px;
}
.warn code {
  background: var(--color-surface-sunken);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 12px;
}
.group-title {
  font-size: 14px;
  font-weight: 600;
  margin: 6px 0 4px;
  color: var(--color-fg-muted);
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--color-fg-muted);
}
.field-wide {
  grid-column: 1 / -1;
}
.field input {
  padding: 8px 12px;
  border: 1px solid var(--color-border-strong);
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  background: var(--color-surface);
  color: var(--color-fg);
}
.field input:focus {
  border-color: var(--color-accent);
}
.actions {
  display: flex;
  gap: 10px;
  margin-top: 6px;
}
.primary-btn {
  background: var(--color-accent);
  color: var(--color-accent-fg);
  border: none;
  border-radius: 8px;
  padding: 9px 20px;
  font-size: 14px;
  cursor: pointer;
}
.primary-btn:disabled {
  background: var(--color-fg-disabled);
  cursor: not-allowed;
}
.ghost-btn {
  background: var(--color-surface);
  color: var(--color-fg);
  border: 1px solid var(--color-border-strong);
  border-radius: 8px;
  padding: 9px 18px;
  font-size: 14px;
  cursor: pointer;
}
.ghost-btn:disabled {
  color: var(--color-fg-disabled);
  cursor: not-allowed;
}
.conn-result {
  margin-top: 6px;
  padding: 14px 16px;
  background: var(--color-panel);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.conn-line {
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.badge {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}
.badge.ok {
  background: var(--color-success);
  color: var(--color-success-on-solid);
}
.badge.bad {
  background: var(--color-danger);
  color: var(--color-danger-on-solid);
}
.err {
  color: var(--color-danger-fg);
  font-size: 12px;
}
.models {
  color: var(--color-fg-muted);
  word-break: break-all;
}
</style>
