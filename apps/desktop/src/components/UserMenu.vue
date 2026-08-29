<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { message } from "ant-design-vue";
import {
  PhCaretUpDown,
  PhGearSix,
  PhSignOut,
  PhUserCircle,
} from "@phosphor-icons/vue";

import { useAuthStore } from "../stores/auth";

withDefaults(
  defineProps<{
    inline?: boolean;
    collapsed?: boolean;
  }>(),
  { inline: false, collapsed: false }
);

const emit = defineEmits<{
  settings: [];
}>();

const auth = useAuthStore();
const router = useRouter();
const menuOpen = ref(false);
const username = computed(() => auth.user?.username?.trim() || "账号");

function openSettings(): void {
  menuOpen.value = false;
  emit("settings");
}

async function logout(): Promise<void> {
  if (auth.loading) return;
  menuOpen.value = false;
  try {
    await auth.logout();
  } catch (reason) {
    message.warning(reason instanceof Error ? reason.message : "服务端退出失败");
  }
  await router.replace({ name: "login" });
}
</script>

<template>
  <div class="user-menu" :class="{ 'user-menu--inline': inline, 'is-collapsed': collapsed }">
    <a-dropdown
      v-model:open="menuOpen"
      :placement="inline ? 'topLeft' : 'topRight'"
      trigger="click"
    >
      <button
        type="button"
        class="user-menu__trigger"
        data-testid="user-menu-trigger"
        :aria-label="`账号菜单：${username}`"
        :aria-expanded="menuOpen"
      >
        <PhUserCircle :size="inline ? 25 : 20" weight="fill" aria-hidden="true" />
        <span class="user-menu__identity">
          <strong>{{ username }}</strong>
          <small v-if="inline">个人账号</small>
        </span>
        <PhCaretUpDown
          v-if="!collapsed"
          class="user-menu__caret"
          :size="14"
          aria-hidden="true"
        />
      </button>

      <template #overlay>
        <div
          class="user-menu__popover"
          role="menu"
          aria-label="账号操作"
          data-testid="user-menu-popover"
        >
          <header class="user-menu__popover-head">
            <PhUserCircle :size="24" weight="fill" aria-hidden="true" />
            <strong>{{ username }}</strong>
          </header>
          <div class="user-menu__divider" />
          <button
            type="button"
            role="menuitem"
            data-testid="user-menu-settings"
            @click="openSettings"
          >
            <PhGearSix :size="17" aria-hidden="true" />
            <span>设置</span>
          </button>
          <button
            type="button"
            role="menuitem"
            class="user-menu__logout"
            data-testid="user-menu-logout"
            :disabled="auth.loading"
            @click="void logout()"
          >
            <PhSignOut :size="17" aria-hidden="true" />
            <span>{{ auth.loading ? "正在退出…" : "退出登录" }}</span>
          </button>
        </div>
      </template>
    </a-dropdown>
  </div>
</template>

<style scoped>
.user-menu {
  position: fixed;
  z-index: 90;
  right: 16px;
  bottom: 30px;
}

.user-menu--inline {
  position: static;
  min-width: 0;
  flex: 1;
}

.user-menu__trigger {
  display: flex;
  min-width: 0;
  height: 38px;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  border: 1px solid color-mix(in srgb, var(--color-border) 82%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-surface) 94%, transparent);
  color: var(--color-fg-muted);
  box-shadow: var(--shadow-sm);
  cursor: pointer;
}

.user-menu--inline .user-menu__trigger {
  width: 100%;
  height: 42px;
  padding: 0 8px;
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  box-shadow: none;
  text-align: left;
}

.user-menu__trigger:hover,
.user-menu__trigger[aria-expanded="true"] {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}

.user-menu__trigger:focus-visible,
.user-menu__popover button:focus-visible {
  outline: var(--focus-ring);
  outline-offset: 1px;
}

.user-menu__identity {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
}

.user-menu__identity strong {
  overflow: hidden;
  color: var(--color-fg);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-menu__identity small {
  overflow: hidden;
  color: var(--color-fg-faint);
  font-size: var(--pa-text-meta);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-menu__caret {
  flex: 0 0 auto;
  color: var(--color-fg-subtle);
}

.user-menu__popover {
  width: 236px;
  padding: 8px;
  border: 1px solid var(--color-border);
  border-radius: 16px;
  background: color-mix(in srgb, var(--color-surface) 96%, transparent);
  box-shadow: var(--shadow-lg);
  backdrop-filter: blur(18px);
}

.user-menu__popover-head {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 9px;
  padding: 7px 9px;
  color: var(--color-fg);
}

.user-menu__popover-head strong {
  overflow: hidden;
  font-size: var(--text-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-menu__divider {
  height: 1px;
  margin: 3px 4px 5px;
  background: var(--color-border);
}

.user-menu__popover button {
  display: flex;
  width: 100%;
  height: 36px;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--text-sm);
  text-align: left;
  cursor: pointer;
}

.user-menu__popover button:hover {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}

.user-menu__popover button:disabled {
  cursor: wait;
  opacity: 0.6;
}

.user-menu__popover .user-menu__logout {
  color: var(--color-danger-fg);
}

.is-collapsed .user-menu__trigger {
  justify-content: center;
  padding-inline: 0;
}

.is-collapsed .user-menu__identity {
  display: none;
}
</style>
