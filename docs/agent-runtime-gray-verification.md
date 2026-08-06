# R3 Agent Runtime 灰度验证与兼容链退出提案（2026-08-06）

> 范围：`docs/remaining-work-plan-20260806.md` §6。Runtime 代码底座已存在且默认关闭；
> 本报告记录隔离环境逐开关验证、故障门禁、取消清理修复和兼容链退出标准，
> 并如实标注哪些仍需要生产授权与跨版本观察窗口。

## 1. 灰度顺序（§6.2）逐项验证证据

| 步骤 | 开关 | 证据（测试文件，全部默认关闭下可用 flag 独立回退） |
|---|---|---|
| 1. Agent Runs API 无工具 | `PA_AGENT_RUNS_API_ENABLED` | `tests/test_agent_runs_api.py`：flag 关闭 404、create/status/事件重放、注入 dispatcher 全闭环 |
| 2. 只读 safe 工具 | `PA_AGENT_RUN_READ_ONLY_TOOLS_ENABLED` | `test_agent_runs_api.py`（tool bundle 默认关/7 工具集合）、`test_tool_contracts.py` |
| 3. confirm 文件读取与审批恢复 | 同 2 的 CONFIRM 工具 | `test_tool_approvals.py`（暂停→resume→consumed、token 轮换、崩溃窗口重放）、`test_agent_run_repository.py`（waiting_approval checkpoint） |
| 4. ContextBuilder | `PA_AGENT_CONTEXT_BUILDER_ENABLED` | `test_agent_runs_api.py`（默认关/开启事件）、`test_agent_context.py` |
| 5. 非空输出验证 | `PA_AGENT_OUTPUT_VERIFICATION_ENABLED` | `test_agent_runs_api.py`（重试策略）、`test_agent_verification.py` |
| 6. RAG 工具与引用验证 | `PA_AGENT_RAG_TOOLS_ENABLED` | `test_rag_tools.py`（工具合同、durable 引用验证、伪造 quote 拒绝）、`test_rag_abstention.py`（R2.1 拒答接入工具输出） |
| 7. Chat Agent Runtime 接管 | `PA_CHAT_AGENT_RUNTIME_ENABLED` | `test_chat_agent_runtime_compat.py`（路由四分支、SSE 审批保持、断线取消、完成重连唯一消息投影、RAG 接管与回退） |
| 8. 自动摘要 worker（独立灰度） | `PA_CONVERSATION_SUMMARY_WORKER_ENABLED` | `tests/test_conversation_summary_worker.py`（不与其他步骤同批开启） |

回退性：全部为独立 env flag，关闭单个即回退，无需 schema downgrade（设计文档已声明）。

## 2. 故障门禁（§6.3）覆盖矩阵

