<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import zhCN from "ant-design-vue/es/locale/zh_CN";

import { useAuthStore } from "./stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

function handleSessionExpired(): void {
  auth.clearSession();
  if (route.name !== "login" && route.name !== "register") {
    void router.replace({
      name: "login",
      query: { redirect: route.fullPath },
    });
  }
}

onMounted(() => window.addEventListener("pa:session-expired", handleSessionExpired));
onBeforeUnmount(() =>
  window.removeEventListener("pa:session-expired", handleSessionExpired)
);
</script>

<template>
  <a-config-provider :locale="zhCN">
    <RouterView />
  </a-config-provider>
</template>
