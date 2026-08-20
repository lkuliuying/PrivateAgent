# PrivateAgent Coding Agent 重构计划

> 状态：Draft（观察策略已于 2026-08-20 调整）
> 日期：2026-08-20
> 目标版本：下一主版本
> 适用范围：Tauri 桌面端、FastAPI sidecar、AgentRuntime、项目与工具系统
> 观察策略：[观察期顺延决策](./releases/observation-policy-20260820.md)

## 1. 执行结论

本次重构不采用推倒重写。保留现有 Tauri 2、Vue 3、FastAPI、MySQL、AgentRuntime、工具审批、执行恢复和发布体系，将产品从“包含 Agent 页面的本地私人助手”收敛为“以项目、工作区和任务会话为核心的本地 Coding Agent”。

重构重点不是重新实现模型调用或工具框架，而是完成以下五项收敛：

1. 产品信息架构从多功能工作台调整为 `Project → Workspace → Thread → Run`。
2. 前端不再参与 Agent 决策循环，只负责创建运行、订阅事件、投影状态和提交用户意图。
3. 会话和 AgentRun 必须绑定明确的项目、工作区、Git 状态、模型与权限快照。
4. 执行计划、工具状态、Diff、命令结果和最终报告均来自后端事实源。
5. 新 Coding Agent 主链路稳定后默认隔离旧 UI 和旧 planner 双轨；物理删除在 `v1.0.0` stable 之后另行实施。

预计工作量：

- 单人全职：约 8–11 周。
- 两名熟悉项目的工程师：约 6–8 周。
- 可用 MVP：约 5–7 周，自动化、插件市场和装饰性功能后置。

## 2. 背景与现状

### 2.1 可复用资产

项目已经具备较完整的可信执行底座：

- Tauri 2 + Vue 3 + Vite + TypeScript 桌面应用。
- FastAPI sidecar 与本地 API 安全边界。
- 可持久化、可取消、可恢复的 AgentRun。
- 工具输入输出 Schema、能力策略、风险分级和审批。
- 审批防重放、参数哈希、执行 claim、幂等与结果验证。
- 项目授权、代码搜索、文件读取、Git 状态与 Diff。
- 补丁、白名单命令、流式输出和审批恢复。
- Python、Vitest、Playwright、Rust 和发布检查体系。

因此，下列组件原则上保留演进：

- `src/personal_assistant/agents/`
- `src/personal_assistant/llm/`
- `src/personal_assistant/context/`
- `src/personal_assistant/core/code_tools.py`
- `src/personal_assistant/core/*_workflow.py`
- `src/personal_assistant/api/routes_agent_runs.py`
- `apps/desktop/src/design/`
- Tauri sidecar、认证、凭据、更新与诊断体系

### 2.2 当前主要问题

| 现状 | 影响 | 目标状态 |
|---|---|---|
| 产品以“私人助手多工作区”为中心 | Coding Agent 只是一级入口之一 | Coding Agent 成为产品主线 |
| Session 没有项目和 workspace 归属 | 任务、路径、分支和权限上下文不稳定 | Thread 显式绑定 ProjectWorkspace |
| AgentRun 只绑定 session | 无法审计具体代码根、HEAD 和权限 | 每次 run 保存不可变执行快照 |
| 前端根据消息推导四步计划 | 展示进度可能与真实运行不一致 | 后端持久化计划并发布 plan 事件 |
| `App.vue` 处理 planner、流、审批和续跑 | UI 和执行循环耦合 | 前端只做事件投影和用户操作 |
| v1/v2 UI 双轨仍存在 | 维护成本高，状态路径重复 | 新壳验收后删除旧壳 |
| `api.ts` 和 `types.ts` 过大 | 领域边界模糊，修改容易互相影响 | 按 coding 领域拆分 API 和契约 |
| Coding feature flag 默认关闭 | 能力存在但不是默认产品路径 | 分阶段启用并建立发布门禁 |

相关实现位置：

- `apps/desktop/src/App.vue`
- `apps/desktop/src/models/agentWorkspace.ts`
- `apps/desktop/src/features/agent/AgentWorkspace.vue`
- `apps/desktop/src/api.ts`
- `apps/desktop/src/types.ts`
- `src/personal_assistant/api/routes_agent_runs.py`
- `src/personal_assistant/core/models.py`
- `src/personal_assistant/config.py`

