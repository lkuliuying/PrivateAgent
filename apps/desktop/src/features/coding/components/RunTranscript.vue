<script setup lang="ts">
/**
 * RunTranscript · v0.8.0 W2
 *
 * 文档式活动流：用户请求 → 运行/上下文 → 模型轮次 → 计划摘要 → 工具卡 →
 * 审批卡 → 验证 → 变更集/产出 → 终态摘要（含最终输出，pre-wrap 纯文本，
 * 与现行消息渲染一致；Markdown 渲染不在 W2 范围）。
 * 工具活动默认摘要折叠；新活动自动跟随（离开底部时出现「查看新活动」）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  PhArrowCircleDown,
  PhCheckCircle,
  PhCircleNotch,
  PhClipboardText,
  PhClock,
  PhFilePlus,
  PhGitDiff,
  PhLightning,
  PhProhibit,
  PhShieldWarning,
  PhUser,
  PhWarningCircle,
} from "@phosphor-icons/vue";
import type { TranscriptEntry, RunProjection } from "../model/runProjector";
import type {
  RunApprovalPreviewRecord,
  RunApprovalRecord,
  RunConnectionPhase,
  RunExecutionOutputPage,
  RunExecutionRecord,
} from "../model/runContracts";
import { RUN_STATUS_META } from "../model/runContracts";
import DiffArtifact from "./DiffArtifact.vue";
import CommandOutput from "./CommandOutput.vue";

const props = withDefaults(
  defineProps<{
    projection: RunProjection | null;
    phase?: RunConnectionPhase;
    connectionError?: string | null;
    approvals?: RunApprovalRecord[];
    /** W3：审批影响范围预览（父层按需加载；键为 approvalId） */
    approvalPreviews?: Record<string, RunApprovalPreviewRecord | null>;
    previewLoading?: string[];
    /** W3：工具执行结果（键为 toolCallId，按工具名+完成顺序关联） */
    executionByTool?: Record<string, RunExecutionRecord>;
    /** W3：流式输出页（键为 executionId） */
    outputPages?: Record<string, RunExecutionOutputPage | null>;
    outputLoading?: string[];
    previewMode?: boolean;
  }>(),
  {
    phase: "idle" as RunConnectionPhase,
    connectionError: null,
    approvals: () => [],
    approvalPreviews: () => ({}),
    previewLoading: () => [],
    executionByTool: () => ({}),
    outputPages: () => ({}),
    outputLoading: () => [],
    previewMode: false,
  }
);

const emit = defineEmits<{
  approve: [approvalId: string];
  reject: [approvalId: string];
  "open-plan": [];
  "retry-stream": [];
  "load-output": [executionId: string];
}>();

const TOOL_STATE_LABEL: Record<string, { label: string; tone: string }> = {
  requested: { label: "已请求", tone: "neutral" },
  started: { label: "执行中", tone: "info" },
  approval_required: { label: "等待审批", tone: "warning" },
  completed: { label: "已完成", tone: "success" },
  failed: { label: "失败", tone: "danger" },
};

const PATCH_STATE_LABEL: Record<string, { label: string; tone: string }> = {
  previewed: { label: "已预览", tone: "info" },
  applied: { label: "已应用", tone: "success" },
  rolled_back: { label: "已回滚", tone: "neutral" },
  failed: { label: "应用失败", tone: "danger" },
  unknown: { label: "状态未知（人工处置）", tone: "warning" },
};

const entries = computed(() => props.projection?.entries ?? []);
const entryCount = computed(() => entries.value.length);
const pendingApprovals = computed(() => props.approvals.filter((item) => item.status === "pending"));

// 长列表分段渲染（计划 §6.4：窗口化/分段，W5 5,000 条压力前提）：
// 默认仅渲染最近 RENDER_BATCH 条，「显示更早」按批次扩展；切换 run 重置。
const RENDER_BATCH = 200;
const visibleCount = ref(RENDER_BATCH);
const visibleEntries = computed(() =>
  entries.value.slice(Math.max(0, entries.value.length - visibleCount.value))
);
const hiddenCount = computed(() => entries.value.length - visibleEntries.value.length);

