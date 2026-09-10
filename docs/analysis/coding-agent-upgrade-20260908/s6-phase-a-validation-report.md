# 阶段 A：评测终态、取消与证据修复记录

日期：2026-09-09（Asia/Shanghai）。工作区：`F:\Program\Agent`，分支 `dev/1.0.0`，HEAD `25ba4d3`。本轮仅实施 [后续计划](./s6-follow-up-development-plan.md) A-01～A-05；B～F、M3 放行及发布不在本轮范围。

结论：**阶段 A 满足本轮退出条件，完成后停止。** 最终 S6 专项 128 passed，完整隔离回归 477 passed、1 项既有权限跳过，旧服务端兼容 106 passed，公开校准 30/30、回环矩阵 15/15。具体失败过程、环境与证据边界如下。

## 实施与证据边界

开工时完整读取根 `AGENTS.md`、`docs/project-state.md`、总体路线和阶段 A，核对 Git 状态、已有差异、源码与测试；仓库检索未发现下级 `AGENTS.md`。开工已有 23 个 S6 改动文件，均保留。只修改三个评测脚本、两份 S6 测试及对应阶段文档，未修改产品运行时、协议生成物、依赖或锁文件。

项目记忆是 2026-08-31、`E:\Program\Agent`、旧 HEAD 的历史快照；当前 Git 与源码确认本机运行时已有六种终态。按照本轮明确要求，`docs/project-state.md` 保持原内容，不建立新的记忆体系。本报告和评测协议记录本轮事实，不将历史源码、安装、生产验收状态混同。

开工基线的文件摘要和相关原文件保存在 `.run/s6-phase-a-c71245b86aaa4cb193795d7bb2466d81/`，仅用于本机差异审查。该目录和全部测试证据均被 Git 忽略，不保证跨机器存在。

| 工作项 | 实际修改 |
| --- | --- |
| A-01 | `TERMINAL_EVENTS` 覆盖六种终态，轮询复用；通过纯 AST 与共享核心枚举的一致性测试防止漂移，不启动业务服务。 |
| A-02 | 最新快照先判终态；独立记录运行时状态、错误码、评测停止原因；区分预算、活动时长、运行失败、用户取消和评测超时。 |
| A-03 | 取消仅请求一次；回执与最终状态分别记录，各有 5 秒上限；丢失或失败回执后只读核对；未知终态不执行外置判定。审批 ID 不重复提交。 |
| A-04 | 保留连续序号与唯一终态检查，增加状态/事件匹配、终态后事件、分页停滞拒绝及明确原因。 |
| A-05 | 使用受控响应门闩、实际状态同步点和直接测试的虚拟时钟，分别验证取消先结束、上下文上限先结束、运行超时先结束、评测超时、外部取消、回执丢失、取消决策后运行时先结束及待审批取消。 |

六种终态均通过直接检查；正式 IPC 活动时长耗尽的实际契约为 `limit_exceeded` / `max_active_seconds`，分类为 `runtime_timeout`，没有把它伪造成 `timed_out`。`timed_out` / `wall_time` 单独通过契约、轮询与事件测试。

## 变更文件

下表仅列本轮在开工基线上修改或新增的文件；开工前已有的其他 S6 改动保持原样。

| 文件 | 本轮内容 |
| --- | --- |
| [run_coding_acceptance.py](../../../scripts/run_coding_acceptance.py) | 修改轮询、一次取消、结束归因、审批防重、事件分页及未知终态处理。 |
| [coding_acceptance_evidence.py](../../../scripts/coding_acceptance_evidence.py) | 统一终态映射，增加明确的事件完整性失败原因，保留布尔校验入口。 |
| [coding_acceptance_transport.py](../../../scripts/coding_acceptance_transport.py) | 有界处理超时请求迟到帧；提供仅用于回环夹具的响应同步门闩。 |
| [test_s6_acceptance.py](../../../tests/coding_acceptance/test_s6_acceptance.py) | 增加终态契约、事件异常、轮询与取消、迟到帧和期限边界测试。 |
| [test_s6_delivery.py](../../../tests/coding_acceptance/test_s6_delivery.py) | 将原不稳定 Token 用例拆成独立、确定性的正式 IPC 场景，严格检查文件及审批。 |
| [s6-acceptance-protocol.md](./s6-acceptance-protocol.md) | 记录六种终态、取消上限、新增证据字段、分类及未知结果边界。 |
| [s6-follow-up-development-plan.md](./s6-follow-up-development-plan.md) | 保留编制时失败证据，补充 A 的退出核对和停止边界。 |
| [README.md](./README.md) | 增加阶段 A 验证入口，区分历史失败与本轮结果。 |
| [本报告](./s6-phase-a-validation-report.md) | 新增阶段 A 实施、测试、差异与未验证范围记录。 |

