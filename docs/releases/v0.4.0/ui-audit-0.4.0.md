# PrivateAgent 0.4.0 UI 审计报告（D0）

> 基线：`0.3.0-alpha.2`，提交 `e6da3ee`，schema `0022`
> 审计日期：2026-08-08
> 审计范围：`apps/desktop/src` 全部 54 个 Vue 组件、tokens/components 设计系统、animations 动效模块、App.vue 装配层
> 配套文档：[`ui-state-matrix-0.4.0.md`](./ui-state-matrix-0.4.0.md)、[`v0.4.0-ui-ux-redesign-plan.md`](./v0.4.0-ui-ux-redesign-plan.md)

## 1. 资产清单（应保留演进）

| 资产 | 现状 | 处置 |
|---|---|---|
| `WorkspaceShell` | 三栏壳（rail 240/72、中央、检查器 360/320、状态栏），1320/920 断点 | 保留布局骨架，升级为 AppShell v2（分组导航、四 tab 上下文栏、统一页面层级） |
| `NavRail` | 主导航 5 + 更多工作区 7、最近任务 6 条、折叠、命令入口 | 信息架构重组为 6 个分组，迁移到视图注册表驱动 |
| `tokens.css` | 单层令牌：颜色/字号/间距/圆角/阴影/动效/布局/z-index 共 ~80 个 | 升级为三层令牌（primitive/semantic/component），保留旧变量别名保证兼容 |
| `components.css` | pa-btn/input/badge/status-dot/card + 动画语义层 | 保留类名契约，组件化封装为 `pa-*` Vue 组件 |
| Phosphor Icons / anime.js | 已统一使用，anime 作用域清理完整 | 继续使用，不引入新图标/动画库 |
| `animations/` | agent/chat/page/workflow 四模块均有完整 destroy 清理 | 按动效等级语义收敛参数（见 §6） |
| `models/agentWorkspace.ts` | 计划/任务状态/工具状态映射 | 保留，扩展为 D3 统一 UI 模型适配层 |
| `dev/agentWorkspacePreview.ts` | 运行中任务预览 fixture | 保留并扩展为全状态 fixture 集 |
| 测试基建 | Vitest 32 项、Playwright 15 项、release-check 14/14 | 每个 D 阶段同步扩充 |

## 2. 量化审计结果

### 2.1 硬编码颜色（103 处，应收敛到令牌）

| 文件 | 数量 | 性质 |
|---|---:|---|
| ConfigWizard.vue | 38 | 向导表单 + 连接状态徽标 |
| SettingsView.vue | 25 | 设置表单 + 健康状态 |
| StatusView.vue | 15 | 展示型 Dashboard 状态色 |
| UpdateChecker.vue | 15 | 更新状态徽标 |
| McpServersPanel.vue | 4 | 健康点 |
| NavRail / TodayView / NotificationCenter / TaskComposer / StatusBar | 各 1–2 | 零星 |

高频值：`#fff`(15)、`#1a1b1e`(8)、`#e5e6e8`(8)、`#2e7d32`(7)、`#b71c1c`(7)、`#9a9b9e`(7)、`#c0c1c4`(6)。集中在四个"表单+状态徽标"页面，中性灰与红绿状态色两套均未走令牌。**D1 建立语义令牌后，D4 迁移时清零。**

### 2.2 硬编码字号（135 处）

- 小字号占 83%：10px×38、12px×26、13px×16、14px×15、11px×9、9px×8；
- 大字号为空状态标题：30/34px（Learning/Project）、32px（Settings）、22–28px 零散；
- 结论：需要 `meta(11–12) / compact(13) / body(14) / section(16–18) / page-title(22–24) / display(28–32)` 六级语义字号覆盖全部场景，9/10px 用法归并入 meta。

### 2.3 z-index（14 处，无 9999 滥用）

局部 0–2（AgentActivityFeed/AgentPlan/Today/TaskWorkspace）、浮层 100（CodingWorkflow/Collection/DocumentCompare/Knowledge/Learning 授权对比类）。需统一映射到 `--z-base/raised/inspector/overlay/toast` 五级。

### 2.4 组件规模（Top 10，行数）

| 文件 | 行数 | 处置方向 |
|---|---:|---|
| TodayView.vue | 2007 | D4 首批拆分：概览/收件箱/提醒/简报分区组件化 |
| LearningWorkspace.vue | 1328 | D4 迁移，业务状态与布局解耦 |
| TaskWorkspace.vue | 978 | D4 迁移，工作流可视化保留为独立组件 |
| App.vue | 949 | D2 拆分：会话/SSE/审批/兼容逻辑移入 composable |
| CodingWorkflowPanel.vue | 928 | D4 迁移 |
| ProjectWorkspace.vue | 795 | D4 迁移 |
| KnowledgeView.vue | 735 | D4 迁移 |
| SettingsView.vue | 734 | D4 迁移 + 硬编码颜色清零 |
| MemoryWorkspace.vue | 686 | D4 迁移 |
| CollectionWorkspace.vue | 668 | D4 迁移 |

### 2.5 视图与信息架构现状

`View` 联合类型 12 项：`chat / today / kb / projects / learning / tasks / memory / settings / diagnostics / extensions / integrations / backup`。

现状问题：NavRail 分为"主要 5 + 更多 7"两组，分组依据是功能清单而非用户任务；"设置/诊断/备份"维护入口与日常入口混排；页面标题映射散落在 `App.vue` 的 switch 中。

### 2.6 动效现状

