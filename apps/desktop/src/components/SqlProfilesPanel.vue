<script setup lang="ts">
/**
 * SqlProfilesPanel · v0.5.0 rc.2 只读 SQL 连接 profile 管理
 *
 * 安全边界（验收修复）：数据库密码只经桌面壳原生系统凭据对话框（CredUI）
 * 写入 OS keyring，不进入 Vue 状态、API 请求或数据库；keyring 引用由后端
 * 生成。配置后需重启应用使密码注入生效。
 */
import { onMounted, ref } from "vue";
import { PhDatabase, PhKey, PhPlus, PhTrash } from "@phosphor-icons/vue";
import type { SqlReadonlyProfile } from "../types";
import {
  createSqlProfile,
  deleteSqlProfile,
  listSqlProfiles,
  updateSqlProfile,
} from "../api";
import PaBadge from "../design/PaBadge.vue";
import PaButton from "../design/PaButton.vue";
import PaDialog from "../design/PaDialog.vue";
import PaEmptyState from "../design/PaEmptyState.vue";
import PaInlineNotice from "../design/PaInlineNotice.vue";
import PaSpinner from "../design/PaSpinner.vue";
import {
  clearSqlProfileSecret,
  desktopCapable,
  promptSqlProfileSecret,
  sqlProfileSecretStatus,
} from "../api/credentials";

const profiles = ref<SqlReadonlyProfile[]>([]);
const loading = ref(true);
const loadError = ref("");
const showEditor = ref(false);
const saving = ref(false);
const editorError = ref("");
const isDesktop = ref(false);
const confirmDelete = ref<SqlReadonlyProfile | null>(null);

const editing = ref<SqlReadonlyProfile | null>(null);
const form = ref({
  name: "",
  host: "127.0.0.1",
  port: 3306,
  database: "",
  username: "root",
  max_rows: 1000,
  max_bytes: 1048576,
  timeout_ms: 30000,
  enabled: true,
});
/** 密码 keyring 配置状态（仅布尔，不含明文） */
const passwordConfigured = ref(false);