## 3. 产品范围

### 3.1 MVP 范围

MVP 必须覆盖：

- 授权和管理本地代码项目。
- 选择项目与工作区后创建任务会话。
- 显示当前 Git branch、HEAD 和 dirty 状态。
- 读取项目指令、搜索文件、读取代码。
- 展示后端真实执行计划和工具活动。
- 生成并预览多文件 Diff。
- 逐次审批或按权限策略执行文件写入。
- 执行受控测试、lint 和 build 命令。
- 展示结构化测试结果和最终变更报告。
- 停止、失败重试、断线恢复和应用重启恢复。
- 选择模型、推理强度和权限模式。

### 3.2 非目标

以下能力不作为 MVP 发布阻断项：

- 云端多用户和团队协作。
- GitHub/GitLab PR 自动发布。
- 任意 Shell 或全机器无限制访问。
- 完整 IDE、LSP、调试器和内置终端模拟器。
- 多 Agent 编排。
- 自动化市场和插件商城重做。
- 吉祥物、复杂主题和大规模品牌升级。
- 删除现有知识库、学习、记忆等后端数据。

### 3.3 旧能力处理原则

现有“今日、知识库、学习、记忆、目标、集成”等能力先迁入“更多工作区”或次级入口，不在同一次重构中删除数据库表和 API。

旧能力只有在满足以下条件后才能进入物理清理版本：

1. 新 Coding Agent 主链路已默认启用。
2. `v1.0.0-rc.1` 最终 14 天观察中，对应兼容调用归零或全部有明确解释。
3. 数据导出、迁移或归档策略已经明确。
4. 发布检查与回滚演练已经通过。

## 4. 目标信息架构

### 4.1 一级入口

建议将桌面端一级入口收敛为：

- 新建任务
- 搜索
- 自动化
- 扩展
- 项目与最近任务
- 账户、设置和诊断

自动化和扩展入口可以先复用现有能力；如果尚未具备真实内容，应隐藏或明确标记为预览，不提供无功能的假入口。

### 4.2 左侧栏层级

```text
项目
├── Agent
│   ├── main
│   │   ├── 修复运行时恢复问题
│   │   └── 重构审批组件
│   └── agent/new-shell
│       └── 实现新工作台
└── AnotherProject
    └── main
        └── 暂无任务
```

侧栏需要支持：

- 项目展开和折叠。
- 当前 workspace/branch 显示。
- 会话状态、未决审批和运行状态标记。
- 最近更新时间。
- 任务归档、重命名和搜索。
- 大量任务下的分页或虚拟化。
- 窄窗口折叠和键盘导航。

### 4.3 首页

首页对应空任务状态：

- 居中问候和主输入框。
- 输入前必须选择项目和 workspace。
- 输入框支持 `@文件`、`@目录` 和 `/命令`。
- 底部展示权限模式、模型、推理强度和发送按钮。
- 推荐任务只保留 3–4 个真实可执行模板。
- 项目未授权、Provider 未配置、sidecar 未就绪时给出直接操作入口。

### 4.4 任务页

任务页由五个区域组成：

1. 顶栏：任务标题、项目、workspace/branch、Git 状态和全局操作。
2. 主区：用户需求、Agent 回复、工具活动、Diff、命令输出和最终报告。
3. 计划浮层：真实计划进度和当前步骤。
4. 上下文抽屉：Files、Context、Sources、Artifacts。
5. 底部输入器：继续指令、附件、权限、模型、推理强度和停止按钮。

Files、Context 和 Artifacts 不应长期占据主工作区宽度。默认使用可折叠抽屉；计划面板可采用右上浮层，并允许固定展开。

## 5. 目标领域模型

### 5.1 核心关系

```text
Project
  └── ProjectWorkspace（项目根目录或 Git worktree）
        └── Session / CodingThread
              └── AgentRun
                    ├── RunPlanItem
                    ├── RunStep
                    ├── RunEvent
                    ├── ToolApproval
                    ├── ToolExecution
                    └── Artifact
```

