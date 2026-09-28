# 阶段 C：真实模型入口、预算与过程指标

> 下文 2026-09-14 内容保留旧代理阶段的原始日期、成绩和限制。当前直连实现及本轮结论见文末“2026-09-15：直连适配与复验”；旧 `product_proxy` 命令不再适用于当前产品。

日期：2026-09-14（Asia/Shanghai）。工作区 `F:\Program\Agent`；基线 HEAD `1dde393e29f3dbacd3647d11834b39824ac8323f`。仅实施 [后续计划](./s6-follow-up-development-plan.md) C-01～C-05，不进入 D～F，没有提交、推送、部署、修改远程资源、读取生产凭据或调用付费模型。

## 验收状态

| 判断 | 本轮状态 |
| --- | --- |
| 开发与隔离测试 | **已完成**。C-01～C-05 已实现；最终直接套件 59 passed，control 30/30、matrix 15/15；完整回归及复验范围见实测表 |
| 实际产品路径的真实模型联调 | **待执行**。测试仅使用合成账号、HTTP/ASGI 替身及临时项目，没有目标模型或测试账号的真实联调授权 |
| 阶段 C 完整退出条件 | **未满足**。真实目标模型正负用例和远端实际安装身份尚无证据；不能以替身成绩宣布完整验收通过 |

已读根 `AGENTS.md`、`docs/project-state.md`、后续开发计划、阶段 A 验证记录、阶段 B 契约、B 补充报告和本地学习验收记录。未找到适用的下级 `AGENTS.md`。开工工作区已有 B 契约两行修改和未跟踪的 B 本地学习报告，均保留。基线差异和保护文件摘要在 `.run/s6-phase-c-20260914/`，不保证跨机器存在。

B 的公开样例只用于学习、校准和回归。独立保留题和保管回执缺失不阻断本轮 C 本地开发；正式 `independent_evaluation` 的 AppContainer、来源回执、未污染声明、完整设计和独立判定门禁保持有效。

## C-01：连接模式与入口

| connection_mode | 用途与调用路径 |
| --- | --- |
| fixture | 原 control/matrix 确定性回环；通过正式 IPC 驱动 Agent，由已知参考脚本提供模型响应，不能视为模型独立完成 |
| local_unbilled | 兼容原六字段本机不计费 JSON 配置；合成账号认证 → 本机 IPC → ConfiguredModels → 现有 OpenAI/Ollama 适配器 |
| product_proxy | 专用测试账号的正式登录会话 → 私有 stdio IPC → 本机 Agent → ConfiguredModels → Cloud → `/desktop/model/complete` 或 `/desktop/model/stream` → 服务器模型网关 |

新增 `--mode probe`：必须指定 1～3 个公开任务且 `--repetitions 1`，用于 C 的少量联调。它不会自动扩大为 D 的 90 次实验，也不进入正式质量分母。`quality` 仍要求三次重复；control/matrix 不能注入真实模型配置或向正式题集注入参考答案。各模式进入 manifest、冻结 schedule、尝试和汇总报告。

产品连接必须指定外部 JSON 清单及 `--isolation appcontainer`。真实推理另需 `--authorize-model-calls`；该开关仅供操作者在已有授权后使用，不代表本报告授予调用许可。`preflight` 可接收模型配置，只查询认证、模型和协议能力，不发起推理。工具网络仍为 `network_policy=none`，模型网络只经过既有受控传输层；不扩大工具权限或降级为 trusted_project。

测试账号会话仅在交互终端通过隐藏输入取得，内存中传入正式 Authorization/IPC 请求；非交互输入被拒绝。没有 token CLI 参数、环境变量或凭据文件入口，不自动提取桌面或生产账号配置。会话不写入清单、题集、报告、stderr 或子进程命令行；运行结束清除评测连接对象中的引用。用户须使用专用测试账号，不能在聊天中提供凭据。

## C-02：能力与错误

新增本机只读 `/model-evaluation/preflight?profile_id=…`，先经现有账号绑定，再按实际模型路由解析。检查 profile、模型、上下文容量、原生工具能力、推理参数、路由及预算协议；每次任务启动前重新查询并核对冻结摘要。声明能力只表示预检可进行，不代表普通回答、工具或流式推理已经实测成功。

普通响应、流式和旧代理的完整响应路径继续使用现有产品适配器。旧代理在推理发送**之前**通过能力 GET 选择 complete；已发送/消费的响应发生超时、断流、JSON 或序号错误时不切换为 complete 重放。服务器新增 `request_budget_protocol=1.0`：带 `X-Model-Request-Budget: 1.0` 的请求复制当前网关实例并将 `RetryPolicy.max_attempts` 限定为 1，不修改共享网关默认策略。`X-Model-Call-Id` 是有界关联标识（本机生成 UUID），成功响应回传它；服务器供应商 Key 仍留在原账号网关。

旧代理没有这个计数协议时仍保留产品完整响应兼容能力，但 product_proxy 评测预检返回 `provider_request_budget_capability_missing`。不能在供应商内部重试数未知的情况下声明请求预算可执行。旧记录的供应商调用数和重试数标为 unknown，不用零代替。

| 场景 | 分类/记录 |
| --- | --- |
| 账号 401/403 | cloud_auth_required，保留失败，不输出认证响应正文 |
| 所选 profile 不存在 | model_not_found；供应商不存在所选模型经既有头部归为 model_model_not_found |
| 工具/参数或计数能力不足 | 预检 missing 列表或 model_unsupported_capability |
| 服务器接口 404 | cloud_interface_missing；capabilities 404 只允许推理之前的旧协议协商 |
| HTTP/流式超时 | model_timeout；有效运行时长耗尽仍是 max_active_seconds |
| 连接失败 | model_network_error |
| 响应缺终帧/连接中断 | model_stream_interrupted |
| 错误 JSON | model_invalid_response |
| 流序号、请求绑定或文本不一致 | model_protocol_error |
| 流内供应商错误 | 固定允许列表中的 model_*，不回显任意错误正文 |
| 用户取消 | 保留 cancelled 与已有一次取消/只读终态核对；中断用量未知 |

阶段 A 的六种终态映射、轮询先读终态、单次取消、迟到 IPC 帧处理和事件连续性算法没有改写。新增预算上限沿现有 limit_exceeded 收束，未知计量沿 failed 收束，不伪造 cancelled。原 fixture 的 token 轮询取消场景保持历史语义；实际模型评测启用新的请求边界 token 限额。连接模式纳入冻结身份比较，不能将 fixture 行改标为 product_proxy；旧记录双方均无该字段时仍可解释。

## C-03：可复现信息

模型配置使用严格 JSON（拒绝重复键、未知字段、非有限数字和凭据字段）。原 local_unbilled 配置不要求升级。产品连接配置 schema 为 1，预算对象使用下述预算 v2，完整字段示例仅供**获得授权后填写**：

```json
{
  "schema_version": 1,
  "connection_mode": "product_proxy",
  "endpoint": "https://test.example.invalid",
  "profile_id": "replace-with-test-profile",
  "model": "replace-with-model",
  "model_version": null,
  "context_tokens": 131072,
  "parameters": {"reasoning_effort": null, "max_output_tokens": 2048, "auto_compact": true},
  "budget": {
    "max_model_requests": 8, "max_tool_calls": 12, "max_active_seconds": 60,
    "max_attempt_tokens": 10000, "max_total_tokens": 10000,
    "cost_usd": null, "total_cost_usd": null,
    "max_total_model_requests": 8, "max_total_tool_calls": 12, "max_total_active_seconds": 60
  }
}
```

示例地址不可用，数值不是调用授权或推荐预算。`model_version=null` 表示服务端未给出可识别版本；模型名/别名不被当作不可变版本。指定版本时必须与预检一致。保存实际 profile、路由、上下文容量、协议能力、可识别版本及未知原因、推理强度、输出限额、压缩参数、真实运行 `permission_mode=confirm`，并保存配置文件摘要。未暴露的供应商默认参数标记 unknown，不推断温度/随机种子等。