| 故障场景 | 状态 | 证据 |
|---|---|---|
| owner lock 丢失 → 写入口 503 | ✅ 已有 | `test_agent_recovery.py`（503 门禁、MySQL 双持有者 GET_LOCK） |
| owner 监控 verify 失败 → coordinator shutdown | ✅ 本次补齐 | `tests/test_agent_process_cancellation.py::test_owner_monitor_shuts_down_coordinator_when_lock_lost`（`main_api.monitor_agent_runtime_owner` 抽出为可测函数） |
| 第二进程竞争 | ✅ 已有 | `test_agent_recovery.py`（真实 MySQL named lock） |
| API 退出/孤儿 run | ✅ 已有 | `test_agent_recovery.py`（running→failed/cancelled、created 保留、幂等 reconcile） |
| 已有取消意图/等待审批 checkpoint | ✅ 已有 | `test_agent_run_repository.py`、`test_tool_approvals.py` |
| 幂等 execution 回放 / 非幂等 unknown | ✅ 已有 | `test_agent_recovery.py`、`test_tool_executions.py`（claim 四分支、重领 lease） |
| 审批 token 轮换/一次消费/拒绝/过期 | ✅ 已有 | `test_tool_approvals.py`（reissue、并发消费恰一成功、TTL 过期） |
| SSE 断线 → 取消 | ✅ 本次补齐 | `test_chat_agent_runtime_compat.py::test_sse_disconnect_cancels_active_run` |
| 并发 continuation 唯一消息投影 | ✅ 已有 | `test_chat_agent_runtime_compat.py::test_completed_chat_run_can_reconnect_and_persist_its_answer` |
| grep_code 线程取消退让 | ✅ 本次修复 | `tool_adapter.py` 绑定 stop_event；`_grep` 检查点退让；`test_agent_process_cancellation.py`（3 项） |
| Git/legacy 子进程取消清理 | ✅ 本次修复 | `code_tools.py::_run_git/_execute_command` CancelledError 时 kill；`test_agent_process_cancellation.py`（2 项） |
| provider 精确 tokenizer 与旧聊天预算口径 | ✅ 完成（2026-08-06） | 见下节；Ollama `/api/tokenize` 在本机 404，精确 tokenizer 不可用，改用真实 usage 抽样校准 |
| compatibility telemetry 跨版本观察窗口 | ✅ 基础设施完成（2026-08-06）；窗口观察进行中 | 见 §4；持久化已上线，等待跨版本窗口积累 |

## 3. 取消清理修复明细（本次代码改动）

- `src/personal_assistant/core/code_tools.py`：新增 `_kill_process()`；`_run_git` 与
  `_execute_command` 在 `CancelledError` 时 kill 子进程并回收管道后重抛。
- `src/personal_assistant/core/projects.py`：`search_content(..., stop_event)`——to_thread
  扫描线程在文件/行之间检查事件提前退让（线程不可强杀，迟到结果由取消方丢弃）。
- `src/personal_assistant/core/tools.py`：`ToolContext.grep_stop_event`；`_grep_code_execute` 透传。
- `src/personal_assistant/core/tool_adapter.py`：grep 包装器创建 stop_event 并绑定
  `cancellation.wait()`，`finally` 无条件置位（取消/超时/正常结束都停止扫描线程）。
- `src/personal_assistant/main_api.py`：`monitor_agent_runtime_owner(guard, coordinator, interval)`
  从 lifespan 抽出为模块级可测函数，行为不变（10s 轮询、verify 失败 shutdown+退出）。

## 3.1 预算口径统一与 tokenizer 校准（2026-08-06）

**修复前**：旧聊天（`ChatService.stream_reply`）把全部历史无预算注入，远程审计用
`input_chars // 4` 估算 token；AgentRuntime/ContextBuilder 用 `ConservativeTokenEstimator`
（CJK 1:1、非 CJK /3）。三处口径分裂，且旧聊天可突破 provider `num_ctx`。

**修复**（`docs/remaining-work-plan-20260806.md` §6.3 项）：
- 旧聊天历史按 `llm_context_length`（settings 表生效值）做**从旧到新截断**，保留最近消息，
  与 Runtime 共用同一估算器（`core/chat.py` + `tests/test_chat_budget.py`）；
- 远程审计 `estimated_input_tokens` 改用同一估算器（不再用字符/4），测试断言统一口径；
- **安全系数**：真实 usage 抽样（`scripts/measure_tokenizer_accuracy.py`，
  `data/rehearsals/r3-tokenizer-20260806/`）显示纯字符公式在 5 类代表文本中 4 项低估
  （最低约 0.5x，含 chat template 固定开销），**不保证上界**；`ConservativeTokenEstimator`
  增加 `safety_factor`（默认 2.0，`PA_TOKEN_ESTIMATE_SAFETY_FACTOR` 可调），
  系数 2.0 下抽样文本估算/真实比率 1.000–2.645，**5/5 项 ≥1.0**，保守上界成立；
- 预算语义明确为"保守上界"而非精确计数；Ollama `/api/tokenize` 在本机版本返回 404，
  精确 tokenizer 不可用（如实记录），后续版本可用时再按精确计数校准系数。

