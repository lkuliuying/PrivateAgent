<script setup lang="ts">
/**
 * 备份恢复与升级安全面板（第八阶段 M9）。
 * 导出备份（增强 manifest：app_version/schema_head/checksum/modules）+ 恢复演练
 * （预览 + manifest 校验 + Chroma/MySQL 一致性）+ 迁移失败 runbook。
 */
import { computed, onMounted, ref } from "vue";
import { PhArrowClockwise, PhDatabase, PhFlask, PhBookOpen } from "@phosphor-icons/vue";
import {
  exportBackup,
  getMigrationRunbook,
  listBackups,
  restoreDrillBackup,
} from "../api";
import type { BackupExportResult } from "../types";
import { useNotifications } from "../stores/notifications";

const notify = useNotifications();
const backups = ref<{ items: BackupExportResult[]; last_backup_at: string | null }>({
  items: [],
  last_backup_at: null,
});
const drill = ref<Record<string, unknown> | null>(null);
const runbook = ref<Record<string, string>>({});
const busy = ref(false);

const drillValid = computed(
  () => (drill.value?.manifest_validation as { valid?: boolean } | undefined)?.valid ?? false
);
const drillConsistent = computed(
  () => (drill.value?.chroma_mysql as { consistent?: boolean } | undefined)?.consistent ?? false
);
const drillOpenFindings = computed(
  () => (drill.value?.open_integrity_findings as number | undefined) ?? 0
);
const drillReady = computed(() => drill.value?.ready === true);

async function load() {
  try {
    backups.value = await listBackups();
    runbook.value = await getMigrationRunbook();
  } catch (e) {
    notify.error("加载备份信息失败", String(e));
  }
}

async function doExport() {
  busy.value = true;
  try {
    await exportBackup();
    notify.success("备份已导出");
    await load();
  } catch (e) {
    notify.error("导出失败", String(e));
  } finally {
    busy.value = false;
  }
}

async function doDrill(path: string) {
  busy.value = true;
  try {
    drill.value = await restoreDrillBackup(path);
    notify.success("恢复演练完成");
  } catch (e) {
    notify.error("演练失败", String(e));
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="bu-panel">
    <div class="panel-head">
      <div>
        <h3>备份恢复与升级安全</h3>
        <p class="hint">发布前备份建议 + manifest 校验 + 恢复演练 + 迁移失败 runbook。</p>
      </div>
      <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="load">
        <PhArrowClockwise :size="14" /> 刷新
      </button>
    </div>

    <div class="bu-actions">
      <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="busy" @click="doExport">
        <PhDatabase :size="14" /> 导出备份
      </button>
      <span class="bu-meta">最近备份：{{ backups.last_backup_at || "无" }}</span>
    </div>

    <div class="bu-list">
      <h4>备份包</h4>
      <div v-for="b in backups.items" :key="b.path" class="bu-item">
        <PhDatabase :size="14" class="bu-icon" />
        <div class="bu-item-body">
          <strong>{{ b.path.split(/[\\/]/).pop() || b.path }}</strong>
          <span>{{ Math.round((b.size_bytes || 0) / 1024) }} KB · {{ b.created_at }}</span>
        </div>
        <button class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="busy" @click="doDrill(b.path)">
          <PhFlask :size="14" /> 恢复演练
        </button>
      </div>
      <p v-if="!backups.items.length" class="bu-empty">暂无备份包。</p>
    </div>

    <div v-if="drill" class="bu-drill">
      <h4>演练结果</h4>
      <p>manifest 校验：{{ drillValid ? "通过" : "失败" }}</p>
      <p>open 完整性发现：{{ drillOpenFindings }}</p>
      <p>Chroma/MySQL 一致：{{ drillConsistent ? "是" : "否" }}</p>
      <p>就绪：{{ drillReady ? "是" : "否" }}</p>
    </div>

    <div class="bu-runbook">
      <h4><PhBookOpen :size="14" /> 迁移失败 runbook</h4>
      <dl>
        <template v-for="(v, k) in runbook" :key="k">
          <dt>{{ k }}</dt>
          <dd>{{ v }}</dd>
        </template>
      </dl>
    </div>
  </div>
</template>

<style scoped>
.bu-panel { display: flex; flex-direction: column; gap: var(--space-3); }
.panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-2); }
.panel-head h3 { margin: 0; font-size: var(--text-md); }
.hint { margin: 2px 0 0; color: var(--color-fg-faint); font-size: var(--text-sm); }
.bu-actions { display: flex; align-items: center; gap: var(--space-3); }
.bu-meta { font-size: var(--text-sm); color: var(--color-fg-muted); }
.bu-list h4, .bu-drill h4, .bu-runbook h4 { margin: 0 0 var(--space-2); font-size: var(--text-sm); }
.bu-item { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius); }
.bu-icon { color: var(--color-fg-subtle); }
.bu-item-body { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.bu-item-body strong { font-size: var(--text-sm); }
.bu-item-body span { font-size: var(--text-xs); color: var(--color-fg-muted); }
.bu-empty { color: var(--color-fg-faint); font-size: var(--text-sm); text-align: center; padding: var(--space-3); }
.bu-drill, .bu-runbook { padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius); background: var(--color-bg); font-size: var(--text-sm); }
.bu-drill p, .bu-runbook dd { margin: 2px 0; color: var(--color-fg-muted); }
.bu-runbook dt { font-weight: var(--font-medium); color: var(--color-fg); margin-top: var(--space-2); }
</style>