产品源码身份覆盖共享核心、本机执行器及本仓库桌面模型代理源码；题集、验收材料、运行器、每次任务和实际隔离证据沿 B 的摘要链绑定。**本仓库代理源码摘要不证明远端加载的安装副本相同。** 实际服务器版本、供应商版本和已安装桌面客户端仍须真实联调确认。每次请求的关联 ID 与本机事件关联，跨机器只记录关联关系，不直接相减两台机器时间。

## C-04：预算版本与结算

外部题集同时接受 schema 1 和 2。schema 1 保持原字段、约束、原始字节摘要和历史解释，`cost_usd` 仍只能为 null。schema 2 的顶层预算和每题预算都增加三个整场计数/时长字段与 `total_cost_usd`；`cost_usd` 可为有限正数或 null。不会改写仓库已有 30 题及历史清单。

| 维度 | 单次 | 整场 | 执行边界 |
| --- | --- | --- | --- |
| 请求 | max_model_requests | max_total_model_requests | 本机下一请求前检查；产品代理协商一次供应商尝试，失败/取消仍消耗已尝试次数 |
| 工具 | max_tool_calls | max_total_tool_calls | 沿既有运行时计数/执行前门禁；下一次任务传入整场余量 |
| 有效时长 | max_active_seconds | max_total_active_seconds | 同一运行时 monotonic，扣除审批/暂停；模型和工具使用现有超时边界 |
| token | max_attempt_tokens | max_total_tokens | ContextLimits.max_total_tokens 控制单次运行；响应后结算，下次请求前拒绝超额或未知用量 |
| 费用 | cost_usd | total_cost_usd | 只结算实际 usage.cost_usd；无价格/用量时标记 unknown，存在费用限额时阻止下一请求/下一任务 |

模型配置、清单及整场剩余配额取最小值。schema 1 未显式定义的总请求/工具/时长按冻结 schedule 的单次上限乘计划次数派生；总 token 沿原 max_total_tokens。预算 v2 上限为总请求 2160、总工具 4320、总有效时长 54000 秒、总 token 10800000；单次仍遵循 B 上限。单次/总费用范围为 `(0,1000]` 或 null，不能把有明确限额的父预算扩成无限制。

整场顺序分配剩余额度，不要求为下一任务预留整个单次上限；已结算尝试 ID 不得再次结算。未启动条目不消耗模型配额，已经启动的失败/取消保留在追加式账本；用量未知则已知小计和总计分别保存，未知总计不能继续当作零额度已用。按响应计量的 token 和费用均为**软预算，不是账单硬上限**；一条请求可在响应后才发现超额。没有价格时不按 token 虚构费用；有费用上限但服务端不返回费用时，第一次响应后停止继续调用并报告未知。

fixture 的 token/费用属于模拟值，整场报告明确标记 `fixture_simulation_not_enforced`；暂停测试的 unknown 不会阻断后续校准，也不会被填成零。它仍保留既有单次运行/轮询预算，以及整场请求、工具和有效时长预算。这个分支只由“未配置真实模型”决定；local_unbilled 和 product_proxy 都执行完整用量预算及 unknown 门禁，模型配置不能关闭它。

有效时长不包含评测器工具准备、判定/清理；这些时间计入总耗时。审批中的快照也扣除当前尚未结束的等待，避免轮询把审批等待算作活跃执行。评测器自身 deadline 与产品有效时长上限继续分开记录。

## C-05：指标字典

指标协议 `s6-process-1`，预算汇总 `s6-budget-2`；历史 `s6-attempt-ledger-1` 追加式记录格式不变。新字段缺失的历史证据可继续读取，不补造新指标。每个尝试和 metrics.json 都保留过程与资源结果。

| 指标 | 定义、来源与缺失规则 |
| --- | --- |
| total_seconds / elapsed_seconds | 评测父进程 monotonic：该尝试的重建、IPC、运行、判定及清理总耗时；整场工具准备另属实验预检 |
| model_seconds | 同一 clock_id 下 model.requested 至 model.output.finished/interrupted 的区间并集；不包括请求前上下文组装 |
| tool_seconds | tool.requested 至唯一 tool.invocation_finished 的并集减审批等待并集；包括工具 API 等待输出，不将后台进程独立存活时长重复相加 |
| approval_seconds | tool.approval_required/resolved 按 approval_id 配对的并集；取消导致缺少配对时标明 unfinished_interval，实际累计等待仍见 run/loop_budget.approval_wait_seconds |
| active_seconds | 本机 LocalContext 的实际预算快照；排除审批和暂停；不能直接用其他机器墙钟推算 |
| model_requests | model.requested 事件数；含失败、取消和用户显式控制后新尝试 |
| provider_requests / provider_retries | 成功协商的传输元数据；本机适配器固定一次、零重试，产品代理以回传 call_id 和计数协议验证；失败、取消或旧协议缺计量为 unknown |
| verification_retries | 产品完成校验重试计数，单列于网络/供应商重试 |
| compactions / compaction_attempts | context.compaction_completed / started 的次数；当前本地压缩不发起额外模型调用 |
| model_tool_union_seconds | 模型与工具调用的总区间并集；分类区间可能重叠，不可将各列直接相加 |
| peak_processes | Windows QueryInformationJobObject 的本次 RuntimeClient 所属 Job 活动进程数；包括其子孙，不扫描/统计其他任务或系统进程；不含评测父进程和独立判定 Job |
| peak_sampled_storage_bytes | 只扫描本次 attempt 目录的文件量；不计全盘或其他实验；引用越界、权限等错误保留缺失原因 |
| interval_seconds / max_observed_interval_seconds / samples | 配置周期 1 秒，开始/结束额外采样，记录实际最大间隔及样本数。短进程及两次采样间峰值可能漏采 |

本机事件由 Runtime.event 添加 clock_id 与 monotonic_seconds。工具进程完成事件可能在一次 exec_command 返回后再次记录；它是不同事实，不用于再次关闭同一工具调用区间。工具唯一结束事件在执行适配器 finally 中记录，取消也不会重复结算。缺关联 ID、跨进程时钟混用、逆序、重复起点和未结束区间均产生 null 与 missing_reasons。真实模型评测缺必需过程/资源指标时不宣称联调成功。

## 实施文件

| 文件/组件 | 变更 |
| --- | --- |
| scripts/run_coding_acceptance.py | 连接/probe 入口、预检与身份冻结、剩余预算传递、指标/结果分类、脱敏异常定位 |
| scripts/coding_acceptance_models.py（新增） | 严格产品配置、安全会话输入、能力核对 |
| scripts/coding_acceptance_budget.py（新增） | 整场分配、单次/总额结算及未知状态 |
| scripts/coding_acceptance_metrics.py（新增） | 区间并集、关联核对、Job 与存储采样 |
| scripts/coding_acceptance_schema.py | schema 2 预算；schema 1 兼容 |
| scripts/coding_acceptance_evidence.py | 连接模式、预算、过程与资源汇总；保留 M3 blocked |
| scripts/coding_acceptance_transport.py | 回环能力/计数模拟，IPC 固定错误分类 |
| scripts/coding_validation_process.py | 暴露本次已托管 Job 给只读采样器 |
| scripts/run_coding_validation.py | model-evaluation 直接套件，纳入 acceptance/all |
| src/private_agent_core/context.py、contracts.py | 可选请求边界 token 配额；拒绝非有限费用 |
| src/private_agent_local/app.py | 已认证的只读模型预检与能力版本；固定错误码 |
| src/private_agent_local/cloud.py、local_models.py | 模型描述、协议/错误分类、关联与请求计量 |
| src/private_agent_local/context_manager.py | 响应结算和下一请求 token/费用检查；进行中的审批时间扣除 |
| src/private_agent_local/core_adapter.py、runtime.py | 请求关联、唯一工具调用结束、同域时钟、预算终态映射 |
| src/personal_assistant/api/routes_desktop_model.py | 评测单次供应商尝试协商与关联头，不重构 Provider |
| tests/coding_acceptance/test_s6_models.py（新增） | 配置、IPC/代理替身、预算/指标、错误与兼容测试 |
| tests/unit/test_desktop_model.py | 代理单次请求正反例；既有 Request 替身补齐 headers |
| tests/coding_acceptance/README.md、本报告 | 持久契约、命令、实测及限制 |

## 实际命令与结果

