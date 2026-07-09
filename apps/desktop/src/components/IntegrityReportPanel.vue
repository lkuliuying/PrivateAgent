<script setup lang="ts">
/**
 * 数据完整性体检面板（第七阶段 M7）。运行体检、查看发现项、生成修复计划（预览）、
 * 按条执行修复（不默认删用户数据）。挂在诊断中心。
 */
import { onMounted, ref } from "vue";
import {
  PhArrowClockwise,
  PhClipboardText,
  PhWrench,
  PhCheckCircle,
  PhWarning,
} from "@phosphor-icons/vue";
import {
  applyRepair,
  listIntegrity,
  repairPlan,
  runIntegrity,
  type IntegrityFinding,
  type RepairPlanItem,
} from "../api";
import { useNotifications } from "../stores/notifications";

const notify = useNotifications();
const findings = ref<IntegrityFinding[]>([]);
const plan = ref<RepairPlanItem[]>([]);
const loading = ref(false);
const running = ref(false);

async function load() {
  loading.value = true;
  try {
    findings.value = await listIntegrity();
  } catch (e) {
    notify.error("加载体检结果失败", String(e));
  } finally {
    loading.value = false;
  }
}

async function run() {
  running.value = true;
  try {
    findings.value = await runIntegrity();
    notify.success("体检完成", `发现 ${findings.value.filter((f) => f.status === "open").length} 项待处理`);
  } catch (e) {
    notify.error("体检失败", String(e));
  } finally {
    running.value = false;
  }
}

async function genPlan() {
  try {
    plan.value = await repairPlan();
  } catch (e) {
    notify.error("生成修复计划失败", String(e));
  }
}

async function apply(item: RepairPlanItem) {
  if (item.destructive) {
    const ok = await notify.confirm({
      title: "执行修复",
      message: item.impact,
      danger: true,
      confirmLabel: "执行",
    });
    if (!ok) return;
  }
  try {
    const res = await applyRepair(item.finding_id);
    if (res.ok) notify.success("修复已执行", item.impact);
    else notify.warning("修复未完全执行", String(res.error || res.note || ""));
    await load();
    await genPlan();
  } catch (e) {
    notify.error("执行修复失败", String(e));
  }
}

function sevLabel(s: string): string {
  return { info: "提示", warning: "警告", error: "错误" }[s] || s;
}
function actionLabel(a: string | null): string {
  return (
    { reindex: "重建索引", delete_orphan: "删除孤立向量", archive: "归档", relink: "重新关联", ignore: "忽略" }[a || ""] || a || "—"
  );
}

onMounted(load);
</script>

<template>
  <article class="integ-panel">
    <div class="panel-head">
      <h3>数据完整性体检</h3>
      <div class="panel-actions">
        <button class="pa-btn pa-btn--subtle pa-btn--sm" :disabled="loading" @click="load">
          <PhArrowClockwise :size="14" /> 刷新
        </button>
        <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="running" @click="run">
          <PhClipboardText :size="14" /> 运行体检
        </button>
        <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="genPlan">
          <PhWrench :size="14" /> 修复计划
        </button>
      </div>
    </div>

    <div v-if="findings.length === 0" class="empty">
      <PhCheckCircle :size="18" weight="fill" /> 暂无发现项（点击「运行体检」检查）
    </div>
    <ul v-else class="integ-list">
      <li v-for="f in findings" :key="f.id" class="integ-item">
        <div class="integ-item-head">
          <component
            :is="f.severity === 'error' ? PhWarning : f.severity === 'warning' ? PhWarning : PhCheckCircle"
            :size="15"
            :class="`sev-${f.severity}`"
            weight="fill"
          />
          <strong>{{ f.check_name }}</strong>
          <span class="sev-badge" :class="`sev-${f.severity}`">{{ sevLabel(f.severity) }}</span>
          <span class="status-badge" :class="`st-${f.status}`">{{ f.status }}</span>
        </div>
        <p v-if="f.detail_json" class="integ-detail">
          {{ JSON.stringify(f.detail_json) }}
        </p>
        <div class="integ-foot">
          <span class="action-label">建议：{{ actionLabel(f.suggested_action) }}</span>
          <button
            v-if="f.status === 'open'"
            class="pa-btn pa-btn--subtle pa-btn--sm"
            @click="genPlan().then(() => { const p = plan.find((x) => x.finding_id === f.id); if (p) apply(p); })"
          >
            执行修复
          </button>
        </div>
      </li>
    </ul>

    <div v-if="plan.length" class="plan-section">
      <h4>修复计划（预览）</h4>
      <ul class="plan-list">
        <li v-for="p in plan" :key="p.finding_id" class="plan-item">
          <div>
            <strong>{{ p.check_name }}</strong>
            <span class="action-label"> → {{ actionLabel(p.suggested_action) }}</span>
            <p class="plan-impact">{{ p.impact }}</p>
          </div>
          <button class="pa-btn pa-btn--primary pa-btn--sm" @click="apply(p)">
            应用
          </button>
        </li>
      </ul>
    </div>
  </article>
</template>

<style scoped>
.integ-panel {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.panel-head h3 {
  margin: 0;
  font-size: var(--text-md);
}
.panel-actions {
  display: flex;
  gap: var(--space-2);
}
.empty {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.integ-list,
.plan-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.integ-item {
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-2) var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.integ-item-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.integ-item-head strong {
  font-size: var(--text-sm);
}
.sev-error {
  color: var(--color-danger);
}
.sev-warning {
  color: var(--color-warning);
}
.sev-info {
  color: var(--color-info);
}
.sev-badge {
  font-size: var(--text-xs);
  padding: 1px var(--space-2);
  border-radius: var(--radius-full);
  background: var(--color-surface-sunken);
}
.sev-badge.sev-error {
  color: var(--color-danger-fg);
  background: var(--color-danger-soft);
}
.sev-badge.sev-warning {
  color: var(--color-warning-fg);
  background: var(--color-warning-soft);
}
.status-badge {
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
}
.integ-detail {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  word-break: break-word;
}
.integ-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.action-label {
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
}
.plan-section {
  border-top: 1px solid var(--color-border);
  padding-top: var(--space-3);
}
.plan-section h4 {
  margin: 0 0 var(--space-2);
  font-size: var(--text-sm);
}
.plan-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  font-size: var(--text-sm);
}
.plan-impact {
  margin: 2px 0 0;
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
}
</style>
