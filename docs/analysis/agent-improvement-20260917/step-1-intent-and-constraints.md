# 第一步：理解目标与落实约束

关联：[总计划](./README.md) → 本文 → [第二步](./step-2-planning-context-and-recovery.md)。状态：2026-09-17 第一阶段 M1 开发及自动验证完成，真实实施记录见第 9 节；第二步未执行。

> **2026-09-20 更新**：用户确认本次完善文字任务主链，现行变化见[第 12 节](#12-2026-09-20-文字任务主链对齐)。下文“同一任务只收紧”和 `schema_version=1.0` 是第一阶段历史约定；新建的 `1.1` 任务支持有原始用户来源的指定禁止项撤销，旧任务继续保守恢复。普通问句和条件执行改由完整模型上下文理解，不强制转为人工验收。本次不包含图片输入、完整第二阶段或客户端发布。

## 1. 任务目标与完成条件

让同一份用户输入在“需求识别、工具选择、执行权限、完成判断”中保持一致。优先修复复合动作和否定语义，避免 Agent 错误地只回答、强制运行用户禁止的测试，或把未验证的目标报告为已验证。

本步完成必须同时满足：

1. 已知错误输入有稳定回归用例，复合指令不会因开头出现“解释”丢掉后续动作。
2. 禁止测试、禁止命令、禁止修改、限定路径等约束在适用执行入口生效，不仅写进提示词。
3. 无法自动验证的行为要求被保留并显示，不能悄悄丢弃或默认满足。
4. 创建任务、任务中追加限制、恢复任务使用同一套解释和约束合并规则。
5. 既有文件目标识别、审批绑定和完成证据检查保持有效。

## 2. 实施前基线与已核实问题

核心入口是 [completion.py](../../../src/private_agent_core/completion.py) 的 `task_requirements`；创建任务经[本地 runtime](../../../src/private_agent_local/runtime.py)，追加限制经 [run_controls.py](../../../src/private_agent_local/run_controls.py)。

实施前的规则主要依赖正则；“回答型输入”和“执行型输入”的判断没有覆盖所有复合句、否定句。下表保留评估时的纯函数调用结果，不是当前实现状态，也不是模型端到端执行结论。

| 输入 | 当前观察 | 本步期望 |
|---|---|---|
| `修复 app.py，并运行测试。` | 识别文件修改和测试要求 | 保持 |
| `请解释错误原因，然后修复 app.py 并运行测试。` | `answer_only=true`，要求为空 | 保留解释要求，同时识别修改和测试 |
| `修复 app.py，但不要运行测试。` | 仍生成测试要求，`commands_forbidden=false` | 允许授权范围内修改；不运行测试、不生成必须测试的要求 |
| `优化登录流程，保持 API 兼容，并验证刷新后的状态。` | 未提取验收要求 | 保留兼容性及状态验证要求，标注证据类型或待澄清 |

当前代码还包含对文件修改目标识别的既有调整，应围绕实际工作区补测试并保留，不能直接用旧版本覆盖。

## 3. 设计方案

### 3.1 统一的任务解释结果

共享核心现以内部 `TaskInterpretation`、`TaskPolicy`、`TaskSource` 承载下列语义，保存在既有运行 JSON 中；没有新增公共 API 字段。项目指令继续使用现有来源及信任链，不混入用户目标或用来解除用户限制。

| 信息 | 内容 | 约束 |
|---|---|---|
| 原始输入与来源 | 用户原文、追加输入及其稳定标识 | 保存原文，派生结果不能覆盖原始证据；项目指令来源沿用既有上下文链 |
| 任务目标 | 用户要求实现的行为及输出 | 不凭文件名推断未提出的改造 |
| 动作 | 回答、读取、修改、执行、验证等可组合意图 | 复合动作不能被单个 `answer_only` 提前吞掉 |
| 禁止项 | 禁止写入、禁止测试、禁止所有命令、路径限制 | 采用明确作用范围；审批不自动解除 |
| 验收要求 | 文件变化、命令结果、测试结果、行为/人工验收 | 保留来源和对应原句，区分机器可验证与人工确认 |
| 未决问题 | 对执行范围或验收结果有实质影响的冲突 | 只阻止依赖该答案的操作，仍可完成独立读取 |
| 目标版本 | 当前任务解释所对应的目标版本 | 用于防止旧模型响应、旧计划或旧证据跨版本误用 |

保留 [Requirement 与 RunOutcome](../../../src/private_agent_core/coding_contracts.py) 的现有语义，优先做兼容扩展。行为要求可先使用已有 `manual` 类型，不为每一种自然语言条件新增枚举。

### 3.2 解析和合并顺序

1. 保留原始输入，识别引号、代码块、示例和路径，减少把引用内容当成当前命令的情况。
2. 按动作及作用范围提取候选项，单独处理否定、转折、先后顺序与条件。
3. 合并当前有效限制。明确用户限制与现有权限共同约束执行，外部文档不能解除这些限制。
4. 生成验收要求，排除已被禁止的测试或命令义务；“未执行”保留为结果说明。
5. 判断是否存在必须澄清的矛盾，最后再确定是否为纯回答任务。
6. 将同一解释结果提供给上下文、工具过滤、执行校验和完成验证，减少各处重复正则产生不同结论。

首先实现确定性规则和类型校验。对于无法可靠判定的输入，保留原始要求并提示未决点；本步不新增默认的独立 LLM 解析调用。自然语言覆盖不是无限的，未知语义必须显式保留。

### 3.3 禁止项落实到执行边界

| 限制 | 必须拦截的位置 | 正常允许的行为 |
|---|---|---|
| 不修改文件 | 文件写入、patch 应用、可能写入的命令 | 已授权范围的读取和解释 |
| 不运行任何命令 | 命令工具、执行会话创建、借助命令的验证 | 内置文件读取和必要的上下文检索 |
| 不运行测试 | 需求生成、测试命令调用与验证反馈中的补测请求 | 用户允许的修改和不属于测试的必要读取 |
| 只允许指定路径 | 工具目标解析、工作目录和最终落盘路径复核 | 范围内动作；越界请求返回明确原因 |

执行限制应覆盖实际本地入口，包括 `run_project_command` 和执行会话工具。不能只在某个工具名上判断；命令别名、封装脚本和子命令需要结合已知项目脚本及执行契约判断。无法确定某命令是否会违反明确禁止项时，先停止该命令并说明原因，不通过普通权限审批绕过限制。

测试工具返回“被用户禁止”时，完成验证不得继续要求模型重试测试。应报告已完成的修改、未执行的验证及原因。

### 3.4 追加指令与恢复

- 复用当前状态版本、`generation` 和目标版本规则；追加限制使受影响的待审批操作失效。
- 2026-09-17 第一阶段保持“同一任务的限制只收紧”；2026-09-20 新建任务的指定禁止项撤销按第 12 节处理，路径范围、预览模式和旧任务仍保留原边界。
- 恢复任务使用持久化的原始目标和有效限制重新校验；不能用旧的解析缓存绕过新约束。
- 已完成操作记录仍保留；旧证据是否继续有效由第二步的版本和工作区校验处理。

## 4. 任务拆分与预计涉及组件

以下保留原工作拆分；本轮实际变更文件和职责见第 9.2 节。

| 编号 | 工作 | 预计涉及组件 | 验收产物 |
|---|---|---|---|
| A1 | 固化已知问题及否定/复合语句样本 | `tests/unit/test_local_completion.py`、必要的新解析测试 | 先出现符合现状的失败，再由修复通过 |
| A2 | 统一意图、限制及验收要求解释 | `private_agent_core/completion.py`、`coding_contracts.py` | 同一原文得到可追溯的解释结果 |
| A3 | 创建、追加指令及恢复共用解释规则 | `private_agent_local/runtime.py`、`run_controls.py`、`recovery.py` | 生命周期内限制一致 |
| A4 | 执行入口落实禁止项 | 本地工具分发、`execution_tools.py`、现有文件工具 | 被禁止动作不触达实际执行器 |
| A5 | 完成结果解释未执行与未验证内容 | `private_agent_local/completion.py`、`runOutcome.ts` 及现有结果展示 | 无测试证据时不会显示测试通过 |
| A6 | 契约与文档同步 | 对应测试、验证套件、现行契约文档 | 无手工漂移的生成文件，无遗漏用例 |

仅在现有文件无法保持清晰职责时提取纯解析模块，不新建服务层或引入依赖。若共享契约变化，通过现有生成入口更新产物。

## 5. 必须覆盖的验收用例

| 编号 | 场景 | 必须观察到的结果 |
|---|---|---|
| A-T01 | 解释原因后修复文件并测试 | 解释、修改、测试要求并存 |
| A-T02 | 修复文件，但不要运行测试 | 可以修改；测试不会被执行，也不会被验证循环重新要求 |
| A-T03 | 只解释，不修改也不运行命令 | 所有写入/命令入口拒绝；保留可回答能力 |
| A-T04 | 不要只解释，请修复后验证 | 不把“不要只解释”误判为禁止修复或验证 |
| A-T05 | 引用示例中的“删除文件”，实际要求分析 | 不从引用生成删除任务 |
| A-T06 | 只修改 A，读取 B 作为参考 | B 不成为必须修改的目标，越界写入被阻止 |
| A-T07 | 要求 API 兼容、界面刷新正确 | 要求保留，缺少适用证据时标为待验证 |
| A-T08 | 同一句同时要求运行测试与禁止测试 | 阻止矛盾的测试操作；独立读取可继续，并报告冲突 |
| A-T09 | 等待审批时用户追加禁止命令 | 旧审批失效，旧模型响应不能触发执行 |
| A-T10 | 在限制生效后暂停并恢复 | 限制保持，不重放被禁止或副作用未知的操作 |
| A-T11 | 空输入、异常长输入、非法结构 | 明确校验错误或既有输入上限行为，无静默成功 |
| A-T12 | 模型调用别名/封装命令试图执行被禁测试 | 实际命令在执行前被拒绝，拒绝原因可观察 |
| A-T13 | 只有解释任务，未产生文件改动 | 可以为 `answered`，不伪造文件证据 |

测试同时覆盖纯函数输出和实际分发是否被调用。仅断言提示词包含“不要执行”不足以证明禁止项生效。

## 6. 验证命令与记录要求

以下命令从仓库根目录执行；本次已运行，结果见第 9.4 节。

```powershell
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite completion
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite recovery
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite execution
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite contracts
```

本次还运行 `local`、`repository`、`context`、`sandbox` 套件。新解析和执行限制测试已登记到 [验证脚本](../../../scripts/run_coding_validation.py) 的 `completion` 套件。该脚本提供隔离目录与超时；超时、跳过和失败分别记录。

公共共享契约未改变，仍执行以下只读检查，确认没有生成文件漂移：

```powershell
.\.venv\Scripts\python.exe -B scripts/protocol_codegen.py --check
```

前端源码未修改，在 `apps/desktop` 执行已有结果投影回归：

```powershell
npm.cmd run test -- src/features/coding/model/runOutcome.spec.ts src/features/coding/model/runProjector.spec.ts
```

未执行 `npm.cmd run build` 或安装包构建。本阶段不改变前端构建输入，验证集中在后端行为及既有结果显示兼容性。执行器沙箱断言保持有效，测试不使用真实用户凭据或付费模型。

## 7. 风险、兼容与恢复方案

- 自然语言规则不可能穷尽。优先保证明确限制不会被放宽；对不确定语义保留原文和待确认项。
- 新字段必须兼容旧任务读取；缺少派生字段的历史任务可以从原文计算用于显示，但执行仍需重新校验当前权限。
- 修改解析可能影响大量既有输入。除新增失败样本，保留已有文件目标识别及正常回答样本作为回归。
- “未测试”不是“测试失败”，也不是“验证通过”。结果界面必须区分这些情况。
- 回退实现时不能丢弃已经持久化的限制。先停止受影响任务，保留记录，再采用兼容代码修复；不要求用户删库或覆盖工作区。

## 8. 交付检查表

- [x] A1–A6 实施完成，并且每个实际改动均可对应任务目标。
- [x] A-T01–A-T13 的适用用例有自动化断言；执行拦截有实际调用边界证据。
- [x] 相关隔离套件通过，契约与前端检查按实际改动执行。
- [x] 现有用户改动保留；无无关依赖、版本号或发布配置变化。
- [x] 补充真实实施与验证记录，并更新受影响的现行设计文档。
- [x] 根据下列执行证据确认 M1 达成；本次止于第一阶段，未进入第二步。

## 9. 2026-09-17 实施与验收记录

### 9.1 实现和契约

- **统一解释。** `task_intent.py` 负责原文、来源、可组合动作、目标版本、限制和验收要求；`task_requirements` 保留兼容入口。解析排除引述和代码示例，保留已知文件目标、多文件清单及前置宾语规则。空白、非字符串、超过 32000 字符或超过 32 项有效验收要求明确拒绝。
- **独立限制。** 禁止测试、禁止命令、禁止写入和预览分别建模。写入范围与访问范围分开；追加范围取交集，禁止路径取并集。“只修改 A，读取 B”允许读取 B，但 B 不成为写入验收目标。通配符或无法明确的范围失败关闭。
- **实际执行边界。** 约束在工具分发、审批前后、执行会话启动、UI stdin 入口、patch 绑定和最终落盘时复核。越界操作返回 `user_constraint` 或现有路径拒绝，不触发审批、宿主执行或写盘；普通批准不能解除限制。
- **生命周期。** 创建任务、追加指令和恢复共用解释器。原始用户输入及 steer 来源保存在运行 JSON 中，恢复时重新解析；旧派生缓存只可收紧，不能放宽。追加限制继续使用已有 `generation`、目标版本和审批失效机制；已终止父任务记录不因关联恢复而改写。
- **完成语义。** 被禁止的测试/命令不生成必须补做的义务。API 兼容、刷新状态等条件使用现有 `manual`，没有适用证据时保持未验证。完成消息区分已核实操作、未验证项和阻塞，不能照抄模型的虚假“测试通过”。追加禁止项保留先前真实执行事实，不能改写成从未执行。
- **兼容边界。** `TaskInterpretation.schema_version=1.0` 是内部状态；运行快照不暴露该对象。公共 `Requirement`、`RunOutcome` 及生成的前端契约不变，SQLite 仍为 schema 7，没有迁移和依赖变化。项目指令和历史上下文沿用原有信任机制；本步没有接入长期记忆或新计划工具。

### 9.2 本轮实际变更文件

下表相对本次接手工作区记录；Git HEAD 为 `1dde393`，不能把其他会话已有差异算作本轮开发。

| 文件 | 本轮变更 |
|---|---|
| [`src/private_agent_core/task_intent.py`](../../../src/private_agent_core/task_intent.py) | 新增纯解释、来源模型及单调限制合并 |
| [`src/private_agent_core/completion.py`](../../../src/private_agent_core/completion.py) | 委托统一解释，完成结果接收冲突和未执行说明 |
| [`src/private_agent_local/task_constraints.py`](../../../src/private_agent_local/task_constraints.py) | 新增本地持久化适配、恢复重建、工具过滤及路径/命令限制检查 |
| [`src/private_agent_local/runtime.py`](../../../src/private_agent_local/runtime.py) | 接入创建、工具执行和最终输出；保留公共快照字段 |
| [`src/private_agent_local/run_controls.py`](../../../src/private_agent_local/run_controls.py) | 统一 steer 合并及关联恢复，保留事务和版本边界 |
| [`src/private_agent_local/recovery.py`](../../../src/private_agent_local/recovery.py) | 恢复前在副本上重新校验原始限制 |
| [`src/private_agent_local/execution_tools.py`](../../../src/private_agent_local/execution_tools.py) | 命令与 stdin 在审批和执行前复核 |
| [`src/private_agent_local/execution_sessions.py`](../../../src/private_agent_local/execution_sessions.py) | 宿主启动、分发及 UI stdin 的最终入口检查 |
| [`src/private_agent_local/patchsets.py`](../../../src/private_agent_local/patchsets.py) | patch 应用和回滚落盘使用当前任务限制 |
| [`src/private_agent_local/context_manager.py`](../../../src/private_agent_local/context_manager.py) | 每次请求复核任务状态并过滤工具，注入可追溯的目标与限制 |
| [`src/private_agent_local/completion.py`](../../../src/private_agent_local/completion.py) | 保留人工验收原句、跳过被禁补做义务、保留既有执行事实 |
| [`tests/unit/test_task_intent.py`](../../../tests/unit/test_task_intent.py) | 新增复合、否定、来源、路径、无效输入及兼容样本 |
| [`tests/unit/test_local_task_constraints.py`](../../../tests/unit/test_local_task_constraints.py) | 新增真实分发边界、缓存/审批复核及结果语义回归 |
| [`tests/unit/test_local_completion.py`](../../../tests/unit/test_local_completion.py) | 调整被禁止测试义务语义；正常写入和命令验证仍有闭环断言 |
| [`tests/unit/test_local_recovery.py`](../../../tests/unit/test_local_recovery.py) | 新增审批失效、暂停/关联恢复和历史来源重建回归 |
| [`scripts/run_coding_validation.py`](../../../scripts/run_coding_validation.py) | 将两个新测试文件登记到 completion 套件 |
| [`docs/analysis/agent-improvement-20260917/README.md`](./README.md) | 更新 M1 状态、验证证据及当前授权范围 |
| [`docs/analysis/agent-improvement-20260917/step-1-intent-and-constraints.md`](./step-1-intent-and-constraints.md) | 同步实现、用例映射、验证和限制 |
| [`docs/analysis/coding-agent-upgrade-20260908/s1-completion-and-verification.md`](../coding-agent-upgrade-20260908/s1-completion-and-verification.md) | 同步现行任务解释及完成语义，注明历史版本边界 |

### 9.3 验收用例映射

| 用例 | 自动化证据（省略共同的 `tests/unit/` 前缀） |
|---|---|
| A-T01、A-T04 | `test_task_intent.py::test_compound_intent_keeps_write_and_test`、`test_negative_only_answer_does_not_forbid_execution` |
| A-T02 | `test_negative_test_is_not_an_execution_obligation`；`test_local_task_constraints.py::test_modified_file_without_tests_finishes_unverified_without_retry` |
| A-T03、A-T13 | `test_readonly_request_keeps_answer_capability`；`test_command_and_stdin_boundaries_cannot_override_constraints`；既有 completion 纯回答与预览回归 |
| A-T05 | `test_quoted_instructions_are_data`、`test_explaining_how_to_modify_is_not_a_write_request` |
| A-T06 | `test_only_modify_a_allows_reading_b_but_rejects_other_writes`、`test_move_destination_and_cached_patch_are_checked_before_apply`、`test_write_scope_merge_uses_intersection_and_does_not_loosen` |
| A-T07 | `test_behavior_requirements_are_kept_for_manual_verification`、`test_behavior_requirements_are_visible_and_not_passed_by_file_evidence` |
| A-T08 | `test_conflicting_test_request_blocks_only_dependent_work`、`test_conflicting_test_request_still_allows_independent_read` |
| A-T09 | `test_local_recovery.py::test_steer_invalidates_command_approval_and_does_not_replay`；既有延迟模型响应丢弃用例；`test_final_write_guard_rechecks_policy_after_approval` |
| A-T10 | `test_tightened_test_restriction_survives_pause_and_linked_resume`、`test_legacy_restore_reparses_applied_steer_sources`、`test_cache_cannot_relax_original_restrictions`及既有恢复故障回归 |
| A-T11 | `test_invalid_input_has_explicit_validation_error`及既有显式要求版本、数量、非法结构断言 |
| A-T12 | `test_test_alias_and_unknown_wrapper_never_reaches_executor`，覆盖两个命令入口、npm 别名和 Python 包装；另有最终会话启动和 UI stdin 检查 |

拒绝用例使用实际本地运行时、ASGI/SQLite 夹具及执行边界 spy，断言执行器、宿主启动、stdin 发送或最终写入没有发生；不是只检查提示词。成功写入及合法命令仍由已有真实磁盘和执行证据断言验证。

### 9.4 实际验证结果

环境：Windows 11、Python 3.12.13；沿用已有虚拟环境、依赖和本地测试用执行宿主。测试运行使用 `.run/coding-agent-validation/` 下的独立临时 SQLite、项目和配置，模型使用测试替身，不访问生产数据库或真实模型账号。

下表每行实际执行 `.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite <套件>`，工作目录为 `F:\Program\Agent`。最终八组退出码均为 0。

| 套件 | 最终观察结果 | 用时 | 本地运行日志（均在忽略目录内） |
|---|---|---|---|
| `completion` | 162 passed | 44.71s | `.run/intent-completion-verified.log` |
| `local` | 71 passed | 23.48s | `.run/intent-local-verified.log` |
| `recovery` | 38 passed | 54.72s | `.run/intent-recovery-verified.log` |
| `execution` | 19 passed | 33.28s | `.run/intent-execution-verified.log` |
| `repository` | 50 passed, 1 skipped | 15.64s | `.run/intent-repository-verified.log` |
| `context` | 35 passed | 13.29s | `.run/intent-context-verified.log` |
| `contracts` | 15 passed | 0.66s | `.run/intent-contracts-verified.log` |
| `sandbox` | 26 passed | 223.34s | `.run/intent-sandbox-verified.log` |

合计 **416 passed、1 skipped**。唯一跳过项位于 `test_local_file_ranges.py:111`：当前 Windows 测试身份无创建真实符号链接权限；该真实链接场景未得到运行验证，不能写成通过。沙箱大目录扫描用例耗时较长但在启动器时限内正常完成，没有超时或删减断言。

其他实际执行的检查：

- `apps/desktop` 下执行第 6 节的 `npm.cmd run test -- ...`：两个文件共 **24 passed**，退出码 0；前端源码和生成契约没有修改。
- `.\.venv\Scripts\python.exe -B scripts/protocol_codegen.py --check`：`protocol codegen in sync: OK`，退出码 0。
- 以下 Ruff 命令：`All checks passed!`，退出码 0。
- `git diff --check`：退出码 0。工作区状态和本轮相对接手内容的差异另外核对，既有未提交内容保留，没有提交、分支或发布操作。
- 用 Python 只读检查本次三份文档的 UTF-8 文本及本地链接：52 个文件链接全部存在，无替换字符。源码验证完成后的复核确认，本轮既有代码文件与最终测试时内容一致。

```powershell
.\.venv\Scripts\python.exe -B -m ruff check src/private_agent_core/completion.py src/private_agent_core/task_intent.py src/private_agent_local/task_constraints.py src/private_agent_local/runtime.py src/private_agent_local/run_controls.py src/private_agent_local/recovery.py src/private_agent_local/execution_tools.py src/private_agent_local/execution_sessions.py src/private_agent_local/patchsets.py src/private_agent_local/context_manager.py src/private_agent_local/completion.py tests/unit/test_task_intent.py tests/unit/test_local_task_constraints.py tests/unit/test_local_completion.py tests/unit/test_local_recovery.py scripts/run_coding_validation.py
```

红灯与环境故障记录：最初 completion 为 **18 failed、72 passed**，其中 17 项是新增问题回归，1 项是既有搜索工具无法在受限测试进程中启动 `rg.EXE`。诊断观察到 `PermissionError [WinError 5]`；恢复套件也曾因同一测试进程权限边界导致宿主能力不可用、故障注入点未到达。获准在宿主环境运行隔离测试后，这些用例正常通过，产品执行沙箱和断言没有关闭。中间发现的解析兼容回归均已修复，并以本节最终全套结果为准；未把早期失败计作通过。

### 9.5 限制与项目记忆同步

- 确定性语义规则覆盖本节样本，不等于通用自然语言理解。无法可靠判断的行为和验证条件保留原句及 `manual` 未验证项；本阶段没有新增人工确认界面。
- 在禁止测试或限制写入范围时，不明确的脚本采取保守拒绝。例如 `npm run build` 可能通过生命周期钩子执行测试，`python verify.py` 可能写入范围外文件，均不能仅凭名称认定符合限制；已登记的只读 Git 诊断或 PowerShell 文件读取仍按原权限和路径检查处理。
- 2026-09-16 的“仅修改 sample.py，随后执行 python verify.py”目标提取规则仍保留，但本次新增执行限制后，该脚本无法证明只修改指定文件时会被拒绝。一般“修改 sample.py，随后执行验证命令”的既有闭环继续通过；本次测试拆开了目标提取与严格写入范围验证，没有以宽松执行替代禁止项。
- 当时所有限制在同一任务内只收紧；2026-09-20 对新建 `1.1` 任务的指定禁止项增加显式撤销，详见第 12 节。恢复仍不重放副作用未知操作，也不把此前已执行测试抹掉。阶段二的计划工具、压缩状态及更完整目标版本证据关联未在第一阶段扩展。
- 已完整读取 `docs/project-state.md`，并对照现行直连模型、统一桌面运行时、上下文文档、S1 设计和当前源码。该记忆为 2026-08-31 的历史运行快照，其旧目录/运行方式不代表当前 `F:\Program\Agent` 和统一主链；S1 第 5 节的 SQLite 3 是当时版本，当前 `store.py` 核实为 schema 7。历史时点得到标注，最新规则同步到本计划、第一步细则及 S1 第 10 节。按仓库专门约定，没有改写 `docs/project-state.md`，也没有新建项目记忆系统。
- M1 开发验收阶段未执行第二、三阶段、桌面构建、安装包生成、真实模型/账号验收、服务器操作、发布部署。后续用户另行要求的第一阶段候选打包见下节，不回写为此前已执行。

## 10. 第一阶段用户试用交付

用户在 M1 完成后明确要求新安装包与测试集。2026-09-17 已构建独立候选版 1.0.7，提供 14 个手工场景、逐项提示词、反馈模板和只读结果采集脚本。构建、随包验证和测试集验证通过；安装及真实模型试用仍等待用户反馈。产物路径、SHA256、实际命令和限制见[第一阶段候选版 1.0.7](./phase-1-trial-1.0.7.md)。本次交付没有进入第二、三阶段。

## 11. T01 用户反馈与完成验收修复

2026-09-18：用户反馈 1.0.7 中 T01 的文件修改和指定 pytest 已通过核验，整体任务却因未登记的 PowerShell 请求和多条历史证据过期记录受阻。此前随包自动场景仅覆盖直接读取、修复、测试，未覆盖真实模型的辅助命令与错误工具尝试；不能据原冒烟结果认定此类路径正常。

本次定向修复沿用现有 Requirement/RunOutcome 和执行审计：明确要求继续严格核验；尚未启动且没有副作用证据的 local_tool_rejected 不新增验收义务；有对应完成事件、正常退出、可确认未改变工作区的非测试辅助命令只留在执行记录。同一命令先前已改变或无法核对工作区时仍保留验收，失败、测试、未知结果、拒绝权限和修改后过期的验证不会被辅助命令规则忽略。未通过的命令验证显示命令名称。

本轮实现、回归、候选安装器与复测步骤见 [1.0.8 修复与复测记录](./phase-1-trial-1.0.8.md)。该修复不改变第一阶段的自然语言边界，不展开第二、三阶段。

## 12. 2026-09-20 文字任务主链对齐

本次只处理用户确认的文字任务理解、约束纠正、项目规则和上下文来源。对齐依据是 Codex 的[模型与执行框架分工](https://developers.openai.com/blog/codex-as-a-platform)、[运行中追加输入](https://learn.chatgpt.com/docs/app-server)和[项目规则发现顺序](https://learn.chatgpt.com/docs/agent-configuration/agents-md)，不宣称复刻其模型能力或全部内部实现。

### 12.1 当前行为

- **语义与执行边界分工。** 模型始终收到完整用户原文；解析结果是辅助数据，不是完整语义或新授权。普通问题和仅提及 `pytest` 等工具名不再制造执行或人工验收义务；明确修改、运行命令、测试和 API 兼容等要求继续使用既有证据验证。
- **条件与文字边界。** 已识别的 `如果`、`if`、`unless` 条件正文保留为 `conditions`，不强制生成无条件修改、测试或禁止项，由模型根据观察决定。支持“修一下”“测试先别跑”等表达。“要求如下：”直接引入的 text/Markdown 围栏参与约束提取，示例、引述、程序代码仍作为数据。已识别条件不等于条件已满足。
- **明确撤销。** 新解释对象显式写入 `schema_version=1.1`。只有现有用户 steer 入口中的直接明确表述，例如“现在可以运行测试”“取消之前不运行测试的限制”“现在可以运行命令”“现在可以修改文件”“现在可以联网”，才撤销对应禁止项。审计保留 `policy_releases.field/source_id/text`、原文和递增 `goal_version`；同一消息又禁止该动作时，以禁止为准。引述、问句、条件许可、泛化允许、模型响应、项目规则或普通工具审批不能撤销限制。
- **限制相互独立。** 撤销测试禁令不会撤销命令禁令；路径范围、禁止路径、预览模式、权限模式、审批、宿主沙箱不因此改变。解除禁止本身不生成新的执行要求；需要继续执行时应同时提出执行要求，原先通过结构化契约显式提交的验收要求则恢复核验。只有已解决的冲突和阻止说明会清除，历史执行事实保留。
- **运行中同步。** 核心保留权限模式允许的工具目录，在每个模型请求边界根据最新策略筛选，避免任务启动时永久隐藏工具；系统提示不缓存旧任务的要求或禁令。任务辅助状态与受信项目规则以 `user` 角色先于原始历史进入上下文，系统只保留固定框架规则。已有的代次、取消、审批失效、预算与完成核验继续生效。
- **项目规则。** 每层优先选非空 `AGENTS.override.md`，再选非空 `AGENTS.md`；来源包含路径、作用域、摘要、信任和优先级。新增、移除或修改当前选中的 override 会使活动任务的写入失效。继续执行单文件 32 KiB、总量 64 KiB、最多 16 份限制；无效、不可读或链接规则显式失败，不回退掩盖错误。不读取授权项目之外的个人全局规则。
- **恢复兼容。** 恢复从原始用户来源重放已生效撤销，再与持久化限制保守合并。旧 `1.0`、缺少版本、缺少解释对象的记录不自动升级撤销权限；缓存或审计字段不能单独提供放行依据。公共 API、数据库 schema、依赖和生成的前端契约不变。旧实现不能用于继续新建的 `1.1` 任务，回退时须保留原始记录并使用理解该契约的实现。

### 12.2 验证与边界

验证使用既有 `scripts/run_coding_validation.py`，临时项目、SQLite 和模型测试替身均与业务环境隔离。新增回归覆盖普通提问、否定、条件、围栏来源、限定撤销、权限保留、旧任务、暂停与关联恢复、同一运行恢复工具可见性、项目规则覆盖及审批期间变化。命令成功用例使用受控退出码，未调用真实付费模型。

最终执行命令及观察结果见下表；测试结果只证明本地实现和受控交互，不代表真实模型的语义准确率或桌面安装包验收。

| 命令 | 结果 |
|---|---|
| `.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite completion` | 234 passed |
| `.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite context` | 44 passed |
| `.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite recovery` | 41 passed |
| `.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite tools` | 74 passed |

合计 **393 passed**，无跳过项。以下静态检查退出码为 0，Ruff 返回 `All checks passed!`；Git 仅提示工作区既有 LF/CRLF 转换信息，没有差异空白错误。新增测试的一个 import 格式问题已按 Ruff 建议修正后复查通过。

```powershell
.\.venv\Scripts\python.exe -B -m ruff check src/private_agent_core/task_intent.py src/private_agent_local/task_constraints.py src/private_agent_local/runtime.py src/private_agent_local/context_manager.py src/private_agent_local/instructions.py tests/unit/test_task_intent.py tests/unit/test_local_task_constraints.py tests/unit/test_local_recovery.py tests/unit/test_local_instructions.py
git diff --check
```

首轮受限环境中 completion 为 230 passed、1 failed（搜索工具不可访问），recovery 为 39 passed、2 failed（执行宿主持续能力不可用，故障注入点未触发）。获准在宿主环境运行相同隔离套件后通过，未修改执行沙箱或放宽原有断言。初次新增口语样本暴露“改好”漏识别，已补齐并回归；后续补充无版本旧记录和显式验收恢复等边界测试。

仍有限制：自然语言提取不是完备解析器，未识别的语义由模型结合原文处理；路径放宽、预览模式切换和旧任务解除限制继续要求新建范围明确的任务。本次未接入图像、全局个人规则或独立模型解析服务，未进行真实模型质量比较、前端构建、打包、安装或部署。没有提交或覆盖接手时已有工作。

已读取 `docs/project-state.md`、当前上下文设计和本文件，并核对实际源码。第一阶段文档中旧的单调限制描述与本次行为不同，已保留历史日期并指向本节；项目规则发现顺序和消息层级同步到 [context-design.md](../../context-design.md)。`docs/project-state.md` 的最新记录为 2026-09-19，属于历史运行状态；按根目录 `AGENTS.md` 的专门约定，本次未获更新该文件的明确请求，因此不改写，也未创建新的项目记忆系统。
