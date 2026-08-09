<script setup lang="ts">
/**
 * HttpProfilesPanel · v0.5.0 rc.2 HTTP endpoint profile 管理
 *
 * 安全边界（验收修复）：
 * - 明文 API key 只经桌面壳原生系统凭据对话框（CredUI）写入 OS keyring，
 *   不进入 Vue 状态、API 请求或数据库；
 * - 前端只声明需要密钥的请求头名（secret_slots）；keyring 引用由后端生成
 *   并保存（secret_refs）；executor 运行时从 keyring 通道解析注入；
 * - 删除 profile 时同步清理对应 keyring 条目；重新配置后重启 sidecar 生效。
 */
import { computed, onMounted, ref } from "vue";
import { PhGlobe, PhKey, PhPlus, PhTrash } from "@phosphor-icons/vue";
import type { HttpEndpointProfile } from "../types";
import {
  createHttpProfile,
  deleteHttpProfile,
  listHttpProfiles,
  updateHttpProfile,
} from "../api";
import PaBadge from "../design/PaBadge.vue";
import PaButton from "../design/PaButton.vue";
import PaDialog from "../design/PaDialog.vue";
import PaEmptyState from "../design/PaEmptyState.vue";
import PaInlineNotice from "../design/PaInlineNotice.vue";
import PaSpinner from "../design/PaSpinner.vue";

const profiles = ref<HttpEndpointProfile[]>([]);
const loading = ref(true);
const loadError = ref("");
const showEditor = ref(false);
const saving = ref(false);
const editorError = ref("");
const isDesktop = ref(false);
const confirmDelete = ref<HttpEndpointProfile | null>(null);

const editing = ref<HttpEndpointProfile | null>(null);
const form = ref({
  name: "",
  scheme: "https",
  host: "",
  port: 443,
  path_prefix: "/",
  allowed_methods: ["GET"] as string[],
  timeout_ms: 30000,
  max_response_bytes_kb: 1024,
  allow_insecure_local: false,
  allow_private_network: false,
  enabled: true,
});
/** 需要密钥的请求头名（仅声明，不含任何明文） */
const secretSlots = ref<string[]>([]);
/** header → keyring 配置状态（桌面环境经 status command 查询） */
const secretStatus = ref<Record<string, "configured" | "missing" | "unknown">>({});
const newSecretHeader = ref("");

async function load() {
  loading.value = true;
  loadError.value = "";
  try {
    profiles.value = await listHttpProfiles();
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
    scheme: "https",
    host: "",
    port: 443,
    path_prefix: "/",
    allowed_methods: ["GET"],
    timeout_ms: 30000,
    max_response_bytes_kb: 1024,
    allow_insecure_local: false,
    allow_private_network: false,
    enabled: true,
  };
  secretSlots.value = [];
  secretStatus.value = {};
  editorError.value = "";
  showEditor.value = true;
}

function openEdit(profile: HttpEndpointProfile) {
  editing.value = profile;
  form.value = {
    name: profile.name,
    scheme: profile.scheme,
    host: profile.host,
    port: profile.port,
    path_prefix: profile.path_prefix,
    allowed_methods: [...profile.allowed_methods],
    timeout_ms: profile.timeout_ms,
    max_response_bytes_kb: Math.round(profile.max_response_bytes / 1024),
    allow_insecure_local: profile.allow_insecure_local,
    allow_private_network: profile.allow_private_network,
    enabled: profile.enabled,
  };
  secretSlots.value = [...profile.secret_slots];
  secretStatus.value = {};
  editorError.value = "";
  showEditor.value = true;
  if (isDesktop.value) {
    void refreshSecretStatus(profile.name);
  }
}

function toggleMethod(method: string) {
  const index = form.value.allowed_methods.indexOf(method);
  if (index >= 0) {
    if (form.value.allowed_methods.length > 1) {
      form.value.allowed_methods.splice(index, 1);
    }
  } else {
    form.value.allowed_methods.push(method);
  }
}

