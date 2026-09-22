# ContextBuilder 设计

> **2026-09-22 指令作用域修复**：内部任务解释升级为 `1.2`，用户原文保持不变，派生限制增加来源 ID、原文位置及整个任务／路径／子任务范围。“修复 A.py，B.py 只分析”保留 A 的修改要求并限制 B；没有具体路径的“这个方向先汇报不动工”作为局部原文提示交给主模型，不扩大为全局禁写。用户明确要求执行的引用内容参与解析，普通示例、文档、日志和未满足的条件不产生执行授权。任务状态提示、执行检查及 Observer 共用同一份解析结果，不新增解析模型调用。
>
> 新版本从原始目标与已生效追加指令重建策略，不将旧派生缓存再次合并为独立限制。旧任务在恢复边界核对不可变上下文中的初始消息、已应用控制记录、来源列表及目标版本，来源完整时升级；缺失或不一致时保留原有限制并说明未升级原因。权限模式、审批、已执行事实和原始历史独立保留，数据库表和外部 API 不变。发送给供应商的消息副本仍经过凭据过滤；普通代码表达式及中文标点后的指令不再因误匹配被改写。

> **2026-09-21 反思与纠错补记**：恢复协议 1.0 的任务增加有界 `reflection_state`，保存错误类别、目标摘要、尝试次数及来源索引，不复制参数、输出或错误正文。最近 4 项未解决纠错作为事实提示进入请求预算，与当前目标、工具结果及用户约束共同供模型核对；成功的无关读取不清除失败。同目标、同工作区同操作累计 3 次失败警告、4 次停止，工作区推进重新划分活跃失败周期，目标改变清除旧纠错；原累计预算不重置。达到两次可纠正失败的修改任务，在机器证据通过后追加无工具的独立上下文复核；最多 2 次，计入原模型次数、tokens、费用和有效时间。复核只提供公开问题摘要，不保存隐藏推理、不生成长期规则，不能代替机器或人工验收。纠错与复核状态进入恢复检查点摘要，详情见[反思纠错对齐记录](solutions/2026-09-21-reflection-alignment.md)。

