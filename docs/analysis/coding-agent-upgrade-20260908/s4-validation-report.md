# S4 持续执行、流式输出与权限开发报告

日期：2026-09-08。环境：Windows 11（10.0.26200）、现有 Python 3.12.13 虚拟环境、Rust 工具链及桌面 Node 依赖。

## 任务总结

用户要求进入 S4 开发。本轮读取项目入口、完整 `docs/project-state.md`、S0 契约、S1–S3 相关实现和 S4 计划，核对工作区为 `F:\Program\Agent`，分支 `dev/1.0.0`，HEAD `a2208a6`，开工时工作区及暂存区干净。按先检查与计划、再实现、验证和交付的顺序完成本机执行会话、公开模型增量及桌面显示；未新增依赖、修改锁文件、提交、推送、安装或部署。

源码已接入正式本机调用链，真实十分钟命令、持续 HTTP 服务、stdin、父子进程回收及本机/代理模型流式协议完成隔离测试。此结论不包括真实 Provider、发行安装、原生文件/网络隔离或 UI p95；M1 的完整验收条件尚未全部满足。

## 实际实现与契约

### 宿主与执行会话

本机 Runtime 按账号拥有 ExecutionSessions，每工作区最多 2 个活动执行、账号最多 4 个，每 run 最多 256 条执行记录。每个活动执行独占一个 exec-host，跨模型工具调用保留到命令结束；没有复用给另一工作区，也没有空闲宿主常驻。现有 Windows Job 的所有权属于宿主，独占方案让取消一个执行时可以关闭整个宿主而不终止其他执行。

执行绑定 run、session、project、workspace、operation_id、execution_id、host_instance_id 和私有 nonce。公开记录包含宿主 SHA 与授权摘要，不包含 nonce。启动前校验宿主文件及健康握手，要求 `session_protocol=1` 和进程树终止能力；旧字段缺失默认为不可用，禁止静默改用 Python 子进程执行。正常、取消、超时和协议失败均回收专用宿主；等待退出有明确期限，失败保留 unknown/stopped=false。

| 工具 | 输入和结果 |
| --- | --- |
| `exec_command` | 结构化 argv，最多 40 项；相对 cwd；yield 默认 1000ms，范围 0–30000ms；总期限默认 600000ms。普通 run 保留最多 1 小时，显式 session 保留最多 24 小时，均受实际授权期限约束。返回 execution ID、初始输出和当前状态。 |
| `read_execution` | 当前 session 的 execution ID、cursor、有界 wait；返回 stdout/stderr chunks、next_cursor、gap、可用范围、has_more 及真实状态。 |
| `write_stdin` | 最多 8192 字符、EOF 和 expected_state_version；每次独立审批，状态变化或关闭后拒绝，不自动重试输入。 |
| `cancel_execution` | 当前 session 的执行 ID 和请求 ID；已结束时返回原状态，重复取消不重复中断清理。只有 stopped=true 才报告已停止。 |
| `list_executions` | 当前 session 最近最多 256 条记录；返回登记工具是否位于 PATH。版本号未运行探测时为 null/not_probed，审批使用实际程序文件 SHA 绑定。 |

yield 仅结束这次工具等待，不杀进程。run 保留在任务结束时清理；session 保留在正常任务结束后可继续，但会话归档/关闭进程、授权失效、项目切换、退出账号或应用关闭会清理。运行异常结束不会保留服务。撤权检查在输出监听中持续执行，服务器身份约每 15 秒重新验证，验证自身最多等待 5 秒；这不是服务器撤销后瞬时停止的保证。重启只恢复记录，不恢复进程或授权。

异步执行结束时更新最初的工具记录、ExecutionResult 和完成事件来源。即使首次调用已 yield，后续非零退出也会更新为 tool.failed，供工具卡和 S1 读取；启动成功和读取成功不等于命令验证通过。工作区变化通过有界摘要观察，不能精确归因所有磁盘变化到某一个进程。

