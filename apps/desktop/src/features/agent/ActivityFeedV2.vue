<script setup lang="ts">
/**
 * ActivityFeedV2 · 统一活动流（0.4.0 D3）
 * 消息类型与表达（docs/ui-state-matrix-0.4.0.md §6）：
 *   user 简洁任务输入 / agent 正文（流式光标、来源、记忆）/
 *   tool 动作摘要+折叠参数结果 / approval 审批卡 / error 原因·影响·恢复 /
 *   result 高层级结果块。
 * 每个条目携带 data-activity-idx 供计划步骤定位与自动跟随使用。
 */
import {
  PhArrowRight,
  PhBrain,
  PhCheckCircle,
  PhDatabase,
  PhTray,
  PhSparkle,
  PhUser,
  PhWarningCircle,
} from "@phosphor-icons/vue";
import type { AgentWorkspaceMessage } from "../../models/agentWorkspace";
import { formatActivityTime, toolLabel } from "../../models/agentWorkspace";
import type { AgentTaskState } from "../../types";
import ApprovalCardV2 from "./ApprovalCardV2.vue";
import PaBadge from "../../design/PaBadge.vue";
import PaDisclosure from "../../design/PaDisclosure.vue";
import PaSpinner from "../../design/PaSpinner.vue";

const props = withDefaults(
  defineProps<{
    messages: AgentWorkspaceMessage[];
    streaming: boolean;
    taskState?: AgentTaskState;
  }>(),
  { taskState: "idle" }
);

const emit = defineEmits<{
  "approve-tool": [id: number];
  "reject-tool": [id: number];
  "approve-agent": [runId: string, approvalId: string];
  "reject-agent": [runId: string, approvalId: string];
  "select-chunk": [chunkId: number];
  "save-inbox": [messageId: number, content: string];
  "use-prompt": [prompt: string];
}>();

const starterPrompts = [
  "整理今天最重要的三个任务",
  "分析一个项目目录并给出下一步",
  "结合知识库生成一份执行计划",
];

function isErrorContent(content: string): boolean {
  return content.includes("[错误：") || content.includes("[连接错误：");
}

function isStreamingMessage(index: number): boolean {
  return props.streaming && index === props.messages.length - 1;
}

function hasToolSettled(message: AgentWorkspaceMessage): boolean {
  const status = message.tool_call?.status;
  return Boolean(status && status !== "pending_approval");
}

function toolTone(status: string): "success" | "danger" | "info" | "neutral" {
  if (status === "succeeded" || status === "consumed") return "success";
  if (status === "failed") return "danger";
  if (status === "running" || status === "approved") return "info";
  return "neutral";
}

function toolStatusLabel(status: string): string {
  return (
    {
      approved: "准备执行",
      running: "执行中",
      succeeded: "已完成",
      failed: "失败",
      rejected: "已拒绝",
      cancelled: "已取消",
    }[status] ?? status
  );
}
</script>

