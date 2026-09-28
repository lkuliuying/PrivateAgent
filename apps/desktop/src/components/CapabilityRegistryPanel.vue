<script setup lang="ts">
import { computed, ref } from "vue";
import { PhBookOpen, PhFolderSimple, PhPlugs, PhPuzzlePiece } from "@phosphor-icons/vue";
import { useCodingWorkspace } from "../features/coding/model/codingWorkspaceStore";
import SkillsPanel from "./SkillsPanel.vue";
import McpIntegrationsPanel from "./McpIntegrationsPanel.vue";
import DocumentationMcpPanel from "./DocumentationMcpPanel.vue";

const store = useCodingWorkspace();
const tab = ref<"skills" | "mcp">("skills");
const project = computed(() => store.projects.value.find(item => item.id === store.selectedProjectId.value));
</script>

<template>
  <section class="capability-registry">
    <div class="capability-content">
      <header class="capability-heading">
        <div><p class="capability-eyebrow">能力与工具</p><h1>让搭档多一份能力</h1><p>管理项目技能，连接完成任务所需的外部工具。</p></div>
        <PhPuzzlePiece :size="40" weight="duotone" aria-hidden="true" />
      </header>
      <div class="capability-project">
        <PhFolderSimple :size="20" aria-hidden="true" />
        <label for="capability-project-select">当前项目</label>
        <select id="capability-project-select" class="pa-input" :value="store.selectedProjectId.value ?? ''" @change="store.selectProject(Number(($event.target as HTMLSelectElement).value))">
          <option v-if="!store.projects.value.length" value="">尚无项目</option>
          <option v-for="item in store.projects.value" :key="item.id" :value="item.id">{{ item.name }}</option>
        </select>
        <span>配置仅作用于所选项目</span>
      </div>
      <nav class="capability-tabs" aria-label="插件类型">
        <button type="button" :aria-pressed="tab === 'skills'" @click="tab = 'skills'"><PhBookOpen :size="18" />Skills</button>
        <button type="button" :aria-pressed="tab === 'mcp'" @click="tab = 'mcp'"><PhPlugs :size="18" />MCP 工具</button>
      </nav>
      <div class="capability-panel">
        <p v-if="!store.selectedProjectId.value" class="capability-empty">先在工作台添加并选择一个项目，再配置技能与外部工具。</p>
        <template v-else>
          <p class="capability-scope"><PhFolderSimple :size="14" />{{ project?.name || '当前项目' }}</p>
          <SkillsPanel v-if="tab === 'skills'" :key="store.selectedProjectId.value" :project-id="store.selectedProjectId.value" />
          <div v-else>
            <McpIntegrationsPanel :key="store.selectedProjectId.value" :project-id="store.selectedProjectId.value" />
            <details><summary>公开文档服务（已有配置）</summary><DocumentationMcpPanel /></details>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.capability-registry { flex: 1; min-height: 0; overflow: auto; padding: var(--space-5) clamp(20px, 3vw, 48px) var(--space-10); background: var(--color-bg); color: var(--color-fg); }
.capability-content { max-width: 1060px; margin: 0 auto; }
.capability-heading { display: flex; align-items: center; justify-content: space-between; gap: var(--space-6); margin-bottom: var(--space-6); }
.capability-heading h1 { margin: 0 0 var(--space-2); font-size: var(--pa-text-page-title); font-weight: var(--font-semibold); }
.capability-heading p { margin: 0; color: var(--color-fg-subtle); line-height: 1.6; }
.capability-heading .capability-eyebrow { margin-bottom: var(--space-2); color: var(--color-accent-soft-fg); font-size: var(--pa-text-meta); }
.capability-heading > svg { flex-shrink: 0; color: var(--color-accent-soft-fg); }
.capability-project { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); padding: var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); }
.capability-project > svg { color: var(--color-accent-soft-fg); }
.capability-project label { font-size: var(--pa-text-compact); }
.capability-project select { width: min(280px, 100%); min-width: 0; }
.capability-project > span { margin-left: auto; color: var(--color-fg-subtle); font-size: var(--pa-text-meta); }
.capability-tabs { display: flex; gap: var(--space-5); margin-top: var(--space-5); border-bottom: 1px solid var(--color-border); }
.capability-tabs button { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-3) var(--space-2); border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--color-fg-muted); cursor: pointer; }
.capability-tabs button[aria-pressed="true"] { border-bottom-color: var(--color-accent); color: var(--color-accent-soft-fg); font-weight: var(--font-semibold); }
.capability-tabs button:focus-visible { outline: 2px solid var(--color-accent); outline-offset: -2px; }
.capability-panel { margin-top: var(--space-5); padding: var(--space-6); border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); }
.capability-scope { display: flex; align-items: center; gap: var(--space-2); margin: 0 0 var(--space-5); color: var(--color-fg-subtle); font-size: var(--pa-text-meta); }
.capability-empty { padding: var(--space-8) 0; color: var(--color-fg-muted); text-align: center; }
details { margin-top: var(--space-5); padding-top: var(--space-4); border-top: 1px solid var(--color-border); }
summary { color: var(--color-fg-muted); cursor: pointer; }
@media (max-width: 600px) { .capability-panel { padding: var(--space-4); } .capability-project > span { width: 100%; margin-left: 0; } }
</style>
