<script setup lang="ts">
/**
 * AgentWorkspace · Agent 核心工作区（0.4.0 D3）
 * 编排：计划 → 活动流 → 输入区；长活动流自动跟随 +「有新活动」入口；
 * 停止立即反馈并区分「正在请求停止 / 已停止」。
 */
import { computed, onBeforeUnmount, ref, watch } from "vue";
import type { AgentTaskState } from "../../types";
import type { AgentWorkspaceMessage } from "../../models/agentWorkspace";
import { buildAgentPlan } from "../../models/agentWorkspace";
import { useActivityFollow } from "./useActivityFollow";
import AgentPlanV2 from "./AgentPlanV2.vue";
import ActivityFeedV2 from "./ActivityFeedV2.vue";
import TaskComposerV2 from "./TaskComposerV2.vue";

const props = withDefaults(
  defineProps<{
    messages: AgentWorkspaceMessage[];
    streaming: boolean;
    knowledgeBase: boolean;
    pendingTool?: boolean;
    taskState?: AgentTaskState;
  }>(),
  { pendingTool: false, taskState: "idle" }
);

const emit = defineEmits<{
  send: [text: string];
  stop: [];
  "toggle-kb": [];
  approve: [id: number];
  reject: [id: number];
  "approve-agent": [runId: string, approvalId: string];
  "reject-agent": [runId: string, approvalId: string];
  "select-chunk": [chunkId: number];
  "gen-candidates": [];
  "save-inbox": [messageId: number, content: string];
  "use-prompt": [prompt: string];
}>();

const draft = ref("");
const scrollRef = ref<HTMLElement | null>(null);
const planSteps = computed(() => buildAgentPlan(props.messages, props.streaming));
// 内容版本：消息数量或末条内容变化时递增，驱动跟随逻辑
const feedVersion = ref(0);
const lastContent = ref("");

watch(
  () => props.messages.length,
  () => {
    feedVersion.value += 1;
  }
);
watch(
  () => props.messages[props.messages.length - 1]?.content ?? "",
  (content) => {
    if (content !== lastContent.value) {
      lastContent.value = content;
      feedVersion.value += 1;
    }
  }
);

const { newActivity, onScroll, scrollToLatest, scrollToIndex } = useActivityFollow(
  scrollRef,
  feedVersion
);

// 停止状态：点击停止 →「正在请求停止」至少呈现 700ms（含瞬时视觉反馈），
// 之后若流已结束则转为「已停止」提示 4s。
const stopRequested = ref(false);
const stopped = ref(false);
let stoppedTimer: number | null = null;
let stopTransitionTimer: number | null = null;

function onStop() {
  if (props.streaming && !stopRequested.value) {
    stopRequested.value = true;
    emit("stop");
    if (stopTransitionTimer !== null) window.clearTimeout(stopTransitionTimer);
    stopTransitionTimer = window.setTimeout(() => {
      stopTransitionTimer = null;
      stopRequested.value = false;
      if (!props.streaming) {
        stopped.value = true;
        if (stoppedTimer !== null) window.clearTimeout(stoppedTimer);
        stoppedTimer = window.setTimeout(() => {
          stopped.value = false;
          stoppedTimer = null;
        }, 4000);
      }
    }, 700);
  }
}

/** 计划步骤 → 活动流定位 */
function onLocate(stepId: string) {
  const messages = props.messages;
  if (!messages.length) return;
  let index = messages.length - 1;
  if (stepId === "understand") {
    index = messages.findIndex((m) => m.role === "user");
  } else if (stepId === "execute") {
    const toolIdx = messages.findIndex(
      (m) => m.tool_call || m.agent_approval
    );
    index = toolIdx >= 0 ? toolIdx : index;
  } else if (stepId === "respond") {
    const lastAssistant = [...messages]
      .reverse()
      .findIndex(
        (m) =>
          m.role === "assistant" && Boolean(m.content.trim()) && !m.tool_call
      );
    index = lastAssistant >= 0 ? messages.length - 1 - lastAssistant : index;
  }
  scrollToIndex(Math.max(0, index));
}

function onUsePrompt(prompt: string) {
  draft.value = prompt;
  scrollToLatest();
}

// 卸载时清理停止状态定时器，避免组件销毁后仍触发状态写入
onBeforeUnmount(() => {
  if (stoppedTimer !== null) {
    window.clearTimeout(stoppedTimer);
    stoppedTimer = null;
  }
  if (stopTransitionTimer !== null) {
    window.clearTimeout(stopTransitionTimer);
    stopTransitionTimer = null;
  }
});
</script>

<template>
  <div class="agent-workspace">
    <div
      ref="scrollRef"
      class="agent-scroll"
      @scroll.passive="onScroll"
      data-testid="agent-scroll"
    >
      <div class="agent-inner">
        <AgentPlanV2 :steps="planSteps" @locate="onLocate" />
        <ActivityFeedV2
          :messages="messages"
          :streaming="streaming"
          :task-state="taskState"
          @approve-tool="(id) => emit('approve', id)"
          @reject-tool="(id) => emit('reject', id)"
          @approve-agent="(runId, approvalId) => emit('approve-agent', runId, approvalId)"
          @reject-agent="(runId, approvalId) => emit('reject-agent', runId, approvalId)"
          @select-chunk="(chunkId) => emit('select-chunk', chunkId)"
          @save-inbox="(messageId, content) => emit('save-inbox', messageId, content)"
          @use-prompt="onUsePrompt"
        />
      </div>
    </div>

    <button
      v-if="newActivity"
      class="new-activity-pill"
      data-testid="new-activity-pill"
      @click="scrollToLatest(true)"
    >
      有新活动
      <span class="pill-dot" />
    </button>

    <TaskComposerV2
      v-model="draft"
      :streaming="streaming"
      :pending-tool="pendingTool"
      :knowledge-base="knowledgeBase"
      :stop-requested="stopRequested"
      :stopped="stopped"
      @send="(text) => emit('send', text)"
      @stop="onStop"
      @toggle-kb="emit('toggle-kb')"
      @gen-candidates="emit('gen-candidates')"
    />
  </div>
</template>

<style scoped>
.agent-workspace {
  display: flex;
  position: relative;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  background: var(--color-bg);
}
.agent-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  scroll-padding-bottom: 160px;
}
.agent-inner {
  width: min(100%, var(--pa-page-max-w));
  min-height: 100%;
  margin: 0 auto;
  padding: var(--space-5) var(--space-6) var(--space-8);
}
.new-activity-pill {
  display: inline-flex;
  position: absolute;
  z-index: var(--z-raised);
  right: var(--space-6);
  bottom: 150px;
  align-items: center;
  gap: var(--space-2);
  height: 32px;
  padding: 0 var(--space-4);
  border: 1px solid color-mix(in srgb, var(--color-accent) 45%, var(--color-border));
  border-radius: var(--radius-full);
  background: var(--color-surface);
  color: var(--color-accent-soft-fg);
  font-size: var(--pa-text-compact);
  font-weight: var(--font-medium);
  box-shadow: var(--shadow);
  cursor: pointer;
}
.new-activity-pill:hover {
  background: var(--color-accent-soft);
}
.new-activity-pill:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.pill-dot {
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  background: var(--color-accent);
}
.pa-float-enter-active,
.pa-float-leave-active {
  transition: opacity var(--pa-motion-standard) var(--ease),
    transform var(--pa-motion-standard) var(--ease-out);
}
.pa-float-enter-from,
.pa-float-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
@media (max-width: 900px) {
  .agent-inner {
    padding: var(--space-4);
  }
}
</style>
