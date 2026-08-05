<script setup lang="ts">
import {
  PhArrowRight,
  PhBrain,
  PhCheckCircle,
  PhDatabase,
  PhTray,
  PhSparkle,
  PhUser,
} from "@phosphor-icons/vue";
import type { AgentWorkspaceMessage } from "../models/agentWorkspace";
import { formatActivityTime } from "../models/agentWorkspace";
import ToolApprovalCard from "./ToolApprovalCard.vue";
import AgentRunApprovalCard from "./AgentRunApprovalCard.vue";

defineProps<{
  messages: AgentWorkspaceMessage[];
  streaming: boolean;
}>();
const emit = defineEmits<{
  approve: [id: number];
  reject: [id: number];
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

function approveAgent(runId: string, approvalId: string) {
  emit("approve-agent", runId, approvalId);
}

function rejectAgent(runId: string, approvalId: string) {
  emit("reject-agent", runId, approvalId);
}
</script>

<template>
  <section class="activity-section" aria-labelledby="activity-title">
    <div class="activity-heading">
      <div>
        <span class="activity-kicker">ACTIVITY</span>
        <h2 id="activity-title">任务活动</h2>
      </div>
      <span v-if="streaming" class="live-indicator">
        <span class="pa-status-dot pa-status-dot--info pa-status-dot--pulse" />
        实时更新
      </span>
    </div>

    <div v-if="messages.length === 0" class="activity-empty">
      <div class="empty-icon"><PhSparkle :size="24" weight="regular" /></div>
      <strong>描述一个目标，PrivateAgent 会从计划开始</strong>
      <p>执行过程、工具调用、授权请求和最终结果都会集中显示在这里。</p>
      <div class="starter-actions">
        <button v-for="prompt in starterPrompts" :key="prompt" @click="emit('use-prompt', prompt)">
          <span>{{ prompt }}</span>
          <PhArrowRight :size="14" />
        </button>
      </div>
    </div>

    <div v-else class="activity-timeline">
      <article
        v-for="(message, index) in messages"
        :key="message.clientKey ?? message.id"
        class="activity-item"
        :class="[`is-${message.tool_call || message.agent_approval ? 'tool' : message.role}`, { 'is-last': index === messages.length - 1 }]"
        data-chat-message
      >
        <time :datetime="message.created_at">{{ formatActivityTime(message.created_at) }}</time>
        <div class="timeline-marker" :data-agent-state="message.role === 'assistant' && streaming && index === messages.length - 1 ? 'thinking' : undefined">
          <PhUser v-if="message.role === 'user'" :size="15" weight="regular" />
          <PhDatabase v-else-if="message.tool_call" :size="15" weight="regular" />
          <PhSparkle v-else :size="15" weight="fill" />
        </div>

        <div class="activity-content">
          <AgentRunApprovalCard
            v-if="message.agent_approval"
            :approval="message.agent_approval"
            @approve="approveAgent"
            @reject="rejectAgent"
          />

          <ToolApprovalCard
            v-else-if="message.tool_call"
            :tool-call="message.tool_call"
            @approve="emit('approve', $event)"
            @reject="emit('reject', $event)"
          />

          <div v-else-if="message.role === 'user'" class="user-request">
            <div class="activity-label">你的任务</div>
            <p>{{ message.content }}</p>
          </div>

          <div v-else class="agent-response" :class="{ 'is-streaming': streaming && index === messages.length - 1 }">
            <div class="agent-response-head">
              <div>
                <span class="agent-name">PrivateAgent</span>
                <span class="agent-role">本地智能体</span>
              </div>
              <span v-if="!streaming || index !== messages.length - 1" class="response-state">
                <PhCheckCircle :size="14" weight="fill" /> 已记录
              </span>
            </div>
            <p class="response-copy">{{ message.content }}<span v-if="streaming && index === messages.length - 1 && message.content" class="cursor" /></p>

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
              <span v-for="memory in message.memories" :key="memory.id" class="memory-chip">{{ memory.title }}</span>
            </div>
            <button
              v-if="message.id > 0 && message.content && !(streaming && index === messages.length - 1)"
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
.activity-section { padding-bottom: var(--space-4); }
.activity-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-3);
  margin: var(--space-5) 0 var(--space-3);
}
.activity-kicker { display: block; margin-bottom: 2px; color: var(--color-fg-faint); font-size: 10px; font-weight: var(--font-semibold); letter-spacing: .11em; }
.activity-heading h2 { margin: 0; color: var(--color-fg); font-size: var(--text-lg); }
.live-indicator { display: inline-flex; align-items: center; gap: var(--space-2); color: var(--color-accent-soft-fg); font-size: var(--text-xs); }
.activity-empty {
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
.empty-icon { display: grid; width: 46px; height: 46px; place-items: center; margin-bottom: var(--space-3); border-radius: 14px; background: var(--color-accent-soft); color: var(--color-accent); }
.activity-empty strong { color: var(--color-fg); font-size: var(--text-md); }
.activity-empty p { max-width: 540px; margin: var(--space-2) 0 var(--space-5); color: var(--color-fg-subtle); font-size: var(--text-sm); line-height: var(--leading-normal); }
.starter-actions { display: grid; width: min(100%, 620px); grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-2); }
.starter-actions button { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); color: var(--color-fg-muted); text-align: left; cursor: pointer; }
.starter-actions button:hover { border-color: color-mix(in srgb, var(--color-accent) 45%, var(--color-border)); color: var(--color-accent-soft-fg); }
.starter-actions button:focus-visible { outline: none; box-shadow: var(--focus-ring); }
.activity-timeline { display: flex; flex-direction: column; }
.activity-item { position: relative; display: grid; grid-template-columns: 54px 28px minmax(0, 1fr); gap: var(--space-2); padding: var(--space-2) 0 var(--space-4); }
.activity-item::before { content: ""; position: absolute; top: 31px; bottom: -2px; left: 67px; width: 1px; background: var(--color-border-strong); }
.activity-item.is-last::before { display: none; }
.activity-item time { padding-top: 7px; color: var(--color-fg-faint); font-size: 10px; font-variant-numeric: tabular-nums; }
.timeline-marker { position: relative; z-index: 1; display: grid; width: 28px; height: 28px; place-items: center; border: 1px solid var(--color-border-strong); border-radius: var(--radius-full); background: var(--color-surface); color: var(--color-fg-subtle); }
.is-assistant .timeline-marker { border-color: color-mix(in srgb, var(--color-accent) 30%, var(--color-border)); background: var(--color-accent-soft); color: var(--color-accent); }
.is-tool .timeline-marker { background: var(--color-rail-bg); color: var(--color-rail-fg-strong); }
.activity-content { min-width: 0; }
.activity-label { margin-bottom: var(--space-1); color: var(--color-fg-faint); font-size: var(--text-xs); font-weight: var(--font-semibold); }
.user-request { padding: var(--space-3) var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface-muted); }
.user-request p, .response-copy { margin: 0; color: var(--color-fg); font-size: var(--text-base); line-height: 1.62; white-space: pre-wrap; word-break: break-word; }
.agent-response { padding: var(--space-3) var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.agent-response.is-streaming { border-color: color-mix(in srgb, var(--color-accent) 35%, var(--color-border)); box-shadow: inset 3px 0 0 var(--color-accent); }
.agent-response-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-2); }
.agent-name { color: var(--color-fg); font-size: var(--text-sm); font-weight: var(--font-semibold); }
.agent-role { margin-left: var(--space-2); color: var(--color-fg-faint); font-size: 10px; }
.response-state { display: inline-flex; align-items: center; gap: var(--space-1); color: var(--color-success-fg); font-size: 10px; }
.cursor { display: inline-block; width: 6px; height: 13px; margin-left: 3px; background: var(--color-accent); animation: activity-blink 1s steps(2) infinite; vertical-align: -2px; }
@keyframes activity-blink { 50% { opacity: 0; } }
.reference-row { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1); margin-top: var(--space-3); color: var(--color-fg-faint); font-size: var(--text-xs); }
.reference-row button, .memory-chip { padding: 3px var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-full); background: var(--color-surface-sunken); color: var(--color-accent-soft-fg); font-size: 10px; }
.reference-row button { cursor: pointer; }
.reference-row button:hover { border-color: var(--color-accent); }
.save-action { display: inline-flex; align-items: center; gap: var(--space-1); margin-top: var(--space-3); padding: 0; border: none; background: transparent; color: var(--color-fg-subtle); font-size: var(--text-xs); cursor: pointer; }
.save-action:hover { color: var(--color-accent); }
.save-action:focus-visible { outline: none; box-shadow: var(--focus-ring); }
@media (max-width: 780px) {
  .activity-item { grid-template-columns: 28px minmax(0, 1fr); }
  .activity-item time { display: none; }
  .activity-item::before { left: 13px; }
  .starter-actions { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) { .cursor { animation: none; } }
</style>
