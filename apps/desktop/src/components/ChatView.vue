<script setup lang="ts">
import { ref, nextTick, watch } from "vue";
import {
  PhArrowUp,
  PhBrain,
  PhDatabase,
  PhLink,
  PhPaperclip,
  PhStop,
} from "@phosphor-icons/vue";
import type { MemorySource, Message, Source, ToolCall } from "../types";
import ToolApprovalCard from "./ToolApprovalCard.vue";

type ChatMessage = Message & {
  sources?: Source[];
  memories?: MemorySource[];
  tool_call?: ToolCall;
};

const props = withDefaults(
  defineProps<{
    messages: ChatMessage[];
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
  "select-chunk": [chunkId: number];
  "gen-candidates": [];
  "save-inbox": [messageId: number, content: string];
}>();

const input = ref("");
const listRef = ref<HTMLElement | null>(null);

function send() {
  const t = input.value.trim();
  if (!t || props.streaming || props.pendingTool) return;
  emit("send", t);
  input.value = "";
}

async function scrollBottom() {
  await nextTick();
  if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight;
}
watch(() => props.messages.length, scrollBottom);
watch(() => props.messages[props.messages.length - 1]?.content, scrollBottom);
</script>

<template>
  <div class="chat">
    <div class="messages" ref="listRef">
      <div v-if="messages.length === 0" class="empty-chat">
        <div class="empty-title">把问题、文件或下一步计划交给 PrivateAgent</div>
        <div class="empty-sub">它会结合本地知识库、记忆和当前上下文回答。</div>
      </div>
      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <div class="avatar">{{ m.role === "user" ? "我" : "P" }}</div>
        <div class="bubble-wrap">
          <ToolApprovalCard
            v-if="m.tool_call"
            :tool-call="m.tool_call"
            @approve="emit('approve', $event)"
            @reject="emit('reject', $event)"
          />
          <template v-else>
            <div class="bubble">
              {{ m.content
              }}<span
                v-if="
                  m.role === 'assistant' &&
                  streaming &&
                  i === messages.length - 1 &&
                  m.content
                "
                class="cursor"
                >▍</span
              >
            </div>
            <div
              v-if="m.role === 'assistant' && m.sources && m.sources.length"
              class="sources"
            >
              <PhPaperclip :size="13" /> 来源：<span
                v-for="(s, si) in m.sources"
                :key="si"
                class="source"
                @click="emit('select-chunk', s.chunk_id)"
                >{{ s.doc_name }} · 片段{{ s.ordinal
                }}<span
                  v-if="s.matched_keywords && s.matched_keywords.length"
                  class="src-hit"
                  >（命中：{{ s.matched_keywords.slice(0, 3).join("、") }}<template
                    v-if="s.matched_keywords.length > 3"
                    >等</template
                  >）</span
                ><span v-if="si < m.sources.length - 1">；</span></span
              >
            </div>
            <div
              v-if="m.role === 'assistant' && m.memories && m.memories.length"
              class="memories"
            >
              <PhBrain :size="13" /> 记忆：<span
                v-for="(mem, mi) in m.memories"
                :key="mem.id"
                class="memory"
                >{{ mem.title }}<span v-if="mem.summary" class="mem-summary"
                  >（{{ mem.summary }}）</span
                ><span v-if="mi < m.memories.length - 1">；</span></span
              >
            </div>
            <button
              v-if="
                m.id > 0 &&
                m.content &&
                !(streaming && i === messages.length - 1)
              "
              class="msg-action"
              title="保存这条消息到收件箱"
              @click="emit('save-inbox', m.id, m.content)"
            >
              存为收件箱
            </button>
          </template>
        </div>
      </div>
    </div>

    <div class="composer-wrap">
      <div class="composer">
        <textarea
          v-model="input"
          @keydown.enter.exact.prevent="send"
          placeholder="有什么问题或需要我帮忙的吗？"
          :disabled="streaming || pendingTool"
          rows="2"
        ></textarea>
        <div class="composer-tools">
          <label class="tool-chip" :class="{ on: knowledgeBase }">
            <input type="checkbox" :checked="knowledgeBase" @change="emit('toggle-kb')" />
            <PhDatabase :size="15" />
            <span>搜索知识库</span>
          </label>
          <button
            class="tool-chip"
            :disabled="streaming"
            title="从当前对话生成候选记忆"
            @click="emit('gen-candidates')"
          >
            <PhBrain :size="15" />
            <span>生成记忆</span>
          </button>
          <button class="tool-chip" disabled title="关联稍后接入">
            <PhLink :size="15" />
            <span>关联</span>
          </button>
          <div class="composer-spacer" />
          <button v-if="streaming" class="stop-btn" @click="emit('stop')">
            <PhStop :size="16" weight="fill" />
          </button>
          <button
            v-else
            class="send-btn"
            @click="send"
            :disabled="!input.trim() || pendingTool"
            title="发送"
          >
            <PhArrowUp :size="18" weight="bold" />
          </button>
        </div>
      </div>
      <p class="composer-note">本地优先处理，所有数据只保存在你的设备上。</p>
    </div>
  </div>
</template>

<style scoped>
.chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.messages {
  flex: 1;
  overflow: auto;
  padding: var(--space-6) 0;
}
.empty-chat {
  text-align: center;
  color: var(--color-fg-faint);
  padding: 90px 0;
}
.empty-title {
  color: var(--color-fg);
  font-size: var(--text-xl);
  font-weight: var(--font-semibold);
}
.empty-sub {
  margin-top: var(--space-2);
  font-size: var(--text-sm);
}
.msg {
  display: flex;
  gap: 12px;
  padding: var(--space-2) var(--space-8);
  max-width: 920px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}
.msg.user {
  flex-direction: row-reverse;
}
.avatar {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
}
.msg.user .avatar {
  background: var(--color-surface-sunken);
  color: var(--color-fg);
}
.msg.assistant .avatar {
  background: var(--color-rail-bg);
  color: #fff;
}
.bubble-wrap {
  min-width: 0;
}
.msg.user .bubble-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
.bubble {
  display: inline-block;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-lg);
  font-size: var(--text-base);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  text-align: left;
}
.msg.user .bubble {
  background: var(--color-rail-bg);
  color: #fff;
  border-bottom-right-radius: 4px;
}
.msg.assistant .bubble {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-bottom-left-radius: 4px;
}
.sources {
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-fg-subtle);
  padding: 0 4px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 3px;
}
.source {
  color: var(--color-accent);
}
.src-hit {
  color: var(--color-fg-faint);
  font-size: 11px;
}
.memories {
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-fg-subtle);
  padding: 0 4px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 3px;
}
.memory {
  color: var(--color-accent-soft-fg);
}
.mem-summary {
  color: var(--color-fg-faint);
  font-size: 11px;
}
.msg-action {
  margin-top: 6px;
  padding: 2px 8px;
  font-size: 11px;
  color: var(--color-fg-subtle);
  background: transparent;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  cursor: pointer;
}
.msg-action:hover {
  color: var(--color-accent);
  border-color: var(--color-accent);
}
.cursor {
  display: inline-block;
  animation: blink 1s steps(2) infinite;
  color: var(--color-accent);
  margin-left: 1px;
}
@keyframes blink {
  to {
    opacity: 0;
  }
}
.composer-wrap {
  padding: var(--space-4) var(--space-8) var(--space-5);
}
.composer {
  max-width: 760px;
  margin: 0 auto;
  border: 2px solid var(--color-accent);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: 0 8px 28px rgba(7, 135, 163, 0.08);
  overflow: hidden;
}
.tool-chip {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-fg-muted);
  cursor: pointer;
  padding: 0 var(--space-3);
  height: 32px;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  user-select: none;
  white-space: nowrap;
}
.tool-chip.on {
  background: var(--color-accent-soft);
  border-color: color-mix(in srgb, var(--color-accent) 30%, var(--color-border));
  color: var(--color-accent-soft-fg);
}
.tool-chip input {
  margin: 0;
  display: none;
}
textarea {
  width: 100%;
  resize: none;
  border: none;
  padding: var(--space-4) var(--space-4) var(--space-2);
  font-size: var(--text-base);
  font-family: inherit;
  outline: none;
  max-height: 140px;
  line-height: 1.5;
  min-width: 0;
  background: transparent;
}
textarea:focus {
  border-color: transparent;
}
.composer-tools {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3);
  border-top: 1px solid var(--color-border);
}
.composer-spacer {
  flex: 1;
}
.send-btn,
.stop-btn {
  width: 40px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: var(--radius);
  font-size: var(--text-base);
  cursor: pointer;
  border: none;
  font-weight: 500;
}
.send-btn {
  background: var(--color-accent);
  color: #fff;
}
.send-btn:disabled {
  background: var(--color-fg-disabled);
  cursor: not-allowed;
}
.stop-btn {
  background: var(--color-danger);
  color: #fff;
}
.composer-note {
  text-align: center;
  margin: var(--space-3) 0 0;
  color: var(--color-fg-faint);
  font-size: var(--text-xs);
}

@media (max-width: 760px) {
  .composer-tools {
    flex-wrap: wrap;
  }
  .composer-spacer {
    display: none;
  }
  .send-btn,
  .stop-btn {
    margin-left: auto;
  }
}
</style>
