# PrivateAgent 任务中断、现场核对与续跑改造计划书

日期：2026-10-21（Asia/Shanghai）  
用途：交给 DeepSeek 执行的本地开发与验收方案。  
状态：**首轮已实施（2026-10-21），验证证据见第 15 节**。编制时只核对源码、现有差异、测试入口和此前的官方资料；第 15 节之前的正文保留计划原貌，不改写为完成记录。

## 1. 交付目标与范围

让用户在任务中断、退出应用、网络故障后重新打开会话时，能够明确看到已完成内容、未确认操作、剩余预算和可用恢复动作，并在核对后继续工作。

保留现有 Tauri/Vue、Python 本机执行器、共享 AgentRuntime、SQLite 和权限审批链。首轮按 **M0 → M1 → M2 → M3 → M4 → M5** 顺序推进。

| 阶段 | 交付内容 | 验收重点 |
| --- | --- | --- |
| M0 | 核对基线、复现风险、建立故障矩阵 | 先获得可复跑证据，保留其他会话改动 |
| M1 | 活动耗时持久化与离线间隔分离 | 次日恢复不因关机间隔耗尽预算 |
| M2 | 未知操作的核对与处理闭环 | 原始事实不改写，处理决定可审计，未确认进程继续阻塞 |
| M3 | 可恢复失败续跑、显式选择恢复模型 | 不重放旧工具，不重置预算，不跨路由发送旧原生状态 |
| M4 | 恢复面板与按轮次查阅、回滚已确认补丁 | 用户能完成操作；文件变化后拒绝过期预览 |
| M5 | 故障注入、兼容性与文档交付 | 真实子进程退出、界面交互与源码检查分别验收 |

**首轮文件恢复的明确边界：**复用现有补丁预览和逐补丁回滚，增加按运行轮次及续跑链查阅的入口。保留当前会话历史，通过追加事件说明回滚后的现场。首轮不承诺“一键回到任意消息前的全部文件与对话”。

首轮不引入 LangGraph、Temporal、shadow Git、向量数据库、新后台服务、独立恢复数据库或新的必填配置；不升级依赖、重建锁文件、调整正式版本或打包发布。不实现任意 Shell/远端操作自动重放、命令进程跨执行器重启重附着、跨设备恢复、自动增加预算、自动切换模型或自动调用真实模型。

## 2. 授权与实施规则

本文本身只是一份实施方案。用户明确把本计划交给执行 Agent 并要求实施后，执行以下范围内的本地开发；编制计划的当前会话不实施业务代码。

执行时以下内容属于已说明的必要改造：现有运行 JSON 增加可选恢复元数据；本机恢复响应增加可选结构化字段；增加现场核对提交与恢复预览接口；扩展现有 resume 请求的可选参数；同步前端类型、事件投影、恢复界面和相关测试。不得仅因这些已列明的接口调整再次请求同一范围的批准。

遇到必须增加依赖、数据库表/列迁移、独立服务、扩大文件访问权限或其他未列明公共契约的情况，先说明必要性、替代方案与兼容边界，完成不依赖该决定的工作后一次性确认。不要为普通实现细节反复中断实施。

- 遵循适用的 AGENTS.md；默认中文沟通，新增或实质修改的注释使用简体中文。
- 不提交、建分支、PR、推送、发布、部署、远程写入或自动更新安装包。
- 不读取真实用户数据库、模型密钥、完整环境配置或生产日志正文。测试仅用合成项目、隔离 SQLite、受控模型与测试宿主。
- 不把恢复确认变成新的权限授予；原有路径限制、禁止事项、逐次审批和限时完全访问授权继续生效。
- 保留其他会话的工作；不 reset、clean、强制覆盖，不把全工作区差异列为本次成果。
- 不自动启动其他 Agent。用户自己安排 DeepSeek 执行，不代表允许当前 Agent 向其他会话发消息或代为调度。
- 不更新 docs/project-state.md 或用户级记忆；实施只同步受影响的普通技术文档，除非用户另外明确要求维护记忆。

## 3. 当前基线与源码入口

编制时目录：`F:\Program\Agent`；分支：`dev/1.0.0`；本地 HEAD：`87a8331`。未 fetch，不代表远端实时状态。

工作区已有上下文和记忆改造、自有下载源、学习文档等大量未提交与未跟踪内容。恢复链直接涉及的 `app.py`、`runtime.py`、`context_manager.py`、`context_history.py`、`planning/reflection` 配套和测试运行器也可能与其他任务重叠。执行者必须从当前文件做增量修改，不能用 HEAD 覆盖它们。此前记忆计划见 [上下文与记忆改造计划](2026-10-20-context-management-improvement-plan.md)，本计划不接管其阶段状态。

| 入口 | 当前职责与本计划接入点 |
| --- | --- |
| [store.py](../../src/private_agent_local/store.py) | SQLite 事务、事件与检查点提交、启动恢复；M1 计时、M2 持久化 |
| [recovery.py](../../src/private_agent_local/recovery.py) | 检查点校验、blockers、恢复资格、模型版本核验；M2/M3 核心 |
| [run_controls.py](../../src/private_agent_local/run_controls.py) | 控制幂等、状态版本、安全边界、关联续跑；M2/M3 提交链 |
| [runtime.py](../../src/private_agent_local/runtime.py) | 运行创建、父子继承、执行循环、关闭清理；M1/M3 生命周期 |
| [context_manager.py](../../src/private_agent_local/context_manager.py) | 单调时钟、活动预算、历史组装和模型配置；M1/M3 |
| [context_history.py](../../src/private_agent_local/context_history.py) | 原始上下文、压缩检查点、缺失工具结果补记；恢复只读事实来源 |
| [core_adapter.py](../../src/private_agent_local/core_adapter.py) | 模型响应代次、工具派发、回执与上下文记录；防旧调用重放 |
| [workspaces.py](../../src/private_agent_local/workspaces.py) | 真实工作区锁、执行租约、未知现场阻塞；M2 统一处理结论 |
| [execution_store.py](../../src/private_agent_local/execution_store.py)、[execution_sessions.py](../../src/private_agent_local/execution_sessions.py) | 持续进程、输出与停止状态；不能用恢复按钮伪造 stopped |
| [integration_mcp.py](../../src/private_agent_local/integration_mcp.py) | prepared/dispatched/acknowledged、未知写入、逐次审批 |
| [completion.py](../../src/private_agent_local/completion.py) | 禁止/未知操作范围、证据核验与完成判断；必须保留来源区别 |
| [planning.py](../../src/private_agent_local/planning.py) | 计划与相关状态摘要；新增恢复决定必须绑定检查点 |
| [patchsets.py](../../src/private_agent_local/patchsets.py) | 原子文件写入、逐项日志、现场事实与安全回滚；M2/M4 |
| [task_review.py](../../src/private_agent_local/task_review.py) | 最近一轮/整个会话/工作区的变更聚合；M4 复用 |
| [app.py](../../src/private_agent_local/app.py) | 本机身份、恢复与控制路由、能力声明、错误映射 |
| [direct_models.py](../../src/private_agent_local/direct_models.py)、[model_errors.py](../../src/private_agent_local/model_errors.py) | 供应商错误映射、模型调用与敏感内容过滤；M3 错误分类 |
| [core/context.py](../../src/private_agent_core/context.py)、[core/contracts.py](../../src/private_agent_core/contracts.py) | 配置版本、上下文与不透明供应商状态；不随意修改共享协议 |
| [recovery.ts](../../apps/desktop/src/features/coding/api/recovery.ts)、[pendingControls.ts](../../apps/desktop/src/features/coding/model/pendingControls.ts) | 前端恢复类型、请求幂等与刷新后的待确认控制 |
| [RecoveryPanel.vue](../../apps/desktop/src/features/coding/components/RecoveryPanel.vue)、[RunControlBar.vue](../../apps/desktop/src/features/coding/components/RunControlBar.vue) | 恢复操作、阻塞说明、模型选择与处理记录 |
| [CodingThreadWorkspace.vue](../../apps/desktop/src/features/coding/components/CodingThreadWorkspace.vue)、[useRunStream.ts](../../apps/desktop/src/features/coding/composables/useRunStream.ts) | 会话重开、最近运行恢复、事件补读和续流 |
| [TaskReviewPanel.vue](../../apps/desktop/src/features/coding/components/TaskReviewPanel.vue)、[PatchReviewPanel.vue](../../apps/desktop/src/features/coding/components/PatchReviewPanel.vue) | 按轮次查阅、补丁差异与回滚；M4 不另造第二套审阅 |

