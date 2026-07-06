<script setup lang="ts">
import { ref, nextTick, watch } from "vue";
import type { Message, Source, ToolCall } from "../types";
import ToolApprovalCard from "./ToolApprovalCard.vue";

type ChatMessage = Message & { sources?: Source[]; tool_call?: ToolCall };

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
        开始与助手对话，按 Enter 发送消息。
      </div>
      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <div class="avatar">{{ m.role === "user" ? "我" : "AI" }}</div>
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
              📎 来源：<span
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
          </template>
        </div>
      </div>
    </div>

    <div class="input-bar">
      <label class="kb-toggle" :class="{ on: knowledgeBase }">
        <input type="checkbox" :checked="knowledgeBase" @change="emit('toggle-kb')" />
        <span>📚 知识库</span>
      </label>
      <textarea
        v-model="input"
        @keydown.enter.exact.prevent="send"
        placeholder="输入消息，Enter 发送，Shift+Enter 换行…"
        :disabled="streaming || pendingTool"
        rows="1"
      ></textarea>
      <button v-if="streaming" class="stop-btn" @click="emit('stop')">停止生成</button>
      <button
        v-else
        class="send-btn"
        @click="send"
        :disabled="!input.trim() || pendingTool"
      >
        发送
      </button>
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
  padding: 20px 0;
}
.empty-chat {
  text-align: center;
  color: #9a9b9e;
  padding: 60px 0;
  font-size: 14px;
}
.msg {
  display: flex;
  gap: 12px;
  padding: 8px 32px;
  max-width: 900px;
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
  border-radius: 8px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
}
.msg.user .avatar {
  background: #e8eaf0;
  color: #1a1b1e;
}
.msg.assistant .avatar {
  background: #2e7d32;
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
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  text-align: left;
}
.msg.user .bubble {
  background: #1a1b1e;
  color: #fff;
  border-bottom-right-radius: 4px;
}
.msg.assistant .bubble {
  background: #fff;
  border: 1px solid #e5e6e8;
  border-bottom-left-radius: 4px;
}
.sources {
  margin-top: 6px;
  font-size: 12px;
  color: #6a6b6e;
  padding: 0 4px;
}
.source {
  color: #1565c0;
}
.src-hit {
  color: var(--color-fg-faint);
  font-size: 11px;
}
.cursor {
  display: inline-block;
  animation: blink 1s steps(2) infinite;
  color: #2e7d32;
  margin-left: 1px;
}
@keyframes blink {
  to {
    opacity: 0;
  }
}
.input-bar {
  border-top: 1px solid #e5e6e8;
  padding: 12px 32px;
  display: flex;
  gap: 10px;
  background: #fff;
  align-items: flex-end;
  min-width: 0;
}
.kb-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #6a6b6e;
  cursor: pointer;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid #e5e6e8;
  user-select: none;
  white-space: nowrap;
}
.kb-toggle.on {
  background: #e8f5e9;
  border-color: #c8e6c9;
  color: #1b5e20;
}
.kb-toggle input {
  margin: 0;
}
textarea {
  flex: 1;
  resize: none;
  border: 1px solid #d8d9da;
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 14px;
  font-family: inherit;
  outline: none;
  max-height: 120px;
  line-height: 1.5;
  min-width: 0;
}
textarea:focus {
  border-color: #1a1b1e;
}
.send-btn,
.stop-btn {
  padding: 10px 20px;
  border-radius: 10px;
  font-size: 14px;
  cursor: pointer;
  border: none;
  font-weight: 500;
}
.send-btn {
  background: #1a1b1e;
  color: #fff;
}
.send-btn:disabled {
  background: #c0c1c4;
  cursor: not-allowed;
}
.stop-btn {
  background: #c62828;
  color: #fff;
}
</style>
