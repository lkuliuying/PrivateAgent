# 第二步：贯通计划、上下文与纠错

关联：[总计划](./README.md) · [第一步](./step-1-intent-and-constraints.md) → 本文 → [第三步](./step-3-capabilities-and-trial-delivery.md)。状态：2026-09-20 已接通本地核心编排及规划协作模式，源码验证见第 9、10 节；未打包、部署或进行真实模型验收。

## 1. 任务目标与完成条件

将“任务要求 → 分步计划 → 当前上下文 → 工具执行 → 观察证据 → 纠错或完成”贯通到当前本地主链。用户能知道 Agent 在做什么、还缺什么，以及为什么停止。

完成条件：

1. 复杂任务能够创建和更新本地计划，并在界面、历史回放和恢复后保持一致。
2. 上下文压缩后仍可获得目标、有效限制、关键决策、当前步骤、待办与证据引用。
3. 重复失败和重复成功但没有进展的循环都有上限；正常长命令等待不会被误杀。
4. 结果状态来自有效证据，计划勾选和模型口头声明不能直接把任务标记为已验证。
5. 暂停、取消、追加限制、崩溃恢复和过期模型响应保持现有安全语义。

## 2. 实施前的能力与缺口（2026-09-17 基线）

| 范围 | 已有实现 | 本步需要补齐 |
|---|---|---|
| 共享循环 | [core/runtime.py](../../../src/private_agent_core/runtime.py) 已执行模型、工具和完成验证反馈 | 接入计划及进展状态，保持单一循环 |
| 任务计划 | run_plan.py（历史路径：`src/personal_assistant/core/run_plan.py`，已移除） 有版本、状态转换和单个进行中步骤；桌面已有计划展示 | 旧实现依赖服务端存储；当前本地工具列表未接通同类能力 |
| 压缩历史 | [context_history.py](../../../src/private_agent_local/context_history.py) 保留用户消息、工具配对、近期组和内容引用 | 工具成败摘要不能充分表达决策、约束与下一步 |
| 上下文预算 | [core/context.py](../../../src/private_agent_core/context.py)、[context_manager.py](../../../src/private_agent_local/context_manager.py) 有估算、用量校准和预算控制 | 让高价值任务状态获得明确预算，保留来源 |
| 纠错 | [core_adapter.py](../../../src/private_agent_local/core_adapter.py) 对连续同指纹失败有告警和停止 | 成功读取会重置失败计数，反复读取但无推进仍可能循环 |
| 完成验证 | [local/completion.py](../../../src/private_agent_local/completion.py) 检查磁盘变更、命令/测试与工作区版本 | 与计划步骤和行为要求关联，清楚解释证据缺口 |
| 恢复 | [recovery.py](../../../src/private_agent_local/recovery.py)、[run_controls.py](../../../src/private_agent_local/run_controls.py) 有检查点、代次与失效控制 | 将新增计划和任务摘要一起纳入一致性检查 |

旧 `agent_v2/application/planner.py` 的 `ToolPlan` 主要选择工具暴露范围，不能当作本步已经具备任务步骤规划的证据。

## 3. 设计方案

### 3.1 本地计划契约与工具

复用旧计划的状态机思想及界面能力，把纯契约与校验放在共享核心，通过本地存储适配器持久化。不要为了复用类而把 SQLAlchemy 服务端会话引入轻量本地运行时。

本地计划更新工具固定为 `update_run_plan`，入参与前端完整计划事件已接通。以下是计划的信息集：

| 对象 | 必需信息 | 校验原则 |
|---|---|---|
| 计划 | 任务标识、目标版本、计划版本、简短说明、步骤列表 | 更新携带预期版本，过期写入明确冲突 |
| 步骤 | 稳定 `item_key`、标题、状态、关联要求、证据引用 | 不用标题充当身份；证据必须引用实际记录 |
| 更新事件 | 更新版本、变更步骤、原因和顺序号 | 与持久化状态一致，支持断线回放和去重 |

延续已有 `pending`、`in_progress`、`completed`、`blocked`、`failed`、`cancelled` 语义及最多一个进行中步骤的约束。第一版使用有序列表，不实现通用 DAG、跨 Agent 依赖调度或自动资源编排。

