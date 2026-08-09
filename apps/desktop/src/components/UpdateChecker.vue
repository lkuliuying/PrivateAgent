<script setup lang="ts">
import { ref } from "vue";
import {
  cmdCheckForUpdates,
  cmdDownloadAndInstallUpdate,
  cmdRelaunchApp,
  type UpdateInfo,
} from "../api";

const checking = ref(false);
const installing = ref(false);
const update = ref<UpdateInfo | null>(null);
const upToDate = ref(false);
const error = ref("");
const errorDetail = ref("");
const note = ref("");

type ErrorKind = "network" | "manifest" | "signature" | "unknown";

/** Classify an updater error string into a user-facing category with a next step.
 *  Tauri plugin errors are strings: network/manifest failures surface at check(),
 *  signature failures surface at download_and_install(). Keyword ordering matters:
 *  signature is checked first (so base64/minisign decode errors like "invalid symbol"
 *  are not swallowed by the manifest bucket's "invalid"), and binary-download HTTP
 *  failures ("download request failed with status: 404") are matched as network
 *  before the manifest bucket's "404". */
function classifyUpdateError(e: unknown): { kind: ErrorKind; message: string; detail: string } {
  const raw = e instanceof Error ? e.message : String(e);
  const s = raw.toLowerCase();
  let kind: ErrorKind = "unknown";
  if (
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
    network: "无法连接更新服务器。请检查网络后重试（自动更新需访问 GitHub Release）。",
    manifest: "更新清单 (latest.json) 无效或未找到。可能是发布源尚未部署或版本号配置错误。",
    signature: "更新签名验证失败。安装包可能被篡改或签名密钥不匹配，已拒绝更新。",
    unknown: "操作失败，请稍后重试或手动下载新版本。",
  };
  return { kind, message: messages[kind], detail: raw };
}

async function check() {
  checking.value = true;
  update.value = null;
  upToDate.value = false;
  error.value = "";
  errorDetail.value = "";
  note.value = "";
  try {
    const res = await cmdCheckForUpdates();
    if (res) {
      update.value = res;
    } else {
      upToDate.value = true;
    }
  } catch (e) {
    const c = classifyUpdateError(e);
    error.value = c.message;
    errorDetail.value = c.detail;
  } finally {
    checking.value = false;
  }
}

async function install() {
  installing.value = true;
  note.value = "";
  error.value = "";
  errorDetail.value = "";
  try {
    // 1) download + install (signature is verified here; sidecar is killed first by Rust).
    try {
      await cmdDownloadAndInstallUpdate();
    } catch (e) {
      const c = classifyUpdateError(e);
      // Manifest was already validated during check(); an install-time failure is a
      // download/signature/unknown problem, so only signature/network get their own
      // wording -- never the manifest-invalid message.
      error.value = c.kind === "signature" || c.kind === "network" ? c.message : "安装失败，请稍后重试或手动下载新版本。";
      errorDetail.value = c.detail;
      return;
    }
    // 2) install succeeded -- relaunch. A relaunch failure must clear the success note
    // so we never render a green "下载安装完成" next to a red error.
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
    <div class="row">
      <button class="ghost-btn" @click="check" :disabled="checking">
        {{ checking ? "检查中…" : "检查更新" }}
      </button>
      <button
        v-if="update"
        class="primary-btn"
        @click="install"
        :disabled="installing"
      >
        {{ installing ? "安装中…" : `下载并安装 v${update.version}` }}
      </button>
    </div>

    <p v-if="upToDate" class="msg ok">✓ 当前已是最新版本。</p>
    <p v-if="error" class="msg err">
      ⚠ {{ error }}
      <span v-if="errorDetail" class="hint">（{{ errorDetail }}）</span>
      <span class="hint">详见 docs/archive/phases/phase5-plan.md 与 docs/signing-and-keys.md</span>
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
  gap: 10px;
}
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
