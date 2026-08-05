<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { AgentWorkspaceMessage } from "../models/agentWorkspace";
import { buildAgentPlan } from "../models/agentWorkspace";
import { mountAgentAnimations } from "../animations/agent";
import { mountChatAnimations } from "../animations/chat";
import type { AnimationHandle } from "../animations/utils";
import AgentActivityFeed from "./AgentActivityFeed.vue";
import AgentPlan from "./AgentPlan.vue";
import TaskComposer from "./TaskComposer.vue";

const props = withDefaults(
  defineProps<{
    messages: AgentWorkspaceMessage[];
    streaming: boolean;
    knowledgeBase: boolean;
    pendingTool?: boolean;
  }>(),
  { pendingTool: false }
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
}>();

const draft = ref("");
const scrollRef = ref<HTMLElement | null>(null);
const chatRef = ref<HTMLElement | null>(null);
const planSteps = computed(() => buildAgentPlan(props.messages, props.streaming));
let chatAnimations: AnimationHandle | null = null;
let agentAnimations: AnimationHandle | null = null;

async function scrollToLatest() {
  await nextTick();
  if (!scrollRef.value || props.messages.length === 0) return;
  scrollRef.value.scrollTo({
    top: scrollRef.value.scrollHeight,
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "auto"
      : "smooth",
  });
}

watch(() => props.messages.length, scrollToLatest);
watch(() => props.messages[props.messages.length - 1]?.content, scrollToLatest);

onMounted(() => {
  if (!chatRef.value) return;
  chatAnimations = mountChatAnimations(chatRef.value);
  agentAnimations = mountAgentAnimations(chatRef.value);
});

onBeforeUnmount(() => {
  chatAnimations?.destroy();
  agentAnimations?.destroy();
  chatAnimations = null;
  agentAnimations = null;
});
</script>

<template>
  <div ref="chatRef" class="agent-workspace">
    <div ref="scrollRef" class="agent-workspace-scroll">
      <div class="agent-workspace-inner">
        <AgentPlan :steps="planSteps" />
        <AgentActivityFeed
          :messages="messages"
          :streaming="streaming"
          @approve="emit('approve', $event)"
        @reject="emit('reject', $event)"
        @approve-agent="(runId, approvalId) => emit('approve-agent', runId, approvalId)"
        @reject-agent="(runId, approvalId) => emit('reject-agent', runId, approvalId)"
          @select-chunk="emit('select-chunk', $event)"
          @save-inbox="(messageId, content) => emit('save-inbox', messageId, content)"
          @use-prompt="draft = $event"
        />
      </div>
    </div>

    <TaskComposer
      v-model="draft"
      :streaming="streaming"
      :pending-tool="pendingTool"
      :knowledge-base="knowledgeBase"
      @send="emit('send', $event)"
      @stop="emit('stop')"
      @toggle-kb="emit('toggle-kb')"
      @gen-candidates="emit('gen-candidates')"
    />
  </div>
</template>

<style scoped>
.agent-workspace {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  background: var(--color-bg);
}
.agent-workspace-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  scroll-padding-bottom: 160px;
}
.agent-workspace-inner {
  width: min(100%, 1060px);
  min-height: 100%;
  margin: 0 auto;
  padding: var(--space-5) var(--space-6) var(--space-8);
}
@media (max-width: 900px) {
  .agent-workspace-inner {
    padding: var(--space-4);
  }
}
</style>