具体规则：

- 单次读取、简单回答或小修改可以不建计划，避免每个操作都增加流程负担。
- 复杂目标建议先给出少量可验证步骤；步骤数量沿用已有上限，不无限扩张。
- 计划 `completed` 表示步骤工作结束，独立的证据状态决定“是否验证”。计划全部勾选不能替代任务验证。
- 已结束步骤不通过重写历史重新打开；需要修正时追加说明和后续步骤，并保留原证据。
- 目标版本变化使旧计划进入需核对状态；限制收紧后重验受影响步骤，禁止沿旧计划继续执行被禁止动作。
- 计划工具只改变任务元数据，不获得文件、Shell 或网络权限。

### 3.2 结构化工作摘要

压缩时生成与当前目标版本绑定的工作摘要，最低包含：

1. 用户目标和验收要求。
2. 当前有效限制、可信项目指令及其来源引用。
3. 当前计划步骤、已经完成的工作和待办。
4. 关键发现与决策，区分观察事实、用户决定和模型假设。
5. 验证证据及其对应工作区版本；已经失效的证据明确标注。
6. 尚未解决的问题、阻塞原因、下一步建议。
7. 原始消息和工具结果的内容引用，必要时可重新读取。

优先从持久化任务、计划、操作和证据记录确定性生成摘要；自由文本只补充无法由结构化状态表达的内容，并标明来源。第一版不强制增加一次模型摘要调用。

预算分配保留现有总上限与输出预留，在其中优先安排当前目标、限制、工作摘要和近期完整消息组。低优先级长输出使用摘要与引用。不能为容纳摘要而拆开 assistant/tool 配对或无界重复注入历史。

当必须保留的信息已经超出预算，应显式缩小单次任务或报告预算阻塞，不能悄悄删除禁止项。模型报告的真实用量继续校准估算；未知模型保持现有保守处理。

### 3.3 计划、摘要与恢复的一致性

采用现有 `goal_version`、状态版本、`generation` 和工作区版本体系：

- 计划与工作摘要记录其目标版本和生成依据；不创建另一套互不关联的任务状态机。
- 状态写入与事件通知遵循现有事务边界；发布事件前确保可从存储恢复，避免界面看到无法回放的步骤。
- 检查点包含或引用计划版本、摘要版本和有效上下文位置，不复制全部大输出。
- 恢复时先校验目标、权限、指令信任和工作区，再重建模型上下文。
- 过期响应和压缩结果被丢弃时保留诊断原因，不得覆盖新一代任务状态。
- 崩溃时副作用状态不明的命令继续交给现有恢复流程判断，不自动重跑。

### 3.4 进展检测与有界纠错

保留当前“连续同指纹失败第三次告警、第四次停止”的保护。新增进展判断时不删除这条已存在的边界。

| 观察 | 处理方式 |
|---|---|
| 参数或结构错误 | 返回可操作的字段错误，允许有限纠正 |
| 暂时性读取失败 | 仅对明确可重试的幂等读取使用有界重试，受总预算约束 |
| 审批拒绝、禁止项或路径越界 | 解释限制并停止依赖动作，不把重复请求当成恢复策略 |
| 测试失败且有新诊断信息 | 允许继续定位和修复，保留当前失败证据 |
| 重复读取相同内容、同样结论且未产生新证据 | 先提醒改变策略；持续无进展则停止并报告缺口 |
| 命令仍运行且正常读取新增输出 | 视为等待执行，受超时和活动预算限制，不误判为循环 |
| 命令副作用状态未知 | 阻止自动重放，进入现有恢复或人工处理流程 |

第一版采用保守的重复检测：在同一目标和工作区版本下，比较规范化调用、结果内容引用及步骤/证据变化。先对明确重复的无进展行为生效，不推断模型隐藏思考。

阈值作为有边界的策略参数由故障用例确定；可从连续三个重复观察窗口后发出一次纠正提示开始验证，但该数值是候选值，不是已确定的产品契约。纠正后仍无变化，应输出具体阻塞，而非无限追加“请继续”。

### 3.5 完成状态和用户输出

