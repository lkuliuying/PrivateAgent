<script setup lang="ts">
import { ref } from "vue";
import { isTauri } from "@tauri-apps/api/core";
import { defaultConnectionProfile, getConnectionProfile, saveConnectionProfile, validateConnectionProfile } from "../services/connectionProfile";
import { stopLocalExecutor } from "../services/localExecutor";
import { clearAccessToken } from "../auth/session";

const available = isTauri() && import.meta.env.VITE_LOCAL_EXECUTOR !== "false";
const expanded = ref(false);
const busy = ref(false);
const error = ref("");
let initial = defaultConnectionProfile();
try { initial = getConnectionProfile() ?? initial; } catch { expanded.value = true; }
const profile = ref({ ...initial });
const capacity = ref(initial.context_tokens === null ? "" : String(initial.context_tokens));

async function apply(): Promise<void> {
  error.value = "";
  busy.value = true;
  try {
    const selected = validateConnectionProfile({ ...profile.value, context_tokens: capacity.value.trim() ? Number(capacity.value) : null });
    // 先停止运行和撤销旧授权，再切换配置，避免旧任务获得新连接的身份。
    await stopLocalExecutor();
    saveConnectionProfile(selected);
    clearAccessToken();
    window.location.reload();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "连接切换失败";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <details v-if="available" class="connection-settings" :open="expanded">
    <summary>连接设置 · 本地 / 云端 / 自托管</summary>
    <form @submit.prevent="apply">
      <label>连接方式<select v-model="profile.mode"><option value="local">本地模型（无需云端账号）</option><option value="cloud">云端账号服务</option><option value="self_hosted">自托管账号服务</option></select></label>
      <template v-if="profile.mode !== 'local'">
        <label>账号服务源站<input v-model="profile.server_origin" required placeholder="https://agent.example.com" /></label>
        <label>模型执行位置<select v-model="profile.inference_mode"><option value="service">账号服务提供模型</option><option value="local">使用本机模型（保留当前账号记录）</option></select></label>
      </template>
      <template v-if="profile.mode === 'local' || profile.inference_mode === 'local'">
        <label>模型协议<select v-model="profile.model_protocol"><option value="ollama">Ollama</option><option value="openai">OpenAI 兼容接口</option></select></label>
        <label>本机模型地址<input v-model="profile.model_endpoint" required placeholder="http://127.0.0.1:11434" /></label>
        <label>模型名称<input v-model="profile.model_name" maxlength="200" placeholder="填写已安装或已加载的模型名称" /></label>
        <label>上下文容量<input v-model="capacity" type="number" min="1" step="1" placeholder="未知时留空；Ollama 必填" /></label>
        <p>OpenAI 兼容服务请填写包含 /v1 的本机地址。本地模式不支持需要密钥的服务。</p>
      </template>
      <p>切换将停止当前任务并撤销完全访问授权。项目和任务始终留在本机；不同账号和本机身份的数据互相隔离，不自动合并。</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <button :disabled="busy" type="submit">{{ busy ? "正在切换…" : "保存并重新连接" }}</button>
    </form>
  </details>
</template>

<style scoped>
.connection-settings { margin: 12px 0; font-size: 13px; }
summary { cursor: pointer; }
form { display: grid; gap: 10px; padding: 12px 0; }
label { display: grid; gap: 4px; }
input, select, button { font: inherit; padding: 8px; border: 1px solid #b8bec8; border-radius: 6px; color: inherit; background: transparent; }
p { margin: 0; line-height: 1.5; }
[role="alert"] { color: #b42318; }
</style>