function loadEarlier(): void {
  visibleCount.value += RENDER_BATCH * 5;
}

watch(
  () => props.projection?.runId,
  () => {
    visibleCount.value = RENDER_BATCH;
  }
);

const scrollEl = ref<HTMLElement | null>(null);
const anchoredBottom = ref(true);
const newActivity = ref(false);

function onScroll(): void {
  const el = scrollEl.value;
  if (!el) return;
  anchoredBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  if (anchoredBottom.value) newActivity.value = false;
}

async function scrollToBottom(): Promise<void> {
  const el = scrollEl.value;
  if (!el) return;
  // jsdom 无滚动实现：可选调用，锚定状态由逻辑保证
  el.scrollTo?.({ top: el.scrollHeight });
  anchoredBottom.value = true;
  newActivity.value = false;
}

watch(entryCount, async () => {
  if (anchoredBottom.value) {
    await nextTick();
    void scrollToBottom();
  } else {
    newActivity.value = true;
  }
});

onMounted(() => void scrollToBottom());
onBeforeUnmount(() => {
  // 无定时器/监听器需要拆除（scroll 绑定随 DOM 卸载）
});

function approvalById(approvalId: string): RunApprovalRecord | undefined {
  return props.approvals.find((item) => item.id === approvalId);
}

function riskLabel(risk: string): string {
  return risk === "safe" ? "低风险" : risk === "confirm" ? "需确认" : risk === "restricted" ? "受限" : risk;
}

function toolEntryClass(entry: Extract<TranscriptEntry, { kind: "tool" }>): string {
  return `tone-${TOOL_STATE_LABEL[entry.state]?.tone ?? "neutral"}`;
}

function terminalMeta(): { label: string; tone: string } | null {
  const status = props.projection?.status;
  if (!status) return null;
  const meta = RUN_STATUS_META[status];
  return { label: meta.label, tone: meta.tone };
}
</script>

