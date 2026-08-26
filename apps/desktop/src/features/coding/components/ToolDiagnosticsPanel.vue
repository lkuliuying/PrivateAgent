<script setup lang="ts">
/**
 * CT-9 · 工具快照诊断面板（消费 GET /agent-runs/tool-diagnostics）。
 *
 * 回答"本轮模型究竟会看到什么工具、为什么"：
 *  - direct / deferred / hidden 计数与四组规范化 hash；
 *  - 每个工具的暴露状态与隐藏原因（稳定枚举 → 中文标签）；
 *  - 脱敏视图：不含 schema 全文/描述正文/参数/secret。
 */
import { computed, onMounted, ref } from "vue";
import {
  fetchToolDiagnostics,
  hiddenReasonLabel,
  parseExposure,
  type ToolDiagnosticsSnapshot,
} from "../api/toolDiagnostics";

const props = defineProps<{
  /** 初始意图 tag（逗号分隔字符串，如 "file.mutate,code.inspect"）。 */
  initialTags?: string;
}>();

const snapshot = ref<ToolDiagnosticsSnapshot | null>(null);
const loading = ref(false);
/** 404 = 端点未启用；其余为一般错误。 */
const notEnabled = ref(false);
const errorText = ref("");
const tagsInput = ref(props.initialTags ?? "");

async function load() {
  loading.value = true;
  notEnabled.value = false;
  errorText.value = "";
  try {
    const tags = tagsInput.value
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    snapshot.value = await fetchToolDiagnostics(tags);
  } catch (err) {
    const status = (err as { status?: number }).status;
    if (status === 404) {
      notEnabled.value = true;
    } else {
      errorText.value =
        (err as { message?: string }).message ?? "诊断数据加载失败";
    }
    snapshot.value = null;
  } finally {
    loading.value = false;
  }
}

onMounted(load);

const rows = computed(() => {
  if (!snapshot.value) return [];
  return snapshot.value.tools.map((tool) => ({
    ...tool,
    parsed: parseExposure(tool.exposure),
    reasonLabel: hiddenReasonLabel(parseExposure(tool.exposure).reason),
  }));
});

function shortHash(hash: string): string {
  return hash.length > 16 ? `${hash.slice(0, 16)}…` : hash;
}
</script>

<template>
  <div class="tool-diagnostics" data-testid="tool-diagnostics-panel">
    <div class="toolbar">
      <input
        v-model="tagsInput"
        class="tags-input"
        data-testid="tags-input"
        placeholder="intent_tags（逗号分隔，如 file.mutate,code.inspect）"
        @keydown.enter="load"
      />
      <button class="apply" data-testid="apply-tags" @click="load">查询</button>
      <button class="reload" data-testid="reload" :disabled="loading" @click="load">
        {{ loading ? "加载中…" : "刷新" }}
      </button>
    </div>

    <p v-if="notEnabled" class="notice" data-testid="endpoint-disabled">
      工具快照诊断未启用：需设置 PA_AGENT_V2_TOOL_SNAPSHOT_ENABLED=1 并开启
      Agent Runs API 后重启应用。
    </p>
    <p v-else-if="errorText" class="notice error" data-testid="load-error">
      {{ errorText }}
    </p>
    <p v-else-if="loading && !snapshot" class="notice" data-testid="loading">
      正在加载工具快照…
    </p>

    <template v-if="snapshot">
      <div class="counts" data-testid="counts">
        <span data-testid="count-direct">直接可见 {{ snapshot.direct_total }}</span>
        <span data-testid="count-deferred">延迟检索 {{ snapshot.deferred_total }}</span>
        <span data-testid="count-hidden">隐藏 {{ snapshot.hidden_total }}</span>
      </div>

      <dl class="hashes" data-testid="hashes">
        <div><dt>catalog</dt><dd :title="snapshot.catalog_hash">{{ shortHash(snapshot.catalog_hash) }}</dd></div>
        <div><dt>visible</dt><dd :title="snapshot.visible_hash">{{ shortHash(snapshot.visible_hash) }}</dd></div>
        <div><dt>model</dt><dd :title="snapshot.model_profile_hash">{{ shortHash(snapshot.model_profile_hash) }}</dd></div>
        <div><dt>policy</dt><dd :title="snapshot.policy_hash">{{ shortHash(snapshot.policy_hash) }}</dd></div>
      </dl>

      <p class="redaction-note" data-testid="redaction-note">
        脱敏视图：仅含暴露状态与原因，不含 Schema 全文、参数与秘密。
      </p>

      <table v-if="rows.length" class="tools" data-testid="tools-table">
        <thead>
          <tr>
            <th>工具</th><th>版本</th><th>暴露</th><th>原因</th>
            <th>风险</th><th>审批</th><th>副作用</th><th>执行器</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.canonical_name" :data-testid="`tool-row-${row.canonical_name}`">
            <td>{{ row.canonical_name }}</td>
            <td>{{ row.version }}</td>
            <td>
              <span :class="['badge', `badge-${row.parsed.state}`]" :data-testid="`exposure-${row.canonical_name}`">
                {{ row.parsed.state }}
              </span>
            </td>
            <td>{{ row.reasonLabel || "—" }}</td>
            <td>{{ row.risk_level }}</td>
            <td>{{ row.approval_mode }}</td>
            <td>{{ row.side_effect_class }}</td>
            <td>{{ row.executor_kind }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="notice" data-testid="empty-tools">本轮无已注册工具。</p>
    </template>
  </div>
</template>

<style scoped>
.tool-diagnostics { display: grid; gap: var(--space-3, 12px); font-size: 13px; }
.toolbar { display: flex; gap: 8px; }
.tags-input { flex: 1; min-width: 240px; padding: 6px 8px; }
.notice { color: var(--text-secondary, #666); margin: 0; }
.notice.error { color: var(--danger, #c0392b); }
.counts { display: flex; gap: 16px; font-weight: 600; }
.hashes { display: flex; flex-wrap: wrap; gap: 8px 24px; margin: 0; }
.hashes div { display: flex; gap: 6px; align-items: baseline; }
.hashes dt { color: var(--text-secondary, #888); font-size: 11px; text-transform: uppercase; }
.hashes dd { margin: 0; font-family: monospace; }
.redaction-note { color: var(--text-secondary, #888); font-size: 11px; margin: 0; }
.tools { width: 100%; border-collapse: collapse; }
.tools th, .tools td { border-bottom: 1px solid var(--border, #ddd); padding: 4px 8px; text-align: left; }
.tools th { font-weight: 600; color: var(--text-secondary, #666); }
.badge { padding: 1px 8px; border-radius: 999px; font-size: 11px; }
.badge-direct { background: var(--success-bg, #e6f6ec); color: var(--success, #1a7f37); }
.badge-deferred { background: var(--info-bg, #e8f1fb); color: var(--info, #1c5fa8); }
.badge-hidden { background: var(--muted-bg, #eee); color: var(--text-secondary, #666); }
</style>