### 5.2 ProjectWorkspace

`ProjectWorkspace` 表示一次 coding task 实际可以访问的代码根。项目根目录也是一个 workspace；未来可以增加隔离 Git worktree。

建议字段：

| 字段 | 说明 |
|---|---|
| `id` | 稳定主键 |
| `project_id` | 所属项目 |
| `kind` | `root` 或 `git_worktree` |
| `root_path` | 解析后的绝对路径 |
| `branch_name` | 当前分支 |
| `base_ref` | 创建 worktree 时的基线引用 |
| `head_sha` | 最近确认的 HEAD |
| `status` | active、missing、dirty、archived、conflict |
| `last_used_at` | 最近使用时间 |
| `created_at/updated_at` | 审计时间 |

每次运行必须重新确认路径、Git 状态和授权边界，不能仅依赖数据库中的历史值。

### 5.3 Session / CodingThread

建议对现有 `sessions` 表做增量扩展：

- `project_id`
- `workspace_id`
- `kind`，默认 `coding`
- `pinned_at`
- `archived_at`
- `last_run_id`

旧会话这些字段保持为空，并通过兼容入口继续访问。

### 5.4 AgentRun

建议对 `agent_runs` 增加：

- `project_id`
- `workspace_id`
- `base_head_sha`
- `model_profile_id`
- `reasoning_effort`
- `permission_snapshot_json`
- `client_request_id`

`project_id` 和 `workspace_id` 同时写入 session 与 run：session 表示长期归属，run 表示执行时不可变快照。

`client_request_id` 用于创建幂等，避免网络重试创建两次任务。

### 5.5 RunPlanItem

当前前端启发式四步计划应替换为后端事实模型。

建议字段：

- `run_id`
- `plan_version`
- `item_id`
- `ordinal`
- `title`
- `status`
- `detail`
- `evidence_json`
- `started_at`
- `completed_at`

状态建议限制为：

- `pending`
- `in_progress`
- `completed`
- `blocked`
- `failed`
- `cancelled`

同一计划版本最多允许一个 `in_progress` 项。

### 5.6 Artifact

Artifact 是 UI 可展示、可恢复的产物投影，建议覆盖：

- 文件 Diff
- 测试报告
- lint/build 报告
- 命令输出摘要
- 修改文件列表
- 最终 Markdown 报告
- 导出文件

原始敏感输出继续由 `ToolExecution` 保存并执行脱敏、限长；Artifact 只保存面向用户的有界内容和引用。

## 6. 后端重构

### 6.1 Project-bound AgentRun

扩展创建请求：

```json
{
  "session_id": 123,
  "project_id": 8,
  "workspace_id": 12,
  "message": "修复测试失败",
  "model_profile_id": "local-coder",
  "reasoning_effort": "high",
  "permission_mode": "workspace",
  "client_request_id": "uuid"
}
```

创建时必须：

1. 校验 session、project 和 workspace 的归属。
2. 解析真实路径并确认仍在授权根内。
3. 检查符号链接、重解析点和路径穿越。
4. 读取 branch、HEAD 和 dirty 状态。
5. 装载项目指令和模型能力。
6. 固定本次 run 的模型、权限和执行限制。
7. 通过 `client_request_id` 去重。

### 6.2 Coding Agent 系统配置

将通用私人助手提示调整为 Coding Agent profile，至少包含：

- 当前项目和 workspace。
- 操作系统、主要语言和框架。
- Git branch、HEAD 和 dirty 状态。
- 项目级指令与用户级指令。
- 权限模式和禁止项。
- 工具能力及使用约束。
- 验证与完成条件。
- 外部内容不可信声明。

项目指令按以下顺序发现：

1. 应用内用户级 Coding Agent 指令。
2. workspace 根目录的 `AGENTS.md`。
3. 从根目录到目标文件路径上的更具体 `AGENTS.md`。
4. 项目配置文件中的补充规则。
5. README 和构建配置只作为不可信项目资料，不得提升权限。

### 6.3 真实计划系统

新增内部安全工具：

```text
update_run_plan(
  items: [{ id, title, status }],
  explanation?: string
)
```

