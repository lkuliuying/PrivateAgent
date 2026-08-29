<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { PhCamera, PhTrash, PhUserCircle } from "@phosphor-icons/vue";

import { useAuthStore } from "../stores/auth";

interface LocalProfile {
  avatarDataUrl: string;
  nickname: string;
  bio: string;
}

const auth = useAuthStore();
const fileInput = ref<HTMLInputElement | null>(null);
const avatarDataUrl = ref("");
const nickname = ref("");
const bio = ref("");
const feedback = ref("");
const feedbackTone = ref<"success" | "error">("success");

const storageKey = computed(() => `pa.local-profile.${auth.user?.id ?? "guest"}`);
const username = computed(() => auth.user?.username?.trim() || "未登录");
const initial = computed(() => (nickname.value.trim() || username.value).slice(0, 1).toUpperCase());
const roleLabel = computed(() => auth.user?.role === "admin" ? "管理员" : "普通用户");
const statusLabel = computed(() => auth.user?.status === "disabled" ? "已停用" : "正常");

function readLocalProfile(): void {
  feedback.value = "";
  avatarDataUrl.value = "";
  nickname.value = auth.user?.display_name?.trim() || auth.user?.username?.trim() || "";
  bio.value = "";
  try {
    const raw = window.localStorage.getItem(storageKey.value);
    if (!raw) return;
    const saved = JSON.parse(raw) as Partial<LocalProfile>;
    avatarDataUrl.value = typeof saved.avatarDataUrl === "string" ? saved.avatarDataUrl : "";
    nickname.value = typeof saved.nickname === "string" ? saved.nickname : nickname.value;
    bio.value = typeof saved.bio === "string" ? saved.bio : "";
  } catch {
    // 本机旧数据不可解析时回到账号默认信息，不阻断设置页。
  }
}

watch(() => auth.user?.id ?? null, readLocalProfile, { immediate: true });

function chooseAvatar(): void {
  fileInput.value?.click();
}

function onAvatarSelected(event: Event): void {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    feedbackTone.value = "error";
    feedback.value = "请选择 PNG、JPG 或 WebP 图片。";
    return;
  }
  if (file.size > 1024 * 1024) {
    feedbackTone.value = "error";
    feedback.value = "头像图片不能超过 1 MB。";
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    avatarDataUrl.value = typeof reader.result === "string" ? reader.result : "";
    feedback.value = "";
  };
  reader.onerror = () => {
    feedbackTone.value = "error";
    feedback.value = "头像读取失败，请重新选择。";
  };
  reader.readAsDataURL(file);
}

function removeAvatar(): void {
  avatarDataUrl.value = "";
  feedback.value = "";
}

function saveProfile(): void {
  try {
    const value: LocalProfile = {
      avatarDataUrl: avatarDataUrl.value,
      nickname: nickname.value.trim(),
      bio: bio.value.trim(),
    };
    window.localStorage.setItem(storageKey.value, JSON.stringify(value));
    feedbackTone.value = "success";
    feedback.value = "个人资料已保存在当前设备。";
  } catch {
    feedbackTone.value = "error";
    feedback.value = "本机存储空间不足，个人资料未保存。";
  }
}
</script>