### 已确认行为与待验证风险

1. 重要事件、运行状态与检查点已有事务提交；文件写入已有逐项日志。保留它们。
2. 重启将活动运行转为 interrupted，旧审批失效；未知命令/MCP 写入阻止继续。
3. `Store._recover()` 对 running 记录把最后检查点至启动恢复的墙钟间隔加入 active_seconds。这可能把离线间隔计作活动时间，属于源码可见风险，M0 必须复现后再修复。
4. `Recovery.inspect()` 目前只允许 paused/interrupted/cancelled 续跑，模型配置/能力指纹不匹配就拒绝。
5. 未知副作用会影响工作区租约；当前核对入口主要展示阻塞原因，缺少本计划要求的完整处理闭环。
6. 已有按运行查看补丁和回滚能力。不要把 M4 写成从零新增这些能力。

此前同一会话执行过前端 useRunStream/RecoveryPanel 定向测试，20 项通过；后端 recovery 隔离套件曾未完成并被中止，没有通过结论，也没有确认停滞原因。这些结果只用于定位后续检查范围，不能替代 M0 当前基线。

## 4. 必须保持的恢复不变量

1. **记录不等于授权。** 检查点、计划、摘要、人工核对说明和模型判断均不能绕过原权限链。
2. **保留原始事实。** 原 unknown、失败、缺失结果和补丁日志不覆盖为成功；新增核对决定采用追加记录。
3. **不自动重放。** 不从 pending_response、旧审批或历史调用序列恢复派发。续跑从当前历史和磁盘事实重新规划。
4. **未确认进程必须阻塞。** 不能因“我已看过”“放弃任务”或超过一定时间，把 stopped=False 改成 True，或强行清除工作区锁。
5. **预算连续。** 原逻辑任务已记录的请求、工具次数、Token、费用、有效耗时和失败次数按原规则继承。人工处理未知副作用不等于已修复失败，不自动清空纠错计数。
6. **未知费用保持未知。** 未配置费用上限时按其他预算处理；配置了费用上限且无法确认已用费用时，不允许通过取消勾选、恢复计时或切换模型绕过门禁。
7. **版本与幂等。** 所有写控制携带 request_id、expected_state_version；涉及检查点、模型或文件预览时再绑定相应摘要。重复请求返回同一结果，不产生第二条续跑链。
8. **区分来源。** 机器校验事实、用户人工说明、模型报告分别标记。用户确认不能被完成验证器当成机器验证成功。
9. **原历史可读。** 恢复、回滚和模型切换通过追加记录表达，不删除用户原文、旧模型输出、工具事实和旧压缩检查点。

## 5. M0：接手、基线与复现

### 实施步骤

1. 完整阅读 AGENTS.md 和 docs/project-state.md；当前代码优先于旧环境记录。
2. 执行以下只读核对，再只查看与本计划有关的差异：

   ```powershell
   Set-Location F:\Program\Agent
   git status --short --branch
   git log -5 --oneline
   git diff --stat
   git diff --staged --stat
   ```

3. 确认表中源码入口、字段与测试命令仍有效；发现已被其他会话完成的内容，先验收，不覆盖重写。
4. 先运行 recovery 基线。若停滞，定位最后测试/阶段，使用有超时和所属进程回收的隔离运行方式；不放宽产品沙箱、跳过有效断言或访问业务库。
5. 在现有隔离测试中复现：running 任务退出后，推进恢复时钟至次日，观察 active_seconds、blockers 和 can_resume；另测 paused、waiting_approval、waiting_input。
6. 固定 unknown 文件、unknown 命令、dispatched MCP 写入、acknowledged MCP 回执、供应商断流、模型配置变化等后续夹具。

### 验收与停止条件

- 明确记录“源码观察 / 已复现 / 环境阻塞 / 尚未运行”，不能把缺失基线说成已通过。
- 测试目录与生产隔离，故障进程能按所属关系回收。
- M0 未完成时可处理确定的局部问题，但不能把 M1–M5 标记为完成；不得先大改后补造改造前结果。

## 6. M1：活动耗时与离线间隔分离

### 实现决定

- 活动时长以进程内单调时钟和已提交的预算快照为依据。启动恢复不再用 `now - checkpoint.created_at` 追加 active_seconds。
- 在现有 run JSON 内增加可选 timing 元数据，至少区分：最后确认的活动耗时、最后回执时间、进程时钟标识、是否存在未确认尾段。字段采用一个有版本的内部对象即可，不新增表。
- 复用 LocalContext.budget_snapshot() 作为活动耗时计算来源，不建立第二套累加器；暂停、审批等待、用户输入等待继续按现有规则排除。
- 长模型请求/工具执行期间，由 Runtime 生命周期管理一个轻量周期任务，建议 5 秒保存一次活动预算回执；仅处理有活动上下文的运行。运行创建、等待、暂停及结束边界也保存最新值。
- 周期回执只更新必要 JSON 元数据，不生成每 5 秒一条公开事件/完整恢复检查点，不扫描文件、复制工具正文或增加模型请求。保存与结束/取消必须串行核验运行仍活动，防止迟到回执覆盖终态；close 必须取消并等待该任务。
- 崩溃后无法确认的尾段标记为未知，不把关机间隔算进去，也不声称计时精确。界面显示“已记录活动时间，末段耗时未确认”，继续动作明确接受该不确定性；不得重置已记录用量或增加预算上限。
- 旧记录缺少 timing 元数据时采用最后已提交预算，不追加离线时间。已经被旧版本按 conservative_until_restart 填满预算的记录，不自动回减或修改历史；单独说明该兼容边界。

### 测试与验收

