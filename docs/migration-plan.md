# PrivateAgent 现代化迁移计划

> 状态：Phase 0 执行计划
> 日期：2026-08-02
> 原则：先止损、后建契约、再切流量；每阶段可验证、可回退、可保留现有数据

> **当前状态（2026-08-06）**：本文 Phase 0–8 的执行台账属于历史记录（**历史执行台账（不得当作当前状态）**），其中「主库仍为 `0012`」「未获授权迁移」「发布未放行」等描述只代表对应切片当时的时点事实，不得据此重复迁移或重新 rollout。当前事实：应用主库已获授权迁移到 `0021 (head)`（`0020` 为 2026-08-05 迁移基线，2026-08-06 新增 `0021` telemetry 表；回滚克隆 `personal_assistant_preupgrade_20260805111304`、`personal_assistant_preupgrade_20260806070435` 保留）；versioned RAG indexing/retrieval 已生产启用（4 个 canonical 文档、10 个 reviewed case 全通过）；RAG 证据充分性与 Agent Runtime 批 A 已生产开启，聊天接管与自动摘要仍默认关闭。Windows `0.2.1` 为当前发布候选。详见 `docs/database-design.md`、`docs/rag-design.md` 顶部摘要。

## 1. 总体策略

迁移采用 Strangler Pattern：新能力在稳定契约后逐步接管旧路径，旧 API 和数据结构通过适配器继续工作。禁止以一次性重写替代迁移，也禁止在没有数据核验和回滚方案时做破坏性 schema 变更。

顺序固定为：

1. Phase 0：基线、数据安全和可重复验证；
2. Phase 1：统一 Agent Runtime 与模型契约；
3. Phase 2：工具、权限、审批和本地 API 安全；
4. Phase 3：上下文预算与记忆；
5. Phase 4：RAG 解析、检索和版本化索引；
6. Phase 5：MCP 客户端与可选服务端；
7. Phase 6：仅在证据满足时评估 LangGraph；
8. Phase 7：前端切换到运行事件模型；
9. Phase 8：交付、可观测性、备份和兼容清理。

每一阶段先通过单元和集成测试，再进入真实数据迁移；前一阶段未达到退出条件时，不并行切换后一阶段的生产路径。

## 2. 跨阶段安全规则

### 2.1 数据库

- 测试默认只允许连接名称明确包含 `test` 的独立数据库，并拒绝与应用数据库 URL 相同的连接。
- 所有 Alembic 迁移先在空测试库和主库副本执行，再记录关键表迁移前后行数。
- 表和列遵循“新增—双写—回填—切读—观察—清理”，清理独立成后续版本。
- 迁移失败时应用进入不可写的启动失败状态，不能跳过迁移继续服务。
- RAG、记忆和工具历史在新路径验收前不物理删除。

### 2.2 依赖

- `uv.lock`、`package-lock.json` 和 `Cargo.lock` 是可复现构建的依据。
- Python 声明从宽泛下界逐步改为经过验证的兼容范围；每次只升级一组相关依赖。
- 不因目录现代化新增框架。引入依赖必须写明缺口、替代方案、体积、安全和回滚影响。
- 模型原生工具调用的实现必须先核对当时的 Ollama、OpenAI-compatible 和 Claude 官方协议，再改适配器。

### 2.3 接口

- 公共 DTO、SSE 事件和数据库状态均有版本；新增字段优先可选。
- 兼容端点记录调用次数和调用方，不能凭时间猜测可以删除。
- 错误映射保持稳定：用户错误、策略拒绝、提供商错误、工具错误和内部错误不可混为一类。

## 3. Phase 0：基线和止损

### 3.1 已完成的基线工作

- 完成代码、依赖、配置、迁移、API、前端、模型、工具、任务、记忆、RAG 与数据库只读盘点。
- 形成 `docs/modernization-audit.md`、`docs/target-architecture.md` 和本文。
- 验证 Rust 构建、前端单测和前端生产构建；验证 API、MySQL、Chroma 健康路径。
- 识别 pytest 连接应用主库和 E2E 选择器滞后等基线阻断项。

### 3.2 Phase 0A：测试数据库隔离

首个代码切片只改变测试基础设施：

1. 从 `PA_TEST_DB_URL` 或应用数据库的安全派生名称解析测试 URL；
2. 拒绝与 `PA_DB_URL` 相同的 URL；
3. 拒绝数据库名不含明确 `test` 标志的 URL；
4. 测试清理只发生在验证后的测试库；
5. 提供显式的测试库准备命令，创建和迁移前打印目标数据库名，不打印凭据；
6. 在测试库隔离完成前，不再次执行全量 pytest。

验证：

```powershell
uv run pytest --collect-only -q
uv run pytest -q
```

退出条件：故意把 `PA_TEST_DB_URL` 指向应用数据库时，测试在任何删除或写入前失败；正常测试库完成迁移且全套测试不改变应用数据库关键表行数。

回退：还原测试配置改动即可；不会触碰应用 schema。测试数据库是独立可删除资产。

### 3.3 Phase 0B：其他基线修复

- 更新 E2E 稳定选择器，优先使用 `data-testid`，不依赖中文或英文可见文案。
- 为 API 启动测试使用隔离数据目录和独立端口。
- 增加最小 CI：锁文件安装、Python 测试、前端测试/构建、`cargo check --locked`、Alembic 空库升级。
- 将当前广泛依赖范围登记为风险，但不在同一改动中升级依赖。

Phase 0 总退出条件：所有验证可重复运行，并且不会写入应用数据库或用户数据目录。

## 4. Phase 1：Agent Runtime 与模型契约

### 4.1 Slice 1：纯契约和可执行内存运行时

新增最小的 `agents/contracts.py` 和 `agents/runtime.py`：

