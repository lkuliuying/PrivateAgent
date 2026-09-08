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