该工具：

- 不产生外部副作用。
- 将计划写入 `run_plan_items`。
- 发布 `plan.created`、`plan.updated`、`plan.item_changed` 事件。
- 校验 item id、顺序、状态和并发版本。
- 不把模型声明的“完成”直接当作可信验收结果。

计划项完成后仍需要执行结果、文件哈希、测试或 completion verifier 作为证据。

### 6.4 统一事件流

目标接口：

```text
POST /agent-runs
GET  /agent-runs/{run_id}
GET  /agent-runs/{run_id}/events?after_sequence=N
GET  /agent-runs/{run_id}/events/stream?after_sequence=N
POST /agent-runs/{run_id}/cancel
POST /agent-runs/{run_id}/approvals/{approval_id}/approve
POST /agent-runs/{run_id}/approvals/{approval_id}/reject
```

稳定事件集合建议包括：

- `run.started`
- `context.prepared`
- `plan.created`
- `plan.updated`
- `model.started`
- `model.completed`
- `tool.requested`
- `tool.approval_required`
- `tool.approval_resolved`
- `tool.started`
- `tool.output_available`
- `tool.completed`
- `tool.failed`
- `artifact.created`
- `verification.started`
- `verification.completed`
- `run.completed`
- `run.failed`
- `run.cancelled`

Token delta 可以作为临时流事件，不逐 token 入库。完整模型结果必须持久化；重连时前端用 run 快照覆盖未完成的临时文本，并从最后 durable sequence 继续。

### 6.5 Coding Context

ContextBuilder 增加 Coding 上下文源：

- 当前 project/workspace 元数据。
- Git branch、HEAD 和 dirty 摘要。
- 项目指令。
- 当前用户请求。
- 未完成计划和工具调用。
- 最近对话窗口。
- 明确 `@` 引用的文件。
- 搜索或工具返回的代码片段。
- 旧会话摘要和相关记忆。

上下文预算原则：

1. 安全策略、当前请求和未完成工具上下文不可丢弃。
2. 显式 `@` 引用优先于自动召回。
3. 代码片段必须保留路径、行号、哈希和来源。
4. 不默认发送整个仓库或未授权文件。
5. 远程 Provider 必须遵守用户的数据外发设置。

## 7. Coding 工具体系

### 7.1 MVP 工具

保留并强化：

- `search_files`
- `grep_code`
- `read_code_file`
- `get_git_status`
- `get_git_diff`
- `propose_patch`
- `apply_patch_to_workspace`
- `run_whitelisted_command`

### 7.2 新增工具

建议新增：

- `list_directory`
- `read_file_range`
- `apply_patch_set`
- `create_file`
- `delete_file`
- `move_file`
- `get_project_instructions`
- `list_project_commands`
- `run_project_command`

其中创建、删除、移动可以作为 `apply_patch_set` 的结构化操作，而不是多个自由工具。

### 7.3 多文件补丁

`apply_patch_set` 至少需要：

- 多文件 create/update/delete/rename。
- 每个文件的旧内容 SHA-256。
- run 创建时的 `base_head_sha`。
- 统一 Diff 预览。
- 总文件数、总字节数和 Diff 大小限制。
- 写入前全量校验，避免半写入。
- 失败后的回滚或明确 partial 状态。
- 写入后回读验证。
- 产出结构化 Artifact。

### 7.4 命令执行

命令仍使用参数数组，不经过 shell。项目 command profile 应声明：

- 固定 executable。
- 可接受参数模式。
- 工作目录。
- 超时。
- 环境变量白名单。
- 输出上限。
- 是否允许网络。
- 结果解析器。
- 风险级别。

MVP 优先支持测试、lint、类型检查和 build；不提供任意交互式终端。

### 7.5 Git 与 worktree

MVP 只需显示现有 branch 和 HEAD，不自动创建分支。

后续支持隔离 workspace 时：

- worktree 创建由应用服务使用固定 Git 参数执行。
- 创建前显示路径、分支和基线提交。
- 检查 dirty 状态和同名分支。
- workspace 删除必须单独确认。
- 模型不能通过自由命令创建或删除 worktree。

## 8. 权限与模型

### 8.1 权限模式

