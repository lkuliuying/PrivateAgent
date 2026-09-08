# ContextBuilder 设计

> **2026-09-08 本机 S2**：桌面主链已接入独立的上下文记录、预算和程序化压缩，见 [S2 契约与验收报告](analysis/coding-agent-upgrade-20260908/s2-validation-report.md)。本文其余 `personal_assistant/context`、RAG 与功能开关说明属于旧服务端，不是本机启用条件。

## 本机 S2 已实现约定

- `private_agent_core/context.py` 提供预算算法与 `ContextLimits`；本机 `instructions.py` 发现规则，`context_history.py` 保存原始上下文与派生检查点，`context_manager.py` 在安全模型请求边界组装。共享 `AgentRuntime.context_sink` 为可选接口，旧服务端不传时行为不变。
- SQLite schema 4 增加 `context_items` 与 `context_checkpoints`。沿用 S0 `ContextItem`，内容摘要只保存在 `content_ref`；工具结果加性关联实际 execution、operation 和事件序号。原始条目不可覆盖，检查点是派生视图；旧消息首次导入标记 legacy，缺失工具正文明确标记，不恢复历史授权。
- `AGENTS.md` 只沿项目根至目标目录发现，嵌套仅覆盖相应子树。规则源信任单独确认，不增加工具权限。单文件 32 KiB、总量 64 KiB、16 份；每次有界读取计算摘要，链接/编码/读取/超限错误明确报告。活动任务规则或信任变化后，本轮写入保守阻断。
- 完整请求按 UTF-8 字节数加 25% 余量估算，另预留输出默认 2048 和 `max(512, 窗口×5%)` 安全量。估算、上次供应商实测和缓存计费分别展示。容量未知时仍显示未知，仅允许内部按 8192 保守上限尝试小请求。每次重新读取模型配置，配置版本变化清除旧 usage 校准。
- 80% 触发压缩，100% 硬阻断；超过 80 条消息也尝试压缩，最多发送 100 条消息和 1.5 MB 请求。压缩由程序从原始记录生成事实与续读索引，不新增模型调用；全部用户原文逐项保持，最近两个完整调用组保留，较早助手和工具正文通过引用续读，不把秘密或批准正文写入摘要。多次压缩直接引用原始 item。失败保留上一个完整检查点，持续越过同一阈值只自动尝试一次。
- `read_context_content` 只接受当前会话的 item ID，最多续读 6000 字符。大工具结果在请求中只保留 3000 字符摘录与引用。单项保存最多 2 MiB、单次历史读取最多 20000 条或 64 MiB；超限明确停止。引用覆盖真实工具返回，不能恢复旧文件工具本已裁掉的尾部，精确大文件检索仍属于 S3。
- API：`GET /sessions/{id}/context`、扩展的 `GET /sessions/{id}/context-budget`、`POST /sessions/{id}/context/compact`（必需 `client_request_id`）、`POST /projects/{id}/instruction-trust`（`trusted`）。新建项目接受 `trust_instructions=false`。运行中压缩在安全边界排队，同会话请求互斥并返回同一活动 ID；取消时不提交半份摘要。
- `context_limits` 默认 64 次模型请求、128 次工具、3600 秒有效执行；S1 纠偏不重置预算。等待审批单独计时，每次仍最多 600 秒，保留 24 小时绝对兜底。费用未知时显示未知并依靠其他上限；相同参数、失败输出、工作区版本连续三次失败提示模型，四次停止，成功工具打断该连续计数。
- `ModelRequest.max_output_tokens` 在共享契约、网关、Provider complete/stream 及复用此类型的云端 DTO 生效；未声明输出上限能力时请求前拒绝。兼容 Provider 和真实模型窗口仍需独立验收。新客户端需配套的服务器代码，本次未部署。
- 新运行可设 `context_limits.auto_compact=false` 停止自动压缩；原始必需输入过大时仍阻断，不静默截断约束。程序回退必须理解 schema 4，禁止删表或覆盖数据库降级。详尽字段、测试及限制见 S2 报告。

> 状态：有预算、可解释、信任分级的 ContextBuilder 已实现；仅在 `PA_AGENT_CONTEXT_BUILDER_ENABLED=true` 时接管原生 AgentRun。

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