测试统一使用已有 Python 3.12.13；本机已有 Node 24.14.0 / npm 11.9.0。默认工具环境的 Codex Node 未发现 npm；常规测试环境使用现有配套工具。未安装依赖、修改全局环境或锁文件。需要 Node 的命令在测试 PowerShell 进程内临时调整并恢复 PATH：

```powershell
$phaseCSavedPath = $env:PATH
try {
    $env:PATH = 'C:\ProgramSoftware\nodejs;' + $phaseCSavedPath
    .venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite acceptance
    $phaseCExit = $LASTEXITCODE
}
finally { $env:PATH = $phaseCSavedPath }
exit $phaseCExit
```

此处 exit 用于测试子进程；交互终端可检查 `$phaseCExit` 后继续，不必退出终端。以下表中命令若使用 Node，均采用上述临时 PATH 包装。每次独立 UUID 目录保留首次失败，不用成功复跑覆盖原证据。

| 检查 | 实际结果 | `.run/coding-agent-validation/` 证据目录 |
| --- | --- | --- |
| model-evaluation 首批 | 44 passed | model-evaluation-d0ded593c42641a58e98b5e95c5ae392 |
| model-evaluation 扩展首次 | 48 passed、1 failed；命名管道权限限制 | model-evaluation-0b65d6eceabc401d9d7c0aa46980e760 |
| streaming | 33 passed | streaming-20b719640d284248939120418fb6ec49 |
| legacy 首次 | 104 passed、4 failed；3 项命名管道权限限制，1 项旧 Request 替身缺 headers | legacy-1467d823823740abb98061bd80b0029c |
| legacy 修正/环境复验 | 108 passed | legacy-1b2126fa55a34baaba9eefb6fdc8ab30 |
| model-evaluation 常规权限首次 | 48 passed、1 failed；任务成功，但工具重复结束事实使 tool_seconds 为 null | model-evaluation-ed1db1347b4b429c97e9e37db5ec51c5 |
| external | 113 passed | external-d97bcf670c7e47f79048255a6b13c58e |
| custody | 27 passed | custody-67d83480b4e7444eb5efa4a4952445ea |
| model-evaluation 指标修正复验 | 49 passed | model-evaluation-9704e71542c543e2807a46b8ab60eb0f |
| acceptance（加入旧本机入口及审批计时用例） | 331 passed，532.47 秒 | acceptance-978fc41a73334912979cf8a83f49ac6c |
| model-evaluation 严格身份/配置复验 | 56 passed，87.52 秒；另补连接模式身份校验及非法配置类型边界 | model-evaluation-5c8237b2ab2840ea8826beb41c285c61 |
| all 完整隔离回归 | 687 passed、1 skipped，676.29 秒；20 个本轮 Python 文件在回归期间无摘要变化 | all-d714ee22abfd4208bec965d0a62c0f46 |
| streaming 最后协议防御修正后 | 33 passed，8.20 秒 | streaming-0039616da1304741943b92cc5a176e86 |
| model-evaluation 协议防御复验 | 58 passed，60.37 秒；包含非字符串错误码与布尔序号的协议拒绝 | model-evaluation-0e04de3413d7496390fce047c63d09fc |
| control 首次完整校准 | 退出 1：前 9 题系统行为通过，PY09 暂停造成模拟 token unknown，后 21 题被误阻断 | control-37358a5cdf384d62acc65b077cc794c0（位于 `.run/coding-acceptance/`） |
| model-evaluation 最终代码 | 59 passed，59.07 秒；fixture 模拟用量与真实预算边界完整复验 | model-evaluation-90d7d58d0c04458d98a1686517112173 |
| control 修正后 | 退出 0，30/30 系统行为通过；账本完整，token unknown 保留，M3 blocked | control-8a287e519d4b465ca2768f0d95b7af6e（位于 `.run/coding-acceptance/`） |
| matrix 最终代码 | 退出 0，15/15 通过；service/OpenAI/Ollama 各 5 次，M3 blocked | matrix-ab4d25b26f284cfcbd353452fb178746（位于 `.run/coding-acceptance/`） |
| preflight 默认工具环境 | 退出 1，missing=[npm]，runner_exception=null；未启动任务 | preflight-66ea238d2c444c9b8d07c864be10c2a1（位于 `.run/coding-acceptance/`） |
| preflight 常规测试环境 | 退出 0；现有配套 Node/npm 被正确选择；未启动任务 | preflight-03c774b504d04b6181c20bb77acb4a1f（位于 `.run/coding-acceptance/`） |

命令分别为 `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite <表内套件>`；legacy 使用 `.venv/Scripts/python.exe -B scripts/run_coding_legacy_validation.py`。仅指定该次真实运行的名称，不把历史 A/B 成绩写成本轮成绩。

