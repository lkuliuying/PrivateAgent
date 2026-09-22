<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  cmdCheckForUpdates,
  cmdDownloadAndInstallUpdate,
  cmdRelaunchApp,
  cmdGetUpdateConfiguration,
  type UpdateInfo,
  type UpdateConfiguration,
} from "../api";
import { useNotifications } from "../stores/notifications";

const { confirm } = useNotifications();
const checking = ref(false);
const confirming = ref(false);
const installing = ref(false);
const loading = ref(true);
const configuration = ref<UpdateConfiguration | null>(null);
const busy = computed(() => loading.value || checking.value || confirming.value || installing.value);
const update = ref<UpdateInfo | null>(null);
const upToDate = ref(false);
const error = ref("");
const errorDetail = ref("");
const note = ref("");
let disposed = false;
onBeforeUnmount(() => { disposed = true; });

async function loadConfiguration(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const result = await cmdGetUpdateConfiguration();
    if (disposed) return;
    configuration.value = result;
  } catch (cause) {
    if (!disposed) error.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    if (!disposed) loading.value = false;
  }
}
onMounted(loadConfiguration);

type ErrorKind = "network" | "manifest" | "signature" | "configuration" | "unknown";

/** 优先识别签名和下载错误，避免被通用的清单错误分支掩盖。 */
function classifyUpdateError(e: unknown): { kind: ErrorKind; message: string; detail: string } {
  const raw = e instanceof Error ? e.message : String(e);
  const s = raw.toLowerCase();
  let kind: ErrorKind = "unknown";
  if (s.includes("endpoints") || s.includes("更新地址") || s.includes("未配置更新源")) {
    kind = "configuration";
  } else if (
    s.includes("signature") ||
    s.includes("signing") ||
    s.includes("verify") ||
    // verify_signature() surfaces base64-decode (Error::Base64) and minisign-decode
    // (Error::Minisign::InvalidEncoding) failures whose Display strings contain
    // "invalid" but NOT "signature"/"verify" -- catch them here before the manifest
    // bucket's "invalid" keyword, so a malformed/tampered signature is reported as such.
    s.includes("minisign") ||
    s.includes("invalid symbol") ||
    s.includes("invalid last symbol") ||
    s.includes("invalid padding") ||
    s.includes("invalid input length") ||
    s.includes("could not be decoded")
  ) {
    kind = "signature";
  } else if (
    s.includes("network") ||
    s.includes("download request failed") || // binary-download HTTP failure (e.g. 404 on the asset), not a manifest problem
    s.includes("failed to fetch") ||
    s.includes("sending request") ||
    s.includes("dns") ||
    s.includes("connect") ||
    s.includes("timeout") ||
    s.includes("timed out") ||
    s.includes("refused") ||
    s.includes("unreachable") ||
    s.includes("proxy")
  ) {
    kind = "network";
  } else if (
    s.includes("manifest") ||
    s.includes("更新清单") ||
    s.includes("json") ||
    s.includes("parse") ||
    s.includes("deserialize") ||
    s.includes("404") ||
    s.includes("not found") ||
    s.includes("version") ||
    s.includes("invalid")
  ) {
    kind = "manifest";
  }
  const messages: Record<ErrorKind, string> = {
    configuration: "自动更新服务尚未就绪，请等待发布方提供更新。",
    network: "无法连接更新服务器或下载安装包。请检查网络后重试。",
    manifest: "更新清单 (latest.json) 无效或未找到。可能是发布源尚未部署或版本号配置错误。",
    signature: "更新签名验证失败。安装包可能被篡改或签名密钥不匹配，已拒绝更新。",
    unknown: "操作失败，请稍后重试或手动下载新版本。",
  };
  return { kind, message: messages[kind], detail: kind === "configuration" ? "" : raw };
}

async function check() {
  if (busy.value || disposed || !configuration.value) return;
  checking.value = true;
  update.value = null;
  upToDate.value = false;
  error.value = "";
  errorDetail.value = "";
  note.value = "";
  try {
    if (!configuration.value.endpoint?.trim()) throw new Error("未配置更新源");
    const res = await cmdCheckForUpdates();
    if (disposed) return;
    if (res) {
      update.value = res;
    } else {
      upToDate.value = true;
    }
  } catch (e) {
    if (disposed) return;
    const c = classifyUpdateError(e);
    error.value = c.message;
    errorDetail.value = c.detail;
  } finally {
    checking.value = false;
  }
}

