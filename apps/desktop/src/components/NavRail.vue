<script setup lang="ts">
import { ref } from "vue";
import {
  PhActivity,
  PhBooks,
  PhBrain,
  PhChatsCircle,
  PhCommand,
  PhDatabase,
  PhDotsThree,
  PhFolderSimple,
  PhGearSix,
  PhGraduationCap,
  PhListChecks,
  PhPlus,
  PhPlugs,
  PhPuzzlePiece,
  PhSidebarSimple,
  PhSparkle,
  PhSun,
  PhUserCircle,
} from "@phosphor-icons/vue";
import type { Session, View } from "../types";

withDefaults(
  defineProps<{
    active: View;
    sessions?: Session[];
    currentId?: number | null;
    collapsed?: boolean;
  }>(),
  {
    sessions: () => [],
    currentId: null,
    collapsed: false,
  }
);
const emit = defineEmits<{
  navigate: [view: View];
  "open-command": [];
  "new-session": [];
  "select-session": [id: number];
  "toggle-collapse": [];
}>();
const utilitiesOpen = ref(false);

const primaryItems: { key: View; label: string; icon: typeof PhChatsCircle }[] = [
  { key: "tasks", label: "任务", icon: PhListChecks },
  { key: "chat", label: "Agent", icon: PhChatsCircle },
  { key: "kb", label: "知识库", icon: PhBooks },
  { key: "integrations", label: "集成", icon: PhPlugs },
  { key: "settings", label: "设置", icon: PhGearSix },
];