- 运行状态、步骤类型、公开事件、限制、取消令牌；
- 模型请求/响应的结构化工具调用和用量；
- 注入式模型客户端、工具调度器和事件接收器；
- 有界循环、取消、超时、工具错误和最终响应；
- 仅用 fake model/tool 的确定性测试。

这一切片不修改现有聊天请求路径，不添加数据库表，不改前端。它必须真正完成多轮工具循环，而不是只创建空接口。

验收：正常回答、一次/多次工具调用、工具失败、取消、最大步数、最大工具数和超时均有测试；公开事件顺序稳定且不含隐式推理。

回退：删除新增模块和测试，对现有运行无影响。

### 4.2 Slice 2：ModelGateway 适配

- 为当前 Ollama、OpenAI-compatible 和 Claude 提供适配器。
- 声明 streaming、native tools、structured output、usage 和 cancellation 能力。
- 保留旧 `ProviderRouter` 作为兼容门面，逐个调用点切换。
- 为远程基址加 URL 策略、超时、有界重试和错误归一化。
- 删除 OpenAI/Claude “假流式”行为；能力不支持时明确返回非流式事件。

验收：使用 fake HTTP server 验证协议；本地 Ollama 离线是清晰可诊断的退化，不导致长时间悬挂。

回退：兼容门面切回旧 provider 实现。

### 4.3 Slice 3：运行持久化

以新增迁移创建 `agents`、`agent_runs`、`run_steps`，并给现有会话/消息添加可空关联：

- 迁移先在测试库和副本验证；
- 不回填无法可靠推断的历史运行；
- 现有 `agent_tasks` 保留，先通过映射服务读取新状态；
- 事务提交与事件序号绑定，保证重连不丢失已提交事件。

验收：进程在任意步骤退出后，已提交运行可读取、可标记失败或按策略恢复；重复事件不会造成重复工具执行。

回退：关闭新运行功能开关，旧表继续工作；新增表保留等待修复，不做紧急删除。

### 4.4 Slice 4：兼容接管聊天

- `/chat/stream` 内部创建 `AgentRun`，将新事件转换成旧 SSE 事件。
- 工具结果由后端继续循环，不再要求前端二次提交。
- 先对开发会话启用，再按配置扩大；保留旧路径开关和对比日志。
- 现有任务计划和审批通过适配器接入同一运行时，避免第二套循环继续扩张。

验收：现有 UI 不修改也能完成聊天和审批；刷新后可从持久化运行恢复；同一调用不会被执行两次。

Phase 1 退出条件：后端拥有唯一可持久化闭环，至少 Ollama 和一个远程适配器支持原生结构化工具调用，旧聊天 API 仅为兼容层。

## 5. Phase 2：工具、权限、审批与本地安全

### 5.1 工具契约与执行器

- 将现有 ToolDefinition 包装为版本化 `ToolSpec`，保留现有工具名和行为。
- 在统一入口执行 JSON Schema 输入/输出验证、超时、取消、大小限制和脱敏。
- `safe`、`confirm`、`restricted` 映射为能力策略，不再让所有工具一律进入待审批。
- 为幂等工具支持调用键；非幂等工具在状态不明时不自动重试。
- 首批迁移低风险只读工具，再迁移文件写入、进程和网络工具。

### 5.2 审批

- 新增 `tool_approvals`，保存规范化参数哈希、过期和一次性批准令牌。
- 审批决定由 Runtime 消费；前端无法替换参数后继续执行。
- 暂停、取消和超时都能原子终止待审批调用。

### 5.3 本地 API 安全

- sidecar 启动生成随机令牌，所有业务 API/SSE 强制 Bearer 认证。
- CORS/Origin/Host 收紧到桌面应用实际来源。
- 健康端点拆成最小公开存活与认证后详细健康。
- Tauri 开启 CSP；数据库密码和 API key 不再通过 `read_config` 返回 Vue。
- 使用操作系统凭据存储保存秘密，配置只保存凭据引用和脱敏状态。

验收：跨站页面不能调用本地 API；旧/错误令牌被拒绝；变更审批参数会失效；敏感配置不会出现在 Vue 状态、日志或错误响应。

回退：认证兼容窗口只允许由 sidecar 启动参数显式开启，并显示高风险告警；不得恢复 wildcard CORS 作为默认值。

Phase 2 退出条件：所有工具都经过统一执行器，所有业务 API 都认证，秘密不进入渲染进程。

## 6. Phase 3：上下文与记忆

### 6.1 ContextBuilder

- 引入按区段预算的上下文构建器，先只对新 Runtime 生效。
- 保留最近消息，旧消息生成带覆盖范围的摘要；原消息不删除。
- RAG 和记忆都有单独 token 配额、来源和不可信内容边界。
- 记录构建决策、实际 token 和截断原因。

### 6.2 记忆

- 增量扩展 `memory_items`：owner、stable key、importance、expiry、version、deleted_at。
- 抽取只生成候选；提供查看、确认、纠错、禁用、合并和删除流程。
- 冲突记忆并存并显式关联，不用最后一次写入静默覆盖。
- 为已确认记忆建立可重建向量索引；MySQL 继续为事实源。
- 删除事件独立保留，不再由级联删除抹除审计。

验收：固定长会话在预算内运行；摘要可追溯；用户纠正记忆后旧版本不再注入；敏感候选不会自动启用。

回退：关闭 ContextBuilder/语义记忆开关，旧历史读取和结构化记忆仍在。

Phase 3 退出条件：长会话具有可测预算，记忆生命周期和冲突处理可由 UI 管理。

## 7. Phase 4：RAG 现代化

### 7.1 结构化解析与切分