<template>
  <div class="profile-panel" data-testid="profile-settings-panel">
    <section class="avatar-section" aria-labelledby="profile-avatar-title">
      <div class="avatar-preview">
        <img v-if="avatarDataUrl" :src="avatarDataUrl" alt="当前头像" />
        <span v-else-if="initial" aria-hidden="true">{{ initial }}</span>
        <PhUserCircle v-else :size="54" weight="fill" aria-hidden="true" />
      </div>
      <div class="avatar-copy">
        <h3 id="profile-avatar-title">个人头像</h3>
        <p>支持 PNG、JPG、WebP，图片不超过 1 MB。</p>
        <div class="avatar-actions">
          <button type="button" class="profile-button" data-testid="profile-avatar-upload" @click="chooseAvatar">
            <PhCamera :size="16" aria-hidden="true" />
            上传头像
          </button>
          <button v-if="avatarDataUrl" type="button" class="profile-button secondary" @click="removeAvatar">
            <PhTrash :size="15" aria-hidden="true" />
            移除
          </button>
        </div>
        <input
          ref="fileInput"
          class="file-input"
          type="file"
          accept="image/png,image/jpeg,image/webp"
          data-testid="profile-avatar-input"
          @change="onAvatarSelected"
        />
      </div>
    </section>

    <div class="profile-fields">
      <label>
        <span>称呼</span>
        <input v-model="nickname" maxlength="50" autocomplete="nickname" />
      </label>
      <label class="profile-fields__wide">
        <span>个人简介</span>
        <textarea v-model="bio" maxlength="240" rows="3" placeholder="简单介绍一下自己（可选）" />
      </label>
    </div>

    <dl class="account-facts">
      <div><dt>用户名</dt><dd>{{ username }}</dd></div>
      <div><dt>邮箱</dt><dd>{{ auth.user?.email || "—" }}</dd></div>
      <div><dt>账号角色</dt><dd>{{ roleLabel }}</dd></div>
      <div><dt>账号状态</dt><dd>{{ statusLabel }}</dd></div>
    </dl>

    <footer class="profile-footer">
      <p>首版个人资料仅保存在当前设备，暂不跨设备同步。</p>
      <div class="profile-footer__action">
        <span v-if="feedback" :class="`feedback ${feedbackTone}`" role="status">{{ feedback }}</span>
        <button type="button" class="profile-button" data-testid="profile-save" @click="saveProfile">保存资料</button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.profile-panel { display: grid; gap: 22px; }
.avatar-section {
  display: flex;
  align-items: center;
  gap: 18px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--color-border);
}
.avatar-preview {
  display: grid;
  width: 82px;
  height: 82px;
  flex: 0 0 auto;
  place-items: center;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-surface-sunken);
  color: var(--color-accent);
  font-size: 28px;
  font-weight: var(--font-semibold);
}
.avatar-preview img { width: 100%; height: 100%; object-fit: cover; }
.avatar-copy { min-width: 0; }
.avatar-copy h3 { margin: 0; font-size: var(--text-base); }
.avatar-copy p { margin: 4px 0 10px; color: var(--color-fg-subtle); font-size: var(--text-xs); }
.avatar-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.file-input { position: absolute; width: 1px; height: 1px; overflow: hidden; opacity: 0; pointer-events: none; }
.profile-button {
  display: inline-flex;
  height: 34px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 13px;
  border: 1px solid var(--color-accent);
  border-radius: 9px;
  background: var(--color-accent);
  color: white;
  font: inherit;
  font-size: var(--text-xs);
  cursor: pointer;
}
.profile-button.secondary { border-color: var(--color-border); background: var(--color-surface); color: var(--color-fg-muted); }
.profile-button:hover { filter: brightness(.97); }
.profile-button:focus-visible,
.profile-fields input:focus-visible,
.profile-fields textarea:focus-visible { outline: var(--focus-ring); outline-offset: 2px; }
.profile-fields { display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; }
.profile-fields label { display: grid; gap: 6px; color: var(--color-fg-muted); font-size: var(--text-xs); }
.profile-fields input,
.profile-fields textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 9px 11px;
  border: 1px solid var(--color-border-strong);
  border-radius: 9px;
  background: var(--color-surface);
  color: var(--color-fg);
  font: inherit;
}
.profile-fields textarea { resize: vertical; }
.account-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 0; }
.account-facts > div { padding: 12px 14px; border: 1px solid var(--color-border); border-radius: 10px; background: var(--color-surface-sunken); }
.account-facts dt { color: var(--color-fg-subtle); font-size: var(--pa-text-meta); }
.account-facts dd { overflow: hidden; margin: 4px 0 0; color: var(--color-fg); font-size: var(--text-sm); text-overflow: ellipsis; white-space: nowrap; }
.profile-footer { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding-top: 16px; border-top: 1px solid var(--color-border); }
.profile-footer > p { margin: 0; color: var(--color-fg-faint); font-size: var(--pa-text-meta); }
.profile-footer__action { display: flex; align-items: center; gap: 10px; }
.feedback { font-size: var(--pa-text-meta); }
.feedback.success { color: var(--color-success-fg); }
.feedback.error { color: var(--color-danger-fg); }
@media (max-width: 640px) {
  .avatar-section,
  .profile-footer { align-items: flex-start; flex-direction: column; }
  .account-facts { grid-template-columns: 1fr; }
  .profile-footer__action { width: 100%; justify-content: space-between; }
}
</style>
