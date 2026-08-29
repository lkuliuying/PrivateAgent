<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import {
  Col as ACol,
  message,
  Modal as AModal,
  Row as ARow,
  Select as ASelect,
} from "ant-design-vue";
import type { FormInstance, TablePaginationConfig } from "ant-design-vue";
import {
  ApiOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  DashboardOutlined,
  FolderOpenOutlined,
  LogoutOutlined,
  MessageOutlined,
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
  TeamOutlined,
  UserOutlined,
  WarningOutlined,
} from "@ant-design/icons-vue";

import { useAdminStore } from "../stores/admin";
import { useAuthStore } from "../stores/auth";
import type { AdminUserCreateInput, AdminUserRow } from "../types/auth";

type TableFilterValue = (string | number | boolean)[] | null;

interface CreateUserForm extends AdminUserCreateInput {
  confirmPassword: string;
}

type AdminModule = "system" | "users";

const router = useRouter();
const adminStore = useAdminStore();
const authStore = useAuthStore();
const { overview, users, auditLogs, loading } = storeToRefs(adminStore);
const activeModule = ref<AdminModule>("system");
const search = ref("");
const userPage = reactive({ current: 1, size: 20 });
const userFilters = reactive<{
  role?: "admin" | "user";
  status?: "active" | "disabled";
}>({});
const auditPage = reactive({ current: 1, size: 50 });
const createOpen = ref(false);
const createFormRef = ref<FormInstance>();
const createForm = reactive<CreateUserForm>({
  email: "",
  username: "",
  password: "",
  confirmPassword: "",
  role: "user",
});
const roleOpen = ref(false);
const roleTarget = ref<AdminUserRow | null>(null);
const roleValue = ref<"admin" | "user">("user");
let refreshTimer: number | null = null;

const healthEntries = computed(() => Object.entries(overview.value?.health || {}));
const currentUserId = computed(() => authStore.user?.id ?? null);
const moduleTitle = computed(() =>
  activeModule.value === "system" ? "系统总览" : "用户管理"
);
const moduleDescription = computed(() =>
  activeModule.value === "system"
    ? "查看平台运行状态、核心指标与最近操作"
    : "创建账号、分配角色并管理用户访问状态"
);
const roleOptions = [
  { label: "用户", value: "user" },
  { label: "管理员", value: "admin" },
];

