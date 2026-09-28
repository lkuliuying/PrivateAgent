<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import { listSkills, type LocalSkill } from "../api/skills";
const props = defineProps<{ projectId: number }>();
const emit = defineEmits<{ choose: [id: string] }>();
const skills = ref<LocalSkill[]>([]), error = ref("");
const loading = ref(false);
const panel = ref<HTMLElement>();
let controller: AbortController | undefined;
watch(() => props.projectId, async id => {
  controller?.abort(); const current = new AbortController(); controller = current;
  skills.value = []; error.value = "";
  loading.value = true;
  try {
    const result = await listSkills(id, current.signal);
    if (!current.signal.aborted) {
      skills.value = result.items.filter(item => item.enabled);
      await nextTick();
      panel.value?.querySelector<HTMLButtonElement>("button")?.focus();
    }
  }
  catch { if (!current.signal.aborted) error.value = "技能目录暂不可用"; }
  finally { if (!current.signal.aborted) loading.value = false; }
}, { immediate: true });
onBeforeUnmount(() => controller?.abort());
</script>
<template><div ref="panel" class="skill-picker"><span v-if="loading" role="status">正在读取技能…</span><span v-else-if="error" role="alert">{{ error }}</span><span v-else-if="!skills.length">在插件 → Skills 中启用技能，然后输入 /skill 选择。</span><button v-for="item in skills" :key="item.id" type="button" class="pa-btn pa-btn--ghost" :title="item.description" @click="emit('choose', item.id)">{{ item.name }}</button></div></template>
<style scoped>.skill-picker { display: flex; flex-wrap: wrap; gap: 6px; max-width: 500px; padding: 10px; font-size: 12px; color: var(--color-fg-muted); }</style>
