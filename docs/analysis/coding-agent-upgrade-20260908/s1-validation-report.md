# S1 可信完成与验证闭环：开发交付与验收报告

日期：2026-09-08（Asia/Shanghai）。工作区：`F:\Program\Agent`，分支 `dev/1.0.0`，接手 HEAD `8dcfa7f`。本报告对应用户要求“进行 S1 阶段的开发”。阶段计划是需求和设计输入，不是执行其余阶段、发布或服务器操作的授权。

## 任务总结

S1 开发及本机隔离验证已完成。明确修改任务不能靠零工具回答宣称完成，pytest 退出 1 会作为失败反馈回同一个 Agent 循环；文件证据经过独立磁盘回读，测试证据在工作区变化后过期。桌面按目标结果显示已回答、已验证、未完成、受阻和未知，历史 completed 不再默认显示成功。

S1 专项 37 项、本机全套 162 项、旧服务端纯单测 56 项、桌面相关 200 项通过。全套另有 1 项 PTY 跳过、2 项 G10 严格预期失败，均公开保留，不能计入通过。真实账号、付费模型、生产数据库、安装升级及完整 OS 隔离没有因此获得验收结论。

## 实施计划与完成情况

保留 Tauri/Vue、共享 AgentRuntime、本机 FastAPI/SQLite 和 Rust exec-host 架构；先新增 T01/T02 红灯回归，再实现纯契约/命令解释、持久化事实加载、共享循环验证、前端投影和同源验收。没有另建 Agent 循环、迁移业务仓储、变更依赖或扩大命令权限。

| 工作项 | 实际实现 | 验收依据 |
| --- | --- | --- |
| S1-01 结果语义 | 沿用冻结的 RunOutcome/ExecutionResult；扩展 Requirement 和 EvidenceRef，生成 Schema/TS；旧记录 unknown | 契约测试、生成校验、同源载荷 |
| S1-02 命令结果 | 保存真实退出、超时、取消、启动失败和未知；按命令类别解释业务结果；失败输出送回模型 | 本机 T02/T03/T09、真实宿主及组件回归 |
| S1-03 要求与证据 | 可见最低要求；独立文件回读、来源事件关联、工作区版本/摘要、产物存在、manual 未验证 | T01/T04/T05/T06/T08 及边界测试 |
| S1-04 主链接入 | 本机 Runtime 注入验证器；最多两次纠偏共享原预算；拒绝和未知范围阻止绕行；结果/消息/终态同事务 | T07/T10/T11、原共享核心回归 |
| S1-05 桌面投影 | 正文、头部、上下文抽屉共用结果语义；命令显示真实结果；刷新纠偏后的执行事实，隔离迟到请求 | 200 项桌面相关测试及构建 |
| S1-06 回归与交接 | S1 专项、本机、宿主、契约、旧纯单测、前端验证；更新本报告及既有说明 | 下列实际执行记录；业务数据库集成单独标未验证 |

## 实现决议与边界

### 结果与 API

- `ExecutionResult.outcome` 仍为 `exited | timed_out | cancelled | failed | unknown`，正常非零退出属于 exited。另用 `command_kind` 和 `validation_outcome` 表示业务含义，替代 S1 草案混用 succeeded 的方案。
- pytest 退出 1 是测试失败；搜索类别 1 是正常无匹配。受审查开发命令按 0 通过。任意 Python/Node 脚本、PowerShell 的退出 0 不被推定为业务验证通过；pytest 的版本、帮助和仅收集参数不能代替测试。
- 创建运行接受可选 `completion_contract_version=1.0` 与最多 32 个显式要求，未知版本返回 422；旧客户端可省略版本。本机前端自动附带该版本，旧服务端创建输入保持原状。模型不能删除初始要求。
- `run_outcome` 同时存在于持久化记录、GET 快照和终态事件；顶层 `goal_outcome` 为兼容读取的派生值。SQLite 保持 schema 3，仅扩展既有 JSON。共享 `AgentRunResult` 保持严格，不直接填入额外字段。
- 生命周期 completed 只表示循环结束。准确报告受阻或未知时可以 completed，但目标仍为 blocked/unknown。已知要求未满足在纠偏用尽后为 unmet；取消、超时、预算耗尽保留原生命周期。旧记录缺证据时按 unknown 投影，不回写或补造通过。

### 要求、证据与授权