const userColumns = [
  { title: "用户", key: "user", width: 260 },
  {
    title: "角色",
    dataIndex: "role",
    key: "role",
    width: 100,
    filters: [
      { text: "管理员", value: "admin" },
      { text: "用户", value: "user" },
    ],
    filterMultiple: false,
  },
  {
    title: "状态",
    dataIndex: "status",
    key: "status",
    width: 100,
    filters: [
      { text: "正常", value: "active" },
      { text: "停用", value: "disabled" },
    ],
    filterMultiple: false,
  },
  { title: "会话", dataIndex: "session_count", key: "session_count", width: 80 },
  { title: "项目", dataIndex: "project_count", key: "project_count", width: 80 },
  { title: "文档", dataIndex: "document_count", key: "document_count", width: 80 },
  { title: "操作数", dataIndex: "operation_count", key: "operation_count", width: 90 },
  { title: "最近登录", dataIndex: "last_login_at", key: "last_login_at", width: 180 },
  { title: "管理", key: "actions", width: 190, fixed: "right" },
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
      role: userFilters.role,
      status: userFilters.status,
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

async function refreshManagementData(): Promise<void> {
  await Promise.all([loadUsers(), refreshOverview(), loadAuditLogs()]);
}

function handleUserPage(
  pagination: TablePaginationConfig,
  filters: Record<string, TableFilterValue>
): void {
  userPage.current = pagination.current || 1;
  userPage.size = pagination.pageSize || 20;
  const role = filters.role?.[0];
  const status = filters.status?.[0];
  userFilters.role = role === "admin" || role === "user" ? role : undefined;
  userFilters.status =
    status === "active" || status === "disabled" ? status : undefined;
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

function handleModuleChange(module: AdminModule): void {
  activeModule.value = module;
}

function resetCreateForm(): void {
  Object.assign(createForm, {
    email: "",
    username: "",
    password: "",
    confirmPassword: "",
    role: "user",
  });
  createFormRef.value?.clearValidate();
}

function handleOpenCreate(): void {
  resetCreateForm();
  createOpen.value = true;
}

function handleCloseCreate(): void {
  createOpen.value = false;
  resetCreateForm();
}

/** 校验并创建用户，成功后同步刷新用户、统计和审计数据。 */
async function handleCreateUser(): Promise<void> {
  try {
    await createFormRef.value?.validate();
    if (createForm.password !== createForm.confirmPassword) {
      message.error("两次输入的密码不一致");
      return;
    }
    await adminStore.createUser({
      email: createForm.email.trim(),
      username: createForm.username.trim(),
      password: createForm.password,
      role: createForm.role,
    });
    message.success("用户创建成功");
    handleCloseCreate();
    await refreshManagementData();
  } catch (reason) {
    if (reason instanceof Error) message.error(reason.message);
  }
}

function handleOpenRole(record: AdminUserRow): void {
  roleTarget.value = record;
  roleValue.value = record.role;
  roleOpen.value = true;
}

function handleCloseRole(): void {
  roleOpen.value = false;
  roleTarget.value = null;
}

/** 保存角色修改；当前登录管理员在界面和服务端均不可降级自身。 */
async function handleUpdateRole(): Promise<void> {
  const target = roleTarget.value;
  if (!target) return;
  try {
    await adminStore.updateUser(target.id, { role: roleValue.value });
    message.success("用户角色已更新");
    handleCloseRole();
    await refreshManagementData();
  } catch (reason) {
    message.error(reason instanceof Error ? reason.message : "角色修改失败");
  }
}

/** 启停操作必须二次确认；停用会立即撤销目标用户的全部会话。 */
function handleToggleStatus(record: AdminUserRow): void {
  const enabling = record.status === "disabled";
  AModal.confirm({
    title: enabling ? "启用用户" : "停用用户",
    content: enabling
      ? `确认恢复 ${record.username} 的登录权限吗？`
      : `确认停用 ${record.username} 吗？该用户将立即退出所有会话。`,
    okText: enabling ? "确认启用" : "确认停用",
    okType: enabling ? "primary" : "danger",
    cancelText: "取消",
    async onOk() {
      try {
        await adminStore.updateUser(record.id, {
          status: enabling ? "active" : "disabled",
        });
        message.success(enabling ? "用户已启用" : "用户已停用");
        await refreshManagementData();
      } catch (reason) {
        message.error(reason instanceof Error ? reason.message : "用户状态修改失败");
        throw reason;
      }
    },
  });
}

async function handleLogout(): Promise<void> {
  try {
    await authStore.logout();
  } catch (reason) {
    message.warning(reason instanceof Error ? reason.message : "服务端退出失败");
  }
  await router.replace({ name: "login" });
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
    <header class="admin-brand">
      <SafetyCertificateOutlined class="admin-brand__icon" />
      <span class="admin-brand__name">私人助手</span>
      <span class="admin-brand__badge">ADMIN</span>
    </header>

    <header class="admin-topbar">
      <div class="admin-topbar__title">
        <DashboardOutlined />
        <span>后台管理系统</span>
      </div>
      <div class="admin-topbar__actions">
        <span v-if="overview" class="admin-topbar__time">
          更新于 {{ formatDate(overview.generated_at) }}
        </span>
        <a-button
          class="admin-topbar__button"
          type="text"
          :loading="loading.overview"
          @click="refreshOverview(true)"
        >
          <ReloadOutlined /> 刷新
        </a-button>
        <span class="admin-topbar__identity">
          <UserOutlined /> {{ authStore.user?.username || "管理员" }}
        </span>
        <a-button
          class="admin-topbar__button"
          type="text"
          :loading="authStore.loading"
          @click="handleLogout"
        >
          <LogoutOutlined /> 退出登录
        </a-button>
      </div>
    </header>

    <aside class="admin-sidebar" aria-label="管理员模块导航">
      <div class="admin-sidebar__caption">管理模块</div>
      <nav class="admin-nav">
        <button
          type="button"
          class="admin-nav__item"
          :class="{ 'is-active': activeModule === 'system' }"
          @click="handleModuleChange('system')"
        >
          <DashboardOutlined class="admin-nav__icon" />
          <span>
            <strong>系统</strong>
            <small>运行监控与操作审计</small>
          </span>
        </button>
        <button
          type="button"
          class="admin-nav__item"
          :class="{ 'is-active': activeModule === 'users' }"
          @click="handleModuleChange('users')"
        >
          <TeamOutlined class="admin-nav__icon" />
          <span>
            <strong>用户</strong>
            <small>账号、角色与访问状态</small>
          </span>
        </button>
      </nav>
      <footer class="admin-sidebar__footer">
        <SafetyCertificateOutlined />
        <span>
          <strong>管理员模式</strong>
          <small>仅显示管理功能</small>
        </span>
      </footer>
    </aside>

    <section class="admin-workspace">
      <header class="admin-breadcrumb">
        <span>首页</span>
        <span class="admin-breadcrumb__separator">/</span>
        <strong>{{ moduleTitle }}</strong>
      </header>

      <section class="admin-content">
        <header class="admin-content__heading">
          <div>
            <h1>{{ moduleTitle }}</h1>
            <p>{{ moduleDescription }}</p>
          </div>
          <a-button
            v-if="activeModule === 'users'"
            type="primary"
            @click="handleOpenCreate"
          >
            <PlusOutlined /> 创建用户
          </a-button>
        </header>

        <template v-if="activeModule === 'system'">
          <section class="admin-stats" aria-label="系统核心指标">
            <article class="admin-stat admin-stat--blue">
              <span class="admin-stat__icon"><TeamOutlined /></span>
              <div>
                <strong>{{ overview?.users_total ?? 0 }}</strong>
                <span>用户总数</span>
                <small>活跃 {{ overview?.users_active ?? 0 }}</small>
              </div>
            </article>
            <article class="admin-stat admin-stat--cyan">
              <span class="admin-stat__icon"><SafetyCertificateOutlined /></span>
              <div>
                <strong>{{ overview?.admins_total ?? 0 }}</strong>
                <span>管理员</span>
                <small>受保护系统权限</small>
              </div>
            </article>
            <article class="admin-stat admin-stat--green">
              <span class="admin-stat__icon"><MessageOutlined /></span>
              <div>
                <strong>{{ overview?.sessions_total ?? 0 }}</strong>
                <span>用户会话</span>
                <small>服务器持久化</small>
              </div>
            </article>
            <article class="admin-stat admin-stat--orange">
              <span class="admin-stat__icon"><FolderOpenOutlined /></span>
              <div>
                <strong>{{ overview?.projects_total ?? 0 }}</strong>
                <span>项目总数</span>
                <small>全部用户项目</small>
              </div>
            </article>
            <article class="admin-stat admin-stat--violet">
              <span class="admin-stat__icon"><ApiOutlined /></span>
              <div>
                <strong>{{ overview?.operations_24h ?? 0 }}</strong>
                <span>24h 操作</span>
                <small>全部 API 操作</small>
              </div>
            </article>
            <article class="admin-stat admin-stat--red">
              <span class="admin-stat__icon"><WarningOutlined /></span>
              <div>
                <strong>{{ overview?.errors_24h ?? 0 }}</strong>
                <span>24h 异常</span>
                <small>HTTP 4xx / 5xx</small>
              </div>
            </article>
          </section>

          <section class="admin-panel admin-panel--health">
            <header class="admin-panel__header">
              <div>
                <h2>系统状态</h2>
                <p>核心服务实时健康检查</p>
              </div>
              <a-tag color="green">自动刷新</a-tag>
            </header>
            <div v-if="healthEntries.length" class="health-grid">
              <article
                v-for="[name, state] in healthEntries"
                :key="name"
                class="health-item"
              >
                <component
                  :is="state.ok ? CheckCircleFilled : CloseCircleFilled"
                  :class="state.ok ? 'health-item__ok' : 'health-item__error'"
                />
                <div>
                  <strong>{{ name }}</strong>
                  <span>{{ state.ok ? "运行正常" : "需要检查" }}</span>
                </div>
              </article>
            </div>
            <a-empty v-else description="暂无健康状态" />
          </section>

          <section class="admin-panel admin-panel--table">
            <header class="admin-panel__header">
              <div>
                <h2>操作审计</h2>
                <p>最近 API 请求与异常记录</p>
              </div>
              <span class="admin-panel__count">共 {{ auditLogs.total }} 条记录</span>
            </header>
            <a-table
              class="admin-table"
              row-key="id"
              size="middle"
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
          </section>
        </template>

        <section v-else class="admin-panel admin-panel--users">
          <header class="admin-user-toolbar">
            <div class="admin-user-toolbar__search">
              <a-input
                v-model:value="search"
                allow-clear
                class="admin-search"
                placeholder="搜索邮箱或用户名"
                @press-enter="handleSearch"
              >
                <template #prefix><SearchOutlined /></template>
              </a-input>
              <a-button type="primary" @click="handleSearch">搜索</a-button>
            </div>
            <span>共 {{ users.total }} 个用户</span>
          </header>
          <a-table
            class="admin-table"
            row-key="id"
            size="middle"
            :columns="userColumns"
            :data-source="users.results"
            :loading="loading.users || loading.mutation"
            :scroll="{ x: 1340 }"
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
                    <strong>{{ record.username }}</strong>
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
              <template v-else-if="column.key === 'actions'">
                <div class="admin-user-actions">
                  <a-button
                    type="link"
                    size="small"
                    :disabled="record.id === currentUserId"
                    @click="handleOpenRole(record)"
                  >
                    修改角色
                  </a-button>
                  <a-button
                    type="link"
                    size="small"
                    :danger="record.status === 'active'"
                    :disabled="record.id === currentUserId"
                    @click="handleToggleStatus(record)"
                  >
                    {{ record.status === "active" ? "停用" : "启用" }}
                  </a-button>
                </div>
              </template>
            </template>
          </a-table>
        </section>
      </section>
    </section>

    <AModal
      v-model:open="createOpen"
      title="创建用户"
      :confirm-loading="loading.mutation"
      :destroy-on-close="true"
      ok-text="创建"
      cancel-text="取消"
      @ok="handleCreateUser"
      @cancel="handleCloseCreate"
    >
      <a-form ref="createFormRef" :model="createForm" layout="vertical">
        <ARow :gutter="16">
          <ACol :span="12">
            <a-form-item
              label="用户名"
              name="username"
              :rules="[
                { required: true, message: '请输入用户名' },
                { min: 2, max: 50, message: '用户名长度需为 2–50 个字符' },
                { pattern: /^[^\s@]+$/, message: '用户名不能包含 @ 或空白' },
              ]"
            >
              <a-input v-model:value="createForm.username" autocomplete="off" />
            </a-form-item>
          </ACol>
          <ACol :span="12">
            <a-form-item
              label="角色"
              name="role"
              :rules="[{ required: true, message: '请选择角色' }]"
            >
              <ASelect v-model:value="createForm.role" :options="roleOptions" />
            </a-form-item>
          </ACol>
        </ARow>
        <ARow>
          <ACol :span="24">
            <a-form-item
              label="邮箱"
              name="email"
              :rules="[
                { required: true, message: '请输入邮箱' },
                { type: 'email', message: '请输入有效邮箱地址' },
              ]"
            >
              <a-input v-model:value="createForm.email" autocomplete="off" />
            </a-form-item>
          </ACol>
        </ARow>
        <ARow :gutter="16">
          <ACol :span="12">
            <a-form-item
              label="初始密码"
              name="password"
              :rules="[
                { required: true, message: '请输入初始密码' },
                { min: 10, max: 128, message: '密码长度需为 10–128 个字符' },
              ]"
            >
              <a-input-password
                v-model:value="createForm.password"
                autocomplete="new-password"
              />
            </a-form-item>
          </ACol>
          <ACol :span="12">
            <a-form-item
              label="确认密码"
              name="confirmPassword"
              :rules="[{ required: true, message: '请再次输入密码' }]"
            >
              <a-input-password
                v-model:value="createForm.confirmPassword"
                autocomplete="new-password"
              />
            </a-form-item>
          </ACol>
        </ARow>
        <a-alert
          type="info"
          show-icon
          message="管理员创建的账号立即生效，无需邮箱验证码。"
        />
      </a-form>
    </AModal>

    <AModal
      v-model:open="roleOpen"
      title="修改用户角色"
      :confirm-loading="loading.mutation"
      ok-text="保存"
      cancel-text="取消"
      @ok="handleUpdateRole"
      @cancel="handleCloseRole"
    >
      <a-form layout="vertical">
        <ARow :gutter="16">
          <ACol :span="12">
            <a-form-item label="用户">
              <a-input :value="roleTarget?.username || '--'" disabled />
            </a-form-item>
          </ACol>
          <ACol :span="12">
            <a-form-item label="角色">
              <ASelect v-model:value="roleValue" :options="roleOptions" />
            </a-form-item>
          </ACol>
        </ARow>
      </a-form>
    </AModal>
  </main>
