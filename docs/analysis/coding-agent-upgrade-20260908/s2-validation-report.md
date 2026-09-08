# S2：项目指令与上下文管理验收报告

日期：2026-09-08（Asia/Shanghai）。范围：用户明确要求进入 S2 开发；阶段文档作为需求与设计参考，不作为服务器操作、发布或后续阶段授权。

## 任务总结

S2 已接入统一桌面客户端的本机 Coding 主链。项目规则按目录和独立信任状态加载；模型历史改为有序、可追溯的原始记录；每次请求重新组装并检查输入与输出预算；自动和手动压缩保存派生检查点；循环执行采用明确的次数、时长、费用与无进展边界。桌面上下文抽屉提供规则查看、信任操作、预算与压缩状态。

开工前完整读取根 AGENTS.md、项目状态记忆、S0 契约/基线及 S1 验收资料。Git 核对为 `dev/1.0.0`、HEAD `ef54b9c`，工作区干净；基线已含 S0/S1。执行前建立计划，随后完成代码实现、隔离测试、文档同步和最终差异检查。本次未提交或部署，不自动进入 S3。

验收结论限定为实现和隔离环境中的机制验证：S2 专项 30 项通过，完整本机回归 192 项通过，前端相关回归 215 项通过。夹具通过 34 次模型请求、至少两次自动压缩，继续实际创建文件并完成 S1 回读验收。真实模型是否正确理解和遵守所有自然语言规则仍需独立质量验收。

### 已冻结的实现约定

| 组件 | 已实现行为 |
| --- | --- |
| 指令来源 | 仅支持授权根到目标目录祖先链中的 AGENTS.md；单文件 32 KiB、合计 64 KiB、最多 16 份。规则记录路径、子树范围、SHA-256、优先级与信任状态。兄弟目录规则不互相注入。 |
| 信任与失效 | 默认未信任，独立确认后以专门的系统上下文项注入，并声明用户要求与应用边界优先。普通代码和工具结果保持数据角色。每次有界读取计算摘要；链接、不可读、编码或容量错误明确报告。新嵌套规则先交给下一次模型请求；活动任务规则或信任变化保守阻断本轮后续写入。规则不扩大权限。 |
| 原始事实 | SQLite schema 4 新增 context_items、context_checkpoints。ContextItem 沿用 S0 契约，按会话 ordinal 排序、source_key 幂等；工具结果关联实际 execution_id、operation_id、source_sequence。原消息、事件和执行记录的语义不变。 |
| 内容引用 | content_ref 保存 SHA-256 与字节数，续读使用 item_id。单项最大 2 MiB，单次历史读取最多 20000 条或 64 MiB。大工具结果在请求中保留 3000 字符摘录与引用，read_context_content 每次最多返回 6000 字符，并重新检查当前账号、项目和会话范围。 |
| 迁移与恢复 | schema 2/3 先生成 pre-v4 备份，再事务升级；旧消息首次使用时幂等导入并标记 legacy。缺失工具结果只补 result_unknown，重启后采用最后完整检查点，未完成压缩标记失败，不恢复历史授权或重放副作用。 |
| 请求计量 | 完整 ModelRequest JSON 的 UTF-8 字节数乘 1.25 并按实测向上校准；窗口再扣除输出预留和 max(512, 窗口×5%) 余量。80% 触发压缩、100% 硬阻断，消息数另设 80/100 软硬阈值，请求体最多 1.5 MB。估算包含指令、消息和工具 schema，不能理解为精确 tokenizer 结果。 |
| 未知窗口 | 对外容量保持未知；内部只按 8192 的保守容量尝试小请求，不伪造大窗口。每次重新读取模型配置，配置版本改变后清除旧 usage 和校准，避免混用计量。 |
| 输出约束 | ModelRequest.max_output_tokens 通过共享网关能力检查和云端 DTO 传递。OpenAI 官方端点使用 max_completion_tokens，其他 OpenAI 兼容端点使用 max_tokens，Ollama 使用 options.num_predict，Claude 使用 max_tokens；complete/stream 均已接线。未声明能力的适配器在网络请求前拒绝。 |
| 压缩 | 使用程序化事实索引，不额外调用模型。保留全部用户原文与最近两个完整调用组；历史助手回答和较早工具结果提供续读引用，保留失败与文件修改来源。每次均从原始 items 派生，记录父检查点和来源 ID；不把摘要当成执行成功或授权证明。 |
| 压缩失败 | 活动任务在安全模型边界排队，幂等请求和同会话活动请求共用检查点。提交与完成事件在事务内进行；取消或故障保留旧历史。持续超过同一阈值时只自动尝试一次；仍超硬门槛则明确停止。 |
| 执行预算 | 默认模型 64 次、工具 128 次、有效执行 3600 秒；可配置上限分别为 256、512、14400 秒。输出默认预留 2048。审批等待另行累计，每次最长 600 秒，另保留 24 小时绝对兜底。S1 纠偏不重置预算。费用缺失显示未知，其他边界继续生效。 |
| 无进展 | 相同工具、参数、失败结果和工作区版本连续三次失败时提示，四次后停止。成功工具会打断该连续计数；普通重复读取不直接判定为停滞。 |