原校准入口及 CLI 检查的实际命令：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode control
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode matrix --tasks PY01,PY09,PY10,VT07,RS01
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode preflight
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --help
```

`--help` 退出 0，并展示 preflight/control/matrix/quality/probe、model-config 和 authorize-model-calls；没有运行 quality 或 90 次实验。control 与 matrix 的最终账本另用 `coding_acceptance_evidence.verify_ledger` 只读核验，均通过；尝试数分别为 30/15，全部系统行为通过，integrity=true、real_model_called=false、delivery_decision=blocked。

56 项直接复验内的产品路径**替身**证据：`model-evaluation-5c8237b2ab2840ea8826beb41c285c61/tmp/600ad35cb06043d39f49a22a31031c40/probe-842af7131afc4ed38039af119e0cf79a/`。实际经过 IPC/Agent/AppContainer，PY01 终态 completed、事件完整、系统行为通过、权限 confirm、隔离验证通过；测试账号和模型响应均为合成数据。5 次模型请求、4 次工具、600 个模拟 token、费用 null；模型区间 0.062 秒、工具扣除审批后 2.031 秒、审批 0.047 秒、有效运行 2.422 秒、总耗时 21.828 秒。采样 23 次，实际最大间隔 1.032 秒，所属 Job 峰值 8 个进程、目录采样峰值 3828881 字节，缺失原因列表为空；账本校验通过，M3 决议仍为 blocked。以上值只证明采集和结算路径，不能代表真实模型性能。

静态校验实际命令：

```powershell
.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check
.venv/Scripts/python.exe -B scripts/check_agent_v2_imports.py
.venv/Scripts/python.exe -B -m ruff check scripts/run_coding_acceptance.py scripts/coding_acceptance_budget.py scripts/coding_acceptance_metrics.py scripts/coding_acceptance_models.py scripts/coding_acceptance_evidence.py scripts/coding_acceptance_schema.py scripts/coding_acceptance_transport.py scripts/coding_validation_process.py scripts/run_coding_validation.py src/private_agent_core/context.py src/private_agent_core/contracts.py src/private_agent_local/app.py src/private_agent_local/cloud.py src/private_agent_local/local_models.py src/private_agent_local/core_adapter.py src/private_agent_local/context_manager.py src/private_agent_local/runtime.py src/personal_assistant/api/routes_desktop_model.py tests/coding_acceptance/test_s6_models.py tests/unit/test_desktop_model.py
git diff --check
```

观察结果分别为 `protocol codegen in sync: OK`、`agent_v2 dependency rules: OK`、`All checks passed!` 和无输出、退出 0。没有改动生成协议、前端、Rust 宿主或锁文件；未执行桌面构建和与本轮无关的 600 秒长命令专项。

完整回归覆盖最终的共享预算契约、运行时和恢复逻辑。它结束后，补入流帧错误码字符串/序号整数校验及两项测试，再依据 control 的直接失败修正 fixture 模拟用量门禁并新增一项回归。后续改变由最新 model-evaluation、streaming 及 control/matrix 命令核验，未重复运行完整 all。唯一跳过项为 `tests/unit/test_local_file_ranges.py::test_actual_symlink_rejected`，原因为当前 Windows 未授予创建真实符号链接权限；没有新增 skip、扩大超时或将该项写成通过。

### 失败定位

Windows 默认工具沙箱内的最小诊断命令：

```powershell
.venv/Scripts/python.exe -B -c "import asyncio.windows_utils as w; import _winapi; a,b=w.pipe(duplex=True,overlapped=(False,True)); _winapi.CloseHandle(a); _winapi.CloseHandle(b); print('named_pipe_ok')"
```

受限环境退出 1：`asyncio/windows_utils.py:63` 的 `_winapi.CreateFile` 报 `PermissionError [WinError 5]`；同一命令经工具审批在常规执行权限下退出 0，输出 `named_pipe_ok`。产品 AppContainer、network_policy=none 和测试数据库/网络守卫没有关闭。此对照定位本轮命名管道失败的环境边界，**不能证明已修复 B 历史 preflight-805a4… 那次缺栈的 PermissionError**。

最后的默认环境预检失败有明确 `missing=[npm]`，并非 PermissionError。对照中 `C:/ProgramSoftware/nodejs/node.exe` 和 `npm.cmd` 均存在且 `os.access(..., os.X_OK)=true`，但默认工具环境的 `shutil.which` 仍选择 Codex Node、npm=None；PowerShell 首选 PATH 前缀没有保持为 Python 子进程的首选前缀。常规测试环境中同样的临时 PATH 设置选择 `C:/ProgramSoftware/nodejs/node.EXE` 和 `npm.CMD`，预检通过。本轮仅定位两种执行环境的工具发现差异，未修改工具层或宣称全局修复。

阶段 C 的产品替身贯通测试最初将两种工具完成事件当作一对，直接得到缺失指标失败。新增唯一 invocation 结束事件后复验，而不是过滤真实失败或将 null 改为零。开发中 Ruff 报导入顺序、未用导入和漏导入 SimpleNamespace，均仅在本轮改动文件中修正。没有扩大超时、降低终态断言或跳过有效测试。

首次完整 control 暴露本轮新增整场门禁误用于 fixture 模拟 token 的回归，原目录、PY09 的 completed 终态与 tokens=null、后续 21 条 `total_tokens_unknown` 均保留。修正仅区分确定性模拟用量与真实模型用量，不删除失败、不重写原账本、不放宽真实调用预算。新尝试使用新目录，不以复跑成功宣称首次实验本来有效。

## 项目记忆与未验证边界

项目记忆 `docs/project-state.md` 保留 2026-08-31 的 E 盘旧快照；当前已按 F 盘 Git 与源码核对。它不表示本轮 HEAD、运行时能力或部署状态，报告已明确日期与环境差异。依仓库特定约定不自动改写该文件；本轮持久的接口、预算兼容策略与指标定义同步到本文和测试入口说明，未新建记忆体系。两份既有 B 文档的开工内容保留。

最终复核共 22 个本轮文件（20 个 Python 文件及 2 个 Markdown 文件），没有新增依赖或锁文件改动。已检查完整差异、未跟踪文件、暂存区和源码摘要；暂存区无变化，原两份 B 文档与 project-state 的 SHA256 均等于开工值。最终 control/matrix 期间的源码无漂移。基线/前后摘要存于 `.run/s6-phase-c-20260914/`；该目录只作本机审计定位，不纳入交付源码。

没有运行真实供应商、真实测试账号登录、桌面安装/UI、生产数据库、付费模型或 D 的 90 次实验。实际服务器需要支持评测请求计数协议；没有这项能力时预检拒绝精确请求预算评测，普通旧协议产品兼容仍保留。工具峰值仅限当前 Windows 所属 Job，后台进程寿命与工具调用耗时语义分开，采样仍可能漏掉短进程。

## 下一步真实联调

最少需要用户确定：测试服务 HTTPS 源站、目标 profile/model（版本可未知）、实际上下文容量及推理/输出参数；专用测试账号会话的使用授权；单次和整场请求、工具、有效时长、token 预算，以及可获得的费用上限/费用缺失处置。只提供这些非敏感配置和授权，凭据在本机交互终端隐藏输入，不能粘贴进聊天、命令行或报告。

获得上述输入后，将无凭据模型配置保存为 `.run/s6-phase-c-model.json`，先运行只读预检，再在明确调用授权内运行一次公开开发题：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode preflight --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer --tasks PY01 --model-config .run/s6-phase-c-model.json
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode probe --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer --tasks PY01 --repetitions 1 --model-config .run/s6-phase-c-model.json --authorize-model-calls
```

若预检指出接口/能力缺口，本轮不代为更新远端；需要另行授权及验证部署。上述真实命令本轮**未执行**。随后按目标模型的真实行为补充普通/工具/流式、无流式兼容、拒绝/取消和预算用例回执；故障注入只能使用专用测试环境，不能将故意昂贵调用作为预算测试。C 退出仍需独立核对真实调用和指标，且不会自动触发 D～F。

## 2026-09-15：直连适配与复验

工作区 `F:\Program\Agent`，HEAD `1dde393e29f3dbacd3647d11834b39824ac8323f`，分支 `dev/1.0.0`。范围仅 C-01～C-05；保留开工全部未提交改动和上述旧代理记录。当前账号服务器只处理身份认证，模型调用链为正式测试会话 → 本机私有 stdio IPC → 本机 Agent → 供应商。

### 本轮结论

| 判断 | 状态 |
| --- | --- |
| 直连适配开发与隔离测试 | **已完成**。C-01～C-05 直连实现、最终 model-evaluation 128 passed、完整隔离回归 812 passed/1 项原有环境跳过；control 30/30、matrix 15/15。各阶段源码摘要及适用范围见下表 |
| 实际产品路径的真实模型联调 | **待执行**；没有真实供应商调用或生产凭据读取授权，本轮只使用合成账号、合成密钥、MockTransport 与回环服务 |
| 阶段 C 完整退出 | **未满足**；不能用隔离替身、元数据预检或公开题成绩替代目标模型真实正负用例，M3 保持 blocked |

### 上下文、基线与历史证据

完整阅读根 `AGENTS.md`、`docs/project-state.md`、`direct-model-execution.md`、后续计划、阶段 A 报告、阶段 B 三份指定材料和阶段 C 旧报告；仓库中没有下级 `AGENTS.md`。检查 Git 状态、最近五个提交、暂存区和工作区差异。开工源码、差异和保护摘要保存在 `.run/s6-phase-c-direct-bf02cff684cb4efa8bdad1d576aef8f9/`；这是忽略目录中的本机审计材料，不保证跨机器存在。

记忆仍为 2026-08-31 的 E 盘/旧 HEAD/服务器推理快照。当前 F 盘源码 `model_service → ConfiguredModels` 以及服务器拒绝旧模型入口的实现，证明调用链已变化。本轮按用户要求保留 `docs/project-state.md` 原文；持久契约同步到本报告、直连说明、评测 README 和后续计划的 C 部分。

历史 direct-models 的 53、streaming 的 33 和旧 C 的 59 都不能直接继承。开工实际 direct-models 重新得到 53 passed；同一开工状态的旧 model-evaluation 为 54 passed、5 failed，原因是正式独立 Agent 没有模型配置。测试范围由 `run_coding_validation.SUITES` 核对；本轮后续源码及测试发生变化，必须以本轮表中的对应复验为准。

### C-01～C-05 实现及兼容策略