- 最低要求来自用户请求、受审查意图规则及本轮工具事实，展示在任务正文。解释可零工具 answered；仅方案/预览可 answered。预览拦截后的写入请求不能反过来变成必须执行的要求。
- 文件要求验证实际变化、写后摘要和最终回读；产物要求验证存在及摘要。二者都不证明功能正确。仅生成补丁文本不足以满足落盘要求。
- 新证据关联 run、operation、真实工具调用/执行标识、来源事件序号、内容摘要、时区时间和工作区版本。纯回答和产物核对不虚构 execution ID；manual 不伪造用户验收记录。
- 测试与命令证据在执行前后及最终结算核对工作区。扫描上限为 10,000 文件、64 MiB，排除既有忽略目录、常见缓存和受保护路径；读取不完整、链接或超限返回未知。单文件回读沿用 1 MiB 上限。受跟踪文件再次变化时，旧验证不能复用。
- 审批仍绑定工具、参数、预览和项目位置；增加 operation、参数摘要和拒绝范围。命令影响范围不能静态证明时保守关联整个项目，同轮拒绝或未知副作用后不能通过换工具、路径参数或命令重试绕行。新的明确指令应创建新运行，本阶段没有运行中撤销拒绝的权限升级路径。

### 纠偏、事务与宿主

- 沿用 `output.validation_started/passed/failed`。验证失败的具体本机事实送回原模型上下文；最多两次输出验证纠偏，复用原步骤、工具调用和时长预算，不重置计数。
- 可补救的 unmet 进入纠偏。拒绝、环境受阻或未知不触发自动权限调整、依赖安装或云端执行。验证器异常使用安全错误类别并失败关闭；空回答不能变成通过。
- 结果、最终助手消息和运行终态在既有 SQLite 事务中提交。写消息或写终态失败后重新读取已提交状态，不能把已回滚的内存成功事件再次保存。测试同时注入了消息插入失败及终态写后异常。
- 宿主先发 cancelled、后发携带超时原因的 exited；适配器等待终态并收齐有界输出，区分取消与超时，不伪造退出码。通信/输出不完整保留 unknown。每次调用关闭专用宿主，真实测试核对进程回收。

## S1-T01 至 S1-T12 验收矩阵

后端用例均在 `tests/unit/test_local_completion.py`；前端消费同一份实际 ASGI 载荷。测试模型和故障命令是明确替身，本机 API、SQLite、文件回读、共享 Runtime 和投影为真实实现。

| 用例 | 直接检查 | 结果 |
| --- | --- | --- |
| T01 | `test_s1_t01_zero_tool_file_claim_is_unmet`：明确写文件、零工具声称完成 | unmet，磁盘无变化；S0 G01 转为普通回归 |
| T02 | `test_s1_t02_failed_test_reaches_same_model_loop`：pytest 退出 1 | 模型收到真实失败和输出，API/UI 不误报成功；S0 G02 转为普通回归 |
| T03 | `test_s1_t03_search_empty_is_normal` 及命令类别判定 | 空搜索正常；未新增 rg/grep 执行授权 |
| T04 | `test_s1_t04_fake_file_result_is_not_evidence` | apply 返回值不能代替磁盘证据 |
| T05 | `test_s1_t05_preview_respects_user_scope`、被拦截写入后的预览 | 落盘任务 unmet；明确预览 answered 且文件不变 |
| T06 | `test_s1_t06_test_evidence_expires_after_write`、外部磁盘变更负例 | 工具修改或外部变化均使旧测试证据失效 |
| T07 | `test_s1_t07_denial_cannot_be_bypassed` | 同文件、替代命令及受控 PowerShell 绕行均被阻止 |
| T08 | `test_s1_t08_explanation_needs_no_tools` | 纯解释 answered，不要求副作用 |
| T09 | 执行故障参数化、取消持久化、真实 exec-host 测试 | 超时/取消/启动失败/通信未知独立保存，保留部分输出，无假退出码 |
| T10 | 验证异常、可纠偏成功、`test_verification_retries_cannot_reset_step_budget` | 至多两次纠偏；原预算有效；异常失败关闭 |
| T11 | `test_s1_t11_final_transaction_never_publishes_early_success` 两种注入 | 没有提前持久化已验证终态；回滚后结果 unknown |
| T12 | legacy 回归、`runOutcome.spec.ts` 同源快照/事件重放 | 旧记录 unknown，重复帧幂等；未知版本和不完整证据保守处理 |

额外覆盖了只读 manual、禁止命令但仍保留测试要求、用户不能删减最低要求、未知副作用禁止自动重放、空回答、产物检查，以及 UI 切换运行时迟到请求和重用 tool_call_id 的隔离。

## 验证结果

下列命令均实际执行。默认工作目录为仓库根目录，npm 命令工作目录为 `F:\Program\Agent\apps\desktop`。没有用历史 S0 成绩代替本轮执行。