沿用 `answered`、`verified`、`unmet`、`blocked`、`unknown`，不新增另一个含义含糊的“成功”字段。

- 回答型任务说明已经回答什么，避免附带虚构的测试证据。
- 修改型任务展示实际 diff、变更文件和验证结果。
- 自动可验证要求必须关联实际事件、文件或测试结果；旧工作区的成功测试不能证明新修改正确。
- 人工验收要求保持待确认；模型不得代替用户点击确认或伪造回执。
- 最终结果包含“已完成工作、验证依据、尚未验证、阻塞/下一步”，引用大输出而不是全量粘贴日志。
- 前端运行结束与业务目标已验证分开呈现，恢复历史时保持一致。

## 4. 任务拆分与预计涉及组件

| 编号 | 工作 | 预计涉及组件 | 依赖 |
|---|---|---|---|
| B1 | 提取/补齐纯计划契约及状态校验 | `private_agent_core/coding_contracts.py`，参考旧 `run_plan.py` | M1 |
| B2 | 本地计划持久化与更新工具 | `private_agent_local/store.py`、`runtime.py`、必要的本地计划适配模块 | B1 |
| B3 | 计划事件与桌面展示接通 | `runProjector.ts`、`RunPlanPopover.vue`、已有状态与回放测试 | B2 |
| B4 | 结构化工作摘要与预算排序 | `context_history.py`、`context_manager.py`、共享上下文契约 | B1、B2 |
| B5 | 恢复、追加限制及代次校验 | `recovery.py`、`run_controls.py`、`core_adapter.py` | B2、B4 |
| B6 | 无进展检测与错误分类 | `core_adapter.py`、共享运行循环及相关测试 | B4、B5 |
| B7 | 计划、要求、证据与最终输出关联 | 本地 `completion.py`、`runOutcome.ts`、结果界面 | B3、B6 |
| B8 | 长任务故障回归与设计说明 | 验证脚本、对应测试、上下文/运行时说明 | B1–B7 |

本地存储当前为 schema 7。优先利用已有可扩展数据；如果确实需要迁移，实施前明确版本、旧记录默认值、事务行为和恢复路径，不能直接按计划文档假定迁移已经可行。

## 5. 必须覆盖的验收用例

| 编号 | 场景 | 必须观察到的结果 |
|---|---|---|
| B-T01 | 复杂任务创建并更新三个步骤 | 版本递增，最多一个进行中，界面与存储一致 |
| B-T02 | 简单回答或一次读取 | 不强迫建立复杂计划 |
| B-T03 | 两个更新使用同一期望版本 | 一个成功，过期更新冲突；不覆盖先前结果 |
| B-T04 | 非法状态转换、重复步骤键、超量步骤 | 明确拒绝，不产生半完成事件 |
| B-T05 | 断线后回放同一批事件 | 步骤和消息不重复、不乱序 |
| B-T06 | 长工具输出触发多次压缩 | 仍保留目标、禁止项、当前步骤、失败原因和引用 |
| B-T07 | 需要查看被裁剪的文件内容 | 可通过内容引用取回；过期文件不能冒充当前文件 |
| B-T08 | 旧测试通过后再次修改文件 | 旧证据失效，任务不会直接为 `verified` |
| B-T09 | 连续重复读取成功但没有新信息 | 触发一次有界纠正，再持续则明确停止 |
| B-T10 | 长命令正常运行并持续产生输出 | 不误判无进展；仍可取消、超时和释放资源 |
| B-T11 | 暂停/取消期间模型响应返回 | 旧响应不更新计划，不调用工具，不覆盖摘要 |
| B-T12 | 压缩与追加限制发生竞争 | 恢复上下文采用新限制，旧压缩结果不覆盖 |
| B-T13 | 执行后崩溃但完成事件未落盘 | 保留未知副作用，不自动重跑 |
| B-T14 | 计划全部完成，但人工验收未做 | 说明工作已完成及未验证项，不伪造用户确认 |
| B-T15 | 读取旧版本任务与无计划任务 | 历史正常展示，必要时使用兼容默认值 |
| B-T16 | 摘要预算不足、无效引用或错误结构 | 明确降级或阻塞，不删除限制、不静默成功 |