</template>

<style scoped>
.admin-page {
  display: grid;
  grid-template-areas:
    "brand topbar"
    "sidebar workspace";
  grid-template-columns: 220px minmax(0, 1fr);
  grid-template-rows: 56px minmax(0, 1fr);
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  color: var(--color-fg);
  background: var(--color-surface-sunken);
}

.admin-brand,
.admin-topbar {
  position: relative;
  z-index: var(--z-raised);
  display: flex;
  align-items: center;
  color: var(--color-accent-fg);
  background: var(--color-info);
}

.admin-brand {
  grid-area: brand;
  gap: var(--space-2);
  padding: 0 var(--space-4);
  border-right: 1px solid rgba(255, 255, 255, 0.16);
}

.admin-brand__icon {
  font-size: var(--pa-text-page-title);
}

.admin-brand__name {
  font-size: var(--pa-text-section);
  font-weight: var(--font-semibold);
}

.admin-brand__badge {
  margin-left: auto;
  padding: 2px 6px;
  border: 1px solid rgba(255, 255, 255, 0.34);
  border-radius: var(--radius-sm);
  font-size: var(--pa-text-meta);
  letter-spacing: 0.08em;
}

.admin-topbar {
  grid-area: topbar;
  justify-content: space-between;
  gap: var(--space-4);
  min-width: 0;
  padding: 0 var(--space-5);
}