## 复现与修复过程

- 修复前直接测试为 **3 failed、4 passed**：两种遗漏终态和运行时集合一致性失败。旧评测源码中的事件终态集合也缺少两项。没有重复覆盖已有修复。
- 最初 7 个正式 IPC 用例在默认工具沙箱均未通过执行宿主预检，记录为 `runner_error`，实验未启动。经正常审批后相同隔离链路可运行，判定为该执行环境的宿主可用性限制；未关闭产品沙箱或跳过测试。
- 常规权限首次复验已得到正确终态，但新增测试误从运行快照读取 `approvals`，7 项因 `KeyError` 失败；改为查询真实审批 API 并检查对应事件后，7 项通过。
- 新增待审批用例初次缺少写入前真实读取，未满足既有版本绑定要求，1 项失败；补齐夹具的真实读取步骤后，精确验证待审批取消、零消费、零文件写入，1 项通过。未放宽终态断言。
- 首轮完整回归通过后，最终审查补充两个边界：取消回执明确未接受时保留外部取消来源；状态查询耗尽评测剩余期限时记录评测超时。补充直接断言并重新执行受影响专项与完整回归，不扩大期限。
- 历史约 632.5 秒的误分类及 900 秒总超时记录仍按原 [后续计划](./s6-follow-up-development-plan.md) 定位保留，本轮追加独立证据，不覆盖旧记录。

## 验证命令与结果

所有命令在仓库根执行，使用已有 Python 3.12.13 环境。直接测试启动器复用 `isolated_environment`、`managed_process`、`coding_validation_plugin`，每次新建测试目录，禁用仓库 conftest 与自动插件加载；执行宿主用例经正常审批在常规权限下复验。无业务配置、生产数据库或真实模型凭据输入，仅回环替身。

```powershell
.venv/Scripts/python.exe -B .run/s6-phase-a-c71245b86aaa4cb193795d7bb2466d81/direct.py "all_runtime_terminals or local_runtime_terminal_contract"
.venv/Scripts/python.exe -B .run/s6-phase-a-c71245b86aaa4cb193795d7bb2466d81/direct.py
.venv/Scripts/python.exe -B .run/s6-phase-a-c71245b86aaa4cb193795d7bb2466d81/direct.py "token_budget or ipc_runtime or ipc_evaluator or ipc_user"
.venv/Scripts/python.exe -B .run/s6-phase-a-c71245b86aaa4cb193795d7bb2466d81/direct.py "ipc_budget_cancel"
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite acceptance
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all
.venv/Scripts/python.exe -B scripts/run_coding_legacy_validation.py
.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check
.venv/Scripts/python.exe -B scripts/check_agent_v2_imports.py
.venv/Scripts/python.exe -B -m ruff check scripts/run_coding_acceptance.py scripts/coding_acceptance_evidence.py scripts/coding_acceptance_transport.py tests/coding_acceptance/test_s6_acceptance.py tests/coding_acceptance/test_s6_delivery.py
git diff --check
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode preflight
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode control
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode matrix --tasks PY01,PY09,PY10,VT07,RS01
.venv/Scripts/python.exe -B .run/s6-phase-a-c71245b86aaa4cb193795d7bb2466d81/final_review.py
```

直接启动器是本机忽略目录中的复现辅助，完整 acceptance/all 为仓库持久入口；`deselected` 表示直接检查的显式筛选，不是从完整套件跳过用例。