使用脚本化模型响应和临时工作区稳定复现长任务；不用“模型这次回答得不错”替代确定性断言。

## 6. 验证命令与实施记录

实施后从仓库根目录运行适用套件：

```powershell
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite context
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite recovery
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite completion
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite streaming
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite contracts
.\.venv\Scripts\python.exe -B scripts/protocol_codegen.py --check
```

涉及执行会话时增加 `--suite execution`。新的计划、循环与压缩用例加入固定套件列表；不通过删除旧用例缩短运行时间。

在 `apps/desktop` 验证计划、结果和回放：

```powershell
npm.cmd run test -- src/features/coding/model/runProjector.spec.ts src/features/coding/model/runOutcome.spec.ts src/features/coding/components/RunPlanPopover.spec.ts src/features/coding/composables/useRunStream.spec.ts
npm.cmd run build
```

实施记录至少包含一次“压缩后继续完成”和一次“崩溃后恢复但不重放副作用”的隔离场景；记录事件序列、版本和结论，使用内容引用避免保存大段敏感日志。

2026-09-20 的实际执行结果见第 9 节。上述命令是可复核入口，不能推导安装包或真实模型已通过验收。

## 7. 风险、兼容与恢复方案

- 计划是任务元数据，不能变成第二个执行总控；实际动作仍由现有运行循环调度。
- 摘要可能遗漏信息。保留原始记录和可取回引用，对目标与禁止项采用结构化来源，不能只信模型生成的总结。
- 进展阈值过严会误伤调查任务，过松会继续循环。用真实重复读取、正常探索和长命令三类用例比较，再确定默认值。
- 事件格式变化可能影响旧回放。新增字段提供默认解释，旧事件保持可读取。
- 存储升级不等于旧二进制可无损降级。若涉及新 schema，先验证旧数据读取和备份恢复；不要承诺未经验证的跨版本降级。
- 当前大量未提交代码可能影响基线，实施前复核差异，不把既有超时、构建或环境问题归为本阶段新问题。

## 8. 交付检查表

- [x] B1–B8 的本地主链接通，计划工具确实进入模型工具列表。
- [x] B-T01–B-T16 的适用源码场景有可复现证据，见第 9 节映射；未据此声明真实模型验收。
- [x] 压缩与恢复后的目标、约束和步骤连续性通过验证。
- [x] 不存在计划勾选即宣告 `verified` 的捷径。
- [x] 无进展纠错有上限，正常等待和取消不被破坏。
- [x] 契约、回放、前端构建和受影响运行时测试通过。
- [x] 更新真实实施记录及受影响设计文档；后续能力和交付阶段单独验收，不自动开始新任务。

## 9. 2026-09-20 本地任务编排实施记录

本次按“完善任务编排器，与 Codex 对齐”接通核心主链，保留既有 `AgentRuntime`、工具权限、审批、补丁及完成验证器。没有引入第二个总控循环、SQLAlchemy 依赖、数据库迁移或独立的规划模型请求。

实际实现：

- `private_agent_core/planning.py` 定义纯计划契约和状态转换；`private_agent_local/planning.py` 校验计划/目标版本、需求 ID、同逻辑任务的已提交调用引用，保存简短公开说明。步骤最多 32 项、输入最多 16000 UTF-8 字节，终态和历史证据不可覆盖。
- 运行 JSON 持久化计划，计划事件、工具完成事件与状态在同一事务提交。`runProjector.ts` 消费完整计划更新，保留旧事件兼容，禁止旧版本覆盖新快照；面板显示需核对状态、公开说明和调用引用数量，并区分进度与验收。
- 请求和压缩保留当前计划及有来源的公开说明。公开说明标记为模型报告，不保存或索取隐藏推理。原始用户目标与禁止项继续逐条保留；摘要不能删除权限限制。目标代次变化时拒绝提交旧压缩结果。
- 恢复检查点增加计划/进度摘要，继续运行继承计划和累计预算。追加目标使计划进入 `needs_review`；旧模型响应不能修改新计划。祖先调用仅作为来源，磁盘和测试结果仍由完成验证器重新核对。
- 重复成功查询连续 3 次告警、6 次停止，最多保留 64 个指纹；新增查询、内容、工作区、计划状态或命令诊断会重新计数。运行中的命令轮询不计停滞。原有重复失败和整体预算不变。
- 计划未完成、待核对或受阻会形成交付缺口；全部勾选不改变原有机器验收的要求和证据判定。小任务和无计划历史保持兼容。