<template>
  <div class="run-transcript" data-testid="run-transcript">
    <div ref="scrollEl" class="transcript-scroll" @scroll.passive="onScroll">
      <!-- 未开始任务 -->
      <div v-if="!projection" class="transcript-empty" data-testid="transcript-empty">
        <PhLightning :size="26" weight="duotone" />
        <p>还没有开始任务</p>
        <p class="hint">在下方输入要执行的内容；执行计划、工具与审批都会在这里展示。</p>
      </div>

      <template v-else>
        <!-- 用户请求 -->
        <div v-if="projection.userMessage" class="user-bubble" data-testid="transcript-user-message">
          <div class="user-avatar"><PhUser :size="14" weight="fill" aria-hidden="true" /></div>
          <div class="user-copy">{{ projection.userMessage }}</div>
        </div>

        <button
          v-if="hiddenCount > 0"
          class="load-earlier"
          data-testid="transcript-load-earlier"
          @click="loadEarlier"
        >
          显示更早的活动（{{ hiddenCount.toLocaleString() }} 条）
        </button>

        <div
          v-for="entry in visibleEntries"
          :key="entry.key"
          class="entry"
          :class="`entry-${entry.kind}`"
          :data-testid="`transcript-${entry.kind}`"
        >
          <!-- 运行开始 -->
          <template v-if="entry.kind === 'run-start'">
            <PhCircleNotch :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">
              任务开始 · 最多 {{ entry.maxSteps }} 步 / {{ entry.maxToolCalls }} 次工具<template v-if="entry.maxWallTimeSeconds !== null"> / {{ Math.round(entry.maxWallTimeSeconds) }}s</template>
            </span>
          </template>

          <!-- 上下文就绪 -->
          <template v-else-if="entry.kind === 'context'">
            <PhClipboardText :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">
              上下文就绪 · 约 {{ entry.estimatedTokens.toLocaleString() }} tokens<template v-if="entry.truncated">（已截断）</template>
            </span>
          </template>

          <!-- 模型轮次（摘要折叠） -->
          <template v-else-if="entry.kind === 'model-turn'">
            <PhLightning :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">
              模型第 {{ entry.ordinal }} 轮
              <template v-if="entry.state === 'completed'">
                · {{ entry.outputTokens.toLocaleString() }} 输出 tokens<template v-if="entry.latencyMs !== null"> · {{ Math.round(entry.latencyMs) }}ms</template>
              </template>
              <template v-else> · 生成中</template>
            </span>
          </template>

          <!-- 计划摘要 -->
          <button
            v-else-if="entry.kind === 'plan'"
            class="entry plan-entry"
            data-testid="transcript-plan-note"
            @click="emit('open-plan')"
          >
            <PhClipboardText :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">
              {{ entry.note === "created" ? "执行计划已建立" : "执行计划已更新" }} · v{{ entry.version }} · {{ entry.itemCount }} 项 · 点击查看
            </span>
          </button>

          <!-- 工具卡（摘要行 + W3 执行输出按需加载） -->
          <template v-else-if="entry.kind === 'tool'">
            <span class="entry-icon" :class="toolEntryClass(entry)" aria-hidden="true">●</span>
            <span class="entry-copy mono">{{ entry.name }}</span>
            <span class="entry-state" :class="toolEntryClass(entry)">
              <PhCircleNotch v-if="entry.state === 'started' || entry.state === 'requested'" :size="12" class="spin" />
              {{ TOOL_STATE_LABEL[entry.state]?.label ?? entry.state }}
            </span>
            <span v-if="entry.errorMessage" class="entry-error" :title="entry.errorMessage">
              {{ entry.errorType || "错误" }}：{{ entry.errorMessage }}
            </span>
            <CommandOutput
              v-if="executionByTool[entry.toolCallId]"
              :execution="executionByTool[entry.toolCallId]"
              :page="outputPages[executionByTool[entry.toolCallId].id] ?? null"
              :loading="outputLoading.includes(executionByTool[entry.toolCallId].id)"
              class="entry-execution"
              @load="emit('load-output', executionByTool[entry.toolCallId].id)"
            />
          </template>

          <!-- 审批卡 -->
          <div v-else-if="entry.kind === 'approval'" class="approval-card" data-testid="approval-card">
            <div class="approval-head">
              <PhShieldWarning :size="16" class="approval-icon" aria-hidden="true" />
              <strong>授权请求</strong>
              <span class="mono approval-tool">{{ approvalById(entry.approvalId)?.tool_name ?? entry.toolName }}</span>
            </div>
            <div v-if="approvalById(entry.approvalId)" class="approval-meta">
              <span class="risk" :class="`risk-${approvalById(entry.approvalId)!.risk_level}`">
                {{ riskLabel(approvalById(entry.approvalId)!.risk_level) }}
              </span>
              <span>能力：{{ approvalById(entry.approvalId)!.required_capabilities.join("、") || "—" }}</span>
              <span class="mono">{{ approvalById(entry.approvalId)!.tool_version }}</span>
            </div>
            <div v-if="entry.resolved || approvalById(entry.approvalId)?.status !== 'pending'" class="approval-resolved">
              已处理（{{ approvalById(entry.approvalId)?.status ?? "resolved" }}）
            </div>
            <DiffArtifact
              v-if="approvalPreviews[entry.approvalId] !== undefined || previewLoading.includes(entry.approvalId)"
              :preview="approvalPreviews[entry.approvalId] ?? null"
              :loading="previewLoading.includes(entry.approvalId)"
            />
            <div
              v-if="!entry.resolved && approvalById(entry.approvalId)?.status === 'pending'"
              class="approval-actions"
            >
              <button class="pa-btn pa-btn--primary" :data-testid="`approval-approve-${entry.approvalId}`" @click="emit('approve', entry.approvalId)">
                批准执行
              </button>
              <button class="pa-btn pa-btn--ghost" :data-testid="`approval-reject-${entry.approvalId}`" @click="emit('reject', entry.approvalId)">
                拒绝
              </button>
            </div>
          </div>

          <!-- 输出校验 -->
          <template v-else-if="entry.kind === 'verification'">
            <PhCheckCircle
              :size="14"
              class="entry-icon"
              :class="`tone-${entry.state === 'passed' ? 'success' : entry.state === 'failed' ? 'danger' : 'info'}`"
              aria-hidden="true"
            />
            <span class="entry-copy">
              输出校验 · {{ entry.verifier }} · 第 {{ entry.attempt }} 次 · {{ entry.state === "started" ? "进行中" : entry.state === "passed" ? "通过" : entry.willRetry ? "未通过（将重试）" : "未通过" }}
              <template v-if="entry.message"> · {{ entry.message }}</template>
            </span>
          </template>

          <!-- 变更集（W2 摘要，W3 扩展 Diff） -->
          <template v-else-if="entry.kind === 'patch-set'">
            <PhGitDiff :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">
              变更集 · {{ PATCH_STATE_LABEL[entry.state]?.label ?? entry.state }}
              <template v-if="entry.fileCount !== null"> · {{ entry.fileCount }} 个文件</template>
              <template v-if="entry.verified === true"> · 已验证</template>
              <template v-if="entry.reason"> · {{ entry.reason }}</template>
            </span>
          </template>

          <!-- 产出（W2 摘要，W3 按需加载内容） -->
          <template v-else-if="entry.kind === 'artifact'">
            <PhFilePlus :size="14" class="entry-icon" aria-hidden="true" />
            <span class="entry-copy">产出 · {{ entry.artifactKind }} · {{ entry.title }}</span>
          </template>

          <!-- 终态摘要 -->
          <div v-else-if="entry.kind === 'terminal'" class="terminal-card" :data-testid="'terminal-summary'" :class="`tone-${terminalMeta()?.tone}`">
            <div class="terminal-head">
              <PhCheckCircle v-if="entry.status === 'completed'" :size="16" weight="fill" aria-hidden="true" />
              <PhWarningCircle v-else-if="entry.status === 'failed' || entry.status === 'timed_out'" :size="16" aria-hidden="true" />
              <PhProhibit v-else :size="16" aria-hidden="true" />
              <strong>{{ terminalMeta()?.label }}</strong>
              <span v-if="entry.errorCode" class="mono terminal-code">{{ entry.errorCode }}</span>
              <span class="terminal-usage">
                {{ projection.usage.toolCallCount }} 次工具 · {{ projection.usage.outputTokens.toLocaleString() }} 输出 tokens
              </span>
            </div>
            <pre
              v-if="entry.output || projection.output"
              class="terminal-output"
              data-testid="terminal-output"
            >{{ entry.output ?? projection.output }}</pre>
          </div>
        </div>

        <!-- 断线重连提示 -->
        <div v-if="phase === 'reconnecting' || connectionError" class="stream-notice" data-testid="stream-reconnect-notice">
          <PhClock :size="14" aria-hidden="true" />
          <span>连接中断，正在重连…（任务在本地继续执行，已完成步骤不会丢失）</span>
          <button class="notice-btn" @click="emit('retry-stream')">立即重试</button>
        </div>
        <div v-else-if="phase === 'streaming'" class="stream-live" data-testid="stream-live">
          <PhCircleNotch :size="12" class="spin" aria-hidden="true" />
          <span>实时更新中</span>
        </div>

        <!-- 静态预览标记 -->
        <div v-if="previewMode" class="preview-tag">RUN PREVIEW</div>
      </template>
    </div>

    <Transition name="pa-zone">
      <button
        v-if="newActivity"
        class="follow-pill"
        data-testid="new-activity-pill"
        @click="scrollToBottom"
      >
        <PhArrowCircleDown :size="14" />
        查看新活动
      </button>
    </Transition>

    <span
      v-if="pendingApprovals.length > 0"
      class="sr-only"
      role="status"
    >有 {{ pendingApprovals.length }} 个待审批请求</span>
  </div>