.admin-topbar__title,
.admin-topbar__actions,
.admin-topbar__identity {
  display: flex;
  align-items: center;
}

.admin-topbar__title {
  gap: var(--space-2);
  font-size: var(--pa-text-body);
  font-weight: var(--font-semibold);
}

.admin-topbar__actions {
  gap: var(--space-3);
  min-width: 0;
}

.admin-topbar__time {
  font-size: var(--pa-text-meta);
  color: rgba(255, 255, 255, 0.76);
  white-space: nowrap;
}

.admin-topbar__identity {
  gap: var(--space-1);
  padding-left: var(--space-3);
  border-left: 1px solid rgba(255, 255, 255, 0.24);
  font-size: var(--pa-text-compact);
  font-weight: var(--font-semibold);
  white-space: nowrap;
}

.admin-topbar__button {
  color: var(--color-accent-fg);
}

.admin-topbar__button:hover,
.admin-topbar__button:focus-visible {
  color: var(--color-accent-fg);
  background: rgba(255, 255, 255, 0.14);
}

.admin-sidebar {
  grid-area: sidebar;
  display: flex;
  min-height: 0;
  flex-direction: column;
  padding: var(--space-5) var(--space-3) var(--space-4);
  background: var(--color-rail-bg);
  color: var(--color-rail-fg);
}

