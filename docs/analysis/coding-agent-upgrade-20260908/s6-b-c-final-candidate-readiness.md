# B、C 与最终候选验收准备记录

> 当前范围修订（2026-09-15，用户后续确认）：本项目仅用于个人学习，本次取消独立验收方、正式保留题和独立回执要求，改用现有测试集。B 的独立材料不再阻止 C 配置和联调准备。范围及客户端检查见 [第 6 节](#6-个人学习范围调整与客户端核对)；最新 C 已通过，候选已冻结，宿主及原生取证状态见 [第 10 节](#10-c-个人联调通过与候选冻结)。下文第 1～5 节保留同日此前以正式验收为目标的历史记录，第 7～9 节保留此前失败和修复，不能作为当前重复调用或重新提供独立材料的要求。

日期：2026-09-15（Asia/Shanghai）。工作区：`F:\Program\Agent`；HEAD：`1dde393e29f3dbacd3647d11834b39824ac8323f`。开工时已有大量未提交修改，本轮保留这些修改。

**此前正式验收准备结论（本日范围调整前）：** 当时完成交接准备与本机核验，B 的独立材料尚未提供，C 的实际模型配置与预算尚未确定，最终候选尚未冻结。此处保留原结论，当前个人学习验收以第 6 节为准。

本轮证据目录：`.run/s6-readiness-ced9e64e4c1341e4a8a99582bb078996/`。其中 `readiness.json` 记录检查结果，`historical-bundle-identity.json` 记录旧产物身份，`phase-c-direct-model.example.json` 是待替换占位值的配置示例。目录被 Git 忽略，不保证跨机器存在。

依据：[B 契约](s6-phase-b-contract.md)、[B 学习验收](s6-phase-b-local-learning-validation.md)、[C 直连报告](s6-phase-c-validation-report.md)、[D 准备报告](s6-phase-d-local-development-validation.md)、[本机直连说明](../../direct-model-execution.md)。

## 1. B：独立题集交接

### 本机核验结果

| 检查对象 | 实际结果 |
| --- | --- |
| 现有题集 | 30 题，development 18、holdout 12；全部 `public_calibration` |
| 清单 SHA256 | `533c6bc8973e22a4b4da2d9bb10176c8c800a6ba8223f6239a6b6d713fc201a3` |
| 判定材料 SHA256 | `49415efb5ba7f0697a939fced07b6f3451229e7effc5886d89cb849597d40fdb` |
| 历史资格验证 | `dataset-47690660f1b44c67b2baf46edf08a024` 的 30 题、120 次控制及关联产物摘要链核对通过；本轮没有重跑这些控制 |
| 历史 qualification SHA256 | `c41675b370b70143e5a7659ac029bda4b3854a1c258d8e4b626a38141853beb3` |
| 独立声明 | 历史模板的保管人和独立性说明为空；污染记录有 1 项覆盖全部公开题的事件 |
| 当前判定器 | 与历史资格验证相比，`coding_acceptance_isolation.py`、`coding_acceptance_schema.py`、`scripts/coding_validation_process.py`、`scripts/run_coding_validation.py` 的摘要发生变化 |

历史记录完整性与当前版本资格是两个结论。新正式材料必须用当前判定器重新执行 `qualify`，不能修改旧报告中的摘要后直接沿用结果。现有公开题不能通过修改 ID、来源或 exposure 标签成为独立题。

### 验收方需要交接的材料

1. 正式 `catalog.json` 及其引用的验收 JSON：30 题，三种语言各 10 题，每语言 6 个开发题、4 个保留题，原分类、重复次数和统计口径保持不变。
2. 每题来源、许可、来源产物 SHA256、初始版本、公开文件摘要、允许修改范围与判定契约。当前 `verify_custody` 对全部 30 题核对未用于 Agent 调试的声明；不能混用仓库公开题补足开发集。
3. 当前判定器生成的 `qualification.json`、`qualification-attempts.jsonl`、全部控制对应的 `verdict.json` 与权限探针证据。initial/reference/wrong/protected 共 120 次控制，必须有完整启动及结束记录。
4. `contamination.json` 及其版本记录。存在污染时保持失败状态，由验收方按原契约处理。
5. 验收方签署的 `receipt.json`：填写 `curator_id`、`independence_statement`、带时区的 `prepared_at`，绑定清单、判定材料、资格验证、污染记录及逐题摘要，并确认逐题 `not_used_for_agent_debugging`。
6. 经独立渠道交接的 `receipt.json` SHA256。不能仅由接收方对一个未知来源文件计算摘要，再把计算结果当作独立交接。

材料路径和回执摘要尚待提供。不要把隐藏题目、答案、密钥或完整控制输出粘贴到会话中。独立性、来源真实性和未污染事实由验收方负责，本轮不代签声明。

验收方执行命令（示例路径须替换，本轮未执行）：

```powershell
.venv/Scripts/python.exe -B scripts/coding_acceptance_dataset.py qualify --catalog 'F:/Evaluation/S6/catalog.json' --work-dir 'F:/Evaluation/S6/qualification-runs'
```

接收正式材料后的预检命令（替换路径及独立交接的真实摘要，本轮未执行）：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode preflight --catalog 'F:/Evaluation/S6/catalog.json' --isolation appcontainer --custody-receipt 'F:/Evaluation/S6/receipt.json' --custody-sha256 '<验收方交接的64位SHA256>'
```

## 2. C：测试配置与调用范围

本轮检查 `.run/s6-phase-c-direct-model.json` 不存在。已从 C 报告提取原 schema 2 示例并用当前 `direct_config` 验证结构；保存到本轮证据目录的 `phase-c-direct-model.example.json`。示例含 `.invalid` 地址与占位 ID，**不是实际可用配置，也不构成调用授权**。

填写实际配置需要以下非敏感信息：

| 信息 | 当前状态 |
| --- | --- |
| 专用测试账号的 HTTPS 认证源站 | 待提供 |
| 客户端 `desktop` / `candidate` 命名空间和绝对 `local-projects` 路径 | 待提供 |
| 本机 profile/provider ID、协议、规范化端点 | 待提供 |
| 模型名、可识别版本、实际上下文、温度、推理强度、输出上限、压缩参数 | 待确认；版本无法识别时保留 null |
| 单次及总请求数、工具数、活动时长、token 和费用预算 | 待确认 |
| 目标配置摘要、允许任务及次数、授权记录 | 实际配置确定后再绑定 |

原报告的首轮预算示例如下，仅供确认或调整：

| 维度 | 单次 | 整场 |
| --- | ---: | ---: |
| 模型请求 | 8 | 8 |
| 工具调用 | 12 | 12 |
| 活动时间 | 60 秒 | 60 秒 |
| token | 10,000 | 10,000 |
| 美元费用 | null，未配置费用上限 | null，未配置费用上限 |

建议首次授权范围为公开开发题 `PY01`、1 次尝试。该范围内可能有多次模型请求，受到配置的请求预算约束。它只覆盖首轮联调，后续正负场景及其他目标模型须纳入明确的总范围与预算。单题成功不等于 C 完整退出，更不等于正式质量成绩。

费用为 null 不表示免费；token 和费用是响应后结算的软预算，不能当作供应商账单硬上限。设置费用上限而缺少价格/用量时，工具按未知状态阻断后续请求。实际模型与供应商确定后，需要核对该组合的版本、能力和价格来源。

实际配置完成后的授权记录应能明确表达：批准配置文件及其 SHA256、目标供应商/模型、任务 ID 与尝试次数、单次/整场预算及停止条件。配置或目标变化后，原授权不能自动适用于新配置。本轮尚无可绑定的实际配置，因此没有添加 `--authorize-model-calls` 发起请求。

供应商凭据由用户在正式客户端保存到系统凭据库。测试会话仅在本机交互终端隐藏输入；不得存入 JSON、环境变量、CLI 参数或聊天。当前自动化命令使用非交互输入，不能代替这一步，也不能提取已有登录会话。

后续命令（实际配置完成后使用，本轮未执行）：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode preflight --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer --tasks PY01 --model-config .run/s6-phase-c-direct-model.json
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode probe --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer --tasks PY01 --repetitions 1 --model-config .run/s6-phase-c-direct-model.json --authorize-model-calls
```

第一条校验会话、配置、凭据可用性和实际隔离，不执行推理。第二条会发送真实模型请求，只有具体配置及范围获授权后才执行。所有结果保留独立 UUID 目录，失败不删除、不覆盖。

## 3. C 完成后的候选与取证

本轮只核验旧 `bundle-rechecked`，没有重建、安装或冻结最终候选。完整路径在 `readiness.json` 中。当前 414 项源码摘要与该产物清单一致，构建记录为 `dirty=true`、`portable`、`unsigned`，HEAD 为上述 `1dde393…`。

| 旧产物文件 | 本轮核对的 SHA256 |
| --- | --- |
| `PrivateAgent-windows-x64.exe` | `e7098d2017f6968e393cde62c1db306d89307e2aa18e675f6ff3890e613492df` |
| `private-agent-local.exe` | `5e61a83108412191b49497db9195ae4ed4216d6a2386aacc554f84d773230888` |
| `exec-host.exe` | `dec3cb3cf81122454552f674231a9f1da83eb8fa6c13ddde820d262efe10cf94` |

按用户要求，B/C 完整退出后才能冻结最终候选。冻结清单需关联源码、构建输入、desktop/sidecar/host、正式题集及判定器、独立回执、模型配置、Windows/架构/权限组合、构建与运行记录。任何相关输入变化后，应重新判断原证据是否仍适用。

| 取证项目 | 必需证据及验收口径 | 当前状态 |
| --- | --- | --- |
| 宿主持续执行 | 最终宿主上的真实 600 秒命令、130 秒兼容命令、持续服务和完整终态记录 | 未在最终候选验证 |
| PTY、输入与取消 | stdin、Unicode、大输出、权限正反例；可控进程树取消后 5 秒内退出，异常阻断后续冲突执行 | 未在最终候选验证 |
| 原生桌面 | 实际 Tauri 前台窗口中的登录、项目/会话、模型选择、审批、修改、测试、纠错、审查及中断恢复；记录运行路径、版本、相关 PID、图像和业务证据 | 本轮未启动原生窗口 |
| 输出延迟 | 至少 100 个可关联的宿主收到输出至前台 UI 可见样本，使用同机可比较时钟；记录机器负载、p95、最大值及超过 1 秒数量；p95 ≤ 1 秒 | 未采样 |
| 运行身份 | 区分磁盘文件摘要、启动进程信息与实际加载组件；未观测的内存身份保持 unknown | 本轮仅核对磁盘文件 |

以上阈值沿用 [S6 目标](s6-evaluation-and-delivery.md) 和 D 报告。旧 `91eb57…f7a` 宿主的长时测试不能迁移给 `dec3cb…f94`；浏览器夹具、IPC 校准、构建成功也不能替代原生窗口与性能样本。

## 4. 本轮验证

下列命令均在仓库根目录运行。前两组验证只检查已有材料和工具行为；通过不等于取得独立回执、真实模型成绩或最终候选验收。

| 实际命令 | 观察结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B .run/s6-readiness-ced9e64e4c1341e4a8a99582bb078996/check_readiness.py before` | 退出 0；公开题摘要、历史 120 次控制的账本/产物摘要、旧候选 414 项源码与二进制、示例配置结构核对完成；B/C 仍未完成 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite custody` | 退出 0，27 passed，43.18 秒；目录 `custody-26d0d10ef9694022b27d2a59a70ca275` |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite model-evaluation`（当前沙箱） | 退出 1，125 passed / 3 failed，72.19 秒；目录 `model-evaluation-89d9651bfe2848b796a00d4bad0202b6` |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite model-evaluation`（经工具审批的普通本机权限） | 退出 0，128 passed，115.64 秒；目录 `model-evaluation-ce1f5977d9e34e4698e060582111cdf5` |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite phase-d`（经工具审批的普通本机权限） | 退出 0，19 passed，7.36 秒；目录 `phase-d-a3f150b4d3aa4257bf207451e184e719`；仅候选身份与合成 IPC 测试 |
| `.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --help` | 退出 0；本文入口参数存在 |
| `.venv/Scripts/python.exe -B scripts/coding_acceptance_dataset.py qualify --help` | 退出 0；题集资格验证参数存在 |

上述测试目录均在 `.run/coding-agent-validation/` 下，各自保留 `invocation.json`、`pytest-result.json` 及子实验目录。model-evaluation 两次调用均临时使用本机已有配套 Node/npm，实际 PowerShell 包装如下；没有修改全局环境：

```powershell
$s6ReadinessSavedPath = $env:PATH
try {
    $env:PATH = 'C:/ProgramSoftware/nodejs;' + $s6ReadinessSavedPath
    .venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite model-evaluation
    $s6ReadinessExitCode = $LASTEXITCODE
}
finally {
    $env:PATH = $s6ReadinessSavedPath
}
exit $s6ReadinessExitCode
```

首次 model-evaluation 的失败为 `test_legacy_local_unbilled_config_runs_through_agent[openai]`、`[ollama]` 及 `test_product_probe_uses_agent_ipc_isolation_and_bound_evidence`。前两项记录“环境预检失败：持续执行宿主不可用，实验未启动”，第三项在 `ExecHostClient.start` 创建子进程时抛出 `ExecutorUnavailable`，三项均未启动题目。随后在相同沙箱下用正式 `ExecHostClient` 进行最小握手，复现原因链 `PermissionError / WinError 5 / errno 13`；普通 `subprocess.run` 可以启动该文件，不能因此推断异步 IPC 可用。

同一套件在经工具审批的普通本机权限下通过 128 项，期间未修改源码；结合最小握手的 WinError 5，首次 3 项失败归为当前沙箱的宿主启动权限限制。原失败保留，不修改权限门禁、测试断言或产品代码。本轮没有真实供应商调用，没有将任何公开校准成绩转为正式成绩。

文档以 UTF-8 解码成功，6 个本地链接均可解析。最终差异及用户既有修改的摘要复核见本轮证据目录的 `worktree-after.json`；最终核对命令如下：

```powershell
.venv/Scripts/python.exe -B .run/s6-readiness-ced9e64e4c1341e4a8a99582bb078996/check_readiness.py after
git diff --check
git diff --no-index --check -- NUL docs/analysis/coding-agent-upgrade-20260908/s6-b-c-final-candidate-readiness.md
git status --short --branch
git diff --stat
git diff --staged --stat
```

`git diff --no-index` 将新增文档与空文件比较，存在新增内容时退出 1；应同时检查是否输出空白错误，不能把“有新增差异”解释为测试失败。完整新增文档另行复读，未覆盖旧文档或用户源码。

## 5. 项目记忆与边界

已完整阅读指定记忆 `docs/project-state.md`，并读取本页开头列出的任务文档。记忆仍是 2026-08-31 的 E 盘历史快照；当前 Git、F 盘工作区及本机直连实现与该历史状态不同。本轮按当前代码、当前摘要和已注明日期的 C/D 报告判断，不继承旧服务器推理或部署结论。

按仓库约定，本次未获更新共享历史快照的明确要求，因此不改写 `docs/project-state.md`，不新建记忆体系。本页记录此次验收准备事实；没有修改架构、接口、模型配置、依赖或产品行为。用户原有源码改动、旧运行证据及失败记录均应保留。

继续实施仍需 B 的独立材料路径/交接摘要，以及 C 的实际非敏感配置、预算和后续明确调用范围；真实会话需要本机隐藏输入。在这些条件具备前，三项完整验收均保持未完成。

## 6. 个人学习范围调整与客户端核对

### 当前验收范围

用户明确取消本次 B 的独立验收要求，改用已有测试集。现有工具已支持无需 custody 回执的公开题流程，本轮 30 题、120 次控制、当前构建的 AppContainer 预检和 30/30 Agent 学习测试均通过，最终账本及关联产物核对通过，B 的个人学习验收完成。实测结果与命令见 [B 学习复验](s6-phase-b-local-learning-validation.md#2026-09-15-个人学习复验)。独立材料不再是本次 C 的前置条件。

### 当前电脑上的客户端

2026-09-15 只读检查了文件版本、SHA256、开始菜单快捷方式和匹配进程。证据为 `.run/s6-learning-current-1973ec4364a349bc876f3776796d7cff/client-inspection.json`。初次 WMI 查询被执行沙箱拒绝；经工具审批后同一类只读查询成功，未检测到匹配的客户端/执行器进程。不能据此判断用户过去打开过哪个副本。

| 对象 | 路径及实际情况 | 对 C 的意义 |
| --- | --- | --- |
| 开始菜单 PrivateAgent | `C:\ProgramSoftware\PrivateAgent\appsdesktop.exe`，版本 1.0.0，2026-08-29 文件；同目录为完整 `personal-assistant-server.exe` | 历史普通版，不能按当前直连评测文档操作 |
| 已安装联网版 | `C:\Users\likecandy\AppData\Local\PrivateAgentRemote\privateagent-remote.exe`，版本 1.0.2，2026-08-30 文件 | 历史联网版，与当前本机构建不同 |
| 开始菜单 PrivateAgentCandidate | `F:\Program\Agent\.run\s5-candidate-install-20260909-layout\privateagent-candidate.exe`，版本 1.0.0，2026-09-09 文件 | 较早测试版，desktop/sidecar/host 摘要均不同于当前构建 |
| 当前工作区配套构建 | `F:\Program\Agent\.run\s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670\bundle-rechecked\PrivateAgent-windows-x64.exe`，版本仍为 1.0.0，2026-09-15 构建 | 414 项源码与当前文件一致，随包执行器已在隔离副本中完成本轮 30 题学习测试，可作为后续 C 的配置起点 |

上述比较针对当前工作区及本机产物，没有在线查询发布通道，因此不作“最新公开发布版”结论。版本号相同不表示二进制相同；当前 desktop、sidecar、host 摘要见 `current-build-identity.json`，构建为 `portable / unsigned / dirty=true`，不是 C 完成后冻结的最终候选。

检查时 `C:\Users\likecandy\AppData\Local\com.personal-assistant.desktop` 存在，但其中尚无 `local-projects`；`com.personal-assistant.desktop.candidate\local-projects` 已存在。本轮仅检查目录是否存在，没有读取其中模型配置、账号会话或凭据。当前构建的命名空间为 `desktop`，不能直接照抄旧示例中的 `candidate` 路径。

### C 的简化操作

2026-09-15 后续选择：用户要求在自建服务器修复期间使用隔离本机入口直连云 API，并自行填入凭据。当前使用 [隔离本机 Coding / 云 API 联调](s6-local-cloud-probe.md)；下面的服务器账号流程保留作服务器恢复后的参考，不再是本次学习联调的前置条件。新入口的费用字段为 `null`，下述旧一美元草案不适用于缺少价格配置的本机入口。

1. 后续使用上表 9 月 15 日构建的 `PrivateAgent-windows-x64.exe`，保留同目录的 `private-agent-local.exe`、`exec-host.exe` 和摘要文件。本轮没有替换旧安装或修改快捷方式。
2. 在该客户端登录专用测试账号，进入“设置 → 模型设置 → 添加供应商”，填写名称、服务类型和 Base URL，密钥只填入客户端的 API Key 输入框。点击“获取模型”，选择目标模型并“添加模型”，最后点击“添加供应商”保存；修改已有供应商时按钮为“保存配置”。这些名称已按当前界面源码核对，本轮尚未操作原生窗口。
3. 提供供应商名称、Base URL、模型 ID 和可接受的预算；内部 profile/provider ID、实际参数及目录由后续指定测试配置核对，无需用户手工编写完整 JSON。
4. 形成实际配置后，绑定模型、任务次数及单次/总预算，再进行真实调用确认。下列数值是本次准备的首轮预算草案，不是已经同意的支出。

### C 的首轮配置与预算草案

本机非敏感模板为 [phase-c-desktop-model.example.json](../../../.run/records/run/s6-learning-current-1973ec4364a349bc876f3776796d7cff/phase-c-desktop-model.example.json)。它对应当前构建的 `desktop` 命名空间及本机绝对目录，采用现有 `schema_version=2 / direct_provider`，不含凭据。

模板已通过当前 `direct_config` 的严格结构校验，结果保留于同目录 `phase-c-config-validation.json`，文件 SHA256 为 `a2351f85133f7900869731958efd00637b2a0ccdb044f5f623ea6dece6ace5fb`。该摘要仅标识此份草案；填写真实模型后需要重新计算。

认证源站、供应商、profile、模型及参数仍需按专用测试账号实际配置替换；`.invalid` 地址和 `replace-with-*` 是明确占位值，`openai` 协议、32768 上下文、0.7 温度和 2048 输出上限也只用于展示格式。该文件不是可直接执行的实际模型配置，不能仅因结构校验成功就用于真实调用。

| 首轮范围或预算 | 草案 |
| --- | --- |
| 公开题与尝试次数 | `PY01`，1 次；失败后先保留证据并分析，不自动扩大范围 |
| 模型请求 | 单次及整场均最多 8 次 |
| 工具调用 | 单次及整场均最多 12 次 |
| 活动时间 | 单次及整场均 60 秒 |
| token | 单次及整场均 10000 |
| 美元费用 | 单次及整场均暂拟 1.00 美元，待结合选定平台和模型确认 |

请求数、工具数和活动时间使用现有执行限制。token 与费用按响应后的已知用量结算，属于软预算；费用缺失时保留 unknown，设有费用限额时会阻止继续请求。它不能代替供应商侧账单硬上限，也不保证首个响应不会超额。确认模型后再核对价格和能力，不把这一美元当作已经验证的费用估算。

页面中的“测试模型”仅检查可连接和模型列表存在性，不能证明已完成聊天生成或 C 的真实 Agent 调用。后续实际评测仍使用前述专用配置及绑定预算。

本轮没有启动真实桌面窗口、登录真实账号或调用供应商；安装/升级、原生 UI 和性能仍需后续实际验证。B 的个人学习测试与 C 的真实模型测试分开记录，继续以 C 的完成情况决定最终候选冻结时点。

## 7. 真实云联调回执与下一轮草案

2026-09-15 后续回执：用户已运行本机操作，并确认自建服务端已修复。当前已核对用户生成的四份记录，审阅结果为 [review.json](../../../.run/records/run/s6-cloud-review-3289b421501341cba4edb478759f5174/review.json)。本节更新当前 C 状态；前文“尚未调用供应商”属于准备阶段的历史结论。

### 实际执行结果

目标为 `api.deepseek.com` 的 `deepseek-flash`，使用 OpenAI 兼容协议、本机临时测试身份。不可变模型版本和美元费用仍未知。原配置 SHA256：`20f9b886e31705e046cdf4340aac564ad259d4ee5d4132e50f1759d4fd64eb9b`。

| 记录（位于 `.run/coding-local-probe/`） | 核验结果 |
| --- | --- |
| `preflight-107a31304d8d435bb347bc08105af167` | 本机预检通过；没有推理调用。 |
| `probe-2c847dc765024946ad2a96569ace7aa8` | 在隐藏输入 Key 时取消，任务未启动，模型请求为 0。 |
| `probe-7383d929a257453a8b53a42c8462fb05` | 在隐藏输入 Key 时取消，任务未启动，模型请求为 0。 |
| `probe-ac7573fb70d04112abb1cdd7ca462104` | 真实调用 3 次，供应商重试 0 次；因 token 预算停止，Coding 未完成。 |

最后一轮三次响应的 token 分别为 3813、4866、6067，累计为 3813、8679、14746。第三次请求发起前尚未达到 10000；响应结算后超限，运行在下一次请求前进入 `limit_exceeded / max_total_tokens`。这是现有软预算的行为，不能把 10000 当作供应商账单硬上限。

运行共消耗 13959 个输入 token、787 个输出 token；响应报告的缓存 token 已包含在输入统计内，不再次扣减。工具调用为 2 次目录查看和 6 次文件读取，没有写入、命令执行或完成验证。前后文件摘要一致，外置判定为失败；隔离、范围保护、事件完整性和产物绑定均核对通过。费用字段为 `null`，不表示免费。

四份账本均通过 `verify_ledger`，原始配置、运行器、当前源码及关联事件/产物摘要匹配。审阅没有更改原始实验或当前用户配置，也没有再次调用模型。

### C 当前结论与服务器恢复

- 已证实：真实供应商响应、原生工具调用解析、用量上报、本机读取工具及预算停止链路。
- 尚未完成：`PY01` 的实际修改、验证命令、功能判定及在预算内完成；C 保持未完成。
- 当前真实调用使用源码入口，不能直接作为指定打包 sidecar/宿主的 C 通过证据。
- 服务端恢复来自用户本轮确认；未在本轮独立检查部署或正常客户端登录。服务器恢复不改变这轮本机直连的结果。
- B 沿用个人学习已完成状态；最终候选仍待 C 完成后冻结，原生桌面和性能证据继续待补。

### 下一轮可审阅配置

已另存 [followup-model.json](../../../.run/records/run/s6-cloud-review-3289b421501341cba4edb478759f5174/followup-model.json)，不覆盖 `.run/coding-local-probe.json`。新配置 SHA256：`612fc3e74f85c24a39b6923eb2577a055b0ca28e15dcd4cc293b2d81976f33a8`。

只调整 `budget.max_attempt_tokens` 和 `budget.max_total_tokens`，从 10000 改为 50000。模型、参数、`PY01` 一次、8 次模型请求、12 次工具调用、60 秒活动时间均保持原值，美元费用继续为未知。这是按本次每轮约 3800～6100 token 留出后续执行空间的草案，不保证任务一定完成，也不消除软预算的超出可能。

配套候选目录重新核对为 414 项源码匹配，来源及各二进制摘要保存在 [candidate-identity.json](../../../.run/records/run/s6-cloud-review-3289b421501341cba4edb478759f5174/candidate-identity.json)。目前只作为下一轮验证对象，没有冻结为最终候选。

先检查草案：

    .venv/Scripts/python.exe -B scripts/run_coding_local_probe.py check --config .run/s6-cloud-review-3289b421501341cba4edb478759f5174/followup-model.json

用户接受该预算后，可直接运行下面的命令。`--authorize-model-calls` 对应本份配置内的范围，无需另外在聊天确认。上次 Key 未保存，新进程需要在本机隐藏提示中再次输入；不要将 Key 放入 JSON、命令参数或聊天。

    .venv/Scripts/python.exe -B scripts/run_coding_local_probe.py probe --config .run/s6-cloud-review-3289b421501341cba4edb478759f5174/followup-model.json --bundle .run/s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670/bundle-rechecked --authorize-model-calls

### 本轮核验命令与记忆

实际执行只读证据审阅及草案生成：

    .venv/Scripts/python.exe -B .run/s6-cloud-review-3289b421501341cba4edb478759f5174/review_real_run.py

脚本核对四份账本、当前输入与逐次产物，重算三次用量及零文件变化，并仅新增预算草案和审阅输出；退出 0。草案还通过上述 `check` 命令，不代表已授权或再次调用云模型。本轮没有产品代码改动，无需重跑产品单元测试或构建。

已阅读 `docs/project-state.md`，保留其 8 月 31 日历史状态。当前真实调用与用户报告的服务器恢复记录在本节；按仓库交接约定，本轮未获修改历史项目记忆的明确请求，因此不改写该文件。

## 8. 补丁参数拒绝的定位、修复与复验入口

2026-09-15 用户确认已执行第 7 节命令。实际运行目录为 `.run/coding-local-probe/probe-bcfed289043844bcb4d8a6b023f42c59`。本次审计及修复材料位于 `.run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0`，下文简称修复目录。

### 真实调用结果与原因

账本、模型配置、运行器、事件和逐次产物摘要均已核验；修改代码前，旧候选的 414 项源码绑定也核对通过。实际调用的 sidecar 为 `5e61a83108412191b49497db9195ae4ed4216d6a2386aacc554f84d773230888`。审阅结果见 [cloud-review.json](../../../.run/records/run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/cloud-review.json)。

- 本轮真实调用 8 次，输入 48651、输出 1880，累计 **50531 tokens**；费用未知。
- 工具执行 12 次：3 次目录查看、8 次文件读取、1 次补丁提案拒绝。终态为 `limit_exceeded / max_tool_calls`，功能与验证均未通过，前后项目文件摘要一致。
- 首个补丁调用在 `operations[0].edits` 提供了 `null`；模型已有正确的完整 `content` 和本轮读取快照，但 `edits` 契约要求数组。以当前 `PatchProposal` 重验该参数，得到 `list_type`。随后模型重新读取文件，并再次生成同样的 `edits: null`，但第二个补丁调用因工具预算停止而未执行。
- 旧错误提示只说明“工具参数无效”，没有指出字段。此次改动补充完整内容应配 `edits: []` 的工具说明，并针对该字段的数组类型错误返回明确提示。参数仍严格校验，错误输入不产生补丁预览或写入；快照、审批、权限和预算机制保持原行为。

真实供应商链路已有证据，**C 仍未完成**。本轮修复后的离线结果不能替代新产物的真实云复验，也不能继承旧产物的 C 成绩。

### 修复后的联调产物

新产物目录为 [bundle](../../../.run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/bundle)，来源见 [bundle-identity.json](../../../.run/records/run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/bundle-identity.json)。414 项来源文件中仅 `src/private_agent_local/runtime.py` 改变；sidecar 使用既有 PyInstaller 在独立目录重建。桌面壳从同目录启动 sidecar，其自身源码、构建输入及宿主来源未变，因此复用已核对摘要的桌面和宿主二进制；`build-info.json` 明确记录复用来源。

| 文件 | SHA256 |
| --- | --- |
| `private-agent-local.exe`（本轮重建） | `a03f1e97b990230f34269013e0ec68ce9d3eefc18ca3fa52b3fdc67fe5332ca6` |
| `PrivateAgent-windows-x64.exe`（复用） | `e7098d2017f6968e393cde62c1db306d89307e2aa18e675f6ff3890e613492df` |
| `exec-host.exe`（复用） | `dec3cb3cf81122454552f674231a9f1da83eb8fa6c13ddde820d262efe10cf94` |

该产物是 `portable / unsigned / dirty=true` 的本机联调候选，未安装、未启动桌面窗口，尚未冻结为最终候选。旧目录及用户原配置保留。

### 验证结果

以下命令均从 `F:\Program\Agent` 执行，修复目录名均为 `s6-patch-feedback-f6b09996597d484298ee16e99614deb0`。

| 实际命令 | 结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B .run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/run_checks.py`（当前沙箱） | 37 passed、1 failed；11.90 秒。失败为既有 `test_local_tools_keep_legacy_parameter_defaults` 的文件搜索，目录 `patch-feedback-aa23a21c324d4401bcd5a861a5b991c0`。 |
| 同一命令（经工具审批的普通本机权限） | **38 passed**；11.11 秒；目录 `patch-feedback-aaecddcfb10f4194a9faf3b73920c74b`。含非法数组反馈、无写入、合法完整内容与行编辑、审批、回滚及模型契约。 |
| `.venv/Scripts/python.exe -B -m ruff check src/private_agent_local/runtime.py tests/unit/test_local_patchsets.py` | 通过。 |
| `.venv/Scripts/python.exe -B .run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/build_probe_bundle.py` | 退出 0；sidecar 构建成功，源码及复用文件摘要核对通过。 |
| `.venv/Scripts/python.exe -B .run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/verify_bundle.py`（经工具审批的普通本机权限） | 正负两种打包联调断言通过，均使用回环模拟供应商和 AppContainer。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_local_probe.py check --config .run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/retry-model.json` | 配置校验通过，无真实模型调用。 |
| `git diff --check` | 通过。 |

在最初失败的临时项目中直接调用 `repository.search`，重现 `PermissionError / WinError 5 / errno 13`；同一测试集在普通本机权限通过，期间未修改搜索代码或测试断言，因此该失败归于当前执行沙箱的进程权限限制。两份原始测试记录均保留在 `.run/coding-agent-validation/`。

打包负例执行 5 次模拟请求、600 个模拟 tokens，数组错误被拒绝、无审批、文件摘要未变；运行器退出 1 是负例的预期结果。打包正例执行 6 次模拟请求、720 个模拟 tokens，经过 2 次审批完成补丁应用及测试，`completed / verified`，功能、验证和预算判定均通过。明细见 [bundle-verification.json](../../../.run/records/run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/bundle-verification.json)。这些模拟用量不是供应商用量或 C 质量成绩。

### 下一轮范围与命令

原 8 次请求、12 次工具、50000 tokens 均已耗尽。另存 [retry-model.json](../../../.run/records/run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/retry-model.json) 作为待接受草案：模型仍为 `deepseek-flash`，同一供应商及参数，`PY01` 一次；请求上限 **12**、工具上限 **20**、token 软上限 **100000**，活动时间保持 **60 秒**，费用仍未知。差异见 [retry-scope.json](../../../.run/records/run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/retry-scope.json)。新配置 SHA256 为 `394fd3d72bd12f672f14bc46ae924805d5550396a0e35db6d28fbe87ad8af157`。

此草案为检查后的补丁应用、验证及收尾留出额度，不保证模型完成，也不保证响应结算前不超额。本轮没有新增真实云调用。用户接受上述范围后，可在本机运行：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_local_probe.py probe `
  --config .run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/retry-model.json `
  --bundle .run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/bundle `
  --authorize-model-calls
```

API Key 仅在终端隐藏提示中输入。命令自动预检，并保存独立运行目录。B 保留个人学习范围下的历史结果；最终候选冻结及其宿主、原生桌面与性能证据仍待 C 完成后继续。服务端恢复沿用用户确认，本轮没有服务器操作。

### 项目记忆同步

已完整读取 `docs/project-state.md`，并对照当前源码、Git 状态及本轮回执。它是 8 月 31 日 E 盘历史快照，不能覆盖当前 F 盘运行事实；本页第 7 节的预算阻断记录也保留为历史，由本节补充新证据。持久变化是补丁数组参数的说明、错误反馈、回归用例及新的联调产物入口，已在本节同步。按根 `AGENTS.md` 的明确约定，本轮未改写共享历史记忆，也未创建新的记忆体系。

## 9. 验证命令超时条件的修复与同范围复验

2026-09-15 用户确认第 8 节命令已执行。本轮审阅目录为 `.run/s6-command-contract-7931fe5f83b845eda2ad0786a695c208`；以下简称审阅目录。当前 C 仍未完整通过，新的进展是实际代码修改及外置功能判定已通过。

### 真实运行结果

运行目录为 `.run/coding-local-probe/probe-162387237229424f84d7f0aa21d91a89`，审阅摘要见 [cloud-review.json](../../../.run/records/run/s6-command-contract-7931fe5f83b845eda2ad0786a695c208/cloud-review.json)。修改运行器前，已核对账本、事件顺序、配置、运行器、产物及源码绑定。

- `deepseek-flash` 真实请求 12 次，累计 **87920 tokens**，工具调用 15 次；费用和不可变模型版本未知。终态为 `limit_exceeded / max_model_requests`。
- 仅修改允许的 `src/domain.py`，外置功能判定通过，范围与隔离检查通过。原文件 SHA256 为 `59714f4e202b7fbf0e4468ad701ffa0d00d6a8a5c1fd3a6c1f8e85f1d4629438`，修改后为 `bb60ad7d9b3e2746a77bcb29285b0d6d32102693a56a01598d159e47eeed9216`。
- 模型请求执行 `python -m pytest`，命令、工作目录、保留范围、受限模式和无网络要求均匹配，但 `timeout_ms=300000` 超过验收脚本批准的 60000。该审批被拒绝，再次请求同一命令被既有拒绝记录阻止；Agent 内测试未执行，`validation_passed=false`。
- 旧任务提示只披露受限模式与无网络要求，没有披露命令超时上限。仅将原审批预览的超时改为 60000 后，现有审批函数即返回通过；该验证只在内存中进行，没有更改旧审批或重放命令。

该自动拒绝来自项目验收脚本的范围判定，不是 Codex 的工具审批拒绝。不能把外置功能判定替代 Agent 的实际测试和完整终态，因此保留 C 未完成，最终候选暂不冻结。

### 修复方式与边界

`scripts/run_coding_acceptance.py` 将 60000 毫秒上限提取为共用常量，并生成可执行的任务说明：命令参数严格按题面；工作目录、保留范围、执行模式、网络策略及超时明确给出；异步命令须等待最终退出码。审批规则和测试通过条件没有放宽。

首次补充完整 JSON 参数数组时，回归发现完成判定器将其中的 `pytest` 片段识别为额外命令，导致测试已通过但整体未完成。最终说明只在题面保留完整命令，JSON 仅列其余执行参数；新增回归核对全部 30 个公开题在两种执行模式下的验收要求均未改变。首次失败及对应模拟运行均保留，不能归因于权限或服务器。

第二次回归另有请求耗尽用例在隔离探针读取租约时返回 `PermissionError / errno=13 / winerror=null`，主模型任务未启动。调用栈定位到 `read_live_journal → read_json → file_hash → read_bytes`；现有重读只匹配 `winerror=5/32/33`，遗漏了本次错误形式。对 `coding_acceptance_isolation.py` 作最小补充：仅在 Windows 上将无 `winerror` 的 `EACCES` 纳入原有最多 1 秒重读；持续拒绝、其他 errno 和非 Windows 情况仍抛错，权限及隔离判定不变。新增回归覆盖上述边界，未删除或放宽原断言。

本次只修改验收入口、租约读取辅助函数、相关测试和两份交接文档，产品源码与配套二进制不变；继续使用第 8 节的 bundle。模型、参数、`PY01` 一次、12 次模型请求、20 次工具调用、100000 tokens、60 秒活动时间均沿用已运行的配置，未提高预算。本轮没有新增真实云调用。

### 本轮验证记录

全部 IPC/AppContainer 检查使用经工具审批的普通本机权限、合成凭据和回环供应商。以下为实际运行的命令与观察结果：

| 命令 | 结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite local-probe`，首次 | 54 passed、1 failed，144.23 秒；新增 JSON 数组导致多余 `pytest` 要求，目录 `local-probe-84cc15043e7b40e2af6e58de513da79e`。 |
| 同一命令，第二次 | 84 passed、1 failed，122.10 秒；正常 Coding 已通过，请求耗尽用例在租约读取时出现 `errno=13`，目录 `local-probe-6f8b938c57124dfb822e48b3c258e83f`。 |
| 同一命令，完成两项修正后 | **89 passed，130.92 秒**，目录 `local-probe-7dba6b6a5a4b4327b56fbd6e9d32bb54`；包括 30 题验收要求不变、审批范围、正常完成、请求耗尽、错误凭据和读取异常边界。 |
| `.venv/Scripts/python.exe -B -m ruff check scripts/run_coding_acceptance.py scripts/coding_acceptance_isolation.py tests/coding_acceptance/test_s6_local_probe.py` | 通过。 |
| `.venv/Scripts/python.exe -B .run/s6-command-contract-7931fe5f83b845eda2ad0786a695c208/verify_prompt_bundle.py` | 最终退出 0；当前 bundle 的超范围拒绝与允许范围成功两项断言通过。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_local_probe.py check --config .run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/retry-model.json` | 通过，配置摘要及预算不变，没有连接供应商。 |
| `.venv/Scripts/python.exe -B .run/s6-command-contract-7931fe5f83b845eda2ad0786a695c208/final_review.py` | 通过；5 个本轮文件增量、其他基线文件、8 份旧证据、配置及 bundle 摘要核对通过，414 项产品源码仍匹配。 |
| `git diff --check` | 通过。 |

打包结果见 [bundle-verification.json](../../../.run/records/run/s6-command-contract-7931fe5f83b845eda2ad0786a695c208/bundle-verification.json)：负例使用 6 次模拟请求、720 个模拟 token，命令拒绝、无测试执行；其运行器退出 1 是预期结果。正例使用 4 次模拟请求、480 个模拟 token，命令退出 0、`completed / verified`，功能、验证、范围和预算均通过。这些用量均为替身数据，不是云端用量或 C 质量成绩。

该打包验证脚本的首次正例也暴露了上述多余命令要求；中间一次使用更深的临时路径时，在 IPC 退出阶段报 `OSError / errno=22`，主任务未启动、没有逐次产物。换用较短的新临时路径后两项通过；该退出错误的底层原因未作独立确认，不将其解释为模型或服务器故障。全部失败目录保留。审阅脚本首次把基线排除的三个 `.env*` 示例列为新增，统一路径过滤规则后通过；没有读取这些文件的内容。

最终增量及保护项见 [final-review.json](../../../.run/records/run/s6-command-contract-7931fe5f83b845eda2ad0786a695c208/final-review.json) 和同目录 `turn-diff.patch`。本次没有改动产品构建输入，因此未重建客户端；当前模拟打包验证不能证明原生桌面、最终候选性能或修复后的真实云端任务已经通过。

### 同范围复验

在 `F:\Program\Agent` 的本机 PowerShell 执行：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_local_probe.py probe `
  --config .run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/retry-model.json `
  --bundle .run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/bundle `
  --authorize-model-calls
```

无需修改配置或重新安装。上次 Key 未保存，新进程仍须在终端隐藏提示中输入；不要发送到聊天或写入 JSON。命令自动预检并新建证据目录，旧运行记录完整保留。新回执通过后再继续最终候选冻结与宿主、原生桌面及性能证据。

### 项目记忆同步

本轮完整读取 `docs/project-state.md`，以当前源码、运行器与真实回执核对其历史范围。该文件仍为 8 月 31 日 E 盘快照，不把旧环境结论套用到当前 F 盘联调；第 7、8 节均保留为历史，由本节及 [本机联调说明](s6-local-cloud-probe.md) 同步当前命令审批契约、已知结果和复验入口。遵循根 `AGENTS.md` 的明确约定，本轮没有改写共享历史记忆，也未新建记忆体系。

## 10. C 个人联调通过与候选冻结

2026-09-15 用户成功执行新一轮 `probe-03f47eff5f7b4515a159047d2862a248`。本次已核对原始账本、修改差异、实际测试终态和配置绑定：公开 `PY01` 为 `completed / verified`，功能、验证、范围、隔离和预算通过；实际 10 次模型请求、11 次工具调用、65401 tokens，活动时间 13.187 秒。费用和不可变模型版本仍未知。第 9 节的 C 待复验状态由这份新证据更新，历史失败保留。

候选已从该次 C 实际使用的 bundle 原样冻结至 `.run/s6-final-f146e704/candidate/`，六个配套文件摘要及 414 项产品源码输入均已核对。冻结清单 SHA256 为 `f4bf402afcffbbb66f5abcb5ef214a386e11c25c8f8d51991cf69a92ca417934`；没有重建或改变实际调用预算，也没有新增云调用。

同一冻结宿主的 600 秒、130 秒测试通过；首次宿主回归为 34 passed / 1 failed，原取消测试复跑通过，并完成五次带进程创建身份的取消计时。首次失败和首次诊断的计时局限继续保留，不能将全部回归描述为一次通过。原生桌面及性能取证的最终状态、精确命令和证据位置集中记录在 [候选冻结与本机验证](s6-final-candidate-local-validation.md)。

原生窗口已完成手动登录、项目授权和本机替身模型选择，但三次任务提交均显示“执行创建失败”；测试项目无 run、无命令记录，替身生成调用为 0。打包私有 IPC 对照可以创建任务，原生失败根因尚未确认。原生补丁/测试/审查/中断恢复未验证，前台延迟样本为 0；汇总回执 `final-evidence.json` 标记 `frozen_not_accepted`。本次测试进程和临时联接已清理，最终验收仍未完成。

B 保持第 6 节的个人学习验收结论；公开单题 C 通过不等于独立模型质量放行。原正式评审门禁未放宽，产物仍为 1.0.0 的 Windows x64 便携无签名构建，未安装、部署或发布。指定历史记忆 `docs/project-state.md` 不改写，本节同步当前任务状态。
