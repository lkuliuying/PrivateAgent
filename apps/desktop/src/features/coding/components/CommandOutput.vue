<script setup lang="ts">
/**
 * CommandOutput · v0.8.0 W3
 *
 * 命令执行输出（按需加载）：流式行（stdout/stderr 语义色）+ parsed 测试
 * 摘要（11 种冻结 parser 的统一字段：passed/failed/skipped/errors +
 * failures ≤50）。轮询与拉取在父层（工作区）发生，组件只呈现与发起
 * 「加载更多/继续跟随」意图（不阻塞主区：行数上限 + 独立滚动）。
 */
import { computed } from "vue";
import { PhTerminalWindow } from "@phosphor-icons/vue";
import type {
  RunExecutionOutputPage,
  RunExecutionRecord,
} from "../model/runContracts";

const props = withDefaults(
  defineProps<{
    execution: RunExecutionRecord;
    page: RunExecutionOutputPage | null;
    loading?: boolean;
  }>(),
  { loading: false }
);

const emit = defineEmits<{
  load: [];
}>();

const MAX_RENDER_LINES = 600;
const lines = computed(() => (props.page ? props.page.lines.slice(0, MAX_RENDER_LINES) : []));

interface ParsedSummary {
  parser: string;
  summary: string | null;
  passed: number | null;
  failed: number | null;
  skipped: number | null;
  errors: number | null;
  failures: string[];
  truncated: boolean | null;
}

const parsed = computed<ParsedSummary | null>(() => {
  const output = props.execution.output;
  if (!output || typeof output !== "object") return null;
  const raw = (output as { parsed?: unknown }).parsed;
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  return {
    parser: typeof record.parser === "string" ? record.parser : "",
    summary: typeof record.summary === "string" ? record.summary : null,
    passed: typeof record.passed === "number" ? record.passed : null,
    failed: typeof record.failed === "number" ? record.failed : null,
    skipped: typeof record.skipped === "number" ? record.skipped : null,
    errors: typeof record.errors === "number" ? record.errors : null,
    failures: Array.isArray(record.failures)
      ? record.failures.filter((item): item is string => typeof item === "string").slice(0, 10)
      : [],
    truncated: typeof record.truncated === "boolean" ? record.truncated : null,
  };
});

const hasFailures = computed(
  () => (parsed.value?.failed ?? 0) > 0 || (parsed.value?.errors ?? 0) > 0
);

function lineClass(kind: string): string {
  if (kind === "stderr" || kind === "error") return "line-err";
  if (kind === "stdout") return "line-out";
  return "line-meta";
}
</script>

<template>
  <div class="command-output" :data-testid="`command-output-${execution.id}`">
    <div class="output-head">
      <PhTerminalWindow :size="14" aria-hidden="true" />
      <span class="mono output-tool">{{ execution.tool_name }}</span>
      <span class="output-status" :class="{ failed: execution.status !== 'succeeded' }">
        {{ execution.status === "succeeded" ? "成功" : execution.status === "failed" ? "失败" : execution.status }}
      </span>
      <button
        v-if="!page && !loading"
        class="load-btn"
        data-testid="command-output-load"
        @click="emit('load')"
      >
        查看输出
      </button>
      <span v-else-if="loading" class="output-hint">加载中…</span>
    </div>

    <p v-if="execution.error_message" class="output-error">{{ execution.error_message }}</p>

    <template v-if="parsed">
      <div class="parsed-summary" :class="{ 'has-failures': hasFailures }" data-testid="command-parsed">
        <span class="parsed-parser mono">{{ parsed.parser }}</span>
        <span v-if="parsed.summary">{{ parsed.summary }}</span>
        <span v-if="parsed.passed !== null" class="stat pass">{{ parsed.passed }} 通过</span>
        <span v-if="parsed.failed !== null" class="stat fail">{{ parsed.failed }} 失败</span>
        <span v-if="parsed.skipped !== null" class="stat skip">{{ parsed.skipped }} 跳过</span>
        <span v-if="parsed.errors !== null" class="stat fail">{{ parsed.errors }} 错误</span>
      </div>
      <ul v-if="parsed.failures.length" class="parsed-failures">
        <li v-for="failure in parsed.failures" :key="failure" class="mono">{{ failure }}</li>
      </ul>
    </template>

    <pre v-if="page && lines.length" class="output-body" data-testid="command-output-body"><code
      ><span
        v-for="line in lines"
        :key="line.seq"
        class="output-line"
        :class="lineClass(line.kind)"
      >{{ line.text }}
</span></code></pre>
    <div v-else-if="page && !lines.length" class="output-empty">（无输出行）</div>

    <div v-if="page && !page.finished" class="output-hint">
      输出进行中…
      <button class="load-btn" data-testid="command-output-poll" @click="emit('load')">刷新</button>
    </div>
    <div v-if="page && page.lines.length > MAX_RENDER_LINES" class="output-truncated">
      输出过长，仅渲染前 {{ MAX_RENDER_LINES }} 行
    </div>
  </div>
</template>

<style scoped>
.command-output {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin-top: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.output-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg);
  font-size: var(--pa-text-meta);
}
.output-tool {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.output-status {
  padding: 1px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  color: var(--color-success-fg);
}
.output-status.failed {
  color: var(--color-danger-fg);
}
.load-btn {
  margin-left: auto;
  padding: 2px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.load-btn:hover {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.output-hint {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.output-error {
  margin: 0;
  color: var(--color-danger-fg);
  font-size: var(--pa-text-meta);
  word-break: break-word;
}
.parsed-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-success-soft);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.parsed-summary.has-failures {
  background: var(--color-danger-soft);
}
.parsed-parser {
  color: var(--color-fg);
}
.stat.pass { color: var(--color-success-fg); }
.stat.fail { color: var(--color-danger-fg); }
.stat.skip { color: var(--color-fg-muted); }
.parsed-failures {
  margin: 0;
  padding: 0 var(--space-2);
  list-style: none;
  color: var(--color-danger-fg);
  font-size: var(--pa-t-11);
}
.parsed-failures li {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.output-body {
  max-height: 280px;
  overflow: auto;
  margin: 0;
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
  font-size: var(--pa-text-meta);
  line-height: var(--leading-normal);
}
.output-line {
  display: block;
  white-space: pre-wrap;
  word-break: break-all;
}
.line-out { color: var(--color-fg); }
.line-err { color: var(--color-danger-fg); }
.line-meta { color: var(--color-fg-subtle); }
.output-empty {
  padding: var(--space-1) 0;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.output-truncated {
  padding-top: var(--space-1);
  border-top: 1px solid var(--color-border);
  color: var(--color-warning-fg);
  font-size: var(--pa-t-11);
}
</style>
