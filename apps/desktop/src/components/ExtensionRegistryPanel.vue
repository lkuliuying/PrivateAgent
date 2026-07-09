<script setup lang="ts">
/**
 * 扩展注册表面板（第八阶段 M7）。
 * 列出 command / capture_source / provider / diagnostic_check / maintenance_check /
 * notification_target 注册项，可启用/禁用可配置扩展（不绕过审批状态机）。
 */
import { computed, onMounted, ref } from "vue";
import { PhPuzzlePiece, PhArrowClockwise } from "@phosphor-icons/vue";
import { listExtensions, patchExtension, type ExtensionDescriptor } from "../api";
import { useNotifications } from "../stores/notifications";

const notify = useNotifications();
const items = ref<ExtensionDescriptor[]>([]);
const loading = ref(false);
const kindFilter = ref<string>("");

const kinds = computed(() => [...new Set(items.value.map((i) => i.kind))]);
const filtered = computed(() =>
  kindFilter.value ? items.value.filter((i) => i.kind === kindFilter.value) : items.value
);

async function load() {
  loading.value = true;
  try {
    items.value = await listExtensions();
  } catch (e) {
    notify.error("加载扩展失败", String(e));
  } finally {
    loading.value = false;
  }
}

async function toggle(ext: ExtensionDescriptor) {
  try {
    await patchExtension(ext.id, !ext.enabled);
    ext.enabled = !ext.enabled;
    notify.success(`${ext.title} 已${ext.enabled ? "启用" : "禁用"}`);
  } catch (e) {
    notify.error("切换失败", String(e));
  }
}

onMounted(load);
</script>

<template>
  <div class="ext-panel">
    <div class="panel-head">
      <div>
        <h3>扩展注册表</h3>
        <p class="hint">统一注册 command / capture / provider / diagnostic / maintenance / notification。</p>
      </div>
      <button class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="loading" @click="load">
        <PhArrowClockwise :size="14" /> 刷新
      </button>
    </div>
    <div class="ext-filters">
      <button
        v-for="k in kinds"
        :key="k"
        class="ext-chip"
        :class="{ active: kindFilter === k }"
        @click="kindFilter = kindFilter === k ? '' : k"
      >
        {{ k }}
      </button>
    </div>
    <div v-for="ext in filtered" :key="ext.id" class="ext-item">
      <PhPuzzlePiece :size="16" class="ext-icon" />
      <div class="ext-body">
        <strong>{{ ext.title }} <span class="ext-kind">{{ ext.kind }}</span></strong>
        <span class="ext-meta">
          风险 {{ ext.risk_level }} · 权限
          {{ ext.permissions.length ? ext.permissions.join(", ") : "（无）" }}
        </span>
      </div>
      <button
        v-if="ext.configurable"
        class="pa-btn pa-btn--subtle pa-btn--sm"
        @click="toggle(ext)"
      >
        {{ ext.enabled ? "禁用" : "启用" }}
      </button>
      <span v-else class="ext-locked">内置</span>
    </div>
  </div>
</template>

<style scoped>
.ext-panel { display: flex; flex-direction: column; gap: var(--space-3); }
.panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-2); }
.panel-head h3 { margin: 0; font-size: var(--text-md); }
.hint { margin: 2px 0 0; color: var(--color-fg-faint); font-size: var(--text-sm); }
.ext-filters { display: flex; flex-wrap: wrap; gap: var(--space-1); }
.ext-chip {
  border: 1px solid var(--color-border); background: var(--color-surface);
  color: var(--color-fg-muted); font-size: var(--text-xs); padding: 2px var(--space-2);
  border-radius: var(--radius-full); cursor: pointer;
}
.ext-chip.active { background: var(--color-accent-soft); color: var(--color-accent); border-color: var(--color-accent); }
.ext-item {
  display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border); border-radius: var(--radius); background: var(--color-bg);
}
.ext-icon { color: var(--color-fg-subtle); flex-shrink: 0; }
.ext-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.ext-body strong { font-size: var(--text-sm); font-weight: var(--font-medium); }
.ext-kind { font-size: var(--text-xs); color: var(--color-fg-faint); font-weight: normal; }
.ext-meta { font-size: var(--text-xs); color: var(--color-fg-muted); }
.ext-locked { font-size: var(--text-xs); color: var(--color-fg-faint); }
</style>
