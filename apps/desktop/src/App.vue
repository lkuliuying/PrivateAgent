<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import Sidebar from "./components/Sidebar.vue";
import ChatView from "./components/ChatView.vue";
import KnowledgeView from "./components/KnowledgeView.vue";
import SettingsView from "./components/SettingsView.vue";
import ConfigWizard from "./components/ConfigWizard.vue";
import {
  createSession,
  getHealth,
  getMessages,
  listSessions,
  setApiBase,
  setApiBaseDefault,
  streamChat,
  cmdStartSidecar,
  cmdConfigExists,
  cmdRelaunchApp,
} from "./api";
import { isTauri } from "@tauri-apps/api/core";
import type { Message, Session, Source } from "./types";

type ChatMessage = Message & { sources?: Source[] };

// bootState：checking（检测中）/ wizard（配置向导）/ starting（启动后端中）
//   / done（就绪）/ dev（开发模式手动后端）/ error（失败）
type BootState = "checking" | "wizard" | "starting" | "done" | "dev" | "error";
const bootState = ref<BootState>("checking");
const wizardMode = ref<"first" | "reconfigure">("first");
const bootError = ref("");

const sessions = ref<Session[]>([]);
const currentSessionId = ref<number | null>(null);
const messages = ref<ChatMessage[]>([]);
const view = ref<"chat" | "kb" | "settings">("chat");
const streaming = ref(false);
const knowledgeBase = ref(false);
let controller: AbortController | null = null;

const currentSession = computed(
  () => sessions.value.find((s) => s.id === currentSessionId.value) ?? null
);

onMounted(boot);

// ============ 启动引导 ============

async function boot() {
  // 浏览器开发：直接用默认端口。
  if (!isTauri()) {
    setApiBaseDefault();
    bootState.value = "done";
    await loadSessions();
    return;
  }

  bootState.value = "checking";
  let res;
  try {
    res = await cmdStartSidecar();
  } catch {
    bootError.value = "无法与桌面壳通信";
    bootState.value = "error";
    return;
  }

  // dev 模式：sidecar 返回 dev_mode，回退手动后端 127.0.0.1:8000。
  if (res.dev_mode) {
    setApiBaseDefault();
    bootState.value = "dev";
    await loadSessions();
    return;
  }

  // 打包模式：sidecar 已 spawn。
  if (res.ok && res.port) {
    bootState.value = "starting";
    setApiBase(res.port);
    const ready = await pollHealth(30);
    if (ready) {
      bootState.value = "done";
      await loadSessions();
    } else {
      bootError.value = "后端启动超时，请检查 MySQL / Ollama 是否正在运行。";
      bootState.value = "error";
    }
    return;
  }

  // ok:false —— 通常尚未配置连接；也可能是 spawn 失败。
  const exists = await cmdConfigExists().catch(() => false);
  if (!exists) {
    wizardMode.value = "first";
    bootState.value = "wizard";
  } else {
    bootError.value = res.error || "后端启动失败";
    bootState.value = "error";
  }
}

/** 轮询 /health 直到成功或超时。仅当 MySQL 与 Ollama 都就绪才算就绪——
 * HTTP 服务绑定但依赖未就绪时 /health 仍返回 200（api.ok=true, mysql.ok=false），
 * 不能仅凭 fetch 不抛错就判定后端可用。 */
