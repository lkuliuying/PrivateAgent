# S0：执行基线与契约收敛开发计划

> 状态：2026-09-08 已交付基线、隔离入口、契约与早期探针；产品已知缺口保留。实际成绩见 [S0 验证报告](./s0-validation-report.md)。前置：无；原预计 3–5 人日，可选 App Server 验证未纳入。
> 返回：[总体路线](./README.md)。下一阶段：[S1](./s1-completion-and-verification.md)。

## 1. 阶段目标

确认当前统一客户端真正执行哪条链路，建立不依赖生产环境的测试入口，冻结跨阶段最小契约，并用可复现任务保留改造前基线。S0 不批量迁移模块，不启用新的自动执行权限。

本阶段结束时，应能回答：用户点发送后哪个 Runtime 接管，工具在哪里注册，审批由谁消费，结果何时落盘，哪个状态驱动 UI，以及哪些功能仅存在于旧服务端路径。

## 2. 开工输入与现有依据

- [统一客户端说明](../../unified-desktop-runtime.md)与[当前本机运行时](../../../src/private_agent_local/runtime.py)。
- [前端本机分流](../../../apps/desktop/src/services/localExecutor.ts)、[私有传输](../../../apps/desktop/src/services/privateTransport.ts)、[本机 IPC](../../../src/private_agent_local/ipc.py)。
- [本机 Store](../../../src/private_agent_local/store.py)、[共享运行时](../../../src/private_agent_core/runtime.py)。
- [服务端工具与完成入口](../../../src/personal_assistant/api/routes_agent_runs.py)、[工具引擎](../../../src/personal_assistant/agent_v2/application/tool_engine.py)。
- [协议生成器](../../../scripts/protocol_codegen.py)、[导入边界检查](../../../scripts/check_agent_v2_imports.py)。
- [本机执行测试](../../../tests/unit/test_local_executor.py)、[权限测试](../../../tests/unit/test_local_permissions.py)、[模型契约测试](../../../tests/unit/test_local_model_contract.py)。

再次读取适用 AGENTS.md、项目记忆、最新 Git 状态和构建入口；不要继承旧文档中的“测试已通过”结论。

## 3. 工作分解

| 工作项 | 开发与分析内容 | 交付物 | 验收条件 |
| --- | --- | --- | --- |
| S0-01 主链追踪 | 从 CodingComposer 到本机 API、Runtime、ModelGateway、工具、SQLite、事件投影逐跳核对；覆盖取消和批准分支 | 一张调用链与入口清单 | 每个节点有实际文件/符号，无凭文档推定的节点 |
| S0-02 能力矩阵 | 对文件读写、patch、shell、stdin、PTY、压缩、恢复、worktree、MCP 分别标注“代码存在/已接入/默认启用/测试过/安装验证过” | 能力矩阵与复用映射 | 不把服务端测试成绩填入桌面列 |
| S0-03 隔离测试入口 | 核对 Python/Node/Rust 和 fixtures；解决测试临时目录权限；阻止加载生产 conftest/数据库 | 测试说明和可复跑入口 | 两次独立新目录运行得到一致结果，错误不被忽略 |
| S0-04 契约冻结 | 审查 run 业务结果、执行结果、操作 ID、事件游标、能力协商、版本兼容 | 契约设计记录、最小样例 | S1–S5 不对同一字段给出不同含义 |
| S0-05 任务基线 | 挑选三类仓库与 30 个任务，划分开发集和留出集；保存起始代码和判定脚本 | 任务清单及基线报告 | 所有任务可重建，成功由产物/测试而非模型自评决定 |
| S0-06 早期执行风险探针 | 对当前 Rust 宿主的子进程、文件范围、网络与 PTY 做独立对照测试 | 能力探针报告 | “禁止成功”必须有对应“允许成功”对照，不把宿主根本无法启动当隔离有效 |
| S0-07 开发决议 | 汇总依赖、接口所有权、工时与延期项 | 阶段结论和下一阶段工作项 | 每个阻断项有状态，不写成默认已解决 |