.admin-sidebar__caption {
  padding: 0 var(--space-3) var(--space-3);
  font-size: var(--pa-text-meta);
  color: var(--color-rail-fg-muted);
  letter-spacing: 0.12em;
}

.admin-nav {
  display: grid;
  gap: var(--space-2);
}

.admin-nav__item {
  position: relative;
  display: flex;
  align-items: center;
  width: 100%;
  min-height: 64px;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  color: var(--color-rail-fg);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition:
    background var(--pa-motion-fast) var(--ease),
    border-color var(--pa-motion-fast) var(--ease),
    color var(--pa-motion-fast) var(--ease);
}

.admin-nav__item:hover {
  background: var(--color-rail-surface);
  color: var(--color-rail-fg-strong);
}

.admin-nav__item.is-active {
  border-color: var(--pa-rail-active-border);
  color: var(--color-rail-fg-strong);
  background: var(--color-rail-active);
}

.admin-nav__item.is-active::before {
  position: absolute;
  top: 12px;
  bottom: 12px;
  left: -12px;
  width: 3px;
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  background: var(--color-rail-accent);
  content: "";
}

.admin-nav__icon {
  flex: 0 0 auto;
  font-size: var(--pa-text-section);
  color: var(--color-rail-accent);
}

.admin-nav__item span,
.admin-nav__item strong,
.admin-nav__item small,
.admin-sidebar__footer span,
.admin-sidebar__footer strong,
.admin-sidebar__footer small {
  display: block;
  min-width: 0;
}