async function pollHealth(seconds: number): Promise<boolean> {
  for (let i = 0; i < seconds * 5; i++) {
    try {
      const h = await getHealth();
      const mysql = (h.mysql as { ok?: boolean } | undefined)?.ok;
      const ollama = (h.ollama as { ok?: boolean } | undefined)?.ok;
      if (mysql && ollama) return true;
    } catch {
      // HTTP 服务尚未绑定
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  return false;
}

/** 向导完成（配置已写入）后：首次运行→启动 sidecar；重新配置→重启应用。 */
async function onWizardDone() {
  if (wizardMode.value === "reconfigure") {
    // 新配置需重启应用才能让 sidecar 重新加载 .env。
    try {
      await cmdRelaunchApp();
    } catch {
      bootError.value = "重启失败，请手动重启应用";
      bootState.value = "error";
    }
    return;
  }
  // 首次运行：启动 sidecar。
  bootState.value = "starting";
  const res = await cmdStartSidecar().catch(() => null);
  if (res && res.ok && res.port) {
    setApiBase(res.port);
    const ready = await pollHealth(30);
    if (ready) {
      bootState.value = "done";
      await loadSessions();
    } else {
      bootError.value = "后端启动超时，请检查 MySQL / Ollama。";
      bootState.value = "error";
    }
  } else {
    bootError.value = res?.error || "后端启动失败";
    bootState.value = "error";
  }
}

/** 从设置页触发重新配置。 */
function reconfigure() {
  wizardMode.value = "reconfigure";
  bootState.value = "wizard";
}

async function retryBoot() {
  await boot();
}

// ============ 会话 / 对话 ============

async function loadSessions() {
  try {
    sessions.value = await listSessions();
    if (sessions.value.length > 0 && currentSessionId.value === null) {
      await selectSession(sessions.value[0].id);
    }
  } catch {
    // 后端未连接，设置/状态页会展示提示
  }
}

async function selectSession(id: number) {
  if (streaming.value) return;
  currentSessionId.value = id;
  view.value = "chat";
  try {
    messages.value = await getMessages(id);
  } catch {
    messages.value = [];
  }
}

async function newSession() {
  if (streaming.value) return;
  try {
    const s = await createSession();
    sessions.value.unshift(s);
    await selectSession(s.id);
  } catch (e) {
    alert("新建会话失败：" + String(e));
  }
}

function sendMessage(text: string) {
  if (!currentSession.value || streaming.value) return;
  const sid = currentSession.value.id;
  const now = new Date().toISOString();

  messages.value.push({
    id: -Date.now(),
    session_id: sid,
    role: "user",
    content: text,
    created_at: now,
  });
  messages.value.push({
    id: -2,
    session_id: sid,
    role: "assistant",
    content: "",
    created_at: now,
  });
  const aiIdx = messages.value.length - 1;
  streaming.value = true;

  controller = streamChat(
    sid,
    text,
    knowledgeBase.value,
    (e) => {
      if (e.type === "token" && e.content) {
        messages.value[aiIdx].content += e.content;
      } else if (e.type === "done") {
        if (e.message_id) messages.value[aiIdx].id = e.message_id;
        if (e.content) messages.value[aiIdx].content = e.content;
        if (e.sources) messages.value[aiIdx].sources = e.sources;
      } else if (e.type === "title" && e.title && currentSession.value) {
        currentSession.value.title = e.title;
        const s = sessions.value.find((x) => x.id === sid);
        if (s) s.title = e.title;
      } else if (e.type === "error" && e.message) {
        messages.value[aiIdx].content += `\n\n[错误：${e.message}]`;
      }
    },
    (err) => {
      messages.value[aiIdx].content += `\n\n[连接错误：${err}]`;
      streaming.value = false;
    },
    () => {
      streaming.value = false;
    }
  );
}

function stopGenerate() {
  controller?.abort();
  streaming.value = false;
}

const titleMap: Record<string, string> = {
  chat: "私人助手",
  kb: "知识库",
  settings: "设置 / 状态",
};
</script>

<template>
  <!-- 启动引导覆盖层 -->
  <div v-if="bootState !== 'done' && bootState !== 'dev'" class="boot">
    <div v-if="bootState === 'checking' || bootState === 'starting'" class="boot-card">
      <div class="spinner" />
      <p>{{ bootState === "checking" ? "正在检测环境…" : "正在启动本地后端…" }}</p>
      <p class="hint">首次启动可能需要数秒</p>
    </div>

    <ConfigWizard
      v-else-if="bootState === 'wizard'"
      :mode="wizardMode"
      @done="onWizardDone"
    />

    <div v-else class="boot-card">
      <p class="boot-err">⚠ 启动失败</p>
      <p class="hint">{{ bootError }}</p>
      <button class="retry-btn" @click="retryBoot">重试</button>
      <button v-if="isTauri()" class="retry-btn ghost" @click="reconfigure">
        重新配置连接
      </button>
    </div>
  </div>

  <!-- 主应用 -->
  <div v-else class="app">
    <Sidebar
      :sessions="sessions"
      :current-id="currentSessionId"
      @select="selectSession"
      @new="newSession"
      @show-kb="view = 'kb'"
      @show-settings="view = 'settings'"
    />
    <main class="main">
      <header class="topbar">
        <span class="title">{{
          view === "chat"
            ? currentSession?.title || "私人助手"
            : titleMap[view]
        }}</span>
        <span v-if="bootState === 'dev'" class="dev-tag">DEV · 手动后端 8000</span>
      </header>
      <SettingsView v-if="view === 'settings'" @reconfigure="reconfigure" />
      <KnowledgeView v-else-if="view === 'kb'" />
      <ChatView
        v-else-if="currentSession"
        :messages="messages"
        :streaming="streaming"
        :knowledge-base="knowledgeBase"
        @send="sendMessage"
        @stop="stopGenerate"
        @toggle-kb="knowledgeBase = !knowledgeBase"
      />
      <div v-else class="placeholder">
        <p>👋 欢迎使用私人助手</p>
        <p class="hint">点击左侧「+ 新建」开始对话</p>
      </div>
    </main>
  </div>
</template>

<style>
:root {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Microsoft YaHei", sans-serif;
  font-size: 14px;
  color: #1a1b1e;
  background-color: #f7f7f8;
}
* {
  box-sizing: border-box;
}
body,
html {
  margin: 0;
  padding: 0;
}
.app {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
}
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.topbar {
  height: 48px;
  background: #fff;
  border-bottom: 1px solid #e5e6e8;
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 12px;
  flex-shrink: 0;
}
.topbar .title {
  font-size: 15px;
  font-weight: 500;
}
.dev-tag {
  font-size: 11px;
  color: #9a9b9e;
  border: 1px solid #e5e6e8;
  border-radius: 10px;
  padding: 2px 8px;
}
.placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #6a6b6e;
}
.placeholder p {
  margin: 4px 0;
}
.placeholder .hint {
  font-size: 13px;
  color: #9a9b9e;
}

/* 启动引导 */
.boot {
  height: 100vh;
  width: 100vw;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f7f7f8;
}
.boot-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px;
}
.boot-card p {
  margin: 0;
}
.boot-card .hint {
  font-size: 13px;
  color: #9a9b9e;
}
.boot-err {
  color: #b71c1c;
  font-size: 16px;
}
.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #e5e6e8;
  border-top-color: #1a1b1e;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: 6px;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.retry-btn {
  margin-top: 10px;
  background: #1a1b1e;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 8px 20px;
  font-size: 14px;
  cursor: pointer;
}
.retry-btn.ghost {
  background: #fff;
  color: #1a1b1e;
  border: 1px solid #d8d9da;
}
</style>
