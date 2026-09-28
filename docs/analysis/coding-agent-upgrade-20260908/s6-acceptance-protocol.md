# S6 评测协议：公开校准、证据与交付决议

> 阶段 B 补充（2026-09-10）：严格外部 JSON、验收材料分离、候选输出独立比较、实际权限探针及追加式尝试账本见 [阶段 B 契约](./s6-phase-b-contract.md)。下文保留原公开校准入口和阶段 A 行为；外部入口使用 --catalog，仍不能将本轮公开样例或同身份执行声明为正式盲评。

版本：`s6-calibration-1`。日期：2026-09-09。实现：[运行器](../../../scripts/run_coding_acceptance.py)、[任务定义](../../../tests/coding_acceptance/s6_fixtures.py)、[外置判定器](../../../scripts/coding_acceptance_catalog.py)、[证据汇总](../../../scripts/coding_acceptance_evidence.py)。本协议不构成生产操作、付费调用或发布授权。

## 1. 冻结任务与指标

保留 S0 `tasks.json` 的 Python/Node/混合项目 24/6 基线，不修改其成绩。S6 新增原创、可分发的 CC0-1.0 小型合成项目：Python 包及服务响应、Vue/TypeScript 模型及真实组件、无第三方依赖的 Rust crate。

| 主分类 | Python | Vue/TypeScript | Rust |
| --- | ---: | ---: | ---: |
| 缺陷修复 | 2 | 2 | 1 |
| 跨文件需求 | 2 | 2 | 1 |
| 行为约束重构 | 2 | 1 | 2 |
| 长文件与上下文 | 1 | 2 | 2 |
| 执行失败或暂停接续 | 2 | 1 | 2 |
| 用户工作与授权边界 | 1 | 2 | 2 |

每类项目 10 题，编号 `PY01–PY10`、`VT01–VT10`、`RS01–RS10`。各自前 6 题是开发集，后 4 题是保留组，即 18/12。清单冻结提示、初始代码、允许文件、分类、场景、参考实现、隐藏输入和预定验证命令；每次记录清单源码 SHA-256 与任务原始树摘要。机器专属的 Vue 编译器路径、Rust 链接器/SDK 配置和初始 Cargo.lock 在启动前物化，其实际文件摘要另存为 before 清单。修改任务内容后必须更改版本并重建基线，不能混用旧实验。

三个 `*10` 是预先定义的不可完成编码目标：审批拒绝后不写文件。每模型 30 题 × 3 次为 90 次，其中 **27 × 3 = 81** 次是编码质量分母，9 次只评估系统边界。已启动后的超时、工具失败、模型失败、人工帮助与预算耗尽不排除；预检失败列为未启动。`control` / `matrix` 的编码质量分母为 0，结果用于验证工具机制。

独立完成须同时满足功能断言、预定验证、范围保护、真实终态 verified、连续证据、模型身份、预算、零解题人工介入，以及人工核对的说明真实性和实现约束。审批及题目预定义的暂停不算解题帮助。重构题初始功能可以通过；优化/结构约束要独立审阅，不能只凭功能测试或参考字符串判定。

**这是一套公开校准集。** 参考实现与断言在本仓库可读，保留组已暴露；`blind_quality_eligible=false`。虽然不会复制隐藏断言到模型项目，当前用户权限仍不形成保密盲评隔离。正式 M3 需增加未参与调试的独立题、记录污染及隔离验收来源。不能把这些小型项目成绩承诺为复杂商业项目成功率。

