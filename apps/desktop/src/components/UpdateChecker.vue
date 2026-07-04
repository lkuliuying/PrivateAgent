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
const note = ref("");

async function check() {
  checking.value = true;
  update.value = null;
  upToDate.value = false;
  error.value = "";
  note.value = "";
  try {
    const res = await cmdCheckForUpdates();
    if (res) {
      update.value = res;
    } else {
      upToDate.value = true;
    }
  } catch (e) {
    // updater 未配置（无发布源/公钥）时也会走到这里。
    error.value = String(e);
  } finally {
    checking.value = false;
  }
}

async function install() {
  installing.value = true;
  note.value = "";
  error.value = "";
  try {
    await cmdDownloadAndInstallUpdate();
    note.value = "下载安装完成，正在重启…";
    await cmdRelaunchApp();
  } catch (e) {
    error.value = "安装失败：" + String(e);
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
      <span class="hint">（自动更新需配置发布源与签名公钥，见 docs/phase5-installer-updater.md）</span>
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
  background: #fff;
  color: #1a1b1e;
  border: 1px solid #d8d9da;
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 14px;
  cursor: pointer;
}
.ghost-btn:disabled {
  color: #c0c1c4;
  cursor: not-allowed;
}
.primary-btn {
  background: #1a1b1e;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 14px;
  cursor: pointer;
}
.primary-btn:disabled {
  background: #c0c1c4;
  cursor: not-allowed;
}
.msg {
  font-size: 13px;
  margin: 0;
}
.msg.ok {
  color: #2e7d32;
}
.msg.err {
  color: #b71c1c;
}
.hint {
  color: #9a9b9e;
  font-size: 12px;
}
.update-info {
  padding: 12px 14px;
  background: #fafafa;
  border: 1px solid #e5e6e8;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.k {
  display: inline-block;
  font-size: 12px;
  color: #9a9b9e;
  width: 64px;
}
.v {
  font-size: 14px;
}
.body {
  font-size: 13px;
  color: #545659;
  white-space: pre-wrap;
  border-top: 1px solid #eee;
  padding-top: 6px;
  margin-top: 2px;
}
</style>
