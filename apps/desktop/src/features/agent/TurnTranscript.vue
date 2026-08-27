<script setup lang="ts">
/**
 * TurnTranscript · v0.8.0 W6-R2（计划 §4.4 逐轮内容结构）
 *
 * 每轮用户消息形成稳定 turn 容器：用户请求 → 公开过程（工具/命令/审批/
 * 中间公开消息）→ 最终回答。公开思考摘要只来自 Agent 主动输出的公开消息；
 * 无公开摘要时仅呈现「正在分析/正在执行/等待审批」等真实状态（不虚构）。
 * 最终回答完成后提供复制按钮：复制内容 = 可见最终回答正文（保留换行），
 * 不混入按钮文案、过程或隐藏 DOM；成功只提示「回答已复制」，失败/剪贴板
 * 不可用给出可恢复提示，通知中不含回答正文。
 */
import { computed, ref } from "vue";
import { PhCopy } from "@phosphor-icons/vue";
import type { AgentTaskState } from "../../types";
import type { AgentWorkspaceMessage } from "../../models/agentWorkspace";
import type { AgentTurn } from "./model/agentTurns";
import { turnPublicStatusLabel } from "./model/agentTurns";
import {
  copyAnswerText,
  COPY_FAILED_MESSAGE,
  COPY_SUCCESS_MESSAGE,
  COPY_UNAVAILABLE_MESSAGE,
} from "./model/copyAnswerText";
import { useNotifications } from "../../stores/notifications";
import ActivityFeedV2 from "./ActivityFeedV2.vue";

withDefaults(
  defineProps<{
    turns: AgentTurn[];
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

const notify = useNotifications();

function turnMessages(turn: AgentTurn): AgentWorkspaceMessage[] {
  return [
    ...(turn.userMessage ? [turn.userMessage] : []),
    ...turn.process,
    ...(turn.finalAnswer ? [turn.finalAnswer] : []),
  ];
}

/** 本轮是否存在真实的工具/命令/审批过程（公开事实） */
function turnHasProcessActions(turn: AgentTurn): boolean {
  return turn.process.some((message) => Boolean(message.tool_call || message.agent_approval));
}

const copiedKey = ref<string | null>(null);
const copiedTurnKey = computed(() => copiedKey.value);

async function onCopyAnswer(turn: AgentTurn): Promise<void> {
  const answer = turn.finalAnswer;
  if (!answer) return;
  const result = await copyAnswerText(answer.content);
  if (result === "ok") {
    copiedKey.value = turn.key;
    notify.success(COPY_SUCCESS_MESSAGE);
  } else if (result === "unavailable") {
    notify.error("复制不可用", COPY_UNAVAILABLE_MESSAGE);
  } else {
    notify.error("复制失败", COPY_FAILED_MESSAGE);
  }
}
</script>

<template>
  <div class="turn-transcript" data-testid="turn-transcript">
    <div v-if="turns.length === 0" class="turns-empty">
      <ActivityFeedV2
        :messages="[]"
        :streaming="streaming"
        :task-state="taskState"
        @use-prompt="(prompt) => emit('use-prompt', prompt)"
      />
    </div>

    <article
      v-for="(turn, index) in turns"
      :key="turn.key"
      class="turn"
      :data-testid="`turn-${index}`"
      :data-turn-key="turn.key"
      :aria-label="`第 ${index + 1} 轮`"
    >
      <ActivityFeedV2
        :messages="turnMessages(turn)"
        :streaming="turn.phase === 'running'"
        :task-state="taskState"
        :show-heading="false"
        @approve-tool="(id) => emit('approve-tool', id)"
        @reject-tool="(id) => emit('reject-tool', id)"
        @approve-agent="(runId, approvalId) => emit('approve-agent', runId, approvalId)"
        @reject-agent="(runId, approvalId) => emit('reject-agent', runId, approvalId)"
        @select-chunk="(chunkId) => emit('select-chunk', chunkId)"
        @save-inbox="(messageId, content) => emit('save-inbox', messageId, content)"
        @use-prompt="(prompt) => emit('use-prompt', prompt)"
      />

      <!-- 无最终回答时的真实状态（公开事实，不虚构思考内容） -->
      <div
        v-if="turnPublicStatusLabel(turn)"
        class="turn-status"
        :class="turn.phase === 'waiting_approval' ? 'is-warning' : 'is-info'"
        data-testid="turn-public-status"
      >
        {{ turnPublicStatusLabel(turn) }}
      </div>

      <!-- W6-R3：本轮无命令/工具时的真实空态（不留白、不伪造动作） -->
      <div
        v-if="turn.phase === 'settled' && !turnHasProcessActions(turn)"
        class="turn-no-commands"
        data-testid="turn-no-commands"
      >
        本轮未执行命令或工具。
      </div>

      <!-- 完成后的最终回答复制（只复制可见最终回答正文） -->
      <div v-if="turn.finalAnswer && turn.phase !== 'running'" class="turn-answer-actions">
        <button
          class="copy-answer"
          type="button"
          :data-testid="`turn-copy-${index}`"
          @click="onCopyAnswer(turn)"
        >
          <PhCopy :size="13" aria-hidden="true" />
          <span>{{ copiedTurnKey === turn.key ? "已复制" : "复制回答" }}</span>
        </button>
      </div>
    </article>
  </div>
</template>

<style scoped>
.turn-transcript {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.turn {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-border);
}
.turn:last-child {
  border-bottom: none;
}
.turn-status {
  align-self: flex-start;
  padding: 2px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.turn-status.is-info {
  color: var(--color-accent-soft-fg);
}
.turn-status.is-warning {
  border-color: color-mix(in srgb, var(--color-warning) 40%, var(--color-border));
  color: var(--color-warning-fg);
}
.turn-no-commands {
  align-self: flex-start;
  padding: 2px var(--space-2);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
.turn-answer-actions {
  display: flex;
  justify-content: flex-end;
}
.copy-answer {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.copy-answer:hover {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.turns-empty :deep(.feed) {
  border: none;
}
</style>