<template>
  <section class="feed" aria-labelledby="feed-title">
    <div class="feed-heading">
      <div>
        <span class="feed-kicker">ACTIVITY</span>
        <h2 id="feed-title">任务活动</h2>
      </div>
      <span v-if="streaming" class="live-indicator">
        <span class="live-dot" />
        实时更新
      </span>
    </div>

    <div v-if="messages.length === 0" class="feed-empty" data-testid="feed-empty">
      <div class="empty-icon"><PhSparkle :size="24" /></div>
      <strong>描述一个目标，PrivateAgent 会从计划开始</strong>
      <p>执行过程、工具调用、授权请求和最终结果都会集中显示在这里。</p>
      <div class="starter-actions">
        <button
          v-for="prompt in starterPrompts"
          :key="prompt"
          @click="emit('use-prompt', prompt)"
        >
          <span>{{ prompt }}</span>
          <PhArrowRight :size="14" />
        </button>
      </div>
    </div>

    <div v-else class="feed-timeline">
      <article
        v-for="(message, index) in messages"
        :key="message.clientKey ?? message.id"
        :data-activity-idx="index"
        class="feed-item"
        :class="[
          message.tool_call || message.agent_approval
            ? 'is-tool'
            : `is-${message.role}`,
          { 'is-last': index === messages.length - 1 },
        ]"
        data-chat-message
      >
        <time :datetime="message.created_at">
          {{ formatActivityTime(message.created_at) }}
        </time>
        <div
          class="timeline-marker"
          :data-agent-state="
            message.role === 'assistant' && isStreamingMessage(index)
              ? 'thinking'
              : undefined
          "
        >
          <PhUser v-if="message.role === 'user'" :size="15" />
          <PhDatabase v-else-if="message.tool_call" :size="15" />
          <PhSparkle v-else :size="15" weight="fill" />
        </div>

        <div class="feed-content">
          <!-- 审批（Runtime / legacy 统一） -->
          <ApprovalCardV2
            v-if="message.agent_approval"
            :approval="message.agent_approval"
            @approve-agent="(runId, approvalId) => emit('approve-agent', runId, approvalId)"
            @reject-agent="(runId, approvalId) => emit('reject-agent', runId, approvalId)"
          />
          <ApprovalCardV2
            v-else-if="message.tool_call?.status === 'pending_approval'"
            :tool-call="message.tool_call"
            @approve-tool="(id) => emit('approve-tool', id)"
            @reject-tool="(id) => emit('reject-tool', id)"
          />

          <!-- 工具执行摘要（非待审批） -->
          <div v-else-if="message.tool_call && hasToolSettled(message)" class="tool-card">
            <div class="tool-head">
              <span
                class="tool-icon"
                :class="`tone-${toolTone(message.tool_call.status)}`"
              >
                <PhDatabase :size="15" />
              </span>
              <div class="tool-copy">
                <strong>{{ toolLabel(message.tool_call.tool_name) }}</strong>
                <span class="tool-scope">
                  {{
                    typeof message.tool_call.input_json?.path === "string"
                      ? message.tool_call.input_json.path
                      : message.tool_call.input_json?.command ?? ""
                  }}
                </span>
              </div>
              <PaBadge :tone="toolTone(message.tool_call.status)">
                <span class="tool-status">
                  <PaSpinner
                    v-if="message.tool_call.status === 'running'"
                    :size="10"
                    :label="toolStatusLabel(message.tool_call.status)"
                  />
                  {{ toolStatusLabel(message.tool_call.status) }}
                </span>
              </PaBadge>
            </div>
            <PaDisclosure title="查看参数与结果">
              <pre class="tool-json">{{
                JSON.stringify(message.tool_call.input_json, null, 2)
              }}</pre>
              <pre
                v-if="message.tool_call.output_json"
                class="tool-json is-output"
              >{{ JSON.stringify(message.tool_call.output_json, null, 2) }}</pre>
            </PaDisclosure>
          </div>

          <!-- 用户请求 -->
          <div v-else-if="message.role === 'user'" class="user-request">
            <div class="block-label">你的任务</div>
            <p>{{ message.content }}</p>
          </div>

          <!-- Agent 正文 / 错误 / 结果 -->
          <div
            v-else
            class="agent-block"
            :class="{
              'is-streaming': isStreamingMessage(index),
              'is-error': isErrorContent(message.content),
              'is-result': !isStreamingMessage(index) && message.content && !isErrorContent(message.content) && index === messages.length - 1,
            }"
          >
            <div class="agent-block-head">
              <div>
                <span class="agent-name">PrivateAgent</span>
                <span class="agent-role">本地智能体</span>
              </div>
              <span
                v-if="!isStreamingMessage(index) && message.content"
                class="response-state"
              >
                <PhCheckCircle :size="14" weight="fill" /> 已记录
              </span>
            </div>

            <template v-if="isErrorContent(message.content)">
              <PaBadge tone="danger">
                <PhWarningCircle :size="12" weight="fill" /> 执行遇到问题
              </PaBadge>
              <p class="agent-copy is-error-copy">{{ message.content }}</p>
            </template>

            <p v-else class="agent-copy">
              {{ message.content
              }}<span
                v-if="isStreamingMessage(index) && message.content"
                class="cursor"
              />
            </p>

            <div v-if="message.sources?.length" class="reference-row">
              <PhDatabase :size="14" />
              <span>引用资料</span>
              <button
                v-for="source in message.sources"
                :key="source.chunk_id"
                @click="emit('select-chunk', source.chunk_id)"
              >
                {{ source.doc_name }} · #{{ source.ordinal }}
              </button>
            </div>
            <div v-if="message.memories?.length" class="reference-row">
              <PhBrain :size="14" />
              <span>关联记忆</span>
              <span
                v-for="memory in message.memories"
                :key="memory.id"
                class="memory-chip"
                >{{ memory.title }}</span
              >
            </div>
            <button
              v-if="
                message.id > 0 &&
                message.content &&
                !isStreamingMessage(index)
              "
              class="save-action"
              @click="emit('save-inbox', message.id, message.content)"
            >
              <PhTray :size="14" /> 存为收件箱事项
            </button>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.feed {
  padding-bottom: var(--space-4);
}
.feed-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-3);
  margin: var(--space-5) 0 var(--space-3);
}
.feed-kicker {
  display: block;
  margin-bottom: 2px;
  color: var(--color-fg-muted);
  font-size: var(--pa-t-11);
  font-weight: var(--font-semibold);
  letter-spacing: 0.11em;
}
.feed-heading h2 {
  margin: 0;
  font-size: var(--pa-text-section);
}
.live-indicator {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-accent-soft-fg);
  font-size: var(--pa-text-meta);
}
.live-dot {
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  background: var(--color-accent);
  box-shadow: 0 0 0 0 var(--color-accent);
  animation: live-pulse 1.8s var(--ease) infinite;
}
@keyframes live-pulse {
  0% {
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--color-accent) 50%, transparent);
  }
  70% {
    box-shadow: 0 0 0 5px transparent;
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
  }
}
.feed-empty {
  display: flex;
  min-height: 300px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  padding: var(--space-8);
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--color-surface) 78%, transparent);
  text-align: center;
}
.empty-icon {
  display: grid;
  width: 46px;
  height: 46px;
  place-items: center;
  margin-bottom: var(--space-3);
  border-radius: 14px;
  background: var(--color-accent-soft);
  color: var(--color-accent);
}
.feed-empty strong {
  font-size: var(--pa-text-body);
}
.feed-empty p {
  max-width: 540px;
  margin: var(--space-2) 0 var(--space-5);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-compact);
  line-height: var(--leading-normal);
}
.starter-actions {
  display: grid;
  width: min(100%, 620px);
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-2);
}
.starter-actions button {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  text-align: left;
  cursor: pointer;
}
.starter-actions button:hover {
  border-color: color-mix(in srgb, var(--color-accent) 45%, var(--color-border));
  color: var(--color-accent-soft-fg);
}
.starter-actions button:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.feed-timeline {
  display: flex;
  flex-direction: column;
}
.feed-item {
  position: relative;
  display: grid;
  grid-template-columns: 54px 28px minmax(0, 1fr);
  gap: var(--space-2);
  padding: var(--space-2) 0 var(--space-4);
}
.feed-item::before {
  content: "";
  position: absolute;
  top: 31px;
  bottom: -2px;
  left: 67px;
  width: 1px;
  background: var(--color-border-strong);
}
.feed-item.is-last::before {
  display: none;
}
.feed-item time {
  padding-top: 7px;
  color: var(--color-fg-faint);
  font-size: var(--pa-t-11);
  font-variant-numeric: tabular-nums;
}
.timeline-marker {
  position: relative;
  z-index: 1;
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-full);
  background: var(--color-surface);
  color: var(--color-fg-subtle);
}
.is-assistant .timeline-marker {
  border-color: color-mix(in srgb, var(--color-accent) 30%, var(--color-border));
  background: var(--color-accent-soft);
  color: var(--color-accent);
}
.is-tool .timeline-marker {
  background: var(--color-rail-bg);
  color: var(--color-rail-fg-strong);
}
.feed-content {
  min-width: 0;
}
.block-label {
  margin-bottom: var(--space-1);
  color: var(--color-fg-faint);
  font-size: var(--pa-text-meta);
  font-weight: var(--font-semibold);
}
.user-request {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}
.user-request p {
  margin: 0;
  color: var(--color-fg);
  font-size: var(--pa-text-body);
  line-height: 1.62;
  white-space: pre-wrap;
  word-break: break-word;
}
.tool-card {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.tool-head {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
}
.tool-icon {
  display: grid;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  place-items: center;
  border-radius: var(--radius);
  background: var(--color-surface-sunken);
  color: var(--color-fg-subtle);
}
.tool-icon.tone-success {
  background: var(--color-success-soft);
  color: var(--color-success-fg);
}
.tool-icon.tone-danger {
  background: var(--color-danger-soft);
  color: var(--color-danger-fg);
}
.tool-icon.tone-info {
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
}
.tool-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 1px;
}
.tool-copy strong {
  font-size: var(--pa-text-compact);
}
.tool-scope {
  overflow: hidden;
  color: var(--color-fg-faint);
  font-family: var(--font-mono);
  font-size: var(--pa-t-12);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tool-status {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}
.tool-json {
  margin: var(--space-2) 0 0;
  max-height: 220px;
  overflow: auto;
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-surface-sunken);
  color: var(--color-fg-muted);
  font-family: var(--font-mono);
  font-size: var(--pa-t-12);
  line-height: 1.5;
  white-space: pre-wrap;
}
.tool-json.is-output {
  border-top: 1px solid var(--color-border);
  color: var(--color-fg);
}
.agent-block {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.agent-block.is-streaming {
  border-color: color-mix(in srgb, var(--color-accent) 35%, var(--color-border));
  box-shadow: inset 3px 0 0 var(--color-accent);
}
.agent-block.is-result {
  border-color: color-mix(in srgb, var(--color-success) 30%, var(--color-border));
}
.agent-block.is-error {
  border-color: color-mix(in srgb, var(--color-danger) 30%, var(--color-border));
  background: var(--color-danger-soft);
}
.agent-block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}
.agent-name {
  font-size: var(--pa-text-compact);
  font-weight: var(--font-semibold);
}
.agent-role {
  margin-left: var(--space-2);
  color: var(--color-fg-faint);
  font-size: var(--pa-t-11);
}
.response-state {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--color-success-fg);
  font-size: var(--pa-t-11);
}
.agent-copy {
  margin: var(--space-2) 0 0;
  font-size: var(--pa-text-body);
  line-height: 1.62;
  white-space: pre-wrap;
  word-break: break-word;
}
.is-error-copy {
  color: var(--color-danger-fg);
}
.cursor {
  display: inline-block;
  width: 6px;
  height: 13px;
  margin-left: 3px;
  background: var(--color-accent);
  animation: activity-blink 1s steps(2) infinite;
  vertical-align: -2px;
}
@keyframes activity-blink {
  50% {
    opacity: 0;
  }
}
.reference-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
  margin-top: var(--space-3);
  color: var(--color-fg-faint);
  font-size: var(--pa-text-meta);
}
.reference-row button,
.memory-chip {
  padding: 3px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-surface-sunken);
  color: var(--color-accent-soft-fg);
  font-size: var(--pa-t-11);
}
.reference-row button {
  cursor: pointer;
}
.reference-row button:hover {
  border-color: var(--color-accent);
}
.save-action {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  margin-top: var(--space-3);
  padding: 0;
  border: none;
  background: transparent;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.save-action:hover {
  color: var(--color-accent);
}
.save-action:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
@media (max-width: 780px) {
  .feed-item {
    grid-template-columns: 28px minmax(0, 1fr);
  }
  .feed-item time {
    display: none;
  }
  .feed-item::before {
    left: 13px;
  }
  .starter-actions {
    grid-template-columns: 1fr;
  }
}
@media (prefers-reduced-motion: reduce) {
  .cursor,
  .live-dot {
    animation: none;
  }
}
</style>
