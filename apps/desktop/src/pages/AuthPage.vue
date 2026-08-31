<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { message } from "ant-design-vue";
import {
  LockOutlined,
  MailOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from "@ant-design/icons-vue";

import { sendRegistrationVerificationCode } from "../services/auth";
import { ensureDesktopBackendReady } from "../services/backendStartup";
import { useAuthStore } from "../stores/auth";

type AuthMode = "login" | "register";
interface AuthForm {
  identifier: string;
  username: string;
  email: string;
  verification_code: string;
  password: string;
  confirm_password: string;
}

const props = defineProps<{ mode: AuthMode }>();
const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const error = ref("");
const backendStarting = ref(true);
const sendingCode = ref(false);
const codeCountdown = ref(0);
const form = ref<AuthForm>({
  identifier: "",
  username: "",
  email: "",
  verification_code: "",
  password: "",
  confirm_password: "",
});
let countdownTimer: ReturnType<typeof setInterval> | undefined;

const isRegister = computed(() => props.mode === "register");
const title = computed(() => (isRegister.value ? "创建账号" : "欢迎回来"));
const subtitle = computed(() =>
  isRegister.value
    ? "验证邮箱后，数据将按账号隔离保存"
    : "使用邮箱或用户名登录 PrivateAgent"
);

function stopCountdown(): void {
  if (countdownTimer) clearInterval(countdownTimer);
  countdownTimer = undefined;
  codeCountdown.value = 0;
}

function startCountdown(seconds: number): void {
  stopCountdown();
  codeCountdown.value = Math.max(1, seconds);
  countdownTimer = setInterval(() => {
    codeCountdown.value -= 1;
    if (codeCountdown.value <= 0) stopCountdown();
  }, 1_000);
}

async function handleSendCode(): Promise<void> {
  if (backendStarting.value) return;
  const email = form.value.email.trim();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    error.value = "请先输入有效邮箱地址";
    return;
  }
  error.value = "";
  sendingCode.value = true;
  try {
    await ensureDesktopBackendReady();
    const result = await sendRegistrationVerificationCode(email);
    startCountdown(result.retry_after_seconds);
    message.success("验证码已发送，5 分钟内有效");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "验证码发送失败";
  } finally {
    sendingCode.value = false;
  }
}

async function handleSubmit(): Promise<void> {
  if (backendStarting.value) return;
  error.value = "";
  if (isRegister.value && form.value.password !== form.value.confirm_password) {
    error.value = "两次输入的密码不一致";
    return;
  }
  try {
    if (isRegister.value) {
      await ensureDesktopBackendReady();
      await auth.register({
        username: form.value.username.trim(),
        email: form.value.email.trim(),
        verification_code: form.value.verification_code.trim().toUpperCase(),
        password: form.value.password,
      });
      message.success("注册成功");
    } else {
      await ensureDesktopBackendReady();
      await auth.login({
        identifier: form.value.identifier.trim(),
        password: form.value.password,
      });
      message.success("登录成功");
    }
    const redirect =
      typeof route.query.redirect === "string" && route.query.redirect.startsWith("/")
        ? route.query.redirect
        : "/app";
    await router.replace(redirect);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "操作失败，请稍后重试";
  }
}

watch(isRegister, (registering) => {
  error.value = "";
  if (!registering) stopCountdown();
});
onBeforeUnmount(stopCountdown);
onMounted(async () => {
  try {
    await ensureDesktopBackendReady();
  } catch (reason) {
    error.value =
      reason instanceof Error ? reason.message : "客户端连接准备失败，请重试或联系管理员";
  } finally {
    backendStarting.value = false;
  }
});
</script>