建议提供：

1. `readonly`：只读、搜索和查看 Git。
2. `confirm`：读取自动；写入和命令逐次确认。
3. `workspace`：允许当前 workspace 内的授权写入和项目命令 profile。

不建议直接使用含义不清的“完全访问”。即使在 workspace 模式下，以下操作仍需再次确认或默认拒绝：

- workspace 外文件访问。
- 大量删除或覆盖。
- 任意网络请求。
- 系统配置和凭据读取。
- 自定义 Shell。
- 部署、发布、提交远程仓库。

每次 AgentRun 保存权限快照；运行期间修改权限只影响后续工具调用，不能追溯扩大已有审批。

### 8.2 模型能力

后端提供模型 profile API，返回：

- Provider 和模型名。
- 本地或远程。
- 是否支持原生工具调用。
- 是否支持流式、视觉和结构化输出。
- 上下文长度。
- 支持的推理强度。
- 使用量和成本能力。

前端只保存 profile id，不接触 API key。

不支持原生工具调用的模型只能进入只读问答模式，不回退旧文本 JSON planner。

## 9. 前端工程重构

### 9.1 技术原则

- 保持 Vue 3、`<script setup lang="ts">` 和当前视图状态切换。
- 不为本次重构新增 Vue Router、Pinia、Tailwind 或大型组件库。
- 继续使用 `tokens.css`、`components.css` 和 `pa-*` primitives。
- 所有 HTTP、Tauri invoke、文件选择和系统操作通过 API/service 层。
- SSE、轮询、AbortController、定时器和监听器必须在切换线程或卸载时清理。

### 9.2 建议目录

```text
apps/desktop/src/
├── features/coding/
│   ├── api/
│   │   ├── threads.ts
│   │   ├── runs.ts
│   │   ├── projects.ts
│   │   └── models.ts
│   ├── model/
│   │   ├── contracts.ts
│   │   ├── runProjector.ts
│   │   └── codingWorkspaceStore.ts
│   ├── composables/
│   │   ├── useRunStream.ts
│   │   ├── useThreadSelection.ts
│   │   └── useComposer.ts
│   └── components/
│       ├── CodingHome.vue
│       ├── CodingSidebar.vue
│       ├── CodingThreadWorkspace.vue
│       ├── ThreadHeader.vue
│       ├── RunTranscript.vue
│       ├── RunPlanPopover.vue
│       ├── ToolEventCard.vue
│       ├── DiffArtifact.vue
│       └── CodingComposer.vue
```

### 9.3 App.vue 收敛

`App.vue` 最终只负责：

- 启动流程和 sidecar 状态。
- 当前产品视图和线程选择。
- 工作台壳挂载。
- 全局快捷键。
- Toast、确认、命令面板和搜索等全局 overlay。

以下逻辑迁出：

- 消息拼接。
- planner 选择。
- 工具执行决策。
- 审批后续跑。
- run event 解析。
- run 恢复。
- 项目和上下文轮询。

### 9.4 API 与类型拆分

逐步拆分现有 `api.ts`：

- `api/http.ts`
- `api/runtime.ts`
- `api/sessions.ts`
- `api/projects.ts`
- `api/agentRuns.ts`
- `api/modelProfiles.ts`
- `api/automations.ts`
- `api/extensions.ts`

逐步拆分 `types.ts`：

- `contracts/session.ts`
- `contracts/project.ts`
- `contracts/workspace.ts`
- `contracts/agentRun.ts`
- `contracts/approval.ts`
- `contracts/artifact.ts`
- `contracts/modelProfile.ts`

不要一次性机械移动所有文件；按调用方迁移并保持每个提交可构建。

### 9.5 Run Projector

`runProjector` 是前端唯一的运行投影入口：

- 按 `(run_id, sequence)` 幂等消费 durable event。
- 拒绝旧 run 事件写入当前 thread。
- 将事件投影为 transcript、plan、tool card、approval 和 artifact。
- 临时 token delta 与 durable 结果分离。
- 重连后用快照纠正临时状态。
- 不从文案或消息数量猜测执行状态。

### 9.6 视觉方向