关键场景对应证据：

| 场景 | 确定性验证 |
|---|---|
| B-T01–05、15 | 本地计划的版本冲突、状态/数量边界、事务故障回滚，以及前端完整事件/旧事件/快照回放 |
| B-T06–07 | 24 次文件读取后至少两次压缩，再真实创建 `done.txt`、回读、完成三个计划步骤；上下文 suite 继续检查引用与用户原文 |
| B-T08、14 | 原有 completion suite 检查失效证据与人工要求；新增用例验证勾选完成不能满足未发生的文件修改 |
| B-T09–10 | 真实循环重复读取在第 7 次调用后停止；不同查询/新诊断继续；运行中轮询豁免，执行会话回归检查取消和资源回收 |
| B-T11–13 | 旧模型计划响应被丢弃，压缩/追加约束竞态保留原历史；恢复 suite 的真实宿主退出和未确认副作用不重放 |
| B-T16 | 无效来源、跨任务调用及过大计划拒绝；现有上下文硬上限/取消用例保留原始内容 |

实际运行结果（全部使用临时工作区、独立 SQLite 和模拟模型，不读取生产配置、不调用付费模型）：

| 实际命令（仓库根目录） | 最终结果 |
|---|---|
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite orchestration` | 33 passed |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite context` | 44 passed |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite recovery` | 41 passed |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite completion` | 234 passed |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite tools` | 78 passed |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite streaming` | 32 passed |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite contracts` | 15 passed |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite parallel` | 57 passed，含上述 recovery 用例，不重复计算为新增覆盖 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite execution` | 37 passed |
| `.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check` | `protocol codegen in sync: OK` |

在 `apps/desktop` 实际运行以下命令，四个前端文件共 63 项测试通过，`vue-tsc --noEmit` 和 Vite 构建通过。构建仍报告大于 500 kB 的 chunk 提示，本次未扩展为打包拆分改造。

```powershell
node node_modules/vitest/vitest.mjs run src/features/coding/model/runProjector.spec.ts src/features/coding/model/runOutcome.spec.ts src/features/coding/components/RunPlanPopover.spec.ts src/features/coding/composables/useRunStream.spec.ts
npm.cmd run build
```

对全部本次 Python 实现及测试执行以下静态检查，结果为 `All checks passed!`：

```powershell
.venv/Scripts/python.exe -m ruff check src/private_agent_core/planning.py src/private_agent_local/planning.py src/private_agent_local/progress.py src/private_agent_local/runtime.py src/private_agent_local/tool_registry.py src/private_agent_local/context_manager.py src/private_agent_local/context_history.py src/private_agent_local/core_adapter.py src/private_agent_local/recovery.py src/private_agent_local/run_controls.py src/private_agent_local/completion.py tests/unit/test_local_planning.py tests/unit/test_local_progress.py tests/unit/test_local_model_contract.py scripts/run_coding_validation.py
```

失败与复核：改动前 context 为 44 passed，completion 为 233 passed、1 failed（空搜索结果）。受限环境中 Git/搜索/执行宿主遇到 `WinError 5` 管道限制，前端 esbuild 遇到 `spawn EPERM`；获准在原隔离目录机制下运行后，相应套件全部通过，未修改搜索或宿主权限实现。初次回归还暴露无计划压缩调用兼容性及旧工具可见性断言需同步：保留旧位置参数调用方式，并增加恢复协议有/无两类契约覆盖后通过。竞态夹具按实际控制事件签名和模型请求边界修正，最终保留全部断言，无跳过或删除测试。

本次变更清单（24 个文件；以下均为仓库相对路径，保留任务开始前的未提交内容）：

| 文件 | 动作与内容 |
|---|---|
| `src/private_agent_core/planning.py` | 新增纯计划契约和状态转换校验 |
| `src/private_agent_local/planning.py` | 新增本地计划、来源核对、上下文与交付缺口检查 |
| `src/private_agent_local/progress.py` | 新增有界重复观察记录，恢复保留最近命令依据 |
| `src/private_agent_local/runtime.py` | 接入计划工具、事务、恢复继承和空闲压缩 |
| `src/private_agent_local/tool_registry.py` | 注册计划控制工具及输入输出结构 |
| `src/private_agent_local/core_adapter.py` | 按批次顺序记录进展，向模型反馈重复观察 |
| `src/private_agent_local/context_manager.py` | 注入当前计划、执行停滞门禁并拒绝旧代次压缩 |
| `src/private_agent_local/context_history.py` | 压缩记录结构化任务状态，兼容无计划调用 |
| `src/private_agent_local/recovery.py` | 检查计划/进度摘要和累计停滞限制 |
| `src/private_agent_local/run_controls.py` | 追加目标时要求核对计划、清除旧目标的观察计数 |
| `src/private_agent_local/completion.py` | 计划缺口参与交付判定，保留原有证据验证 |
| `apps/desktop/src/features/coding/model/runContracts.ts` | 扩展可选计划元数据 |
| `apps/desktop/src/features/coding/model/runProjector.ts` | 完整计划事件、旧事件兼容及版本防回退 |
| `apps/desktop/src/features/coding/model/runProjector.spec.ts` | 增补计划回放、旧版本和快照验证 |
| `apps/desktop/src/features/coding/components/RunPlanPopover.vue` | 展示计划待核对、公开说明及调用关联 |
| `apps/desktop/src/features/coding/components/RunPlanPopover.spec.ts` | 增补状态提示、来源与验收区分测试 |
| `tests/unit/test_local_planning.py` | 新增真实存储、模拟模型及故障边界测试 |
| `tests/unit/test_local_progress.py` | 新增重复查询、分页、命令诊断与恢复计数测试 |
| `tests/unit/test_local_model_contract.py` | 增加恢复协议有/无两种工具暴露验证 |
| `scripts/run_coding_validation.py` | 注册独立 orchestration 套件并纳入组合回归 |
| `docs/local-tool-system.md` | 更新本地计划和停滞保护契约 |
| `docs/context-design.md` | 补充计划摘要、来源及恢复一致性说明 |
| `docs/analysis/agent-improvement-20260917/README.md` | 标注第二步新状态，保留历史交付日期 |
| `docs/analysis/agent-improvement-20260917/step-2-planning-context-and-recovery.md` | 本实施、验证及边界记录 |

未改依赖、数据库 schema、发布配置及项目状态快照。完成前核对了相对任务开始副本的差异与 Git 状态；原有 333 个状态条目无消失或状态回退，新增状态条目仅为本次 3 个原先干净的前端文件及 5 个新增文件。测试目录和构建目录均被 Git 忽略。

交付边界：本次完成的是本地主循环的计划、进展、压缩、恢复及验证对齐。多 Agent 委派、通用 DAG、跨工作区调度、候选安装包与真实模型试用未在本次实施；不能据此宣称与 Codex 的所有产品能力完全一致。项目状态快照 `docs/project-state.md` 按会话入口约定保留，本次仅同步相关设计说明和实施记录。

## 10. 2026-09-20 规划协作模式与 Codex 对齐

在第 9 节的实现基础上，补齐“调研 → 关键问题澄清 → 提交实施计划 → 用户选择执行”的闭环。继续使用同一 Agent 主循环，范围不包含多 Agent、DAG 或新模型服务。规划任务的结束与实施目标的验证完成分别记录。

### 实际行为

- 输入器增加“规划 / 执行”切换和 `/plan`，能力未开放时保留原界面。规划期间后端拒绝文件写入、补丁及命令，不依赖模型自觉遵守；任务页面重开后回显当前协作模式。
- `request_user_input` 提供 1–3 个问题、可选建议与自由回答。等待问题、目标版本和操作回执持久化；回答与用户消息、目标修订原子提交。重复提交幂等，过期回答明确冲突；暂停、追加约束、取消和重启使旧问题失效。
- 规划完成时必须有与当前目标一致、覆盖必需验收项的计划。拟实施步骤保持待执行，过时步骤可取消，输出明确“尚未执行”。有效执行预算不计算用户等待时间。
- “按计划执行”校验计划版本、状态版本、检查点、会话最新运行、模型配置与剩余预算，在事务提交后启动关联任务。原目标、用户限制、计划及预算继续沿用，工具审批仍单独执行。“修改计划”保留输入器已有草稿。
- 新增 `supersedes` 关联失败步骤及后续补救链。后续成功可以解除该计划阻塞，失败历史保留；文件、测试及其他完成要求仍独立验证。

### 本轮文件清单

下表为本轮相对开始副本的变更，不包含第 9 节已经存在的其他改动。

| 文件 | 本轮变化 |
|---|---|
| `src/private_agent_core/planning.py` | 补救关联、结构化问题契约与引用校验 |
| `src/private_agent_local/planning.py` | 草案验收、补救链与检查点摘要 |
| `src/private_agent_local/planning_interaction.py` | 新增澄清等待、回答事务与实施交接 |
| `src/private_agent_local/runtime.py` | 协作模式、工具执行边界、规划提示及交接上下文 |
| `src/private_agent_local/tool_registry.py` | 注册规划澄清工具及补救说明 |
| `src/private_agent_local/task_constraints.py` | 规划只读限制、回答来源恢复 |
| `src/private_agent_local/context_manager.py` | 从有效执行时长扣除用户等待 |
| `src/private_agent_local/core_adapter.py` | 运行开始事件携带协作模式 |
| `src/private_agent_local/completion.py` | 独立核对规划交付，不声明实施完成 |
| `src/private_agent_local/app.py` | 能力位、模式输入及两个版本化交互接口 |
| `src/private_agent_local/recovery.py` | 等待状态、规划交接的现场核对 |
| `src/private_agent_local/run_controls.py` | 控制操作使旧问题失效，恢复保留模式 |
| `src/private_agent_local/store.py` | 等待任务纳入活动集合，重启失效问题并同步检查点 |
| `apps/desktop/src/api/runtime.ts` | 声明规划能力位 |
| `apps/desktop/src/features/coding/api/planning.ts` | 新增回答与实施请求封装 |
| `apps/desktop/src/features/coding/api/recovery.ts` | 规划控制回执类型 |
| `apps/desktop/src/features/coding/model/contracts.ts` | 首条消息保留协作模式 |
| `apps/desktop/src/features/coding/model/runContracts.ts` | 等待状态、问题和协作模式契约 |
| `apps/desktop/src/features/coding/model/runProjector.ts` | 问题事件/快照恢复、终态清理及补救引用 |
| `apps/desktop/src/features/coding/model/runOutcome.ts` | 展示等待回答状态 |
| `apps/desktop/src/features/coding/components/CodingComposer.vue` | 模式切换、`/plan` 与草稿保留 |
| `apps/desktop/src/features/coding/components/CodingThreadWorkspace.vue` | 接入规划卡片及关联执行任务 |
| `apps/desktop/src/features/coding/components/PlanningInteractionPanel.vue` | 新增问题表单、实施/修改入口和幂等重试 |
| `apps/desktop/src/features/coding/components/RunPlanPopover.vue` | 展示失败补救关联 |
| `apps/desktop/src/features/coding/components/RecoveryPanel.vue` | 显示回答与计划交接回执 |
| `apps/desktop/src/features/coding/components/ThreadHeader.vue` | 等待回答图标 |
| `tests/unit/test_local_plan_mode.py` | 新增后端模式、交接、权限、回滚、重启与等待预算用例 |
| `tests/unit/test_local_model_contract.py` | 默认执行模式不暴露澄清工具 |
| `apps/desktop/src/features/coding/components/PlanningInteractionPanel.spec.ts` | 新增回答、冲突、重试及卸载保护用例 |
| `apps/desktop/src/features/coding/components/CodingComposer.spec.ts` | `/plan` 载荷、空指令与草稿保护 |
| `apps/desktop/src/features/coding/model/runProjector.spec.ts` | 问题回放、旧事件与终态处理 |
| `apps/desktop/e2e/planning-mode.spec.ts` | 新增完整页面流程、重开任务及窄屏验证 |
| `scripts/run_coding_validation.py` | 将新增规划模式测试纳入隔离套件 |
| `docs/local-tool-system.md` | 同步模式、接口、等待、交接及补救契约 |
| 本文 | 记录本轮实现与实际验证，保留前次历史 |

### 实际验证

后端均通过现有隔离脚本，在临时项目和独立 SQLite 中使用受控模型响应，没有调用付费模型或使用生产数据库。

| 仓库根目录命令 | 最终结果 |
|---|---|
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite orchestration` | 44 passed |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite context` | 44 passed |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite recovery` | 41 passed |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite completion` | 234 passed |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite tools` | 78 passed |
| `.venv\Scripts\python.exe -B scripts/protocol_codegen.py --check` | `protocol codegen in sync: OK` |

