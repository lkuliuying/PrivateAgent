<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { message } from "ant-design-vue";
import type { TablePaginationConfig } from "ant-design-vue";
import {
  ArrowLeftOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  ReloadOutlined,
  SearchOutlined,
  UserOutlined,
} from "@ant-design/icons-vue";

import UserMenu from "../components/UserMenu.vue";
import { useAdminStore } from "../stores/admin";

const router = useRouter();
const adminStore = useAdminStore();
const { overview, users, auditLogs, loading } = storeToRefs(adminStore);
const search = ref("");
const userPage = reactive({ current: 1, size: 20 });
const auditPage = reactive({ current: 1, size: 50 });
let refreshTimer: number | null = null;

const healthEntries = computed(() => Object.entries(overview.value?.health || {}));

const userColumns = [
  { title: "用户", key: "user", width: 260 },
  { title: "角色", dataIndex: "role", key: "role", width: 90 },
  { title: "状态", dataIndex: "status", key: "status", width: 90 },
  { title: "会话", dataIndex: "session_count", key: "session_count", width: 80 },
  { title: "项目", dataIndex: "project_count", key: "project_count", width: 80 },
  { title: "文档", dataIndex: "document_count", key: "document_count", width: 80 },
  { title: "操作数", dataIndex: "operation_count", key: "operation_count", width: 90 },
  { title: "最近登录", dataIndex: "last_login_at", key: "last_login_at", width: 180 },
];

const auditColumns = [
  { title: "时间", dataIndex: "created_at", key: "created_at", width: 180 },
  { title: "用户 ID", dataIndex: "actor_user_id", key: "actor_user_id", width: 90 },
  { title: "方法", dataIndex: "method", key: "method", width: 82 },
  { title: "路径", dataIndex: "path", key: "path" },
  { title: "状态", dataIndex: "status_code", key: "status_code", width: 80 },
  { title: "耗时", dataIndex: "duration_ms", key: "duration_ms", width: 90 },
  { title: "来源 IP", dataIndex: "client_ip", key: "client_ip", width: 140 },
];