### 输出、事件与存储

SQLite 升为 schema 6，新增 `managed_executions`、`execution_chunks`。schema 2/3/4/5 先生成 `*.pre-v6-<唯一标识>.sqlite3` 一致性备份，再事务升级，保留已有消息、补丁与上下文。重启把 starting/running 记录标为 unknown、stopped=false，禁止重放。

宿主按每次读取发送完整 UTF-8 前缀，保留未完整码点，不再等待累积 64KiB 才发首段。Python 输出采用 UTF-8 和无缓冲环境；非 UTF-8 原生程序输出仍可能显示替换字符，不承诺任意 Windows 代码页自动转码。客户端队列上限 128 帧，溢出或协议断裂失败关闭。每 100ms 或 16 块批量存储，每执行滚动保留最多 1MiB/512 块，账号正文配额 64MiB。

配额不足继续排空管道并记录 dropped_bytes/output_quota_exceeded，不冒充完整日志；当前无自动清除历史日志任务。read 的输出预算是按完整块控制的软上限：至少返回一块以推进游标，首块可能超过请求预算；API 和宿主另有帧大小上限。需要剩余保留内容时按游标翻页，已丢弃的内容无法补回。

宿主 sequence 从 0 开始，持久输出 chunk sequence 从 1 开始，run durable sequence 由 Store 事务分配，不能相互替换。高频 execution.output 事件只写游标引用及 run 游标，不重写全部工具历史；模型 delta 同样使用该事件入口。run.terminal 是传输关闭提示，复用最后 durable sequence。桌面发现缺失 run 事件时先补读所有页面；重复帧不重复追加，执行输出缺口明确显示。

### 权限与 Windows 命令

新桌面在 API 声明支持时发送 `execution_contract_version=1.0`，不再向模型暴露旧 run_project_command。新可写运行创建前探测宿主能力，缺少能力则提示升级；只读运行仍可创建。旧调用省略版本时保留原工具集合及历史批准行为，不能把旧自动批准迁移为新执行授权。

四种权限仍约束专用文件工具；exec_command 和模型 write_stdin 在所有可写档位都要求明确批准。审批分类为高风险 command.execute，预览说明当前用户可访问的项目外文件和网络，以及 session 保留与总期限。授权摘要绑定规范 argv/cwd、过滤后环境、实际程序 SHA、工作区内容版本、网络档位和生命周期。批准后重新核对身份、规则、脚本/配置、程序位置和环境，变化即拒绝此次执行。

当前文件读隔离、文件写隔离、网络隔离均报告 false。`restricted` 或 `network_policy=none` 请求直接拒绝；只允许用户明确接受 `trusted_project + approved` 的当前用户范围。没有域名级内核规则，没有管理员权限提升，Job 回收不等于沙箱。WSL/容器未引入。

