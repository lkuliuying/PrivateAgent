<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { deleteDocument, importDocument, listDocuments, retryDocument } from "../api";
import type { DocumentItem } from "../types";

const docs = ref<DocumentItem[]>([]);
const uploading = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
let timer: ReturnType<typeof setInterval> | undefined;

async function load() {
  try {
    docs.value = await listDocuments();
  } catch {
    // 后端未连接
  }
}
onMounted(() => {
  load();
  timer = setInterval(load, 3000);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
});

async function onFile(e: Event) {
  const target = e.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;
  uploading.value = true;
  try {
    await importDocument(file);
    await load();
  } catch (err) {
    alert("导入失败：" + String(err));
  } finally {
    uploading.value = false;
    if (fileInput.value) fileInput.value.value = "";
  }
}

async function remove(id: number) {
  if (!confirm("确认删除该文档？将同步清理向量数据。")) return;
  try {
    await deleteDocument(id);
    await load();
  } catch (err) {
    alert("删除失败：" + String(err));
  }
}

async function retry(id: number) {
  try {
    await retryDocument(id);
    await load();
  } catch (err) {
    alert("重试失败：" + String(err));
  }
}

const STATUS_TEXT: Record<string, string> = {
  pending: "等待中",
  processing: "处理中",
  ready: "已就绪",
  failed: "失败",
  deleting: "删除中",
};
const STATUS_CLASS: Record<string, string> = {
  ready: "ok",
  failed: "bad",
  processing: "warn",
  pending: "warn",
  deleting: "warn",
};

function fmtSize(b: number | null): string {
  if (!b) return "-";
  if (b < 1024) return b + " B";
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + " KB";
  return (b / 1024 / 1024).toFixed(1) + " MB";
}
</script>

<template>
  <section class="content">
    <h1>知识库</h1>
    <p class="subtitle">导入本地文档（PDF / Word / Markdown / TXT），启用知识库后助手可基于资料回答并标注来源。</p>

    <div class="upload">
      <input ref="fileInput" type="file" accept=".pdf,.docx,.md,.markdown,.txt" @change="onFile" hidden />
      <button class="upload-btn" @click="fileInput?.click()" :disabled="uploading">
        {{ uploading ? "导入中…" : "+ 导入文档" }}
      </button>
      <span class="hint">支持 PDF / Word / MD / TXT（扫描件 PDF 暂不支持）</span>
    </div>

    <div v-if="docs.length === 0" class="empty">暂无文档，点击上方按钮导入</div>
    <div v-else class="doc-list">
      <div v-for="d in docs" :key="d.id" class="doc-item">
        <div class="doc-main">
          <div class="doc-name">{{ d.name }}</div>
          <div class="doc-meta">
            <span class="status" :class="STATUS_CLASS[d.status]">{{ STATUS_TEXT[d.status] || d.status }}</span>
            <span>{{ fmtSize(d.size_bytes) }}</span>
            <span v-if="d.chunk_count">切片 {{ d.chunk_count }}</span>
            <span v-if="d.embedding_model">{{ d.embedding_model }}</span>
          </div>
          <div v-if="d.error_message" class="doc-err">失败原因：{{ d.error_message }}</div>
        </div>
        <div class="doc-actions">
          <button v-if="d.status === 'failed'" class="retry-btn" @click="retry(d.id)">重试</button>
          <button class="del-btn" @click="remove(d.id)">删除</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.content {
  padding: 28px 32px;
  overflow: auto;
  flex: 1;
}
h1 {
  margin: 0 0 4px;
  font-size: 22px;
}
.subtitle {
  margin: 0 0 20px;
  color: #6a6b6e;
  font-size: 13px;
}
.upload {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 20px;
}
.upload-btn {
  background: #1a1b1e;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 14px;
  cursor: pointer;
}
.upload-btn:disabled {
  background: #c0c1c4;
  cursor: not-allowed;
}
.hint {
  font-size: 12px;
  color: #9a9b9e;
}
.empty {
  text-align: center;
  color: #9a9b9e;
  padding: 60px 0;
  font-size: 14px;
}
.doc-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.doc-item {
  background: #fff;
  border: 1px solid #e5e6e8;
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.doc-name {
  font-weight: 500;
  font-size: 14px;
  word-break: break-all;
}
.doc-meta {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: #6a6b6e;
  margin-top: 4px;
  flex-wrap: wrap;
}
.status {
  font-weight: 500;
}
.status.ok {
  color: #2e7d32;
}
.status.bad {
  color: #c62828;
}
.status.warn {
  color: #e65100;
}
.doc-err {
  font-size: 12px;
  color: #c62828;
  margin-top: 4px;
}
.doc-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.retry-btn,
.del-btn {
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
  border: 1px solid #d8d9da;
  background: #fff;
}
.retry-btn {
  color: #1565c0;
}
.del-btn {
  color: #c62828;
}
.retry-btn:hover,
.del-btn:hover {
  background: #f0f1f3;
}
</style>