- 活动 30 秒后退出、模拟次日恢复：已确认耗时保留，不变为 24 小时或直接填满上限。
- 活动、暂停、等待审批、等待输入分别计时；重复重启不重复累加。
- 周期回执与 finish/cancel/close 竞态：终态、检查点与历史预算不被迟到更新回退，无后台任务泄漏。
- 进程墙钟前跳/后跳不改变单调活动计时；缺失或损坏元数据不能伪造已知耗时。
- 原请求数、工具次数、Token 和费用限制仍能触发停止；不以恢复计时为由提高硬上限。

## 7. M2：未知现场的核对与处理闭环

### 7.1 响应与接口

保留 `GET /agent-runs/{run_id}/recovery` 的旧字段 `can_resume`、`blockers: string[]`、checkpoint_id、state_version 等；增加可选结构化详情，使新版 UI 不必解析中文错误字符串。至少表达阻塞类型、原 operation/execution/patch/change 标识、事实来源、可用动作与不能处理的原因。

新增本机提交入口：`POST /agent-runs/{run_id}/recovery/reconcile`。输入基于现有 ControlInput 扩展，包含 request_id、expected_state_version、checkpoint_id、待处理项标识、核对预览摘要和选择的处理方式；用户说明限制长度并经过现有敏感内容过滤。

处理记录复用 run JSON 与 run_control_requests；状态、控制回执、追加事件和新检查点在同一事务提交。记录标识、原操作绑定、证据引用、处理方式、机器/人工来源、时间和版本，不重复保存完整命令、外部响应或私密日志。达到有界记录上限时拒绝并解释，不静默淘汰尚有作用的决定。

新操作通过可选能力位声明。旧前端仍能读取旧字段；新前端遇到旧后端时禁用新增提交，保留只读核对和原有续跑入口。

### 7.2 按操作类型处理

| 现场 | 允许的处理 | 仍然禁止 |
| --- | --- | --- |
| 文件日志停在 applying | 在原路径、目录身份及文件身份校验通过后，对比 before/after 摘要；追加“当前匹配写前/写后”的机器观察，并明确是否可安全解除该文件项阻塞 | 猜测日志已完成、覆盖第三种内容、自动应用补丁剩余项 |
| 文件当前与 before/after 都不匹配 | 展示冲突路径、预期与实际摘要，保留文件；用户回到文件/补丁入口处理后重新核对 | 一个“忽略冲突”按钮直接解锁写入 |
| MCP 已持久 acknowledged | 复用绑定当前调用的回执，不重复发送 | 借用其他调用或复用 call_id 的旧回执 |
| MCP dispatched、无确认回执 | 可由用户在外部系统核对后提交“人工核对说明”；保留机器结果 unknown，明确接受未验证后续处理，不能据此产生成功证据 | 把用户一句“完成了”写成工具 success，恢复接口主动调用外部写工具 |
| 命令/进程结果未知 | 只有既有宿主终态、进程身份或进程树停止证据足够时，才能解除本地执行占用；输出缺失仍保留 | 凭 PID、时间经过、没有输出或人工勾选就认定进程已停止 |
| 放弃原任务 | 保留结果未知、停止该任务的后续恢复意图；仅在本地进程与文件操作已静止且其他风险已按本节处理后允许租约释放 | 放弃即清空所有 unknown、强行杀任意 PID 或无条件释放锁 |

文件“当前匹配 after”只证明此刻内容匹配，不证明整个工具调用、所有文件或所有命令副作用已完成。多个文件逐项核对，不将一项成功提升为整组成功。

### 7.3 处理决定怎样影响续跑

- 原 execution.status/error、patch journal 和 uncertain_operations 作为审计事实保留。通过有版本、可校验、绑定原项的追加决定派生“仍未处理的阻塞项”。
- Recovery.inspect、Workspaces._take/release、工具未知操作防护和完成验证器使用同一处理结论，不能出现“界面已解锁、执行器仍全拒绝”或“旧租约永久锁住”的两套判断。
- **人工核对外部结果**只能解除已明确接受的那一项风险对续跑资格的阻塞。保留它的未验证来源，不清空其他 uncertain_operations、denied_operations、失败记录或权限限制。
- 已处理的原操作仍进入禁止自动重复执行的清单。使用现有 tool_name、tool_version、arguments_sha256、工作区和必要的 MCP 来源绑定识别原操作；续跑继承该清单，不把新的 call_id 当成新操作。
- 若旧记录缺少足以可靠区分的参数指纹，维持保守范围限制并说明，不为了继续而猜测。对语义等价但参数不同的命令，不声称仅凭摘要就保证 exactly-once；原权限与用户明确指令仍是边界。
- 经机器核对确认没有落盘的文件操作，后续如需执行，必须重新读取、生成新预览并走原权限链；不直接派发原工具调用。
- 处理记录的摘要加入现有恢复检查点一致性校验；旧检查点仍按旧规则读取。新记录出现了处理决定却缺少匹配摘要时失败关闭。
- 核对提交只处理事实，不调用模型、不自动续跑。用户再明确选择继续，复查状态版本和所有剩余阻塞。

### 测试与验收

- 覆盖写前、写后、第三种内容、不可读、目录替换、移动成对依赖、部分落盘。
- 覆盖 MCP prepared/dispatched/acknowledged，以及同名工具、复用 call_id、来源版本变化。
- 人工说明不会成为 verified evidence；相同原操作不会因新 run_id/call_id 被自动执行第二次。
- 未确认进程停止时，继续、放弃后释放租约、另起同工作区任务都不能绕过阻塞。
- 相同 request_id 相同内容幂等；不同内容冲突；过期版本/检查点/文件预览失败且保留输入。
- 在记录提交前后退出：重启后要么没有决定，要么决定、事件和检查点一致；无半条授权或伪成功。
- 恢复项不能跨账号、项目、会话或工作区提交；说明中过滤敏感数据，不访问原项目范围外的路径。

## 8. M3：可恢复失败与显式选择恢复模型

### 8.1 恢复资格集中判定

将当前散落的资格判断收敛到现有 Recovery 中的一个清晰实现，供报告、预览、提交与租约核对按各自用途调用。不要另建通用策略引擎；租约核对不应被任务预算不足误判为磁盘/进程仍被占用。

保留原 paused/interrupted/cancelled；仅为明确属于模型传输/供应商暂时故障的失败增加手动续跑。首轮候选错误码为 `model_network_error`、`model_timeout`、`model_stream_interrupted`、`model_rate_limited`、`model_provider_unavailable`。M0 核对它们是否由当前适配器产生，逐一建立夹具；不要根据错误文案猜测。

| 分类 | 首轮处理 |
| --- | --- |
| 上述已确认的可恢复模型错误 | 无其他阻塞且预算足够时，提供用户手动继续 |
| unknown / execution_unknown / 文件冲突 / 无法确认进程停止 | 先走 M2，不归入可恢复网络错误 |
| 无权限、用户拒绝、历史损坏、检查点不匹配、未知错误码 | 保持阻塞，给出明确原因 |
| limit_exceeded、无进展、累计失败或费用上限不足 | 不自动增加预算或清零计数；说明剩余限制 |
| timed_out | 不按状态一概开放；只有证据明确是上述模型超时且本地操作已收敛，才按模型故障处理 |