- 先增加解析器输出契约和 golden fixtures，保持现有导入 API。
- PDF 保留页码，DOCX/Markdown 保留标题路径，文本保留行范围。
- token-aware splitter 与旧 500 字符切分器并行生成版本化结果。
- 对不同文档类型建立固定评测集。

### 7.2 版本化索引

- 新增知识库、索引版本和索引任务表。
- 新版本旁路写入 MySQL 和 Chroma；数量、哈希和召回检查通过后切换 active version。
- 旧版本保留到回滚窗口结束；失败任务可续跑，不删除当前 active 数据。
- 修复当前 retry/reindex 先删旧索引的 P0 风险后，才允许批量重建。

### 7.3 检索评测

- 保留 BM25 + vector + RRF + rerank，所有阶段输出可观测。
- 增加权限过滤、重复片段抑制、每文档配额和引用校验。
- 门禁至少包含 Recall@K、MRR、引用正确率、P50/P95 延迟和空召回率。

验收：人为注入解析、embedding 或 Chroma 写入失败时，旧版本仍可查询；引用能定位到页码/标题/行范围。

回退：原子切回旧 `active_index_version`，不需要重新导入原文。

Phase 4 退出条件：任何重建失败都不影响在线检索，质量和延迟有固定回归基线。

## 8. Phase 5：MCP

### 8.1 客户端

- 实现 stdio 和必要的 HTTP 传输，先接只读测试服务器。
- 服务器配置包含信任状态、固定命令/URL、允许能力和启用范围。
- 发现的 tools/resources/prompts 经过内部 schema 和策略转换。
- 调用统一使用超时、取消、输出上限、脱敏和审计。

当前实现状态（2026-08-02）：Slice 1 已落地且默认关闭。官方 SDK stdio 测试服务器已完成真实初始化、分页发现和工具调用；Streamable HTTP 适配器已实现 HTTPS 默认、无重定向、无环境代理、DNS 私网拒绝和资源上限，但尚未完成带认证的真实外部服务器互操作。服务器必须依次经过显式 trust、enable 和工具 allowlist；适配后的 MCP 工具继续经过内部 capability policy、`confirm` 审批、checkpoint、durable execution 与不含正文的调用审计。桌面设置、待审批刷新恢复和 continuation SSE 已接入。详细边界见 `docs/mcp-design.md`。

### 8.2 服务端

只有确定存在外部客户端需求时，才把少量稳定、低风险能力暴露为 MCP Server。服务端复用内部 ToolSpec 和权限规则，不直接调用数据库仓储绕过领域服务。

验收：恶意 schema、超大输出、进程退出、协议错误、提示注入和未经信任的服务器都能被隔离；MCP 工具和内建工具产生相同形态的运行步骤。

回退：按服务器或工具禁用 MCP，不影响内建工具和 AgentRuntime。

Phase 5 退出条件：至少一个真实外部 MCP 集成通过安全和恢复测试；没有真实需求则明确保持未启用状态也视为正确决策。

## 9. Phase 6：LangGraph 条件评估

这一阶段不是默认实施项。先记录轻量 Runtime 在真实流程中的复杂度指标：状态分支数、补偿逻辑、恢复缺陷、重复代码和调试成本。

只有满足目标架构中的引入门槛时，才完成一个不改变公共契约的 PoC，并比较：

- 持久化和恢复正确性；
- 代码量与认知复杂度；
- 性能和包体；
- 升级与调试成本；
- 现有运行数据兼容性。

若收益不明确，记录“不引入”决定并结束本阶段。不得为了已存在的依赖而反推采用框架。

## 10. Phase 7：前端运行体验

- 增加单一 agent-run client，封装创建、订阅、重连、审批、取消和重试。
- 用 run/step/event 投影驱动消息、AgentPlan、AgentActivityFeed 和 ToolApprovalCard。
- `App.vue` 删除工具规划、执行和结果二次提交的业务编排。
- 所有流式资源拥有 AbortController 和组件卸载清理；重连按事件序号恢复。
- 使用 `data-testid` 构建稳定 E2E，不用可见文案作为唯一选择器。
- 继续复用现有 WorkspaceShell、设计 tokens 和已在工作区中的 UI 组件，不批量换 UI 框架。

验收场景：普通回答、多工具调用、等待审批、拒绝、取消、工具超时、模型离线、刷新恢复、sidecar 重启和长输出。

回退：保留兼容 UI 开关到 E2E 和人工 QA 稳定；切回时不会改变后端运行数据。

Phase 7 退出条件：Vue 只呈现和提交用户意图，不再实现 Agent 循环。

## 11. Phase 8：交付、运维和清理

- JSON 日志、trace ID、关键指标、审计日志和本地诊断包。
- sidecar 启动前数据库备份/迁移检查，迁移失败阻断可写服务。
- 主要生产形态仍是桌面 sidecar；另提供独立单机 Compose（隔离 MySQL、Chroma、secret files 和可选 GPU Ollama），不得挂载或迁移现有桌面主库来绕过授权。
- Windows 安装、升级、回滚、数据目录、日志和备份恢复演练。
- 统计旧 API、旧 provider 和旧工具路径调用；归零且经过一个兼容窗口后单独删除。
- 更新用户文档、开发文档、威胁模型、数据迁移手册和故障处理手册。

Phase 8 退出条件：可从备份恢复；升级失败可回退；兼容代码删除有调用证据；完整发布清单通过。

## 12. 测试矩阵