| 模块 | 现状 | 问题 |
|---|---|---|
| page.ts | logo 420ms、hero 560ms、卡片 480ms(stagger 55)、新增 420ms；hover y-6 + scale 1.02（260/360ms） | 页面入场超过 320ms 预算；hover 位移/缩放对高密度工作台过大 |
| chat.ts | 消息入场 300–360ms、流式 150ms | 符合 Fast/Standard 档，保留 |
| agent.ts | 循环呼吸 620–2600ms | 低振幅循环可用，需保留 reduced-motion 旁路（已有） |
| workflow.ts | 连线 520ms、粒子 1180ms 循环、大脑 1700ms | 粒子/大脑属装饰性循环，D5 降频或改为状态驱动 |

清理机制：四模块 MutationObserver + destroy 完整，无残留风险。

## 3. 核心问题确认（与计划 §2.2 对齐）

1. **信息架构**：12 个一级视图无任务导向分组，维护入口混排 —— 确认，D2 用视图注册表 + 6 分组解决。
2. **视觉断层**：StatusView/TodayView 展示卡风格 vs Settings 表单风格 vs Chat 工作台风格，密度与标题层级不统一 —— 确认，D1 统一页面层级原语，D4 逐页套用。
3. **交互语言**：运行/等待/失败/停止/审批已有 `TASK_STATE_META` 等映射但只在 chat 顶栏使用，未贯穿所有页面 —— 确认，D1 状态映射组件化，D3/D4 铺开。
4. **右栏能力**：InspectorPanel 已有 files/context/artifacts 三 tab，但仅 chat 可用且缺 Sources —— 确认，D3 扩展为 Files/Context/Sources/Artifacts 四 tab 并与任务绑定。
5. **前端结构**：App.vue 承担启动/会话/SSE/审批/导航/覆盖层 6 类职责 —— 确认，D2 拆分。
6. **UI 状态展厅缺失**：很多状态只能靠真实接口复现 —— 确认，D1 建 UI Lab。

## 4. 信息架构冻结（D0 决议）

一级导航 6 分组（工作入口 5 + 系统 1），`View` 联合类型不变，仅重组分组与元数据：

| 分组 | 视图 | 说明 |
|---|---|---|
| 日常 | `today` 今日 | 简报、待办、收件箱、继续工作 |
| 执行 | `chat` Agent | 会话、计划、活动流、审批、结果、产物 |
| 工作 | `projects` 项目、`tasks` 任务 | 项目、任务、目标、代码工作区 |
| 知识 | `kb` 知识库、`learning` 学习、`memory` 记忆 | 文档、集合、学习资料、记忆 |
| 连接 | `integrations` 集成、`extensions` 扩展 | 本地集成、MCP、扩展注册表 |
| 系统（底部） | `settings` 设置、`diagnostics` 诊断、`backup` 备份 | 维护型入口，含运行状态 |

决议依据：计划 §4.1 建议与现有 12 视图一一映射，无功能下线；学习/记忆归入知识区符合"知识库含记忆与学习资料"的定义；系统区沉底与日常工作入口分离。

## 5. 视觉方向决议（D0 决议）

在三个候选方向中选定 **方向 A：Calm Workbench 2.0（演进式）**，理由：

- 方向 B（深色玻璃 Dashboard 全面铺开）与"内容优先、避免大面积高亮"原则冲突，且深色主题未达可发布状态；
- 方向 C（彻底重绘的编辑器式极简）推翻现有资产过多，违背"保留演进"约束，回归风险高；
- 方向 A 在现有浅色生产力基调上收敛：青蓝仅作交互/状态强调，导航保持深青灰品牌区，统一六级字号与 4/8 间距节奏，卡片 hover 收敛到 0–2px，页面入场收敛到 180–240ms。

冻结项：

1. 浅色主题为唯一首轮交付主题；深色仅在全部核心页面验收后开放；
2. 六级语义字号：display 28–32 / page-title 22–24 / section 16–18 / body 14 / compact 13 / meta 11–12；
3. 间距 4px 基础单位，页面外边距 20/24/32，卡片内边距 12/16/20；
4. 动效四档：Instant 80–120 / Fast 120–180 / Standard 180–240 / Deliberate 240–320，页面切换不超 320ms；
5. 状态语义色：成功/等待/危险/信息独立于青色，对比度达 WCAG AA。

## 6. 页面迁移顺序冻结（D4 执行序）

按风险与依赖排序，每页迁移同步完成状态/键盘/窄窗口/测试：

1. `today`（首屏，验证页面层级原语）
2. `kb`（知识库，验证列表+浮层模式）
3. `projects` + `tasks`（验证工作区与可视化保留）
4. `learning` + `memory`（验证左右分栏模式）
5. `integrations` + `extensions`（验证表单面板模式）
6. `settings` + `diagnostics` + `backup`（系统页收尾，清零硬编码颜色大户）

## 7. 改造前截图基线

已存在根目录证据（`design-implementation-*-1536x1024.png` 等 14 张，覆盖 1280/1440/1536 宽度与聊天/工作台/产物页），作为改造前基线归档引用；D6 视觉快照矩阵将以同视角重拍对比。新增截图在 D2 新壳落地后由 Playwright `toHaveScreenshot` 基线化。

## 8. D0 退出条件核对

- [x] 产品方向、一级导航、核心 Agent 工作区和页面迁移清单获得确认（§4–§6）
- [x] 所有核心状态均有真实 fixture 或可重复生成方式（`src/dev/uiStateFixtures.ts`，见状态矩阵）
- [x] 审计量化数据归档（§2）
- [x] 改造前截图基线确认（§7）