建议责任分工：运行时负责人负责 S0-01/02/04，测试负责人负责 S0-03/05，熟悉 Windows/Rust 的工程师负责 S0-06；没有对应人员时由同一负责人顺序执行，不假设额外团队已经存在。

## 4. 契约冻结清单

### 4.1 已有标识的保留

继续使用 `session_id` 和 `run_id`。领域概念可对应 Thread/Turn，但不为名称一致而迁移所有 ID 或 API。已有审批、执行和事件 ID 应保留可追溯关联。

### 4.2 拟议契约及所有者

| 契约 | 拟议关键字段 | 规则与所有者 |
| --- | --- | --- |
| RunOutcome | `goal_outcome`、`requirements`、`verification_results`、`evidence_ids`、`unverified_items` | S1 完成验证器生成，模型不能直接覆盖 |
| ExecutionResult | `execution_id`、`operation_id`、`exit_code`、`outcome`、`output_ref` | 宿主报告事实，本机应用解释业务语义 |
| EventEnvelope | `run_id`、`sequence`、`type`、`schema_version`、`payload` | Store 分配序号，唯一有序事件源 |
| CapabilitySnapshot | `protocol_version`、支持工具及版本、执行/流式/恢复能力 | 本机实际探测与配置共同生成，不硬编码全为 true |
| ContextItem | `item_id`、角色、调用关联、内容引用、来源、摘要 | S2 维护模型上下文，不与 UI 文本拼接混用 |
| WorkspaceIdentity | 项目、根路径、规范化位置、Git 可用性、初始状态 | S3/S5 用于操作、锁和变更归属 |

S0-04 已核对既有 ContractModel 的严格字段校验与前端类型，选定共享 Pydantic 为新增 Coding 契约的唯一源；已实现类型、未接入语义与兼容映射以 [契约决议](./s0-contract-decisions.md) 为准。

### 4.3 兼容与演进约束

1. 优先加性字段；旧客户端收到新可选字段应保持基本读取能力。
2. 必需新能力通过握手约束；不支持时提示升级，不用静默替代路径。
3. 若继续使用现有 agent_v2 schema，应扩展其生成流程；若本机专用契约确需独立 schema，明确所有权与映射，不手写多个副本。
4. 不将新语义混入旧字段，例如把运行完成直接解释为测试通过。
5. 数据迁移版本在实际实现时按当前 `SCHEMA_VERSION` 递增，本文不预分配版本。

## 5. 测试环境与命令

### 5.1 执行前提

以下为后续开发验证命令，不是本计划编写阶段的测试成绩。Python 测试使用已有 `.venv`，不自动安装或升级依赖。选择一个新建且路径已核对的隔离目录；`pytest --basetemp` 可能清理既有目录，禁止指向工作仓库、真实账号数据或已有证据目录。

在 PowerShell 中选择工作区 `.run/coding-agent-validation/<唯一标识>` 等明确测试位置，使用 `--noconftest` 和禁用自动插件避免进入生产数据路径；无 `.env` 的隔离 cwd 与显式源码路径由测试启动器统一设置。S0-03 建议新增一个小型启动器封装这些约束，新增依赖并非默认方案。

既有定向测试命令形态：

```powershell
.\.venv\Scripts\python.exe -B -m pytest --noconftest -p no:cacheprovider -q tests/unit/test_local_executor.py tests/unit/test_local_permissions.py tests/unit/test_local_context.py tests/unit/test_local_model_contract.py
```

这是仓库根目录下的参数示意，不能原样粘贴到隔离 cwd。测试启动器须将 Python、测试文件和 pyproject 转为已核对的绝对路径，显式设置源码导入路径，在子进程禁用插件自动发现并显式加载所需 pytest-asyncio 插件；同时确认测试模块本身没有加载生产配置。不能仅凭 `--noconftest` 宣称环境已隔离。