在 `apps/desktop` 实际执行，前端 103 项、浏览器 1 项通过：

```powershell
node node_modules/vitest/vitest.mjs run src/features/coding/components/PlanningInteractionPanel.spec.ts src/features/coding/components/CodingComposer.spec.ts src/features/coding/components/CodingThreadWorkspace.spec.ts src/features/coding/components/RecoveryPanel.spec.ts src/features/coding/components/RunPlanPopover.spec.ts src/features/coding/components/ThreadHeader.spec.ts src/features/coding/model/runProjector.spec.ts src/features/coding/model/runOutcome.spec.ts src/features/coding/composables/useRunStream.spec.ts
node node_modules/@playwright/test/cli.js test e2e/planning-mode.spec.ts --retries=0
npm.cmd run build
```

构建包含 `vue-tsc --noEmit` 与 Vite，均通过。已查看 Chromium 的 1280 像素问题卡和 640 像素计划卡截图，修复选项两行内容被固定高度挤压的问题；窄屏按钮可见、页面无横向溢出。浏览器使用模拟 IPC 与路由，断流提示来自测试主动结束 SSE，不代表真实后端断线故障。

Python 静态检查命令及结果：

```powershell
.venv\Scripts\python.exe -B -m ruff check src/private_agent_core/planning.py src/private_agent_local/planning.py src/private_agent_local/planning_interaction.py src/private_agent_local/task_constraints.py src/private_agent_local/runtime.py src/private_agent_local/tool_registry.py src/private_agent_local/context_manager.py src/private_agent_local/core_adapter.py src/private_agent_local/recovery.py src/private_agent_local/run_controls.py src/private_agent_local/completion.py src/private_agent_local/app.py src/private_agent_local/store.py tests/unit/test_local_plan_mode.py tests/unit/test_local_model_contract.py scripts/run_coding_validation.py
```