续跑继续采用关联新 run 的方式，继承 logical_task_id、祖先引用、原目标、计划、约束、预算和失败事实。paused 且协程仍活动的原模型恢复保留同一 run；需要换模型时不得在线热切换暂停协程，使用经核验的关联新运行路径。若取消/整理原暂停协程产生 unknown，先处理 unknown，再允许创建。

### 8.2 恢复预览与模型变化确认

新增只读语义的 `POST /agent-runs/{run_id}/resume/preview`：接收可选目标 model_profile_id，返回当前恢复资格、目标模型身份与配置差异、能力缺口、预算说明和 preview_sha256。预览不发起真实模型调用，不修改默认模型或原运行。

扩展原 resume 请求的可选字段：选定 model_profile_id、目标配置/能力版本、preview_sha256、显式接受模型变化及未确认计时尾段的标志。老请求不传新字段时继续维持原模型严格校验，不能因新增选择器静默改变旧行为。

- 未选择新模型时，配置或能力变化仍然显示阻塞。用户可打开现有模型选择器，选择同一 profile 的新配置或另一个可用模型，核对差异后继续。
- 必须核对当前任务所需原生工具、图片、结构化输出、上下文容量、协议与路由；不支持时拒绝，不自动丢附件、改 Schema、改目标或放宽约束。
- 预览后配置、工作区、状态或检查点变化，提交返回冲突并保留选择；使用现有 409 冲突处理约定，不循环自动确认。
- 在事务内提交控制回执、关联运行、继承字段和恢复说明，事务成功后才启动协程。失败不能留下孤儿运行或重复用户消息。
- 原运行模型配置不改写；新运行记录选定模型和切换原因。会话/项目/全局默认模型保持用户原设置。
- 目标模型配置确实变化时，重新校准上下文计量；原供应商实际用量与未知费用不清零。原工具与预算上限不扩大。

### 8.3 原生供应商状态隔离

不能仅放宽 model_config_version 的相等判断。恢复组装链必须区分原路由的可公开历史和不透明 provider_state。

- 同一受支持路由可沿用通过验证的原生状态；端点、协议、供应商或模型变化时，保守使用公开历史投影，不发送旧 response id、加密推理条目或其他不透明状态。
- 不修改/清洗掉原始历史中的 provider_state；只对本次出站请求构造副本或派生投影。
- 沿用现有工具调用/结果配对和缺失结果处理；不把不完整旧响应里的工具重新变成待派发调用。
- 若现有公开投影无法形成目标协议合法输入，或必要上下文无法安全恢复，预览明确阻塞，不发送残缺请求碰运气。
- 恢复说明进入新运行上下文，明确已核对操作、未验证项、当前模型与权限；说明不替代原始用户指令，不自动写入长期记忆。

### 测试与验收

- 五类可恢复模型错误逐项测试；无权限、未知码、预算耗尽和副作用未知的反例保持拒绝。
- 用受控适配器记录实际出站 ModelRequest：同路由合法续接；跨协议/端点/模型不含旧不透明状态；原数据库历史保持不变。
- 附件视觉能力缺失、结构化输出缺失、小窗口无法容纳任务都在真实请求前阻止。
- 换模型不修改默认选择、不扩大权限、不复用旧审批；原用户拒绝与路径限制仍有效。
- 预览过期、重复提交、响应丢失、事务失败、暂停协程与新续跑竞态均不产生双运行。
- 新运行使用正确模型并继承所有累计预算；最终结果仍走现有完成验证，不把恢复成功等同于任务完成。

## 9. M4：恢复操作与文件现场的用户体验

### 9.1 统一恢复操作

复用 RecoveryPanel、RunControlBar 和既有模型选择器；共享类型与必要的控制请求状态，避免两个入口各自推导不同的恢复资格。只为现有重复状态提取小型复用逻辑，不重建整个工作台 store。

进入中断会话后首先展示：最后已确认完成的事项、当前文件与进程状态、阻塞原因、累计用量/剩余预算和下一步动作。空历史、旧协议或读取失败要有明确提示。

动作按实际资格展示：

1. 保留当前代码并继续任务：原模型无变化、没有待处理项时走现有确认链。
2. 核对未确认操作：打开 M2 的逐项观察与处理表单。
3. 选择模型后继续：展示配置差异、能力和预算预览，用户确认后提交。
4. 查看本轮修改：跳转已有任务审阅和补丁面板。
5. 放弃后续恢复：明确保留已修改文件和未知结果；若进程仍未核实，继续提示工作区占用。

用户文案解释行为，不暴露 operation_id、SHA、协议版本等开发字段作为主要流程；诊断详情中保留可复制标识。人工确认显示“用户已核对，系统未验证”；不会显示成“工具执行成功”。

延续 request_id 持久化：切换任务/刷新后仍能核对或重试同一次写控制；单纯恢复组件实例销毁不得丢掉待确认请求。旧页迟到请求不得更新新会话，卸载取消请求、轮询和定时器。

### 9.2 按轮次查阅和安全回滚

- 在现有 TaskReviewPanel 中按 run 和 resumed_from_run_id/logical_task_id 展示原运行及续跑关系，标注中断、人工处理、机器核对、模型切换和补丁状态。
- 使用现有 session review 与补丁接口，必要时给聚合响应增加可选元数据；不新建独立快照列表或再存一份完整对话。
- 提供“查看该轮补丁”“预览撤销这组补丁”，复用 PatchService.rollback_preview 和当前执行接口。选择确认前展示涉及文件、实际 diff、冲突、未包含的命令/外部变化。
- 当前文件或目录身份变化即拒绝过期预览；原有手工编辑、无归属变化、命令副作用和其他会话修改不能被整体覆盖。
- 首轮不自动拼接多组互相覆盖的补丁，不对多次修改同一文件的历史独立生成回滚后假装可以任意顺序应用。用户按当前可验证的最近补丁逐项处理，受阻则明确原因。
- 回滚依然需要原权限检查和独立确认。服务端必须校验当前工作区无活动执行、预览仍有效；不能仅依靠前端 disabled。只读/规划/禁止写入约束不能借“恢复文件”绕过。
- 回滚结果追加事件和新的用户可见现场说明，刷新补丁事实、完成证据与恢复资格；相关计划进入待核对。不得修改旧模型回答、原历史和旧“曾通过”的验证记录来伪造当前仍通过。
- 单纯浏览轮次、打开差异、刷新恢复报告不会写文件、发模型请求或创建运行。

### 界面验收

在真实浏览器的新实例完成以下流程，并检查宽窗口和约 390 CSS 像素窄窗口；接口可使用隔离路由夹具，但必须标注不是原生桌面或真实供应商验收。

