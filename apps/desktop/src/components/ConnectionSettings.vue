<script setup lang="ts">
import { ref } from "vue";
import { isTauri } from "@tauri-apps/api/core";
import { defaultConnectionProfile, getConnectionProfile, saveConnectionProfile, validateConnectionProfile, modelConfigurationError } from "../services/connectionProfile";
import { stopLocalExecutor } from "../services/localExecutor";

const available = isTauri();
const expanded = ref(false);
const busy = ref(false);
const error = ref("");
let initial = defaultConnectionProfile();
try { initial = getConnectionProfile(); } catch { expanded.value = true; }
error.value = modelConfigurationError();
const profile = ref({ ...initial });
const capacity = ref(initial.context_tokens === null ? "" : String(initial.context_tokens));

async function apply(): Promise<void> {
  error.value = "";
  busy.value = true;
  try {
    const selected = validateConnectionProfile({ ...profile.value, context_tokens: capacity.value.trim() ? Number(capacity.value) : null });
    if (selected.inference_mode === "local" && !selected.model_name) throw new Error("请填写本机模型名称");
    if (selected.inference_mode === "local" && selected.model_protocol === "ollama" && selected.context_tokens === null) throw new Error("请填写 Ollama 上下文容量");
    // 停止任务并撤销授权后更换模型，服务器账号及 SQLite 所有者保持不变。
    await stopLocalExecutor();
    saveConnectionProfile(selected);
    window.location.reload();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "模型配置保存失败";
  } finally { busy.value = false; }
}
</script>

<template>
  <details v-if="available" class="connection-settings" :open="expanded">
    <summary>模型执行设置</summary>
    <form @submit.prevent="apply">
      <label>模型执行位置<select v-model="profile.inference_mode"><option value="service">使用服务器模型</option><option value="local">使用本机模型</option></select></label>
      <template v-if="profile.inference_mode === 'local'">
        <label>本机模型协议<select v-model="profile.model_protocol"><option value="ollama">Ollama</option><option value="openai">OpenAI 兼容接口</option></select></label>
        <label>本机模型地址<input v-model="profile.model_endpoint" required type="url" placeholder="http://127.0.0.1:11434" /></label>
        <label>模型名称<input v-model="profile.model_name" required maxlength="200" placeholder="填写已安装或已加载的模型名称" /></label>
        <label>上下文容量<input v-model="capacity" type="number" min="1" step="1" placeholder="未知时留空；Ollama 必填" /></label>
        <p>仅支持本机回环服务；OpenAI 兼容接口请包含 /v1。目前不支持需要密钥的本机模型。</p>
      </template>
      <p>始终使用服务器账号登录。保存将停止当前任务并撤销授权，账号、项目与任务记录保持不变。</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <button :disabled="busy" type="submit">{{ busy ? "正在保存…" : "保存并重新连接" }}</button>
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
