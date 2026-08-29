<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import zhCN from "ant-design-vue/es/locale/zh_CN";

import { cmdExitApp, cmdHideMainWindow, listenForMainWindowClose } from "./api/tauri";
import CloseBehaviorDialog from "./components/CloseBehaviorDialog.vue";
import {
  getSavedWindowCloseBehavior,
  saveWindowCloseBehavior,
  type WindowCloseBehavior,
} from "./services/windowClose";
import {
  backendStartupState,
  retryDesktopBackendStartup,
} from "./services/backendStartup";
import { useAuthStore } from "./stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const closeDialogOpen = ref(false);
const closeBehavior = ref<WindowCloseBehavior>("exit");
const dontAskAgain = ref(false);
const closeBusy = ref(false);
const closeError = ref("");
const backendRetryBusy = ref(false);
let unlistenWindowClose: (() => void) | null = null;
let rootUnmounted = false;

function handleSessionExpired(): void {
  auth.clearSession();
  if (route.name !== "login" && route.name !== "register") {
    void router.replace({
      name: "login",
      query: { redirect: route.fullPath },
    });
  }
}

async function performClose(behavior: WindowCloseBehavior): Promise<void> {
  if (closeBusy.value) return;
  closeBusy.value = true;
  closeError.value = "";
  try {
    if (behavior === "background") {
      await cmdHideMainWindow();
      closeDialogOpen.value = false;
    } else {
      await cmdExitApp();
    }
  } catch {
    closeDialogOpen.value = true;
    closeError.value =
      behavior === "background"
        ? "无法隐藏到系统托盘，请重试。"
        : "无法退出应用，请重试。";
  } finally {
    closeBusy.value = false;
  }
}

function handleWindowCloseRequest(): void {
  if (closeDialogOpen.value || closeBusy.value) return;
  const savedBehavior = getSavedWindowCloseBehavior();
  if (savedBehavior) {
    void performClose(savedBehavior);
    return;
  }
  closeBehavior.value = "exit";
  dontAskAgain.value = false;
  closeError.value = "";
  closeDialogOpen.value = true;
}

function cancelWindowClose(): void {
  closeDialogOpen.value = false;
  closeError.value = "";
}

function confirmWindowClose(): void {
  if (dontAskAgain.value) saveWindowCloseBehavior(closeBehavior.value);
  void performClose(closeBehavior.value);
}

async function retryBackendStartup(): Promise<void> {
  if (backendRetryBusy.value) return;
  backendRetryBusy.value = true;
  try {
    await retryDesktopBackendStartup();
    await router.replace(route.fullPath);
  } catch {
    // backendStartupState already carries the sanitized user-facing error.
  } finally {
    backendRetryBusy.value = false;
  }
}

onMounted(() => {
  window.addEventListener("pa:session-expired", handleSessionExpired);
  void listenForMainWindowClose(handleWindowCloseRequest)
    .then((unlisten) => {
      if (rootUnmounted) unlisten();
      else unlistenWindowClose = unlisten;
    })
    .catch(() => {
      // 浏览器预览或桌面事件通道不可用时保留平台默认关闭行为。
    });
});

onBeforeUnmount(() => {
  rootUnmounted = true;
  unlistenWindowClose?.();
  window.removeEventListener("pa:session-expired", handleSessionExpired);
});
</script>

<template>
  <a-config-provider :locale="zhCN">
    <RouterView v-if="backendStartupState.status === 'ready'" />
    <main
      v-if="backendStartupState.status === 'idle' || backendStartupState.status === 'starting'"
      class="startup-gate"
      aria-live="polite"
      aria-busy="true"
    >
      <section class="startup-gate__card">
        <div class="startup-gate__brand" aria-hidden="true">PA</div>
        <span class="startup-gate__spinner" aria-hidden="true" />
        <h1>正在启动 PrivateAgent</h1>
        <p>正在连接本地服务，请稍候…</p>
      </section>
    </main>
    <main
      v-else-if="backendStartupState.status === 'error'"
      class="startup-gate"
      aria-live="assertive"
    >
      <section class="startup-gate__card startup-gate__card--error">
        <div class="startup-gate__brand startup-gate__brand--error" aria-hidden="true">!</div>
        <h1>本地服务未能启动</h1>
        <p>{{ backendStartupState.error }}</p>
        <button
          class="pa-btn pa-btn--primary"
          type="button"
          :disabled="backendRetryBusy"
          @click="retryBackendStartup"
        >
          {{ backendRetryBusy ? "正在重试…" : "关闭其他实例后重试" }}
        </button>
      </section>
    </main>
    <CloseBehaviorDialog
      v-model:selected="closeBehavior"
      v-model:dont-ask-again="dontAskAgain"
      :open="closeDialogOpen"
      :busy="closeBusy"
      :error="closeError"
      @cancel="cancelWindowClose"
      @confirm="confirmWindowClose"
    />
  </a-config-provider>
</template>

<style scoped>
.startup-gate {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  display: grid;
  place-items: center;
  min-width: 320px;
  min-height: 360px;
  padding: var(--space-6);
  color: var(--color-fg);
  background:
    radial-gradient(circle at 50% 28%, var(--color-accent-soft), transparent 32%),
    var(--color-surface-sunken);
}

.startup-gate__card {
  display: flex;
  width: min(420px, 100%);
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-8);
  text-align: center;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
}

.startup-gate__brand {
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  color: var(--color-accent-fg);
  font-weight: var(--font-semibold);
  background: var(--color-accent);
  border-radius: var(--radius-lg);
}

.startup-gate__brand--error {
  color: var(--color-danger-fg);
  background: var(--color-danger-soft);
}

.startup-gate__spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--color-border-strong);
  border-top-color: var(--color-accent);
  border-radius: var(--radius-full);
  animation: startup-spin 700ms linear infinite;
}

.startup-gate h1,
.startup-gate p {
  margin: 0;
}

.startup-gate h1 {
  font-size: var(--text-xl);
}

.startup-gate p {
  max-width: 34ch;
  color: var(--color-fg-muted);
  line-height: 1.6;
}

.startup-gate__card--error p {
  color: var(--color-danger-fg);
}

@keyframes startup-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .startup-gate__spinner {
    animation: none;
  }
}
</style>
