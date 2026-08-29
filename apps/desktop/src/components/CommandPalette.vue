<script setup lang="ts">
/**
 * 命令面板（第七阶段 M2）。Ctrl/Cmd+K 打开（App.vue 注册热键）。
 * 命令复用既有 API + 现有审批/风险边界（不绕过）。
 * 动作：新建会话/收件箱/提醒、导入文档、生成今日简报、运行健康检查、打开设置/诊断、全局搜索。
 */
import { computed, nextTick, onMounted, ref, watch } from "vue";
import type { Component } from "vue";
import {
  PhChatCircle,
  PhTray,
  PhBell,
  PhUploadSimple,
  PhSparkle,
  PhMagnifyingGlass,
} from "@phosphor-icons/vue";
import { createInbox, createReminder, createTodayBriefing, createSession } from "../api";
import { useNotifications } from "../stores/notifications";
import type { View } from "../types";
import { VIEW_REGISTRY } from "../models/viewRegistry";

const props = withDefaults(defineProps<{ codingOnly?: boolean }>(), {
  codingOnly: false,
});

const emit = defineEmits<{
  navigate: [view: View];
  "open-search": [];
  close: [];
}>();
const notify = useNotifications();

const query = ref("");
const inputEl = ref<HTMLInputElement | null>(null);
const selected = ref(0);

interface Command {
  id: string;
  label: string;
  hint?: string;
  icon: Component;
  keywords: string;
  run: () => void | Promise<void>;
}

/** 视图注册表驱动的一级导航命令（D2：统一命令面板入口） */
const CODING_VIEW_KEYS = new Set<View>([
  "coding",
  "projects",
  "tasks",
  "extensions",
  "settings",
  "diagnostics",
]);

const viewCommands = computed<Command[]>(() =>
  Object.values(VIEW_REGISTRY)
    .filter((meta) => !props.codingOnly || CODING_VIEW_KEYS.has(meta.key))
    .map((meta) => ({
      id: `view-${meta.key}`,
      label: `打开${meta.label}`,
      hint: meta.group === "system" ? "系统" : undefined,
      icon: meta.icon,
      keywords: meta.keywords.join(" "),
      run: () => emit("navigate", meta.key),
    }))
);

const commands = computed<Command[]>(() => {
  const items: Command[] = [
  ...viewCommands.value,
  {
    id: "search",
    label: "全局搜索",
    hint: "搜索会话/文档/任务/记忆…",
    icon: PhMagnifyingGlass,
    keywords: "search 搜索",
    run: () => emit("open-search"),
  },
  {
    id: "new-session",
    label: "新建会话",
    icon: PhChatCircle,
    keywords: "chat 对话 session",
    run: async () => {
      try {
        await createSession();
        emit("navigate", "chat");
        notify.success("已新建会话");
      } catch (e) {
        notify.error("新建会话失败", String(e));
      }
    },
  },
  {
    id: "new-inbox",
    label: "新建收件箱项",
    icon: PhTray,
    keywords: "inbox 收件箱 todo",
    run: async () => {
      const title = await notify.prompt({ title: "新建收件箱项", placeholder: "标题" });
      if (!title) return;
      try {
        await createInbox({ title, item_type: "todo" });
        notify.success("已创建收件箱项", title);
      } catch (e) {
        notify.error("创建失败", String(e));
      }
    },
  },
  {
    id: "new-reminder",
    label: "新建提醒",
    icon: PhBell,
    keywords: "reminder 提醒",
    run: async () => {
      const title = await notify.prompt({ title: "新建提醒", placeholder: "标题" });
      if (!title) return;
      const due = new Date(Date.now() + 3600_000).toISOString();
      try {
        await createReminder({ title, due_at: due });
        notify.success("已创建提醒", `${title}（1 小时后）`);
      } catch (e) {
        notify.error("创建失败", String(e));
      }
    },
  },
  {
    id: "import-doc",
    label: "导入文档到知识库",
    icon: PhUploadSimple,
    keywords: "import 文档 knowledge kb",
    run: () => emit("navigate", "kb"),
  },
  {
    id: "briefing",
    label: "生成今日简报",
    icon: PhSparkle,
    keywords: "briefing 简报 today",
    run: async () => {
      try {
        await createTodayBriefing();
        emit("navigate", "today");
        notify.success("今日简报已生成");
      } catch (e) {
        notify.error("生成简报失败", String(e));
      }
    },
  },
  ];
  if (!props.codingOnly) return items;
  return items.filter((item) => item.id === "search" || item.id.startsWith("view-"));
});

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return commands.value;
  return commands.value.filter(
    (c) =>
      c.label.toLowerCase().includes(q) || c.keywords.toLowerCase().includes(q)
  );
});