参考 UI 使用低饱和中性色、紧凑侧栏和文档式主区。项目应吸收以下特点：

- 浅色中性背景和弱边框。
- 风险与权限使用橙色或警告色，不作为品牌主色泛滥。
- 主区减少漂浮卡片堆叠。
- 工具活动默认折叠摘要，错误、审批和 Diff 保持醒目。
- 计划浮层可扫描但不遮挡正文。
- 长命令输出和 Diff 有独立滚动、复制和展开入口。
- 适配 1280、1440、1920 宽度以及 125%/150% Windows 缩放。

## 10. 核心数据流

```text
选择项目/workspace
  → 创建或打开 CodingThread
  → POST /agent-runs
  → 保存 workspace、HEAD、模型和权限快照
  → 订阅 durable event + 临时 delta
  → runProjector 更新 transcript/plan/tool/artifact
  → 工具需要审批时暂停
  → 用户批准或拒绝
  → Runtime 从 checkpoint 续跑
  → 执行验证和完成条件
  → 保存最终报告与 artifact
```

断线恢复：

```text
SSE 断开
  → 保留 active run id 和最后 sequence
  → 指数退避重连
  → GET run 快照
  → GET events?after_sequence=N
  → 用 durable 状态替换临时文本
  → 继续订阅
```

## 11. 分阶段实施

### M0 · 范围冻结与基线（2–3 天）

工作项：

- 冻结 Coding MVP 与非目标。
- 输出页面状态图和核心用户流程。
- 记录当前 UI、API、数据库和测试基线。
- 建立旧能力保留/迁移/删除清单。
- 定义 feature flag 与回滚策略。

验收：

- 产品范围不再变动。
- 主链路和关键 DTO 完成评审。
- 当前测试和构建结果已记录。

### M1 · 契约与数据模型（4–6 天）

工作项：

- 新增 `project_workspaces`。
- 增量扩展 sessions 和 agent_runs。
- 新增 plan item 和 artifact 契约。
- 扩展前后端 DTO。
- 为旧数据提供兼容读取。
- 编写迁移、回滚和数据一致性测试。

验收：

- 旧会话、项目和 run 可继续读取。
- 新字段可空，旧版本不会因 schema 变化崩溃。
- 迁移在空库、测试库和主库副本通过。

### M2 · Runtime 主链路（5–7 天）

工作项：

- 实现 project-bound AgentRun。
- 接入 Coding Context。
- 增加 `update_run_plan`。
- 增加 plan/artifact 事件。
- 提供可续读事件流。
- 完善取消、审批恢复和重连语义。

验收：

- 前端不再把工具结果拼成新的用户请求。
- 运行刷新或 SSE 断开后可恢复。
- 计划状态来自后端事实。

### M3 · Coding 工具闭环（7–10 天）

工作项：

- 强化只读代码工具。
- 实现多文件补丁。
- 接入项目 command profile。
- 结构化测试、lint 和 build 结果。
- 接入领域 verifier。
- 生成 Diff 和测试 Artifact。

验收：

- 能完成“读取 → 修改 → 测试 → 报告”任务。
- 写入前后哈希与 HEAD 校验通过。
- 超时、取消和进程树清理可验证。

### M4 · 前端数据层（4–6 天）

工作项：

- 拆分 coding API 和 contracts。
- 实现 `runProjector`。
- 实现 `useRunStream`。
- 实现线程选择和恢复 store。
- 处理快速切换线程、旧响应和重复事件。

验收：

- 切换、刷新、停止和重连不产生幽灵状态。
- 所有副作用在卸载和切换时正确清理。
- projector 和 composable 有独立单元测试。

### M5 · 新工作台 UI（6–9 天）

工作项：

- 实现 CodingSidebar。
- 实现 CodingHome。
- 实现 CodingThreadWorkspace。
- 实现计划浮层、工具卡片、Diff 和 Artifact。
- 实现新输入器、`@` 引用和 `/` 命令。
- 改造上下文抽屉。
- 完成空态、错误态、加载态和窄窗口适配。

验收：

- 参考图的主要信息架构和交互层次已经落地。
- 1280/1440/1920 与 125%/150% 缩放通过。
- 键盘导航和可访问性检查通过。