| 检查 | 结果 | 证据目录（位于 `.run/coding-agent-validation/`） |
| --- | --- | --- |
| 修复前直接复现 | 3 failed、4 passed，0.62 秒 | `a-direct-24b25e30b39541ca87122274bc519240` |
| 第一批直接测试 | 45 passed，0.58 秒 | `a-direct-73ad094d0c3d4d05a48db41211d14b2b` |
| 第二批直接测试 | 46 passed，0.61 秒 | `a-direct-8219f60bff92490aa9c823a7054cf929` |
| 最终直接测试 | 48 passed，0.61 秒 | `a-direct-ad2140671a474b05a39b5fc64a1a43b7` |
| 默认沙箱 IPC | 7 failed，宿主预检不可用，12.70 秒 | `a-direct-a75656955e024edcb3fe4df81ae99bb2` |
| 常规权限 IPC 首次 | 7 failed，测试误读审批字段，18.59 秒 | `a-direct-009c154367414ecbb17c1410b751f4dd` |
| IPC 修正复验 | 7 passed，17.86 秒 | `a-direct-604409417512426f8499fd15e7c2d406` |
| 待审批用例初次 | 1 failed，夹具未先读取文件，18.00 秒 | `a-direct-3e45bff436434d04913402198c16c743` |
| 待审批用例复验 | 1 passed，3.23 秒 | `a-direct-96ef822812084398a815a678702f1b77` |
| 首轮 S6 acceptance | 126 passed，65.89 秒 | `acceptance-681eb84cb9c54f0f8f99e91c9a5c656a` |
| 首轮完整隔离回归 | 475 passed、1 skipped，308.26 秒 | `all-0fc76679939a4a28b9d9eeda570f9a12` |
| 最终 S6 acceptance | 128 passed，58.44 秒 | `acceptance-0557ef94abf943eaa062580cac07f8c2` |
| 最终完整隔离回归 | 477 passed、1 skipped，325.94 秒 | `all-a0d376e1e07e4f03bd37052958bf9a22` |
| 旧服务端兼容纯单测 | 106 passed，6.35 秒 | `legacy-83ab37358612447fb0133c400f78d518` |

`protocol_codegen.py --check` 输出 `protocol codegen in sync: OK`，`check_agent_v2_imports.py` 输出 `agent_v2 dependency rules: OK`，五个实际改动 Python 文件的 Ruff 输出 `All checks passed!`，`git diff --check` 无错误，均退出 0。`preflight` 退出 0，证据位于 `.run/coding-acceptance/preflight-aeeb0df3d0c346358462b1d73b61b81a`。

主隔离套件通过导入守卫禁止业务配置/数据库模块。旧服务端兼容入口按既有设计允许加载 `personal_assistant.config`、`personal_assistant.core.db`，使用独立无环境文件目录、固定不可用测试数据库地址和网络审计守卫；加载模块不表示读取生产配置或连接数据库。

唯一既有跳过为 `tests/unit/test_local_file_ranges.py:71`：当前 Windows 环境未授予创建真实符号链接权限。保留原测试及跳过条件，不计作通过，不扩大到新平台支持结论。

30 题公开校准退出 0，**30/30 系统行为通过**，每次尝试耗时合计 149.86 秒；证据位于 `.run/coding-acceptance/control-420bbf956d8c42739819f694a908720d`。逐项证据摘要匹配，完整性通过，`real_model_called=false`，交付决议仍为 `blocked`，编码质量分母为 0。

最终完整回归中，8 个正式 IPC 终态场景均通过；单次 **2.141～3.125 秒**，上下文上限先结束的场景为 **2.156 秒**，不再等待约 632.5 秒。所有场景的事件完整、范围保护通过、评测批准次数为 0；待审批场景中的一项审批明确取消，未消费。直接测试另覆盖不可确认的取消结果、状态查询期限和迟到 IPC 分块，不将这些模拟传输结果冒充真实故障网络验收。

指定 `PY01,PY09,PY10,VT07,RS01` 的 service / OpenAI / Ollama 回环矩阵退出 0，**15/15 系统行为通过**，每次尝试耗时合计 66.921 秒。证据位于 `.run/coding-acceptance/matrix-251908fa2179465db3de198154422b47`；所有引用摘要匹配，完整性通过，`real_model_called=false`、编码质量分母为 0、交付决议仍为 `blocked`。

## 退出条件与后续边界

阶段 A 的退出条件已满足：全部合法终态及时收束，结束原因保留，取消请求不重复，缺失/重复终态及非法后续事件仍被拒绝，直接测试、S6 专项和完整隔离回归没有未解释失败。逐项检查本轮差异与开工基线，保留其他会话改动；`docs/project-state.md` 摘要未变。未新增依赖、协议生成物、提交、推送或部署。

最终审查辅助 `final_review.py` 核对八个修改文件、一个新增报告、其余开工文件摘要、文档本地引用、最终测试计数、隔离守卫及两组校准的引用/运行器摘要，并执行 `git diff --check`。本轮增量差异与审查结果分别保存在开工证据目录的 `phase-a.diff`、`final-review.json`；它们是忽略目录中的本机审查材料。

本轮没有真实模型质量、原生桌面流程、干净安装、旧安装升级/回退或生产验收，不将公开校准成绩作为质量或 M3 放行依据。600 秒持续命令专项未因本次纯评测脚本修复而重复执行，产品运行时与 Rust 宿主未改动。

范围外后续事项沿用 B～F：独立题集、正式模型入口与指标、真实质量与桌面流程、安装/升级/回退、最终门禁与发布材料。既有符号链接权限缺证据留待对应权限验收补充。本轮不实施这些事项，无需用户执行额外操作。
