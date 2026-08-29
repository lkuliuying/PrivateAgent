import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { clearAccessToken, getAccessToken, setAccessToken } from "../auth/session";
import {
  getCurrentAccount,
  loginAccount,
  logoutAccount,
  registerAccount,
} from "../services/auth";
import type { AuthUser } from "../types/auth";

export const useAuthStore = defineStore("auth", () => {
  const user = ref<AuthUser | null>(null);
  const loading = ref(false);
  const initialized = ref(false);
  const isAuthenticated = computed(() => user.value !== null);
  const isAdmin = computed(() => user.value?.role === "admin");

  /** 应用启动时用持久 token 恢复服务端会话。 */
  async function restoreSession(): Promise<boolean> {
    if (initialized.value) return isAuthenticated.value;
    initialized.value = true;
    if (!getAccessToken()) return false;
    loading.value = true;
    try {
      user.value = await getCurrentAccount();
      return true;
    } catch {
      clearSession();
      return false;
    } finally {
      loading.value = false;
    }
  }

  /** 登录成功后设置 token，再把用户作为 store 的唯一身份源。 */
  async function login(payload: {
    identifier: string;
    password: string;
  }): Promise<void> {
    loading.value = true;
    try {
      const response = await loginAccount(payload);
      setAccessToken(response.access_token);
      user.value = response.user;
      initialized.value = true;
    } finally {
      loading.value = false;
    }
  }

  async function register(payload: {
    email: string;
    password: string;
    username: string;
    verification_code: string;
  }): Promise<void> {
    loading.value = true;
    try {
      const response = await registerAccount(payload);
      setAccessToken(response.access_token);
      user.value = response.user;
      initialized.value = true;
    } finally {
      loading.value = false;
    }
  }

  async function logout(): Promise<void> {
    loading.value = true;
    try {
      await logoutAccount();
    } finally {
      clearSession();
      loading.value = false;
    }
  }

  function clearSession(): void {
    clearAccessToken();
    user.value = null;
    initialized.value = true;
  }

  return {
    user,
    loading,
    initialized,
    isAuthenticated,
    isAdmin,
    restoreSession,
    login,
    register,
    logout,
    clearSession,
  };
});