- 中断记录重开 → 显示原历史 → 核对阻塞 → 明确继续 → 进入关联运行。
- 人工核对说明被保留，机器未验证状态可见；未确认进程不能通过按钮解锁。
- 可恢复模型失败 → 原模型继续；模型失效 → 选择新模型 → 查看差异 → 确认继续。
- 回滚预览后外部编辑文件 → 确认失败且用户修改保留。
- 控制响应丢失 → 刷新/切换会话 → 同一请求重试，不创建重复运行。
- 切换会话时迟到响应不污染新页；错误/冲突后保留表单；键盘焦点、按钮禁用原因、长路径换行与窄窗口确认可用。

## 10. M5：验证命令与故障矩阵

### 10.1 现有测试优先复用

- [test_local_recovery.py](../../tests/unit/test_local_recovery.py)：控制竞态、检查点事务、关联续跑、旧授权、模型变化与真实进程退出。
- [recovery_process.py](../../tests/coding_acceptance/recovery_process.py)：真实子进程在模型、工具、补丁 intent/disk/record 等边界退出。
- [test_local_execution_sessions.py](../../tests/unit/test_local_execution_sessions.py)：进程结果、身份与资源回收。
- [test_local_patchsets.py](../../tests/unit/test_local_patchsets.py)：文件回读、部分落盘、冲突和回滚。
- [test_mcp_memory_boundaries.py](../../tests/unit/test_mcp_memory_boundaries.py)：MCP 写入阶段、回执绑定和重启。
- [test_local_task_constraints.py](../../tests/unit/test_local_task_constraints.py)、[test_local_completion.py](../../tests/unit/test_local_completion.py)：恢复后的约束与完成证据。
- [useRunStream.spec.ts](../../apps/desktop/src/features/coding/composables/useRunStream.spec.ts)、[RecoveryPanel.spec.ts](../../apps/desktop/src/features/coding/components/RecoveryPanel.spec.ts)、[PatchReviewPanel.spec.ts](../../apps/desktop/src/features/coding/components/PatchReviewPanel.spec.ts)：界面恢复与交互。

测试过大时可增加 focused 的 recovery timing / resolution / model handoff 文件，并登记到现有隔离运行器的 recovery 套件；不要把每一阶段拆成新的测试框架。新增测试须验证外部可观察行为，不靠断言实现字段数量证明功能完成。

### 10.2 后端命令

在仓库根目录执行，分阶段按影响选择，最终只汇总已通过且仍适用的结果：

```powershell
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite recovery
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite execution
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite repository
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite mcp-memory-boundaries
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite completion
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite context-alignment
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite orchestration
.venv\Scripts\python.exe -B scripts/protocol_codegen.py --check
```

- M1 先跑 recovery 的计时与生命周期相关用例；M2 增加 execution/repository/MCP 边界；M3 增加 completion/context-alignment/orchestration。
- 若改动实际出站模型投影，增加当前对应适配器/Responses/模型路由已有测试；不要误把 direct-models 套件当作覆盖所有出站协议。先查当前 SUITES 后将必要用例登记到相关隔离套件。
- Ruff 仅检查实际修改的 Python 文件。安全、IPC、原生宿主或共享协议受到影响时，再增加对应套件；不默认执行 all。
- 若确需改变生成协议，先改事实源并使用既有生成器，禁止手改 generated 文件。只是本机可选 JSON 字段时，也运行现有 check，确认没有意外漂移。

### 10.3 前端命令

在 `F:\Program\Agent\apps\desktop` 执行：

```powershell
node node_modules/vitest/vitest.mjs run src/features/coding/composables/useRunStream.spec.ts src/features/coding/components/RecoveryPanel.spec.ts src/features/coding/components/PatchReviewPanel.spec.ts --maxWorkers=2 --minWorkers=1
npm run build
```

按实际新增内容扩展现有控制条/待确认请求/API/模型选择测试。新增的本计划浏览器场景可集中到 `e2e/task-recovery.spec.ts`，该文件是**待新增交付**，创建后执行：

```powershell
node node_modules/@playwright/test/cli.js test e2e/task-recovery.spec.ts
```

浏览器夹具不得连接个人数据目录或真实模型。若 1420 已被占用，先核对服务归属，使用既有 PA_E2E_BASE_URL / PA_E2E_EXTERNAL_SERVER 机制或独立测试端口，不停止未知进程。

### 10.4 必过故障矩阵

| 故障/变化 | 必须观察到的结果 |
| --- | --- |
| 仅 SSE/界面断开，后台仍运行 | 补读事件与快照，未创建第二次运行、未重放工具 |
| 模型请求中退出，次日重开 | 预算不计离线间隔，末段未知可见 |
| 暂停/审批/用户输入等待后重启 | 等待不计活动耗时，旧审批/问题按原规则失效 |
| 补丁 intent/disk/record/result 边界退出 | 已落盘文件保留，逐项核对，不自动写剩余文件 |
| MCP 发送前/发送后/回执落盘后退出 | 三阶段区别保留；未知写入不自动重复；已确认回执不丢失 |
| 命令启动后服务退出，进程停止未知 | 仍阻塞租约，不能凭按钮、PID 或等待时长解锁 |
| 核对决定、控制回执或新运行事务提交失败 | 无半提交决定/孤儿运行；重试仍对应同一请求 |
| 同 request_id 重试、改内容重试、过期 state_version | 同内容幂等；不同内容/旧版本冲突，输入保留 |
| 临时模型故障与真正的权限/历史/预算错误 | 前者可手动继续；后者继续阻塞，无自动降级 |
| 显式切换模型、协议或端点 | 出站请求不携带旧不透明状态，原历史和预算保留 |
| 回滚预览后用户编辑、目录身份变化 | 不覆盖用户编辑，预览失败，当前现场保留 |
| 旧记录、新旧前后端组合、读取更新数据库版本 | 兼容范围清晰；未知格式/更新数据库仍失败关闭 |
| 恢复/回滚后再次交付 | 旧证据重新核对；人工说明和历史成功不能伪装当前验证通过 |

至少使用现有 recovery_process 故障注入复跑关键真实退出场景，并覆盖 M1 计时与 M2 决定提交边界。模拟模型可以证明控制与数据一致性，不能证明真实供应商行为、断电持久性或已安装客户端效果。

## 11. 兼容、回退与数据保护

- 首轮保持 SQLite 当前 schema，不新增表/列；使用现有 JSON、控制回执和事件。不要为了避免新增表把无界正文塞入 run JSON。
- 旧记录缺字段时保持可读并保守派生状态；旧报告字段继续保留。对于旧记录缺失的原始调用摘要、路由信息或进程身份，不通过猜测补齐。
- 新处理记录和模型恢复元数据必须有版本和摘要绑定。旧二进制不能理解新处理语义时，不保证可继续写入；降级前须停执行器并核对兼容，不能宣称“可选字段意味着任意版本都能安全降级续跑”。
- 阶段回退只撤销本次明确拥有的代码差异，使用按块反向修改，保留其他会话改动。不得 reset 整文件、删除数据库、清空控制表或擦除追加记录。
- 真正涉及数据恢复时，先在所有所属进程停止后使用既有一致性备份能力；不要在 SQLite WAL 活动时只复制主库文件。生产数据回退不在本计划自动执行范围。
- M1 回退不能恢复错误的离线计时并把它当作已知事实；M2 回退应回到保守阻塞，不删除核对记录；M3 回退恢复严格原模型核验，但保留已创建新运行；M4 回退移除入口，不自动反向改用户文件。