function addSecretSlot() {
  const header = newSecretHeader.value.trim();
  if (!header || secretSlots.value.includes(header)) return;
  secretSlots.value.push(header);
  secretStatus.value[header] = "unknown";
  newSecretHeader.value = "";
}

function removeSecretSlot(header: string) {
  secretSlots.value = secretSlots.value.filter((item) => item !== header);
  delete secretStatus.value[header];
}

function slotForHeader(header: string): string {
  return header.toLowerCase().replace(/[^a-z0-9.-]/g, "-").slice(0, 64) || "header";
}

async function refreshSecretStatus(name: string) {
  if (!isDesktop.value) return;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    for (const header of secretSlots.value) {
      try {
        const status = await invoke<{ configured: boolean }>(
          "http_profile_secret_status",
          { name, slot: slotForHeader(header) }
        );
        secretStatus.value[header] = status.configured ? "configured" : "missing";
      } catch {
        secretStatus.value[header] = "unknown";
      }
    }
  } catch {
    // 非桌面环境静默
  }
}

/** 原生系统凭据对话框写入 keyring（明文不经 Vue） */
async function promptSecret(header: string) {
  if (!isDesktop.value) {
    editorError.value = "仅桌面版可配置系统凭据";
    return;
  }
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const result = await invoke<{ configured: boolean; cancelled: boolean }>(
      "prompt_http_profile_secret",
      { name: form.value.name.trim(), slot: slotForHeader(header) }
    );
    secretStatus.value[header] = result.configured ? "configured" : "missing";
  } catch (error) {
    editorError.value = `写入系统凭据失败：${String(error)}`;
  }
}

async function save() {
  saving.value = true;
  editorError.value = "";
  try {
    const payload: Record<string, unknown> = {
      scheme: form.value.scheme,
      host: form.value.host.trim(),
      port: form.value.port,
      path_prefix: form.value.path_prefix || "/",
      allowed_methods: form.value.allowed_methods,
      timeout_ms: form.value.timeout_ms,
      max_response_bytes: form.value.max_response_bytes_kb * 1024,
      allow_insecure_local: form.value.allow_insecure_local,
      allow_private_network: form.value.allow_private_network,
      enabled: form.value.enabled,
      headers: {},
      secret_slots: secretSlots.value,
    };
    if (editing.value) {
      await updateHttpProfile(editing.value.id, payload);
    } else {
      payload.name = form.value.name.trim();
      await createHttpProfile(payload);
    }
    showEditor.value = false;
    await load();
  } catch (error) {
    editorError.value = String(error);
  } finally {
    saving.value = false;
  }
}

async function remove(profile: HttpEndpointProfile) {
  try {
    const result = await deleteHttpProfile(profile.id);
    // 同步清理对应 OS keyring 条目（引用 → slot）
    if (isDesktop.value) {
      const { invoke } = await import("@tauri-apps/api/core");
      for (const reference of Object.values(result.secret_refs ?? {})) {
        const match = /^secret:\/\/os-keyring\/http\/[^/]+\/([^/]+)$/.exec(
          reference
        );
        if (match) {
          try {
            await invoke("clear_http_profile_secret", {
              name: profile.name,
              slot: match[1],
            });
          } catch {
            // keyring 清理失败不阻断删除
          }
        }
      }
    }
    confirmDelete.value = null;
    await load();
  } catch (error) {
    loadError.value = String(error);
    confirmDelete.value = null;
  }
}

async function toggleEnabled(profile: HttpEndpointProfile) {
  try {
    await updateHttpProfile(profile.id, { enabled: !profile.enabled });
    await load();
  } catch (error) {
    loadError.value = String(error);
  }
}

const hasSecretSlots = computed(() => secretSlots.value.length > 0);

onMounted(async () => {
  try {
    const { isTauri } = await import("@tauri-apps/api/core");
    isDesktop.value = Boolean(isTauri());
  } catch {
    isDesktop.value = false;
  }
  await load();
});
</script>

