# 更新日志

## 0.4.0-alpha.2（2026-08-08，Workbench UX 2.0 收口 · 开发中）

> 计划：[`docs/releases/v0.4.0/v0.4.0-ui-ux-redesign-plan.md`](docs/releases/v0.4.0/v0.4.0-ui-ux-redesign-plan.md)。

### ui_v2 默认开启（alpha.2 契约切换）
- `src/config/uiFlags.ts`：`DEFAULT_UI_V2 = true`——默认进入新 UI，`?ui=v1` / `pa_ui_v2=0` 回退兼容壳；
- E2E 适配默认壳切换：legacy 动画模块回归测试（`chat.ts`/`agent.ts`）固定 `?ui=v1` 运行；
  共享行为测试（Today/KB/布局溢出）改为壳无关断言（nav testid、heading `.first()`、hover 前先 `scrollIntoViewIfNeeded`）；
- E2E 25/25 通过（默认壳 = v2）。

### Python 运行时修复
- `agents/runtime.py` `_await_with_cancellation`：协程先 `ensure_future` 调度、后做取消检查，
  消除取消窗口内"协程未等待"（`RuntimeWarning: coroutine ... was never awaited`）；
  `-W always::RuntimeWarning` 全量 pytest 零警告，637 passed。

### 令牌收敛
- NavRailV2 / NavRail 4+4 处 RGBA 字面量收敛为组件令牌 `--pa-rail-brand-border/-bg`、
  `--pa-rail-active-border`、`--pa-rail-icon-bg`、`--pa-rail-running-glow`；
  `src/` 组件无新增裸 RGBA/hex。

### D4 · 知识库页面组件化（`features/knowledge/` 首个领域迁移）
- 新增 `DocListItem`：文档行整体拆分（状态徽标/元数据/操作区内聚，focus-visible 补齐）；
- 空态/加载/错误态改用 `PaEmptyState`/`PaErrorState`；KnowledgeView 767 → ~540 行；
- 单测 +4，E2E 知识库窄窗口通过。

### D5 · 包体基线
- 前端生产资源 vs 0.3.0-alpha.2 基线：index gzip +10.6%、vendor +2.2%、合计 +6.2%，**在 ≤15% 门槛内**。

### D6 · 视觉回归矩阵
- `e2e/visual-regression.spec.ts`：5 个 `toHaveScreenshot` 断言基线
  （v2 Agent 1280/1440/1920、今日 1440、v1 回退），确定性采集 + maxDiffPixelRatio 0.02；
  基线已提交，复验通过；更新命令 `--update-snapshots`。

### D4 · 今日视图组件化（`features/today/`）
- 新增 `OverviewCards`（概览卡片）与 `PriorityList`（优先事项/空态引导），
  展示字段父层预计算后传入；TodayView 2057 → ~1980 行；
- 单测 +4；视觉回归基线无变化（样式原样迁移），30/30 通过。

### D4 · 记忆领域迁移（`features/memory/`）
- 新增 `MemoryRow`（列表项）与 `MemoryEditorForm`（新建/编辑表单）；
  MemoryWorkspace 716 → ~580 行；单测 +4。

### D6 · alpha.2 检查点
- 版本统一 `0.4.0-alpha.2`（八处含 package-lock.json，UTF-8 无 BOM），telemetry 测试同步；
- `docs/releases/v0.4.0/v0.4.0-alpha.2-checkpoint-20260808.md`；
- **release-check-full：14/14，绑定 `8c50900`，`worktree_dirty=False`，`installer_built=True`**。

### D4 · 全生产页面验收（验收修复轮）
- `e2e/pages-smoke.spec.ts` 13/13：12 视图导航/主体渲染/空态/无横向溢出/键盘 Tab + 断连错误态；
- `docs/releases/v0.4.0/v0.4.0-alpha.2-function-comparison.md` 完整功能对照表（逐页功能/证据/状态覆盖）。

### D5 · 性能与资源清理（验收修复轮）
- `e2e/performance-resource.spec.ts` 3/3：页面切换长任务 **0 个（p95=0ms）**、
  150 帧 SSE 长流压力、重复切换后定时器 4→4 / 存活监听器 41→41 零残留。

