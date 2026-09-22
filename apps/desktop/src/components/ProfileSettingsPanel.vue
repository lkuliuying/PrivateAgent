<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";
import { PhCamera, PhTrash } from "@phosphor-icons/vue";
import { useLocalProfile } from "../services/localProfile";
import defaultAvatar from "../assets/companion/default-avatar.png";
import profileCover from "../assets/companion/profile-cover.png";

const { profile, readError, save } = useLocalProfile();

const fileInput = ref<HTMLInputElement | null>(null);
const avatarDataUrl = ref(profile.value.avatarDataUrl);
const nickname = ref(profile.value.nickname);
const bio = ref(profile.value.bio);
const feedback = ref("");
const feedbackTone = ref<"success" | "error">("success");

const username = "本机用户";
let avatarReader: FileReader | null = null;
function cancelAvatarRead(): void {
  const reader = avatarReader;
  avatarReader = null;
  if (reader?.readyState === FileReader.LOADING) reader.abort();
}
onBeforeUnmount(cancelAvatarRead);

function chooseAvatar(): void {
  fileInput.value?.click();
}

function onAvatarSelected(event: Event): void {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
    feedbackTone.value = "error";
    feedback.value = "请选择 PNG、JPG 或 WebP 图片。";
    return;
  }
  if (file.size > 1024 * 1024) {
    feedbackTone.value = "error";
    feedback.value = "头像图片不能超过 1 MB。";
    return;
  }
  cancelAvatarRead();
  const reader = new FileReader();
  avatarReader = reader;
  reader.onload = () => {
    if (avatarReader !== reader) return;
    avatarReader = null;
    avatarDataUrl.value = typeof reader.result === "string" ? reader.result : "";
    feedback.value = "";
  };
  reader.onerror = () => {
    if (avatarReader !== reader) return;
    avatarReader = null;
    feedbackTone.value = "error";
    feedback.value = "头像读取失败，请重新选择。";
  };
  reader.readAsDataURL(file);
}

function removeAvatar(): void {
  cancelAvatarRead();
  avatarDataUrl.value = "";
  feedback.value = "";
}

