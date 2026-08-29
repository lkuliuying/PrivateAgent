import { reactive, ref } from "vue";
import { defineStore } from "pinia";

import {
  createAdminUser,
  getAdminOverview,
  getAdminUsers,
  getAuditLogs,
  updateAdminUser,
} from "../services/admin";
import type {
  AdminOverview,
  AdminUserCreateInput,
  AdminUserRow,
  AdminUserUpdateInput,
  AuthUser,
  AuditLogRow,
  PagedResult,
} from "../types/auth";

export const useAdminStore = defineStore("admin", () => {
  const overview = ref<AdminOverview | null>(null);
  const users = ref<PagedResult<AdminUserRow>>({ total: 0, results: [] });
  const auditLogs = ref<PagedResult<AuditLogRow>>({ total: 0, results: [] });
  const loading = reactive({ overview: false, users: false, audit: false, mutation: false });

  /** 获取系统健康状态和 24 小时核心统计。 */
  async function loadOverview(): Promise<void> {
    loading.overview = true;
    try {
      overview.value = await getAdminOverview();
    } finally {
      loading.overview = false;
    }
  }

  async function loadUsers(params: {
    page: number;
    size: number;
    search?: string;
    role?: "admin" | "user";
    status?: "active" | "disabled";
  }): Promise<void> {
    loading.users = true;
    try {
      users.value = await getAdminUsers(params);
    } finally {
      loading.users = false;
    }
  }

  /** 创建账号并由调用页面决定何时刷新列表与统计。 */
  async function createUser(payload: AdminUserCreateInput): Promise<AuthUser> {
    loading.mutation = true;
    try {
      return await createAdminUser(payload);
    } finally {
      loading.mutation = false;
    }
  }

  /** 修改用户角色或状态，并返回服务端确认后的账号信息。 */
  async function updateUser(
    userId: number,
    payload: AdminUserUpdateInput
  ): Promise<AuthUser> {
    loading.mutation = true;
    try {
      return await updateAdminUser(userId, payload);
    } finally {
      loading.mutation = false;
    }
  }

  async function loadAuditLogs(params: {
    page: number;
    size: number;
    actorUserId?: number;
    statusCode?: number;
  }): Promise<void> {
    loading.audit = true;
    try {
      auditLogs.value = await getAuditLogs(params);
    } finally {
      loading.audit = false;
    }
  }

  return {
    overview,
    users,
    auditLogs,
    loading,
    loadOverview,
    loadUsers,
    loadAuditLogs,
    createUser,
    updateUser,
  };
});
