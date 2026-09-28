# S0 跨阶段契约决议

日期：2026-09-08。范围：S0-04。S0 交付时仅实现**纯类型、生成及校验**；S1 后续接入状态见第 6 节。S1–S5 接入必须使用这里的含义；不能因为类型存在就打开能力声明。

## 1. 唯一来源与兼容边界

选择 `src/private_agent_core/coding_contracts.py` 中的 Pydantic 模型为本机 Coding 扩展唯一来源。原因：当前桌面使用共享核心契约和本机 dict DTO，未通过旧 `agent_v2` JSON-RPC dispatcher 执行；让新纯核心依赖旧业务协议会重新引入业务配置/数据库依赖。

继续沿用 `scripts/protocol_codegen.py` 入口，委托 `coding_contract_codegen.py` 生成：

- `src/private_agent_core/coding_contracts.schema.json`：Draft 2020-12 的 `$defs` 束。
- `apps/desktop/src/features/coding/model/generated/codingContracts.ts`：TypeScript 类型，禁止手写副本。
- `tests/coding_acceptance/contract_examples.json`：六个最小实例，用两种验证器校验。

旧 `agent_protocol.schema.json` 仍是旧 agent_v2 协议的唯一来源，原生成物内容不变。这是两个明确命名的协议面，不是同一字段的两份实现。JSON Schema/TS 负责结构，Pydantic 附加 validator 负责证据引用、退出码、能力依赖等跨字段约束；Schema 本身不能证明磁盘证据真实。

现有 `ContractModel(extra="forbid")` 保持严格。S1 不能把新字段直接塞进旧 `AgentRunResult`，必须在应用边界生成版本化扩展，联动 GET 快照、持久化终态和 UI。旧数据缺字段映射 unknown，不补造 verified。

## 2. 字段语义与所有者

| 契约 | 冻结语义 | 产生/消费所有者 |
| --- | --- | --- |
| RunOutcome | run_id 不变；goal_outcome 为 answered/verified/unmet/blocked/unknown；requirements 按 ID 引用；passed 必须关联 evidence_ids；verified 要求所有必要项通过且无失败/未验证项 | S1 应用完成验证器产生；UI 展示；模型不能覆盖 |
| ExecutionResult | execution_id 是一次实际执行；operation_id 是本机应用分配的一次逻辑操作；outcome 是 exited/timed_out/cancelled/failed/unknown；exited 必须带真实 exit_code，1 仍是正常进程退出事实 | Rust 报事实，本机转换；由 S1/S4 接通 |
| EventEnvelope | (run_id, sequence) 唯一，sequence 从 1 开始，限 JS 安全整数；type 开放以兼容可选事件；schema_version=1.0；payload 必须由具体事件校验 | 最终由 Store 在事务内分配；S0 只冻结，当前仍是 Runtime 计算、Store 校验 |
| CapabilitySnapshot | 工具 name/version 与 execution/stdin/pty/model_streaming/output_streaming/recovery；默认 false；终端子能力依赖 execution | 本机实际探测与配置共同决定，UI 校验必需能力；不是手工全 true |
| ContextItem | item_id/session_id/run_id/ordinal/role/kind/content_ref/source/created_at；工具消息关联 tool_call_id；summary_of 保留来源；时间必须含时区 | S2 上下文服务写入，S5 按已提交游标恢复 |
| WorkspaceIdentity | project_id/workspace_id、原 root_path 与 canonical_path、git_available、initial_head、initial_dirty；Git 不可用时不造 HEAD/dirty | S3 捕获真实工作区，S5 用于锁、恢复和任务变更归属 |

S2 草案中的 `content_sha256` 收敛为 `content_ref.sha256`，不保存两个可能冲突的摘要；S2 应沿用此处字段。`source=legacy` 保留历史导入来源；摘要不产生权限。S3 的 patch_set_id 是补丁集合 ID，不能替代 operation_id；S5 checkpoint 的运行游标对应 EventEnvelope.sequence，而不是宿主输出 offset。

### 状态映射

- `completed` 只代表循环正常结束，不能映射 verified。
- `answered` 用于不要求操作验证且已完成回答的目标；`verified` 需要本机证据闭环。
- `unmet` 表示目标/验证未达成；`blocked` 表示缺少必要权限、资源或依赖；`unknown` 表示证据不足或历史缺字段。
- 进程 `exited + exit_code=1` 如何影响验证由命令语义决定。测试命令失败不与协议错误混用同一错误码。
- 取消、超时和进程失败保留各自运行状态，不能被目标结果覆盖；S1 实现准确 UI 映射。

