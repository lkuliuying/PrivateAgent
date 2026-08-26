<script setup lang="ts">
/**
 * UI Lab · 设计系统状态展厅（仅开发模式；?ui-lab 进入，生产构建不可达）。
 * 复用真实 pa-* 组件与真实 fixture 类型，集中展示：
 *  - 全部基础组件及状态；
 *  - Agent idle/running/waiting/completed/failed/stopped；
 *  - 空/加载/错误/离线场景；
 *  - 文本场景（短/长/中英/路径/日志）。
 */
import { computed, ref } from "vue";
import ToolDiagnosticsPanel from "../features/coding/components/ToolDiagnosticsPanel.vue";
import {
  PhChatCircle,
  PhDownloadSimple,
  PhFolderOpen,
  PhGlobe,
  PhMagnifyingGlass,
  PhNotePencil,
  PhPalette,
  PhPuzzlePiece,
  PhSidebar,
  PhStar,
  PhTextT,
  PhTrash,
  PhUserCircle,
  PhWrench,
} from "@phosphor-icons/vue";
import {
  PaBadge,
  PaButton,
  PaCard,
  PaCheckbox,
  PaDialog,
  PaDisclosure,
  PaDropdownMenu,
  PaEmptyState,
  PaErrorState,
  PaField,
  PaIconButton,
  PaInlineNotice,
  PaInput,
  PaProgress,
  PaSegmentedControl,
  PaSelect,
  PaSkeleton,
  PaSpinner,
  PaStatusIndicator,
  PaSwitch,
  PaTabs,
  PaTextarea,
  PaTooltip,
  type PaMenuItem,
} from "../design";
import AgentActivityFeed from "../components/AgentActivityFeed.vue";
import CodingComposer from "../features/coding/components/CodingComposer.vue";
import { workspaceFixtures } from "./uiStateFixtures";

type LabSection =
  | "overview"
  | "buttons"
  | "forms"
  | "data"
  | "navigation"
  | "feedback"
  | "agent"
  | "composer"
  | "text"
  | "a11y"
  | "tools";

const requestedSection = window.location.hash.slice(1);
const section = ref<LabSection>(requestedSection === "composer" ? "composer" : "overview");
const toggleValue = ref(true);
const checkboxValue = ref(true);
const inputValue = ref("本地路径 F:\\Program\\Agent\\apps\\desktop");
const textareaValue = ref("当前阶段：D1 设计系统 2.0。\n目标：后续页面不再自行定义基础控件和状态。");
const selectValue = ref("safe");
const tabsValue = ref("tab-a");
const segmentValue = ref("compact");
const dialogOpen = ref(false);
const disclosureOpen = ref(true);
const selectedMenu = ref("");

const MENU_ITEMS: PaMenuItem[] = [
  { key: "export", label: "导出报告" },
  { key: "duplicate", label: "复制任务" },
  { key: "delete", label: "删除任务", danger: true },
  { key: "disabled", label: "不可用", disabled: true },
];

const SECTIONS: { key: LabSection; label: string; icon: typeof PhPalette }[] = [
  { key: "overview", label: "概览", icon: PhPalette },
  { key: "buttons", label: "按钮", icon: PhStar },
  { key: "forms", label: "表单", icon: PhNotePencil },
  { key: "data", label: "数据展示", icon: PhDownloadSimple },
  { key: "navigation", label: "导航与浮层", icon: PhSidebar },
  { key: "feedback", label: "反馈与空态", icon: PhChatCircle },
  { key: "agent", label: "Agent 状态", icon: PhPuzzlePiece },
  { key: "composer", label: "任务输入器", icon: PhChatCircle },
  { key: "text", label: "文本场景", icon: PhTextT },
  { key: "a11y", label: "无障碍检查", icon: PhUserCircle },
  { key: "tools", label: "工具诊断", icon: PhWrench },
];

const agentFixtures = computed(() =>
  ["empty", "planning", "streaming", "tool-running", "approval-pending", "legacy-tool-pending", "approval-resolved", "failed", "stopped", "rag-answer", "rag-refusal", "reconnecting", "artifacts"]
    .map((key) => workspaceFixtures.find((f) => f.key === key)!)
    .filter(Boolean)
);