## 4. 兼容链退出提案（§6.4）删除 `/tools`、`/tools/plan` 或旧 tool-call 端点**必须同时满足**以下条件，缺一不可：

1. **Runtime 模式新消息 planner 调用稳定为 0**：桌面端 `/capabilities` 返回
   `chat_execution_mode=agent_runtime` 时 `useLegacyToolPlanner=false`（已有 E2E 覆盖）；
   需要生产遥测确认 `/tools/plan` 的 `runtime_filtered` 计数为 0。
2. **跨版本观察窗口 legacy 调用为 0**：兼容遥测已持久化（2026-08-06 上线，
   schema `0021`、`PA_COMPATIBILITY_TELEMETRY_PERSIST_ENABLED=true`，每个进程一个窗口，
   退出标记 `ended_at`）。观察窗口建议：**至少覆盖一次发布升级（如 0.2.0 → 0.2.1）
   前后各 ≥14 天**，期间 `legacy_full` 与 `/tools` 调用为零、无 pending tool_call 残留。
   证据输出：`uv run python scripts/telemetry_window_report.py --since <升级前日期>`
   （`legacy_zero=true` 且窗口覆盖整个观察期）。
3. **历史 pending 调用处置**：`waiting_approval`/`pending_approval` 记录需耗尽、迁移或
   有明确人工处置方案（审批 API 的恢复链路保留到删除端点为止）。
4. **回滚一致性**：删除端点与最低支持版本同步——回滚安装旧版不再调用已删端点，或删除
   提案本身携带回滚版本要求。
5. **删除是独立变更**：单独 commit、单独回滚，不与"默认开启 Runtime"同一提交完成。

当前状态：条件 2 的持久化基础设施已就绪并开始积累窗口（自 2026-08-06 生产启用起）；
条件 1/3/4/5 尚未满足，**不提案删除任何 legacy 端点**。预算口径与 tokenizer 校准见 §3.1。

### 4.1 遥测持久化实现（2026-08-06）

- 迁移 `0021` 新增 `compatibility_telemetry` 表（scope/scope_key/path/mode/outcome/calls/
  started_at/last_flushed_at/ended_at，唯一约束 per cell）；测试库已演练
  `0020 → 0021 → 0020` 往返，主库已迁移并保留克隆
  `personal_assistant_preupgrade_20260806070435`（0020 基线）。
- `CompatibilityTelemetryPersister`（`core/compatibility.py`）：每进程一个窗口
  （scope_key=uuid），定期（默认 60s，`PA_COMPATIBILITY_TELEMETRY_FLUSH_SECONDS`）把
  增量 upsert 落库，进程退出 `flush_now(ended=True)` 标记 `ended_at`；崩溃最多丢一个间隔。
- `windowed_telemetry_summary()` 跨窗口聚合；`scripts/telemetry_window_report.py`
  输出窗口列表、legacy 分路径计数与 `legacy_zero` 判定。
- 测试：`tests/test_compatibility_telemetry.py`（增量幂等、ended 标记、跨窗口聚合）。

## 5. 未完成边界（如实记录）

- 未在生产 `.env` 开启任何 Agent Runtime 开关（`PA_AGENT_RUNS_API_ENABLED` 等保持 false）；
  灰度第 1–8 步的**生产开启**需要单独授权，本报告只提供隔离验证证据。
- provider 精确 tokenizer（Ollama `/api/tokenize`）在本机版本返回 404，不可用；
  预算以校准后的安全系数（2.0）保守估算，后续 Ollama 版本支持后再按精确计数复核。
- 跨版本观察窗口自 2026-08-06 起开始积累，但尚未覆盖一次升级周期，§6.4 条件 2 未达成。
- `grep_code` 线程不可强杀：stop_event 只能让线程在检查点退让，单次超大文件内的
  正则扫描仍会跑完；已按计划以 `supports_cancellation=False` 明确声明并丢弃迟到结果。