## 3. 操作与重试

operation_id 在审批/副作用前由本机分配，绑定 run、workspace、tool_call、参数摘要和授权。一次进程尝试有独立 execution_id；重试关联同一逻辑操作，但仍须核实授权与结果。已有审批 ID 不迁移。

未知结果不自动重放，幂等键不是自动重试许可。文件与 SQLite 不是一个事务：S3 写意图与结果，S5 解决崩溃窗口；S0 没有实现操作日志或自动恢复。

## 4. 事件、版本与协商

| 版本面 | 当前值 | 不能混同 |
| --- | --- | --- |
| Tauri 私有传输 | 2 | 不是运行契约 major |
| 本机 `/health.protocol` | 1 | 不是 exec-host 协议版本 |
| exec-host | 字符串 1.0 | 宿主事件 sequence 从 0 开始，按 execution 独立 |
| 新 Coding 契约 | 字符串 1.0 | 运行事件 sequence 从 1 开始，按 run 独立 |
| SQLite | 3 | 本轮不递增；迁移时重新核对 |

后续握手要求：major 不兼容或缺少必需工具版本/能力时，创建运行前失败关闭并提示升级；未知**可选**事件可记录诊断后忽略，但其 durable 游标仍须连续；必需事件不可丢弃。UI 不能通过已有布尔能力猜测新协议可用。

S0 未实现新版握手。当前旧版本错误关闭已有前端测试，本轮新增契约验证拒绝未知协议版本。S1 接快照、S4 接增量时须各自加入真实端到端协商测试。

合成 `run.terminal` 只允许作为传输关闭提示，不能分配新的 durable sequence；当前实现与目标的差异在 S0 基线中公开，S4 接入时修正。快照与事件不得形成第二个独立计数源。

## 5. 接入顺序与变更门禁

S1 只接 RunOutcome 与命令业务结果；S2 接 ContextItem；S3 接 WorkspaceIdentity/operation 关联；S4 接事件和实际 CapabilitySnapshot；S5 复用这些字段处理恢复。新增枚举、必需字段或限制必须同步 Pydantic、codegen、样例与调用端测试。扩展不代表对生产或付费测试的授权。

## 6. S1 接入补记（2026-09-08）

- 本机应用边界已持久化 `run_outcome`，快照和终态携带同一结果；严格共享 `AgentRunResult`、旧服务端领域完成入口及 SQLite schema 3 保持兼容。
- `Requirement` 加性扩展最低验收元数据；模型不能删除初始要求。新要求的 passed 证据必须同时存在于证据索引和完整 `EvidenceRef`，带来源事件、摘要、时区时间与工作区版本；旧 S0 最小实例保留 legacy 默认值。
- `ExecutionResult.outcome` 保持原枚举；`command_kind` 和 `validation_outcome` 表达退出码含义。未知或未分类的结果不回填成功，退出码拒绝布尔值。
- 本机在每个工具调用审批前分配 operation/execution ID，命令调用把 execution ID 传给宿主。模型纠偏产生新的操作，拒绝及未知操作通过语义范围约束后续调用；S1 不自动重试未知副作用，也未实现 S3/S5 的可恢复操作日志。
- 创建运行接受可选完成契约版本 1.0，未知版本在本机 API 返回 422；旧调用可省略，旧记录展示 unknown。此扩展不是 S4 的全能力协商，私有传输和宿主协议版本不变。
- 验证沿用 `output.validation_*`，最多两次纠偏共享原任务预算。六类真实本机 ASGI 载荷位于 `tests/coding_acceptance/s1-wire-examples.json`，Python 与 Vue 测试共同消费。

实际成绩、证据扫描范围和未验证项见 [S1 验收报告](./s1-validation-report.md)。

## 7. S2 接入补记（2026-09-08）

