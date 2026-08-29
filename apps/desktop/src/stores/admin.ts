import { reactive, ref } from "vue";
import { defineStore } from "pinia";

import { getAdminOverview, getAdminUsers, getAuditLogs } from "../services/admin";
import type {
  AdminOverview,
  AdminUserRow,
  AuditLogRow,
  PagedResult,
} from "../types/auth";

export const useAdminStore = defineStore("admin", () => {
  const overview = ref<AdminOverview | null>(null);
  const users = ref<PagedResult<AdminUserRow>>({ total: 0, results: [] });
  const auditLogs = ref<PagedResult<AuditLogRow>>({ total: 0, results: [] });
  const loading = reactive({ overview: false, users: false, audit: false });

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
  }): Promise<void> {
    loading.users = true;
    try {
      users.value = await getAdminUsers(params);
    } finally {
      loading.users = false;
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
  };
});