<template>
  <main class="auth-page">
    <section class="auth-visual" aria-label="PrivateAgent 介绍">
      <div class="auth-brand">
        <span class="auth-brand__icon"><RobotOutlined /></span>
        <span>PrivateAgent</span>
      </div>
      <div class="auth-visual__copy">
        <span class="auth-eyebrow">LOCAL-FIRST WORKSPACE</span>
        <h1>你的智能工作台，<br />数据始终由你掌控。</h1>
        <p>使用服务器账号登录；项目文件和任务在本机管理，可选择服务器模型或本机模型推理。</p>
      </div>
      <div class="auth-signal" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
    </section>

    <section class="auth-panel">
      <div class="auth-card">
        <div class="auth-card__head">
          <h2>{{ title }}</h2>
          <p>{{ subtitle }}</p>
        </div>

        <a-alert
          v-if="backendStarting"
          class="auth-alert"
          type="info"
          show-icon
          message="正在准备服务器连接与本机执行器…"
        />
        <a-alert
          v-else-if="error"
          class="auth-alert"
          type="error"
          show-icon
          :message="error"
        />

        <a-form layout="vertical" :model="form" @finish="handleSubmit">
          <a-form-item
            v-if="isRegister"
            label="用户名"
            name="username"
            :rules="[
              { required: true, message: '请输入用户名' },
              { min: 2, max: 50, message: '用户名长度需为 2–50 个字符' },
              { pattern: /^[^\s@]+$/, message: '用户名不能包含 @ 或空白' },
            ]"
          >
            <a-input
              v-model:value="form.username"
              size="large"
              autocomplete="username"
              placeholder="请输入唯一用户名"
            >
              <template #prefix><UserOutlined /></template>
            </a-input>
          </a-form-item>

          <a-form-item
            v-if="isRegister"
            label="邮箱"
            name="email"
            :rules="[
              { required: true, message: '请输入邮箱' },
              { type: 'email', message: '请输入有效邮箱地址' },
            ]"
          >
            <a-input
              v-model:value="form.email"
              size="large"
              autocomplete="email"
              placeholder="name@example.com"
            >
              <template #prefix><MailOutlined /></template>
            </a-input>
          </a-form-item>

          <a-form-item
            v-if="isRegister"
            label="邮箱验证码"
            name="verification_code"
            :rules="[
              { required: true, message: '请输入邮箱验证码' },
              { pattern: /^[A-Za-z0-9]{6}$/, message: '验证码为 6 位字母或数字' },
            ]"
          >
            <div class="auth-code-row">
              <a-input
                v-model:value="form.verification_code"
                class="auth-code-input"
                size="large"
                :maxlength="6"
                autocomplete="one-time-code"
                placeholder="6 位验证码"
              >
                <template #prefix><SafetyCertificateOutlined /></template>
              </a-input>
              <a-button
                class="auth-code-button"
                size="large"
                html-type="button"
                :loading="sendingCode"
                :disabled="backendStarting || codeCountdown > 0 || !form.email.trim()"
                @click="handleSendCode"
              >
                {{ codeCountdown > 0 ? `${codeCountdown}s 后重发` : "获取验证码" }}
              </a-button>
            </div>
            <span class="auth-field-hint">验证码由字母和数字组成，5 分钟内有效。</span>
          </a-form-item>

          <a-form-item
            v-if="!isRegister"
            label="邮箱或用户名"
            name="identifier"
            :rules="[{ required: true, message: '请输入邮箱或用户名' }]"
          >
            <a-input
              v-model:value="form.identifier"
              size="large"
              autocomplete="username"
              placeholder="name@example.com / username"
            >
              <template #prefix><UserOutlined /></template>
            </a-input>
          </a-form-item>

          <a-form-item
            label="密码"
            name="password"
            :rules="[
              { required: true, message: '请输入密码' },
              { min: 10, message: '密码至少 10 位' },
            ]"
          >
            <a-input-password
              v-model:value="form.password"
              size="large"
              :autocomplete="isRegister ? 'new-password' : 'current-password'"
              placeholder="至少 10 位"
            >
              <template #prefix><LockOutlined /></template>
            </a-input-password>
          </a-form-item>

          <a-form-item
            v-if="isRegister"
            label="确认密码"
            name="confirm_password"
            :rules="[{ required: true, message: '请再次输入密码' }]"
          >
            <a-input-password
              v-model:value="form.confirm_password"
              size="large"
              autocomplete="new-password"
              placeholder="再次输入密码"
            >
              <template #prefix><LockOutlined /></template>
            </a-input-password>
          </a-form-item>

          <a-button
            class="auth-submit"
            type="primary"
            html-type="submit"
            size="large"
            :loading="auth.loading"
            :disabled="backendStarting || sendingCode"
          >
            {{ isRegister ? "注册并进入" : "登录" }}
          </a-button>
        </a-form>

        <p class="auth-switch">
          {{ isRegister ? "已有账号？" : "还没有账号？" }}
          <RouterLink :to="isRegister ? '/login' : '/register'">
            {{ isRegister ? "去登录" : "立即注册" }}
          </RouterLink>
        </p>
        <p v-if="isRegister" class="auth-first-admin">
          安全部署提示：首个完成注册的账号会成为管理员。
        </p>
      </div>
    </section>
  </main>
