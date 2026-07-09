<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { ensureApiBase, getHealth } from "../api";

interface ComponentHealth {
  ok: boolean;
  error?: string;
  [k: string]: unknown;
}
interface HealthResult {
  api: ComponentHealth;
  ollama: ComponentHealth & {
    models?: string[];
    llm_model_available?: boolean;
    embed_model_available?: boolean;
  };
  mysql: ComponentHealth;
  chroma: ComponentHealth & { collections?: number };
}

const health = ref<HealthResult | null>(null);
const connected = ref(false);
const errorMsg = ref("");
const lastUpdated = ref("");
const apiBase = ref("");
let timer: ReturnType<typeof setInterval> | undefined;

async function fetchHealth() {
  try {
    apiBase.value = await ensureApiBase();
    health.value = (await getHealth()) as unknown as HealthResult;
    connected.value = true;
    errorMsg.value = "";
  } catch (e) {
    connected.value = false;
    health.value = null;
    errorMsg.value = e instanceof Error ? e.message : String(e);
  } finally {
    lastUpdated.value = new Date().toLocaleTimeString();
  }
}

onMounted(() => {
  fetchHealth();
  timer = setInterval(fetchHealth, 5000);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
});

const components = computed(() => {
  const h = health.value;
  if (!h) return [];
  return [
    { key: "api", label: "本地后端 API", ok: h.api.ok, detail: "" },
    {
      key: "ollama",
      label: "Ollama · LLM / Embedding",
      ok: h.ollama.ok,
      detail: h.ollama.ok
        ? `LLM ${h.ollama.llm_model_available ? "✓" : "✗"} · Embed ${h.ollama.embed_model_available ? "✓" : "✗"}`
        : h.ollama.error ?? "",
    },
    { key: "mysql", label: "MySQL · 业务库", ok: h.mysql.ok, detail: h.mysql.error ?? "" },
    {
      key: "chroma",
      label: "ChromaDB · 向量库",
      ok: h.chroma.ok,
      detail: h.chroma.ok ? `collections: ${h.chroma.collections ?? 0}` : h.chroma.error ?? "",
    },
  ];
});
</script>

<template>
  <section class="content">
    <h1>运行状态</h1>
    <p class="subtitle">确认 Ollama、MySQL、向量库、本地后端是否正常。</p>

    <div v-if="!connected" class="banner error">
      <div class="banner-title">⚠ 本地后端未连接</div>
      <div class="banner-detail">
        无法访问 <code>{{ apiBase || "本地 API" }}</code>。请确认 Python 后端已启动：
        <br />
        <code>uv run uvicorn personal_assistant.main_api:app --port 8000</code>
      </div>
      <div class="banner-err">{{ errorMsg }}</div>
    </div>
    <div v-else class="banner success">✓ 本地后端已连接</div>

    <div class="status-grid">
      <div
        v-for="c in components"
        :key="c.key"
        class="status-card"
        :class="c.ok ? 'ok' : 'bad'"
      >
        <span class="dot" />
        <div class="info">
          <div class="label">{{ c.label }}</div>
          <div class="detail">{{ c.ok ? (c.detail || "正常") : (c.detail || "不可用") }}</div>
        </div>
      </div>
    </div>

    <div class="footer">最近更新：{{ lastUpdated || "—" }} · 每 5 秒自动刷新</div>
  </section>
</template>

<style scoped>
.content {
  padding: 28px 32px;
  overflow: auto;
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
.banner {
  padding: 12px 16px;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 14px;
}
.banner.success {
  background: #e8f5e9;
  color: #1b5e20;
  border: 1px solid #c8e6c9;
}
.banner.error {
  background: #fdecea;
  color: #b71c1c;
  border: 1px solid #f5c6c2;
}
.banner-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.banner-detail {
  font-size: 13px;
  line-height: 1.6;
}
.banner-detail code {
  background: rgba(0, 0, 0, 0.06);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 12px;
}
.banner-err {
  margin-top: 6px;
  font-size: 12px;
  opacity: 0.8;
}
.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
.status-card {
  background: #fff;
  border: 1px solid #e5e6e8;
  border-radius: 10px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.status-card.ok {
  border-left: 4px solid #2e7d32;
}
.status-card.bad {
  border-left: 4px solid #c62828;
}
.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-card.ok .dot {
  background: #2e7d32;
}
.status-card.bad .dot {
  background: #c62828;
}
.label {
  font-weight: 500;
  font-size: 14px;
}
.detail {
  font-size: 12px;
  color: #6a6b6e;
  margin-top: 2px;
}
.footer {
  margin-top: 20px;
  font-size: 12px;
  color: #9a9b9e;
}
</style>
