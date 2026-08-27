<script setup lang="ts">
/**
 * CommandOutput · v0.8.0 W3（W6-R 增强）
 *
 * 命令执行卡（计划 §4.3/§6.6）：默认展示脱敏后的命令文本、运行状态与
 * 工作目录范围；展开后持续更新 stdout/stderr 流、退出码、耗时与 parsed
 * 测试摘要（11 种冻结 parser 的统一字段：passed/failed/skipped/errors +
 * failures ≤50）。轮询与拉取在父层（工作区）发生，组件只呈现与发起
 * 「加载更多/继续跟随」意图（不阻塞主区：行数上限 + 独立滚动）。
 * 命令文本经呈现层脱敏（redactCommandArgs）；流式行由后端持久化前脱敏。
 */
import { computed, ref } from "vue";
import { PhTerminalWindow } from "@phosphor-icons/vue";
import type {
  RunExecutionOutputPage,
  RunExecutionRecord,
} from "../model/runContracts";
import { redactCommandArgs, redactSecretText } from "../model/redaction";

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

// 后端持久化的命令事实（已脱敏/限长）：args/cwd/returncode 来自
// run_whitelisted_command 的 output_json（公开事实，不由前端猜测）。
const outputFacts = computed(() => {
  const output = props.execution.output;
  if (!output || typeof output !== "object") return null;
  const record = output as Record<string, unknown>;
  const rawExit = record.returncode ?? record.exit_code;
  return {
    args: Array.isArray(record.args)
      ? record.args.filter((item): item is string => typeof item === "string")
      : null,
    cwd: typeof record.cwd === "string" ? record.cwd : null,
    returncode: typeof rawExit === "number" ? rawExit : null,
    truncated: record.truncated === true,
  };
});

/** 脱敏后的实际命令文本（§6.6：命令卡默认展示） */
const commandText = computed(() => {
  const facts = outputFacts.value;
  if (!facts?.args?.length) return null;
  return redactCommandArgs(facts.args);
});

/** 工作目录范围：展示用户授权的项目根路径（公开事实） */
const cwdLabel = computed(() => outputFacts.value?.cwd ?? null);

const exitCode = computed(() => outputFacts.value?.returncode ?? null);

/** 耗时：执行记录 created_at → completed_at（durable 事实） */
const durationLabel = computed(() => {
  const started = props.execution.created_at;
  const ended = props.execution.completed_at;
  if (!started || !ended) return null;
  const start = new Date(started).getTime();
  const end = new Date(ended).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return null;
  const ms = end - start;
  if (ms < 1000) return `${ms}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
});

const detailOpen = ref(false);
function toggleDetail(): void {
  detailOpen.value = !detailOpen.value;
  if (detailOpen.value && !props.page && !props.loading) emit("load");
}

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

function redactLine(text: string): string {
  // 后端持久化前已脱敏；呈现层同语义再过一次（纵深防御，幂等）
  return redactSecretText(text);
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
      <span
        v-if="exitCode !== null"
        class="output-fact"
        :class="{ bad: exitCode !== 0 }"
        data-testid="command-exit-code"
      >退出码 {{ exitCode }}</span>
      <span v-if="durationLabel" class="output-fact" data-testid="command-duration">耗时 {{ durationLabel }}</span>
      <span
        v-if="parsed?.summary"
        class="output-summary"
        data-testid="command-parsed-summary"
        :title="parsed.summary"
      >{{ parsed.summary }}</span>
      <span v-if="page && !page.finished" class="output-hint">输出进行中…</span>
      <button
        class="load-btn"
        data-testid="command-output-toggle"
        :aria-expanded="detailOpen"
        @click="toggleDetail"
      >
        {{ detailOpen ? "收起" : "详情" }}
      </button>
    </div>

    <div v-if="detailOpen" class="output-detail" data-testid="command-output-detail">
      <!-- W6-R：命令、目录、测试统计和 stdout/stderr 只在用户展开时呈现，
           避免每次工具调用都把活动流撑成大卡片。 -->
      <code v-if="commandText" class="command-line mono" data-testid="command-line">$ {{ commandText }}</code>
      <div v-if="cwdLabel" class="command-cwd" data-testid="command-cwd" :title="cwdLabel">
        工作目录：{{ cwdLabel }}
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

      <span v-if="loading" class="output-hint">加载中…</span>
      <pre v-else-if="page && lines.length" class="output-body" data-testid="command-output-body"><code
        ><span
          v-for="line in lines"
          :key="line.seq"
          class="output-line"
          :class="lineClass(line.kind)"
        >{{ redactLine(line.text) }}
</span></code></pre>
      <div v-else-if="page && !lines.length" class="output-empty">（无输出行）</div>

      <div v-if="page && !page.finished" class="output-hint">
        输出进行中…
        <button class="refresh-btn" data-testid="command-output-poll" @click="emit('load')">刷新</button>
      </div>
      <div v-if="page && page.lines.length > MAX_RENDER_LINES" class="output-truncated">
        输出过长，仅渲染前 {{ MAX_RENDER_LINES }} 行
      </div>
    </div>
  </div>
</template>

<style scoped>
.command-output {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 2px;
  padding: 3px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.output-head {
  display: flex;
  min-width: 0;
  min-height: 24px;
  align-items: center;
  gap: var(--space-1);
  color: var(--color-fg);
  font-size: var(--pa-text-meta);
}
.output-fact {
  flex-shrink: 0;
  padding: 0 var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  color: var(--color-fg-subtle);
}
.output-fact.bad {
  color: var(--color-danger-fg);
}
.command-line {
  display: block;
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
  color: var(--color-fg);
  font-size: var(--pa-text-meta);
  line-height: var(--leading-normal);
  white-space: pre-wrap;
  word-break: break-all;
}
.output-detail {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-1) 0;
}
.command-cwd {
  overflow: hidden;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.output-tool {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.output-summary {
  overflow: hidden;
  min-width: 0;
  max-width: 360px;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
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
  flex-shrink: 0;
  padding: 1px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.refresh-btn {
  padding: 1px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  font-size: inherit;
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