.admin-nav__item strong,
.admin-sidebar__footer strong {
  font-size: var(--pa-text-body);
}

.admin-nav__item small,
.admin-sidebar__footer small {
  margin-top: 3px;
  font-size: var(--pa-text-meta);
  color: var(--color-rail-fg-muted);
}

.admin-sidebar__footer {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: auto;
  padding: var(--space-3);
  border-top: 1px solid var(--color-rail-border);
  color: var(--color-rail-fg);
}

.admin-sidebar__footer > svg {
  color: var(--color-rail-accent);
  font-size: var(--pa-text-section);
}

.admin-workspace {
  grid-area: workspace;
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
}

.admin-breadcrumb {
  display: flex;
  align-items: center;
  flex: 0 0 42px;
  gap: var(--space-2);
  padding: 0 var(--space-5);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-compact);
}

.admin-breadcrumb strong {
  color: var(--color-fg);
}

.admin-breadcrumb__separator {
  color: var(--color-fg-faint);
}

.admin-content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--space-5);
}

.admin-content__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.admin-content__heading h1,
.admin-content__heading p,
.admin-panel__header h2,
.admin-panel__header p {
  margin: 0;
}

.admin-content__heading h1 {
  font-size: var(--pa-text-page-title);
  line-height: var(--leading-tight);
}

.admin-content__heading p {
  margin-top: var(--space-1);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-compact);
}

.admin-stats {
  display: grid;
  grid-template-columns: repeat(6, minmax(150px, 1fr));
  gap: var(--space-3);
}