</template>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(360px, 1.05fr) minmax(420px, 0.95fr);
  background: #f5f7fb;
  color: #172033;
}

.auth-visual {
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: clamp(34px, 5vw, 72px);
  color: #f8fbff;
  background:
    radial-gradient(circle at 74% 28%, rgba(93, 205, 255, 0.28), transparent 28%),
    radial-gradient(circle at 16% 82%, rgba(111, 83, 255, 0.32), transparent 32%),
    linear-gradient(145deg, #07152d 0%, #102c58 52%, #173f72 100%);
}

.auth-visual::after {
  position: absolute;
  inset: 0;
  content: "";
  opacity: 0.16;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.18) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.18) 1px, transparent 1px);
  background-size: 54px 54px;
  mask-image: linear-gradient(to bottom, transparent, #000 28%, #000 76%, transparent);
}

.auth-brand,
.auth-visual__copy,
.auth-signal {
  position: relative;
  z-index: 1;
}

.auth-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 18px;
  font-weight: 650;
  letter-spacing: 0.02em;
}

.auth-brand__icon {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(255, 255, 255, 0.32);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.1);
  font-size: 22px;
}

.auth-eyebrow {
  display: inline-block;
  margin-bottom: 20px;
  color: #8edaff;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.18em;
}

.auth-visual h1 {
  max-width: 680px;
  margin: 0 0 22px;
  font-size: clamp(38px, 4.3vw, 68px);
  line-height: 1.08;
  letter-spacing: -0.045em;
}

.auth-visual p {
  max-width: 560px;
  margin: 0;
  color: rgba(235, 244, 255, 0.74);
  font-size: 16px;
  line-height: 1.8;
}

.auth-signal {
  display: flex;
  gap: 8px;
}

.auth-signal span {
  display: block;
  width: 26px;
  height: 4px;
  border-radius: 99px;
  background: rgba(255, 255, 255, 0.28);
}

.auth-signal span:first-child {
  width: 64px;
  background: #6fd3ff;
}

.auth-panel {
  max-height: 100vh;
  overflow-y: auto;
  display: grid;
  place-items: center;
  padding: 36px;
}

.auth-card {
  width: min(440px, 100%);
  padding: 42px;
  border: 1px solid #e4e9f1;
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 24px 70px rgba(32, 49, 78, 0.12);
}

.auth-card__head {
  margin-bottom: 28px;
}

.auth-card__head h2 {
  margin: 0 0 8px;
  color: #172033;
  font-size: 30px;
  line-height: 1.2;
}

.auth-card__head p,
.auth-switch,
.auth-first-admin {
  color: #6f7b91;
}

.auth-card__head p {
  margin: 0;
  line-height: 1.6;
}

.auth-alert {
  margin-bottom: 20px;
}

.auth-code-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 128px;
  gap: 10px;
}

.auth-code-input :deep(input) {
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.auth-code-button {
  padding-inline: 12px;
}

.auth-field-hint {
  display: block;
  margin-top: 6px;
  color: #8a95a8;
  font-size: 12px;
  line-height: 1.5;
}

.auth-submit {
  width: 100%;
  margin-top: 6px;
}

.auth-switch {
  margin: 22px 0 0;
  text-align: center;
}

.auth-switch a {
  margin-left: 6px;
  font-weight: 600;
}

.auth-first-admin {
  margin: 16px 0 0;
  font-size: 12px;
  line-height: 1.6;
  text-align: center;
}

@media (max-width: 860px) {
  .auth-page {
    grid-template-columns: 1fr;
  }

  .auth-visual {
    min-height: 260px;
  }

  .auth-visual h1 {
    font-size: 38px;
  }

  .auth-signal {
    display: none;
  }

  .auth-panel {
    max-height: none;
  }
}

@media (max-width: 540px) {
  .auth-panel {
    padding: 18px;
  }

  .auth-card {
    padding: 28px 22px;
    border-radius: 16px;
  }

  .auth-code-row {
    grid-template-columns: 1fr;
  }
}
</style>