<template>
  <section class="http-panel" aria-label="HTTP 端点配置">
    <div class="panel-head">
      <h3>HTTP 端点</h3>
      <PaButton size="sm" variant="primary" @click="openCreate">
        <PhPlus :size="13" /> 新建端点
      </PaButton>
    </div>
    <p class="panel-hint">
      Agent 只能调用这里保存且已启用的端点；目标、方法、Schema、大小与超时均由
      profile 固定。API key 只存入系统凭据库（OS keyring），不进入数据库、日志、
      模型参数或界面状态。
    </p>

    <PaSpinner v-if="loading" :label="'加载端点配置'" />
    <PaInlineNotice v-else-if="loadError" tone="danger" title="加载失败" @click="load">
      {{ loadError }}
    </PaInlineNotice>
    <PaEmptyState
      v-else-if="profiles.length === 0"
      :icon="PhGlobe"
      title="尚未配置 HTTP 端点"
      description="先添加一个端点 profile，Agent 才会获得受限的 HTTP 调用能力。"
    />

    <ul v-else class="profile-list">
      <li v-for="profile in profiles" :key="profile.id" class="profile-item">
        <div class="profile-copy">
          <strong>{{ profile.name }}</strong>
          <code>
            {{ profile.scheme }}://{{ profile.host }}:{{ profile.port }}{{ profile.path_prefix }}
          </code>
          <span class="profile-meta">
            {{ profile.allowed_methods.join(" · ") }}
            · 超时 {{ Math.round(profile.timeout_ms / 1000) }}s
            · 响应上限 {{ Math.round(profile.max_response_bytes / 1024) }}KB
            <template v-if="profile.secret_slots.length">
              · <PhKey :size="11" /> {{ profile.secret_slots.length }} 个密钥槽位
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
      :title="editing ? `编辑端点 · ${editing.name}` : '新建 HTTP 端点'"
      :width="640"
      @close="showEditor = false"
    >
      <form class="editor-form" @submit.prevent="save">
        <label v-if="!editing">
          <span>名称</span>
          <input v-model="form.name" required maxlength="64" placeholder="如 weather-api" />
        </label>
        <div class="form-row">
          <label>
            <span>Scheme</span>
            <select v-model="form.scheme">
              <option value="https">https</option>
              <option value="http">http（需允许环回）</option>
            </select>
          </label>
          <label>
            <span>Host</span>
            <input v-model="form.host" required maxlength="255" placeholder="api.example.com" />
          </label>
          <label>
            <span>Port</span>
            <input v-model.number="form.port" type="number" min="1" max="65535" required />
          </label>
        </div>
        <label>
          <span>Path 前缀</span>
          <input v-model="form.path_prefix" placeholder="/v1" />
        </label>
        <div class="form-row">
          <label>
            <span>允许的方法</span>
            <div class="method-pills">
              <button
                v-for="method in ['GET', 'HEAD', 'POST']"
                :key="method"
                type="button"
                class="method-pill"
                :class="{ active: form.allowed_methods.includes(method) }"
                @click="toggleMethod(method)"
              >
                {{ method }}
              </button>
            </div>
          </label>
        </div>
        <div class="form-row">
          <label>
            <span>超时（毫秒）</span>
            <input v-model.number="form.timeout_ms" type="number" min="1000" max="60000" />
          </label>
          <label>
            <span>响应上限（KB）</span>
            <input
              v-model.number="form.max_response_bytes_kb"
              type="number"
              min="1"
              max="8192"
            />
          </label>
        </div>
        <div class="form-row checks">
          <label>
            <input v-model="form.allow_insecure_local" type="checkbox" />
            允许环回 http（本地开发服务）
          </label>
          <label>
            <input v-model="form.allow_private_network" type="checkbox" />
            允许私网地址（内部服务）
          </label>
          <label>
            <input v-model="form.enabled" type="checkbox" />
            启用
          </label>
        </div>

        <details class="secret-section" :open="hasSecretSlots">
          <summary>
            <PhKey :size="13" /> API key（存入系统凭据库，明文不进界面）
          </summary>
          <p class="secret-hint">
            先声明需要密钥的请求头名并保存 profile，然后在桌面版中点「设置密钥」
            打开系统凭据对话框。配置后需重启应用使密钥注入生效。
          </p>
          <div v-for="header in secretSlots" :key="header" class="secret-row">
            <code>{{ header }}</code>
            <PaBadge
              :tone="
                secretStatus[header] === 'configured'
                  ? 'success'
                  : secretStatus[header] === 'missing'
                    ? 'warning'
                    : 'muted'
              "
            >
              {{
                secretStatus[header] === "configured"
                  ? "已配置"
                  : secretStatus[header] === "missing"
                    ? "未配置"
                    : isDesktop
                      ? "未知"
                      : "桌面版可配置"
              }}
            </PaBadge>
            <PaButton
              v-if="isDesktop"
              size="sm"
              type="button"
              variant="ghost"
              :disabled="!form.name.trim()"
              @click="promptSecret(header)"
            >
              设置密钥
            </PaButton>
            <button type="button" class="text-btn" @click="removeSecretSlot(header)">
              移除
            </button>
          </div>
          <div class="secret-add">
            <input
              v-model="newSecretHeader"
              placeholder="请求头名，如 X-Api-Key"
              @keyup.enter="addSecretSlot"
            />
            <PaButton size="sm" type="button" @click="addSecretSlot">添加</PaButton>
          </div>
        </details>

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
      :title="`删除端点 · ${confirmDelete.name}`"
      :width="480"
      @close="confirmDelete = null"
    >
      <p class="confirm-copy">
        删除后模型将无法调用该端点；对应的系统凭据库条目也会被清理。
        此操作不可撤销。
      </p>
      <div class="form-actions">
        <PaButton type="button" variant="ghost" @click="confirmDelete = null">取消</PaButton>
        <PaButton
          type="button"
          variant="primary"
          tone="danger"
          @click="remove(confirmDelete)"
        >
          确认删除
        </PaButton>
      </div>
    </PaDialog>
  </section>