### D6 · 安装/升级/回滚证据（验收修复轮）
- 构建 `PrivateAgent_0.4.0-alpha.2_x64-setup.exe` + `.sig`（updater 签名）；
- `dist/alpha-0.4.0-alpha.2-manifest.json`（installer/sidecar SHA-256，绑定 `8c50900`）、
  `dist/alpha-0.4.0-alpha.2-flags.json`（19 项快照）；
- 实机演练（证据 `dist/alpha-0.4.0-alpha.2-install/`，成对计数文件可审计）：
  0.3.0 → alpha.2 **覆盖升级**（pre/post 计数一致）、**真实降版回滚** alpha.2 → 0.3.0
  （重建自 e6da3ee 的 0.3.0 安装包，归档 `dist/rollback-archive/`）、全新安装（首次启动 smoke）、
  卸载数据保留；四次 DB 快照逐项一致；
- Playwright 累计 47/47（pages-smoke 增加载态断言）。

## 0.4.0-alpha.1（2026-08-08，Workbench UX 2.0 内部检查点 · D0–D2）

> 计划：[`docs/releases/v0.4.0/v0.4.0-ui-ux-redesign-plan.md`](docs/releases/v0.4.0/v0.4.0-ui-ux-redesign-plan.md)；
> 证据：`docs/releases/v0.4.0/v0.4.0-alpha.1-checkpoint-20260808.md`。仅内部 Alpha，不更新普通用户 `latest.json`。

### D0 · 设计审计与范围冻结
- 新增 `docs/releases/v0.4.0/ui-audit-0.4.0.md`：全量 UI 审计（54 组件、103 处硬编码颜色、135 处硬编码字号、动效时长分布、组件规模 Top10）；
- 新增 `docs/releases/v0.4.0/ui-state-matrix-0.4.0.md`：Agent 任务/计划/工具/审批/SSE 恢复/右栏/页面级状态矩阵；
- 新增 `src/dev/uiStateFixtures.ts`：13 个真实公开 DTO fixture（空任务/规划/流式/工具执行/审批/失败/停止/RAG/拒答/重连/产物），与状态矩阵一一对应；
- 信息架构冻结：一级导航 6 分组（日常/执行/工作/知识/连接 + 底部系统），12 视图零下线；
- 视觉方向冻结：Calm Workbench 2.0（浅色主题首轮交付，六级语义字号，动效四档）。

### D1 · 设计系统 2.0
- `tokens.css` 升级为三层令牌（Primitive/Semantic/Component），0.3.0 旧变量全部保留为别名，零破坏；
- 新增 25 个 `pa-*` 基础组件（Button/Input/Textarea/Select/Checkbox/Switch/Field/Badge/StatusIndicator/Spinner/Progress/Tabs/SegmentedControl/Disclosure/Card/EmptyState/ErrorState/Skeleton/InlineNotice/Tooltip/DropdownMenu/Dialog/IconButton/PageHeader），全量覆盖 hover/focus-visible/active/disabled/loading/error；
- 新增 `src/dev/UiLab.vue`（`?ui-lab=1` 开发模式）：全部组件状态 + Agent 13 场景 + 文本/无障碍检查，复用真实组件与 fixture；
- 组件测试 +20（新增 21 项，累计 82 项单测）。

### D2 · 应用壳与信息架构
- 新增类型化视图注册表 `src/models/viewRegistry.ts`（12 视图 × 分组/图标/关键词/壳行为），命令面板改由注册表驱动；
- 新增轻量导航历史 `src/composables/useViewHistory.ts`（返回/前进/恢复上次视图，localStorage 持久化）与全局快捷键 `useShortcuts`（Ctrl/Cmd+K、Ctrl/Cmd+N、Alt+←/→，不覆盖输入编辑）；
- 新增 `AppShell v2`（三栏：分组导航/中央工作区/四 tab 上下文栏）与 `NavRailV2`（视图注册表驱动、系统组沉底）；
- 新增 `ContextRail`：Files/Context/Sources/Artifacts 四 tab，与当前任务绑定，无任务时显示全局占位；
- `ui_v2` 开关（`?ui=v2|v1` / `pa_ui_v2`）：alpha.1 默认兼容壳，新壳按开关启用，回退已验证（Playwright E2E）；
- 启动流程统一：>500ms 才展示加载态；失败页说明依赖/数据影响并提供重试/重新配置/退出；
- E2E +7（新壳分组导航、视图历史、上下文栏、命令面板、回退），累计 22 项。