## 12. 文档与最终交付要求

随实际改变更新现有 [工作台说明](../workbench-guide.md)、[本机模型直连](../direct-model-execution.md)、[本机工具系统](../local-tool-system.md)、[测试指南](../testing-guide.md) 中受影响的部分；无影响的文档不必修改。不得把首轮逐补丁回滚宣传为任意完整快照恢复。

每阶段给出简短回执：修改文件、实际行为、验证命令与结果、未完成/阻塞项和下一阶段。普通实现问题在既定范围内自行解决；只有扩大授权或实质范围才暂停确认。

最终必须列明：

1. M0–M5 各自“完成 / 部分完成 / 未完成”，证据来自哪个实际命令或操作。
2. 真正修复的问题，以及仍需人工核对的未知状态和旧记录限制。
3. 实际修改的文件和接口兼容方式；保留的既有差异不计入本次成果。
4. 测试通过、构建通过、浏览器夹具、真实宿主、真实供应商、已安装应用分别报告；未做的保持未验证。
5. 一次完整的用户操作路径：重开中断会话 → 核对现场 → 必要时处理风险/选择模型 → 确认继续 → 完成验证。

本计划的完成定义：首轮范围内的恢复流程可以实际操作，必要失败路径和故障注入通过，文档与差异审阅完成。仅保存字段、增加按钮、编译通过或演示一条顺利路径均不足以宣布完成。

## 13. 对比依据与后续范围

本计划吸收的是公开行为和工程取舍，不声称复制闭源 Agent 的内部算法。