### M6 · 权限与模型（4–6 天）

工作项：

- 实现三种权限模式。
- 保存 run 权限快照。
- 接入模型 profile 和推理强度。
- 优化审批影响范围、Diff 和命令预览。
- 完善 Provider 未就绪和模型能力不兼容状态。

验收：

- 越权默认拒绝。
- 权限切换不修改历史审批范围。
- 模型能力不通过名称猜测。

### M7 · 切换、清理与发布（5–8 天）

工作项：

- 默认启用新 Coding UI。
- 保留短期回滚 flag。
- 观察旧 planner 和旧 UI 使用计数。
- 默认隔离旧壳和旧 planner，仅删除不影响回退与历史数据读取的重复组件。
- 完成性能、安全、恢复和发布测试。
- 更新需求、架构、使用和发布文档。

验收：

- 新主链路默认稳定。
- 最终观察期间旧 planner 非预期调用归零，显式回退调用可审计。
- 全套发布门禁与回滚演练通过。

### 11.1 关键路径

```text
M0 → M1 → M2 → M4 → M5 → M7
            └→ M3 ───────┘
                 └→ M6 → M7
```

M3 可以在 M1 契约冻结后与 M4/M5 的部分前端工作并行，但最终 E2E 必须在 M2、M3、M5 和 M6 全部完成后执行。

## 12. 测试与验收

### 12.1 后端契约测试

- project/workspace/session/run 归属校验。
- 创建幂等。
- event sequence 唯一和续读。
- plan 乐观并发与状态约束。
- 审批参数替换、过期、重放和并发消费。
- Patch SHA、HEAD 漂移、路径穿越和符号链接越界。
- 多文件补丁失败与回滚。
- 命令超时、取消和残留进程检测。
- run crash/restart/reconcile。
- Artifact 脱敏与限长。

### 12.2 前端单元测试

- run projector 幂等与乱序保护。
- 切换 thread 后旧事件丢弃。
- 临时 delta 被 durable 快照替换。
- plan、approval、tool 和 artifact 状态映射。
- 输入器发送、停止、权限和模型状态。
- SSE 重连与 AbortController 清理。
- 大量 transcript item 渲染策略。

### 12.3 E2E 场景

必须覆盖：

1. 授权项目并创建任务。
2. 读取代码并生成计划。
3. 生成多文件 Diff，批准后写入。
4. 执行测试并展示结果。
5. 拒绝审批后正确结束或调整方案。
6. Agent 运行中取消。
7. SSE 中断后恢复。
8. 应用关闭并重启后恢复等待审批 run。
9. Git HEAD 改变时拒绝过期补丁。
10. Provider 未配置或模型不支持工具调用。

### 12.4 视觉与可访问性

分辨率和缩放：

- 1280×720
- 1440×900
- 1920×1080
- Windows 125%
- Windows 150%
- 窄窗口折叠态

检查项：

- 主区不出现双滚动条。
- 底部输入器不遮挡 transcript。
- 浮层不遮挡关键审批。
- 长标题、路径、Diff 和命令输出可用。
- icon-only 控件具有 `aria-label`。
- 关键操作不依赖 hover。
- Reduced Motion 下没有强制循环动效。

### 12.5 性能目标

建议目标：

- 缓存线程切换的首屏反馈小于 150 ms。
- 普通 run event 投影不阻塞输入。
- 5,000 条活动记录仍可滚动和搜索。
- Token delta 合批更新，不逐 token 触发全树渲染。
- 非活动 thread 不保留 SSE、轮询和大块输出缓冲。
- 工具输出和 Diff 按需加载。

## 13. 发布与迁移策略

### 13.1 Feature flag

建议短期使用：

- `PA_CODING_AGENT_UI_ENABLED`
- `PA_PROJECT_BOUND_RUNS_ENABLED`
- `PA_AGENT_PLAN_EVENTS_ENABLED`
- 现有各工具工作流开关

前端不要再增加长期存在的 `ui_v3`。可以复用现有 v2 壳逐步替换内容；切换完成后先默认隔离旧兼容分支，物理删除遵循最终观察后的独立版本计划。

### 13.2 上线顺序