Provider 参数的官方参考为 [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)、[Ollama 模型参数](https://docs.ollama.com/modelfile)和 [Claude Messages](https://platform.claude.com/docs/en/api/http/messages/create)。本轮适配器验证使用拦截 HTTP 的真实适配器载荷测试，没有调用这些在线模型服务。

### 接口与兼容范围

- `GET /sessions/{id}/context`：当前适用规则、信任、完整检查点、活动压缩、错误及循环预算。
- `GET /sessions/{id}/context-budget`：保留原字段，增加请求估算、输入预算、配置版本和循环状态；供应商实测与估算分别展示。
- `POST /sessions/{id}/context/compact`：必需 `client_request_id`，返回压缩 ID、状态及错误；运行中等待安全边界。
- `POST /projects/{id}/instruction-trust`：明确设置 `trusted`；新建项目可传 `trust_instructions`，默认 false。
- 创建运行可传 `context_limits`，未传时使用上表默认值。设置 `auto_compact=false` 可停止新任务的自动压缩，硬预算仍生效。

旧调用可省略 max_output_tokens 和 ContextItem 的执行关联字段。新本机客户端请求需要配套服务器的 ModelRequest 契约；旧服务器的严格 DTO 不保证接受新字段。此次没有服务器部署、安装包构建或已安装客户端升级。

## 变更文件

路径相对于仓库根；以下 44 个文件均属于本次新增或修改，未包含只读检查的文件。

| 文件 | 变更 |
| --- | --- |
| src/private_agent_core/context.py | 新增纯预算算法、指令元数据和 ContextLimits。 |
| src/private_agent_core/contracts.py | ModelRequest 增加有界输出 token 上限。 |
| src/private_agent_core/coding_contracts.py | ContextItem 加性关联实际执行来源，统一 tool_call_id 长度。 |
| src/private_agent_core/coding_contracts.schema.json | 按契约重新生成 JSON Schema。 |
| src/private_agent_core/runtime.py | 可选 context_sink 记录模型回复、工具结果和验收反馈，持久化失败阻断继续。 |
| src/private_agent_core/llm/contracts.py | 增加输出上限能力声明。 |
| src/private_agent_core/llm/gateway.py | 在请求前拒绝不支持输出上限的适配器。 |
| src/private_agent_core/llm/adapters.py | 三类 Provider 的 complete/stream 传递输出上限。 |
| src/private_agent_local/instructions.py | 新增有界规则发现、缓存、信任及安全诊断。 |
| src/private_agent_local/context_history.py | 新增原始上下文、幂等导入、受控引用和派生检查点。 |
| src/private_agent_local/context_manager.py | 新增请求边界组装、规则刷新、压缩及执行预算。 |
| src/private_agent_local/store.py | schema 4 备份迁移、表索引和中断恢复。 |
| src/private_agent_local/runtime.py | 主链接入上下文、续读工具、权限复检、审批计时及任务清理。 |
| src/private_agent_local/core_adapter.py | 模型请求预算、usage 校准与连续失败检测。 |
| src/private_agent_local/context.py | 兼容预算展示并区分估算、实测及配置版本。 |
| src/private_agent_local/app.py | 新增上下文/信任接口及能力标记，扩展运行和项目输入。 |
| apps/desktop/src/api.ts | 扩展上下文预算响应类型。 |
| apps/desktop/src/features/agent/ContextUsageRing.vue | 对估算用量增加明确标签。 |
| apps/desktop/src/features/agent/model/contextRing.ts | 估算状态的可访问标签。 |
| apps/desktop/src/features/coding/api/context.ts | 新增集中管理的上下文 API。 |
| apps/desktop/src/features/coding/api/projects.ts | 仅在本机执行器场景传递可选规则信任字段。 |
| apps/desktop/src/features/coding/components/LocalContextPanel.vue | 新增规则、预算、压缩面板及异步清理。 |
| apps/desktop/src/features/coding/components/LocalContextPanel.spec.ts | 新增状态、操作互斥、信任确认与迟到响应回归。 |
| apps/desktop/src/features/coding/components/ContextDrawer.vue | 按能力嵌入本机上下文面板。 |
| apps/desktop/src/features/coding/components/CodingThreadWorkspace.vue | 传入当前会话和本机上下文能力。 |
| apps/desktop/src/features/coding/components/NewProjectDialog.vue | 提供默认关闭的项目规则信任选项。 |
| apps/desktop/src/features/coding/model/generated/codingContracts.ts | 同步生成 ContextItem 类型。 |
| tests/unit/test_local_instructions.py | 新增指令边界、变化、注入文本和账号撤销测试。 |
| tests/unit/test_local_context_history.py | 新增原始历史、引用、幂等、关联及迁移故障测试。 |
| tests/unit/test_local_compaction.py | 新增预算、连续压缩、长任务、取消、能力和无进展测试。 |
| tests/unit/test_local_executor.py | 假服务提供可动态调整的模型配置。 |
| tests/unit/test_local_model_contract.py | 模型契约夹具补齐当前身份和配置接口。 |
| tests/unit/test_local_store.py | 对齐 schema 4 的迁移、备份和恢复断言。 |
| tests/unit/test_desktop_model.py | 断言云端 DTO 保留输出 token 上限。 |
| tests/coding_acceptance/test_baseline.py | 旧 24 轮场景改为显式预算并验证具体停止码。 |
| scripts/run_coding_validation.py | 增加 context 专项并纳入 all。 |
| scripts/run_coding_legacy_validation.py | 既有隔离入口纳入桌面模型与网关纯单测。 |
| docs/context-design.md | 区分本机 S2 与旧服务端设计，记录当前契约和边界。 |
| docs/testing-guide.md | 记录 S2 专项及适配器验证入口。 |
| docs/unified-desktop-runtime.md | 同步 schema 4、迁移和本机上下文能力。 |
| docs/analysis/coding-agent-upgrade-20260908/README.md | 更新阶段状态并区分原编制与 S2 开工基线。 |
| docs/analysis/coding-agent-upgrade-20260908/s0-contract-decisions.md | 补记 S2 实际接入及 S3 应复用的关联契约。 |
| docs/analysis/coding-agent-upgrade-20260908/s2-instructions-and-context.md | 标注已实现状态，区分原拟议设计与当前契约。 |
| docs/analysis/coding-agent-upgrade-20260908/s2-validation-report.md | 新增本报告。 |

## 验证结果

### 实际执行的最终验证

除前端命令外，工作目录为 `F:\Program\Agent`；前端命令工作目录为 `F:\Program\Agent\apps\desktop`。测试通过仓库现有隔离入口，未使用生产数据库或付费模型。

| 命令 | 观察结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite context` | 30 passed，5.31 秒。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite completion` | 37 passed。已包含在后续 all 回归中。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite local` | 56 passed，10.77 秒。已包含在后续 all 回归中。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all` | 192 passed、1 skipped、2 xfailed，44.73 秒，退出码 0。all 按现有定义不含独立 duration 长时套件。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_legacy_validation.py` | 最终复跑 99 passed，15.18 秒，退出码 0。 |
| `npm run test -- src/features/coding src/features/agent/ContextUsageRing.spec.ts src/features/agent/model/contextRing.spec.ts src/services/localExecutor.spec.ts src/services/privateTransport.spec.ts` | 33 个测试文件、215 项通过，11.97 秒；上下文新面板包含 5 项。 |
| `npm run build` | vue-tsc 与 Vite 均通过，Vite 15.84 秒；已有 antd 分块超过 500 kB 的提醒仍存在。 |
| `.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check` | protocol codegen in sync: OK。生成前也实际执行了 `.venv/Scripts/python.exe -B scripts/protocol_codegen.py`。 |
| `.venv/Scripts/python.exe -B scripts/check_agent_v2_imports.py` | agent_v2 dependency rules: OK。 |
| 下列 Ruff 命令 | All checks passed! |
| `git diff --check` | 无空白错误，退出码 0。 |

```powershell
.venv/Scripts/python.exe -B -m ruff check src/private_agent_core/context.py src/private_agent_core/contracts.py src/private_agent_core/coding_contracts.py src/private_agent_core/runtime.py src/private_agent_core/llm/adapters.py src/private_agent_core/llm/contracts.py src/private_agent_core/llm/gateway.py src/private_agent_local/context_history.py src/private_agent_local/context_manager.py src/private_agent_local/instructions.py src/private_agent_local/runtime.py src/private_agent_local/store.py src/private_agent_local/core_adapter.py src/private_agent_local/app.py src/private_agent_local/context.py tests/unit/test_local_instructions.py tests/unit/test_local_context_history.py tests/unit/test_local_compaction.py tests/unit/test_local_executor.py tests/unit/test_local_model_contract.py tests/unit/test_local_store.py tests/unit/test_desktop_model.py tests/coding_acceptance/test_baseline.py scripts/run_coding_validation.py scripts/run_coding_legacy_validation.py
```

可在本机复核的隔离调用清单位于 `.run/coding-agent-validation/context-ce9a8de8b4f14bcd8a9cfea286df21e1/invocation.json`、`all-19563aa86a0e4ac6b6a6f286c89632d8/invocation.json` 和 `legacy-5801c771062d49c0ace43b0d06e03241/invocation.json`。这些是忽略目录中的临时验证证据，不纳入项目记忆或交付文件。

### S2 场景覆盖

测试文件为 [规则测试](../../../tests/unit/test_local_instructions.py)、[历史测试](../../../tests/unit/test_local_context_history.py)和 [压缩测试](../../../tests/unit/test_local_compaction.py)。参数化用例计入上述 30 项。

| 场景 | 实际用例与断言 |
| --- | --- |
| S2-T01 | test_nested_rules_do_not_leak_between_siblings、test_nested_write_first_delivers_rules_then_rechecks_permission：祖先规则范围正确，首次嵌套写入先交付规则，后续重新检查权限。 |
| S2-T02 | test_oversized_or_invalid_rules_are_errors、test_links_unreadable_and_deletion_invalidate_cache、test_total_size_and_file_count_are_bounded、test_rule_change_during_approval_blocks_previously_approved_write：明确报错，变化后已批准写入也不执行。 |
| S2-T03 | test_early_constraint_after_twelve_messages_and_tool_pairing：16 条旧消息之后，早期禁止项仍完整进入后续请求。该断言验证保留，不等价于真实模型遵守所有自然语言约束。 |
| S2-T04 | test_idempotent_context_and_session_scoped_content、test_missing_result_recovered_as_unknown_without_replay 及 T03：跨会话引用拒绝，幂等冲突不覆盖；call/result 与真实执行/事件关联，无重复最终消息；中断只补结果未知。 |
| S2-T05 | test_request_budget_counts_schema_reserve_unknown_and_invalid_configuration、test_unknown_or_tiny_capacity_never_sends_oversized_request：schema 纳入估算、预留扣除、无效配置拒绝，未知窗口超限不发模型请求。 |
| S2-T06 | test_two_compactions_retain_original_sources_and_constraints 及长任务用例：多次压缩仍关联原始 item，用户原文不改写，保留完整调用组，之后实际写文件。 |
| S2-T07 | test_compaction_storage_failure_preserves_old_checkpoint、test_compaction_cancel_and_hard_limit_preserve_history、test_v3_context_migration_backup_and_failure_rollback：写入失败/取消保留旧历史，迁移失败回滚且备份可读。压缩不调用模型，因此不存在模型摘要流的半份提交路径。 |
| S2-T08 | test_output_limit_unsupported_capability_fails_before_provider、test_output_limit_reaches_real_adapter_payload、既有 usage 契约测试：能力不支持时前置拒绝；四种端点配置的真实适配器载荷得到输出上限；未知 usage 不冒充实测。 |
| S2-T09 | test_thirty_requests_and_two_compactions_continue_to_actual_write：34 次模型请求、至少两次自动压缩，done.txt 实际创建，S1 回读验收成功，无旧 24 轮隐形截停。 |
| S2-T10 | test_repeated_failure_stops_but_success_breaks_stagnation、test_active_and_cost_budgets_are_independent_of_approval_wait：重复失败警告与停止，成功工具打断连续失败，执行预算不重置，等待时间与已知费用独立。 |
| S2-T11 | test_configuration_change_recomputes_capacity_and_usage、test_account_revocation_after_approval_prevents_write：窗口缩小后重新判断且清除旧实测，账号撤销后不写入、不发下一模型请求。 |
| S2-T12 | test_untrusted_rules_and_code_are_not_instruction_messages：代码中的注入文本仍为工具数据，未信任 AGENTS.md 不注入系统规则。 |

### 失败、跳过与环境边界

初期受限令牌下的本机测试出现 WinError 5，前端构建启动 esbuild 时出现 spawn EPERM；使用已获批准的相同本地测试/构建命令复跑通过，没有修改权限策略或降低断言。早期失败还发现了旧测试夹具缺少新身份/配置接口、schema 预期过时，以及旧记录可能缺少 session_id 的恢复兼容路径；分别补齐夹具、更新迁移断言和增加恢复条件后复跑通过。

最终 all 的唯一 skip 来自当前宿主 ConPTY 探针：argv 控制执行可用，但 PTY 探针不满足环境前提。两个 strict xfail 是既有 S4/G10 基线，表示当前宿主没有兑现操作系统级的项目外文件和 network=none 隔离；没有把它们改为通过，也未在 S2 修改执行宿主。新增上下文实现不能被当成操作系统沙箱。

长任务夹具还暴露已有 S1 的自然语言验收推断问题：“创建 done.txt；禁止修改 protected.txt”可能把 protected.txt 也推断为必须修改的目标，触发多余纠偏。根据运行中的 output.validation_failed 及“缺少实际文件变化证据”确认；本轮未修改 S1 推断器。S2 长任务用“禁止联网”验证原文保留，早期文件禁止项仍另有 T03 保留测试。该问题作为范围外观察保留，不能据本报告宣称已修复。

## 项目记忆

已完整读取 `docs/project-state.md`，并结合根 AGENTS.md、S0 基线/契约和 S1 验收报告核对。状态记忆记录日期为 2026-08-31，包含另一工作区及旧 HEAD；与本次 `F:\Program\Agent`、HEAD `ef54b9c` 存在时间和环境差异，通过 `git status --short --branch`、`git log -5 --oneline`、`git diff --stat`、`git diff --staged --stat` 和当前源码验证，以本次证据为准。

按仓库明确的交接约定，只有用户要求更新项目记忆时才改写 `docs/project-state.md`；本次未改写该历史文件，也未创建新的记忆系统。已同步本任务涉及的持久开发文档：上下文设计、统一桌面 Runtime 说明、测试指南、专项路线、S0 契约补记和 S2 状态/报告。同步内容为 schema 4、模块边界、API、默认预算、故障恢复、兼容条件和验证入口。

已区分原计划中的 schema 3/24 轮历史基线与 S2 当前实现；历史结论继续保留，当前适用性由新补记明确说明。没有将生产安装或真实模型效果写成已完成。

## 风险、限制与假设

- 保守字节估算可能提前压缩或阻断，不能保证任意 Provider 的精确窗口。全部用户原文始终保留，必需信息过大时会明确停止；不支持无限上下文。
- 程序摘要压缩的是历史正文，依靠受控引用获取细节；不保证模型主动续读所有必要证据。真实规则遵守、推理效果和成功率未通过在线模型验收。
- 规则发现针对显式文件目标；通用命令可能操作多个目录，本阶段不静态推导其全部嵌套规则。现有文件工具已裁掉的输出尾部无法由新引用恢复；精确大文件检索和补丁属 S3。
- 若 Provider 不提供费用，金额显示未知；次数、输入和时长预算仍有效。已知费用在返回 usage 后计入，因此不能保证最后一次请求恰好不超过金额上限。
- 活动任务中规则或信任变化采用保守写入阻断，需要新任务确认现行规则后继续；不实现 S5 的自动恢复和副作用重放。
- 旧服务器对新增字段的兼容、真实账号、多平台 Provider、Tauri 安装包和已有安装数据库升级未验收；新旧客户端回退不得删表或强行降级写入 schema 4。
- 前端已执行组件交互、类型检查和生产构建，未执行安装后原生窗口的视觉验收。独立 duration 长时套件未重跑；ConPTY、操作系统隔离、现有 S1 否定文件名推断和构建体积提醒见上文。
- 本轮未安装或升级依赖，未修改锁文件、认证协议、执行宿主或部署配置，未提交、推送、打包、部署或进行付费模型调用。

## 用户需执行的操作

源码开发交付无需用户执行额外操作。后续如安排实际安装或服务器联调，应另行确认目标版本与环境，并验证真实模型/窗口和 schema 4 备份升级；这些操作不在本次开发交付范围内。