function saveProfile(): void {
  try {
    save({
      avatarDataUrl: avatarDataUrl.value,
      nickname: nickname.value.trim(),
      bio: bio.value.trim(),
    });
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
    <header class="profile-header">
      <img class="profile-cover" :src="profileCover" alt="" />
      <div class="profile-avatar">
        <img :src="avatarDataUrl || defaultAvatar" alt="当前头像" />
      </div>
      <h1 class="profile-name">{{ nickname.trim() || username }}</h1>
      <p class="profile-mode">API Key 模式 · 本机工作区</p>
      <div class="profile-avatar-actions">
        <button
          type="button"
          class="pa-btn pa-btn--ghost profile-avatar-button"
          data-testid="profile-avatar-upload"
          aria-describedby="profile-avatar-hint"
          @click="chooseAvatar"
        >
          <PhCamera :size="16" aria-hidden="true" />
          上传头像
        </button>
        <button v-if="avatarDataUrl" type="button" class="pa-btn pa-btn--subtle profile-avatar-button" @click="removeAvatar">
          <PhTrash :size="15" aria-hidden="true" />
          移除
        </button>
      </div>
      <p id="profile-avatar-hint" class="profile-avatar-hint">支持 PNG、JPG、WebP，图片不超过 1 MB。</p>
      <input
        ref="fileInput"
        class="profile-file-input"
        type="file"
        accept="image/png,image/jpeg,image/webp"
        data-testid="profile-avatar-input"
        tabindex="-1"
        aria-label="选择头像图片"
        @change="onAvatarSelected"
      />
    </header>

    <section class="profile-details" aria-labelledby="profile-details-title">
      <h2 id="profile-details-title">基本信息</h2>
      <p v-if="readError" class="profile-feedback profile-feedback--error" role="alert">{{ readError }}</p>
      <div class="profile-fields">
        <label class="profile-field">
          <span>称呼</span>
          <input v-model="nickname" class="pa-input" maxlength="50" autocomplete="nickname" />
        </label>
        <label class="profile-field">
          <span id="profile-bio-label">个人简介</span>
          <textarea v-model="bio" class="pa-input" maxlength="240" rows="3" aria-labelledby="profile-bio-label" aria-describedby="profile-bio-count" placeholder="简单介绍一下自己（可选）" />
          <small id="profile-bio-count" class="profile-counter">{{ bio.length }} / 240</small>
        </label>
      </div>

      <footer class="profile-footer">
        <div class="profile-save-status">
          <p>个人资料仅保存在当前设备，暂不跨设备同步。</p>
          <span v-if="feedback" :class="['profile-feedback', `profile-feedback--${feedbackTone}`]" role="status">{{ feedback }}</span>
        </div>
        <button type="button" class="pa-btn pa-btn--primary profile-save" data-testid="profile-save" @click="saveProfile">保存资料</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.profile-panel { width: 100%; min-width: 0; margin: 0 auto; }
.profile-header { position: relative; display: grid; grid-template-columns: 100px minmax(0, 1fr) auto; align-items: center; column-gap: var(--space-5); padding: 0 var(--space-6) var(--space-5); overflow: hidden; border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); }
.profile-cover { grid-column: 1 / -1; width: calc(100% + 48px); height: 160px; margin: 0 -24px; object-fit: cover; object-position: center 85%; }
.profile-avatar { position: relative; grid-column: 1; grid-row: 2 / 5; width: 100px; height: 100px; margin-top: -36px; overflow: hidden; border: 4px solid var(--color-surface); border-radius: var(--radius-full); background: var(--color-surface); }
.profile-avatar img { width: 100%; height: 100%; object-fit: cover; }
.profile-name { grid-column: 2; margin: var(--space-4) 0 var(--space-1); font-size: var(--pa-text-page-title); font-weight: var(--font-semibold); overflow-wrap: anywhere; }
.profile-mode { grid-column: 2; margin: 0; color: var(--color-fg-subtle); font-size: var(--pa-text-compact); }
.profile-avatar-actions { grid-column: 3; grid-row: 2 / 4; display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); padding-top: var(--space-3); }
.profile-avatar-button { height: 34px; }
.profile-avatar-hint { grid-column: 2 / -1; margin: var(--space-2) 0 0; color: var(--color-fg-subtle); font-size: var(--pa-text-meta); }
.profile-file-input { display: none; }
.profile-details { margin-top: var(--space-5); padding: var(--space-6); border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); }
.profile-details h2 { margin: 0 0 var(--space-5); font-size: var(--pa-text-section); font-weight: var(--font-semibold); }
.profile-fields { display: grid; gap: var(--space-5); }
.profile-field { display: grid; grid-template-columns: 130px minmax(0, 1fr); align-items: start; gap: var(--space-3); }
.profile-field > span { padding-top: var(--space-2); color: var(--color-fg-muted); font-size: var(--pa-text-body); }
.profile-field .pa-input { width: 100%; min-width: 0; }
.profile-field textarea { min-height: 114px; resize: vertical; }
.profile-counter { grid-column: 2; text-align: right; color: var(--color-fg-subtle); font-size: var(--pa-text-meta); }
.profile-footer { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); margin-top: var(--space-5); padding-top: var(--space-5); border-top: 1px solid var(--color-border); }
.profile-save-status { min-width: 0; }
.profile-save-status p { margin: 0; color: var(--color-fg-subtle); font-size: var(--pa-text-meta); }
.profile-feedback { display: block; margin-top: var(--space-2); font-size: var(--pa-text-compact); }
.profile-feedback--success { color: var(--color-success-fg); }
.profile-feedback--error { color: var(--color-danger-fg); }
.profile-save { flex-shrink: 0; padding-inline: var(--space-5); }
@media (max-width: 760px) {
  .profile-header { grid-template-columns: 76px minmax(0, 1fr); gap: var(--space-2) var(--space-4); padding-bottom: var(--space-4); }
  .profile-cover { height: 128px; }
  .profile-avatar { width: 76px; height: 76px; }
  .profile-name { margin-top: var(--space-2); }
  .profile-avatar-actions { grid-column: 2; grid-row: auto; padding-top: 0; }
  .profile-avatar-hint { grid-column: 1 / -1; }
  .profile-details { padding: var(--space-4); }
  .profile-field { grid-template-columns: minmax(0, 1fr); gap: var(--space-2); }
  .profile-field > span { padding: 0; }
  .profile-counter { grid-column: 1; }
  .profile-footer { align-items: flex-start; flex-direction: column; }
  .profile-save { align-self: flex-end; }
}
</style>
