<script setup lang="ts">
/**
 * NavRail v2 · 视图注册表驱动分组导航（0.4.0 D2）
 * 工作入口 5 组（日常/执行/工作/知识/连接）+ 底部系统组；
 * 最近任务、折叠、命令入口保留。
 */
import { ref } from "vue";
import {
  PhArrowRight,
  PhCommand,
  PhFolderSimple,
  PhPlus,
  PhSidebarSimple,
  PhSparkle,
  PhUserCircle,
} from "@phosphor-icons/vue";
import type { Session, View } from "../types";
import {
  NAV_GROUPS,
  SYSTEM_GROUP,
  VIEW_GROUP_META,
  groupViews,
  type ViewGroup,
} from "../models/viewRegistry";
import PaTooltip from "../design/PaTooltip.vue";

withDefaults(
  defineProps<{
    active: View;
    sessions?: Session[];
    currentId?: number | null;
    collapsed?: boolean;
  }>(),
  { sessions: () => [], currentId: null, collapsed: false }
);

const emit = defineEmits<{
  navigate: [view: View];
  "open-command": [];
  "new-session": [];
  "select-session": [id: number];
  "toggle-collapse": [];
}>();

const groupOpen = ref<Record<ViewGroup, boolean>>({
  daily: true,
  agent: true,
  work: true,
  knowledge: true,
  connect: true,
  system: true,
  // coding 组不进入旧 NavRail 渲染（NAV_GROUPS 不含），仅为满足 Record 类型
  coding: true,
});

function toggleGroup(group: ViewGroup) {
  groupOpen.value = { ...groupOpen.value, [group]: !groupOpen.value[group] };
}

function groupLabel(group: ViewGroup): string {
  return VIEW_GROUP_META[group].label;
}

