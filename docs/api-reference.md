# API 参考

> 运行时 OpenAPI 是字段级唯一事实源：启动后访问 `http://127.0.0.1:<port>/docs` 或 `/openapi.json`。本文记录安全约束、端点分组和现代化能力边界。

## 1. 连接与认证

- 开发默认端口：`127.0.0.1:8000`。
- 安装版端口由 Tauri 动态选择。
- 非预检请求默认需要 `Authorization: Bearer <launch-token>`。
- `Host` 和 `Origin` 必须匹配 allowlist。
- SSE 重连可使用 `Last-Event-ID` 或端点定义的 `after_sequence`。

源码开发可在受控终端中设置 header；不要把 token 写入脚本或文档：

```powershell
$headers = @{ Authorization = "Bearer $env:PA_API_TOKEN" }
Invoke-RestMethod http://127.0.0.1:8000/health -Headers $headers
```

`GET /capabilities` 是不探测 Ollama/MySQL/Chroma 的轻量客户端协商端点。它只返回非敏感固定门禁：`chat_execution_mode`、`legacy_tool_planner_enabled`、`agent_read_only_tools_enabled` 和 `rag_chat_runtime_enabled`。桌面端以 `chat_execution_mode=agent_runtime` 作为唯一接管信号；此时新消息直接进入 `/chat/stream`，不调用旧 planner。端点不存在时按旧后端处理。

## 2. 核心分组

| 分组 | 路由模块 | 主要用途 |
|---|---|---|
| Health/diagnostics | `routes_health.py`、`routes_diagnostics.py` | 依赖状态、版本、迁移、兼容路径计数和脱敏诊断 |
| Sessions/chat | `routes_sessions.py`、`routes_chat.py` | 会话、消息、SSE 对话、停止和兼容 Runtime |
| Agent runs | `routes_agent_runs.py` | run、step、events、取消和审批 |
| Documents/RAG | `routes_documents.py`、`routes_document_collections.py` | 导入、重建、chunk、index version/head/rollback |
| Memories | `routes_memories.py` | 记忆 CRUD、候选、revision 和 conflict |
| MCP | `routes_mcp.py` | server 配置、发现、健康和调用审计 |
| Tools/projects/coding | `routes_tools.py`、`routes_projects.py`、`routes_coding.py` | 授权路径、计划、补丁和受控命令 |
| Backup/maintenance | `routes_backup.py`、`routes_maintenance.py` | 备份预览/演练、完整性和修复计划 |
| Personal hub | inbox/goals/reminders/today/briefings/search 等路由 | 日常工作流 |

所有 router 在 `src/personal_assistant/main_api.py` 注册。

## 3. AgentRun

功能门禁：`PA_AGENT_RUNS_API_ENABLED=true`。

主要端点：

- `POST /agent-runs`：先持久化 created run，再返回 `202`。
- `GET /agent-runs/{run_id}`：run、steps、usage 和 trace。
- `GET /agent-runs/{run_id}/events`：按 sequence 回放公开事件。
- `POST /agent-runs/{run_id}/cancel`：先持久化取消意图，再取消本进程任务。
- 审批列表、批准和拒绝：精确路径以 OpenAPI 为准。

事件类型在 `src/personal_assistant/agents/contracts.py` 的 `AgentEventType` 定义。payload 不包含模型隐式推理、raw approval token 或完整敏感输入。

## 4. Chat SSE

`routes_chat.py` 保留原有 SSE 契约。`PA_CHAT_AGENT_RUNTIME_ENABLED=true` 时，普通无 RAG/旧工具请求可映射到持久化 Runtime，并先发出 `run_id`；Ollama 原生 NDJSON delta 会映射为多个旧 `token` 事件，最后仍发送唯一 `done`，不会再重复发送完整文本。聊天 Runtime、RAG 工具和输出验证三项开关同时开启时，`knowledge_base=true` 也进入 durable Runtime；缺少任一项或请求带旧 `tool_result` 时继续走 legacy `ChatService`。

增量队列只存在于当前 API 进程，容量为 256 个片段，且只支持一个聊天 continuation 消费者。注册工具时，当前模型回合的文字会缓冲到确认没有结构化工具调用后再发布。完整回答、usage 和运行终态持久化；token 片段不逐条落库，进程重启后的重连会回退到完整回答。

客户端断开不等于删除已持久化 run。取消应调用明确端点；恢复根据 run/event sequence 读取。

## 5. 文档与版本化索引

`routes_documents.py` 包括：

- 文档列表、导入、批量导入、patch、删除、retry 和 reindex；
- legacy `/chunks/{chunk_id}`；
- versioned `/index-chunks/{chunk_id}`；
- 文档 index versions、active head、rollback 和 failed retry；
- 摘要、术语、对比、导出、OCR 和结构化抽取。

版本列表/head/rollback 的基础表来自 `0018`；当前版本化 indexing、retrieval 和 `/index-chunks/{chunk_id}` 来源详情要求 schema `0020+`。详情返回 source kind、parser version、页/字符/行范围和标题路径；来源记录缺失时返回 `409`。只打开 indexing 不会自动改变 retrieval；rollback 会同时重新验证向量/content manifest 与来源哈希。

## 6. Memory

`routes_memories.py` 提供记忆 CRUD、search、candidate、use、events、revisions、conflict list/create/resolve。版本和冲突端点需要 schema `0017+`。

删除为软删除；返回对象包含稳定 key、version、hash、重要度、有效期、敏感级别和确认时间，但不返回秘密配置。

## 7. MCP

功能门禁：`PA_MCP_ENABLED=true`。server 的 create/replace/state/delete、discover、health 和 call logs 均在 `/mcp` 下。开启全局 API 不会自动信任 server；还需 server trusted/enabled 和逐工具 allowlist。

API 不提供 raw MCP 调用参数、结果或 approval token。完整调用仍通过内部 ToolSpec/审批链执行。

## 8. 错误和兼容性

旧 `GET /tools` 与 `POST /tools/plan` 仍服务 Runtime 关闭或尚未升级的客户端，响应包含 `Deprecation: true`。聊天 Runtime 与 Agent 无副作用工具开关同时开启时，planner 不会再向旧文本 JSON 模型暴露七个 Runtime-owned 工具；现代桌面端在 `chat_execution_mode=agent_runtime` 时则完全跳过 planner。历史 `pending_approval` 旧调用仍可重载和处理，避免升级时孤立记录。`POST /chat/stream` 同时记录 `agent_runtime` 或四种互斥的 legacy 原因：Runtime 关闭、旧 `tool_result`、RAG 工具关闭、输出验证关闭。旧 `POST /tool-calls/{id}/approve|reject` 及 `GET /tool-calls[/{id}]` 也返回弃用头，并用不含 ID 的规范化 path 记录执行结果、列表模式及详情命中。上述入口都只写低基数结构化日志，并在 `GET /diagnostics` 的 `compatibility_telemetry` 返回当前进程启动以来的调用、模式与结果计数；计数会随进程重启清零，删除旧路径前应结合轮转日志和观察窗口，而不能只看一次快照。

- `401/403`：认证、Host、Origin 或 capability 拒绝。
- `404`：资源不存在或 feature gate 通过隐藏式拒绝。
- `409`：版本、序列、审批、execution claim 或并发状态冲突。
- `422`：Pydantic/JSON Schema 输入错误。
- `503`：功能开关关闭或依赖暂不可用。

调用方应按 HTTP 状态和响应 Schema 判断，不能从本地化错误文本解析控制流。字段级变化以版本控制中的 OpenAPI diff 和前端类型更新共同验收。
