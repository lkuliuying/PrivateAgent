<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef } from "vue";
import { PhImage, PhArrowCounterClockwise } from "@phosphor-icons/vue";
import { PaSwitch } from "../design";
import { wallpaperTheme } from "../services/wallpaperTheme/controller";
import { processWallpaper, type WallpaperImage } from "../services/wallpaperTheme/image";
import { themeVariables } from "../services/wallpaperTheme/palette";
import { useNotifications } from "../stores/notifications";

const { saved, imageUrl, enabled, loading, busy, error } = wallpaperTheme;
const notify = useNotifications();
const input = ref<HTMLInputElement>();
const draft = shallowRef<WallpaperImage | null>(null);
const draftUrl = ref("");
const processing = ref(false);
const selectionError = ref("");
let selection: AbortController | undefined;
const preview = computed(() => draft.value ?? saved.value);
const previewUrl = computed(() => draftUrl.value || imageUrl.value);
const previewVariables = computed(() => preview.value ? themeVariables(preview.value.palette) : {});
const locked = computed(() => busy.value || loading.value);

function clearDraft() {
  selection?.abort();
  selection = undefined;
  processing.value = false;
  draft.value = null;
  if (draftUrl.value) URL.revokeObjectURL(draftUrl.value);
  draftUrl.value = "";
}

async function selectImage(event: Event) {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  target.value = "";
  if (!file || locked.value) return;
  clearDraft();
  const current = new AbortController();
  selection = current;
  selectionError.value = "";
  processing.value = true;
  try {
    const result = await processWallpaper(file, current.signal);
    if (current.signal.aborted || selection !== current) return;
    draftUrl.value = URL.createObjectURL(result.blob);
    draft.value = result;
  } catch (cause) {
    if (current.signal.aborted || selection !== current) return;
    selectionError.value = cause instanceof Error ? cause.message : "无法处理图片，请重新选择。";
    notify.error("壁纸读取失败", selectionError.value);
  } finally {
    if (selection === current) processing.value = false;
  }
}

async function apply() {
  if (!draft.value || processing.value) return;
  if (await wallpaperTheme.apply(draft.value)) {
    clearDraft();
    notify.success("壁纸主题已应用");
  } else if (error.value) notify.error("壁纸主题未保存", error.value);
}

async function toggle(value: boolean) {
  if (locked.value) return;
  if (await wallpaperTheme.setEnabled(value)) notify.success(value ? "壁纸主题已启用" : "已恢复原有外观，壁纸已保留");
  else if (error.value) notify.error("壁纸主题未保存", error.value);
}

async function reset() {
  if (await wallpaperTheme.reset()) {
    clearDraft();
    selectionError.value = "";
    notify.success("已恢复默认外观");
  } else if (error.value) notify.error("无法恢复默认", error.value);
}

onBeforeUnmount(clearDraft);
</script>

