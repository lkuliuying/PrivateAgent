<script setup lang="ts">
import { ref, watch } from "vue";
import { PhArrowLeft, PhGearSix, PhSidebarSimple, PhSparkle, PhX } from "@phosphor-icons/vue";
import {
  SETTINGS_SECTION_GROUPS,
  SETTINGS_SECTIONS,
  type SettingsSection,
  type SettingsSectionGroup,
} from "../models/settingsSections";

const props = withDefaults(defineProps<{ active: SettingsSection; narrow?: boolean }>(), {
  narrow: false,
});

const emit = defineEmits<{
  select: [section: SettingsSection];
  exit: [];
}>();

function sectionsFor(group: SettingsSectionGroup) {
  return SETTINGS_SECTIONS.filter((item) => item.group === group);
}

const drawerOpen = ref(false);

watch(
  () => props.narrow,
  () => {
    drawerOpen.value = false;
  }
);

function selectSection(section: SettingsSection): void {
  emit("select", section);
  if (props.narrow) drawerOpen.value = false;
}

function exitSettings(): void {
  emit("exit");
  if (props.narrow) drawerOpen.value = false;
}
</script>

<template>
  <Teleport to="body">
    <button
      v-if="narrow && !drawerOpen"
      type="button"
      class="settings-nav__drawer-tab"
      data-testid="settings-drawer-tab"
      aria-label="打开设置模块"
      @click="drawerOpen = true"
    >
      <PhSidebarSimple :size="17" />
    </button>
    <div
      v-if="narrow && drawerOpen"
      class="settings-nav__backdrop"
      data-testid="settings-drawer-backdrop"
      @click="drawerOpen = false"
    />
  </Teleport>

  <Teleport to="body" :disabled="!narrow">
  <nav
    v-if="!narrow || drawerOpen"
    class="settings-nav"
    :class="{ 'is-drawer': narrow }"
    aria-label="设置模块"
    data-testid="settings-module-nav"
  >
    <header class="settings-nav__brand">
      <span class="settings-nav__mark"><PhGearSix :size="19" weight="fill" /></span>
      <span class="settings-nav__brand-copy">
        <strong>设置</strong>
        <small>LOCAL CONTROL CENTER</small>
      </span>
      <button
        v-if="narrow"
        type="button"
        class="settings-nav__close"
        aria-label="收起设置模块"
        data-testid="settings-drawer-close"
        @click="drawerOpen = false"
      >
        <PhX :size="17" />
      </button>
    </header>

    <div class="settings-nav__scroll">
      <section
        v-for="group in SETTINGS_SECTION_GROUPS"
        :key="group.key"
        class="settings-nav__group"
      >
        <h2>{{ group.label }}</h2>
        <button
          v-for="item in sectionsFor(group.key)"
          :key="item.key"
          type="button"
          class="settings-nav__item"
          :class="{ active: active === item.key }"
          :aria-current="active === item.key ? 'page' : undefined"
          :data-testid="`settings-section-${item.key}`"
          @click="selectSection(item.key)"
        >
          <span class="settings-nav__index">{{ item.index }}</span>
          <span class="settings-nav__copy">
            <strong>{{ item.label }}</strong>
            <small>{{ item.description }}</small>
          </span>
        </button>
      </section>
    </div>

    <footer class="settings-nav__footer">
      <button type="button" class="settings-nav__exit" @click="exitSettings">
        <PhArrowLeft :size="15" />
        <span>返回工作台</span>
      </button>
      <span class="settings-nav__local"><PhSparkle :size="13" /> 数据默认留在本机</span>
    </footer>
  </nav>
  </Teleport>
</template>

<style scoped>
.settings-nav {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid var(--color-border);
  background: var(--color-panel);
}
.settings-nav.is-drawer {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: var(--z-overlay);
  width: min(var(--rail-w), calc(100vw - 48px));
  box-shadow: var(--shadow-lg);
}
.settings-nav__drawer-tab {
  position: fixed;
  top: var(--space-4);
  left: var(--space-3);
  z-index: var(--z-overlay);
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  background: var(--color-surface);
  color: var(--color-fg-muted);
  box-shadow: var(--shadow-sm);
  cursor: pointer;
}
.settings-nav__drawer-tab:hover,
.settings-nav__close:hover {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.settings-nav__backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  background: color-mix(in srgb, var(--color-fg) 22%, transparent);
}
.settings-nav__close {
  display: grid;
  width: 30px;
  height: 30px;
  margin-left: auto;
  flex: 0 0 30px;
  place-items: center;
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-fg-muted);
  cursor: pointer;
}
.settings-nav__brand {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: var(--space-3);
  min-height: 72px;
  padding: var(--space-3);
  border-bottom: 1px solid var(--color-border);
}
.settings-nav__mark {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  place-items: center;
  border-radius: var(--radius-md);
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
}
.settings-nav__brand-copy,
.settings-nav__copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
}
.settings-nav__brand-copy strong {
  color: var(--color-fg);
  font-size: var(--text-sm);
}
.settings-nav__brand-copy small {
  margin-top: 2px;
  color: var(--color-accent);
  font-size: 9px;
  font-weight: var(--font-semibold);
  letter-spacing: .12em;
}
.settings-nav__scroll {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: var(--space-3) var(--space-2);
}
.settings-nav__group + .settings-nav__group {
  margin-top: var(--space-3);
}
.settings-nav__group h2 {
  margin: 0 0 var(--space-1);
  padding: 0 var(--space-2);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
  font-weight: var(--font-semibold);
  letter-spacing: .08em;
}
.settings-nav__item {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
  min-height: 44px;
  padding: var(--space-1) var(--space-2);
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-fg-muted);
  text-align: left;
  cursor: pointer;
}
.settings-nav__item:hover {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.settings-nav__item.active {
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
  box-shadow: inset 2px 0 0 var(--color-accent);
}
.settings-nav__item:focus-visible,
.settings-nav__exit:focus-visible,
.settings-nav__close:focus-visible,
.settings-nav__drawer-tab:focus-visible {
  outline: var(--focus-ring);
  outline-offset: -2px;
}
.settings-nav__index {
  flex: 0 0 24px;
  color: var(--color-accent);
  font: 700 10px/1 var(--font-mono);
  text-align: center;
}
.settings-nav__copy strong {
  overflow: hidden;
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.settings-nav__copy small {
  overflow: hidden;
  margin-top: 2px;
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.settings-nav__footer {
  display: flex;
  flex-shrink: 0;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-2);
  border-top: 1px solid var(--color-border);
}
.settings-nav__exit {
  display: flex;
  height: 32px;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-3);
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
  cursor: pointer;
}
.settings-nav__exit:hover {
  background: var(--color-surface-muted);
  color: var(--color-fg);
}
.settings-nav__local {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-3) var(--space-1);
  color: var(--color-fg-subtle);
  font-size: var(--pa-text-meta);
}
@media (max-height: 680px) {
  .settings-nav__brand { min-height: 58px; }
  .settings-nav__item { min-height: 38px; }
  .settings-nav__copy small { display: none; }
}
</style>