- ContextItem 已接入 schema 4 的 `context_items`；原始模型消息由可选 `AgentRuntime.context_sink` 写入，以会话 ordinal 排序和 source_key 去重。压缩检查点为原始条目的派生视图，不从 events 再生成一套不同工具历史。
- `content_ref` 继续只有 SHA-256 和 bytes；受控续读使用 ContextItem.item_id。工具结果加性关联实际 `execution_id`、`operation_id`、`source_sequence`，三者必须成组存在；旧记录可省略。tool_call_id 上限统一到共享模型契约的 200 字符，未知结果不补造执行。
- SQLite 新表为 `context_items`、`context_checkpoints`，schema 2/3 先备份再事务升级到 4；运行/消息/原事件仍保留原有语义。检查点保存压缩前 ordinal、父版本、结构摘要与原始 source_item_ids，后续 S3 应复用这些 item/执行关联保存读取版本，不能另建无关联文件历史。
- ModelRequest 加性支持 max_output_tokens，并接通网关能力检查、三类 Provider 的 complete/stream 与服务器 DTO。旧调用可省略；新版本机请求需要配套服务器代码。S2 没有部署服务器，也没有自动恢复授权或副作用。
- 本机 API 和默认限制、失败边界、源与计量的展示见 [上下文设计](../../context-design.md)及 [S2 验收报告](./s2-validation-report.md)。S0 历史表中的 schema 3、24 轮限制保留为当时基线，不适用于 S2 主链。

## 8. S3 接入补记（2026-09-08）

- 本机运行使用冻结的 `WorkspaceIdentity` 保存项目/工作区、规范根路径、起始 Git HEAD 和 dirty 标记；根文件身份另以设备号/inode 绑定读快照及批准。内部绝对路径不进入新增补丁预览载荷。
- `private_agent_core/patches.py` 定义严格结构化输入和纯文本变换，本机 Repository/PatchService 负责 I/O。保留 `read_code_file` 等工具名称；本轮文件工具、补丁工具和收缩后的 PowerShell 工具记录版本 2。私有传输和宿主协议未改变。
- `file_snapshots` 关联 run/path/SHA，运行时读取另保存真实 execution/operation/tool_call ID，与 S2 ContextItem 来源对应。完整内容复用 Store 的有界内容引用，不另造无来源的模型历史。
- `patch_set_id` 标识不可变预览；预览调用、应用调用、回滚各有自己的 operation ID，不将它们混成一次执行。应用执行记录引用 patch_set_id，逐项日志按补丁内 sequence 排序。重复消费同一个已应用补丁不重复落盘；失败或未知补丁拒绝重放。
- 当前 SQLite schema 5 新增 `file_snapshots`、`patch_sets`、`patch_journal`；schema 2/3/4 备份后事务迁移，重启将 applying 标为 interrupted，保留意图和结果。S5 自动恢复尚未接入。
- S1 从持久化日志与当前磁盘状态生成文件证据，包括删除/目录/移动。用户回滚使原运行完成结论转 unknown，避免沿用已失效证据。实际状态机、限制及验证见 [S3 验收报告](./s3-validation-report.md)。

## 9. S4 接入补记（2026-09-08）

- Store 在同一 SQLite 事务内分配 run 的 durable sequence；宿主 sequence 从 0 开始，输出 chunk sequence 从 1 开始，三者独立。`execution.output` 只引用输出仓库游标；模型公开文本使用 `model.output.delta/finished/interrupted`，不产生另一套最终消息来源。合成 `run.terminal` 复用最后 durable sequence，仅关闭传输。
- 运行输入增加可选 `execution_contract_version=1.0`。新桌面在服务声明 API 支持时发送；新可写运行创建前探测宿主能力，缺失则拒绝。旧调用省略时保留旧工具集合；只读任务仍可使用文件工具。执行前仍检查实际宿主 `session_protocol=1` 与进程树终止能力。
- 复用 CapabilitySnapshot，未通过的 `pty/recovery` 保持 false；执行能力接口另报文件读/写隔离和网络隔离均 false。PTY 只能在实际启动探针成功后使用。模型流能力由当前 Profile 与服务器 `stream_protocol=1.0` 单独协商，不能从执行能力推导。
- SQLite 升为 schema 6，新增 `managed_executions` 和 `execution_chunks`；旧 schema 2/3/4/5 在一致性备份后事务升级。重启将活动执行记为 unknown、stopped=false，禁止重放。
- 执行会话绑定账号、项目、工作区、会话、operation、执行 ID、专用宿主和私有 nonce。每活动执行独占宿主，避免共享 Windows Job 的清理影响其他命令。账号最多 4 个、每工作区最多 2 个；会话保留必须明确批准且可关闭。
- 新命令与 stdin 均逐次审批。可信项目执行意味着当前系统用户可访问的文件及网络范围，不是原生沙箱；restricted/network=none 请求不静默降级。旧客户端命令语义保留，不能将其历史自动批准视为新执行授权。
- `ExecutionResult` 在专用宿主关闭且有界工作区核对后更新原执行记录；没有可靠退出事实时保存 unknown，不能补造进程树已停止或 S1 验证通过。具体 DTO、限制、测试与未验证项见 [S4 报告](./s4-validation-report.md)。