### D3 · Agent 核心工作流（`features/agent/` 领域完整迁移）
- 统一活动流 `ActivityFeedV2`：用户请求/Agent 正文/工具摘要+折叠/审批卡/错误块/结果块；计划步骤点击定位活动；
- 统一审批卡 `ApprovalCardV2`（Runtime + legacy 工具），原位状态转换与过期/取消/失败恢复提示；
- 长活动流自动跟随 +「有新活动」入口（含异步竞态防护）；停止区分「正在停止…/已停止」；
- 上下文栏接入真实数据（`listActivities` 5s 轮询 + `listTrustedPaths`，切换会话清理定时器）；
- 修复续传回答丢失 RAG sources/memories 的真实缺陷（`continueAgentReply` done 事件未消费来源）；
- 测试 +16（单测 14 + E2E 2：审批→批准→RAG 来源闭环、停止即时反馈）。

### D4 · 业务页面迁移（首批）
- SettingsView/StatusView/ConfigWizard/UpdateChecker/McpServersPanel/NavRail 等全部 103 处硬编码颜色清零（统一走语义/组件令牌）；
- 新增 `PageHeader` 统一页面标题层级（面包屑/标题/状态摘要/操作）。

### D5 · 动效与可访问性
- 动效时长按四档收敛：page 入场 560→280ms、卡片 480→240ms、hover 位移 6px+scale1.02 → 2px 无缩放、chat 消息 360→200ms；E2E 断言更新为新规格；
- 全局 `prefers-reduced-motion` 底线（动效只解释状态，不承载功能信息）；
- 接入 `@axe-core/playwright`：v2 壳 + Agent 工作区 WCAG AA 无严重违规（修复主按钮对比度 → teal-700 白字 5.3:1、meta 文字 fg-subtle 校准 ≥5:1）；
- E2E +2（axe 严重违规扫描、键盘 focus-visible 环）。

## 0.2.1（2026-08-06，稳定化发布候选）

### 数据库（schema `0021`）

- 新增 `compatibility_telemetry` 表（迁移 `0021`）：每进程一个观察窗口的兼容遥测持久化，
  用于跨版本 legacy 归零观察（§6.4）；主库已迁移（克隆 `personal_assistant_preupgrade_20260806070435`
  为 0020 基线），测试库完成 `0020 → 0021 → 0020` 往返演练。

### RAG 无答案拒答（rag-evidence-v1）

- 检索层证据充分性策略：阈值 `PA_RAG_EVIDENCE_MIN_FINAL_SCORE=0.80`、
  `PA_RAG_EVIDENCE_MIN_SINGLE_CHANNEL_SCORE=0.85`（真实语料校准）；无答案 case 稳定拒答
  （reviewed 集 abstention_rate=1.0），已知答案 Recall/MRR/引用正确率保持 1.0、零误拒答；
  拒答返回空来源 + 结构化原因，聊天与 `search_knowledge_base` 工具明确说明资料不足。
- 已知边界：语义反转类干扰（高分双渠道）需语义蕴含级验证（`data/rehearsals/rag-evidence-r2-20260806/`）。

### Ollama 生命周期（外部用户管理模式）

- `/health` 错误分类：`ollama_not_running` / `ollama_timeout` / `ollama_http_error` /
  `ollama_model_missing` + `missing_models`；`scripts/ollama_lifecycle_check.py` 与文档
  `docs/ollama-lifecycle.md`（embed P50 87ms / P95 111ms 实测）。

### Agent Runtime 灰度（批 A）

- 生产配置开启：Agent Runs API、只读工具、ContextBuilder、输出验证、RAG 工具
  （`PA_AGENT_*_ENABLED=true`）；聊天接管与摘要 worker 保持关闭。
- 取消清理：git/命令子进程 CancelledError 时 kill、grep to_thread stop_event 退让、
  SSE 断线取消、owner 监控 verify→shutdown；预算口径统一（旧聊天历史按 context length 截断、
  安全系数 `PA_TOKEN_ESTIMATE_SAFETY_FACTOR=2.0`，真实 usage 抽样校准 5/5 项 ≥ 真实值）。

### 领域级结果验证器（R4）

- 6 类验证器（文件 Diff / 代码 / Shell / API / 数据库 / 多步骤完成条件）+ 组合器；
  文件 Diff 已接入 `propose_patch` 真实工作流；失败写 durable `agent_tool_executions`
  并给有界反馈，不消费审批。

