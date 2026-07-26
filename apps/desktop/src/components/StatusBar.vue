<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { PhCpu, PhActivity, PhBell } from "@phosphor-icons/vue";
import { getSettings, type AppSettings } from "../api";
import { useNotifications } from "../stores/notifications";
import { useHealth, type HealthSnapshot } from "../stores/health";

/**
 * 底部状态栏。通过共享 store 轮询 /health（5s）并读取 /settings 显示当前模型。
 * 展示 API/Ollama/MySQL/Chroma 四服务状态点 + 当前模型 + 任务状态。
 * 任务状态由父组件通过 taskLabel 传入（M0：生成中/空闲；M4 接入活动流后扩展）。
 */
defineProps<{ taskLabel?: string }>();

const notify = useNotifications();
const healthStore = useHealth();

type DotState = "ok" | "bad" | "idle";

const services = ref<Record<string, DotState>>({
  api: "idle",
  ollama: "idle",
  mysql: "idle",
  chroma: "idle",
});
const settings = ref<AppSettings | null>(null);
let timer: number | null = null;
let notifyTimer: number | null = null;

function okOf(h: HealthSnapshot, key: keyof HealthSnapshot): boolean {
  return h[key].ok;
}

async function refresh() {
  const h = await healthStore.refresh();
  if (h) {
    services.value = {
      api: okOf(h, "api") ? "ok" : "bad",
      ollama: okOf(h, "ollama") ? "ok" : "bad",
      mysql: okOf(h, "mysql") ? "ok" : "bad",
      chroma: okOf(h, "chroma") ? "ok" : "bad",
    };
  } else {
    // 首次连接尚未成功时置 idle；已有快照由 store 保留，不因瞬时失败闪灰。
    services.value = { api: "idle", ollama: "idle", mysql: "idle", chroma: "idle" };
  }
}

async function loadSettings() {
  try {
    settings.value = await getSettings();
  } catch {
    settings.value = null;
  }
}

onMounted(() => {
  refresh();
  loadSettings();
  timer = window.setInterval(refresh, 5000);
  // 拉取持久化通知，让铃铛角标反映后端未读（导入/备份等异步结果）
  void notify.loadPersisted();
  notifyTimer = window.setInterval(() => void notify.loadPersisted(), 30000);
});
onUnmounted(() => {
  if (timer) window.clearInterval(timer);
  if (notifyTimer) window.clearInterval(notifyTimer);
});

const serviceList: { key: string; label: string }[] = [
  { key: "api", label: "API" },
  { key: "ollama", label: "Ollama" },
  { key: "mysql", label: "MySQL" },
  { key: "chroma", label: "Chroma" },
];
</script>

<template>
  <div class="statusbar" role="status" aria-label="服务状态">
    <div class="sb-services">
      <div
        v-for="s in serviceList"
        :key="s.key"
        class="sb-service"
        :title="`${s.label}: ${services[s.key]}`"
      >
        <span class="pa-status-dot" :class="`pa-status-dot--${services[s.key]}`" />
        <span class="sb-label">{{ s.label }}</span>
      </div>
    </div>

    <div class="sb-right">
      <button
        class="sb-bell"
        :class="{ hasunread: notify.unreadCount.value > 0 }"
        :title="notify.unreadCount.value > 0 ? `通知中心（${notify.unreadCount.value} 条未读）` : '通知中心'"
        aria-label="通知中心"
        @click="notify.openCenter()"
      >
        <PhBell :size="13" weight="regular" />
        <span v-if="notify.unreadCount.value > 0" class="sb-bell-badge">{{
          notify.unreadCount.value
        }}</span>
      </button>
      <div class="sb-item" :title="`当前模型：${settings?.llm_model || '—'}`">
        <PhCpu :size="12" weight="regular" />
        <span class="sb-value pa-ellipsis">{{
          settings?.llm_model || "—"
        }}</span>
      </div>
      <div class="sb-item">
        <PhActivity :size="12" weight="regular" />
        <span class="sb-value">{{ taskLabel || "空闲" }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.statusbar {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-3);
  gap: var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
}
.sb-services {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}
.sb-service {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  white-space: nowrap;
}
.sb-label {
  color: var(--color-fg-subtle);
}
.sb-right {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-shrink: 0;
}
.sb-item {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  white-space: nowrap;
}
.sb-value {
  max-width: 220px;
  font-variant-numeric: tabular-nums;
}
.sb-bell {
  position: relative;
  border: none;
  background: transparent;
  color: var(--color-fg-subtle);
  cursor: pointer;
  padding: var(--space-1);
  border-radius: var(--radius);
  display: grid;
  place-items: center;
  transition: background var(--duration-fast) var(--ease),
    color var(--duration-fast) var(--ease);
}
.sb-bell:hover {
  background: var(--color-surface-sunken);
  color: var(--color-fg);
}
.sb-bell.hasunread {
  color: var(--color-accent);
}
.sb-bell-badge {
  position: absolute;
  top: -2px;
  right: -2px;
  min-width: 14px;
  height: 14px;
  padding: 0 3px;
  background: var(--color-danger);
  color: var(--color-danger-on-solid);
  font-size: 9px;
  font-weight: var(--font-semibold);
  line-height: 14px;
  border-radius: var(--radius-full);
  text-align: center;
}
</style>