继续使用现有登记命令与路径检查，不增加任意 shell、管道、内联 eval、安装依赖或下载解释器入口。cwd 可进入已授权项目子目录；缺少程序时报告程序名。`.cmd/.bat` 路径和参数拒绝 shell 元字符，经验证后使用 `cmd /d /s /c`；Rust 用 raw_arg 避免再次采用 C argv 转义，真实空格路径/参数已测试。依据：[Rust CommandExt](https://doc.rust-lang.org/std/os/windows/process/trait.CommandExt.html)、[Windows cmd 文档](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmd)。

### 模型流式与桌面

当前 Profile 明确支持 streaming 时使用共享适配器；否则调用原 complete。本机 Ollama/OpenAI 兼容模型仍只用无密钥回环服务，账号仍由原服务器验证。ConfiguredModels 保持 Profile/供应商/端点一致性检查，供应商密钥不下载。共享 OpenAI/Ollama/Claude 流解析器逐层 aclose，提前结束、损坏工具 JSON 和取消均释放 HTTP 流。

服务器新增经过原认证的 GET `/desktop/model/capabilities`，返回 `stream_protocol=1.0`；POST `/desktop/model/stream` 复用原模型请求 DTO，并增加 stream_protocol 和 attempt_id。响应是 NDJSON：`text.delta` 携带 delta；`completed` 携带完整 response；`error` 仅携带受控错误代码与 usage_complete=false。每帧都有固定请求 attempt_id 和严格递增 sequence。保留原 `/desktop/model/complete`。

代理最多 4 个推理槽位、等待槽位 1 秒、推理 180 秒、队列 32、流总量 4MiB。客户端检查类型、序号、请求归属、帧大小、结束标记与最终文本一致性。旧服务器能力接口 404 或不支持版本时，在发送推理前选择 complete；发送流式请求后失败不会偷偷重发。取消向 Runtime、HTTP 和共享取消令牌传递。未部署的旧服务器仍可使用非流式路径。

公开文本由本机生成尝试 ID，首 delta 立即写入，此后约 100ms/4096 字符合批；每次尝试最多 1MiB。流式文本不提前生成最终 assistant 消息；只有完整参数解析、工具 schema 和 S1 验证完成后才能提交最终结果。不读取供应商隐藏 reasoning 字段。缺失用量的轮次事件使用 null，UI 显示“用量未知”；run 的兼容累计字段仍保存已知部分，另有 usage_complete=false，不能据此把累计零解释为完整计量。费用保持 null。

桌面新增 ExecutionPanel：显示实际进程、退出码、归属与保留范围，允许停止单个/全部进程及明确确认 stdin。活动时约 300ms 轮询，空闲时 2 秒；输出窗口每执行最多 64000 字符。切换会话、取消请求和组件卸载有 generation/AbortController 保护。正文以 Vue 纯文本渲染并去除控制序列，HTML 不能执行。复用现有 codingHttp、私有传输及全局通知，不新增状态或弹窗系统。

### 本机接口

所有新增本机接口沿用当前账号和私有入口校验；execution ID 必须属于路径中的 session。

| 方法与路径 | 用途 |
| --- | --- |
| `GET /sessions/{id}/execution-capabilities` | 冻结 CapabilitySnapshot 加分项隔离/PTY/容量信息。 |
| `GET /sessions/{id}/executions` | 列表。 |
| `GET /sessions/{id}/executions/{execution_id}?cursor=0&wait_ms=0` | 分块续读，等待最多 30000ms。 |
| `POST /sessions/{id}/executions/{execution_id}/cancel` | execution_id/request_id。 |
| `POST /sessions/{id}/executions/{execution_id}/stdin` | execution_id/data/eof/expected_state_version；仅接受用户界面明确输入，模型走工具审批。 |
| `POST /sessions/{id}/executions/close` | 停止当前会话全部进程。 |

## 验证结果

Python 在仓库根执行，前端命令目录为 `apps/desktop`。测试使用新建 `.run/coding-agent-validation/` 临时项目、SQLite 和模拟 Provider，不连接业务数据库或付费模型。

| 实际命令 | 观察结果与证据目录 |
| --- | --- |
| `cargo build --release --locked --offline --manifest-path apps/exec-host/Cargo.toml` | 成功；未改锁文件，真实宿主测试使用生成的 release 可执行文件。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all` | 285 passed、2 skipped、2 strict xfailed，92.28 秒；`all-58a8d46d7a0f4cbdb3b31266c13a44d7`。其后异步命令终态补强由下两行定向复验。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite execution` | 最终 15 passed，11.58 秒；`execution-bcd8d385cff1484894e62cf203b8dfd8`。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite completion` | 最终 37 passed，14.43 秒；`completion-5dbb6615a0384e31b9fce8cd8e79cd56`。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite execution-duration` | 1 passed，601.41 秒；`execution-duration-75fa31c9f3bc44728c35b4be366eebd6`。真实睡眠 600 秒后正常退出，非模拟时钟；随后生命周期收尾修改由 execution 套件覆盖，未重复十分钟测试。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_legacy_validation.py` | 106 passed，10.59 秒；`legacy-c172866f562b4f8e826a6f8367b01f83`。包括原 CT6 客户端契约、共享模型/运行时和服务器代理纯单测；不等于业务数据库集成验证。 |
| `npm run test -- src/features/coding src/services/localExecutor.spec.ts src/services/privateTransport.spec.ts` | 34 个文件、217 passed，13.59 秒。 |
| `npm run build` | vue-tsc 和 Vite 成功，Vite 15.23 秒；保留现有 antd 814.47kB/超过 500kB 的拆包提示。 |
| `.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check` | `protocol codegen in sync: OK`。 |
| `.venv/Scripts/python.exe -B scripts/check_agent_v2_imports.py` | `agent_v2 dependency rules: OK`。 |
| 下方定向 Ruff | `All checks passed!`。 |
| `git diff --check` | 无输出，退出码 0。 |

```powershell
$s4PythonFiles = @(git diff --name-only -- '*.py') + @(git ls-files --others --exclude-standard -- '*.py')
& .venv/Scripts/python.exe -B -m ruff check @s4PythonFiles
```

两项 skip：环境不支持真实符号链接创建、ConPTY 探针失败。两项 strict xfail：原 G10 文件越界和 network=none 原生隔离对照仍未通过，未改成通过或删除。新链路明确禁止请求该隔离后退回普通执行。

初次宿主/IPC 测试被当前工具沙箱的 Windows 命名管道权限（WinError 5）阻止，首次 Vite 构建被 esbuild EPERM 阻止；使用经过自动审批的提升测试权限在相同临时目录策略下重跑成功，没有改产品安全设置。实现期间发现并修复了 `.cmd` 空格二次转义、HTTP 流提前结束未立即关闭、异步终态先于证据持久化、新工具进入旧请求导致上下文开销变化等问题。旧终态故障注入迁移到 Store.emit，保留事务回滚断言；旧超时测试更新为本轮明确实现的 600 秒。

另在 `.run/coding-agent-validation/s4-previous-head-ffd6781e8c2c4eb785b38715da04571d` 导出 `a2208a6` 的原源码和原模型测试，只读对照得到 18 passed、同样 3 failed：8K 窗口被 S2 预算拒绝，尚未调用 Provider。最终测试保留 8K 拒绝及无模型请求断言，增加 32K 流式成功路径；切换模型的历史/身份测试使用 32K。没有扩大生产默认窗口或降低预算保护。

## 变更文件

文件清单按职责列于本节；没有删除、移动或重命名文件。

### 执行与存储

- `apps/exec-host/src/main.rs`：增量输出、分项能力、期限和 Windows 批处理适配。
- `src/private_agent_core/execution/contracts.py`：加性宿主健康字段与期限范围。
- `src/private_agent_core/execution/exec_host_client.py`：有界队列、协议故障和可确认退出。
- `src/private_agent_local/execution_sessions.py`（新增）：有界宿主及执行生命周期。
- `src/private_agent_local/execution_store.py`（新增）：执行记录、滚动输出和重启标记。
- `src/private_agent_local/execution_tools.py`（新增）：结构化工具与审批边界。
- `src/private_agent_local/executor.py`：旧命令默认期限同步为 600 秒。
- `src/private_agent_local/files.py`：UTF-8 子进程环境、工具缺失错误与批处理 quoting。
- `src/private_agent_local/runtime.py`：工具协商、审批、生命周期及统一事件。
- `src/private_agent_local/store.py`：schema 6、备份迁移和事务序号分配。
- `src/private_agent_local/app.py`：执行 API、创建前能力检查与 durable 终态关闭提示。

### 模型与桌面

- `src/private_agent_core/llm/adapters.py`：通过 aclosing 关闭嵌套流；大部分差异为必要缩进。
- `src/private_agent_local/cloud.py`：代理能力协商、NDJSON 校验和旧接口回退。
- `src/private_agent_local/local_models.py`：本机与配置式路由的流式适配。
- `src/private_agent_local/core_adapter.py`：公开增量、唯一最终消息和未知计量。
- `src/personal_assistant/api/routes_desktop_model.py`：受认证流式代理。
- `apps/desktop/src/features/coding/api/executions.ts`（新增）：执行 API 和安全文本。
- `apps/desktop/src/features/coding/components/ExecutionPanel.vue`（新增）：执行状态、输出、停止和 stdin。
- `apps/desktop/src/features/coding/components/CodingThreadWorkspace.vue`：新契约和进程面板入口。
- `apps/desktop/src/features/coding/components/RunTranscript.vue`：公开输出与未知用量。
- `apps/desktop/src/features/coding/composables/useRunStream.ts`：缺失事件补读和去重。
- `apps/desktop/src/features/coding/model/runContracts.ts`：执行版本输入与权限文案。
- `apps/desktop/src/features/coding/model/runProjector.ts`：公开增量投影和传输终态语义。

### 测试和文档

- `scripts/run_coding_validation.py`：增加 execution、streaming、execution-duration 套件，默认 all 排除耗时专项。
- `scripts/run_coding_legacy_validation.py`：纳入原 CT6 客户端纯测试。
- `tests/unit/test_local_execution_sessions.py`（新增）：真实进程、隔离数据、审批、竞态及终态证据。
- `tests/unit/test_local_streaming.py`（新增）：Provider/代理流、损坏协议、取消与未知用量。
- `tests/coding_acceptance/test_s4_duration.py`（新增）：真实十分钟执行。
- `tests/unit/test_desktop_model.py`：服务器流式帧和错误脱敏。
- `tests/unit/test_local_completion.py`：终态事务故障注入适配。
- `tests/unit/test_local_context_history.py`、`tests/unit/test_local_patchsets.py`、`tests/unit/test_local_store.py`：真实旧 schema 测试夹具及迁移断言。
- `tests/unit/test_local_executor.py`：允许独立流式服务器夹具。
- `tests/unit/test_local_model_contract.py`：新旧版本严格工具 schema 及集合协商。
- `tests/unit/test_local_models.py`：流式 Provider 夹具及 8K/32K 边界。
- `tests/coding_acceptance/test_baseline.py`：实际 600 秒配置回归。
- `apps/desktop/src/features/coding/components/ExecutionPanel.spec.ts`（新增）：安全文本、重复/缺口与异步清理。
- `apps/desktop/src/features/coding/composables/useRunStream.spec.ts`、`apps/desktop/src/features/coding/model/runProjector.spec.ts`：分页重连、公开文本与 durable 游标。
- `docs/analysis/coding-agent-upgrade-20260908/README.md`、`s4-execution-streaming-and-permissions.md`、`s0-contract-decisions.md`：阶段状态和实际契约同步。
- `docs/analysis/coding-agent-upgrade-20260908/s4-validation-report.md`（本文件新增）：实现、验证及限制记录。
- `docs/unified-desktop-runtime.md`：schema 6、新执行批准规则与兼容说明。

## 项目记忆与交付限制

已读 `docs/project-state.md` 和本专项 S0–S3 契约/验收资料。项目状态记忆是 2026-08-31 的 E: 工作区和历史 HEAD；通过当前 Git、源码和隔离测试核对，本轮环境为 F:、S3 HEAD。遵循仓库入口的专项规定，用户未要求更新项目状态记忆，因此保留该历史文件及日期，在当前专项报告、契约和统一客户端说明记录经验证的新状态，未创建新记忆系统。

已同步 schema、能力、权限、事件序号、期限、命令适配和回退约束。S0–S3 报告的历史数字保留日期，最新入口明确指向 S4，不能把历史安装结论当作本轮发布。

剩余限制：原生文件/网络隔离与 PTY 不可用；未测真实安装后的 Tauri/PyInstaller 进程链、真实供应商兼容、UI 输出可见 p95≤1 秒和真实账号任务质量。没有自动保存完整无限日志、恢复活跃进程、域名级网络约束、自动依赖安装或通用 shell。8K 模型可能被必需上下文预算拒绝；程序版本发现目前仅可用性和 SHA，语义版本未探测。M1 仍需上述适用项真实验收。

本轮源码交付无需用户手动改配置。要使用新服务器增量接口，后续需授权部署配套服务端；未部署时按能力选择旧 complete。安装包必须捆绑匹配的新 exec-host 与校验信息，不能仅替换 UI 后宣称验收。需要回退时先停止全部受管理进程、关闭客户端并保留整个账号数据目录；schema 6 不能用旧程序覆盖写入，旧备份也不包含升级后的新数据，不通过删表或覆盖数据文件降级。

## S5 开发前置复核（2026-09-08）

用户后续要求：判断能否进入 S5；满足条件时先提交 S4，本次不开发 S5。复核基线仍为 `a2208a6`，45 个未提交文件均属于本次 S4 变更，暂存区为空；没有混入 S5 实现或其他新增工作。

结论：**具备进入 S5 源码开发的前置条件，可以提交 S4；不代表 S4/M1 的完整端到端验收已经通过。** 判断依据为 S5 文档明确列出的 S2 上下文与预算、S3 操作日志、S4 执行会话和有序事件，而不是把未通过的原生隔离探针当作成功。

| S5 前置项 | 已核对的实现与测试 | 结论 |
| --- | --- | --- |
| 上下文与预算 | ContextItem/压缩检查点保留来源；34 次请求、两次压缩、原目标约束与实际写入回归通过。 | 可供 S5 检查点引用；跨恢复运行累计预算仍由 S5 实现。 |
| 操作日志 | 多文件补丁意图、逐项落盘、部分失败、重启前后摘要核对及受保护回滚回归通过。 | 可供恢复核对；不能仅凭磁盘内容相同补造操作归属。 |
| 执行会话 | 账号/工作区/会话绑定、stdin 版本、真实服务、超时、撤权父子进程回收、重启 unknown 和禁止重放回归通过。 | 可供 S5 引用和清理；重启重新附着或关联新运行仍是 S5 工作。 |
| 有序事件与完成证据 | Store 事务序号、输出独立游标、异步失败更新原工具及 source_sequence、S1 终态事务回归通过；前轮前端补读与去重测试已通过。 | 具备恢复控制与投影的基础；S5 仍须增加控制意图、代次和检查点原子提交。 |
| 兼容与边界 | schema 6 备份迁移、旧宿主拒绝/只读保留、受限请求失败关闭、模型流断裂不重发回归通过。 | 保留现有安全限制，不为 S5 开工打开未验收能力。 |

本次实际执行 `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all`：**286 passed、2 skipped、2 strict xfailed，81.46 秒**。新证据目录为 `.run/coding-agent-validation/all-25e615d1d44242bd8b9cc1020dd057c5`；覆盖前轮最后增加的异步失败用例，未复跑十分钟专项。定向 Ruff、`scripts/protocol_codegen.py --check`、`scripts/check_agent_v2_imports.py` 和 `git diff --check` 再次通过。本次未重跑前端构建、真实 Provider 或安装包验证，没有将先前成绩冒充本次执行。

剩余原生文件/网络隔离、PTY、真实安装链、Provider 和 UI p95 限制阻止 M1 试用放行，但不直接阻止 S5 源码开发。S5 必须先完成单工作区的恢复核对、控制状态与未知副作用处理，再考虑跨工作区并发；不得直接解除账号活动任务限制、恢复过期授权或重放未知命令。这些事项本次仅核对，没有实现。

本次只补充本节和路线入口的前置结论，保留 `docs/project-state.md` 历史日期。S4 提交范围仍为原 45 个文件，不含构建产物、测试临时目录或 S5 功能；提交后不推送、不部署。