</template>

<style scoped>
.http-panel { display: grid; gap: var(--space-3); }
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
.editor-form input:not([type="checkbox"]),
.editor-form select {
  padding: 7px 9px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-fg);
  font: inherit;
  font-size: var(--pa-text-compact);
}
.form-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-2); }
.form-row.checks { display: flex; flex-wrap: wrap; gap: var(--space-3); font-size: var(--pa-t-12); }
.form-row.checks label { display: inline-flex; align-items: center; gap: 4px; }
.method-pills { display: flex; gap: 6px; }
.method-pill {
  padding: 5px 10px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: transparent;
  color: var(--color-fg-muted);
  font: inherit;
  font-size: var(--pa-t-12);
  cursor: pointer;
}
.method-pill.active { border-color: var(--color-accent); color: var(--color-accent); }
.secret-section { display: grid; gap: var(--space-2); }
.secret-section summary { cursor: pointer; color: var(--color-fg-muted); font-size: var(--pa-t-12); }
.secret-hint { margin: 0; color: var(--color-fg-faint); font-size: var(--pa-t-12); line-height: 1.5; }
.secret-row { display: flex; align-items: center; gap: var(--space-2); font-size: var(--pa-t-12); }
.secret-row code { color: var(--color-fg); font-family: var(--font-mono); }
.secret-add { display: flex; gap: 6px; }
.secret-add input { flex: 1; }
.form-actions { display: flex; justify-content: flex-end; gap: var(--space-2); }
.confirm-copy { margin: 0; color: var(--color-fg-muted); font-size: var(--pa-text-compact); line-height: 1.6; }
</style>