## 2. 启动与隔离

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode preflight
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode control
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode matrix --tasks PY01,PY09,PY10
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite acceptance
```

`--tasks` 只选择冻结 ID；`--repetitions` 为 1–3；默认预检，默认每题一次。`--work-dir` 指定测试父目录，程序始终新建 `<mode>-<uuid>`，不复用或删除原目录。路径包含空格、中文时按 shell 规则加引号。无 `--bundle` 时启动当前源码的正式 `private_agent_local.entry --stdio`，并使用现有 release exec-host；指定候选目录时校验源清单及宿主 SHA-256，再将三个运行文件复制到独立目录。

运行器使用正式账号绑定、项目/会话、运行、审批、执行续读、恢复和事件 API。账号服务始终是随机回环端口上的独立替身；令牌只在内存中使用。模型工具经过产品原有策略与完成验证，不直接写模型答案到 UI 或绕过执行器。确定性模型发出可复现的读取、写入/补丁及命令调用，不计作真实模型。

进程继承系统变量白名单，不继承模型密钥、代理、业务 `PA_*` 或 Python 注入选项；运行时使用独立 data-dir 与 Windows 用户目录层级。依赖检查不联网安装：Python/pytest/httpx/FastAPI/uvicorn、Node/npm、仓库已有 Vue/TypeScript/SSR 包、Rust 工具链；Windows Rust 还核对 MSVC 与 SDK 安装元数据。开发工具不算随客户端提供的能力。

命令只有 `python -m pytest`、`npm test`、`cargo test --offline`，按任务匹配。固定脚本属于预先审查的**可信项目执行**，使用产品原有显式审批；当前版本不声称能安全运行恶意候选代码。普通文件只批准题目列出的路径，`*10` 拒绝写入。dirty 正向夹具在新 Git 仓库对用户文件使用 intent-to-add，不产生提交，也不触碰工作仓库 Git 状态。

单次资源目录上限 256 MiB / 20000 文件，工作区源码上限 8 MiB / 1000 文件，IPC 单帧 2 MiB、单响应 8 MiB，证据 JSON 单文件 8 MiB，stderr 1 MiB。外置断言最多 30 秒、输出 64000 字节；超限回收所属进程树。记录采样存储峰值，进程峰值未测则保留 null。以上是有界校准工具约束，不是对恶意代码的磁盘或网络 OS 配额。

采样允许编译器正常删除中间文件。Windows 在隔离用户目录自动建立的 `INetCache/Content.IE5` junction 仅在目标严格等于同目录 `IE` 时跳过重复遍历，真实 `IE` 文件仍计量；其他链接及权限错误仍失败。超时或 token 超额通过已有无请求体的取消入口停止，不进行带新授权的重试。

### 阶段 A 的终态与取消规则（2026-09-09）

合法终态为 `completed`、`failed`、`cancelled`、`timed_out`、`limit_exceeded`、`interrupted`，分别对应 `run.<status>`。评测轮询与证据模块共用映射，并由测试核对本机运行时及共享核心契约；脚本不为读取状态常量而导入业务服务。

每次读取最新状态后先判断终态，再判断 token 预算和评测期限，最后才处理审批或暂停/继续。普通轮询间隔保持 50 ms，单次 IPC 等待不超过原有 30 秒，单题评测期限仍为 630 秒，隔离套件仍为 900 秒。达到停止条件时仅发送一次取消请求：回执等待最多 5 秒，随后另用最多 5 秒只读观察终态。未知回执不重发取消，已超时请求的迟到帧按原 ID 消纳；不接受无关 ID，也不重放审批或工具。

`attempts.jsonl` 的 `run_status` / `run_error_code` 保留运行时事实，新增 `termination` 单独记录 `stop_reason`、`cancel_requested`、`cancel_response`（`not_requested` / `accepted` / `not_accepted` / `unknown`）、`cancel_error`、`observation_error`、`terminal_observed` 和 `observed_before_deadline`。取消回执不证明已取消；最终状态未知时保留最后快照、判证据不完整，不在活动工作区启动外置判定命令。运行器退出仍执行原有进程清理，清理动作不被当成已观察到的终态。

| 已观察事实 | `failure_class` |
| --- | --- |
| `limit_exceeded`，如 `context_limit`；或 token 预算耗尽 | `budget_exhausted` |
| `timed_out`；或本机 `limit_exceeded` + `max_active_seconds` | `runtime_timeout` |
| 评测期限触发取消并收束为 `cancelled` | `attempt_timeout` |
| 未由评测器提出取消，或取消回执明确未接受，而最终为 `cancelled` | `user_cancelled` |
| `interrupted` | `runtime_interrupted` |
| 运行时模型或执行失败，具体原因保留在 `run_error_code` | `runtime_failed` |
| 状态查询超时且未核实终态 | 仍在评测期限内为 `evaluator_transport_timeout`；耗尽评测剩余期限为 `attempt_timeout`；已触发预算/期限时保留原 `stop_reason` |

自然终态优先于竞争中的评测停止意图，例如期限已到但实际为上下文上限时仍记录 `budget_exhausted`；不会把终态改成 `cancelled`。主结束原因与证据错误分别保留，后续证据采集失败不能覆盖已确认的结束原因。

回执丢失时，`cancel_response=unknown` 与已观察到的 `run_status=cancelled` 可以同时成立；这证明运行已取消，不能单凭它证明取消来源。评测停止意图仍单独保留。状态读取失败时不凭过期快照补发取消，终态继续标为未确认。

事件必须从 1 连续到快照的 `last_event_sequence`，恰有一个与快照匹配的合法终态，且为原运行最后一个事件。关联恢复写入新运行；原运行终态后再出现模型、工具或控制事件均拒绝。`event_integrity_errors` 明确区分空事件、非法末序号、序号缺口/重复、缺失/重复终态、终态不匹配及终态后事件；分页游标不前进或重复立即失败。

## 3. Provider 与真实模型

`matrix` 分别运行 service 代理流、OpenAI 兼容流和 Ollama 流的回环替身。原生进程测试另覆盖旧代理在推理前选择 complete、流中断不重试以及重开后旧审批失效。矩阵证明适配器和工具协议链，不能代替具体供应商/模型质量、远程鉴权及费用验收。

真实本机模型可用单独、不含秘密的配置，例如：

```json
{
  "model": "your-installed-local-model",
  "protocol": "ollama",
  "endpoint": "http://127.0.0.1:11434",
  "context_tokens": 32768,
  "local_unbilled": true,
  "max_total_tokens": 10800000
}
```

这是配置格式示例，不代表模型已安装或该服务不收费。确认运行的是不计费的本机服务后，使用：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode quality --model-config <本机配置文件> --repetitions 3
```

