<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { ensureApiBase } from "../api";
import { useHealth } from "../stores/health";

const { health, refreshing, error, refresh } = useHealth();
const connected = computed(() => health.value !== null);
const lastUpdated = ref("");
const apiBase = ref("");
let timer: ReturnType<typeof setInterval> | undefined;

async function fetchHealth() {
  try {
    apiBase.value = await ensureApiBase();
  } catch {
    // refresh 会提供统一错误状态；API 地址仅用于诊断展示。
  } finally {
    await refresh();
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

    <div v-if="refreshing && !connected" class="banner neutral">正在检查本地服务…</div>
    <div v-else-if="!connected" class="banner error">
      <div class="banner-title">⚠ 本地后端未连接</div>
      <div class="banner-detail">
        无法访问 <code>{{ apiBase || "本地 API" }}</code>。请确认 Python 后端已启动：
        <br />
        <code>uv run uvicorn personal_assistant.main_api:app --port 8000</code>
      </div>
      <div class="banner-err">{{ error }}</div>
    </div>
    <div v-else-if="error" class="banner warning">
      当前显示最近一次确认状态；本次刷新失败：{{ error }}
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
  color: var(--color-fg-muted);
  font-size: 13px;
}
.banner {
  padding: 12px 16px;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 14px;
}
.banner.success {
  background: var(--color-success-soft);
  color: var(--color-success-fg);
  border: 1px solid var(--color-success-border);
}
.banner.error {
  background: var(--color-danger-soft);
  color: var(--color-danger-fg);
  border: 1px solid var(--color-danger-border);
}
.banner.warning {
  background: var(--color-warning-soft);
  color: var(--color-warning-fg);
  border: 1px solid color-mix(in srgb, var(--color-warning) 35%, transparent);
}
.banner.neutral {
  background: var(--color-surface-sunken);
  color: var(--color-fg-muted);
  border: 1px solid var(--color-border);
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
  background: var(--color-surface-sunken);
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
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 10px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.status-card.ok {
  border-left: 4px solid var(--color-success);
}
.status-card.bad {
  border-left: 4px solid var(--color-danger);
}
.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-card.ok .dot {
  background: var(--color-success);
}
.status-card.bad .dot {
  background: var(--color-danger);
}
.label {
  font-weight: 500;
  font-size: 14px;
}
.detail {
  font-size: 12px;
  color: var(--color-fg-muted);
  margin-top: 2px;
}
.footer {
  margin-top: 20px;
  font-size: 12px;
  color: var(--color-fg-faint);
}
</style>