function formatDate(value: string | null): string {
  if (!value) return "--";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

async function refreshOverview(showFeedback = false): Promise<void> {
  try {
    await adminStore.loadOverview();
    if (showFeedback) message.success("系统状态已刷新");
  } catch (reason) {
    message.error(reason instanceof Error ? reason.message : "系统状态加载失败");
  }
}

async function loadUsers(): Promise<void> {
  try {
    await adminStore.loadUsers({
      page: userPage.current,
      size: userPage.size,
      search: search.value.trim() || undefined,
    });
  } catch (reason) {
    message.error(reason instanceof Error ? reason.message : "用户列表加载失败");
  }
}

async function loadAuditLogs(): Promise<void> {
  try {
    await adminStore.loadAuditLogs({
      page: auditPage.current,
      size: auditPage.size,
    });
  } catch (reason) {
    message.error(reason instanceof Error ? reason.message : "审计日志加载失败");
  }
}

function handleUserPage(pagination: TablePaginationConfig): void {
  userPage.current = pagination.current || 1;
  userPage.size = pagination.pageSize || 20;
  void loadUsers();
}

function handleAuditPage(pagination: TablePaginationConfig): void {
  auditPage.current = pagination.current || 1;
  auditPage.size = pagination.pageSize || 50;
  void loadAuditLogs();
}

function handleSearch(): void {
  userPage.current = 1;
  void loadUsers();
}

onMounted(() => {
  void Promise.all([refreshOverview(), loadUsers(), loadAuditLogs()]);
  refreshTimer = window.setInterval(() => void refreshOverview(), 30_000);
});

onBeforeUnmount(() => {
  if (refreshTimer !== null) window.clearInterval(refreshTimer);
  refreshTimer = null;
});
</script>

<template>
  <main class="admin-page">
    <header class="admin-header">
      <div class="admin-header__left">
        <a-button type="text" aria-label="返回工作台" @click="router.push('/app')">
          <ArrowLeftOutlined />
        </a-button>
        <div>
          <span class="admin-header__eyebrow">ADMIN CONSOLE</span>
          <h1>系统监控</h1>
        </div>
      </div>
      <div class="admin-header__actions">
        <span v-if="overview" class="admin-header__time">
          更新于 {{ formatDate(overview.generated_at) }}
        </span>
        <a-button :loading="loading.overview" @click="refreshOverview(true)">
          <ReloadOutlined /> 刷新
        </a-button>
      </div>
    </header>

    <section class="admin-content">
      <div class="admin-stats">
        <a-card :loading="loading.overview" class="admin-stat">
          <a-statistic title="用户总数" :value="overview?.users_total ?? 0" />
          <span class="admin-stat__note">活跃 {{ overview?.users_active ?? 0 }}</span>
        </a-card>
        <a-card :loading="loading.overview" class="admin-stat">
          <a-statistic title="管理员" :value="overview?.admins_total ?? 0" />
          <span class="admin-stat__note">受保护系统权限</span>
        </a-card>
        <a-card :loading="loading.overview" class="admin-stat">
          <a-statistic title="用户会话" :value="overview?.sessions_total ?? 0" />
          <span class="admin-stat__note">服务器持久化</span>
        </a-card>
        <a-card :loading="loading.overview" class="admin-stat">
          <a-statistic title="24h 操作" :value="overview?.operations_24h ?? 0" />
          <span class="admin-stat__note">全部 API 操作</span>
        </a-card>
        <a-card :loading="loading.overview" class="admin-stat admin-stat--error">
          <a-statistic title="24h 异常" :value="overview?.errors_24h ?? 0" />
          <span class="admin-stat__note">HTTP 4xx / 5xx</span>
        </a-card>
      </div>

      <a-card class="admin-section" title="系统状态" :loading="loading.overview">
        <div v-if="healthEntries.length" class="health-grid">
          <div v-for="[name, state] in healthEntries" :key="name" class="health-item">
            <component
              :is="state.ok ? CheckCircleFilled : CloseCircleFilled"
              :class="state.ok ? 'health-item__ok' : 'health-item__error'"
            />
            <div>
              <strong>{{ name }}</strong>
              <span>{{ state.ok ? "运行正常" : "需要检查" }}</span>
            </div>
          </div>
        </div>
        <a-empty v-else description="暂无健康状态" />
      </a-card>

      <a-tabs class="admin-section" type="card">
        <a-tab-pane key="users" tab="用户数据">
          <div class="admin-toolbar">
            <a-input
              v-model:value="search"
              allow-clear
              class="admin-search"
              placeholder="搜索邮箱或显示名称"
              @press-enter="handleSearch"
            >
              <template #prefix><SearchOutlined /></template>
            </a-input>
            <a-button type="primary" @click="handleSearch">搜索</a-button>
          </div>
          <a-table
            row-key="id"
            :columns="userColumns"
            :data-source="users.results"
            :loading="loading.users"
            :scroll="{ x: 1150 }"
            :pagination="{
              current: userPage.current,
              pageSize: userPage.size,
              total: users.total,
              showSizeChanger: true,
              showTotal: (total: number) => `共 ${total} 个用户`,
            }"
            @change="handleUserPage"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'user'">
                <div class="user-cell">
                  <a-avatar><template #icon><UserOutlined /></template></a-avatar>
                  <div>
                    <strong>{{ record.display_name }}</strong>
                    <span>{{ record.email }}</span>
                  </div>
                </div>
              </template>
              <template v-else-if="column.key === 'role'">
                <a-tag :color="record.role === 'admin' ? 'blue' : 'default'">
                  {{ record.role === "admin" ? "管理员" : "用户" }}
                </a-tag>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-badge
                  :status="record.status === 'active' ? 'success' : 'default'"
                  :text="record.status === 'active' ? '正常' : '停用'"
                />
              </template>
              <template v-else-if="column.key === 'last_login_at'">
                {{ formatDate(record.last_login_at) }}
              </template>
            </template>
          </a-table>
        </a-tab-pane>

        <a-tab-pane key="audit" tab="操作审计">
          <a-table
            row-key="id"
            :columns="auditColumns"
            :data-source="auditLogs.results"
            :loading="loading.audit"
            :scroll="{ x: 1050 }"
            :pagination="{
              current: auditPage.current,
              pageSize: auditPage.size,
              total: auditLogs.total,
              showSizeChanger: true,
              showTotal: (total: number) => `共 ${total} 条记录`,
            }"
            @change="handleAuditPage"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'created_at'">
                {{ formatDate(record.created_at) }}
              </template>
              <template v-else-if="column.key === 'actor_user_id'">
                {{ record.actor_user_id ?? "--" }}
              </template>
              <template v-else-if="column.key === 'method'">
                <a-tag>{{ record.method }}</a-tag>
              </template>
              <template v-else-if="column.key === 'path'">
                <code class="audit-path">{{ record.path }}</code>
              </template>
              <template v-else-if="column.key === 'status_code'">
                <a-tag :color="record.status_code >= 400 ? 'red' : 'green'">
                  {{ record.status_code }}
                </a-tag>
              </template>
              <template v-else-if="column.key === 'duration_ms'">
                {{ record.duration_ms }} ms
              </template>
              <template v-else-if="column.key === 'client_ip'">
                {{ record.client_ip || "--" }}
              </template>
            </template>
          </a-table>
        </a-tab-pane>
      </a-tabs>
    </section>

    <UserMenu />
  </main>