.admin-stat {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.admin-stat__icon {
  display: grid;
  flex: 0 0 44px;
  width: 44px;
  height: 44px;
  place-items: center;
  border-radius: var(--radius-full);
  font-size: var(--pa-text-page-title);
}

.admin-stat--blue .admin-stat__icon {
  color: var(--color-info);
  background: var(--color-info-soft);
}

.admin-stat--cyan .admin-stat__icon,
.admin-stat--violet .admin-stat__icon {
  color: var(--color-accent-active);
  background: var(--color-accent-soft);
}

.admin-stat--green .admin-stat__icon {
  color: var(--color-success);
  background: var(--color-success-soft);
}

.admin-stat--orange .admin-stat__icon {
  color: var(--color-warning);
  background: var(--color-warning-soft);
}

.admin-stat--red .admin-stat__icon {
  color: var(--color-danger);
  background: var(--color-danger-soft);
}

.admin-stat div,
.admin-stat strong,
.admin-stat span,
.admin-stat small {
  display: block;
  min-width: 0;
}

.admin-stat strong {
  color: var(--color-fg);
  font-size: var(--pa-text-page-title);
  font-weight: var(--font-medium);
  line-height: var(--leading-tight);
}

.admin-stat span {
  margin-top: 2px;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-compact);
}

.admin-stat small {
  margin-top: 2px;
  overflow: hidden;
  color: var(--color-fg-faint);
  font-size: var(--pa-text-meta);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.admin-panel {
  margin-top: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.admin-panel--users {
  margin-top: 0;
}

.admin-panel__header,
.admin-user-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  min-height: 62px;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.admin-panel__header h2 {
  font-size: var(--pa-text-section);
}

.admin-panel__header p {
  margin-top: 2px;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}

.admin-panel__count,
.admin-user-toolbar > span {
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
  white-space: nowrap;
}

.health-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-3);
  padding: var(--space-4);
}

.health-item {
  display: flex;
  align-items: center;
  min-height: 68px;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-panel);
}

.health-item > svg {
  font-size: var(--pa-text-section);
}

.health-item__ok {
  color: var(--color-success);
}

.health-item__error {
  color: var(--color-danger);
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
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}

.admin-user-toolbar__search {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.admin-search {
  width: min(360px, 38vw);
}

.admin-user-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.user-cell {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.audit-path {
  color: var(--color-info-fg);
  word-break: break-all;
}

.admin-table :deep(.ant-table) {
  border-radius: 0 0 var(--radius-sm) var(--radius-sm);
}

.admin-table :deep(.ant-table-thead > tr > th) {
  color: var(--color-fg);
  background: var(--color-panel);
  font-weight: var(--font-semibold);
}

.admin-table :deep(.ant-pagination) {
  margin-right: var(--space-4);
}

@media (max-width: 1320px) {
  .admin-stats {
    grid-template-columns: repeat(3, minmax(170px, 1fr));
  }
}

@media (max-width: 960px) {
  .admin-page {
    grid-template-columns: 78px minmax(0, 1fr);
  }

  .admin-brand {
    justify-content: center;
    padding: 0;
  }

  .admin-brand__name,
  .admin-brand__badge,
  .admin-sidebar__caption,
  .admin-nav__item small,
  .admin-sidebar__footer span {
    display: none;
  }

  .admin-sidebar {
    padding-inline: var(--space-2);
  }

  .admin-nav__item {
    justify-content: center;
    min-height: 66px;
    flex-direction: column;
    gap: var(--space-1);
    padding: var(--space-2);
    text-align: center;
  }

  .admin-nav__item.is-active::before {
    left: -8px;
  }

  .admin-sidebar__footer {
    justify-content: center;
  }

  .admin-topbar__time {
    display: none;
  }
}

@media (max-width: 720px) {
  .admin-topbar {
    padding: 0 var(--space-3);
  }

  .admin-topbar__title span,
  .admin-topbar__identity {
    display: none;
  }

  .admin-content {
    padding: var(--space-3);
  }

  .admin-stats {
    grid-template-columns: repeat(2, minmax(150px, 1fr));
  }

  .admin-content__heading,
  .admin-user-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .admin-user-toolbar__search {
    width: 100%;
  }

  .admin-search {
    width: 100%;
  }
}
</style>
