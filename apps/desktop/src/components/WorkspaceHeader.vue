<script setup lang="ts">
import { PhBell, PhCaretDown } from "@phosphor-icons/vue";
import { useLocalProfile } from "../services/localProfile";
import { useNotifications } from "../stores/notifications";
import defaultAvatar from "../assets/companion/default-avatar.png";
defineProps<{ title: string }>();
const emit = defineEmits<{ profile: [] }>();
const { profile } = useLocalProfile();
const notifications = useNotifications();
</script>

<template>
  <header class="workspace-header">
    <span class="workspace-header__title">{{ title }}</span>
    <div class="workspace-header__actions">
      <button type="button" class="workspace-header__notification" aria-label="通知" @click="notifications.openCenter()">
        <PhBell :size="20" aria-hidden="true" />
        <span v-if="notifications.unreadCount.value" class="workspace-header__dot" />
      </button>
      <button type="button" class="workspace-header__profile" aria-label="打开个人资料" @click="emit('profile')">
        <img :src="profile.avatarDataUrl || defaultAvatar" alt="" />
        <span>{{ profile.nickname || '本机用户' }}</span>
        <PhCaretDown :size="12" aria-hidden="true" />
      </button>
    </div>
  </header>
</template>

<style scoped>
.workspace-header { display: flex; min-height: 60px; flex-shrink: 0; align-items: center; justify-content: space-between; gap: var(--space-4); padding: 0 var(--space-6); background: var(--color-bg); }
.workspace-header__title { color: var(--color-fg-muted); font-size: 16px; font-weight: var(--font-medium); }
.workspace-header__actions { display: flex; align-items: center; gap: var(--space-4); }
.workspace-header button { display: flex; align-items: center; justify-content: center; border: 0; border-radius: var(--radius); background: transparent; color: var(--color-fg-muted); cursor: pointer; }
.workspace-header button:hover { background: var(--color-surface-hover); }
.workspace-header button:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; }
.workspace-header__notification { position: relative; width: 34px; height: 34px; }
.workspace-header__dot { position: absolute; top: 6px; right: 7px; width: 6px; height: 6px; border-radius: var(--radius-full); background: var(--color-danger); }
.workspace-header__profile { gap: var(--space-2); max-width: 220px; padding: var(--space-1); }
.workspace-header__profile img { width: 32px; height: 32px; border-radius: var(--radius-full); object-fit: cover; }
.workspace-header__profile span { overflow: hidden; font-size: var(--pa-text-compact); text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 1279px) { .workspace-header { padding-left: 64px; } }
@media (max-width: 600px) { .workspace-header { padding-right: var(--space-3); } .workspace-header__profile span, .workspace-header__profile svg { display: none; } }
</style>