### 已知限制与回滚

- 安装包 unsigned（SmartScreen 风险）；GitHub Release 未发布（无权限），仅本地候选验收。
- 观察期：兼容遥测窗口自 2026-08-06 起积累，§6.4 legacy 归零判定尚未达成。
- 回滚：删除 `PA_*` 开关行即可回退灰度；数据库回滚非必要（0021 为纯新增表，旧应用可忽略）。

## 0.2.0（2026-08-06 发布门禁收口）

### 发布事实源与门禁（R0/R1，对应 `docs/archive/planning/remaining-work-plan-20260806.md`）

- 明确 `dist/release-check-<version>.json` 为唯一机器事实源：`scripts/generate_release_manifest.py` 改为从该报告的步骤结果生成 manifest 的 validation checklist，不再人工勾选；生成顺序固定为先完整 release check、后刷新 manifest。
- `scripts/run_release_checks.py` 新增四个强制步骤：`ruff_check`、`compileall`、`cargo_test`（新增 `scripts/cargo-test-tauri.bat`）、`sidecar_smoke`，完整门禁由 10 步扩至 14 步。
- Ruff 门禁口径固化到 `pyproject.toml` 的 `[tool.ruff.lint]`（`select = ["E", "F", "I"]`、`ignore = ["E501"]`），并清理存量 `E/F/I` 违规（未使用导入、导入排序、缺失模型导入、死代码等）；`ruff check src tests scripts` 与测试指南口径一致。
- 设计/审计文档统一「当前状态（2026-08-06）」与「历史执行台账（不得当作当前状态）」标记；旧计划书顶部状态更新为 M0/M2 已完成、M1 待干净 HEAD 重跑。
- 以干净工作区最终 HEAD 重跑完整发布门禁：`release-check-0.2.0.json/.md` 绑定该 commit（`worktree_dirty=false`、schema `0020`、`failed=0 / skipped=0 / ok=true`），manifest 与报告同一 commit 与摘要。
- 发布状态边界如实记录：无 Authenticode 证书（`code_signed: no`）；GitHub Release 远程 updater 未以真实远程资产验收。

## 0.2.0（2026-08-05）

### 版本化 RAG 生产上线（schema `0020`）

- 主库完成 `0012 → 0020` 正式迁移并核验：48 张原表行数零变化、10,581 行精确保持，回滚克隆 `personal_assistant_preupgrade_20260805111304` 保留。
- 新增 15 张迁移表：Agent 运行持久化（`agent_runs` / `agent_run_checkpoints` / `agent_run_events` / `agent_tool_executions` / `tool_approvals` / `run_steps`）、记忆事实（`memory_facts`）、版本化 RAG 索引（`document_index_heads` / `document_index_versions` / `document_index_chunks` / `document_index_chunk_provenance`）、MCP 注册表（`mcp_servers` / `mcp_call_logs`）、会话摘要（`conversation_summaries`）。
- 版本化检索已正式启用（`PA_VERSIONED_RAG_INDEXING_ENABLED=true`、`PA_VERSIONED_RAG_RETRIEVAL_ENABLED=true`）：active head 文档走版本化向量路径，未构建索引的文档自动落 legacy 检索，两套路径无缝共存。
- 4 个 canonical 文档完成生产小批构建（4 heads / 4 chunks / 4 versions / 4 provenance，Chroma 4 向量，1024 维），来源 SHA-256 与 canonicalization plan 完全一致。
- 生产评测：10 个人工复核 benchmark case 全部通过（Recall@K / MRR / 引用正确率 1.0，空召回率 0），P95 延迟约 510–713 ms，远低于 2 秒正式阈值。

### Agent Runtime（默认关闭，按开关启用）

- 全新 Agent 执行引擎：持久化 run、计划步骤、恢复与终止语义，MySQL 跨进程命名锁保证单 owner，第二进程 fail closed。
- 崩溃恢复：10 秒监控发现 ownership 丢失即停止本进程写入口，孤儿运行被确定性终结，幂等工具标 failed、非幂等标 unknown 且绝不自动重放。
- 工具审批流：`tool_approvals` 支持逐次审批、取消与恢复未决审批，跨会话/重载保持。
- 模型统一契约：JSON Schema / RAG 引用验证下发为 OpenAI `response_format`、Claude `output_config.format` 或 Ollama `format`，能力不支持时在网络请求前失败关闭。
- 输出验证（`PA_AGENT_OUTPUT_VERIFICATION_ENABLED`）：最终答案非空验证，无效候选最多受控修正 0–2 次。
- Context Builder（`PA_AGENT_CONTEXT_BUILDER_ENABLED`）：预算化输入上下文组装，默认 `PA_AGENT_CONTEXT_MAX_TOKENS=6000`。
- 旧聊天兼容映射（`PA_CHAT_AGENT_RUNTIME_ENABLED`）：无 RAG/无工具结果的开发聊天可接入 durable RAG 工具循环。