| 命令 | 最终观察结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite completion` | 37 passed |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all` | 162 passed、1 skipped、2 xfailed；27.76 秒，退出 0 |
| `.venv/Scripts/python.exe -B scripts/run_coding_legacy_validation.py` | 56 passed；原有共享 Runtime、验证和假成功门禁纯单测，无业务 DB 连接 |
| `npm run test -- src/features/coding src/services/localExecutor.spec.ts src/services/privateTransport.spec.ts` | 30 个文件，200 passed |
| `npm run test -- src/features/coding/components/CodingExecutionRefresh.spec.ts` | 新增测试的类型空值修正后，2 passed |
| `npm run build` | `vue-tsc --noEmit` 和 Vite 生产构建通过；保留既有大 chunk 警告 |
| `.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check` | `protocol codegen in sync: OK` |
| `.venv/Scripts/python.exe -B scripts/check_agent_v2_imports.py` | `agent_v2 dependency rules: OK` |

定向静态检查实际命令：

```powershell
.venv/Scripts/python.exe -B -m ruff check --select E,F,I --ignore E501 src/private_agent_core/coding_contracts.py src/private_agent_core/completion.py src/private_agent_core/runtime.py src/private_agent_core/verification.py src/private_agent_local/app.py src/private_agent_local/completion.py src/private_agent_local/core_adapter.py src/private_agent_local/executor.py src/private_agent_local/runtime.py src/private_agent_local/store.py tests/unit/test_local_completion.py tests/unit/test_local_exec_host.py tests/unit/test_local_executor.py tests/unit/test_local_permissions.py tests/coding_acceptance/test_baseline.py tests/coding_acceptance/test_contracts.py scripts/run_coding_validation.py scripts/run_coding_legacy_validation.py scripts/coding_contract_codegen.py
```

结果为 `All checks passed!`。生成时实际运行过 `.venv/Scripts/python.exe -B scripts/protocol_codegen.py`，其后 --check 确认同步。未修改依赖或锁文件。

最终审查执行了 `git diff --check`、`git diff --staged --stat` 和 `git status --short --branch`：没有差异空白错误，暂存区为空，原有 S0 与本次 S1 改动均保留在工作区。Git 对已有 `scripts/protocol_codegen.py` 给出 CRLF 将转换为 LF 的提示，不是失败。通过 `.venv/Scripts/python.exe -B -` 的标准输入检查本报告 45 个文件均存在且为无 BOM 的 UTF-8，7 份文档的 55 个本地链接有效，两份契约/载荷 JSON 可解析；没有把 `.run` 或桌面 dist 加入交付清单。

可复核的本轮原始记录：

- [本机全套统计](../../../.run/coding-agent-validation/all-172f15e07b754b06812ee424e9e7b0d2/pytest-result.json)及同目录 `invocation.json`。
- [S1 专项统计](../../../.run/coding-agent-validation/completion-a21ff41d24d64f2eb11a8856b2348bdd/pytest-result.json)。
- [旧纯单测统计](../../../.run/coding-agent-validation/legacy-3134fba56897433e8eefd77c6ae1fd70/pytest-result.json)。此套件确实导入必要业务配置/数据库类型，但使用隔离配置且不连接业务数据库；不能误写为“没有导入业务模块”。
- 同源载荷 [s1-wire-examples.json](../../../tests/coding_acceptance/s1-wire-examples.json) 来自 `.run/coding-agent-validation/completion-12815925bb264a92ac002a9d15290a79/s1-wire/*.json` 的六个实际导出，后续全套继续校验其 Schema/业务不变量并另行生成当前运行实例。

`.run` 是本地保留的忽略目录，不是本次交付到仓库的生成产物；持久交付事实由本报告、契约样例和可复跑测试记录。

### 失败、阻塞与修正记录