const utilityItems: { key: View; label: string; icon: typeof PhChatsCircle }[] = [
  { key: "today", label: "今日", icon: PhSun },
  { key: "projects", label: "项目", icon: PhFolderSimple },
  { key: "learning", label: "学习", icon: PhGraduationCap },
  { key: "memory", label: "记忆", icon: PhBrain },
  { key: "diagnostics", label: "诊断", icon: PhActivity },
  { key: "extensions", label: "扩展", icon: PhPuzzlePiece },
  { key: "backup", label: "备份", icon: PhDatabase },
];

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
  <nav class="navrail" :class="{ 'is-collapsed': collapsed }" aria-label="主导航">
    <div class="navrail-brand" title="PrivateAgent 本地智能体">
      <div class="brand-mark"><PhSparkle :size="22" weight="fill" /></div>
      <div class="brand-copy">
        <strong>PrivateAgent</strong>
        <span>LOCAL AGENT</span>
      </div>
    </div>

    <button class="new-task" title="新建任务" @click="emit('new-session')">
      <PhPlus :size="18" weight="bold" />
      <span>新建任务</span>
    </button>

    <div class="rail-scroll">
      <span class="nav-section-label">工作台</span>
      <ul class="navrail-items" aria-label="主要功能">
        <li v-for="item in primaryItems" :key="item.key">
          <button
            class="nav-item"
            :data-testid="`nav-${item.key}`"
            :class="{ active: active === item.key }"
            :aria-current="active === item.key ? 'page' : undefined"
            :title="item.label"
            @click="emit('navigate', item.key)"
          >
            <component :is="item.icon" class="nav-icon" :size="19" />
            <span class="nav-label">{{ item.label }}</span>
          </button>
        </li>
      </ul>

      <button
        class="nav-item utility-toggle"
        data-testid="nav-utilities-toggle"
        :class="{ active: utilitiesOpen || utilityItems.some((item) => item.key === active) }"
        :aria-expanded="utilitiesOpen"
        title="更多工作区"
        @click="utilitiesOpen = !utilitiesOpen"
      >
        <PhDotsThree class="nav-icon" :size="20" weight="bold" />
        <span class="nav-label">更多工作区</span>
      </button>
      <Transition name="rail-more">
        <ul v-if="utilitiesOpen" class="navrail-items utility-items advanced-items" aria-label="更多工作区">
          <li v-for="item in utilityItems" :key="item.key">
            <button
              class="nav-item nav-item--compact"
              :data-testid="`nav-${item.key}`"
              :class="{ active: active === item.key }"
              :aria-current="active === item.key ? 'page' : undefined"
              :title="item.label"
              @click="emit('navigate', item.key)"
            >
              <component :is="item.icon" class="nav-icon" :size="17" />
              <span class="nav-label">{{ item.label }}</span>
            </button>
          </li>
        </ul>
      </Transition>

      <section class="recent-section" aria-labelledby="recent-title">
        <div class="recent-heading">
          <span id="recent-title">最近任务</span>
          <span>{{ sessions.length }}</span>
        </div>
        <div v-if="sessions.length === 0" class="recent-empty">新建任务后会显示在这里</div>
        <button
          v-for="session in sessions.slice(0, 6)"
          :key="session.id"
          class="recent-task"
          :class="{ active: active === 'chat' && session.id === currentId }"
          :title="session.title"
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
      </section>
    </div>

    <div class="navrail-footer">
      <button class="profile-entry" title="本地用户设置" @click="emit('navigate', 'settings')">
        <PhUserCircle :size="30" weight="fill" />
        <span>
          <strong>本地用户</strong>
          <small>数据仅存储在此设备</small>
        </span>
      </button>
      <div class="footer-actions">
        <button class="command-shortcut" title="快捷命令 Ctrl K" aria-label="快捷命令 Ctrl K" @click="emit('open-command')">
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
.navrail {
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
.navrail-brand { display: flex; min-width: 0; flex-shrink: 0; align-items: center; gap: var(--space-3); padding: 0 var(--space-1); }
.brand-mark { display: grid; width: 36px; height: 36px; flex: 0 0 36px; place-items: center; border: 1px solid rgba(95, 224, 229, .24); border-radius: 11px; background: rgba(8, 174, 181, .13); color: var(--color-rail-accent); }
.brand-copy { display: flex; min-width: 0; flex-direction: column; }
.brand-copy strong { overflow: hidden; color: var(--color-rail-fg-strong); font-size: var(--text-lg); letter-spacing: .01em; text-overflow: ellipsis; white-space: nowrap; }
.brand-copy span { margin-top: 1px; color: var(--color-rail-fg-muted); font-size: 9px; font-weight: var(--font-semibold); letter-spacing: .13em; }
.new-task { display: flex; width: 100%; height: 40px; flex-shrink: 0; align-items: center; justify-content: center; gap: var(--space-2); border: 1px solid var(--pa-btn-primary-bg); border-radius: var(--radius-md); background: var(--pa-btn-primary-bg); color: var(--color-accent-fg); font-weight: var(--font-semibold); cursor: pointer; transition: background var(--duration-fast) var(--ease), transform var(--duration-fast) var(--ease); }
.new-task:hover { background: var(--pa-btn-primary-bg-hover); transform: translateY(-1px); }
.new-task:active { transform: translateY(0); }
.new-task:focus-visible { outline: none; box-shadow: 0 0 0 2px var(--color-rail-bg), 0 0 0 4px var(--color-rail-accent); }
.rail-scroll { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; }
.nav-section-label { display: block; margin: var(--space-1) var(--space-2) var(--space-2); color: var(--color-rail-fg-muted); font-size: 9px; font-weight: var(--font-semibold); letter-spacing: .12em; text-transform: uppercase; }
.navrail-items { display: flex; margin: 0; padding: 0; flex-direction: column; gap: 2px; list-style: none; }
.nav-item { display: flex; position: relative; width: 100%; height: 38px; align-items: center; gap: var(--space-3); padding: 0 var(--space-3); border: none; border-radius: var(--radius-md); background: transparent; color: var(--color-rail-fg-muted); cursor: pointer; transition: background var(--duration-fast) var(--ease), color var(--duration-fast) var(--ease); }
.nav-item:hover { background: var(--color-rail-surface); color: var(--color-rail-fg-strong); }
.nav-item.active { background: var(--color-rail-active); color: var(--color-rail-fg-strong); }
.nav-item.active::before { content: ""; position: absolute; top: 10px; bottom: 10px; left: 0; width: 2px; border-radius: var(--radius-full); background: var(--color-rail-accent); }
.nav-item:focus-visible, .recent-task:focus-visible, .profile-entry:focus-visible, .footer-actions button:focus-visible { outline: none; box-shadow: inset 0 0 0 2px var(--color-rail-accent); }
.nav-icon { flex-shrink: 0; }
.nav-label { overflow: hidden; font-size: var(--text-sm); text-overflow: ellipsis; white-space: nowrap; }
.utility-toggle { margin-top: var(--space-1); }
.utility-items { margin: var(--space-1) 0 var(--space-2); padding-left: var(--space-2); border-left: 1px solid var(--color-rail-border); }
.nav-item--compact { height: 32px; }
.recent-section { margin-top: var(--space-4); padding-top: var(--space-3); border-top: 1px solid var(--color-rail-border); }
.recent-heading { display: flex; align-items: center; justify-content: space-between; padding: 0 var(--space-2) var(--space-2); color: var(--color-rail-fg-muted); font-size: 10px; font-weight: var(--font-semibold); letter-spacing: .06em; }
.recent-empty { padding: var(--space-3); color: var(--color-rail-fg-muted); font-size: var(--text-xs); line-height: 1.5; }
.recent-task { display: flex; width: 100%; min-width: 0; align-items: center; gap: var(--space-2); padding: var(--space-2); border: 1px solid transparent; border-radius: var(--radius-md); background: transparent; color: var(--color-rail-fg-muted); text-align: left; cursor: pointer; }
.recent-task:hover { background: var(--color-rail-surface); color: var(--color-rail-fg); }
.recent-task.active { border-color: rgba(95, 224, 229, .14); background: var(--color-rail-active); color: var(--color-rail-fg-strong); }
.recent-icon { display: grid; width: 25px; height: 25px; flex: 0 0 25px; place-items: center; border-radius: var(--radius); background: rgba(255,255,255,.055); }
.recent-copy { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 1px; }
.recent-copy strong { overflow: hidden; font-size: var(--text-xs); font-weight: var(--font-medium); text-overflow: ellipsis; white-space: nowrap; }
.recent-copy small { color: var(--color-rail-fg-muted); font-size: 9px; }
.recent-status { width: 7px; height: 7px; flex: 0 0 7px; border-radius: var(--radius-full); background: var(--color-success); }
.recent-status.running { background: var(--color-rail-accent); box-shadow: 0 0 0 3px rgba(95, 224, 229, .12); }
.navrail-footer { flex-shrink: 0; padding-top: var(--space-3); border-top: 1px solid var(--color-rail-border); }
.profile-entry { display: flex; width: 100%; align-items: center; gap: var(--space-2); padding: var(--space-2); border: none; border-radius: var(--radius-md); background: transparent; color: var(--color-rail-fg); text-align: left; cursor: pointer; }
.profile-entry:hover { background: var(--color-rail-surface); }
.profile-entry > span { display: flex; min-width: 0; flex-direction: column; }
.profile-entry strong { font-size: var(--text-xs); font-weight: var(--font-semibold); }
.profile-entry small { overflow: hidden; margin-top: 1px; color: var(--color-rail-fg-muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.footer-actions { display: flex; align-items: center; justify-content: space-between; margin-top: var(--space-2); }
.footer-actions button { display: inline-flex; height: 30px; align-items: center; gap: var(--space-2); padding: 0 var(--space-2); border: none; border-radius: var(--radius); background: transparent; color: var(--color-rail-fg-muted); font-size: 10px; cursor: pointer; }
.footer-actions button:hover { background: var(--color-rail-surface); color: var(--color-rail-fg-strong); }
.rail-more-enter-active, .rail-more-leave-active { transition: opacity var(--duration) var(--ease), transform var(--duration) var(--ease); }
.rail-more-enter-from, .rail-more-leave-to { opacity: 0; transform: translateY(-4px); }
.is-collapsed { align-items: center; padding-inline: var(--space-2); }
.is-collapsed .brand-copy, .is-collapsed .new-task span, .is-collapsed .nav-section-label, .is-collapsed .nav-label, .is-collapsed .recent-section, .is-collapsed .profile-entry span, .is-collapsed .footer-actions span { display: none; }
.is-collapsed .new-task, .is-collapsed .nav-item, .is-collapsed .profile-entry { width: 42px; padding: 0; justify-content: center; }
.is-collapsed .utility-items { padding-left: 0; border-left: none; }
.is-collapsed .footer-actions { flex-direction: column; }
.is-collapsed .footer-actions button { width: 42px; justify-content: center; }
@media (max-width: 920px) {
  .navrail { align-items: center; padding-inline: var(--space-2); }
  .brand-copy, .new-task span, .nav-section-label, .nav-label, .recent-section, .profile-entry span, .footer-actions span { display: none; }
  .new-task, .nav-item, .profile-entry { width: 42px; padding: 0; justify-content: center; }
  .utility-items { padding-left: 0; border-left: none; }
  .footer-actions { flex-direction: column; }
  .footer-actions button { width: 42px; justify-content: center; }
}
@media (prefers-reduced-motion: reduce) {
  .new-task, .nav-item, .rail-more-enter-active, .rail-more-leave-active { transition: none; }
}
</style>