| 工作项 | 本轮实现 | 验证与剩余边界 |
| --- | --- | --- |
| C-01 | 新增严格 schema 2 `direct_provider`。运行器用正式会话、IPC、项目/会话/Agent API 执行；不在脚本里完成题目。旧 schema 1 `product_proxy` 在登录前拒绝并说明迁移，历史解析与证据账本仍兼容。六字段 `local_unbilled` 保留，且仍要求显式不计费和字面回环地址 | 两种本机协议、直连正式 IPC 和 AppContainer 贯通；fixture 的 service 标签保留历史计划身份，实际 wire 改为本机 OpenAI，并在事件中记录真实协议；没有恢复服务器推理 |
| C-02 | OpenAI 兼容、Claude、Ollama 普通/流式/工具往返；按 profile 在请求前选流式或普通响应。Claude/Ollama 的非空 reasoning_effort 目前请求前拒绝。已发送请求不因错误、断流或供应商选择重放；受控传输拒绝同一模型尝试的第二次发送 | 三协议工具往返和 401/403/404 正反例；保留旧 Cloud 纯协议测试解释旧 complete/stream 协商。它们不再声称当前产品使用代理；真实目标模型的能力仍待实测 |
| C-03 | 冻结 profile/model、协议、非敏感端点、版本或未知原因、实际上下文、所有 ModelParameters、输出/推理/压缩设置、能力、实际权限和产品/题集摘要。新增产品 `/model-evaluation/bind`：认证后只读一个选定 profile 的客户端元数据，产品进程读取其单个系统凭据引用；不枚举、不导出凭据 | 合成凭据验证账号/端点/命名空间绑定、前置不匹配拒绝、只读源库、重复交接拒绝、变更后停止、无凭据落盘；Windows 原生读取以合成 ABI 替身验证，不声称访问过真实系统凭据 |
| C-04 | 保留单次与整场预算的最小额度分配、响应后结算及下一请求前检查。失败、取消消耗已经尝试的模型次数；供应商发送次数在受控传输边界计 0/1，重试 0。缺失部分 usage 不再补造已测量零；缺价格、失败或中断用量仍 unknown | 真实 Agent 替身验证 token、请求、未知费用、失败与取消；预算模块验证五个维度的总额、边界和重复结算。评测禁用额外模型能力探测；预检产生零推理。token/费用仍是软预算，不能承诺账单硬上限 |
| C-05 | 模型调用和传输计量共用 attempt_id/call_id；失败/取消也保留计量事件。拒绝重复/错绑传输记录。缺活动时长明确报告 missing。模型、工具、审批区间仍用单时钟并集，工具扣除审批；分类耗时不能相加当总耗时 | 测试时间重叠、缺时钟、跨时钟、倒序、重复起点、缺结束/计数和错绑关联；Job/存储采样只含当前 attempt 所属资源，记录周期、实际间隔及缺失原因；短进程和采样间峰值可能漏采 |

直连生成参数包含 `llm_temperature`、`llm_context_length`、`kb_enabled_by_default`（Coding 路径目前不使用 KB，仍冻结该设置）、`reasoning_effort`、`max_output_tokens`、`auto_compact`。Ollama 的实际窗口为配置窗口与模型容量的较小值。已声明的模型输出容量另记录 `declared_max_output_tokens`，预检拒绝超过它的请求限额。供应商未暴露的默认参数及不可变版本保持未知。

这里的实际上下文指产品运行预算和请求采用的窗口；模型元数据中的容量声明不等于已实测供应商容量。共享 TokenUsage 的默认值和生成协议保持兼容，直连出口用实际报告字段集合保留 unknown；供应商用量必须为非负 JSON 整数，字符串、布尔值等无效计量不再被隐式转为数值。

错误分类：账号 401/403 为 `cloud_auth_required`；供应商 401/403 为 `model_unauthorized`，404 为 `model_model_not_found`；能力不足为 `model_unsupported_capability`；超时为 `model_timeout`；断流/未结束流为 `model_stream_interrupted`；错误 JSON 为 `model_invalid_response`；已解析但结构不符为 `model_protocol_error`；取消仍保留合法 `cancelled` 终态。冻结源配置变化为 `evaluation_configuration_changed`，缺模型密钥为 `model_missing_api_key`。响应正文和秘密不进入错误消息。

保留预算 schema 1/2 与 `s6-attempt-ledger-1`、`s6-process-1` 格式。schema 1 题集仍按原字段和摘要解释，没有改写公开清单、参考答案或独立回执。新模型配置 schema 2 不默认为 schema 1；旧格式不会静默转为直连。`real_model_called` 是配置入口曾尝试模型调用的历史字段，不能鉴定真实供应商：隔离测试对 direct_provider 使用替身时也可能为 true，必须结合本表测试来源判断，不能以该布尔值作为真实联调回执。

关联层级为评测行的 `attempt_id`（同时作为创建运行的 `client_request_id`）→ 行内 `run_id` → 事件中的模型 `attempt_id`/传输 `call_id`。IPC 帧 `request_id` 只标识一次本机 RPC，不能当作模型请求数。模型/工具/审批耗时来自同一 Runtime 的单调时钟；评测行总耗时使用评测进程自己的时钟，供应商或认证服务器的墙钟不参与相减。

已核对 `context_manager.py` 和 `context_history.py`：当前 Coding 压缩在本机生成历史事实索引，记录压缩尝试/完成事件，不隐式调用模型。预检及每轮身份校验也不是供应商推理；评测 Agent 额外的模型列表和能力探测入口保持关闭。

### 配置交接及凭据边界

独立评测 Agent 只在 `--evaluation --stdio` 启动时接受交接。请求经现有本机边界、正式 Bearer 会话和身份认证；账号目录摘要由产品自己计算。源路径只允许本机绝对目录并拒绝链接/重解析点；仅以 SQLite `mode=ro` 读取 `<目录>/<账号摘要>/model-settings.sqlite3`。结构、启用状态、模型/供应商映射及预期配置先核对，再查询该引用的系统凭据。不会借测试创建迁移、删除原库或改变用户设置。

读取契约已与现有 `apps/desktop/src-tauri/src/credentials.rs` 及锁定的 keyring 4 Windows 后端源码核对：`model-provider.<alias>.api-key.com.personal-assistant.desktop[.candidate]`，UTF-16LE 密码数据；正常和候选命名空间明确分开，不回退查找。原始系统缓冲在释放前清零；Python 字符串不具有可证明的安全清零能力，所以仅保留所属 Agent 内存引用，退出后清除。非 Windows 环境明确拒绝这一交接方式。

生产执行的评测脚本不取得供应商密钥；它只取得操作者在本机交互终端隐藏输入的专用测试账号会话。交接返回元数据与 configured/ready 状态。每个独立 Agent 只读取指定模型；已绑定后配置写入与工具能力探测入口拒绝，运行前再次核对源/目标快照。密钥版本没有可安全公开的不可变标识，不对运行间的人工密钥轮换作已验证承诺。

本轮测试使用 MockTransport、合成凭据读取函数、合成 Windows ABI 缓冲，以及产品现有 `PA_MODEL_PROVIDER_SECRETS_JSON` 启动注入通道。测试进程显式设置 `PA_EVALUATION_SYNTHETIC_ONLY=1`，禁止访问实际 Credential Manager；变量不是用户配置，也不允许测试通过它加载现有凭据。没有创建、读取、枚举或删除实际系统凭据。

### 实际命令与结果

已有 Python 为 `.venv/Scripts/python.exe`（3.12.13）；Node/npm 当前可直接发现，分别为 `C:/ProgramSoftware/nodejs/node.exe`（24.14.0）与 `npm.cmd`（11.9.0）。已运行 `Get-Command python,node,npm`、各自 `--version` 和 Python `shutil.which` 核对。本轮无需修改 PATH；没有安装依赖、修改全局环境或锁文件。

所有套件用原隔离入口和 900 秒上限，新建 UUID 目录、禁用业务配置/conftest/自动插件加载。真实宿主在常规执行权限下复验；模型网络只有回环/HTTP 替身，工具 AppContainer 与 `network_policy=none` 不变。

以下隔离目录均位于 `.run/coding-agent-validation/`；套件退出码、测试文件集合及失败/跳过节点保存在各自 `invocation.json`、`pytest-result.json`。通过数取实际 pytest 结果；未为通过用例补造逐项运行记录。失败和中断运行另见下一节，不以最终成功覆盖它们。

