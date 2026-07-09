<script setup lang="ts">
/**
 * 本地集成面板（第八阶段 M8）：ICS 日历导入 -> 提醒/收件箱。
 * 流程：选择/输入 ICS 文件 -> 创建源 -> 隐私预览 -> 导入 -> 可撤销。
 * 走 trusted paths（Tauri 文件选择器授权）+ 来源追踪 + 可撤销，不默认外发。
 */
import { onMounted, ref } from "vue";
import { PhArrowClockwise, PhFileText, PhEye, PhDownloadSimple, PhArrowCounterClockwise } from "@phosphor-icons/vue";
import {
  createIntegrationSource,
  listIntegrationImports,
  listIntegrationSources,
  pickFile,
  previewIntegration,
  revertIntegrationImport,
  runIntegrationImport,
  type IntegrationImport,
  type IntegrationPreview,
  type IntegrationSource,
} from "../api";
import { useNotifications } from "../stores/notifications";

const notify = useNotifications();
const sources = ref<IntegrationSource[]>([]);
const imports = ref<IntegrationImport[]>([]);
const filePath = ref("");
const title = ref("");
const target = ref<"reminder" | "inbox">("reminder");
const preview = ref<IntegrationPreview | null>(null);
const previewSourceId = ref<number | null>(null);
const busy = ref(false);

async function load() {
  try {
    [sources.value, imports.value] = await Promise.all([
      listIntegrationSources(),
      listIntegrationImports(),
    ]);
  } catch (e) {
    notify.error("加载集成失败", String(e));
  }
}

async function pickIcsFile() {
  const picked = await pickFile([{ name: "iCalendar", extensions: ["ics"] }]);
  if (picked) filePath.value = picked;
}

async function createAndPreview() {
  if (!filePath.value.trim()) {
    notify.warning("请先选择/输入 ICS 文件路径");
    return;
  }
  busy.value = true;
  try {
    const src = await createIntegrationSource({
      kind: "ics_calendar",
      title: title.value.trim() || "ICS 日历",
      file_path: filePath.value.trim(),
      target: target.value,
    });
    previewSourceId.value = src.id;
    preview.value = await previewIntegration(src.id);
    notify.success(`预览：${preview.value.event_count} 个事件`);
  } catch (e) {
    notify.error("预览失败（路径未授权？）", String(e));
  } finally {
    busy.value = false;
  }
}

async function doImport(sourceId: number) {
  busy.value = true;
  try {
    await runIntegrationImport(sourceId);
    notify.success("导入完成（可撤销）");
    preview.value = null;
    previewSourceId.value = null;
    await load();
  } catch (e) {
    notify.error("导入失败", String(e));
  } finally {
    busy.value = false;
  }
}

async function revert(imp: IntegrationImport) {
  try {
    await revertIntegrationImport(imp.id);
    notify.success("已撤销导入");
    await load();
  } catch (e) {
    notify.error("撤销失败", String(e));
  }
}

onMounted(load);
</script>

<template>
  <div class="int-panel">
    <div class="panel-head">
      <div>
        <h3>本地集成 · ICS 日历</h3>
        <p class="hint">导入本地 ICS 文件为提醒/收件箱。只读、可撤销、不外发。</p>
      </div>
      <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="load">
        <PhArrowClockwise :size="14" /> 刷新
      </button>
    </div>

    <div class="int-form">
      <div class="int-row">
        <input v-model="title" class="int-input" placeholder="标题（可选）" />
        <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="pickIcsFile">
          <PhFileText :size="14" /> 选择文件
        </button>
      </div>
      <input v-model="filePath" class="int-input" placeholder="ICS 文件路径（需已授权）" />
      <div class="int-row">
        <select v-model="target" class="int-select">
          <option value="reminder">导入为提醒</option>
          <option value="inbox">导入为收件箱</option>
        </select>
        <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="busy" @click="createAndPreview">
          <PhEye :size="14" /> 预览
        </button>
      </div>
    </div>

    <div v-if="preview" class="int-preview">
      <strong>预览：{{ preview.event_count }} 个事件</strong>
      <ul>
        <li v-for="t in preview.sample_titles" :key="t">{{ t }}</li>
      </ul>
      <button
        v-if="previewSourceId != null"
        class="pa-btn pa-btn--primary pa-btn--sm"
        :disabled="busy"
        @click="doImport(previewSourceId!)"
      >
        <PhDownloadSimple :size="14" /> 确认导入
      </button>
    </div>

    <div class="int-list">
      <h4>导入记录</h4>
      <div v-for="imp in imports" :key="imp.id" class="int-item">
        <div class="int-item-body">
          <strong>#{{ imp.id }} · {{ imp.source_kind }} · {{ imp.status }}</strong>
          <span>{{ imp.summary_json?.event_count ?? 0 }} 事件 -> {{ imp.target_type }}</span>
        </div>
        <button
          v-if="imp.reversible && imp.status === 'imported'"
          class="pa-btn pa-btn--subtle pa-btn--sm"
          @click="revert(imp)"
        >
          <PhArrowCounterClockwise :size="14" /> 撤销
        </button>
      </div>
      <p v-if="!imports.length" class="int-empty">暂无导入记录。</p>
    </div>
  </div>
</template>

<style scoped>
.int-panel { display: flex; flex-direction: column; gap: var(--space-3); }
.panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-2); }
.panel-head h3 { margin: 0; font-size: var(--text-md); }
.hint { margin: 2px 0 0; color: var(--color-fg-faint); font-size: var(--text-sm); }
.int-form { display: flex; flex-direction: column; gap: var(--space-2); }
.int-row { display: flex; align-items: center; gap: var(--space-2); }
.int-input, .int-select {
  flex: 1; border: 1px solid var(--color-border-strong); border-radius: var(--radius);
  padding: var(--space-2) var(--space-3); font-size: var(--text-sm); background: var(--color-surface-sunken); color: var(--color-fg);
}
.int-select { flex: 0 0 auto; }
.int-preview { padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius); background: var(--color-bg); }
.int-preview ul { margin: var(--space-2) 0; padding-left: var(--space-5); font-size: var(--text-sm); color: var(--color-fg-muted); }
.int-list h4 { margin: 0 0 var(--space-2); font-size: var(--text-sm); }
.int-item { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius); }
.int-item-body { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.int-item-body strong { font-size: var(--text-sm); }
.int-item-body span { font-size: var(--text-xs); color: var(--color-fg-muted); }
.int-empty { color: var(--color-fg-faint); font-size: var(--text-sm); text-align: center; padding: var(--space-3); }
</style>