function formatRelative(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const diff = Date.now() - date.getTime();
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟`;
  if (date.toDateString() === new Date().toDateString()) {
    return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  }
  return `${date.getMonth() + 1}/${date.getDate()}`;
}
</script>

<template>
  <nav class="navrail-v2" :class="{ 'is-collapsed': collapsed }" aria-label="主导航">
    <div class="rail-brand" title="PrivateAgent 本地智能体">
      <div class="brand-mark"><PhSparkle :size="22" weight="fill" /></div>
      <div class="brand-copy">
        <strong>PrivateAgent</strong>
        <span>LOCAL AGENT</span>
      </div>
    </div>

    <PaTooltip text="新建任务 (Ctrl/Cmd+N)" placement="bottom">
      <button class="rail-new" title="新建任务" @click="emit('new-session')">
        <PhPlus :size="18" weight="bold" />
        <span>新建任务</span>
      </button>
    </PaTooltip>

    <div class="rail-scroll">
      <section
        v-for="group in NAV_GROUPS"
        :key="group"
        class="rail-group"
        :class="{ 'is-open': groupOpen[group] }"
      >
        <button
          class="rail-group-heading"
          :aria-expanded="groupOpen[group]"
          @click="toggleGroup(group)"
        >
          <span class="group-caret" aria-hidden="true" />
          <span>{{ groupLabel(group) }}</span>
        </button>
        <ul v-if="groupOpen[group]" class="rail-items" :aria-label="groupLabel(group)">
          <li v-for="item in groupViews(group)" :key="item.key">
            <button
              class="rail-item"
              :data-testid="`nav-${item.key}`"
              :class="{ active: active === item.key }"
              :aria-current="active === item.key ? 'page' : undefined"
              :title="item.label"
              @click="emit('navigate', item.key)"
            >
              <component :is="item.icon" class="rail-icon" :size="19" />
              <span class="rail-label">{{ item.label }}</span>
            </button>
          </li>
        </ul>

        <!-- W6-R3：最近任务紧随「Agent 执行」入口（同一数据源/稳定 id/排序/状态，
             旧独立区已删除；与 Agent 页 ConversationList 职责不同） -->
        <div
          v-if="group === 'agent' && groupOpen[group]"
          class="recent-section"
          data-testid="rail-recent-tasks"
          aria-label="最近任务"
        >
          <div class="recent-heading">
            <span>最近任务</span>
            <span>{{ sessions.length }}</span>
          </div>
          <div v-if="sessions.length === 0" class="recent-empty">新建任务后会显示在这里</div>
          <button
            v-for="session in sessions.slice(0, 6)"
            :key="session.id"
            class="recent-task"
            :class="{ active: active === 'chat' && session.id === currentId }"
            :title="session.title"
            :data-testid="`rail-recent-task-${session.id}`"
            @click="emit('select-session', session.id)"
          >
            <span class="recent-icon"><PhFolderSimple :size="15" /></span>
            <span class="recent-copy">
              <strong>{{ session.title }}</strong>
              <small>{{ formatRelative(session.updated_at) }}</small>
            </span>
            <span
              class="recent-status"
              :class="{ running: active === 'chat' && session.id === currentId }"
              :aria-label="active === 'chat' && session.id === currentId ? '当前任务' : '已保存'"
            />
          </button>
          <button
            v-if="sessions.length > 0"
            class="recent-all"
            data-testid="rail-recent-all"
            @click="emit('navigate', 'chat')"
          >
            查看全部 <PhArrowRight :size="12" />
          </button>
        </div>
      </section>

      <section class="rail-group system-group" aria-label="系统">
        <span class="system-heading">系统</span>
        <ul class="rail-items">
          <li v-for="item in groupViews(SYSTEM_GROUP)" :key="item.key">
            <button
              class="rail-item"
              :data-testid="`nav-${item.key}`"
              :class="{ active: active === item.key }"
              :aria-current="active === item.key ? 'page' : undefined"
              :title="item.label"
              @click="emit('navigate', item.key)"
            >
              <component :is="item.icon" class="rail-icon" :size="19" />
              <span class="rail-label">{{ item.label }}</span>
            </button>
          </li>
        </ul>
      </section>
    </div>

    <div class="rail-footer">
      <button class="profile-entry" title="本地用户设置" @click="emit('navigate', 'settings')">
        <PhUserCircle :size="30" weight="fill" />
        <span>
          <strong>本地用户</strong>
          <small>数据仅存储在此设备</small>
        </span>
      </button>
      <div class="footer-actions">
        <button class="command-shortcut" title="快捷命令 Ctrl/Cmd+K" aria-label="快捷命令" @click="emit('open-command')">
          <PhCommand :size="16" />
          <span>Ctrl K</span>
        </button>
        <button
          :title="collapsed ? '展开侧栏' : '折叠侧栏'"
          :aria-label="collapsed ? '展开侧栏' : '折叠侧栏'"
          @click="emit('toggle-collapse')"
        >
          <PhSidebarSimple :size="17" />
        </button>
      </div>
    </div>
  </nav>
</template>

<style scoped>
.navrail-v2 {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-3) var(--space-3);
  overflow: hidden;
  border-right: 1px solid var(--color-rail-border);
  background: var(--color-rail-bg);
  color: var(--color-rail-fg);
}
.rail-brand { display: flex; min-width: 0; flex-shrink: 0; align-items: center; gap: var(--space-3); padding: 0 var(--space-1); }
.brand-mark { display: grid; width: 36px; height: 36px; flex: 0 0 36px; place-items: center; border: 1px solid var(--pa-rail-brand-border); border-radius: 11px; background: var(--pa-rail-brand-bg); color: var(--color-rail-accent); }
.brand-copy { display: flex; min-width: 0; flex-direction: column; }
.brand-copy strong { overflow: hidden; color: var(--color-rail-fg-strong); font-size: var(--pa-text-section); letter-spacing: 0.01em; text-overflow: ellipsis; white-space: nowrap; }
.brand-copy span { margin-top: 1px; color: var(--color-rail-fg-muted); font-size: var(--pa-t-11); font-weight: var(--font-semibold); letter-spacing: 0.13em; }
.rail-new {
  display: flex;
  width: 100%;
  height: 40px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  border: 1px solid var(--pa-btn-primary-bg);
  border-radius: var(--radius-md);
  background: var(--pa-btn-primary-bg);
  color: var(--color-accent-fg);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: background var(--pa-motion-fast) var(--ease), transform var(--pa-motion-instant) var(--ease);
}
.rail-new:hover { background: var(--pa-btn-primary-bg-hover); transform: translateY(-1px); }
.rail-new:active { transform: translateY(0); }
.rail-new:focus-visible { outline: none; box-shadow: 0 0 0 2px var(--color-rail-bg), 0 0 0 4px var(--color-rail-accent); }
.rail-scroll { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; }
.rail-group { margin-bottom: var(--space-1); }
.rail-group-heading {
  display: flex;
  width: 100%;
  height: 26px;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-2);
  border: none;
  background: transparent;
  color: var(--color-rail-fg-muted);
  font-size: var(--pa-t-11);
  font-weight: var(--font-semibold);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  cursor: pointer;
}
.rail-group-heading:hover { color: var(--color-rail-fg); }
.rail-group-heading:focus-visible { outline: none; box-shadow: inset 0 0 0 2px var(--color-rail-accent); }
.group-caret {
  width: 6px;
  height: 6px;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  transform: rotate(-45deg);
  transition: transform var(--pa-motion-fast) var(--ease);
}
.is-open .group-caret { transform: rotate(45deg); }
.rail-items { display: flex; margin: 0; padding: 0; flex-direction: column; gap: 2px; list-style: none; }
.rail-item {
  display: flex;
  position: relative;
  width: 100%;
  height: var(--pa-nav-item-height);
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--space-3);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-rail-fg-muted);
  cursor: pointer;
  transition: background var(--pa-motion-fast) var(--ease), color var(--pa-motion-fast) var(--ease);
}
.rail-item:hover { background: var(--color-rail-surface); color: var(--color-rail-fg-strong); }
.rail-item.active { background: var(--color-rail-active); color: var(--color-rail-fg-strong); }
.rail-item.active::before { content: ""; position: absolute; top: 10px; bottom: 10px; left: 0; width: var(--pa-nav-indicator-w); border-radius: var(--radius-full); background: var(--color-rail-accent); }
.rail-item:focus-visible,
.recent-task:focus-visible,
.profile-entry:focus-visible,
.footer-actions button:focus-visible { outline: none; box-shadow: inset 0 0 0 2px var(--color-rail-accent); }
.rail-icon { flex-shrink: 0; }
.rail-label { overflow: hidden; font-size: var(--pa-text-compact); text-overflow: ellipsis; white-space: nowrap; }
.system-group { margin-top: var(--space-3); padding-top: var(--space-2); border-top: 1px solid var(--color-rail-border); }
.system-heading { display: block; padding: 0 var(--space-2) var(--space-1); color: var(--color-rail-fg-muted); font-size: var(--pa-t-11); font-weight: var(--font-semibold); letter-spacing: 0.12em; text-transform: uppercase; }
.recent-section { margin: var(--space-1) 0 var(--space-1); padding: var(--space-1) 0 0 var(--space-2); border-left: 1px solid var(--color-rail-border); }
.recent-heading { display: flex; align-items: center; justify-content: space-between; padding: 0 var(--space-2) var(--space-2); color: var(--color-rail-fg-muted); font-size: var(--pa-t-11); font-weight: var(--font-semibold); letter-spacing: 0.06em; }
.recent-empty { padding: var(--space-2); color: var(--color-rail-fg-muted); font-size: var(--pa-t-11); line-height: 1.5; }
.recent-task { display: flex; width: 100%; min-width: 0; align-items: center; gap: var(--space-2); padding: var(--space-2); border: 1px solid transparent; border-radius: var(--radius-md); background: transparent; color: var(--color-rail-fg-muted); text-align: left; cursor: pointer; }
.recent-task:hover { background: var(--color-rail-surface); color: var(--color-rail-fg); }
.recent-task.active { border-color: var(--pa-rail-active-border); background: var(--color-rail-active); color: var(--color-rail-fg-strong); }
.recent-icon { display: grid; width: 25px; height: 25px; flex: 0 0 25px; place-items: center; border-radius: var(--radius); background: var(--pa-rail-icon-bg); }
.recent-copy { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 1px; }
.recent-copy strong { overflow: hidden; font-size: var(--pa-t-11); font-weight: var(--font-medium); text-overflow: ellipsis; white-space: nowrap; }
.recent-copy small { color: var(--color-rail-fg-muted); font-size: var(--pa-t-11); }
.recent-status { width: 7px; height: 7px; flex: 0 0 7px; border-radius: var(--radius-full); background: var(--color-success); }
.recent-status.running { background: var(--color-rail-accent); box-shadow: 0 0 0 3px var(--pa-rail-running-glow); }
.recent-all { display: inline-flex; align-items: center; gap: 4px; margin-top: var(--space-1); padding: var(--space-1) var(--space-2); border: none; border-radius: var(--radius-sm); background: transparent; color: var(--color-rail-fg-muted); font-size: var(--pa-t-11); cursor: pointer; }
.recent-all:hover { background: var(--color-rail-surface); color: var(--color-rail-fg-strong); }
.rail-footer { flex-shrink: 0; padding-top: var(--space-2); border-top: 1px solid var(--color-rail-border); }
.profile-entry { display: flex; width: 100%; align-items: center; gap: var(--space-2); padding: var(--space-2); border: none; border-radius: var(--radius-md); background: transparent; color: var(--color-rail-fg); text-align: left; cursor: pointer; }
.profile-entry:hover { background: var(--color-rail-surface); }
.profile-entry > span { display: flex; min-width: 0; flex-direction: column; }
.profile-entry strong { font-size: var(--pa-t-11); font-weight: var(--font-semibold); }
.profile-entry small { overflow: hidden; margin-top: 1px; color: var(--color-rail-fg-muted); font-size: var(--pa-t-11); text-overflow: ellipsis; white-space: nowrap; }
.footer-actions { display: flex; align-items: center; justify-content: space-between; margin-top: var(--space-2); }
.footer-actions button { display: inline-flex; height: 30px; align-items: center; gap: var(--space-2); padding: 0 var(--space-2); border: none; border-radius: var(--radius); background: transparent; color: var(--color-rail-fg-muted); font-size: var(--pa-t-11); cursor: pointer; }
.footer-actions button:hover { background: var(--color-rail-surface); color: var(--color-rail-fg-strong); }
.is-collapsed { align-items: center; padding-inline: var(--space-2); }
.is-collapsed .brand-copy,
.is-collapsed .rail-new span,
.is-collapsed .rail-group-heading,
.is-collapsed .rail-label,
.is-collapsed .recent-section,
.is-collapsed .system-heading,
.is-collapsed .profile-entry span,
.is-collapsed .footer-actions span { display: none; }
.is-collapsed .rail-new,
.is-collapsed .rail-item,
.is-collapsed .profile-entry { width: 42px; padding: 0; justify-content: center; }
.is-collapsed .rail-items { align-items: center; }
.is-collapsed .footer-actions { flex-direction: column; }
.is-collapsed .footer-actions button { width: 42px; justify-content: center; }
.is-collapsed .group-caret { display: none; }
@media (max-width: 920px) {
  .navrail-v2 { align-items: center; padding-inline: var(--space-2); }
  .brand-copy,
  .rail-new span,
  .rail-group-heading,
  .rail-label,
  .recent-section,
  .system-heading,
  .profile-entry span,
  .footer-actions span { display: none; }
  .rail-new,
  .rail-item,
  .profile-entry { width: 42px; padding: 0; justify-content: center; }
  .rail-items { align-items: center; }
  .footer-actions { flex-direction: column; }
  .footer-actions button { width: 42px; justify-content: center; }
  .group-caret { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .rail-new,
  .rail-item,
  .group-caret {
    transition: none;
  }
}
</style>