| 实际命令 | 本轮结果 | 证据目录 |
| --- | --- | --- |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite direct-models` | 开工 53 passed，5.89 秒；usage 修改后复验 53 passed，4.82 秒，均退出 0 | `direct-models-2a4b537abbbd40b39aea6a2ee9d84497`；`direct-models-815d9c85227044d5a451386aec2b3c61` |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite streaming` | 33 passed，8.36 秒，退出 0 | `streaming-558a796056374a51912c21d99229c59b` |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite model-evaluation` | 阶段性 99 passed，67.40 秒；扩展协议后 124 passed，78.09 秒，均退出 0；最终结果续列 | `model-evaluation-3e3724b160e947809efe2543a2110d88`；`model-evaluation-0f50bac9ae6341ae82f36bcc1c3c0b03` |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all` | 计量 I/O 用量补充前：810 passed、1 skipped，655.30 秒，退出 0 | `all-ab106dfbc34148d69c114c77a1326b95` |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite acceptance` | 计量 I/O 用量补充前的独立复验：405 passed，443.38 秒，退出 0 | `acceptance-f1754800bdc543228af9285f0683dcd8` |
| `.venv/Scripts/python.exe -B scripts/run_coding_legacy_validation.py` | 等价协议入口复验 108 passed，7.50 秒，退出 0 | `legacy-81121767a234481c96ff7a6f232b1f56` |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite external` | 113 passed，55.36 秒，退出 0 | `external-93bda6a93ba840558a4248677a6d3ea4` |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite custody` | 27 passed，43.49 秒，退出 0 | `custody-2a9df3d7f156424bb4cccfd586d1fe09` |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite model-evaluation` | 计量 I/O 用量补充前：126 passed，95.62 秒，退出 0；包含计量持久化失败后的资源清理 | `model-evaluation-f903500e2b304d478021313a872c1b83` |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite model-evaluation` | 最终源码：128 passed，96.92 秒，退出 0；包括开始事件和响应计量写入失败的处理 | `model-evaluation-9bce7f9c777a4c9fb9ba2da8f7ee9f7f` |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all` | 最终源码，单独运行：812 passed、1 skipped，773.50 秒，退出 0 | `all-bb5f6ca4ee674160b77c8180e5fa2e36` |

`all` 使用仓库原有集合，按原规则不包含单列的 duration/execution-duration 专用长时套件。唯一 skipped 为 `tests/unit/test_local_file_ranges.py::test_actual_symlink_rejected`：当前 Windows 没有创建真实符号链接权限，原测试未修改，没有新增跳过或放宽超时。首次完整回归和 acceptance 期间，冻结的 175 个相关 Python 源码及测试文件均无摘要变化。旧协议导入调整由 legacy 独立复验覆盖；之后计量 I/O 用量补充仅改 `core_adapter.py` 与相应测试，并重新冻结源码、复跑完整 all，不能直接继承补充前的成绩。

最终源码使用 175 个相关 Python 文件的 SHA-256 冻结，产品来源摘要为 `d149d4d21f40e6054c65ead277bd3b2d31269d335046ad11410c5cc458499898`（59 个产品文件）。control/matrix 对应修正请求开始事件 I/O 异常之前的产品摘要 `70ad616a1160704c6aae7a3831a303a1fb16add345c81899faffddb47c854f1d`；首次完整回归对应更早的摘要 `a89877ffbc8e891f3ea398d65c174311021a9014175bbf74e1c4f062506cfe57`，不能混为同一源码成绩。摘要、增量差异及复核结果分别保存在本轮审计目录的 `regression-source-final.json`、`product-identity-final.json`、`incremental.diff` 和 `current-changes.json`；校准版本另存 `regression-source-calibration.json`、`product-identity-calibration.json`。

已在最终源码运行以下静态与审计命令，均退出 0：

```powershell
.venv/Scripts/python.exe -B -m ruff check scripts/run_coding_acceptance.py scripts/coding_acceptance_models.py scripts/coding_acceptance_transport.py scripts/coding_acceptance_metrics.py scripts/coding_acceptance_evidence.py scripts/coding_acceptance_isolation.py scripts/run_coding_validation.py src/private_agent_core/llm/adapters.py src/private_agent_local/app.py src/private_agent_local/connections.py src/private_agent_local/core_adapter.py src/private_agent_local/direct_models.py src/private_agent_local/entry.py src/private_agent_local/local_models.py src/private_agent_local/model_credentials.py src/private_agent_local/model_evaluation.py src/private_agent_local/model_transport.py tests/coding_acceptance/test_s6_acceptance.py tests/coding_acceptance/test_s6_delivery.py tests/coding_acceptance/test_s6_direct_evaluation.py tests/coding_acceptance/test_s6_external.py tests/coding_acceptance/test_s6_models.py tests/unit/test_model_evaluation.py tests/unit/test_model_gateway.py
.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check
.venv/Scripts/python.exe -B scripts/check_agent_v2_imports.py
.venv/Scripts/python.exe -B .run/s6-phase-c-direct-bf02cff684cb4efa8bdad1d576aef8f9/audit_review.py
git diff --check
```

观察结果依次为 `All checks passed!`、`protocol codegen in sync: OK`、`agent_v2 dependency rules: OK`、28 个本轮增量文件/24 个 Python 文件且保护摘要和暂存区不变、无空白错误。没有本轮桌面改动，因此未运行桌面类型检查或构建。审计辅助文件及运行产物全部位于既有忽略目录 `.run`，未加入交付文件。

专项复验仍通过原隔离函数执行，实际命令如下，结果及保留的失败见下一节：

```powershell
.venv/Scripts/python.exe -B -c "import sys; sys.path.insert(0, 'scripts'); import run_coding_validation as validation; validation.SUITES['phase-c-terminal'] = ['tests/coding_acceptance/test_s6_delivery.py']; raise SystemExit(validation.run('phase-c-terminal'))"
.venv/Scripts/python.exe -B -c "import sys; sys.stdout.reconfigure(encoding='utf-8'); sys.path.insert(0, 'scripts'); import run_coding_validation as validation; validation.SUITES['phase-c-errors'] = ['tests/unit/test_model_evaluation.py']; raise SystemExit(validation.run('phase-c-errors'))"
```

### control/matrix 校准与证据复核