- T01/T02 首轮红灯因尚无 `goal_outcome` 失败，随后接入完成验证才转绿，没有只修改 UI 遮掩后端问题。
- 初次本机回归中，受限 Windows 子进程出现 `WinError 5`；另有旧通用测试提示误触发修改要求及命令替身缺少新增 execution_id 参数。分别在自动审核许可后原命令复跑、修正夹具意图和替身签名；保留原断言目标。
- 默认环境无法启动 esbuild（EPERM），获准在开发环境运行相同 npm 命令后通过，没有放宽产品执行权限。
- 真实超时测试暴露 cancelled 先于 exited 的宿主事件顺序，修正后保留超时原因和部分 stdout；协议失败测试同时验证关闭宿主。
- 旧纯单测首次因清理环境后缺少 Windows 用户名/临时用户目录而收集失败；补充固定测试用户名和临时目录后 56 项通过，没有读取实际用户配置。
- 最后补充预览负例时发现被拦截请求被误算为必须写入，修正后专项 37 项通过。新增 UI 测试首次构建触发 TS2769（可选 props 传给 Object.keys），增加空值处理后定向 2 项与构建通过；断言仍要求实际加载一条事实。
- 保留的 skipped：`test_host_pty_requires_successful_argv_control`，当前 ConPTY 探针不成功。保留的两个 strict xfail：`test_host_file_scope_with_allowed_control`、`test_host_network_none_with_allowed_control`，当前可信项目命令未实现所宣称的完整 OS 文件/网络隔离。这是既有 G10/S4 工作，不是 S1 通过项。

## 变更文件

下列清单只列本次实际新增或修改的文件。部分 S0 文件在接手前已未跟踪，本次是在其现有内容上追加 S1，不能把整个未跟踪目录都算成本次新增。

| 文件（相对仓库根目录） | 本次变更 |
| --- | --- |
| `src/private_agent_core/coding_contracts.py` | 加性要求/证据/执行解释契约及不变量 |
| `src/private_agent_core/coding_contracts.schema.json` | 同步生成 JSON Schema |
| `src/private_agent_core/completion.py` | 新增纯要求提取、命令解释和完成判定 |
| `src/private_agent_core/runtime.py` | 验证 retryable 控制；原循环及默认行为兼容 |
| `src/private_agent_core/verification.py` | 验证结果增加默认开启的 retryable |
| `src/private_agent_local/app.py` | 运行输入接受完成契约版本和显式要求 |
| `src/private_agent_local/completion.py` | 新增本机证据加载、范围守卫及验证器 |
| `src/private_agent_local/core_adapter.py` | 失败输出和验证事件适配 |
| `src/private_agent_local/executor.py` | 真实退出/取消/超时/未知及部分输出 |
| `src/private_agent_local/runtime.py` | 要求、执行事实、审批范围、验证和事务结算 |
| `src/private_agent_local/store.py` | S1 中断记录恢复为未知，不重放 |
| `apps/desktop/src/features/coding/model/generated/codingContracts.ts` | 同步生成 TypeScript 类型 |
| `apps/desktop/src/features/coding/model/runContracts.ts` | 本机 DTO 扩展和中性 completed 元数据 |
| `apps/desktop/src/features/coding/model/runProjector.ts` | 快照/事件投影完成要求、验证状态和结果 |
| `apps/desktop/src/features/coding/model/runOutcome.ts` | 新增边界校验及统一结果文案 |
| `apps/desktop/src/features/coding/model/runOutcome.spec.ts` | 同源载荷、幂等与未知回退 |
| `apps/desktop/src/features/coding/api/runs.ts` | 本机版本输入、保留并校验执行结果 |
| `apps/desktop/src/features/coding/api/runs.spec.ts` | 本机/旧服务端输入及执行映射 |
| `apps/desktop/src/features/coding/components/CodingThreadWorkspace.vue` | 执行事实刷新、调用关联及运行隔离 |
| `apps/desktop/src/features/coding/components/CommandOutput.vue` | 命令事实和验证含义分离显示 |
| `apps/desktop/src/features/coding/components/ContextDrawer.vue` | 使用统一目标状态 |
| `apps/desktop/src/features/coding/components/ContextDrawer.spec.ts` | 历史 completed 显示未确认 |
| `apps/desktop/src/features/coding/components/RunTranscript.vue` | 可见最低要求、验证结果与终态 |
| `apps/desktop/src/features/coding/components/ThreadHeader.vue` | 验证中及目标结果徽标 |
| `apps/desktop/src/features/coding/components/ThreadHeader.spec.ts` | 旧记录状态兼容 |
| `apps/desktop/src/features/coding/components/RunS0Baseline.spec.ts` | 更新旧记录无证据的展示预期 |
| `apps/desktop/src/features/coding/components/RunS1Completion.spec.ts` | 新增 API 同源结果与命令组件回归 |
| `apps/desktop/src/features/coding/components/CodingExecutionRefresh.spec.ts` | 新增执行事实刷新及迟到请求隔离测试 |
| `scripts/coding_contract_codegen.py` | 更新生成文件说明，保留 S0 生成入口 |
| `scripts/run_coding_validation.py` | 加入 completion 套件 |
| `scripts/run_coding_legacy_validation.py` | 新增隔离的冻结旧纯单测入口 |
| `tests/unit/test_local_completion.py` | 新增 S1 全链路和边界测试 |
| `tests/unit/test_local_exec_host.py` | 真实非零退出、超时输出及协议故障/清理 |
| `tests/unit/test_local_executor.py` | 通用只读夹具与明确修改门禁用例分开 |
| `tests/unit/test_local_permissions.py` | 命令替身接受新增执行关联参数 |
| `tests/coding_acceptance/test_baseline.py` | G01/G02 从严格 xfail 转为实际回归 |
| `tests/coding_acceptance/test_contracts.py` | 新契约不变量及同源样例检查 |
| `tests/coding_acceptance/s1-wire-examples.json` | 新增六类真实本机 API 载荷 |
| `tests/coding_acceptance/README.md` | S1 复跑、同源样例和隔离边界 |
| `docs/testing-guide.md` | 增补 S1 专项和旧纯单测入口 |
| `docs/unified-desktop-runtime.md` | 增补当前完成语义及验证边界 |
| `docs/analysis/coding-agent-upgrade-20260908/README.md` | 更新 S1/G01/G02 状态和后续阶段 |
| `docs/analysis/coding-agent-upgrade-20260908/s0-contract-decisions.md` | 保留 S0 历史，追加 S1 实际接入决议 |
| `docs/analysis/coding-agent-upgrade-20260908/s1-completion-and-verification.md` | 标明交付状态，校正已实现契约与事件名 |
| `docs/analysis/coding-agent-upgrade-20260908/s1-validation-report.md` | 新增本报告 |

