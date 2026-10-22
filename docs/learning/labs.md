# 隔离实验手册

实验目的是把代码机制与可观察证据对应起来。先阅读用例的 arrange、操作和断言，再执行对应套件。测试通过证明被覆盖的边界；它不能代替真实供应商、真实第三方账号、原生安装或用户任务的验收。

## 执行约定

在仓库根目录运行，使用现有依赖，不需要填写 API Key：

~~~powershell
Set-Location F:\Program\Agent
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite shared-models
~~~

[正式隔离运行器](../../scripts/run_coding_validation.py)只接受 `--suite`，没有 `-k` 或任意 pytest 参数透传。下文点名用例用于阅读和观察，执行时运行其所在套件。不要直接使用可能加载个人配置或数据库的普通 pytest 入口。

运行器为每次执行创建 `.run/coding-agent-validation/<套件>-<唯一标识>`，裁剪环境，使用临时数据库、材料及受控模型响应。该目录的 `invocation.json` 与 `pytest-result.json` 可用于核对命令、exit code 和统计。只记录这些测试事实，不复制可能包含输入或路径的完整日志到面试材料。

每次填写[实验记录](workbook.md#实验记录)：源码基线、命令、退出码、passed/failed/skipped、关键断言、限制。先把结果记为“未运行”，执行后再更新。实验中的临时 Git、补丁和命令作用于夹具目录；不要把材料换成个人项目或生产数据。

## L01 Agent 循环

**对应：**D01、D06、M06。执行：

~~~powershell
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite parallel
~~~

阅读[共享循环测试](../../tests/unit/test_agent_runtime.py)：

- 成功：`test_executes_multiple_native_tool_calls_then_returns_to_model`。列出两轮模型请求中的工具定义、call ID 与 tool result。
- 失败：`test_tool_failure_is_returned_to_the_model_for_recovery`。观察错误怎样回填，而不是直接伪造最终成功。
- 边界：`test_rejects_a_tool_batch_before_partial_execution_when_limit_is_too_low`、`test_cancellation_stops_a_non_cooperative_model_awaitable`。

**应观察：**预算不足的批次没有先执行其中一部分；取消能终止模型等待；错误回填仍占原预算。画出各步事件，区分模型输出、执行回执和最终状态。

**证据范围：**合成 ModelClient、dispatcher 与实际共享循环；不能据此声称真实模型会选择正确工具。

## L02 模型契约与原生状态

**对应：**D05、M05。按需运行：

~~~powershell
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite shared-models
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite direct-models
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite reasoning
~~~

阅读[ModelGateway](../../tests/unit/test_model_gateway.py)：

- 成功：`test_openai_gateway_drives_the_bounded_runtime_tool_loop`。
- 失败：`test_openai_stream_fails_closed_without_done_after_a_delta`。
- 重试：`test_streaming_gateway_retries_only_before_publishing_a_delta`。

再阅读[Responses](../../tests/unit/test_responses_adapter.py)：

- `test_native_state_and_phase_roundtrip_over_actual_requests`。
- `test_native_state_never_crosses_model_endpoint_or_credential`。
- `test_tampered_native_state_fails_before_request`。

**应观察：**实际 adapter 构造的 HTTP 请求与模拟 transport 回应，消息和原生状态的绑定；发布增量前后可重试的边界。比较 Chat Completions、Responses 与 Claude 的消息差异。

**证据范围：**测试名中的 actual requests 表示经过真实适配代码构造请求，不表示连接了付费供应商。

## L03 前端创建去重与事件续读

**对应：**D02、D13、M01。从仓库根目录执行：

~~~powershell
Push-Location apps\desktop
try {
  node node_modules/vitest/vitest.mjs run src/features/coding/composables/useRunStream.spec.ts src/features/coding/model/runProjector.spec.ts
} finally {
  Pop-Location
}
~~~

阅读[useRunStream](../../apps/desktop/src/features/coding/composables/useRunStream.spec.ts)：

- 成功路径：“startRun：创建→快照→续流，帧按序投影，run.terminal 收敛”。
- 失败路径：“响应丢失只读核对已创建任务，不再次调用创建”。
- 重连：“断线恢复：错误→退避重连→快照纠偏→缺口重放→续流带游标”。
- 迟到回调：“迟到回调拒绝：detach 后旧流帧不再写入”。

阅读[runProjector](../../apps/desktop/src/features/coding/model/runProjector.spec.ts)中重复事件、旧快照、补丁 unknown、合成终态的断言。

**应观察：**创建请求次数、client request ID、after sequence、generation；断线后快照与分页补齐相互配合。新连接不重复追加文本，旧回调不能覆盖当前视图。

**证据范围：**前端状态与服务替身，不能证明 Python 恢复或原生 IPC 本身可用。

## L04 存储事务与私有 IPC

**对应：**D03–D04、D26、M02–M04。执行：

~~~powershell
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite local
.venv\Scripts\python.exe -B scripts/protocol_codegen.py --check
~~~

阅读[Store](../../tests/unit/test_local_store.py)：

- 成功：`test_migration_preserves_ids_content_backup_and_is_idempotent`。
- 失败：`test_events_append_immutable_and_status_changes_rollback_together`、`test_failed_migration_rolls_back_schema_and_preserves_source`。
- 内容校验：`test_large_content_uses_verified_artifact_and_detects_tampering`。

阅读[IPC](../../tests/unit/test_local_ipc.py)：

- 成功：`test_private_pipe_auth_unicode_and_run_event_stream`。
- 拒绝：`test_pipe_rejects_untrusted_request_boundaries`。

**应观察：**失败事务不留下部分事件／状态；升级失败保留原数据；私有管道能处理中文和事件流，但不接受不可信请求边界。`--check` 仅校验生成协议与源码同步。

**证据范围：**隔离本机接口与存储；不等于安装后的 Rust sidecar 启动、应用更新或真实用户数据迁移验收。

## L05 任务限制与计划版本

**对应：**D08、M07–M08。执行：

~~~powershell
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite orchestration
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite completion
~~~

阅读[限制测试](../../tests/unit/test_local_task_constraints.py)：

- 允许：`test_only_modify_a_allows_reading_b_but_rejects_other_writes`。
- 最终守卫：`test_final_write_guard_rechecks_policy_after_approval`。
- 范围变化：`test_explicit_release_allows_only_the_requested_constraint_change`。

阅读[计划测试](../../tests/unit/test_local_planning.py)：

- 成功：`test_model_plan_read_update_and_snapshot_replay`。
- 冲突：`test_conflicts_bad_references_and_illegal_transitions_preserve_plan`。
- 旧响应：`test_late_model_plan_after_steering_is_discarded`。
- 验收：`test_plan_ticks_do_not_satisfy_missing_file_evidence`。

**应观察：**限制从用户输入派生，模型更新计划不能解除它；冲突不修改当前计划；目标变更使旧版本失效；勾选完成没有代替文件证据。

## L06 工具发现与有界并行

**对应：**D09、M09。执行：

~~~powershell
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite tool-selection
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite parallel
~~~

阅读[工具目录](../../tests/unit/test_tool_catalog.py)与[选择运行测试](../../tests/unit/test_tool_selection_runtime.py)：

- 成功：`test_search_activates_actual_definitions_without_mutating_registry_or_saving_schemas`。
- 过期：`test_stale_catalog_is_not_loaded_and_source_version_is_refreshed_on_search`。
- 执行边界：`test_loaded_documentation_disabled_after_model_request_never_reaches_approval_or_remote`。

阅读[并行工具](../../tests/unit/test_parallel_tools.py)：

- `test_read_batches_overlap_cap_two_and_writes_form_a_barrier`。
- `test_cancel_reclaims_all_reads_and_never_starts_following_write`。

**应观察：**搜索影响下一次请求的工具定义；执行前仍核对最新配置；相邻合格只读调用并发上限为 2，写调用形成屏障；取消后不启动后面的写入。

**练习：**比较全量工具 schema 与按需发现的上下文成本、遗漏风险和版本维护成本。不要把已移除的独立只读子任务当成这里的工具并行。

## L07 补丁版本冲突与局部失败

**对应：**D10、M10，案例一。执行：

~~~powershell
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite repository
~~~

阅读[补丁测试](../../tests/unit/test_local_patchsets.py)：

- 成功：`test_multi_file_crlf_bom_tail_create_delete_move_and_rollback`。
- 外部修改：`test_external_edits_at_each_boundary_preserved`。
- 局部失败：`test_second_write_failure_and_recovery_retains_later_user_edit`。
- 幂等与篡改：`test_idempotency_preview_tampering_revoke_and_large_diff`。

**应观察：**分别记录预览前、预览后、授权后、写入间隙的文件 bytes、version 和 journal。冲突时保留用户后来修改的内容；第二次写失败有已发生事实，不能报告“什么都没发生”。

**练习：**比较版本拒绝、自动三方合并与整文件覆盖。说明当前实现优先可核对和保留用户修改，复杂冲突需重新读取和生成新预览。

**证据范围：**临时文件及实际补丁服务，不修改本人工作区；成功回滚仅说明被测边界，不代表所有跨文件写入有全局原子性。

## L08 权限命令与进程生命周期

**对应：**D11–D12、M11–M12。先运行策略套件，原生命令环境齐备后再运行执行套件：

~~~powershell
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite security
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite execution
~~~

阅读[安全权限](../../tests/unit/test_security_permissions.py)：

- `test_all_ordinary_entries_keep_sandbox`。
- `test_trusted_plan_always_requires_separate_approval`。
- `test_unsupported_boundaries_fail_closed`。

阅读[执行会话](../../tests/unit/test_local_execution_sessions.py)：

- 成功：`test_yield_is_not_timeout_and_small_unicode_output_arrives`。
- 文件变化：`test_script_change_during_approval_prevents_start`。
- 回收：`test_concurrent_cancellation_and_disk_failure_still_reap_process`。
- 重启：`test_output_quota_and_restart_never_replay`。

**应观察：**批准与启动分开；yield 不等于 timeout；取消、磁盘错误和关闭仍回收所属进程树；restart 不重放未知命令。对 stderr、exit code、输出序号和 session identity 分别记录。

**前置条件：**Windows 原生沙箱及兼容 exec-host；查看[测试指南](../testing-guide.md)和[exec-host 源码](../../apps/exec-host/src/main.rs)。缺失时记录 blocked，先完成策略与代码阅读，不为学习更改系统安全策略。

## L09 上下文配对预算与来源

**对应：**D15–D16、M13。执行：

~~~powershell
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite context
~~~

阅读[指令](../../tests/unit/test_local_instructions.py)：

- 正常作用域：`test_nested_rules_do_not_leak_between_siblings`。
- 信任边界：`test_untrusted_rules_and_code_are_not_instruction_messages`。
- 审批变化：`test_rule_change_during_approval_blocks_previously_approved_write`。

阅读[历史](../../tests/unit/test_local_context_history.py)：

- `test_early_constraint_after_twelve_messages_and_tool_pairing`。
- `test_missing_result_recovered_as_unknown_without_replay`。

再在[压缩测试](../../tests/unit/test_local_compaction.py)定位预算、工具配对、source refs 和原始限制的断言。

**应观察：**整个模型请求包含规则、历史、工具定义和原生状态成本；必要内容保留，工具调用组不拆成无结果孤项；缺失回执明确标记未知，原文可续读。

**练习：**用两张表描述压缩前后消息，指出摘要丢失了什么、哪些原文仍可通过引用取回。不要把“测试通过”解释成摘要不会遗漏语义。

## L10 长期记忆与可选预算

**对应：**D17、M14。执行：

~~~powershell
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite memory
~~~

阅读[长期记忆](../../tests/unit/test_local_memories.py)：

- 成功：`test_store_persistence_versions_scope_and_forgetting`。
- 生成竞态：`test_inflight_changes_discard_generation`。
- 预算：`test_optional_memory_is_dropped_before_context_overflow`。
- 输入不足：`test_ineligible_sessions_never_call_model`。
- 关闭回收：`test_background_stop_cancels_inflight_model_and_saves_no_memory`。

**应观察：**关键词重叠和作用域决定候选；source/version 变化丢弃过期生成；可选记忆先让出上下文预算；遗忘后旧内容不能被同一来源自动复活。

**练习：**比较关键词与向量召回。当前实现成本低、行为可解释，但同义表达和隐含语义召回有限；替代方案需要索引、模型、隐私和更新策略。

## L11 任务恢复与未知副作用

**对应：**D13、D18、D25、M15、M20。执行：

~~~powershell
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite parallel
~~~

阅读[恢复测试](../../tests/unit/test_local_recovery.py)：

- 成功：`test_pause_resume_same_run_and_idempotent_steer`。
- 迟到响应：`test_late_model_response_is_discarded`。
- unknown：`test_restart_checkpoint_unknown_commands_and_expired_approvals`。
- 预算：`test_budget_exhaustion_blocks_resume`。
- 租约：`test_same_workspace_serializes_and_distinct_workspace_runs`。
- 真实进程边界：`test_real_host_start_then_service_exit_marks_unknown_without_replay`。
- 临时 Git：`test_worktree_real_git_dirty_cleanup_and_request_identity`。

**应观察：**恢复继承原预算、核对 workspace/model/checkpoint；旧审批失效；未知命令不能自动重放；工作区别名不能规避并发租约。记录实测进程用例与纯替身用例的差异。

**练习：**分别写“事件续读”“暂停运行继续”“取消后关联恢复”“崩溃后未知副作用核对”的流程，不用一个“恢复”覆盖全部语义。

## L12 完成验证纠错与观察

**对应：**D19–D20、M16。按需要执行：

~~~powershell
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite completion
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite reflection
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite observer
~~~

阅读[完成验证](../../tests/unit/test_local_completion.py)：

- 修正：`test_s1_t10_correction_uses_original_budget_and_can_pass`。
- 拒绝：`test_s1_t07_denial_cannot_be_bypassed`。
- unknown：`test_unknown_command_is_not_automatically_replayed`。
- 预算：`test_verification_retries_cannot_reset_step_budget`。

阅读[reflection](../../tests/unit/test_local_reflection.py)中的 `test_blocked_and_unknown_never_suggest_automatic_replay`；阅读[Observer](../../tests/unit/test_observer_checks.py)中的 `test_real_file_evidence_satisfies_project_check` 和 `test_user_ban_skips_configured_tests_without_retry_or_false_success`。

**应观察：**证据不足反馈回原循环；纠错仍受预算约束；用户禁止测试时标记未验证，而不是运行配置覆盖限制。把 plan tick、命令退出、文件事实和语义需求分别列出。

## L13 扩展工具草稿与材料

**对应：**D22–D23、D25、M17–M20。执行：

~~~powershell
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite workbench
~~~

这组范围较大，分两天阅读，运行一次即可：

| 子主题 | 正常路径 | 失败或竞态路径 |
| --- | --- | --- |
| [通用 MCP](../../tests/unit/test_workbench_integrations.py) | `test_general_mcp_discovery_approval_reuse_and_revocation` | `test_mcp_catalog_change_and_write_constraints_prevent_invocation` |
| 同文件的网页与浏览器 | `test_real_browser_records_dom_assertions_and_owned_screenshot` | `test_public_transport_rejects_dns_rebinding`、`test_preview_proxy_blocks_writes_cross_origin_and_allows_get` |
| [草稿](../../tests/unit/test_local_drafts.py) | `test_restart_preserves_text_references_and_request_identity` | `test_acknowledgement_preserves_new_input_and_sent_material`、`test_first_session_request_is_idempotent_after_lost_response` |
| [队列与工作区](../../tests/unit/test_workspace_features.py) | `test_queue_exactly_once_inherits_configuration_and_can_cancel` | `test_queue_restart_or_failed_run_preserves_input_without_execution`、`test_handoff_conflict_version_retry_and_retained_source` |
| [附件清理](../../tests/unit/test_attachment_storage.py) | `test_cleanup_keeps_text_and_rejects_stale_preview` | `test_shared_history_material_is_not_removed_and_missing_copy_is_reported` |

**应观察：**MCP 调用前重核项目 binding 与 schema；拒绝时未调用外部工具。旧草稿确认不覆盖新输入；失败队列保留材料；引用存在时清理不删除仍需要的数据。

**证据范围：**MCP SDK/受控 stdio 与本地浏览器夹具可以验证真实调用机制；第三方 OAuth、账号权限和远程服务业务行为须单独验证。缺少 Chromium 时浏览器用例会报告缺失或跳过，按实际记录。

## L14 备份原始字节与模型待确认

**对应：**D24、M19，案例三。执行：

~~~powershell
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite backup-recovery
~~~

阅读[备份](../../tests/unit/test_local_backups.py)：

- 成功：`test_application_roundtrip_restores_drafts_refs_and_preserves_original_files`。
- 原子性：`test_import_failure_rolls_back_records_and_attachment_files`。
- 大小：`test_real_file_size_boundary_accepts_64_mib_and_rejects_one_more_byte`。

阅读[模型恢复](../../tests/unit/test_backup_model_restore.py)：

- 字节：`test_original_numeric_bytes_load_and_reserialized_damage_is_rejected`。
- 继承模型：`test_changed_global_default_cannot_silently_replace_inherited_model`。
- 事务：`test_pending_state_write_failure_rolls_back_whole_import`。

**应观察：**payload 使用规定的 JSON 编码计算摘要，预览摘要另按整包 bytes 计算。原始 JSON 数值 `0.0`、`1.0` 与重新 stringify 的 `0`、`1` 可有不同的摘要来源；原始下载 bytes 必须保留。模型身份不匹配时进入 pending，先确认后发送；重复导入不创建第二套数据。

前端原始下载可单独阅读[backups.spec.ts](../../apps/desktop/src/api/backups.spec.ts)，其中比较 Blob 与原始字节，并验证错误响应不会生成空备份。

可选浏览器往返实验见[backup-roundtrip.spec.ts](../../apps/desktop/e2e/backup-roundtrip.spec.ts)，使用真实下载文件、临时 Python ASGI 夹具及供应商零调用断言。从仓库根目录执行：

~~~powershell
Push-Location apps\desktop
try {
  node node_modules/@playwright/test/cli.js test e2e/backup-roundtrip.spec.ts --project=chromium
} finally {
  Pop-Location
}
~~~

**前置条件：**已有 Playwright Chromium、Python 环境，1420 端口空闲或已核对为本项目测试 Vite 服务。配置会复用已有服务，先确认环境；需要安装依赖时另行安排。

**证据范围：**浏览器 UI、下载文件与隔离 ASGI 存储往返，真实文件下载不是原生 Tauri 安装验收；夹具明确拒绝供应商调用。当前材料不记录这项 E2E 已通过，按本人执行结果填写。

## 环境问题处理

| 现象 | 判断与处理 | 如何记录 |
| --- | --- | --- |
| Windows `WinError 5`，发生在 asyncio 创建管道或子进程 | 先确认是临时测试命令的管道限制。在允许这些测试子进程的执行环境复验；不修改业务逻辑来绕过 | 记录首次环境失败和复验；未经复验不写通过 |
| Node `spawn EPERM`，发生在 esbuild/Vitest 启动 | 核对已有 Node、依赖和子进程权限；在允许本地测试进程的环境复验 | 区分启动失败与断言失败 |
| Windows 无符号链接权限 | 保留测试 skip 原因；其余文件用例可继续 | 不把 skipped 计入 passed |
| exec-host 缺失、版本不符或沙箱不可用 | 按测试指南核对现有宿主；源码阅读继续，原生执行记 blocked | 不关闭沙箱或增加管理员权限来伪造通过 |
| Chromium 或 PDF/图片处理依赖缺失 | 先阅读用例，记录所缺前置条件；依赖安装另行决定 | 不把替身结果写成真实媒体／浏览器验收 |
| 测试超时或中断 | 记录退出码和已完成部分，确认运行器回收所属进程；只重跑相关套件 | 不推测全部成功 |
| 协议生成 drift | 阅读差异并确认基线；学习任务不直接重新生成源码 | 保留失败并定位具体契约 |

无需打开真实数据库、读取个人 `.env`、更改凭据或发起付费调用来完成上述主要实验。真实模型、外部 MCP/OAuth、原生安装、窗口缩放和更新验签属于另行安排的验收。
