<script setup lang="ts">
import { computed, ref, watch, type Component } from "vue";
import {
  PhArchive,
  PhArrowLeft,
  PhBrain,
  PhInfo,
  PhMagnifyingGlass,
  PhPlugs,
  PhPuzzlePiece,
  PhSidebarSimple,
  PhUserCircle,
  PhX,
} from "@phosphor-icons/vue";
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

const sectionIcons: Record<SettingsSection, Component> = {
  "current-model": PhBrain,
  provider: PhPlugs,
  mcp: PhPuzzlePiece,
  profile: PhUserCircle,
  backup: PhArchive,
  about: PhInfo,
};

const drawerOpen = ref(false);
const query = ref("");

const normalizedQuery = computed(() => query.value.trim().toLocaleLowerCase());

function sectionsFor(group: SettingsSectionGroup) {
  const keyword = normalizedQuery.value;
  return SETTINGS_SECTIONS.filter((item) => {
    if (item.group !== group) return false;
    if (!keyword) return true;
    return `${item.label} ${item.description}`.toLocaleLowerCase().includes(keyword);
  });
}

const visibleGroups = computed(() =>
  SETTINGS_SECTION_GROUPS.filter((group) => sectionsFor(group.key).length > 0)
);

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
      <header class="settings-nav__header">
        <div class="settings-nav__topline">
          <button type="button" class="settings-nav__exit" @click="exitSettings">
            <PhArrowLeft :size="15" aria-hidden="true" />
            <span>返回应用</span>
          </button>
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
        </div>
        <label class="settings-nav__search">
          <PhMagnifyingGlass :size="15" aria-hidden="true" />
          <input
            v-model="query"
            type="search"
            placeholder="搜索设置…"
            aria-label="搜索设置"
            data-testid="settings-search"
          />
        </label>
      </header>

      <div class="settings-nav__scroll">
        <section
          v-for="group in visibleGroups"
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
            <component :is="sectionIcons[item.key]" :size="17" aria-hidden="true" />
            <span>{{ item.label }}</span>
          </button>
        </section>

        <p v-if="visibleGroups.length === 0" class="settings-nav__empty">
          没有匹配的设置
        </p>
      </div>
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
  background: color-mix(in srgb, var(--color-panel) 80%, var(--color-surface-muted));
}

.settings-nav.is-drawer {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: var(--z-overlay);
  width: min(276px, calc(100vw - 48px));
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

.settings-nav__backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  background: color-mix(in srgb, var(--color-fg) 22%, transparent);
}

.settings-nav__header {
  display: flex;
  flex-shrink: 0;
  flex-direction: column;
  gap: 12px;
  padding: 16px 10px 12px;
}

.settings-nav__topline {
  display: flex;
  min-height: 30px;
  align-items: center;
  justify-content: space-between;
}

.settings-nav__exit,
.settings-nav__close {
  border: 0;
  background: transparent;
  color: var(--color-fg-muted);
  cursor: pointer;
}

.settings-nav__exit {
  display: inline-flex;
  height: 30px;
  align-items: center;
  gap: 7px;
  padding: 0 8px;
  border-radius: 8px;
  font-size: var(--text-xs);
}

.settings-nav__close {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 8px;
}

.settings-nav__exit:hover,
.settings-nav__close:hover,
.settings-nav__drawer-tab:hover {
  background: var(--color-surface-hover);
  color: var(--color-fg);
}

.settings-nav__search {
  display: flex;
  height: 34px;
  align-items: center;
  gap: 7px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: color-mix(in srgb, var(--color-surface-muted) 88%, var(--color-border));
  color: var(--color-fg-subtle);
}

.settings-nav__search:focus-within {
  border-color: color-mix(in srgb, var(--color-accent) 45%, var(--color-border));
  background: var(--color-surface);
}

.settings-nav__search input {
  min-width: 0;
  flex: 1;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--color-fg);
  font: inherit;
  font-size: var(--text-xs);
}

.settings-nav__search input::placeholder {
  color: var(--color-fg-faint);
}

.settings-nav__scroll {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 3px 8px 16px;
}

.settings-nav__group + .settings-nav__group {
  margin-top: 18px;
}

.settings-nav__group h2 {
  margin: 0 0 5px;
  padding: 0 9px;
  color: var(--color-fg-faint);
  font-size: var(--pa-text-meta);
  font-weight: var(--font-medium);
}

.settings-nav__item {
  display: flex;
  width: 100%;
  height: 34px;
  align-items: center;
  gap: 9px;
  padding: 0 9px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
  text-align: left;
  cursor: pointer;
}

.settings-nav__item:hover {
  background: var(--color-surface-hover);
  color: var(--color-fg);
}

.settings-nav__item.active {
  background: color-mix(in srgb, var(--color-fg) 8%, var(--color-surface));
  color: var(--color-fg);
  font-weight: var(--font-medium);
}

.settings-nav__item:focus-visible,
.settings-nav__exit:focus-visible,
.settings-nav__close:focus-visible,
.settings-nav__drawer-tab:focus-visible {
  outline: var(--focus-ring);
  outline-offset: -2px;
}

.settings-nav__empty {
  margin: 18px 8px;
  color: var(--color-fg-faint);
  font-size: var(--text-xs);
  text-align: center;
}

@media (max-height: 680px) {
  .settings-nav__header { padding-top: 10px; }
  .settings-nav__group + .settings-nav__group { margin-top: 10px; }
  .settings-nav__item { height: 31px; }
}
</style>