</template>

<style scoped>
.run-transcript {
  position: relative;
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}
.transcript-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-5) var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.transcript-empty {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: var(--space-2);
  color: var(--color-fg-subtle);
  text-align: center;
}
.transcript-empty p {
  margin: 0;
  color: var(--color-fg-subtle);
  font-size: var(--text-sm);
}
.transcript-empty .hint {
  max-width: 420px;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}

.user-bubble {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.user-avatar {
  order: 2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: var(--radius-full);
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
}
.user-copy {
  max-width: 76%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  color: var(--color-fg);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  white-space: pre-wrap;
  word-break: break-word;
}

.load-earlier {
  align-self: center;
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.load-earlier:hover {
  color: var(--color-fg);
}

.entry {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  min-height: 28px;
  padding: var(--space-1) var(--space-2);
  border-left: 2px solid transparent;
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
}
.entry-icon {
  flex-shrink: 0;
  color: var(--color-fg-subtle);
}
.entry-icon.tone-info { color: var(--color-accent); }
.entry-icon.tone-success { color: var(--color-success); }
.entry-icon.tone-warning { color: var(--color-warning); }
.entry-icon.tone-danger { color: var(--color-danger); }
.entry-copy {
  min-width: 0;
}
.entry-state {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  font-size: var(--pa-text-meta);
}
.entry-state.tone-info { color: var(--color-accent-soft-fg); }
.entry-state.tone-success { color: var(--color-success-fg); }
.entry-state.tone-warning { color: var(--color-warning-fg); }
.entry-state.tone-danger { color: var(--color-danger-fg); }
.entry-error {
  flex-basis: 100%;
  color: var(--color-danger-fg);
  font-size: var(--pa-text-meta);
  word-break: break-word;
}
.entry-execution {
  flex-basis: 100%;
}
.plan-entry {
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.plan-entry:hover {
  color: var(--color-accent-soft-fg);
}
.mono {
  font-family: var(--font-mono, monospace);
}

.approval-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: var(--space-2) 0;
  padding: var(--space-3);
  border: 1px solid color-mix(in srgb, var(--color-warning) 40%, var(--color-border));
  border-radius: var(--radius-lg);
  background: var(--color-warning-soft);
}
.approval-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg);
  font-size: var(--text-sm);
}
.approval-icon {
  color: var(--color-warning-fg);
}
.approval-tool {
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.approval-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}
.risk {
  padding: 1px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-surface);
}
.risk-safe { color: var(--color-success-fg); }
.risk-confirm { color: var(--color-warning-fg); }
.risk-restricted { color: var(--color-danger-fg); }
.approval-actions {
  display: flex;
  gap: var(--space-2);
}
.approval-resolved {
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
}