接手时已有的 `docs/README.md`、`scripts/protocol_codegen.py`、`tests/unit/test_local_model_contract.py` 以及其余 S0/路线文件继续保留，本次未覆盖或撤销其内容。未提交、建分支、推送、部署，也未改动依赖和锁文件。

## 项目记忆

开工已完整读取根 `AGENTS.md` 和 `docs/project-state.md`，并读取 S0 执行基线、契约决议、验证报告、S1 计划及相关统一客户端/测试说明。当前代码、Git 状态和实际隔离测试用于核对记忆。

发现的时点差异：共享状态记忆最后整理于 2026-08-31，记录 `E:\Program\Agent` 和 HEAD `0c170557`；本轮实际为 `F:\Program\Agent`、HEAD `8dcfa7f`，且已有 S0 未提交工作。通过本机 Git 状态、最近提交、差异及当前调用链确认，不能将历史安装或服务器状态视为本轮源码验收。

根项目入口明确要求只有用户新增/更新项目记忆时才改写 `docs/project-state.md`，因此该文件保持历史记录。本次同步的是现有 S1 专项与统一客户端/测试文档：完成语义、契约接入、验证入口、阶段状态和已知限制。没有新建记忆系统；历史与当前状态通过日期、环境和本报告链接区分，未把推测改成上线成功。

## 风险、限制与假设

- 最低要求是有界规则，不能理解或证明任意自然语言需求；可能漏提取或过度提取。UI 展示摘要，用户可停止并补充说明。模型的成功话术不是证据。
- 文件 SHA 只证明实际变化及一致性，命令退出规则只证明该命令按登记语义退出。manual 条件仍需人工检查，本阶段没有人工验收登记界面。
- 当前文件变化证据针对现有 `write_project_file`；通过任意脚本间接生成文件不会自动成为可信文件写入证据。新多文件补丁、删除/重命名证据和依赖级验证属于后续阶段；可能保守返回未完成。
- 扫描排除依赖、构建、缓存及受保护目录，不能对其变化作完整证明；超出扫描上限或存在链接时不能获得已验证结论。整个工作区的保守失效策略可能增加重跑成本。
- 仍使用原受限工具、单次命令上限及模型请求预算。S4 的持续终端、stdin、输出流和 OS 隔离、S2 的长任务上下文、S5 的安全续跑未在本阶段实现。
- 旧服务端此次只验证原有纯单测，依赖 MySQL/client 夹具的 API/数据库集成用例未执行。没有真实账号、真实付费模型、大型生产仓库、打包安装、升级卸载或非 Windows 实机验收。
- 当前 ConPTY 不可用、文件/网络隔离 G10 已知缺口及 Vite 大 chunk 警告仍在。S0 的约 120 秒独立 duration 探针本轮未重跑；本轮验证了真实短超时、取消、输出和进程回收，不宣称新长任务能力。

## 用户需执行的操作

本次源码开发交付无需用户执行额外操作。复跑可使用上列命令；需要打包、真实模型或部署验收时，应另行指定范围和环境。下一阶段 S2 不在本次授权内。