结果为 `All checks passed!`。首轮新增测试中错误使用辅助函数返回类型、工具暴露预期、导入顺序和新增状态图标的遗漏均已修正，未删除用例或放宽行为断言。部分原有进程用例及前端启动在沙箱中遇到 `WinError 5` / `spawn EPERM`，在允许本地子进程的环境重跑相同用例后通过。浏览器初轮未重新打开刷新后返回首页的任务，补齐操作后通过。

### 边界与项目记忆核对

读取了 `docs/project-state.md`、本设计记录和本机工具系统说明，并以当前源码核对。项目状态快照记录的是较早日期，不作为本轮已交付能力的证明；相关新增契约与结果在本轮文档同步。遵守会话入口约定，不自动改写 `docs/project-state.md`。

相对开始时 `git status --porcelain=v1 -uall` 的 361 条记录，无原状态条目消失或回退；新增 9 条为本轮 3 个原先干净文件的修改及 6 个新增文件。完整增量审查使用任务开始副本，未清理或回退其他会话改动。备份、测试输出与构建目录均被 Git 忽略。

尚未做真实模型规划质量评估、Tauri 安装包验收或部署。保留已有 Ant Design 大于 500 kB 的分包提示，以及浏览器测试的 `NO_COLOR` / `FORCE_COLOR` 环境提示；本轮未升级依赖、改数据库 schema、提交或推送代码。