</template>

<style scoped>
.admin-page {
  min-height: 100vh;
  color: #172033;
  background: #f3f6fa;
}

.admin-header {
  position: sticky;
  z-index: 10;
  top: 0;
  min-height: 82px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 14px clamp(22px, 4vw, 56px);
  border-bottom: 1px solid #e0e6ef;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(16px);
}

.admin-header__left,
.admin-header__actions {
  display: flex;
  align-items: center;
}

.admin-header__left {
  gap: 14px;
}

.admin-header__left h1 {
  margin: 1px 0 0;
  font-size: 24px;
  line-height: 1.15;
}

.admin-header__eyebrow {
  color: #5274a8;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

.admin-header__actions {
  gap: 16px;
}

.admin-header__time {
  color: #7c8799;
  font-size: 12px;
}

.admin-content {
  max-width: 1520px;
  margin: 0 auto;
  padding: 28px clamp(22px, 4vw, 56px) 70px;
}

.admin-stats {
  display: grid;
  grid-template-columns: repeat(5, minmax(150px, 1fr));
  gap: 14px;
}

.admin-stat {
  border-color: #e0e6ef;
}

.admin-stat--error {
  border-top: 3px solid #ff7875;
}

.admin-stat__note {
  display: block;
  margin-top: 8px;
  color: #8691a3;
  font-size: 12px;
}

.admin-section {
  margin-top: 18px;
  border-color: #e0e6ef;
}

.health-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}

.health-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid #e3e8f0;
  border-radius: 10px;
  background: #fafbfd;
}

.health-item svg {
  font-size: 20px;
}

.health-item__ok {
  color: #52c41a;
}

.health-item__error {
  color: #ff4d4f;
}

.health-item strong,
.health-item span,
.user-cell strong,
.user-cell span {
  display: block;
}

.health-item span,
.user-cell span {
  margin-top: 3px;
  color: #8691a3;
  font-size: 12px;
}

.admin-toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}

.admin-search {
  max-width: 360px;
}

.user-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.audit-path {
  color: #2d4f7c;
  word-break: break-all;
}

@media (max-width: 1080px) {
  .admin-stats {
    grid-template-columns: repeat(2, minmax(160px, 1fr));
  }
}

@media (max-width: 620px) {
  .admin-header {
    align-items: flex-start;
  }

  .admin-header__time {
    display: none;
  }

  .admin-stats {
    grid-template-columns: 1fr;
  }
}
</style>