### MCP 客户端（默认关闭）

- MCP registry/client 独立默认关闭，每个 server 需显式信任并启用（`PA_MCP_ENABLED`）。
- 支持 stdio server、审批闭环、刷新恢复、调用日志与失败分类；DNS 私网地址默认拒绝。
- 凭据经系统安全存储管理，备份脱敏，不落配置文件。

### 记忆事实与上下文摘要

- `memory_facts` 支持结构化记忆事实，注入远程上下文时自动排除敏感/禁用条目。
- 可追溯会话摘要 worker（默认关闭）：按来源范围/hash 写结构化摘要、不删除原消息，本地 Provider 默认、远程二次许可，需 schema `0017+`。

### 数据治理、备份与回滚工程

- 数据库克隆脚本（`scripts/clone_application_database.py`）：mysqldump 逻辑克隆 + 逐表行数核对 + 计数 SHA-256 manifest，密码只进子进程环境。
- 升级演练脚本（`scripts/rehearse_database_upgrade.py`）：克隆上真实执行 `0012 → 0020 → 0012` 往返，验证回退哈希一致。
- 版本化迁移脚本（`scripts/migrate_versioned_rag.py`）：只对有源文件的小批文档旁路构建，失败保持 legacy 数据与旧 head。
- RAG 数据质量工具链：`profile_rag_data_quality.py` / `plan_rag_canonicalization.py` / `validate_rag_data_quality.py` / `build_rag_data_quality_report.py`。
- 评测基准：`generate_rag_benchmark.py` / `evaluate_rag.py`，支持空答案（abstention）、重复文档、引用边界与 P95 指标。

### 安全与容器部署

- API 认证强化：默认开启 token 认证、`PA_API_ALLOWED_HOSTS` / `PA_API_ALLOWED_ORIGINS`、`PA_API_ALLOW_NON_LOOPBACK_BIND=false`。
- 容器部署：Dockerfile、compose.yaml、容器密钥生成与 secret file 注入（`PA_API_TOKEN_FILE` / `PA_DB_PASSWORD_FILE`），本地开发/Windows 安装包/容器三种凭据来源互斥。
- Windows 凭据：Tauri sidecar 启动注入 256-bit 随机令牌，不写入磁盘。

### 桌面工作台

- 引入 anime.js 动画系统，Agent 工作台体验与交互细节打磨。
- 新组件：AgentActivityFeed、AgentPlan、AgentRunApprovalCard、TaskComposer、McpServersPanel（含组件测试）。
- 新 API 客户端模块：agentRuns、runtime、mcp；健康轮询状态在组件间共享。
- 检查器 `Files` / `Context` / `Artifacts` 三视图；窗口宽度低于 1320px 自动收起。

### 工程与质量

- Python 测试 535 通过（覆盖 Agent Runtime、恢复、审批、MCP、版本化 RAG、数据克隆、容器密钥、API 安全等新增域）；Vitest / Playwright / Rust / Vue production build / `cargo check --locked` / Docker Compose 配置门禁通过。
- 发布检查器修复：Windows 使用 `npm.cmd`、输出改临时文件防挂起、诊断 smoke 自清理。
- 新增文档：`rag-design.md`、`database-design.md`、`database-upgrade-runbook.md`、`migration-plan.md`、`modernization-audit.md`、`deployment-guide.md`、`mcp-design.md`、`memory-design.md`、`context-design.md`、`security-model.md`、`agent-runtime.md`、`api-reference.md`、`testing-guide.md`、`troubleshooting.md`、`tool-system.md`、`usage-guide.md` 等。

---

## 0.1.2（2026-07-11）

- 首次可安装桌面交付：Tauri/NSIS 安装包、应用内更新、发布检查、升级演练和可选代码签名。