| 层级 | 必须覆盖 | 执行条件 |
|---|---|---|
| Python unit | contracts、runtime、budget、policy、parser | 不依赖主数据库或真实模型 |
| Python integration | MySQL 仓储、Alembic、Chroma、API、任务恢复 | 独立测试数据库和临时数据目录 |
| Provider contract | Ollama/OpenAI-compatible/Claude 请求响应、错误和取消 | fake server；真实 smoke 可选 |
| Tool contract | schema、权限、审批、超时、取消、幂等和脱敏 | 默认 fake executor |
| RAG evaluation | 解析、Recall@K、MRR、引用和失败回滚 | 固定可版本化语料 |
| Frontend unit | event projection、状态、审批和重连 | Vitest |
| Frontend E2E | 主路径、错误、取消、刷新恢复 | Playwright + 隔离 API |
| Rust | sidecar、配置 DTO、启动令牌和生命周期 | `cargo check/test --locked` |
| Release | 安装、升级、备份恢复、离线模式 | Windows 干净环境 |

常规验证命令：

```powershell
uv run pytest -q
Set-Location apps/desktop
npm run test
npm run build
Set-Location src-tauri
cargo check --locked
```

数据库相关测试只有在隔离守卫验证测试库后才执行。

## 13. 每阶段 Definition of Done

每个阶段必须同时满足：

1. 需求和非目标写清；
2. 代码经过最小必要审查，新增公共契约有类型和文档；
3. 单元、集成、静态、构建和适用的 E2E 通过；
4. 数据迁移有前后行数、失败注入和回滚证据；
5. 日志和指标能解释成功、失败、取消和退化；
6. 安全边界没有因兼容而默认放宽；
7. 兼容行为、功能开关和删除条件有记录；
8. 更新审计、架构或迁移文档中的实际状态；
9. 只清理本阶段明确拥有的临时资产，不覆盖用户工作区改动。

## 14. 当前最近执行序列

从本计划落地后，按以下小步推进：

1. 实现测试数据库 fail-closed 隔离和守卫测试；
2. 在隔离测试库运行完整 Python 基线并记录应用主库行数未变化；
3. 修复 E2E 稳定选择器，恢复可重复前端基线；
4. 实现 Phase 1 Slice 1 的契约和内存 AgentRuntime；
5. 用 fake model/tool 完成循环、取消、限制和错误测试；
6. 评审结果后进入 ModelGateway，不同时修改数据库和前端。

## 15. 执行台账

### 2026-08-02