const longText = "这是很长的中文示例文本，用于验证长标题、长段落与换行规则是否稳定。".repeat(6);
const enPath = "F:/Program/Agent/apps/desktop/src/components/InspectorPanel.vue".repeat(2);
const logText = "14:02:31.482 [info] sidecar spawned pid=2841 port=51731\n14:02:31.921 [warn] ollama not reachable, retry in 5s\n14:02:36.118 [ok] chroma connected";
</script>

<template>
  <div class="uilab">
    <aside class="uilab-nav">
      <div class="uilab-brand">
        <strong>UI Lab</strong>
        <span>DESIGN SYSTEM 2.0 · DEV</span>
      </div>
      <nav>
        <button
          v-for="item in SECTIONS"
          :key="item.key"
          class="uilab-nav-item"
          :class="{ active: section === item.key }"
          @click="section = item.key"
        >
          <component :is="item.icon" :size="16" />
          {{ item.label }}
        </button>
      </nav>
      <p class="uilab-hint">Ctrl/Cmd+K 命令面板 · Esc 关闭浮层</p>
    </aside>

    <main class="uilab-main">
      <header class="uilab-header">
        <h1>设计系统 2.0 · UI 状态展厅</h1>
        <p>全部场景复用真实组件与公开 DTO fixture；生产构建不可达。</p>
      </header>

      <!-- ============ 概览 ============ -->
      <section v-if="section === 'overview'" class="uilab-section">
        <h2>设计原则（D0 冻结）</h2>
        <div class="lab-grid lab-grid--3">
          <PaCard v-for="p in [
            ['任务优先', '突出目标、进度、阻塞和结果，不把所有内容做成聊天气泡。'],
            ['内容优先', '青色用于交互和状态，避免大面积高亮与装饰性 Dashboard。'],
            ['渐进披露', '默认人类可读摘要，日志与参数按需展开。'],
            ['稳定可预期', '异步状态不跳动，不因活动流更新导致阅读位置失控。'],
            ['动效有意义', '动效只解释层级、状态变化和空间关系。'],
            ['桌面优先', '先服务 Windows 桌面窗口，窄窗口可完成核心流程。'],
          ] as [string, string][]" :key="p[0]" padding="lg">
            <strong class="lab-principle">{{ p[0] }}</strong>
            <p class="lab-principle-desc">{{ p[1] }}</p>
          </PaCard>
        </div>

        <h2>令牌层级</h2>
        <div class="lab-grid lab-grid--3">
          <PaCard padding="lg">
            <PaBadge tone="info">Layer 1</PaBadge>
            <h3>Primitive</h3>
            <p class="lab-card-text">原始调色板与尺度（--pa-p-* / --pa-t-* / --pa-s-* / --pa-r-* / --pa-shadow-* / --pa-m-*）。页面禁止直接引用。</p>
          </PaCard>
          <PaCard padding="lg">
            <PaBadge tone="success">Layer 2</PaBadge>
            <h3>Semantic</h3>
            <p class="lab-card-text">语义角色（--color-* / --pa-text-* / --pa-motion-* / --focus-ring）。页面样式只允许引用本层与组件层。</p>
          </PaCard>
          <PaCard padding="lg">
            <PaBadge tone="warning">Layer 3</PaBadge>
            <h3>Component</h3>
            <p class="lab-card-text">组件级令牌（--pa-btn-* / --pa-input-* / --pa-nav-* / --pa-card-* / --pa-approval-*）。定制组件外观只覆盖本层。</p>
          </PaCard>
        </div>
      </section>

      <!-- ============ 按钮 ============ -->
      <section v-else-if="section === 'buttons'" class="uilab-section">
        <h2>PaButton 变体</h2>
        <div class="lab-row">
          <PaButton variant="default">默认按钮</PaButton>
          <PaButton variant="primary">主操作</PaButton>
          <PaButton variant="ghost">幽灵</PaButton>
          <PaButton variant="subtle">次级</PaButton>
          <PaButton variant="danger">危险</PaButton>
        </div>
        <h2>状态</h2>
        <div class="lab-row">
          <PaButton variant="primary" disabled>禁用</PaButton>
          <PaButton variant="primary" loading>加载中</PaButton>
          <PaButton variant="danger" disabled>危险禁用</PaButton>
        </div>
        <h2>尺寸与图标按钮</h2>
        <div class="lab-row">
          <PaButton size="sm" variant="ghost">小尺寸</PaButton>
          <PaButton size="sm" variant="primary" loading>小加载</PaButton>
          <PaIconButton label="收藏" :active="true"><PhStar :size="16" weight="fill" /></PaIconButton>
          <PaIconButton label="删除" variant="danger"><PhTrash :size="16" /></PaIconButton>
          <PaIconButton label="搜索" disabled><PhMagnifyingGlass :size="16" /></PaIconButton>
        </div>
      </section>

      <!-- ============ 表单 ============ -->
      <section v-else-if="section === 'forms'" class="uilab-section">
        <h2>输入控件</h2>
        <div class="lab-grid lab-grid--2">
          <PaField label="路径" hint="已授权目录可直读">
            <template #default="{ id, error }">
              <PaInput :id="id" v-model="inputValue" :error="error" />
            </template>
          </PaField>
          <PaField label="必填项（校验失败）" error="该字段不能为空" required>
            <template #default="{ id, error }">
              <PaInput :id="id" v-model="inputValue" :error="error" placeholder="请输入…" />
            </template>
          </PaField>
          <PaField label="描述">
            <template #default="{ id }">
              <PaTextarea :id="id" v-model="textareaValue" :rows="3" />
            </template>
          </PaField>
          <PaField label="风险等级">
            <template #default="{ id }">
              <PaSelect
                :id="id"
                v-model="selectValue"
                :options="[
                  { value: 'safe', label: '安全 · 只读操作' },
                  { value: 'confirm', label: '需确认 · 修改文件' },
                  { value: 'risky', label: '高风险 · 执行命令' },
                ]"
              />
            </template>
          </PaField>
        </div>
        <h2>开关与复选</h2>
        <div class="lab-row">
          <PaSwitch v-model="toggleValue" label="启用知识检索" />
          <PaSwitch v-model="toggleValue" label="禁用态" :disabled="true" />
          <PaCheckbox v-model="checkboxValue" label="批准后继续执行后续步骤" />
          <PaCheckbox v-model="checkboxValue" label="禁用复选" :disabled="true" />
        </div>
      </section>

      <!-- ============ 数据展示 ============ -->
      <section v-else-if="section === 'data'" class="uilab-section">
        <h2>徽标与状态</h2>
        <div class="lab-row">
          <PaBadge>中性</PaBadge>
          <PaBadge tone="info">运行中</PaBadge>
          <PaBadge tone="success">已完成</PaBadge>
          <PaBadge tone="warning">等待确认</PaBadge>
          <PaBadge tone="danger">失败</PaBadge>
          <PaBadge tone="muted">已归档</PaBadge>
        </div>
        <div class="lab-row">
          <PaStatusIndicator tone="ok" label="后端在线" />
          <PaStatusIndicator tone="info" label="生成中" pulse />
          <PaStatusIndicator tone="warn" label="Ollama 离线" />
          <PaStatusIndicator tone="bad" label="连接断开" />
          <PaStatusIndicator tone="idle" label="空闲" />
        </div>
        <h2>进度与加载</h2>
        <div class="lab-col">
          <PaProgress :value="42" label="确定进度" />
          <PaProgress :value="null" label="不确定进度" />
          <PaProgress :value="100" tone="success" label="完成" />
          <div class="lab-row">
            <PaSpinner :size="16" label="加载" />
            <PaSpinner :size="20" label="加载" />
            <span class="lab-muted">骨架屏：</span>
            <div style="width: 320px"><PaSkeleton :lines="2" /></div>
          </div>
        </div>
      </section>

      <!-- ============ 导航与浮层 ============ -->
      <section v-else-if="section === 'navigation'" class="uilab-section">
        <h2>页签与分段</h2>
        <PaTabs
          v-model="tabsValue"
          :items="[
            { key: 'tab-a', label: 'Files', badge: 3 },
            { key: 'tab-b', label: 'Context' },
            { key: 'tab-c', label: 'Sources', badge: 2 },
            { key: 'tab-d', label: 'Artifacts' },
          ]"
        />
        <div style="margin-top: var(--space-4)">
          <PaSegmentedControl
            v-model="segmentValue"
            :options="[
              { value: 'comfortable', label: '舒适' },
              { value: 'compact', label: '紧凑' },
              { value: 'dense', label: '高密' },
            ]"
          />
        </div>
        <h2>折叠与下拉</h2>
        <div class="lab-col">
          <PaDisclosure title="运行日志" :open="disclosureOpen" summary="3 行 · 最近 2 分钟">
            <pre class="lab-log">{{ logText }}</pre>
          </PaDisclosure>
          <div class="lab-row">
            <PaDropdownMenu
              label="更多操作"
              :items="MENU_ITEMS"
              @select="selectedMenu = $event"
            />
            <span class="lab-muted">最近选择：{{ selectedMenu || "—" }}</span>
          </div>
          <PaTooltip text="Ctrl/Cmd+K 打开命令面板">
            <PaButton variant="ghost" size="sm">悬停查看 Tooltip</PaButton>
          </PaTooltip>
        </div>
      </section>

      <!-- ============ 反馈与空态 ============ -->
      <section v-else-if="section === 'feedback'" class="uilab-section">
        <h2>行内通知</h2>
        <div class="lab-col">
          <PaInlineNotice tone="info" title="断线恢复">连接已恢复，正在续传未完成的任务状态。</PaInlineNotice>
          <PaInlineNotice tone="warning" title="Ollama 离线">
            本地模型服务未响应，Agent 将等待恢复。
            <template #actions><PaButton size="sm" variant="ghost">打开状态页</PaButton></template>
          </PaInlineNotice>
          <PaInlineNotice tone="danger" title="输出验证失败">
            生成结果未通过校验，请重试或查看诊断。
          </PaInlineNotice>
          <PaInlineNotice tone="success">任务已完成，产物已保存到本地。</PaInlineNotice>
        </div>
        <h2>空态 / 错误态</h2>
        <div class="lab-grid lab-grid--2">
          <PaCard padding="lg">
            <PaEmptyState :icon="PhFolderOpen" title="还没有任务" description="新任务会出现在这里，Agent 会先建立计划再执行。" />
          </PaCard>
          <PaCard padding="lg">
            <PaEmptyState :icon="PhGlobe" title="知识库为空" description="导入文档后即可开启基于本地资料的回答。" display>
              <PaButton variant="primary" size="sm">导入文档</PaButton>
            </PaEmptyState>
          </PaCard>
          <PaCard padding="lg">
            <PaErrorState title="后端启动失败" message="sidecar 启动超时（90s）。本地数据未受影响，可重试或重新配置连接。" />
          </PaCard>
          <PaCard padding="lg">
            <PaErrorState title="无法读取目录" message="目录不存在或已被移动：D:\\Photos" />
          </PaCard>
        </div>
        <h2>对话框</h2>
        <div class="lab-row">
          <PaButton variant="primary" @click="dialogOpen = true">打开确认对话框</PaButton>
          <PaButton variant="ghost" @click="dialogOpen = true">打开普通对话框</PaButton>
        </div>
        <PaDialog :open="dialogOpen" title="确认执行工具" :width="420" @close="dialogOpen = false">
          <p class="lab-dialog-text">
            Agent 准备执行 <code>run_command</code>：<br />
            <code class="lab-code">mv screenshot-*.png archive/</code><br />
            范围：<strong>E:\Downloads</strong> · 风险：需确认 · 可撤销：否。
          </p>
          <template #footer>
            <PaButton variant="ghost" @click="dialogOpen = false">拒绝</PaButton>
            <PaButton variant="primary" @click="dialogOpen = false">批准执行</PaButton>
          </template>
        </PaDialog>
      </section>

      <!-- ============ Agent 状态 ============ -->
      <section v-else-if="section === 'agent'" class="uilab-section">
        <h2>Agent 工作流状态（真实 fixture）</h2>
        <p class="lab-muted">
          来源：<code>src/dev/uiStateFixtures.ts</code>，与 <code>docs/releases/v0.4.0/ui-state-matrix-0.4.0.md</code> 一一对应。
        </p>
        <PaTabs
          v-model="segmentValue"
          :items="agentFixtures.map((f) => ({ key: f.key, label: f.label }))"
        />
        <div style="margin-top: var(--space-4)">
          <PaCard v-for="f in agentFixtures.filter((f) => f.key === segmentValue)" :key="f.key" padding="lg">
            <PaBadge tone="info">{{ f.description }}</PaBadge>
            <div class="lab-agent-scroll">
              <AgentActivityFeed
                :messages="f.messages"
                :streaming="f.streaming"
                @approve="() => {}"
                @reject="() => {}"
                @approve-agent="() => {}"
                @reject-agent="() => {}"
                @select-chunk="() => {}"
                @save-inbox="() => {}"
                @use-prompt="() => {}"
              />
            </div>
          </PaCard>
        </div>
      </section>

      <!-- ============ 任务输入器 ============ -->
      <section v-else-if="section === 'composer'" class="uilab-section composer-lab">
        <h2>任务输入器 · 空闲态</h2>
        <p class="lab-muted">真实 CodingComposer，用于对照视觉稿与验证输入、权限、模型和发送交互。</p>
        <div class="composer-stage">
          <CodingComposer :thread-id="909" :search-files="async () => []" />
        </div>
      </section>

      <!-- ============ 文本场景 ============ -->
      <section v-else-if="section === 'text'" class="uilab-section">
        <h2>长文本 / 路径 / 日志</h2>
        <div class="lab-col">
          <PaCard padding="lg">
            <strong>超长中文标题</strong>
            <p class="lab-text">{{ longText }}</p>
          </PaCard>
          <PaCard padding="lg">
            <strong>英文长路径</strong>
            <p class="lab-text lab-path">{{ enPath }}</p>
          </PaCard>
          <PaCard padding="lg">
            <strong>技术日志（等宽字体）</strong>
            <pre class="lab-log">{{ logText }}</pre>
          </PaCard>
          <PaCard padding="lg">
            <strong>混合内容：</strong>
            <p class="lab-text">
              更新 <code>tokens.css</code> 后，页面引用 <code>--color-accent</code> 得到 #08aeb5。
              中文正文行高不低于 1.5，技术日志使用等宽字体但普通工具摘要不使用等宽字体。
            </p>
          </PaCard>
        </div>
      </section>

      <!-- ============ 无障碍 ============ -->
      <section v-else-if="section === 'a11y'" class="uilab-section">
        <h2>对比度与焦点</h2>
        <div class="lab-grid lab-grid--3">
          <PaCard padding="lg">
            <h3>文本对比（WCAG AA）</h3>
            <p class="lab-text">正文 --color-fg 于 --color-surface</p>
            <p class="lab-text lab-muted">次级 --color-fg-muted</p>
            <p class="lab-text lab-faint">辅助 --color-fg-subtle</p>
            <p class="lab-text lab-accent">链接/强调 --color-accent</p>
          </PaCard>
          <PaCard padding="lg">
            <h3>键盘路径</h3>
            <ul class="lab-list">
              <li>Tab：进入下一个可交互元素（focus-visible 环）</li>
              <li>PaTabs：←/→ 切换页签</li>
              <li>PaDropdownMenu：↑/↓ 遍历，Esc 关闭</li>
              <li>PaDialog：Esc 关闭，焦点圈禁，关闭后归还</li>
              <li>Ctrl/Cmd+K：命令面板（全局）</li>
            </ul>
          </PaCard>
          <PaCard padding="lg">
            <h3>reduced-motion</h3>
            <p class="lab-text">
              系统开启"减少动态效果"时：位移/缩放/循环脉冲移除，
              Spinner 退化为静态点（组件已内建），功能与状态信息不依赖动画。
            </p>
          </PaCard>
        </div>
        <div class="lab-row">
          <PaButton variant="primary">Tab 聚焦后应显示焦点环</PaButton>
          <PaButton variant="ghost">Focus 顺序：左→右</PaButton>
          <PaInput v-model="inputValue" style="width: 280px" placeholder="输入框焦点环" />
        </div>
      </section>

      <section v-else-if="section === 'tools'" class="uilab-section">
        <h2>工具诊断（CT-9 · ToolSnapshot 投影）</h2>
        <p class="uilab-note">
          消费 GET /agent-runs/tool-diagnostics；脱敏视图。端点需
          PA_AGENT_V2_TOOL_SNAPSHOT_ENABLED=1。
        </p>
        <ToolDiagnosticsPanel initial-tags="" />
      </section>
    </main>
  </div>