watch(filtered, () => {
  selected.value = 0;
});

async function open() {
  query.value = "";
  selected.value = 0;
  await nextTick();
  inputEl.value?.focus();
}

function select(idx: number) {
  const cmd = filtered.value[idx];
  if (!cmd) return;
  emit("close");
  void cmd.run();
}

function onKey(e: KeyboardEvent) {
  if (e.key === "Escape") {
    emit("close");
  } else if (e.key === "ArrowDown") {
    e.preventDefault();
    selected.value = Math.min(selected.value + 1, filtered.value.length - 1);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    selected.value = Math.max(selected.value - 1, 0);
  } else if (e.key === "Enter") {
    e.preventDefault();
    select(selected.value);
  }
}

defineExpose({ open });

onMounted(open);
</script>

<template>
  <Teleport to="body">
    <Transition name="cp">
      <div class="cp-scrim" @click.self="emit('close')">
        <div class="cp-card" role="dialog" aria-modal="true" aria-label="命令面板">
          <div class="cp-input-wrap">
            <PhMagnifyingGlass :size="16" class="cp-input-icon" />
            <input
              ref="inputEl"
              v-model="query"
              class="cp-input"
              placeholder="输入命令或搜索…（↑↓ 选择，回车执行，Esc 关闭）"
              @keydown="onKey"
            />
          </div>
          <ul class="cp-list">
            <li
              v-for="(c, i) in filtered"
              :key="c.id"
              class="cp-item"
              :class="{ active: i === selected }"
              @mouseenter="selected = i"
              @click="select(i)"
            >
              <component :is="c.icon" :size="16" class="cp-item-icon" />
              <span class="cp-item-label">{{ c.label }}</span>
              <span v-if="c.hint" class="cp-item-hint">{{ c.hint }}</span>
            </li>
            <li v-if="filtered.length === 0" class="cp-empty">无匹配命令</li>
          </ul>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.cp-scrim {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  background: var(--color-scrim);
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding-top: 12vh;
}
.cp-card {
  width: 560px;
  max-width: calc(100vw - var(--space-8));
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}
.cp-input-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}
.cp-input-icon {
  color: var(--color-fg-faint);
  flex-shrink: 0;
}
.cp-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: var(--text-base);
  color: var(--color-fg);
}
.cp-list {
  list-style: none;
  margin: 0;
  padding: var(--space-2);
  max-height: 50vh;
  overflow-y: auto;
}
.cp-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius);
  cursor: pointer;
  color: var(--color-fg);
}
.cp-item.active {
  background: var(--color-accent-soft);
}
.cp-item-icon {
  color: var(--color-fg-subtle);
  flex-shrink: 0;
}
.cp-item.active .cp-item-icon {
  color: var(--color-accent);
}
.cp-item-label {
  font-size: var(--text-base);
}
.cp-item-hint {
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
}
.cp-empty {
  padding: var(--space-4);
  text-align: center;
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
}
.cp-enter-active,
.cp-leave-active {
  transition: opacity var(--duration) var(--ease);
}
.cp-enter-active .cp-card,
.cp-leave-active .cp-card {
  transition: transform var(--duration) var(--ease-out);
}
.cp-enter-from,
.cp-leave-to {
  opacity: 0;
}
.cp-enter-from .cp-card,
.cp-leave-to .cp-card {
  transform: translateY(-12px);
}
</style>