async function install() {
  if (busy.value || disposed || !update.value) return;
  const version = update.value.version;
  confirming.value = true;
  try {
    const accepted = await confirm({
      title: `安装 PrivateAgent v${version}？`,
      message: "下载并验证签名后，客户端将退出并安装新版。请先保存输入并结束正在进行的任务。",
      impact: "安装完成后重新打开应用，项目文件与本机记录会保留。",
      confirmLabel: "下载并安装",
      cancelLabel: "稍后更新",
    });
    if (!accepted || disposed) return;
  } finally {
    confirming.value = false;
  }
  installing.value = true;
  note.value = "";
  error.value = "";
  errorDetail.value = "";
  try {
    // 原生层核对同一更新源、版本与签名，再停止执行器并安装。
    try {
      await cmdDownloadAndInstallUpdate(version);
    } catch (e) {
      const c = classifyUpdateError(e);
      // 安装阶段失败不能显示成功提示；保留重试入口。
      error.value = c.kind === "signature" || c.kind === "network" ? c.message : "安装失败，请稍后重试或手动下载新版本。";
      errorDetail.value = c.detail;
      return;
    }
    // 重启失败时撤销成功提示，避免同时呈现相互矛盾的状态。
    note.value = "下载安装完成，正在重启…";
    try {
      await cmdRelaunchApp();
    } catch (e) {
      note.value = "";
      error.value = "更新已安装，但自动重启失败，请手动重启应用。";
      errorDetail.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    installing.value = false;
  }
}
</script>

<template>
  <div class="update-box">
    <p v-if="loading" role="status" class="msg">正在读取更新配置…</p>
    <p v-if="configuration" class="msg">当前版本：v{{ configuration.version }}</p>
    <div class="row">
      <button v-if="!loading && !configuration" class="ghost-btn" @click="loadConfiguration">重新读取更新配置</button>
      <button v-else class="ghost-btn" @click="check" :disabled="busy || !configuration">
        {{ checking ? "检查中…" : "检查更新" }}
      </button>
      <button
        v-if="update"
        class="primary-btn"
        @click="install"
        :disabled="busy"
      >
        {{ installing ? "下载、验证并安装中…" : `下载并安装 v${update.version}` }}
      </button>
    </div>

    <p v-if="upToDate" class="msg ok">✓ 当前已是最新版本。</p>
    <p v-if="error" class="msg err" role="alert">
      ⚠ {{ error }}
      <span v-if="errorDetail" class="hint">（{{ errorDetail }}）</span>
    </p>
    <p v-if="note" class="msg ok">{{ note }}</p>

    <div v-if="update" class="update-info">
      <div><span class="k">新版本</span><span class="v">v{{ update.version }}</span></div>
      <div v-if="update.date"><span class="k">发布时间</span><span class="v">{{ update.date }}</span></div>
      <div v-if="update.body" class="body">{{ update.body }}</div>
    </div>
  </div>
</template>

<style scoped>
.update-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.msg { overflow-wrap: anywhere; }
.ghost-btn {
  background: var(--color-surface);
  color: var(--color-fg);
  border: 1px solid var(--color-border-strong);
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 14px;
  cursor: pointer;
}
.ghost-btn:disabled {
  color: var(--color-fg-disabled);
  cursor: not-allowed;
}
.primary-btn {
  background: var(--pa-btn-primary-bg);
  color: var(--color-accent-fg);
  border: none;
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 14px;
  cursor: pointer;
}
.primary-btn:disabled {
  background: var(--color-fg-disabled);
  cursor: not-allowed;
}
.msg {
  font-size: 13px;
  margin: 0;
}
.msg.ok {
  color: var(--color-success-fg);
}
.msg.err {
  color: var(--color-danger-fg);
}
.hint {
  color: var(--color-fg-subtle);
  font-size: 12px;
}
.update-info {
  padding: 12px 14px;
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.k {
  display: inline-block;
  font-size: 12px;
  color: var(--color-fg-subtle);
  width: 64px;
}
.v {
  font-size: 14px;
}
.body {
  font-size: 13px;
  color: var(--color-fg-muted);
  white-space: pre-wrap;
  border-top: 1px solid var(--color-border);
  padding-top: 6px;
  margin-top: 2px;
}
</style>