静态和前端检查按涉及范围执行：

```powershell
.\.venv\Scripts\python.exe -B scripts/check_agent_v2_imports.py
.\.venv\Scripts\python.exe -B scripts/protocol_codegen.py --check
```

桌面目录中的 `npm run test -- <相关 spec>`、`npm run build`，以及 `cargo test --manifest-path apps/exec-host/Cargo.toml` 在后续涉及对应组件时运行。安装包集成使用[现有验证脚本](../../../scripts/verify-unified-client.py)，先读其参数与副作用范围，不把脚本名称等同于只读命令。

### 5.2 基线用例

| 用例 ID | 场景 | 要记录的基线 |
| --- | --- | --- |
| S0-T01 | 模型零工具回复“已修改” | RunOutcome/现有状态、磁盘是否变化 |
| S0-T02 | 测试退出码 1 | 工具状态、run 状态、UI 标签和模型收到的结果 |
| S0-T03 | 大文件末尾目标 | 是否可定位、读取、局部修改及截断提示 |
| S0-T04 | 24 次以上模型请求的长任务 | 实际停止阈值、原因、历史保留 |
| S0-T05 | 命令运行超过 120 秒 | 生命周期与输出可见时间 |
| S0-T06 | 待审批时取消/重启 | 授权状态、操作次数和残留进程 |
| S0-T07 | 用户原有未提交修改 | 变更归属、是否出现覆盖 |
| S0-T08 | 当前与旧客户端能力不一致 | 握手、错误展示、是否错误回退服务器 |

缺陷基线应保留明确失败结果。新增回归测试在对应修复前允许红灯，但不能为了让 S0 全绿修改预期掩盖缺陷；环境错误与产品失败分别记录。

## 6. 可选 App Server 技术验证

仅在明确纳入开发范围后进行，时间盒建议 3–5 人日，不占用本轮写计划任务的授权。沿用[既有评估](../../releases/v1.0.0/adr/evidence/ct8-app-server-spike-evaluation.md)的研究性质，重新核对版本与能力，不继承旧环境限制作为当前结论。

依次验证：固定版本握手与线程/回合创建；目标模型协议兼容；批准/拒绝/撤权是否由唯一所有者执行；增量与断流；暂停恢复；记录导入导出边界；打包体积与启动影响。不得将两套执行器同时绑定同一真实工作区任务。

结论必须为“采用、暂不采用、证据不足”之一，附对照任务和测量。只有在模型、权限、存储与维护成本均满足要求时才修订主路线。不要把能跑一个演示请求当作迁移完成。

## 7. 预计修改范围

现有文件按实际必要性修改：测试指南、统一客户端说明、协议生成/检查入口、相关本机单测。仅当探针发现直接阻断的测试问题时，做最小修复并解释原因。

已实现 `scripts/run_coding_validation.py`、`tests/coding_acceptance/` 的任务清单与夹具、[阶段能力矩阵](./s0-execution-baseline.md)和[契约决议](./s0-contract-decisions.md)。完整文件清单见 [交接报告](./s0-validation-report.md)。S0 没有批量搬迁业务实现。

## 8. 验收与回滚

- 主链每个能力均有路径证据和状态分层，G01–G13 与后续工作项可追踪。
- 定向测试环境可复跑；Windows `WinError 5` 若仍存在，不能关闭 S0-03。
- 三类仓库的任务清单、成功判定与模型预算已固定；真实模型未执行就标“待执行”。
- 跨阶段契约冲突消除，所有新增接口明确为提案或已实现。
- S0 不应引入应用数据迁移或扩大权限；测试工具可独立移除，历史证据保留。
- 提交阶段交接：实际命令、通过/失败/阻塞、能力矩阵、决议、下一步。项目记忆仅按仓库授权约定更新。