.terminal-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}
.terminal-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-fg);
  font-size: var(--text-sm);
}
.terminal-card.tone-success .terminal-head svg { color: var(--color-success); }
.terminal-card.tone-danger .terminal-head svg { color: var(--color-danger); }
.terminal-card.tone-warning .terminal-head svg { color: var(--color-warning); }
.terminal-code {
  color: var(--color-danger-fg);
  font-size: var(--pa-text-meta);
}
.terminal-usage {
  margin-left: auto;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.terminal-output {
  max-height: 420px;
  overflow-y: auto;
  margin: 0;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-fg);
  font-size: var(--text-sm);
  font-family: inherit;
  line-height: var(--leading-normal);
  white-space: pre-wrap;
  word-break: break-word;
}

.stream-notice {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid color-mix(in srgb, var(--color-warning) 36%, var(--color-border));
  border-radius: var(--radius-md);
  background: var(--color-warning-soft);
  color: var(--color-warning-fg);
  font-size: var(--pa-text-meta);
}
.notice-btn {
  margin-left: auto;
  padding: 2px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.stream-live {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.preview-tag {
  align-self: flex-start;
  padding: 2px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  color: var(--color-fg-subtle);
  font-size: var(--pa-t-11);
  letter-spacing: 0.1em;
}

.follow-pill {
  position: absolute;
  bottom: var(--space-3);
  left: 50%;
  transform: translateX(-50%);
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-surface);
  box-shadow: var(--shadow-md);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
.spin {
  animation: transcript-spin 0.9s linear infinite;
}
@keyframes transcript-spin {
  to { transform: rotate(360deg); }
}
@media (prefers-reduced-motion: reduce) {
  .spin { animation: none; }
}
</style>