<template>
  <section class="plugin-page" aria-labelledby="wallpaper-title" data-testid="wallpaper-plugin">
    <article class="wallpaper-card" :aria-busy="processing || locked" aria-labelledby="wallpaper-title">
      <header class="wallpaper-heading">
        <div class="wallpaper-title"><PhImage :size="24" aria-hidden="true" /><div><h2 id="wallpaper-title">壁纸主题</h2><p>图片与自动配色</p></div></div>
        <PaSwitch :model-value="enabled" label="启用壁纸主题" :disabled="!saved || loading" :aria-disabled="busy" @update:model-value="toggle" />
      </header>
      <p class="wallpaper-description">选择一张喜欢的图片，自动搭配全局配色和明暗外观。页面布局与功能保持不变。</p>
      <div class="wallpaper-preview" :style="previewVariables" data-testid="wallpaper-preview">
        <img v-if="previewUrl" :src="previewUrl" alt="壁纸预览" />
        <div v-if="preview" class="wallpaper-sample"><span>配色预览</span><strong>{{ preview.palette.mode === 'dark' ? '深色主题' : '浅色主题' }}</strong><span class="wallpaper-sample-action">强调色</span></div>
        <div v-else class="wallpaper-empty"><PhImage :size="32" aria-hidden="true" /><span>选择图片，预览你的工作区配色</span></div>
      </div>
      <div v-if="preview" class="wallpaper-details">
        <span class="wallpaper-name" :title="preview.name">{{ preview.name }}</span>
        <div class="wallpaper-swatches" aria-label="主题配色"><span v-for="(color, label) in { 背景: preview.palette.colors.surface, 文字: preview.palette.colors.text, 强调色: preview.palette.colors.accent }" :key="label" :style="{ background: color }" :title="`${label} ${color}`" /></div>
      </div>
      <p class="wallpaper-status" role="status">{{ loading ? '正在读取本机主题…' : processing ? '正在处理图片…' : draft ? '预览尚未保存，应用后全局生效。' : enabled ? '已应用 · 全局生效' : saved ? '已停用，壁纸已保留。' : '尚未启用，当前使用默认外观。' }}</p>
      <p v-if="selectionError || error" class="wallpaper-error" role="alert">{{ selectionError || error }}</p>
      <div class="wallpaper-actions">
        <input ref="input" class="wallpaper-file" type="file" accept="image/png,image/jpeg,image/webp" aria-label="选择壁纸文件" :disabled="locked" @change="selectImage" />
        <button type="button" class="pa-btn" :disabled="locked" @click="input?.click()">{{ preview ? '更换图片' : '选择图片' }}</button>
        <button type="button" class="pa-btn pa-btn--primary" :disabled="!draft || processing || locked" @click="apply">{{ busy ? '正在保存…' : '应用主题' }}</button>
        <button type="button" class="pa-btn pa-btn--ghost wallpaper-reset" :disabled="locked || (!saved && !draft && !error)" @click="reset"><PhArrowCounterClockwise :size="16" aria-hidden="true" />恢复默认</button>
      </div>
      <p class="wallpaper-note">PNG、JPG、WebP，最大 10 MB。图片仅保存在本机，不上传或跨设备同步；恢复默认不会删除原图。</p>
    </article>
  </section>
</template>

<style scoped>
.plugin-page { min-width: 0; color: var(--color-fg); }
.wallpaper-heading p { margin: 0; color: var(--color-fg-muted); }
.wallpaper-card { min-width: 0; }
.wallpaper-heading, .wallpaper-title, .wallpaper-details, .wallpaper-actions { display: flex; align-items: center; gap: var(--space-3); }
.wallpaper-heading, .wallpaper-details { justify-content: space-between; flex-wrap: wrap; }
.wallpaper-title > svg { color: var(--color-accent); }
.wallpaper-heading :deep(.pa-switch[aria-disabled="true"]) { cursor: wait; }
.wallpaper-title h2 { margin: 0 0 var(--space-1); font-size: var(--pa-text-section); }
.wallpaper-heading p, .wallpaper-note { font-size: var(--pa-text-meta); }
.wallpaper-description { margin: var(--space-5) 0; color: var(--color-fg-muted); line-height: var(--leading-normal); }
.wallpaper-preview { position: relative; height: 240px; overflow: hidden; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface-muted); }
.wallpaper-preview img { width: 100%; height: 100%; object-fit: cover; }
.wallpaper-sample { position: absolute; inset: auto var(--space-4) var(--space-4); display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-3); padding: var(--space-4); background: var(--wallpaper-panel); color: var(--color-fg); border: 1px solid var(--color-border); border-radius: var(--radius-md); }
.wallpaper-sample > span:first-child { color: var(--color-fg-muted); }
.wallpaper-sample-action { margin-left: auto; padding: var(--space-1) var(--space-3); background: var(--color-accent); color: var(--color-accent-fg); border-radius: var(--radius); }
.wallpaper-empty { display: flex; height: 100%; flex-direction: column; justify-content: center; align-items: center; gap: var(--space-3); color: var(--color-fg-muted); text-align: center; padding: var(--space-4); }
.wallpaper-details { margin-top: var(--space-3); }
.wallpaper-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; color: var(--color-fg-muted); }
.wallpaper-swatches { display: flex; gap: var(--space-2); }
.wallpaper-swatches span { width: 18px; height: 18px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-full); }
.wallpaper-status { color: var(--color-fg-muted); min-height: 21px; margin: var(--space-4) 0; }
.wallpaper-error { color: var(--color-danger-fg); background: var(--color-danger-soft); padding: var(--space-3); border-radius: var(--radius); }
.wallpaper-actions { flex-wrap: wrap; }
.wallpaper-reset { margin-left: auto; }
.wallpaper-file { display: none; }
.wallpaper-note { margin: var(--space-4) 0 0; color: var(--color-fg-subtle); line-height: var(--leading-normal); }
@media (max-width: 640px) { .wallpaper-reset { margin-left: 0; } }
</style>
