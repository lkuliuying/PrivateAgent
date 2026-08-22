<script setup lang="ts">
/**
 * AgentComposer · v0.8.0 W6-R2（v0.8.0 W6-R3 重排）
 *
 * 底部主控制区（计划 §4.5/§6.8）：
 * - 原「知识检索」位 = 三档命令权限下拉（§6.7 权限表真实语义）；
 * - 移除「知识检索」「生成记忆」手动按钮（能力自动化，见 model/autoContext.ts）；
 * - 底部操作行：模型/Provider 配置入口（当前模型 + 本地/远程）+ 上下文用量
 *   模块 + 执行/停止；
 * - 权限/模型选择绑定真实契约：不支持的能力禁用并说明，不伪造请求。
 */
import { computed, ref } from "vue";
import { PhGearSix, PhWarningCircle } from "@phosphor-icons/vue";
import TaskComposerV2 from "./TaskComposerV2.vue";
import ContextUsageMeter from "./ContextUsageMeter.vue";
import type { ContextUsageFacts } from "./model/contextUsage";
import {
  agentPermissionOptions,
  currentAgentCapabilityFacts,
} from "./model/agentCapabilities";

const draft = defineModel<string>({ default: "" });

const props = withDefaults(
  defineProps<{
    streaming: boolean;
    pendingTool: boolean;
    stopRequested?: boolean;
    stopped?: boolean;
    /** 当前模型（公开配置事实） */
    modelName?: string | null;
    /** Provider 运行位置：本地/远程/未配置 */
    providerLabel?: string;
    /** Provider/模型异常态（配置未完成、模型不可用、远程关闭等） */
    providerWarning?: string | null;
    /** 上下文用量事实（公开 usage，见 model/contextUsage.ts） */
    usageFacts?: ContextUsageFacts | null;
    /** /capabilities 公开字段（原样传入，不猜测） */
    capabilities?: Record<string, unknown> | null;
  }>(),
  {
    stopRequested: false,
    stopped: false,
    modelName: null,
    providerLabel: "本地",
    providerWarning: null,
    usageFacts: null,
    capabilities: null,
  }
);

const emit = defineEmits<{
  send: [text: string];
  stop: [];
  "configure-model": [];
}>();

const facts = computed(() => currentAgentCapabilityFacts(props.capabilities));
const permissions = computed(() => agentPermissionOptions(facts.value));
/** 对话路径真实语义 = 审批流（总是询问）；其余档位按契约禁用 */
const permissionMode = ref<"confirm" | "workspace" | "full_access">("confirm");
</script>

<template>
  <div class="agent-composer" data-testid="agent-composer">
    <TaskComposerV2
      v-model="draft"
      :streaming="streaming"
      :pending-tool="pendingTool"
      :provider-label="providerLabel"
      :stop-requested="stopRequested"
      :stopped="stopped"
      @send="(text) => emit('send', text)"
      @stop="emit('stop')"
    >
      <!-- 原知识检索位：命令权限下拉（键盘可达，三档真实语义） -->
      <template #toolbar-left>
        <label class="permission-select">
          <span class="visually-hidden">命令权限</span>
          <select
            v-model="permissionMode"
            aria-label="命令权限"
            data-testid="composer-permission-select"
          >
            <option
              v-for="option in permissions"
              :key="option.id"
              :value="option.id"
              :disabled="!option.available"
              :title="option.hint"
            >
              {{ option.label }}{{ option.available ? "" : "（不可用）" }}
            </option>
          </select>
        </label>
      </template>

      <!-- 底部模型/Provider 配置入口 + 上下文用量 -->
      <template #toolbar-right>
        <button
          class="model-entry"
          type="button"
          data-testid="composer-model-entry"
          :title="providerWarning ?? '模型/Provider 配置'"
          :class="{ 'has-warning': Boolean(providerWarning) }"
          @click="emit('configure-model')"
        >
          <PhWarningCircle v-if="providerWarning" :size="13" class="model-warning" aria-hidden="true" />
          <span class="model-name">{{ modelName || "系统默认模型" }}</span>
          <span class="model-provider">· {{ providerLabel }}</span>
          <PhGearSix :size="12" aria-hidden="true" />
        </button>
        <ContextUsageMeter
          v-if="usageFacts"
          :facts="usageFacts"
        />
      </template>
    </TaskComposerV2>
  </div>
</template>

<style scoped>
.agent-composer {
  flex-shrink: 0;
}
.permission-select select {
  height: 34px;
  max-width: 180px;
  padding: 0 var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.permission-select select:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.model-entry {
  display: inline-flex;
  max-width: 320px;
  height: 34px;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-meta);
  cursor: pointer;
}
.model-entry:hover {
  border-color: color-mix(in srgb, var(--color-accent) 35%, var(--color-border));
  color: var(--color-fg);
}
.model-entry:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.model-entry.has-warning {
  border-color: color-mix(in srgb, var(--color-warning) 45%, var(--color-border));
}
.model-warning {
  color: var(--color-warning-fg);
}
.model-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.model-provider {
  flex-shrink: 0;
  color: var(--color-fg-subtle);
}
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>