实际命令如下，两条校准均退出 0：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode control --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer --repetitions 1
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode matrix --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer --tasks PY01,PY09,PY10,VT07,RS01 --repetitions 1
.venv/Scripts/python.exe -B .run/s6-phase-c-direct-bf02cff684cb4efa8bdad1d576aef8f9/check_calibration.py .run/coding-acceptance/control-4d4e9c2063194714aea9cc1b6f2f64bc .run/coding-acceptance/matrix-697baa08ab6541efbe308fcbb9c7764f
```

| 证据目录（`.run/coding-acceptance/`） | 观察结果 | 指标与采样 |
| --- | --- | --- |
| `control-4d4e9c2063194714aea9cc1b6f2f64bc` | 30/30 系统行为通过，30 条过程/资源指标完整；账本链及全部产物摘要通过 | 尝试耗时合计 1567.393 秒，所属 Job 采样峰值 12 个进程，单次目录采样峰值 6644130 字节；2 条模拟用量 unknown，30 条费用 unknown |
| `matrix-697baa08ab6541efbe308fcbb9c7764f` | service/OpenAI/Ollama 历史标签各 5/5，通过 15/15；15 条过程/资源指标完整；账本与产物摘要通过 | 尝试耗时合计 789.466 秒，所属 Job 采样峰值 11 个进程，单次目录采样峰值 6134031 字节；3 条模拟用量 unknown，15 条费用 unknown |

两组的实际权限均为 confirm，AppContainer 预检 verified，`network_policy=none`。分别核对 65、24 条已报告的命令会话状态，均为 restricted/none。采样周期均为 1 秒，实际最大间隔约 1.032 秒，缺失原因列表为空；短进程和间隔内峰值仍可能漏采。表中时间是各尝试 `elapsed_seconds` 的和，不能当作整个 CLI 的墙钟时长，也不把模型、工具和审批分类相加推导总耗时。

选择外部公开 JSON 是现有 AppContainer 入口要求。用当前 `coding_acceptance_catalog.load_catalog` 核对，其 30 个任务的 ID、scenario、coding_goal 与原 builtin control 一致，清单摘要为 `533c6bc8973e22a4b4da2d9bb10176c8c800a6ba8223f6239a6b6d713fc201a3`。fixture 的 service 标签实际使用本机 OpenAI wire；此 matrix 不声称测试了 Claude，Claude 由三协议直接用例覆盖。

两组 `integrity_passed/schedule_complete=true`、`runner_errors=[]`、`real_model_called=false`，编码分母和独立完成计数均为 0，`experiment_complete=false`、`delivery_decision=blocked`。公开暂停场景中的模拟用量仍为 unknown，不将其换算为免费真实调用。已核对各行 evidence_sha256、启动日志与追加式记录链；汇总和文件摘要保存在本轮审计目录 `calibration-observations.json`。

校准期间未修改产品源码。结束后仅将 `_complete_attempt` 的关联 ID/异常处理函数定义移到请求事件写入之前，修正原始 I/O 异常被覆盖的问题，并补充一个用例；成功路径的模型、工具、权限、预算和终态逻辑未变。该最终增量由 48 项错误边界专项、最终 model-evaluation 和完整 all 复验，不把校准前的摘要标成最终源码。

### 最终源码的产品直连替身贯通

最终 128 项 model-evaluation 中，`test_product_probe_uses_agent_ipc_isolation_and_bound_evidence` 的证据位于 `.run/coding-agent-validation/model-evaluation-9bce7f9c777a4c9fb9ba2da8f7ee9f7f/tmp/5aacfbee308445f08bea3a03a4c50409/probe-7962bd0bd32049e08d8bef4fbc0f1350/`。产品摘要为上述最终 `d149d4…`；schema 2、direct_provider，正式测试会话 → IPC → Agent → 受控回环替身。元数据预检 `passed=true/inference_performed=false`；实际 PY01 为 completed/verified，权限 confirm、隔离 verified，系统行为通过。

该次 4 次模型请求、4 次供应商发送、0 次传输重试、3 次工具、480 个合成 token，费用 null。模型耗时约 0.048 秒，工具扣除审批后约 2.281 秒，审批约 0.079 秒，有效运行 2.608 秒，尝试总耗时 16.938 秒；没有把这些分类相加。1 秒周期共采样 18 次，最大实际间隔约 1.032 秒，所属 Job 峰值 8 个进程、目录采样峰值 3219073 字节，无指标缺失原因。上述值只证明采集与结算路径，不代表真实模型速度或价格。

已执行只读证据核验，退出 0，启动与尝试摘要链、逐项产物 SHA-256 均通过：

```powershell
.venv/Scripts/python.exe -B .run/s6-phase-b-remaining-5c4f64b2ba234de7b64a67d1db361f78/check_evidence.py .run/coding-agent-validation/model-evaluation-9bce7f9c777a4c9fb9ba2da8f7ee9f7f/tmp/5aacfbee308445f08bea3a03a4c50409/probe-7962bd0bd32049e08d8bef4fbc0f1350
```

这个 direct_provider 用例明确由测试替身响应，不能把其 `real_model_called` 入口标志解释成真实供应商联调成功。质量门禁仍为 blocked，独立完成计数仍为 0。

最终完整 `all` 已完成：812 passed、1 项原有符号链接权限跳过，773.50 秒，退出 0。核对 `invocation.json` 中的测试文件集合，确实覆盖当前 direct-models、model-evaluation、streaming、acceptance、external、custody 全部文件；`pytest-result.json` 的 `business_modules_loaded=[]`。最终回归开始后 175 个相关源码/测试摘要未变，没有把较早 acceptance 的 405 项当成最终版本独立执行的成绩。

独立复验在原有 900 秒内完成；前一次与校准并行的超时仍保留为失败记录。没有专门定位系统级耗时变化，也不能据此宣称已修复历史超时或阶段 B 的 PermissionError。各轮已完成结果、缺失结果标记及原始文件 SHA-256 汇总于审计目录 `validation-observations.json`。

### 失败保留与归因

- 开工旧模型评测的五项失败：独立 Agent 未取得任何模型配置，预检返回 `model_not_configured`。对应目录 `model-evaluation-b903cd9cc5fe482c970e127b287b3b69` 保留；未恢复服务器模型执行来满足旧断言。
- 首轮新实现：96 passed、3 failed。两个旧本机探针因持续执行宿主不可用未启动任务，AppContainer 探针因宿主启动失败阻断；目录 `model-evaluation-cd4013c156544108beb98dc8fa0b7605` 保留。最小 `asyncio.windows_utils.pipe` 在工具受限权限报 `PermissionError [WinError 5]`，常规权限对照输出 `named_pipe_ok`。后者只证明本轮对照可运行，不宣称修复 B 历史缺栈 PermissionError，也不把目录遍历、命名管道及 AppContainer 故障混为一谈。
- 三协议扩展首次：122 passed、2 failed，两个 Ollama 工具往返夹具沿用 8192 窗口，实际工具定义触发 `context_limit`。该组协议夹具改为其声明的 32000 窗口，再验证实际请求的上下文和工具往返；保留原有上下文上限用例，未扩大产品预算或超时。原目录 `model-evaluation-3d55cbb638444a51bb302f8c3133629a` 保留。
- 首轮 acceptance：399 passed、5 failed，497.28 秒。fixture 的 service → OpenAI 转换把注入用量写成固定 100/20，取消竞争中的高用量条件失效；其中待审批场景在合成项目内发生了本不应批准的写入。修正夹具保留输入、输出及缓存用量，原终态、审批、无副作用和 30 秒断言全部保留。失败目录 `acceptance-cec928419bf0428bbfe0e8b2c1870944` 与受影响项目保留；修正后直接专项 25 passed，26.80 秒，目录 `phase-c-terminal-f689ebba9e1540aa82df8434c7d99d22`。
- 自查发现新增 transport 事件的持久化异常可能跳过流式发布任务清理，主动中断尚未完成的 `all-edf3cde7f2f14fde8cb700b9ab2fd684`，该次不计为通过。合成 `OSError` 测试实际复现残留 `publish_batches` 任务：45 passed、1 failed，12.25 秒，目录 `phase-c-errors-e4bdfba28aa74150945f19f1ff9f2f94`。将上下文恢复及任务回收放在计量写入之前后，同组 46 passed，11.97 秒，目录 `phase-c-errors-579007d73ca744c4be8a52a3e7da297a`；异常仍向上报告，不重放供应商请求。
- 对同一路径补充“首请求失败”和“已有成功请求后失败”用量检查，实际发现预算仍可能显示 0 或旧的完整用量：45 passed、2 failed，16.05 秒，目录 `phase-c-errors-ec14a6c5a1a946b68e610a5903c98c79`。增加 I/O/SQLite 异常的 unknown 标记后 47 passed，15.14 秒，目录 `phase-c-errors-1e69085eaecc413885d9c0a8ec91cafb`；异常继续传播。修改产品源码前主动中断 `control-831d3b33cb05451a9366fc4a5622052b`，已产生记录保留，该次不是完整校准通过；最终校准使用新的实验目录和源码摘要。
- 旧协议纯单测首次：99 passed、9 failed，9.21 秒，目录 `legacy-0cfaf4263600494dbbd64e3eef2210ac`。源码证实旧测试仍经新增角色限制的完整后端包装器调用，得到 `ServerModelDisabled`；这是先前直连架构迁移后未适配的测试入口。仅将 `tests/unit/test_model_gateway.py` 的三种适配器导入改为当前共享核心，保留请求、工具、usage、断流及重试等全部原断言；复验 108 passed，7.50 秒，目录 `legacy-81121767a234481c96ff7a6f232b1f56`。没有改变服务器角色、路由或推理权限。旧路由的纯 ASGI/fake Gateway 检查仍只解释历史组件协议；账号服务器前置拒绝由 direct-models 中独立的角色及边界测试验证。
- 开发期 Ruff 发现导入顺序与三个未使用导入；仅在本轮文件内调整，后续静态复验通过。
- 计量 I/O 用量修正后、开始事件异常修正前的完整回归与 AppContainer control 并行执行，在原有 900 秒上限处超时；目录 `all-77661a4fac9d413689d277a49192c491` 的 `invocation.json` 记录退出 124。终端已输出至 88% 后的后续测试点，未观察到断言失败，但没有完整结果，不能记为通过。保留目录并在校准结束后单独复验；并行竞争是待验证的耗时因素，不据此断言产品没有性能问题，也不扩大超时。
- 请求开始事件写入异常的新增用例为 47 passed、1 failed，16.81 秒，目录 `phase-c-errors-fef9c06cc8a84d429f0eb00be30f8d67`。实际捕获到 `UnboundLocalError` 覆盖原始 `OSError`，且供应商请求数为 0。校准完成后前移关联 ID 和异常处理函数定义，同组 48 passed，14.59 秒，目录 `phase-c-errors-eccba079959d40d3b0ae7d8d60248f8a`；验证原始异常继续传播、运行失败且无残留发布任务。

### 本轮增量文件

以下按开工摘要比较，区别于工作区此前已经存在的大量未提交改动。没有修改桌面代码、服务器模型入口、依赖或锁文件。

| 文件 | 增量职责 |
| --- | --- |
| `scripts/run_coding_acceptance.py` | direct_provider 执行入口、旧代理迁移拒绝及本机 profile 路由 |
| `scripts/coding_acceptance_models.py` | schema 2、产品交接请求、能力与实际参数预检 |
| `scripts/coding_acceptance_transport.py` | 独立 Agent 启动与身份交接、测试凭据守卫、旧 service 夹具转换 |
| `scripts/coding_acceptance_metrics.py` | 请求关联与计数完整性、缺活动时长原因 |
| `scripts/coding_acceptance_evidence.py` | 显式记录 direct_provider 的历史调用入口字段 |
| `scripts/coding_acceptance_isolation.py` | 合成隔离探针选用实际本机 profile |
| `scripts/run_coding_validation.py` | 纳入新增直连评测测试 |
| `src/private_agent_core/llm/adapters.py` | 三协议保留实际报告的 usage 字段，拒绝无效计量值 |
| `src/private_agent_local/app.py` | 受限评测交接 API 与配置冻结 |
| `src/private_agent_local/entry.py` | 仅 stdio 使用的 evaluation 启动标志 |
| `src/private_agent_local/model_evaluation.py`（新增） | 只读选定元数据、核对和冻结配置、委托产品读取单个凭据 |
| `src/private_agent_local/model_credentials.py`（新增） | 与现有桌面格式一致的单个 Windows 凭据读取及隔离测试拒绝 |
| `src/private_agent_local/direct_models.py` | 实际配置描述、能力拒绝、usage unknown 与错误分类 |
| `src/private_agent_local/model_transport.py` | 实际发送计量、关联 ID、禁止重放与断流分类 |
| `src/private_agent_local/core_adapter.py` | 成功/失败/取消计量及异常时的发布任务释放 |
| `src/private_agent_local/local_models.py` | 旧本机入口描述、请求前流式选择、未知用量与断流 |
| `src/private_agent_local/connections.py` | 本机启动配置的流式能力开关，默认行为兼容 |
| `tests/coding_acceptance/test_s6_direct_evaluation.py`（新增） | schema、真实 IPC 交接、预检、授权及计量边界 |
| `tests/unit/test_model_evaluation.py`（新增） | 合成凭据、三协议工具往返、失败、预算、取消及资源清理 |
| `tests/coding_acceptance/test_s6_models.py` | 新直连贯通及历史代理纯协议验证 |
| `tests/coding_acceptance/test_s6_acceptance.py` | 新本机 profile 与普通/流式 wire 断言 |
| `tests/coding_acceptance/test_s6_delivery.py` | 本机 profile、断流后禁止副作用重放的等价断言 |
| `tests/coding_acceptance/test_s6_external.py` | 合成 Agent 隔离探针的实际 profile |
| `tests/unit/test_model_gateway.py` | 将历史协议原断言应用到直连共用适配器，保留服务器包装器拒绝行为 |
| `tests/coding_acceptance/README.md` | 评测入口、夹具兼容及凭据边界 |
| `docs/direct-model-execution.md` | 独立评测 Agent 的持久产品契约 |
| `docs/analysis/coding-agent-upgrade-20260908/s6-follow-up-development-plan.md` | 只修订阶段 C 调用链，完整退出条件不变 |
| `docs/analysis/coding-agent-upgrade-20260908/s6-phase-c-validation-report.md` | 追加本轮记录、命令、证据、限制和后续步骤 |

### 交付复核、项目记忆与剩余边界

按开工逐文件摘要及增量差异复核，本轮为上述 28 个文件；保留原有桌面、服务器、B 阶段等未提交改动，暂存区仍为空，仓库 HEAD/分支不变。`docs/project-state.md` 的字节摘要与开工相同；读取的独立记忆源就是该文件。其旧盘符、日期与服务器推理描述按当前源码核实为历史快照差异，本轮没有重写该快照，也没有新建记忆体系。直连调用链、schema 2 兼容策略、产品交接、预算及指标知识已同步到本报告、直连说明、评测 README 和后续计划 C 部分。

本轮没有真实账号登录、真实供应商请求、原生凭据库实读、已安装客户端/UI 验收、发布或部署。Windows 凭据格式仅与现有桌面及锁定后端源码核对，并用合成 ABI 验证；需要下一轮在授权测试配置下预检。真实模型容量、版本、协议能力、价格及实际表现尚待确认；缺价格/usage 不能补零，token/费用仍为响应后结算的软预算。资源采样可能遗漏短进程与间隔内峰值，真实符号链接分支受当前 Windows 权限限制。

独立保留题与回执缺失不阻断本轮 C 本地开发，但正式质量门禁没有放宽。真实目标模型正负用例未执行，因此 **C 完整退出条件仍未满足、M3 仍 blocked**。本轮未进入 D～F，也未运行 D 的 90 次真实实验。

### 下一步真实联调所需最少信息

仅提供以下非敏感信息：专用测试账号的 HTTPS 认证源站；已安装客户端属于 desktop 还是 candidate 命名空间及其 `local-projects` 目录；选定 profile ID、模型名、供应商 ID/协议/端点；实际上下文和设置参数；单次/整场请求、工具、活动时长、token 及可获得费用预算。模型没有不可变版本时明确选择 null；公开开发题首轮只选 PY01、一次。后续真实模型调用必须另有明确授权，不能沿用本轮隔离授权。

客户端配置步骤：

1. 使用专用测试账号登录对应客户端；在“模型设置”中添加测试供应商和模型，核对协议与端点。
2. 在客户端保存该测试供应商的密钥，选择对应模型、上下文、温度和流式声明。密钥留在系统凭据库；无需导出索引、数据库凭据或环境文件。修改端点时重新在客户端保存对应密钥。
3. 记录上述非敏感 ID/目录/设置并填写下方 schema 2 文件。不要把生产凭据、供应商密钥或账号会话放进 JSON、命令行或聊天；运行预检时在本机交互终端隐藏输入受授权的专用测试会话。

模板保存为 `.run/s6-phase-c-direct-model.json`，占位值必须按实际测试配置替换；示例地址不可用，数字不构成调用授权：

```json
{
  "schema_version": 2,
  "connection_mode": "direct_provider",
  "endpoint": "https://test-account.example.invalid",
  "profile_id": "replace-with-local-profile-id",
  "model": "replace-with-model-name",
  "model_version": null,
  "context_tokens": 32768,
  "provider": {"id": "replace-with-provider-id", "protocol": "openai", "endpoint": "https://test-provider.example.invalid/v1"},
  "model_settings_directory": "C:/Users/Example/AppData/Local/com.personal-assistant.desktop.candidate/local-projects",
  "credential_namespace": "candidate",
  "parameters": {
    "llm_temperature": 0.7, "llm_context_length": 32768, "kb_enabled_by_default": false,
    "reasoning_effort": null, "max_output_tokens": 2048, "auto_compact": true
  },
  "budget": {
    "max_model_requests": 8, "max_tool_calls": 12, "max_active_seconds": 60,
    "max_attempt_tokens": 10000, "max_total_tokens": 10000,
    "max_total_model_requests": 8, "max_total_tool_calls": 12, "max_total_active_seconds": 60,
    "cost_usd": null, "total_cost_usd": null
  }
}
```

适配完成后的实际 CLI（真实配置命令本轮未执行）：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode preflight --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer --tasks PY01 --model-config .run/s6-phase-c-direct-model.json
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode probe --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer --tasks PY01 --repetitions 1 --model-config .run/s6-phase-c-direct-model.json --authorize-model-calls
```

第一条只检查会话、冻结配置和实际隔离，不发模型推理；第二条仅在另行授权后运行。命令启动的源码 Agent 必须包含本轮交接实现；旧 bundle 不支持 `--evaluation` 或缺少直连能力时启动/预检失败，不静默回退，也不把旧安装副本说成已通过。缺 usage/价格时不能宣称消耗为零，设有对应上限时后续请求按 unknown 阻断。正式独立题集及回执门禁不变，不运行 D 的 90 次实验，也不自动进入 D～F。