> **2026-09-20 原生推理续接补记**：助手消息增加可选 `phase` 与内部 `provider_state`。Responses 完整输出保存在现有 SQLite 上下文 JSON 中，不改变数据库 schema；仅向匹配端点、模型及凭据的 Responses 路由原样回传。完整状态计入保守请求预算，用户原文与最近两个完整调用组仍按原规则保留；原生调用组的工具结果不做局部摘录，较早组整体转换为事实索引与工作摘要，原始记录继续保留。预算不足时停止，不裁剪加密状态。`read_context_content` 先校验原始摘要，再返回去除 `provider_state` 的公开投影；工作摘要、运行快照、事件及历史导出不携带原生状态。公开投影的分页偏移与字符数以投影正文计算，内部内容摘要仍对应原始记录。API 格式和端点进入模型配置与恢复能力指纹，活动任务路由变化后停止续接。功能边界见[本机模型直连](direct-model-execution.md#原生推理与决策续接)。

> **2026-09-20 本机化与压缩更新**：旧服务端源码已删除。当前实现、验证边界和 Codex 对齐范围见[本机化说明](solutions/2026-09-20-local-only-context.md)。下文旧服务端设计仅保留为历史参考，不是当前启动或迁移步骤。

> **2026-09-20 本机任务编排补记**：恢复协议 1.0 的运行已接通本地 `update_run_plan`。每次请求注入当前目标版本、计划、待核对状态和有来源的公开决定；原始用户目标、限制及可信指令继续按原有规则保留。压缩记录 `task_state_at_compaction`，标记计划和公开说明为模型报告，调用引用不视为验收通过；当前运行计划优先于旧摘要。计划输入上限 16000 UTF-8 字节，持久公开说明保留最近 8 条，请求中的决定摘录保留最近 4 条、每条最多 400 字符，并带 `content_ref` 供续读；完整步骤保留，必需内容超出总预算时显式阻止请求。压缩与追加指令竞争时，旧代次不能提交摘要。恢复检查点校验计划和重复观察进度的摘要，仍不重放工具或审批。设计、验证和边界见[第二步实施记录](analysis/agent-improvement-20260917/step-2-planning-context-and-recovery.md#9-2026-09-20-本地任务编排实施记录)。

> **2026-09-20 文字任务感知与解析补记**：完整用户原文继续进入模型上下文；确定性解析只提供明确约束和可核验要求，不承担完整自然语言理解。条件正文保留在 `conditions` 中，交由模型结合现场证据判断，不提前制造禁止项或无条件执行义务。解析状态和受信项目规则以用户层消息交付，外部正文不再提升为系统指令；固定系统提示声明来源及优先级。每次请求按最新任务策略生成提示和可见工具，明确撤销限制后同一运行可恢复对应工具，实际执行仍受权限模式、路径、审批和沙箱检查。详细契约及验证见[文字任务对齐记录](analysis/agent-improvement-20260917/step-1-intent-and-constraints.md#12-2026-09-20-文字任务主链对齐)。

> **2026-09-20 本机记忆补记**：主数据库现为 schema 7。长期记忆独立保存在同身份目录的 `memories.sqlite3`，不改主库版本；默认关闭，使用及生成开关、来源边界见 [记忆设计](memory-design.md)。请求组装时记忆作为可选参考先计入预算，达到压缩阈值或超限时先移除，避免挤压当前用户请求。短期压缩额外保留最近的助手分析摘录（总计最多 1200 字符、每条最多 400 字符），附来源 ID、截断标记及“未经重新核验”说明；含疑似凭据的助手正文不复制，工具调用文本不冒充已完成事实，原始用户约束与工具配对继续保留。

> **2026-09-08 S3 补记（历史记录）**：该阶段引入 schema 5，后续版本见开头补记。版本化读取的正文超过 1200 字符时，请求投影保留版本/范围元数据、1200 字符摘录和原始 ContextItem 引用；完整工具结果继续保存，不代表已向模型展示全部正文。模型可通过 `read_context_content` 续读原结果，或使用 `read_code_file` 的行/列及 `expected_version` 定位原文件。多文件补丁按各目标目录注入受信规则，首次尚未交付的规则阻断写入并要求下一轮检查；规则变化仍使活动任务失效。见 [S3 验收报告](analysis/coding-agent-upgrade-20260908/s3-validation-report.md)。

> **2026-09-08 本机 S2**：桌面主链已接入独立的上下文记录、预算和程序化压缩，见 [S2 契约与验收报告](analysis/coding-agent-upgrade-20260908/s2-validation-report.md)。本文其余 `personal_assistant/context`、RAG 与功能开关说明属于旧服务端，不是本机启用条件。

## 本机 S2 已实现约定

- `private_agent_core/context.py` 提供预算算法与 `ContextLimits`；本机 `instructions.py` 发现规则，`context_history.py` 保存原始上下文与派生检查点，`context_manager.py` 在安全模型请求边界组装。共享 `AgentRuntime.context_sink` 为可选接口。
- SQLite schema 4 增加 `context_items` 与 `context_checkpoints`。沿用 S0 `ContextItem`，内容摘要只保存在 `content_ref`；工具结果加性关联实际 execution、operation 和事件序号。原始条目不可覆盖，检查点是派生视图；旧消息首次导入标记 legacy，缺失工具正文明确标记，不恢复历史授权。
- 项目规则只沿授权项目根至目标目录发现；同一目录依次选择首个非空的 `AGENTS.override.md`、`AGENTS.md`，嵌套仅覆盖相应子树。规则源信任单独确认，不增加工具权限；不读取项目外的个人全局规则。单文件 32 KiB、总量 64 KiB、16 份；每次有界读取计算摘要，链接/编码/读取/超限错误明确报告，无效 override 不静默回退。活动任务选中规则或信任变化后，本轮写入保守阻断。
- 完整请求按 UTF-8 字节数加 25% 余量估算，另预留输出默认 2048 和 `max(512, 窗口×5%)` 安全量。估算、上次供应商实测和缓存计费分别展示。容量未知时仍显示未知，仅允许内部按 8192 保守上限尝试小请求。每次重新读取模型配置，配置版本变化清除旧 usage 校准。
- 压缩阈值取窗口的 80%（或显式 `context_limits.auto_compact_token_limit`）与“输入预算减去 `max(256, 输入预算×10%)`”的较小值，不低于零。输入硬预算先扣输出预留和安全余量，硬超限必定触发压缩条件；最多 20000 条消息，请求字节上限仍为容量的 8 倍、下限 1.5 MB、上限 64 MiB。全部用户原文和最近两个完整调用组保留，原始历史不删除。
- 活跃任务默认尝试一次模型工作摘要：最多选择 24 个非敏感来源，每项摘录最多 1000 字符，保守输入估算不超过 16000 tokens 或模型输入预算，输出最多 1024 tokens、8 项且引用必须属于提供的来源。摘要与事实索引并存，标为未经复核的数据，不授予权限或证明任务完成。调用使用当前模型和凭据，计入当前任务次数、用量、费用及有效时间；最多等待 30 秒，不自动重试，并保留至少一次主任务调用。关闭 `semantic_compaction`、预算不足、响应无效或摘要超限时使用事实索引。空闲手动压缩不额外调用模型。
- 请求中的事实索引仅含最近 12 项工具事实、4 个失败/修改/历史回答引用以及既有分析摘录。完整来源索引留在 SQLite 检查点，`archive_ref` 可作为 `read_context_content` 的 `item_id` 分页读取。原始 item ID 仍可读取全文；每页最多 6000 字符，仅允许当前会话。压缩后重新核对代次、模型配置、项目位置、规则、权限与历史末序号；取消或失效不提交半份摘要。失败保留上一完整检查点，同一超限状态不反复自动压缩。
- 一般大工具结果在请求中保留 3000 字符摘录与引用；版本化读取使用 1200 字符专用投影。单项保存最多 2 MiB、单次历史读取最多 20000 条或 64 MiB；超限明确停止。引用只能覆盖真实保存的原文，早期工具已经裁掉的尾部无法恢复。
- API：`GET /sessions/{id}/context`、扩展的 `GET /sessions/{id}/context-budget`、`POST /sessions/{id}/context/compact`（必需 `client_request_id`）、`POST /projects/{id}/instruction-trust`（`trusted`）。新建项目接受 `trust_instructions=false`。运行中压缩在安全边界排队，同会话请求互斥并返回同一活动 ID；取消时不提交半份摘要。
- `context_limits` 默认 64 次模型请求、128 次工具、3600 秒有效执行；S1 纠偏不重置预算。等待审批单独计时，每次仍最多 600 秒，保留 24 小时绝对兜底。费用未知时显示未知并依靠其他上限；相同参数、失败输出、工作区版本连续三次失败提示模型，四次停止，成功工具打断该旧连续计数。恢复协议 1.0 另外保留上文的结构化失败记录，无关成功不能清除未解决问题。
- `ModelRequest.max_output_tokens` 在共享契约、网关和 Provider complete/stream 生效；未声明输出上限能力时请求前拒绝。兼容 Provider 和真实模型窗口仍需独立验收。新客户端需与本机执行器来自同一构建，无旧服务端依赖。
- 新运行可设 `context_limits.auto_compact=false` 停止自动压缩；原始必需输入过大时仍阻断，不静默截断约束。程序回退必须理解当前主库 schema 7，禁止删表或覆盖数据库降级。本次检查点只增加 JSON 元数据，不改变数据库 schema。

## 已退役服务端的历史设计

> 以下 `personal_assistant`、功能开关、迁移与测试路径已从当前源码删除，仅说明当时实现。当前代码不执行这些步骤。

## 1. 目标

上下文构建必须回答三个问题：选了什么、为什么选、占用了多少预算。它不能把全部历史、全部记忆和全部文档简单拼接，也不能允许外部资料改变系统策略、权限或审批要求。

实现位置：

- `src/personal_assistant/context/contracts.py`：fragment、trust、selection reason、budget 和 build result。
- `src/personal_assistant/context/builder.py`：`ContextBuilder` 与保守 token 估算器。
- `src/personal_assistant/context/sources.py`：从会话、摘要、记忆和 RAG 组装候选片段。
- `src/personal_assistant/core/context_summaries.py`：带来源范围和哈希的会话摘要。
- `src/personal_assistant/agents/coordinator.py`：原生 AgentRun 接入点。

## 2. 固定优先级

构建顺序为：

1. 系统策略和 Agent 指令。
2. 当前用户请求。
3. 未完成工具调用和工具结果。
4. 最近未压缩会话窗口。
5. 已确认、未过期且非敏感的结构化记忆。
6. 带来源的 RAG 片段。
7. 覆盖更早消息的有效摘要。

前三类为强制片段。总预算不足以容纳强制片段时抛出 `ContextBudgetExceededError`，而不是静默截掉安全约束或当前请求。

## 3. 预算与降级

`ContextBudget` 为历史、记忆、RAG、摘要和总量分别设置上限。`ConservativeTokenEstimator` 在 provider 精确 tokenizer 未可用时采用保守估算。超限时按以下顺序降级：

1. 丢弃低相关、低置信 RAG；
2. 缩短旧历史窗口；
3. 使用已验证摘要覆盖更早消息；
4. 排除低重要度记忆。

系统策略、当前请求、未完成工具上下文永不因可选片段挤占而丢失。默认总预算由 `PA_AGENT_CONTEXT_MAX_TOKENS` 控制，当前默认 6000。

## 4. 信任模型与提示注入

`ContextTrust` 区分受信策略、用户输入和不可信外部数据。RAG、MCP 描述/资源/提示和工具返回都作为 JSON data envelope 注入，并显式标注来源、类型和不可信状态。

以下内容即使出现在文档或工具结果中也不生效：

- 修改系统提示或角色优先级；
- 自动授予 capability；
- 跳过工具审批；
- 暴露秘密或扩大文件路径范围；
- 把数据中的命令当作待执行指令。

最终执行权限仍由 `ValidatedToolDispatcher` 独立校验，因此上下文防护不是唯一安全边界。

## 5. 会话摘要

迁移 `0017_context_memory_facts.py` 创建 `conversation_summaries`。每个摘要保存：

- 精确起止 message ID、消息数和 source SHA-256；
- 生成 provider/model、token 使用和算法版本；
- active/superseded 状态和版本关系。

同一来源范围幂等；修正摘要生成新版本并 supersede 旧 active 版本。原始消息仍保留在数据库，摘要不是破坏性压缩。`ContextBuilder` 只让 active 摘要覆盖其声明的范围。

自动摘要 worker 已实现但默认关闭。只有 `PA_CONVERSATION_SUMMARY_WORKER_ENABLED=true` 且数据库 revision 为 `0017+` 时，lifespan 才启动 `workers/conversation_summarizer.py`。每次 tick 最多生成一个摘要，并通过 MySQL `GET_LOCK` 保证多进程只有一个生成者；候选范围受消息数、字符数和最近消息保留预算约束，生成后仍由 `ConversationSummaryRepository` 重新校验来源哈希。

摘要输出必须通过固定结构 schema，保留目标、决定、已完成/待办、约束、事实、错误、文件、工具和下一步。来源中疑似包含密钥时摘要标为 sensitive，不进入默认上下文。自动摘要默认只用本地 Ollama；若当前 provider 会把内容发送到远程，必须再显式设置 `PA_CONVERSATION_SUMMARY_ALLOW_REMOTE_PROVIDER=true`。模型输出无效时不创建记录，原始消息永不删除。

## 6. 可解释性与隐私

`ContextBuildResult` 返回 selection trace，说明片段是选中、预算排除、敏感排除、过期排除还是被摘要覆盖。`context.prepared` 公开事件只记录各区段数量、token 估算和原因，不记录文档正文、敏感记忆或完整提示词。

## 7. 接入与回滚

开启顺序：

1. schema 升到 `0017+`；
2. 保持聊天兼容路径不变；
3. 只对 `/agent-runs` 开启 `PA_AGENT_CONTEXT_BUILDER_ENABLED=true`；
4. 比较 usage、选取 trace、错误率和回答质量；
5. 再考虑聊天路径接管。

关闭该开关即可回到 Runtime 的兼容上下文组装，不删除摘要或记忆事实。不要为回滚直接删除原始消息。

## 8. 验证与已知边界

```powershell
uv run pytest -q tests/test_context_builder.py tests/test_agent_context.py `
  tests/test_memory_facts.py tests/test_chat_agent_runtime_compat.py
```

已知边界：provider 精确 tokenizer 尚未统一接管旧聊天；自动摘要 worker 已实现为默认关闭的本地优先后台任务，按来源范围/hash 写可追溯结构化摘要且不删除原消息，本轮 `11 passed`；主库已升级到 `0020`，但自动摘要 worker 仍未启用（保持默认关闭，待质量/故障注入门禁）。跨多个摘要版本的自动合并 UI 仍未提供。
