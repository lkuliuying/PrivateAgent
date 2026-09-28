<script setup lang="ts">
import { computed, ref, watch } from "vue";
const props = defineProps<{ content: string; path: string; version: string; offset?: number }>();
const emit = defineEmits<{ feedback: [message: string] }>();
const selected = ref<{ line: number | null; side: string } | null>(null), comment = ref("");
const lines = computed(() => {
  let oldLine: number | null = null, newLine: number | null = null;
  return props.content.split("\n").map(text => {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(text);
    if (hunk) { oldLine = Number(hunk[1]); newLine = Number(hunk[2]); return { text, line: null, side: "说明" }; }
    const side = text.startsWith("-") && !text.startsWith("---") ? "修改前" : "修改后";
    let line: number | null = null;
    if (oldLine !== null && newLine !== null) {
      if (text.startsWith("-")) { line = oldLine; oldLine++; }
      else if (text.startsWith("+")) { line = newLine; newLine++; }
      else if (text.startsWith(" ")) { line = newLine; oldLine++; newLine++; }
    }
    return { text, line, side };
  });
});
watch(() => [props.path, props.version, props.offset], () => { selected.value = null; comment.value = ""; });
function submit() {
  if (!comment.value.trim()) return;
  const location = selected.value?.line ? `${selected.value.side}第 ${selected.value.line} 行` : "文件级反馈";
  emit("feedback", `请核对以下审阅反馈，确认当前文件版本后处理并验证：\n文件：${props.path}\n位置：${location}\n审阅版本：${props.version}\n反馈：${comment.value.trim()}`);
  comment.value = ""; selected.value = null;
}
</script>
<template><div class="diff-feedback"><div class="diff-lines" tabindex="0" aria-label="文件差异"><div v-for="(row, index) in lines" :key="index" :class="{ added: row.text.startsWith('+'), removed: row.text.startsWith('-') }"><button v-if="row.line !== null" type="button" :aria-label="`反馈${row.side}第 ${row.line} 行`" @click="selected = row">{{ row.line }}</button><span v-else class="line-space" /><code>{{ row.text }}</code></div></div><button class="pa-btn pa-btn--ghost pa-btn--sm" @click="selected = { line: null, side: '文件' }">添加文件反馈</button><form v-if="selected" @submit.prevent="submit"><label>{{ selected.line ? `${selected.side}第 ${selected.line} 行` : '文件反馈' }}<textarea v-model="comment" class="pa-input" rows="3" maxlength="6000" autofocus placeholder="描述问题及期望行为…" /></label><button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="!comment.trim()">添加到任务输入</button><button type="button" class="pa-btn pa-btn--ghost pa-btn--sm" @click="selected = null">取消</button></form></div></template>
<style scoped>.diff-lines { max-height: 48vh; overflow: auto; font-size: 12px; background: var(--color-bg); }.diff-lines > div { display: flex; align-items: baseline; min-height: 21px; min-width: max-content; }.diff-lines button, .line-space { width: 42px; min-width: 42px; font-size: 11px; text-align: right; padding-right: 8px; color: var(--color-fg-muted); border: 0; background: transparent; }.diff-lines button { cursor: pointer; }.diff-lines button:hover { background: var(--color-accent-soft); }.diff-lines code { white-space: pre; padding-right: 12px; }.added { background: color-mix(in srgb, #27965e 10%, transparent); }.removed { background: color-mix(in srgb, #d65757 10%, transparent); }form { display: flex; flex-wrap: wrap; gap: 8px; }form label { width: 100%; font-size: 13px; }textarea { display: block; width: 100%; margin-top: 6px; }</style>