入口拒绝远程主机、localhost 别名、凭据、查询参数及未知字段。只允许明确的 `127.0.0.1` 或 `::1` 回环地址；不读取真实账号 token。需要付费远程供应商的验收仍通过另行确定的实际客户端/账号流程，不在此工具内提取凭据。

每题最多 24 个模型请求、48 个工具调用、600 秒活动时间；另有 630 秒运行器等待期限、60 秒验证命令期限、120000 token 检查。开始下一题前预留一整题 token 额度，用量未知时停止后续真实调用。运行时在响应返回后才知道实测 token，最多可能在一个响应内跨过阈值；超限不会计为预算内完成，**这些限制不是供应商账单硬上限**。费用未知保留 null；不把本机“不计费声明”写成已计量的零成本。温度等未由现有入口暴露的模型参数不能伪称已固定，具体模型版本不可得时注明未知。

本轮没有执行 quality。控制模式的假 usage 仅用于协议校验。

## 4. 证据与审阅

| 文件 | 内容 |
| --- | --- |
| `manifest.json` | 版本、任务 revision、启动计划、模型/预算、工具及运行器摘要、实际产物身份 |
| `attempts.jsonl` | 全部尝试的启动与终态、分类、费用未知性、人工介入、审批、资源采样及证据摘要 |
| `events/*.json` | 正式 API 有序事件；连续性及唯一终态核对 |
| `artifacts/*.json`、`*.diff` | 运行快照、执行结果、审查、隐藏断言、验证输入版本、前后摘要和 diff |
| `metrics.json` | 按模型/语言/类别/开发与保留组分组，保留失败、未启动、缺失和门禁未执行理由 |
| `report.md` | 可读结果及继续验收决议 |

引用文件都有摘要；验证期间候选修改自身也判为失败。评测服务正常/异常结束均保存尝试，最初就写入未完成报告，因此中途强制终止不会留下空白的成功报告。无法创建输出目录或解析启动参数时返回 CLI 错误，实验未开始。证据留在被忽略的独立目录，不自动复制到版本库。

机器不能可靠判断任意最终说明及重构约束。审阅者应核对 evidence 后制作以下 JSON（摘要使用实际值）：

```json
{
  "manifest_sha256": "<manifest 摘要>",
  "attempts_sha256": "<逐次记录摘要>",
  "reviewer_role": "独立验收人员",
  "reviewed_at": "2026-09-09T20:00:00+08:00",
  "attempts": [{
    "attempt_id": "ollama-PY01-1",
    "evidence_sha256": {"events/ollama-PY01-1.json": "<摘要>", "artifacts/ollama-PY01-1.json": "<摘要>", "artifacts/ollama-PY01-1.diff": "<摘要>"},
    "report_matches_facts": true,
    "human_interventions": 0,
    "constraints_satisfied": true,
    "note": "逐项说明核对依据，不能默认填通过。"
  }]
}
```

```powershell
.venv/Scripts/python.exe -B scripts/coding_acceptance_review.py --evidence <实验目录> --reviews <审阅文件>
```

审阅只追加新的 `review-<uuid>`，不覆盖原始记录、实验分母或失败分类。输入/证据改动、重复尝试、路径越界或减少已记录人工次数均拒绝。审阅是一份人工声明，不构成签名身份认证，也不能把未跑的正式盲评、UI、安装或回退门禁标为通过。

## 5. 交付决议

运行器退出 0 仅表示所选预检/控制场景成功；`metrics.delivery_decision` 继续为 blocked，并列出 S6-T01–T12 的未完整验收理由及部分证据。S6-T09 目标仍是每个默认候选模型独立完成率至少 80%，保护性门禁不能用该比例抵消。

后续由验收角色补充真实模型及独立保留题、实际桌面流程、支持 OS 的干净安装、旧安装包升级/回退、性能及权限矩阵。测试角色核对复现材料，运行时角色处理归因到 S1–S5 的失败，再重跑受影响范围。没有指定实际人员或日期；不自动安排发布、自动化或新任务。