async function load() {
  loading.value = true;
  loadError.value = "";
  try {
    profiles.value = await listSqlProfiles();
  } catch (error) {
    loadError.value = String(error);
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editing.value = null;
  form.value = {
    name: "",
    host: "127.0.0.1",
    port: 3306,
    database: "",
    username: "root",
    max_rows: 1000,
    max_bytes: 1048576,
    timeout_ms: 30000,
    enabled: true,
  };
  passwordConfigured.value = false;
  editorError.value = "";
  showEditor.value = true;
}

function openEdit(profile: SqlReadonlyProfile) {
  editing.value = profile;
  form.value = {
    name: profile.name,
    host: profile.host,
    port: profile.port,
    database: profile.database,
    username: profile.username ?? "",
    max_rows: profile.max_rows,
    max_bytes: profile.max_bytes,
    timeout_ms: profile.timeout_ms,
    enabled: profile.enabled,
  };
  passwordConfigured.value = false;
  editorError.value = "";
  showEditor.value = true;
  if (isDesktop.value) {
    void refreshPasswordStatus(profile.name);
  }
}

async function refreshPasswordStatus(name: string) {
  if (!isDesktop.value) return;
  try {
    const status = await sqlProfileSecretStatus(name);
    passwordConfigured.value = status.configured;
  } catch {
    passwordConfigured.value = false;
  }
}

/**
 * 原生系统凭据对话框写入 keyring（明文不经 Vue）。
 * 仅在已保存 profile（编辑模式）下可用，避免取消/保存失败留下孤立凭据。
 */
async function promptPassword() {
  if (!isDesktop.value) {
    editorError.value = "仅桌面版可配置系统凭据";
    return;
  }
  if (!editing.value) {
    editorError.value = "请先保存连接，再设置密码（避免孤立凭据）";
    return;
  }
  try {
    const result = await promptSqlProfileSecret(form.value.name.trim());
    passwordConfigured.value = result.configured;
  } catch (error) {
    editorError.value = `写入系统凭据失败：${String(error)}`;
  }
}

async function save() {
  saving.value = true;
  editorError.value = "";
  try {
    const payload = {
      dialect: "mysql",
      host: form.value.host.trim(),
      port: form.value.port,
      database: form.value.database.trim(),
      username: form.value.username.trim() || null,
      max_rows: form.value.max_rows,
      max_bytes: form.value.max_bytes,
      timeout_ms: form.value.timeout_ms,
      enabled: form.value.enabled,
    };
    if (editing.value) {
      await updateSqlProfile(editing.value.id, payload);
    } else {
      await createSqlProfile(payload);
    }
    showEditor.value = false;
    await load();
  } catch (error) {
    editorError.value = String(error);
  } finally {
    saving.value = false;
  }
}

const cleanupError = ref("");

async function remove(profile: SqlReadonlyProfile) {
  try {
    const result = await deleteSqlProfile(profile.id);
    if (isDesktop.value && result.password_secret_ref) {
      cleanupError.value = "";
      try {
        await clearSqlProfileSecret(profile.name);
      } catch {
        cleanupError.value =
          "系统凭据清理失败（重试或手动在系统凭据库中删除该条目）";
      }
    }
    confirmDelete.value = null;
    await load();
  } catch (error) {
    loadError.value = String(error);
    confirmDelete.value = null;
  }
}

async function toggleEnabled(profile: SqlReadonlyProfile) {
  try {
    await updateSqlProfile(profile.id, { enabled: !profile.enabled });
    await load();
  } catch (error) {
    loadError.value = String(error);
  }
}

onMounted(async () => {
  isDesktop.value = await desktopCapable();
  await load();
});
</script>

<template>
  <section class="sql-panel" aria-label="只读数据库配置">
    <div class="panel-head">
      <h3>只读数据库</h3>
      <PaButton size="sm" variant="primary" @click="openCreate">
        <PhPlus :size="13" /> 新建连接
      </PaButton>
    </div>
    <p class="panel-hint">
      Agent 只能查询这里保存且已启用的连接，且仅允许 SELECT/EXPLAIN/SHOW 等只读
      语句（解析 + 只读事务双重限制）。密码只存入系统凭据库（OS keyring），
      不进入数据库、日志、模型参数或界面状态。
    </p>

    <PaSpinner v-if="loading" :label="'加载连接配置'" />
    <PaInlineNotice v-if="loadError" tone="danger" title="操作失败" @click="load">
      {{ loadError }}
    </PaInlineNotice>
    <PaInlineNotice v-if="cleanupError" tone="warning" title="凭据清理未完成">
      {{ cleanupError }}
      <button class="text-btn" @click="confirmDelete && remove(confirmDelete)">重试</button>
    </PaInlineNotice>
    <PaEmptyState
      v-else-if="profiles.length === 0"
      :icon="PhDatabase"
      title="尚未配置只读数据库"
      description="先添加一个只读连接 profile，Agent 才会获得受限的查询能力。"
    />

    <ul v-else class="profile-list">
      <li v-for="profile in profiles" :key="profile.id" class="profile-item">
        <div class="profile-copy">
          <strong>{{ profile.name }}</strong>
          <code>
            {{ profile.dialect }}://{{ profile.host }}:{{ profile.port }}/{{ profile.database }}
          </code>
          <span class="profile-meta">
            {{ profile.username || "（匿名）" }}
            · 行数上限 {{ profile.max_rows }}
            · 超时 {{ Math.round(profile.timeout_ms / 1000) }}s
            <template v-if="profile.password_secret_ref">
              · <PhKey :size="11" /> 密码存系统凭据库
            </template>
          </span>
        </div>
        <div class="profile-actions">
          <PaBadge :tone="profile.enabled ? 'success' : 'muted'">
            {{ profile.enabled ? "已启用" : "已禁用" }}
          </PaBadge>
          <button class="text-btn" @click="toggleEnabled(profile)">
            {{ profile.enabled ? "禁用" : "启用" }}
          </button>
          <button class="text-btn" @click="openEdit(profile)">编辑</button>
          <button class="text-btn danger" @click="confirmDelete = profile">
            <PhTrash :size="13" />
          </button>
        </div>
      </li>
    </ul>

    <PaDialog
      v-if="showEditor"
      :open="true"
      :title="editing ? `编辑连接 · ${editing.name}` : '新建只读连接'"
      :width="600"
      @close="showEditor = false"
    >
      <form class="editor-form" @submit.prevent="save">
        <label v-if="!editing">
          <span>名称</span>
          <input v-model="form.name" required maxlength="64" placeholder="如 reports-db" />
        </label>
        <div class="form-row">
          <label>
            <span>Host</span>
            <input v-model="form.host" required maxlength="255" />
          </label>
          <label>
            <span>Port</span>
            <input v-model.number="form.port" type="number" min="1" max="65535" required />
          </label>
        </div>
        <label>
          <span>数据库</span>
          <input v-model="form.database" required maxlength="255" />
        </label>
        <div class="form-row two">
          <label>
            <span>用户名</span>
            <input v-model="form.username" maxlength="255" />
          </label>
        </div>

        <div class="secret-section">
          <div class="secret-row">
            <PhKey :size="13" />
            <span class="secret-label">数据库密码</span>
            <PaBadge :tone="passwordConfigured ? 'success' : 'warning'">
              {{ passwordConfigured ? "已存入系统凭据库" : "未配置" }}
            </PaBadge>
            <PaButton
              v-if="isDesktop"
              size="sm"
              type="button"
              variant="ghost"
              :disabled="!editing"
              @click="promptPassword"
            >
              {{ passwordConfigured ? "更新密码" : "设置密码" }}
            </PaButton>
          </div>
          <p class="secret-hint">
            {{
              editing
                ? "点击按钮会打开系统凭据对话框；明文不进入界面。配置后需重启应用使密码注入生效。"
                : "先保存连接，再打开编辑设置密码（避免孤立凭据）。"
            }}
          </p>
        </div>

        <div class="form-row">
          <label>
            <span>行数上限</span>
            <input v-model.number="form.max_rows" type="number" min="1" max="100000" />
          </label>
          <label>
            <span>超时（毫秒）</span>
            <input v-model.number="form.timeout_ms" type="number" min="1000" max="60000" />
          </label>
          <label>
            <span>启用</span>
            <input v-model="form.enabled" type="checkbox" />
          </label>
        </div>

        <PaInlineNotice v-if="editorError" tone="danger" title="保存失败">
          {{ editorError }}
        </PaInlineNotice>

        <div class="form-actions">
          <PaButton type="button" variant="ghost" @click="showEditor = false">取消</PaButton>
          <PaButton type="submit" variant="primary" :disabled="saving">
            {{ saving ? "保存中…" : "保存" }}
          </PaButton>
        </div>
      </form>
    </PaDialog>

    <PaDialog
      v-if="confirmDelete"
      :open="true"
      :title="`删除连接 · ${confirmDelete.name}`"
      :width="480"
      @close="confirmDelete = null"
    >
      <p class="confirm-copy">
        删除后模型将无法查询该连接；对应的系统凭据库条目也会被清理。
        此操作不可撤销。
      </p>
      <div class="form-actions">
        <PaButton type="button" variant="ghost" @click="confirmDelete = null">取消</PaButton>
        <PaButton type="button" variant="primary" @click="remove(confirmDelete)">
          确认删除
        </PaButton>
      </div>
    </PaDialog>
  </section>
</template>

<style scoped>
.sql-panel { display: grid; gap: var(--space-3); }
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
.panel-head h3 { margin: 0; font-size: var(--pa-text-compact); }
.panel-hint { margin: 0; color: var(--color-fg-faint); font-size: var(--pa-t-12); line-height: 1.5; }
.profile-list { display: grid; gap: var(--space-2); margin: 0; padding: 0; list-style: none; }
.profile-item {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.profile-copy { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
.profile-copy strong { color: var(--color-fg); font-size: var(--pa-text-compact); }
.profile-copy code { color: var(--color-fg-muted); font-family: var(--font-mono); font-size: var(--pa-t-12); }
.profile-meta { display: inline-flex; align-items: center; gap: 4px; color: var(--color-fg-faint); font-size: var(--pa-t-12); }
.profile-actions { display: flex; flex-shrink: 0; align-items: center; gap: var(--space-2); }
.text-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 4px 6px;
  border: 0;
  background: transparent;
  color: var(--color-accent);
  font: inherit;
  font-size: var(--pa-t-12);
  cursor: pointer;
}
.text-btn.danger { color: var(--color-danger); }
.editor-form { display: grid; gap: var(--space-3); }
.editor-form label { display: grid; gap: 4px; font-size: var(--pa-t-12); color: var(--color-fg-muted); }
.editor-form input:not([type="checkbox"]) {
  padding: 7px 9px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-fg);
  font: inherit;
  font-size: var(--pa-text-compact);
}
.form-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-2); }
.form-row.two { grid-template-columns: repeat(2, 1fr); }
.secret-section { display: grid; gap: var(--space-2); padding: var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-md); }
.secret-row { display: flex; align-items: center; gap: var(--space-2); font-size: var(--pa-t-12); }
.secret-label { color: var(--color-fg); }
.secret-hint { margin: 0; color: var(--color-fg-faint); font-size: var(--pa-t-12); line-height: 1.5; }
.form-actions { display: flex; justify-content: flex-end; gap: var(--space-2); }
.confirm-copy { margin: 0; color: var(--color-fg-muted); font-size: var(--pa-text-compact); line-height: 1.6; }
</style>