- Phase 0：完成。三份设计/审计文档、独立测试数据库守卫、测试库准备脚本、应用库前后行数核验、前端稳定选择器和完整构建基线均已落地。
- Phase 1 Slice 1：完成隔离实现。类型化 Runtime 在内存中完成多轮工具闭环、限制、取消、超时、错误恢复和公开事件；尚未持久化，也未接管 `/chat/stream`。
- Phase 1 Slice 2：三类模型适配器和 ProviderRouter 兼容桥已实现原生流式。Ollama `/api/chat` NDJSON、OpenAI-compatible Chat Completions SSE、Claude Messages SSE 均聚合完整文本/tool calls/usage，保持取消和“首个 delta 后不重试”；旧聊天兼容层也消费远程 SSE。MockTransport 协议回归通过，Claude thinking 不发布，缺终止帧/流内错误失败关闭。真实本地模型 smoke 已完成过一次；OpenAI/Claude 真实付费端点 smoke 仍待用户提供授权环境。
- Phase 1 Slice 3：完成隔离实现。新增 `0013` 迁移、`agent_runs`、`run_steps`、`agent_run_events`、事务性事件投影 repository 和 `PersistentAgentRunner`；每个公开事件与 run/step 状态在同一事务提交，重复的相同序号事件幂等，不同事件冲突或序号跳跃会失败关闭。
- 持久化验证：专用测试库完成真实 `0013 → 0012 → 0013` 往返；运行中断态可由另一数据库会话读取；事件可按 `after_sequence` 重放；event sink 失败不再被 Runtime 伪装成新的 `run.failed`。应用主库仍为 `0012`，没有创建新表。
- P0 本地 API 安全门槛：完成。Tauri 主进程用 OS CSPRNG 为每次打包 sidecar 启动生成 256-bit token，只经进程环境和当前 WebView 连接 DTO 传递；后端对非预检 HTTP/SSE 校验 Bearer，并严格限制 loopback bind、`Host` 和确定 `Origin`。全部前端 API 调用经共享封装附加 token；手动开发需显式共享 token，或显式关闭认证。
- P0-3 凭据/CSP 门槛：完成 Windows 交付路径。数据库密码与 OpenAI/Claude key 由 Windows 原生凭据窗口直接写入 Credential Manager；Vue/Tauri 调用、HTTP DTO、settings 行、桌面 `.env` 和备份只传状态或固定 `secret://` 引用。Rust 在 sidecar 启动时于内存组装数据库 URL 并注入当前子进程环境；旧桌面 `PA_DB_URL` 会在打包启动时迁移后改写为非敏感字段。Tauri CSP 已限制为本地资源、IPC 与动态 loopback sidecar。
- 启动安全：打包 sidecar 的 Alembic 迁移失败改为拒绝启动，错误日志只记录异常类型，不输出可能含 DSN/SQL 参数的异常正文。sidecar smoke 和启动基线脚本同步使用临时 token。
- Phase 1 Slice 4A：完成默认关闭的 `/agent-runs` 开发 API。`POST` 先提交 run 再返回 `202`，进程内 coordinator 后台执行无工具模型运行；`GET` 返回 run/step/usage/trace；事件端点按 `after_sequence` 重放；取消端点先持久化意图，再主动取消本进程挂起调用。进程退出会取消并收拢活动任务。
- Slice 4A 初始边界：功能开关 `PA_AGENT_RUNS_API_ENABLED` 默认 false；不写旧消息、不启用工具、不修改 `/chat/stream`。后续恢复切片已补连接级单进程 owner guard 和启动 reconciler，见下方当前状态。
- Phase 1 Slice 4B：完成默认关闭的 `/chat/stream` 兼容映射。`PA_CHAT_AGENT_RUNTIME_ENABLED` 开启后，仅普通聊天进入持久化 Runtime；SSE 先发送 `run_id`，完成后映射回旧 `token/done/title`，并保持旧 `messages` 写入。前端把 `run_id` 绑定到临时助手消息，为后续断线恢复保留键。
- Slice 4B 边界：RAG 或带 `tool_result` 的请求明确继续走旧 ChatService；新路径已把 Ollama 原生 delta 映射为旧 SSE token，并保持唯一 done 和最终消息持久化。工具启用时先缓冲当前模型回合，确认没有结构化工具调用后再发布；增量队列只在进程内存在，不作为可重放审计事件。开关默认 false，现网行为不变。
- Slice 4B 后续 RAG 接管：仅当 `PA_CHAT_AGENT_RUNTIME_ENABLED`、`PA_AGENT_RAG_TOOLS_ENABLED`、`PA_AGENT_OUTPUT_VERIFICATION_ENABLED` 三者同时开启且请求没有旧 `tool_result` 时，`knowledge_base=true` 进入 durable Runtime。结构化候选在验证前不发布；完成后旧 SSE/消息表只接收 answer，来源名称、ordinal、分数和命中信息从已校验 SHA 的工具执行记录投影，run 仍保留原始 `{answer,citations}`。任一开关缺失时精确回退旧 ChatService，默认行为不变。聊天专项 7 passed，连同引用、RAG 工具和 ModelGateway 的聚焦回归为 47 passed。
- Slice 4B 消息投影幂等：初始 SSE 与 continuation 不再各自盲插 assistant 消息。`persist_chat_output_message_once` 锁定 completed run，在同一事务创建 message、触碰 session，并追加 `chat.output_persisted` 事件；重复或并发重连只返回已绑定 message，绑定缺失或内容不一致时失败关闭。复用现有 event 表，无需新增 schema；聊天 7 项回归同时覆盖初始后重连和双 continuation 并发，均只得到一条 assistant 消息和一个投影事件。
- Phase 2 Slice 1：完成版本化 `ToolSpec`、重复注册拒绝、Draft 2020-12 输入/输出验证、远程 schema 引用拒绝、capability 默认拒绝策略、超时、取消、输入/输出上限、结构化错误、敏感值脱敏和规范化幂等键。`jsonschema` 已成为显式锁定依赖。
- Slice 1 首批迁移：旧 handler 未重写，只包装 `search_files`、`grep_code`、`get_git_status`、`get_git_diff`；各工具声明实际 `database.query`、`filesystem.read`、固定只读 git 所需的 `process.execute` 能力。写入、任意命令和网络工具仍不在新 Runtime 注册表中。
- Slice 1 接管边界：`PA_AGENT_RUN_READ_ONLY_TOOLS_ENABLED` 默认 false，且只对默认关闭的 `/agent-runs` 生效。Coordinator 在自己的数据库会话内构造 dispatcher，避免后台任务复用请求结束后的 session；持久化 run 已验证完整工具事件闭环。
- Phase 2 兼容收口切片：`read_file`、`read_code_file` 已迁入同一注册表并固定为 `confirm`，复用参数绑定审批、checkpoint 和 durable execution；其底层线程读取明确标记不可强取消。纯预览 `propose_patch` 随后作为第五个 safe 工具迁入，严格限制完整新内容、diff 和输出字节数，diff 截断不改变源文件。聊天 Runtime 与只读工具开关同时开启时，旧 `/tools/plan` 排除全部七个 Runtime-owned 工具，恶意或陈旧的同名文本 JSON 选择也不会落旧 `tool_calls`。其余旧工具暂留兼容链，待逐项契约化后再删除前端规划/结果二次提交。
- 兼容调用证据：`/tools/plan` 返回 `Deprecation: true`，每次调用写不含消息/参数的固定标签结构化日志；`/diagnostics.compatibility_telemetry` 暴露当前进程的 calls/mode/outcome 和启动时间。该计数重启清零，只用于即时诊断；端点删除仍要求跨版本日志观察窗口归零。
- 聊天兼容证据：`/chat/stream` 使用同一低基数遥测，区分 `agent_runtime`、Runtime 关闭、旧 `tool_result`、RAG 工具关闭与输出验证关闭；路由选择算法未改变。
- 旧工具端点证据：`GET /tools`、approve/reject、tool-call 列表/详情均带弃用头；写端点使用不含调用 ID 的规范化 path并区分 succeeded/rejected/failed/conflict/not-found，列表区分 all/session-filtered，详情区分 found/not-found。所有进程计数都会重启清零。
- 桌面单执行链收口：新增无依赖探测的 `GET /capabilities`。现代桌面端收到 `chat_execution_mode=agent_runtime` 后，新消息直接进入 `/chat/stream`，不再预调用 `/tools/plan`；端点不存在时兼容旧后端。升级前旧 `pending_approval` 卡片仍可重载/审批，避免状态孤立。后端模式组合、前端路由决策、完整 32 项 Vitest 和生产构建均通过；浏览器级模拟进一步断言 Runtime 消息只调用一次 chat stream、旧 planner 为零。
- Slice 1 当时的未完成项已由 Slice 2/3 补齐：审批等待、一次性批准、checkpoint 和持久化幂等结果均已实现；旧 `grep_code` 线程和 git 子进程的强取消清理仍需加固。
- Phase 2 Slice 2A：新增 additive `0014_tool_approvals` 与仓储状态机。审批精确绑定 run/step/call、工具名和版本、规范化参数哈希、风险与能力；批准 token 只存哈希，带过期和一次消费语义。参数替换、版本替换、错误 token、重放、跨 run step 和并发双消费均有拒绝测试。
- Slice 2A 迁移验证：专用测试库完成真实 `0014 → 0013 → 0014`；应用主库继续保持 `0012`，没有创建 AgentRuntime 或审批表。首次演练发现并修正 MySQL 外键支撑索引的降级顺序。
- Slice 2A 边界：审批仓储尚未接入 Runtime 暂停/唤醒，也未开放 approve/reject API；这是刻意的 fail-closed 状态，避免 renderer 获得一次性执行 token，或在没有恢复 checkpoint 时把 `confirm` 工具暴露给模型。
- Phase 2 Slice 2B（后端恢复完成）：新增 additive `0015_agent_run_checkpoints`。Runtime 将 approval-required 事件与版本化 checkpoint 原子提交，保存 conversation、剩余 tool calls、usage 和精确事件序号；冲突 checkpoint 失败关闭。
- 批准后恢复：raw token 只在后端内存流转并由 SQL consumer 一次消费；`PersistentAgentRunner.resume` 从 checkpoint 和持久化 steps 继续原调用，写 `tool.approval_resolved`，完成剩余工具/模型循环，并在终态删除 checkpoint。端到端数据库测试覆盖等待 → 批准 → 消费 → 恢复 → 完成。
- Phase 2 Slice 3：完成 durable tool execution claim/audit。新增 additive `0016_agent_tool_executions`；run 行锁和唯一键关闭首次双执行竞态，哈希 claim token 与有限租约支持幂等恢复，非幂等不确定态 fail-closed。成功输出经 schema、脱敏和字节限制后先持久化并记录 SHA-256，再返回 Runtime；失败、超时和取消同样进入终态审计。
- Slice 3 审批恢复：execution 与 consumed approval 做完整不可变绑定。若进程在审批消费或工具结果提交后、Runtime 事件提交前退出，新进程无需取得或重放原始 token，即可验证已消费审批并回放已提交结果；跨调用复用带审批的 execution 会被拒绝。
- Slice 3 接管边界：默认关闭的 AgentRun 只读工具已使用持久化 execution store；普通聊天与旧工具 API 不变。approve/reject HTTP API、reject 的模型反馈、coordinator 唤醒和跨进程 reconciler 仍未开放，因此 `confirm` 工具继续不向真实模型注册。
- Phase 3 Slice 1：完成隔离、默认关闭的 ContextBuilder。系统策略/当前请求/未完成工具上下文不可丢弃；历史、确认记忆、摘要和 RAG 使用独立区段预算、硬总预算、敏感内容强制排除和可解释 selection trace。不可信资料以 JSON data envelope 注入，不能改变权限或审批。
- Slice 1 接管边界：`PA_AGENT_CONTEXT_BUILDER_ENABLED` 默认 false，当前仅接入原生 `/agent-runs`；最多读取最近 200 条历史并发出不含正文的 `context.prepared` 事件。旧 `/chat/stream` 与 provider 精确 tokenizer 尚未接管。
- Phase 3 Slice 2：完成 additive `0017_context_memory_facts`。记忆当前投影获得稳定键、单调版本、内容哈希、重要度、有效期、敏感级别、确认时间和软删除时间；每次创建、编辑、确认与删除原子写不可变 revision。冲突以规范化 ID 对显式登记/解决，不允许静默覆盖。
- 可追溯摘要：`conversation_summaries` 绑定精确消息范围、消息数和 source SHA-256，记录生成配置、token 和版本；相同来源幂等，更正生成新版本，重叠 active 摘要被 supersede。ContextBuilder 用 active summary 替代被覆盖的原始历史，并保留 provenance。
- Slice 2 API/检索：Memory API 返回 stable key/version/hash/importance/expiry/sensitivity/confirmation；软删除后 revision 仍可查询；新增冲突登记、待处理列表和显式解决接口。上下文默认排除 tombstone、过期和非 normal 敏感级别。
- Slice 2 迁移验证：首次升级暴露 MySQL 非事务 DDL 部分落列与关键字转义问题；只在守卫后的测试库精确清理九个部分列后，完成真实 `0016 → 0017 → 0016 → 0017`。应用主库仍为 `0012`，没有新增事实表或列。
- Phase 4 Slice 1：完成 additive `0018_versioned_rag_indexes`。独立 version/chunk/head 表与独立 Chroma collection 支持旁路构建、chunk/vector/hash/manifest 校验和单事务 active head 切换；legacy `doc_chunks` 全程不改写。
- Slice 1 失败/回滚：构建失败只标记 staged version，旧 active 不变；回滚前重新核验实际向量与 manifest；active 删除被拒绝，inactive 删除在 head 锁下先移除 DB 可见性再清理向量，避免 TOCTOU。
- Slice 1 渐进接管：indexing/retrieval 两个开关默认 false。只开 indexing 可安全旁路 reindex；打开 retrieval 后按文档 active head 读取新索引，无 head 文档继续 legacy fallback。引用与 RRF identity 均携带 index version，避免双表 ID 冲突。
- Slice 1 恢复：启动 reconciler 仅处理持久化 `building/validated`；前者从 chunks 重做 embedding，后者直接复核后激活。failed 版本须显式 retry；ready 文档重建失败保持旧 active 与 ready 投影。管理 API 可查版本/head/chunk、回滚和触发失败重试。
- Slice 1 迁移验证：专用测试库完成真实 `0017 → 0018 → 0017 → 0018`。应用主库仍为 `0012`，未创建 versioned RAG 表，关键数据计数保持不变。
- Slice 1 保留/评测：启动 reconciler 续做 durable `deleting` claim，并按 14 天/至少一个 retired 版本的默认策略清理；active/previous 不进入候选。通用 rollout gate 计算 Recall@K、MRR、引用正确率、空召回率和 P50/P95，CLI 对固定 JSON cases 执行只读门禁并以退出码阻断。
- Slice 1 迁移工具：分批 CLI 默认 dry-run，只有 `--yes` 才按 ID/limit 旁路构建；已有 active 默认跳过，缺源文件显式 skipped，不自动打开 retrieval。并发单调保护拒绝旧 build 晚到覆盖新 active。
- Phase 5 MCP Client Slice 1：新增 additive `0019_mcp_client_registry`、官方 MCP SDK stdio/Streamable HTTP 客户端、服务器注册/发现/健康/调用元数据 API 和桌面设置面板。全局开关默认 false；服务器初始不信任且不启用，只有显式 allowlist 工具可进入模型注册表。
- MCP 策略链：发现 schema 先经内部 `ToolSpec` 隔离，所有 MCP 工具固定为 `confirm` 并声明外部进程/网络能力。approve/reject API、等待 checkpoint、一次性后端 token、进程重启后的显式 token 轮换、聊天 SSE 等待/恢复以及刷新后审批 rehydrate 已接通；Vue 和 API 不返回原始参数或 token。
- MCP 安全边界：stdio 只允许已存在的绝对可执行路径且不经过 shell；HTTP 默认 HTTPS、拒绝 URL 凭据/非法端口/重定向/环境代理/私网解析，并把通过校验的 DNS 地址集钉到实际 TCP backend，同时保留原域名 TLS SNI/证书校验；发现和输出有硬上限。远程描述、资源、提示和结果均作为不可信数据。调用日志仅存哈希和元数据，未加密备份清空环境值。
- MCP 凭据闭环：桌面原生窗口写 OS keyring，数据库/Vue 只保存固定引用；打包 sidecar 启动时注入有界引用映射并立即从 Python 环境删除。stdio secret env、HTTP Bearer 和受限 API-key header 已通过官方 SDK 真实 server/client 互操作。应用层 DNS pinning 已补齐；仍未完成 OAuth、具体第三方生产服务证书/限流验收、企业代理和证书 pinning。没有真实外部客户端需求，因此不实现本应用 MCP Server。`PA_MCP_ENABLED` 保持默认关闭。
- Phase 5 迁移验证：专用测试库完成真实 `0019 → 0018 → 0019`；应用主库保持 `0012`，未创建 MCP 表。真实官方 stdio server、DNS 私网拒绝、审批闭环、刷新恢复、备份脱敏和默认关闭均有回归覆盖。
- 生产升级安全切片：现有 ZIP 备份的自动恢复仅覆盖 settings，不能冒充完整数据库回滚。新增 `clone_application_database.py`，通过官方 `mysqldump/mysql` 创建绝不覆盖源库的同服务器全库克隆；密码只进入子进程环境，dump 使用自动删除的匿名临时文件，manifest 不含凭据。克隆逐表比较表集合、Alembic head 和精确行数。
- 真实数据演练：主库 `personal_assistant` 的预升级克隆已核验为 `0012 / 48 tables / 10579 rows / counts SHA-256 aa5a2cca…096db`。`rehearse_database_upgrade.py` 只接受源库专属 `_preupgrade_<UTC timestamp>` 名称；该克隆完成 `0012 → 0019 → 0012`，head 时 48 张原表行数保持，回退后的总行数和完整计数哈希与源库一致。正式主库迁移因缺少用户对生产 schema 变更的明确授权而未执行。
- 最近一次完整门禁（早于 Phase 4 Slice 3）：发布报告 `10 passed / 0 failed / 0 skipped`；Python 全量 494 passed；Vitest 9 files / 29 tests passed；Playwright 13 passed；前端生产构建通过；Rust 9 passed、`cargo check --locked` 与 Docker Compose 配置门禁通过。最新镜像隔离运行到 `0020 / 63 tables`，认证、三项健康和容器安全约束通过后，临时容器/网络/测试卷/秘密全部清理。应用主库上次只读复核仍为 `0012 / sessions 927 / documents 1117 / memory_items 0 / agent_tasks 155 / inbox_items 34 / app_notifications 320 / doc_chunks 358`；总行数为 10,581，与保留克隆唯一计数差异是修复前 release smoke 留下的 `diagnostic_runs +2`。
- RAG 实际语料审计：新增隐私受限 profile、独立 MySQL manifest 复核、可执行 notebook、MCP report artifact 与 canonicalization dry-run。主库 1,117 个文档行中只有 383 个 ready/enabled、357 个有 chunk；两个独立口径都只得到 4 个逻辑内容组，规模为 `180 / 59 / 59 / 59`。357 行全部位于重复组，Chroma legacy vector coverage 为 0%，54 个 chunk 缺 BM25，76 个文档的声明/实际 chunk count 不一致。
- RAG 可恢复性：32 个有 chunk 文档仍可解析原始来源，覆盖全部 4 个逻辑组。只读 canonicalization plan 已为每组选择一个有源文件、BM25 完整且 chunk count 一致的 canonical 文档，规划 4 个保留行和 353 个 duplicate 行；计划未授权也未执行删除/更新。
- RAG rollout 门禁：Ollama 已通过直接 `serve` 恢复并完成真实 embedding。全新来源受限克隆和独立 Chroma 已按 canonicalization plan 完成 `0012 → 0019`、4 个文档构建与一致性校验、hybrid 评测、`0019 → 0012` 和临时克隆删除；主库 revision/当次计数哈希未变化。首次 P95 13,402.64 ms 的根因是每次 embedding 重建客户端；缓存同一 `OllamaProvider` 的 embedder 后，legacy P95 为 452.45 ms，versioned P95 为 437.78 ms，正式 2 秒技术 gate 通过。质量仍为 Recall@K 1.0、MRR 0.8333、引用正确率 1.0、空召回率 0；4-case 尚未人工审阅，所以 `rollout_ready=false`。应用主库仍为 `0012`。
- Phase 4 Slice 2：新增 `0020_document_chunk_provenance` 和结构化 block/chunk。PDF 页、Markdown/TXT 段落、Markdown 围栏代码块、DOCX 标题路径与顺序表格、Python AST 与常见代码符号、字符/行范围、source/parser version、保守 token 估算和独立来源哈希进入版本化索引；source hash 绑定原始文件字节，缺失/篡改来源 fail closed，schema 低于 `0020` 在解析和 embedding 前拒绝 indexing。Markdown/DOCX 已升级为 `v2` 解析器并由真实 DOCX 文件和围栏代码测试覆盖。专用测试库已完成空表往返与一条真实 `0019` chunk 回填验证，当前为 `0020 / 63 tables`；主库保持 `0012`。
- Phase 4 Slice 3：新增默认关闭的 `search_knowledge_base / get_document_chunk / get_document / list_knowledge_bases` 四个只读 ToolSpec。Agent 按需检索而不是每条消息强制 RAG；query/top-k/collection/doc type/language/project/tags 经过严格 schema，输出有上限且携带 chunk/version/page/line/heading/source/parser 和真实知识库名称。详情读取继续强制 collection membership；versioned chunk 只接受 active head 且复核正文/provenance 哈希，文档详情不返回本地路径。该切片通过 42 个定向回归及 compileall/Ruff/差异检查；切片后的完整发布复跑受平台提权额度限制尚未执行，因此当前不能据此更新 10/10 报告或放行发布。
- Phase 6 Slice 1：新增受控输出验证层。可信调用方可固定非空/JSON Schema/组合验证器；最终候选失败后以有界反馈最多修正两次，候选通过前不发布，验证事件与重试计数进入既有 durable event 投影，审批恢复不重置预算。后续通过默认关闭的 `PA_AGENT_OUTPUT_VERIFICATION_ENABLED` 把固定非空策略接到 Agent API 与 AgentRuntime 兼容聊天，修正预算由 0–2 的独立配置控制。RAG 引用验证器校验召回身份与精确原文摘录，拒绝缺失、未知、重复或伪造引用；现已在两个相关开关同时开启时接入 durable Agent RAG 工具流。证据只从同一 run 的成功工具执行加载并复核持久化大小/SHA，篡改、冲突和超限均失败关闭，审批恢复无需进程内临时状态；三项聊天/RAG/验证开关同时启用时，知识库兼容聊天也接入并把验证后的结构化结果安全投影回旧 SSE。JSON/RAG 验证器同时生成有界且只允许本地引用的 provider-neutral `ModelOutputFormat`，普通/流式适配器映射到 OpenAI `response_format`、Claude `output_config.format` 和 Ollama `format`；能力不支持时在网络调用前拒绝，Provider 返回后仍由 Runtime 本地复核。此前 Agent/RAG/MCP 组合回归为 `148 passed, 2 deselected`，本次新增聊天专项 7 passed、相关聚焦 47 passed；受限沙箱近全量 Python 历史结果为 `519 passed, 4 WinError 5 failed, 2 deselected`，不记全绿。代码写入、diff、Shell/API 和数据库领域验证器仍待按具体受控工作流接入。
- Schema 安全门禁：新建且不覆盖任何库的 `personal_assistant_preupgrade_20260803081120` 精确匹配主库 `0012 / 48 tables / 10581 rows / a407…f033`；已完成 `0012 → 0020 → 0012`，head 原表计数保持且回退哈希一致，主库未修改。克隆与无凭据 manifest 保留为当前回滚证据。
- 下一步（已完成）：2026-08-05 获得明确授权后，应用主库已从 `0012` 升级到 `0020`（48 张原表行数零变化，10,581 行精确保持）；4 个 canonical 文档完成生产 versioned 构建（来源哈希与 canonical 计划一致），`PA_VERSIONED_RAG_INDEXING_ENABLED` / `PA_VERSIONED_RAG_RETRIEVAL_ENABLED` 均已启用，生产 hybrid 评测 10 个 reviewed case 全部通过（Recall/MRR/引用 1.0，P95 约 510 ms）。回滚克隆 `personal_assistant_preupgrade_20260805111304` 保留。MCP 若接入具体生产远程服务，再补 OAuth/证书/限流验收和网络栈级约束；没有外部客户端需求时不实现本应用 MCP Server。自动摘要与 Agent process guard 仍保持默认关闭，待质量/故障注入门禁后灰度。
- 发布检查器修复：Windows 使用 `npm.cmd`，缺失强制命令改为 failed；输出捕获改用临时文件，避免 Node worker 继承 pipe 后挂起；诊断脱敏 smoke 改用受守卫测试库并自清理。修复前两次 smoke 在主库留下 `diagnostic_runs` ID 36、37；精确删除未获授权，记录保留，未来 clone/hash 比较应显式解释这两个审计行。
- 会话压缩切片：新增默认关闭的自动摘要 worker；schema `0017+`、MySQL 跨进程命名锁、本地 provider 默认、远程二次许可、消息/字符预算、最近消息保留和严格结构化输出共同构成启用门槛。摘要按来源范围/hash 落到既有 `conversation_summaries`，模型输出无效不落库，原消息不删除。主库仍为 0012，因此本轮只在测试库验证，没有启用生产 worker。
- Agent 崩溃恢复切片：当 Agent API/聊天接管开关开启时，lifespan 必须先取得数据库目标专属的连接级 MySQL owner lock；第二进程 fail closed。10 秒监控发现 ownership 丢失会停止本进程运行，写入口返回 503。新 owner 启动后把孤儿 running run 确定性终结，保留 waiting checkpoint；幂等工具 execution 标 failed，非幂等标 unknown 且绝不自动重放。真实 MySQL 双 guard 竞争、取消意图、step/event 投影和悬空 lease 清理均在测试库验证。