1. 发布 additive schema，功能保持关闭。
2. 开启 project-bound run 和事件契约，但不切默认 UI。
3. 内部启用 Coding UI，完成真实项目演练。
4. 默认启用 Coding UI，保留回滚开关。
5. 全部功能、文档和发布物完成后冻结 `v1.0.0-rc.1`，观察旧 planner、旧审批和旧 UI 调用 14 个自然日。
6. 最终观察通过后发布 `v1.0.0` stable；兼容路径的物理删除进入后续独立版本。

### 13.3 回滚

回滚必须满足：

- 新字段可空，旧 UI 能忽略。
- 新表不影响旧查询。
- 新 UI 可以关闭但不删除 run 和 artifact 数据。
- 数据库迁移不重命名或删除现有字段。
- 旧版本不应尝试解释新 plan/artifact 数据。

## 14. 风险与控制

| 风险 | 控制措施 |
|---|---|
| UI 显示假进度 | 计划和状态只消费后端 durable event |
| 前后端存在两套 Agent 循环 | 前端移除 planner、工具决策和工具结果二次提交 |
| 补丁覆盖用户新改动 | 校验文件 SHA、workspace 和 Git HEAD |
| worktree/branch 管理破坏仓库 | 作为应用服务、固定参数、显式确认，MVP 不自动创建 |
| 任意命令扩大攻击面 | command profile、参数数组、默认拒绝、进程树清理 |
| 大规模重构难以回滚 | additive schema、逐模块迁移、每个提交可构建 |
| 长 transcript 导致卡顿 | 事件投影、合批、虚拟化、按需加载输出 |
| 旧功能拖累范围 | 先降级到次级入口，不同步重写或删除后端 |
| 远程模型泄露项目内容 | 显式远程标识、数据外发策略和上下文最小化 |
| feature flag 永久存在 | 为每个 flag 设删除条件和最晚清理版本 |

## 15. MVP 完成定义

MVP 只有在以下主链路完整通过时才算完成：

1. 用户授权本地 Git 项目。
2. 首页选择项目和 workspace，新建任务。
3. 顶栏显示项目、branch、HEAD 和 dirty 状态。
4. Agent 读取项目指令、搜索并读取代码。
5. 右侧显示后端真实计划。
6. Agent 生成多文件 Diff。
7. 用户查看影响范围并批准。
8. 系统检查文件哈希和 Git HEAD，原子应用补丁。
9. 系统执行授权测试或 lint。
10. 最终报告列出修改文件、验证结果、风险和下一步。
11. 应用重启后仍能恢复任务、计划、审批和输出。
12. 用户拒绝、取消、断线或 Provider 失败时不产生幽灵执行。

同时满足：

- Python、Vitest、Playwright 和 Cargo 检查全绿。
- 路径穿越、审批重放和越权测试全绿。
- 视觉矩阵和键盘可访问性通过。
- 发布检查与回滚演练通过。
- 旧 planner 调用达到约定的清理门槛。

## 16. 第一批实施任务

建议按以下顺序创建开发任务：

1. 编写 Coding Agent 产品 ADR，冻结 MVP 与非目标。
2. 新增 `project_workspaces` 和 session/run 绑定迁移。
3. 扩展 AgentRun 创建 DTO 和执行快照。
4. 新增 plan item 与 `update_run_plan` 内部工具。
5. 实现可续读事件流和前端 `runProjector`。
6. 拆分 `api.ts` 的 projects、sessions、runs 和 models。
7. 实现 CodingSidebar 与项目分组任务列表。
8. 实现 CodingHome 与项目选择输入器。
9. 实现 CodingThreadWorkspace 和真实计划浮层。
10. 实现多文件补丁与 Diff Artifact。
11. 接入白名单测试命令和结果验证。
12. 完成重启恢复、安全和端到端主链路测试。

## 17. 相关文档

- [目标架构](./target-architecture.md)
- [工具系统、权限与审批](./tool-system.md)
- [ContextBuilder 设计](./context-design.md)
- [安全与隐私模型](./security-model.md)
- [测试指南](./testing-guide.md)
- [发布检查清单](./release-checklist.md)
- [项目需求文档](./requirements.md)
