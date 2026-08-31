<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import {
  getServiceLogSources, getServiceLogTail,
  type ServiceLogSource, type ServiceLogTail,
} from '../services/adminLogs';
import { formatAdminDateTime, PRODUCT_TIMEZONE } from '../services/timeDisplay';

const sources = ref<ServiceLogSource[]>([]);
const selected = ref('');
const lineCount = ref(200);
const search = ref('');
const autoRefresh = ref(false);
const busy = ref(false);
const error = ref('');
const snapshot = ref<ServiceLogTail | null>(null);
let controller: AbortController | undefined;
let catalogController: AbortController | undefined;
let sequence = 0;
let disposed = false;
let timer: ReturnType<typeof setInterval> | undefined;

const content = computed(() => snapshot.value?.lines.join('\n') || '当前范围没有日志记录');
const updatedAt = computed(() => formatAdminDateTime(snapshot.value?.generated_at));

/** 切换日志类型会取消旧请求，避免旧日志覆盖当前选择。 */
async function loadTail(): Promise<void> {
  if (!selected.value || disposed) return;
  controller?.abort();
  controller = new AbortController();
  const current = ++sequence;
  busy.value = true;
  error.value = '';
  snapshot.value = null;
  try {
    const result = await getServiceLogTail(selected.value, lineCount.value, search.value.trim(), controller.signal);
    if (!disposed && current === sequence) snapshot.value = result;
  } catch (reason) {
    if (!disposed && current === sequence && !controller.signal.aborted) {
      error.value = reason instanceof Error ? reason.message : '日志读取失败';
    }
  } finally {
    if (!disposed && current === sequence) busy.value = false;
  }
}

/** 初始化固定来源；失败时保留重试入口，不自动扩大文件权限。 */
async function loadSources(): Promise<void> {
  catalogController?.abort();
  const current = new AbortController();
  catalogController = current;
  busy.value = true;
  error.value = '';
  try {
    const result = await getServiceLogSources(current.signal);
    if (disposed || current.signal.aborted) return;
    sources.value = result;
    selected.value = result.find(source => source.available)?.id || result[0]?.id || '';
    if (!selected.value) error.value = '服务器没有可用的日志来源';
  } catch (reason) {
    if (!disposed && !current.signal.aborted) error.value = reason instanceof Error ? reason.message : '日志来源加载失败';
  } finally {
    if (!disposed && !current.signal.aborted) busy.value = false;
  }
}

function refresh(): void {
  if (sources.value.length) void loadTail();
  else void loadSources();
}

watch([selected, lineCount], () => { void loadTail(); });
watch(autoRefresh, enabled => {
  if (timer) clearInterval(timer);
  timer = enabled ? setInterval(() => {
    if (!busy.value) refresh();
  }, 5000) : undefined;
});
onMounted(() => { void loadSources(); });
onBeforeUnmount(() => {
  disposed = true;
  sequence += 1;
  controller?.abort();
  catalogController?.abort();
  if (timer) clearInterval(timer);
  snapshot.value = null;
});
</script>

<template>
  <section class="admin-logs" aria-label="服务器日志">
    <form class="admin-logs__toolbar" @submit.prevent="refresh">
      <label>日志来源
        <select v-model="selected" class="pa-input" aria-label="日志来源">
          <option v-for="source in sources" :key="source.id" :value="source.id">
            {{ source.label }}{{ source.available ? '' : '（暂不可读）' }}
          </option>
        </select>
      </label>
      <label>显示行数
        <select v-model.number="lineCount" class="pa-input" aria-label="显示行数">
          <option :value="100">最近 100 行</option>
          <option :value="200">最近 200 行</option>
          <option :value="500">最近 500 行</option>
          <option :value="1000">最近 1,000 行</option>
        </select>
      </label>
      <label class="admin-logs__search">筛选当前日志尾部
        <input v-model="search" class="pa-input" maxlength="100" placeholder="例如：422、ERROR、/projects" aria-label="日志关键字" />
      </label>
      <button type="submit" class="pa-btn pa-btn--primary" :disabled="busy">{{ busy ? '读取中…' : '刷新 / 筛选' }}</button>
      <label class="admin-logs__auto"><input v-model="autoRefresh" type="checkbox" />每 5 秒刷新</label>
    </form>
    <p class="admin-logs__notice">仅管理员可见 · 只读 · 每次最多扫描日志尾部 256 KB；凭据相关行与 URL 查询参数会隐藏。不是完整日志搜索。</p>
    <div v-if="error" class="admin-logs__error" role="alert">{{ error }}</div>
    <div v-else-if="busy" class="admin-logs__empty" role="status">正在读取日志…</div>
    <pre v-else class="admin-logs__output" aria-label="日志内容" tabindex="0">{{ content }}</pre>
    <footer class="admin-logs__footer">
      <span>更新时间：{{ updatedAt }}（{{ PRODUCT_TIMEZONE }}）</span>
      <span v-if="snapshot?.truncated">已截取最近记录；更早日志未返回</span>
      <span v-if="snapshot">{{ snapshot.lines.length }} 行 · 扫描 {{ Math.ceil(snapshot.scanned_bytes / 1024) }} KB</span>
    </footer>
  </section>
</template>

<style scoped>
.admin-logs { border: 1px solid var(--color-border, #e2e8f0); border-radius: 10px; background: var(--color-panel, #fff); overflow: hidden; }
.admin-logs__toolbar { display: flex; align-items: end; flex-wrap: wrap; gap: 14px; padding: 20px; }
.admin-logs__toolbar label { display: flex; flex-direction: column; gap: 7px; font-size: 12px; }
.admin-logs__search { flex: 1; min-width: 210px; }
.admin-logs__toolbar .admin-logs__auto { flex-direction: row; align-items: center; align-self: center; }
.admin-logs__notice { margin: 0; padding: 0 20px 16px; color: var(--color-text-muted, #64748b); font-size: 12px; line-height: 1.6; }
.admin-logs__output { margin: 0; padding: 18px 20px; min-height: 280px; max-height: 58vh; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; background: #111827; color: #e2e8f0; font: 12px/1.7 Consolas, monospace; }
.admin-logs__error, .admin-logs__empty { padding: 30px 20px; min-height: 240px; }
.admin-logs__error { color: #b42318; }
.admin-logs__footer { display: flex; gap: 16px; flex-wrap: wrap; justify-content: space-between; padding: 12px 20px; font-size: 12px; color: var(--color-text-muted, #64748b); }
</style>
