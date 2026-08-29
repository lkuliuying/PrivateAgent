<script setup lang="ts">
import { useRouter } from "vue-router";
import { message } from "ant-design-vue";
import {
  DashboardOutlined,
  LogoutOutlined,
  UserOutlined,
} from "@ant-design/icons-vue";

import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const router = useRouter();

async function handleMenu({ key }: { key: string }): Promise<void> {
  if (key === "admin") {
    await router.push({ name: "admin" });
    return;
  }
  if (key === "logout") {
    try {
      await auth.logout();
    } catch (reason) {
      message.warning(reason instanceof Error ? reason.message : "服务端退出失败");
    }
    await router.replace({ name: "login" });
  }
}
</script>

<template>
  <div class="user-menu">
    <a-dropdown placement="topRight" trigger="click">
      <a-button class="user-menu__button" shape="round">
        <UserOutlined />
        <span>{{ auth.user?.display_name || "账号" }}</span>
      </a-button>
      <template #overlay>
        <a-menu @click="handleMenu">
          <a-menu-item v-if="auth.isAdmin" key="admin">
            <DashboardOutlined /> 管理员端
          </a-menu-item>
          <a-menu-divider v-if="auth.isAdmin" />
          <a-menu-item key="logout" danger>
            <LogoutOutlined /> 退出登录
          </a-menu-item>
        </a-menu>
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

.user-menu__button {
  border-color: rgba(110, 124, 148, 0.34);
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 8px 26px rgba(28, 42, 66, 0.16);
  backdrop-filter: blur(12px);
}
</style>