- [Codex App Server](https://learn.chatgpt.com/docs/app-server)：持久线程/轮次/条目、恢复与分支、显式模型变化、会话历史与文件变化的区别。
- [Claude Code 会话](https://code.claude.com/docs/en/sessions)、[检查点](https://code.claude.com/docs/en/checkpointing)：会话续接、中断工具说明、按交互位置恢复，以及 Shell/外部变化的边界。
- [Gemini CLI 会话](https://geminicli.com/docs/cli/session-management/)、[检查点](https://geminicli.com/docs/cli/checkpointing/)、[Rewind](https://geminicli.com/docs/cli/rewind/)：会话自动保存与文件快照分工。
- [LangGraph Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)：节点结果持久化与恢复粒度参考，不是本计划的依赖选择。

以下留待首轮验收后的单独需求：任意消息位置的对话分支/回退、跨多组补丁的组合恢复、完整文件快照、长期命令独立宿主与跨进程重附着、远端系统幂等键/自动对账、多节点耐久执行。不得在首轮顺带实现。

## 14. 可直接发给 DeepSeek 的执行提示

```text
请在 F:\Program\Agent 按 docs/analysis/2026-10-21-task-recovery-improvement-plan.md 实施首轮任务恢复改造，范围为 M0–M5。

先读取适用 AGENTS.md 和完整 docs/project-state.md，检查 Git 状态及相关已有差异。工作区有其他会话的未提交修改，尤其 app.py/runtime.py/context_manager.py/context_history.py 和上下文记忆相关代码；请保留并基于当前文件增量修改，不从 HEAD 覆盖。

按顺序完成基线、活动计时修复、未知现场核对闭环、可恢复失败/显式模型续跑、恢复界面和逐补丁文件恢复入口，最后做故障注入与文档交付。此前只完成计划编制，不能把本计划或旧测试数量当成实现验收。

本次授权是计划内本地开发、所列必要接口/JSON 扩展、隔离测试和文档同步。普通实现细节自行处理；需要新增依赖、数据库迁移、独立服务、额外权限或扩大范围时，先说明具体必要性再确认。不要逐步重复索要已列明范围的批准。

保留原始历史与未知结果；不自动重放旧工具/审批，不凭 PID 或人工勾选确认进程退出，不把用户人工说明当机器成功证据，不清零预算/失败记录，不跨模型路由发送旧不透明状态。恢复操作仍受原权限、路径和审批链约束。

不提交、建分支、推送、发布、部署、调用真实付费模型或访问真实用户库/凭据；不更新项目状态记忆和用户级记忆。不要启动其他 Agent，不引入工作流框架或完整快照系统。

分阶段简报并持续完成范围内实现和验证。发现已有实现先核对和补齐；失败要区分新回归、既有问题和环境阻塞。最终给出阶段状态、修改文件、实际命令与结果、未验证边界和完整用户恢复路径。未完成的阶段明确写未完成。
```

## 15. 首轮实施记录与验收证据（2026-10-21）

状态：M0–M5 均已实施并在隔离测试中验证；真实执行宿主、真实供应商、已安装应用与真实用户数据未验证（见 15.5）。本节是 2026-10-21 首轮记录；2026-10-22 第三方验收发现 R1–R5 五项缺陷，判定首轮未整体通过，修正与新证据见第 16 节，本节的“完成”结论以第 16 节为准。

### 15.1 阶段状态

| 阶段 | 状态 | 主要内容 | 证据入口 |
| --- | --- | --- | --- |
| M0 | 完成 | 只读核对恢复链、取得基线；固定 unknown 文件/命令、dispatched 与 acknowledged MCP、供应商断流、模型配置变化夹具 | `--suite recovery` 基线 44 passed |
| M1 | 完成 | 启动恢复不再用墙钟间隔累加活动时长；进程内单调时钟周期回执（5 秒）持久化到运行 JSON；旧记录与旧策略保守派生 | `tests/unit/test_recovery_timing.py`（6 用例）、`--suite recovery` |
| M2 | 完成 | 结构化阻塞项、`POST /agent-runs/{id}/recovery/reconcile`、决定追加记录与检查点摘要绑定、租约与续跑资格共用同一结论 | `tests/unit/test_recovery_reconcile.py`（7 用例） |
| M3 | 完成 | 五类可恢复模型故障人工续跑、只读 `POST /agent-runs/{id}/resume/preview`、显式模型交接与跨路由公开历史投影 | `tests/unit/test_recovery_handoff.py`（16 用例） |
| M4 | 完成 | 恢复面板五个动作、按轮次续跑链标注与逐补丁撤销入口、控制请求跨刷新重试 | `RecoveryPanel.spec.ts` 等 30 passed；`e2e/task-recovery.spec.ts` 4 passed |
| M5 | 完成 | 故障矩阵与兼容回归、协议与静态检查、前端构建、文档同步 | 见 15.2–15.4 |

### 15.2 实际执行命令与结果

后端（仓库根目录，隔离目录 `.run/coding-agent-validation/`）：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite recovery            # 73 passed
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite execution           # 38 passed
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite repository          # 60 passed, 1 skipped（Windows 无符号链接权限）
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite mcp-memory-boundaries # 31 passed
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite completion          # 253 passed
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite context-alignment   # 114 passed
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite orchestration       # 46 passed
.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check                          # in sync: OK
.venv/Scripts/python.exe -m ruff check <本次修改的 Python 文件>                            # All checks passed
```

前端（`apps/desktop`）：

```powershell
node node_modules/vitest/vitest.mjs run src/features/coding/composables/useRunStream.spec.ts src/features/coding/components/RecoveryPanel.spec.ts src/features/coding/components/PatchReviewPanel.spec.ts --maxWorkers=2 --minWorkers=1   # 30 passed
node node_modules/@playwright/test/cli.js test e2e/task-recovery.spec.ts --retries=0   # 4 passed
npm run build                                                                          # vue-tsc + vite build 成功
```

直接运行 `pytest tests/unit/...` 时需要 `PYTHONPATH=src;scripts;tests/coding_acceptance;tests/unit`、`PYTHONUTF8=1`、`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`；缺少这些环境变量会表现为 `ModuleNotFoundError: recovery_process` 或插件重名，属环境阻塞而非回归。

### 15.3 故障矩阵对应关系

| 矩阵项 | 覆盖用例 |
| --- | --- |
| SSE 断开不建第二次运行 | `useRunStream.spec.ts`（断线重连只按原请求标识重试，不重复创建） |
| 次日重开不计离线间隔 | `test_recovery_timing.py::test_offline_day_is_not_charged` |
| 暂停/审批/输入等待不计时、旧审批失效 | `test_recovery_timing.py`（暂停回执）、`test_local_recovery.py::test_restart_checkpoint_unknown_commands_and_expired_approvals` |
| 补丁四边界退出保留已落盘、不自动写剩余 | `test_local_recovery.py::test_real_process_exit_preserves_checkpoint_and_partial_patch`（参数化 8 个边界） |
| MCP acknowledged/dispatched 区别保留 | `test_recovery_reconcile.py::test_dispatched_mcp_write_needs_manual_statement`、`test_local_recovery.py`（重启后 acknowledged 复用回执） |
| 命令启动后服务退出仍阻塞租约 | `test_recovery_reconcile.py::test_unknown_command_cannot_be_cleared_by_statement`、`test_local_recovery.py::test_real_host_start_then_service_exit_marks_unknown_without_replay` |
| 事务失败无半提交、无孤儿运行 | `test_local_recovery.py::test_control_transaction_failure_preserves_live_state_and_messages`、`::test_failed_resume_transaction_never_launches_orphan_run` |
| 同请求标识幂等、旧版本冲突 | `test_recovery_reconcile.py::test_reconcile_is_idempotent_and_rejects_changed_payload`、`test_local_recovery.py::test_version_conflict_and_request_id_reuse` |
| 临时模型故障可继续、真错误仍阻塞 | `test_recovery_handoff.py`（五类可恢复码 + 五类拒绝码） |
| 显式换模型不带旧不透明状态 | `test_recovery_handoff.py::test_public_projection_drops_native_state_across_routes` |
| 回滚预览后外部编辑不被覆盖 | `test_local_patchsets.py`、`test_local_recovery.py::test_review_distinguishes_user_edit_and_protected_rollback` |
| 旧记录与前后端兼容、库版本 | `test_recovery_timing.py`（缺失与旧策略记录）、`RecoveryPanel.spec.ts`（新入口按能力位隐藏）、`test_local_recovery.py::test_v6_migration_backup_and_future_version_rejection` |
| 恢复后再次交付重新核对证据 | `--suite completion`（253 passed）、`test_resume_preserves_consumed_verification_retries` |

### 15.4 修改文件

后端：`src/private_agent_local/recovery.py`、`store.py`、`runtime.py`、`run_controls.py`、`app.py`、`patchsets.py`、`context_manager.py`、`task_review.py`。
测试与脚本：`tests/unit/test_recovery_timing.py`、`test_recovery_reconcile.py`、`test_recovery_handoff.py`、`scripts/run_coding_validation.py`。
前端：`src/features/coding/api/recovery.ts`、`api/taskReview.ts`、`model/pendingControls.ts`、`components/RecoveryPanel.vue`、`TaskReviewPanel.vue`、`RunControlBar.vue`、`CodingThreadWorkspace.vue`、`RecoveryPanel.spec.ts`、`e2e/task-recovery.spec.ts`。
文档：`docs/workbench-guide.md`、`docs/local-tool-system.md`、`docs/direct-model-execution.md`、`docs/testing-guide.md`、本文件。

接口兼容：SQLite 保持 schema 10，未新增表或列；运行 JSON 新增可选 `timing`、`recovery_resolutions`、`model_handoff`、`model_switched_from_run_id`、`native_state_projection` 字段；`GET /recovery` 保留 `can_resume`、`blockers: string[]`、`checkpoint_id`、`state_version`，新增结构化详情；新增能力位 `coding_recovery_reconcile_enabled`、`coding_recovery_model_handoff_enabled`、`coding_recovery_timing_enabled`，旧前端不读新字段，新前端在旧后端上隐藏新入口。

### 15.5 未验证边界

- 真实执行宿主、真实供应商、已安装应用与真实用户数据目录：本次未运行，浏览器验收使用页面内路由夹具与 IPC 替身。
- 跨账号/项目/会话/工作区提交核对决定：接口按运行标识定位，未单独构造越权提交夹具。
- `TaskReviewPanel.vue` 只有 e2e 覆盖，没有独立单元测试。
- 已发布版本升级路径：本次只验证旧记录读取保守派生，未在真实安装上升级。
- Windows 符号链接相关用例在无该权限时跳过（1 skipped）。

### 15.6 用户恢复路径

打开中断会话 → 恢复面板先显示计时说明、结构化阻塞项、累计用量与上限 → 逐项“核对未确认操作”（人工说明标注“用户已核对，系统未验证”）或“放弃后续恢复” → 需要换模型时先取只读预览、核对能力缺口与预算后显式接受 → 选择“保留当前代码并继续”，创建关联新运行并继承目标、约束、累计用量与失败记录 → 在“环境与变更”按轮次查看并逐个预览撤销该轮补丁（撤销前重校验文件与目录身份）。

## 16. 验收缺陷修正记录（2026-10-22）

依据 `docs/analysis/2026-10-22-task-recovery-acceptance.md`（1×P1 + 4×P2，整体未通过）逐项修正。原则：只追加与派生，不删除未知结果、不清失败计数、不扩预算、不放宽其他门禁。

### 16.1 逐项结论

| 编号 | 原缺陷 | 修正 | 回归用例 |
| --- | --- | --- | --- |
| R1（P1） | 文件核对按共享 operation_id 放行同组其他文件；现场变化后旧决定仍放行 | `covers()` 对 `file_operation` 只按 `item_id`（补丁项 + 相对路径）匹配，不再用 operation_id 兜底；新增 `evidence_matches()`，核对记录必须绑定并复核当前现场摘要；提交必须携带报告中的 `evidence`，缺失或与现场不符分别报「核对依据缺失」与 409「核对依据与当前现场不一致」；失效记录保留为 `stale_resolution` 并追加说明，不再是放行依据 | `test_recovery_reconcile.py::test_file_decisions_are_bound_to_each_path`、`::test_stale_observation_stops_unblocking_after_file_changes`、`::test_unreadable_path_keeps_block_without_guessing` |
| R2（P2） | 报告可续跑，但新 MCP 调用仍被旧未知范围拦截 | `reconcile_mcp_execution()` 生成未知项时写入 `tool_name`/`tool_version`/`arguments_sha256`/`run_id`；`completion.unknown_side_effect()` 区分原调用（replay）、未确认调用（unknown）与缺少指纹（conservative），并接入 `integration_mcp`、`execution_tools`、`reflection`、`runtime` 四处理实际入口；缺指纹的旧记录在报告与界面标注保守阻止 | `test_mcp_library.py::test_dispatched_write_is_unknown_and_cannot_be_replayed`、`::test_resolved_unknown_write_blocks_original_call_but_allows_new_arguments`、`::test_unknown_write_without_fingerprint_keeps_conservative_block`、`test_mcp_memory_boundaries.py` 系列 |
| R3（P2） | 同一 profile 改配置后预览显示无需接受、提交却拒绝，界面无入口 | `preview()` 增加 `configuration_changed`/`capability_changed`/`changed`、`changes` 说明与 `requires_model_change_acceptance`；变更前事实改取运行已记录的 `recorded_model_facts()`；`validate_resume()` 允许同一 model_profile_id 的新配置在显式接受有效预览后继续，并要求绑定目标配置与能力版本；`context_manager.prepare()` 首次请求再次比对已接受版本，预览后配置再改以 `model_not_configured` 失败；恢复面板为空时也为当前模型提供「预览差异」与「接受当前模型的新配置后继续」 | `test_recovery_handoff.py::test_same_profile_configuration_change_needs_explicit_acceptance`、`::test_model_switch_requires_acceptance_and_bound_preview`、`::test_preview_is_read_only_and_stable` |
| R4（P2） | 能力预检拿累计用量当上下文容量、把所有附件当图片 | `capability_gaps()` 改用 `pending_context_tokens()`（`context_budget.estimated_input_tokens`，并扣除预留输出与 5% 余量）比较目标窗口；视觉要求改由 `vision_required()` 读附件 `requires_vision`，读取失败才保守要求；累计用量、未知费用仍独立继承 | `test_recovery_handoff.py::test_capability_gaps_use_pending_context_and_attachment_metadata` |
| R5（P2） | 390px 窄窗恢复面板被压窄、裁切，旧断言误判通过 | 恢复面板窄窗（≤640px）改为整屏覆盖层，动作按钮纵向排列占满宽度，长标识与说明换行；e2e 断言关键控件逐项落在视口内、面板与控件 `scrollWidth <= clientWidth`、窄窗直接进入与宽→窄两种路径均可操作 | `e2e/task-recovery.spec.ts`（5 用例，含 390px 直接进入与宽→窄转换） |
| 验收附带项 | 换模型后再次续跑时子运行不再带 `model_handoff`，出站投影退回 `native_same_model` | `runtime.create()` 在父运行带 `model_handoff` 或 `public_history_required` 时给新运行写入 `public_history_required`；`context_manager.public_projection()` 见到该标记即只发送公开历史投影，即使当次没有再次换模型；旧路由不透明状态仍由适配层按路由摘要二次过滤 | `test_recovery_handoff.py::test_second_resume_keeps_public_history_projection`（两次连续续跑，断言新运行模型为切换后的模型、标记已继承、出站消息清除 `provider_state` 且原历史不变） |

兼容说明：旧记录没有 `model_config_version`（未发生过模型请求）时无法比对模型事实，`preview()` 按当前默认模型展示，`validate_resume()` 只在用户显式指定其它模型时才要求找到目标配置；这类旧记录的模型校验仍保持原有的“不比对”行为，不会被当成已核对。

### 16.2 实际执行命令与结果（2026-10-22 复验）

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite recovery              # 78 passed (0:01:46)
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite execution              # 38 passed
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite completion             # 253 passed
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite context-alignment      # 114 passed
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite orchestration          # 46 passed
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite mcp-memory-boundaries  # 31 passed
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite repository             # 60 passed, 1 skipped（Windows 无符号链接权限）
.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check                             # in sync: OK
.venv/Scripts/python.exe -m ruff check <本次修改的 Python 文件>                              # All checks passed
```

前端（`apps/desktop`）：三个 spec 30 passed；`e2e/task-recovery.spec.ts` 5 passed；`npm run build` 通过。

### 16.3 修改文件（相对第 15 节新增）

后端：`recovery.py`（R1/R2/R3/R4、旧记录模型事实兼容）、`completion.py`、`integration_mcp.py`、`execution_tools.py`、`reflection.py`、`runtime.py`（R2 门禁统一、`public_history_required` 继承）、`context_manager.py`（R3 首次执行复核、跨路由投影标记）、`patchsets.py`（补充摘要事实）。
测试：`tests/unit/test_recovery_reconcile.py`（9 用例）、`tests/unit/test_recovery_handoff.py`（19 用例）、`tests/unit/test_mcp_library.py`、`tests/unit/test_mcp_memory_boundaries.py`。
前端：`RecoveryPanel.vue`（R3 同配置入口、R5 窄窗整屏）、`RecoveryPanel.spec.ts`、`e2e/task-recovery.spec.ts`。
文档：`docs/workbench-guide.md`、`docs/local-tool-system.md`、`docs/direct-model-execution.md`、`docs/testing-guide.md`、本文件。

接口兼容：仍为 SQLite schema 10，未加表或列；核对请求新增可选 `evidence` 字段，旧客户端不发送时由服务端按当前现场派生并复核（发送内容不符才冲突）；`GET /recovery` 新增 `blocker_details[].evidence`、`stale_resolution` 与 `resolutions` 摘要，旧字段 `can_resume`/`blockers` 保留；`POST /resume/preview` 新增配置/能力变化字段，旧客户端行为不变。

### 16.4 仍未验证的边界

- 真实执行宿主、真实供应商、已安装应用与真实用户数据：仍未运行；R2 的门禁验证使用受控 MCP 连接替身与真实工具入口，未连真实第三方服务。
- 判断 R2 的“旧记录缺指纹”在真实历史数据中的分布：只用合成旧记录验证。
- 两次以上连续换模型：`test_second_resume_keeps_public_history_projection` 覆盖“换一次模型后再按当前模型续跑”，未构造“连续两次都换模型”的用例；`public_history_required` 的继承逻辑对任意深度成立，但只有上述一条链被实测。
- 窄窗验收为本地夹具 + 截图复核，不等同于已安装 Tauri 窗口在真实缩放与系统字体下的表现。

### 16.5 用户路径（补充变化）

中断会话 → 恢复现场显示计时与逐项阻塞 → 文件类阻塞按具体路径逐项核对（核对依据必须与当前内容一致，现场再变即失效）→ MCP/命令类按原调用身份核对，核对后新参数按原权限链重新判定 → 需要换模型或同一模型配置已变时先预览差异并显式接受 → 窄窗下面板整屏显示，可完整操作 → 继续后新建关联运行，原未知结果、失败计数、预算与历史保持不变。