</template>

<style scoped>
.uilab {
  display: flex;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  background: var(--color-bg);
}
.uilab-nav {
  display: flex;
  width: 220px;
  flex-shrink: 0;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-3);
  border-right: 1px solid var(--color-border);
  background: var(--color-surface);
}
.uilab-brand {
  display: flex;
  flex-direction: column;
  padding: 0 var(--space-1);
}
.uilab-brand strong {
  font-size: var(--pa-text-section);
}
.uilab-brand span {
  margin-top: 2px;
  color: var(--color-fg-faint);
  font-size: var(--pa-t-11);
  font-weight: var(--font-semibold);
  letter-spacing: 0.1em;
}
.uilab-nav nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.uilab-nav-item {
  display: flex;
  height: 34px;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-3);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-compact);
  cursor: pointer;
  text-align: left;
}
.uilab-nav-item:hover {
  background: var(--color-surface-sunken);
  color: var(--color-fg);
}
.uilab-nav-item.active {
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
  font-weight: var(--font-medium);
}
.uilab-hint {
  margin: auto 0 0;
  padding: var(--space-2);
  color: var(--color-fg-faint);
  font-size: var(--pa-t-11);
  line-height: 1.5;
}
.uilab-main {
  flex: 1;
  min-width: 0;
  overflow: auto;
  padding: var(--space-6) var(--space-8) var(--space-10);
}
.uilab-header h1 {
  margin: 0;
  font-size: var(--pa-text-page-title);
}
.uilab-header p {
  margin: var(--space-1) 0 0;
  color: var(--color-fg-subtle);
}
.uilab-section h2 {
  margin: var(--space-8) 0 var(--space-3);
  font-size: var(--pa-text-section);
}
.uilab-section h3 {
  margin: var(--space-2) 0;
  font-size: var(--pa-text-body);
}
.lab-grid {
  display: grid;
  gap: var(--space-4);
}
.lab-grid--2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.lab-grid--3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.lab-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}
.lab-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  max-width: 760px;
}
.lab-principle {
  font-size: var(--pa-text-body);
}
.lab-principle-desc {
  margin: var(--space-1) 0 0;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-compact);
  line-height: var(--leading-normal);
}
.lab-card-text {
  margin: var(--space-1) 0 0;
  color: var(--color-fg-muted);
  font-size: var(--pa-text-compact);
  line-height: var(--leading-normal);
}
.lab-muted { color: var(--color-fg-muted); font-size: var(--pa-text-compact); }
.lab-faint { color: var(--color-fg-faint); }
.lab-accent { color: var(--color-accent); }
.lab-text { line-height: var(--leading-normal); word-break: break-word; }
.lab-path { font-family: var(--font-mono); font-size: var(--pa-text-mono); }
.lab-log {
  margin: var(--space-2) 0 0;
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background: var(--color-surface-sunken);
  color: var(--color-fg-muted);
  font-family: var(--font-mono);
  font-size: var(--pa-t-12);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}
.lab-code {
  padding: 1px var(--space-1);
  border-radius: var(--radius-sm);
  background: var(--color-surface-sunken);
  font-family: var(--font-mono);
  font-size: var(--pa-t-12);
}
.lab-list {
  margin: 0;
  padding-left: var(--space-5);
  color: var(--color-fg-muted);
  font-size: var(--pa-text-compact);
  line-height: 1.8;
}
.lab-dialog-text {
  margin: 0;
  line-height: var(--leading-normal);
}
.lab-agent-scroll {
  margin-top: var(--space-3);
  max-height: 480px;
  overflow: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
}
.composer-lab {
  min-width: 0;
}
.composer-stage {
  width: min(922px, 100%);
  margin-top: var(--space-6);
}
</style>
