# 阶段 B：本地学习验收

> 2026-09-15 用户再次明确：本项目用于个人学习，取消本次验收对正式题集、独立验收方及独立回执的要求，使用已有测试集。当前范围与新一轮结果见文末“2026-09-15 个人学习复验”。此前正式 B/M3 的限制仅描述原正式评测用途，不再作为本次个人学习流程的前置条件。

日期：2026-09-14（Asia/Shanghai）。源码 HEAD 为 `1dde393e29f3dbacd3647d11834b39824ac8323f`，本机工作区 `F:\Program\Agent`，开工时 Git 干净。用户说明项目主要用于个人学习，并明确选择改为本地学习验收；本轮不再以取得独立验收回执为目标。

## 验收范围

使用仓库已有 30 个已知样例检查严格清单、工作区重建、参考/错误实现判定、用户文件保护以及实际 AppContainer 访问边界。public_calibration 是工具内部的已知题集用途标识，不表示项目已发布或需要对外开放。

Python、Vue/TypeScript、Rust 各 10 题，每语言 development 6 / holdout 4，共 18 / 12；这些是分组标签，全部样例已暴露。沿用[原分类分布](./s6-evaluation-and-delivery.md)，不把样例改名为正式保留题。

| 主分类 | Python | Vue/TypeScript | Rust | 合计 |
| --- | ---: | ---: | ---: | ---: |
| bug | 2 | 2 | 1 | 5 |
| feature | 2 | 2 | 1 | 5 |
| refactor | 2 | 1 | 2 | 5 |
| long_context | 1 | 2 | 2 | 5 |
| recovery | 2 | 1 | 2 | 5 |
| boundary | 1 | 2 | 2 | 5 |
| 合计 | 10 | 10 | 10 | 30 |

清单与参考材料来自 [external_public](../../../tests/coding_acceptance/external_public/catalog.json)，保持已记录的来源和许可。公开样例用于工具验证，不能证明真实模型的编码质量或普遍的恶意代码隔离能力。正式题集仍按[阶段 B 契约](./s6-phase-b-contract.md)执行独立交接，不放宽原规则。

## 本地运行步骤

下列命令在仓库根执行。所有运行使用新的 UUID 目录，模型交互限本机确定性回环。没有生产配置、生产数据库或真实账号输入，不连接外部模型，不发起付费调用，不安装依赖或创建系统账号。

1. 验证 30 题各自的 initial、reference、wrong、protected 四个控制，共 120 次。

```powershell
.venv/Scripts/python.exe -B scripts/coding_acceptance_dataset.py qualify --catalog tests/coding_acceptance/external_public/catalog.json
```

2. 对整个题集运行真实 AppContainer 预检，核对 Agent IPC、命令令牌、读写权限及两侧工具副本的授权范围。

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode preflight --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer
```

3. 用三种语言各一个已知任务贯通 Agent 读写、公开测试和独立判定。control 使用参考脚本驱动回环替身，用于验证调用链，不计为模型独立完成。

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode control --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer --tasks PY01,VT01,RS01
```

学习用途不传 --custody-receipt / --custody-sha256，不生成虚构保管人回执。qualify 生成的 custody-template.json 保留默认空声明；不修改 blind_quality_eligible 或污染登记来取得放行。

### 当前终端的 Node/npm 入口

本轮默认命令路径选择了 Codex 自带 Node，但该入口未配套可发现的 npm。已核对本机原有 `C:\ProgramSoftware\nodejs` 包含 Node 24.14.0 和 npm 11.9.0；不安装新依赖。前述命令在普通、已配套 npm 的终端可直接运行。本轮复跑通过测试子进程临时选择这一现有安装并恢复 PATH；以下是可用于交互终端的等价写法：

```powershell
$phaseBLearningSavedPath = $env:PATH
$phaseBLearningExit = 1
try {
    $env:PATH = 'C:\ProgramSoftware\nodejs;' + $phaseBLearningSavedPath
    .venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode preflight --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer
    $phaseBLearningExit = $LASTEXITCODE
}
finally {
    $env:PATH = $phaseBLearningSavedPath
}
if ($phaseBLearningExit -ne 0) { throw '学习预检失败，请保留本次证据目录' }
```

qualify 和 control 使用同一方式，只替换其中的 Python 命令。本轮实际子进程在 finally 后执行 exit $phaseBLearningExit 返回原始退出码；上例改用 throw，避免结束交互终端。示例目录仅是本机实测安装，其他机器应先确认真实路径。未修改 Windows 全局环境、终端配置或用户 npm 配置。

## 如何阅读证据

| 位置 | 学习与核对重点 |
| --- | --- |
| .run/coding-dataset-validation/dataset-UUID/qualification.json | 30 题与四种控制是否完整；初始失败、参考成功、错误实现被拒、保护文件变更被拒 |
| qualification-attempts.jsonl 与各控制 verdict.json | 启动/结束链、任务/候选/判定器摘要；超时或环境错误不能冒充有效负向控制 |
| .run/coding-acceptance/preflight-UUID/manifest.json | AppContainer 令牌、权限正反例、实际授权目录和身份摘要 |
| .run/coding-acceptance/control-UUID/attempts.jsonl | 实际终态、评测停止原因、公开命令和独立判定分开记录 |
| metrics.json | 保留已启动失败和未知项；公开校准不能形成正式质量决议 |

预检的 starts.jsonl 应为空，表示没有正式题目尝试启动；预检本身仍会启动权限探针和合成 IPC 进程。探针中刻意的越界读取可能形成 output_validation_failed，应保留实际错误码，权限 verified 不等于功能任务成功。

原始证据位于本机被 Git 忽略的 .run 目录，本文记录的目录名不保证在其他机器存在。本轮保留全部成功与失败运行，没有用复跑覆盖原目录。

## 2026-09-14 实际记录

以下运行均已结束。2026-09-10 的 631 passed / 1 skipped、120 次控制和 30/30 校准属于[历史成绩](./s6-phase-b-remaining-report.md)，不是本轮复测结果。

| 本轮检查 | 结果 | 证据目录 |
| --- | --- | --- |
| 默认工具路径的 preflight | 退出 1；missing=[npm]，未启动题目 | preflight-32b3fced7bb14fd0908ee1e6ba092caa |
| 默认工具路径的 qualify | 退出 1；Python 10 题完成，进入 Vue 工具准备时 FileNotFoundError，未形成完整验收成绩 | dataset-4ef6729eef9b4b2d8a5ac18b6c839acc |
| 配套 Node/npm 后的 preflight 首次运行 | 退出 1；PermissionError，未启动题目；未记录完整异常栈，具体原因待定位 | preflight-805a4e42466440b188d8a620068003a1 |
| 独立合成 Agent IPC 诊断 | 退出 0；权限、令牌及授权目录 verified=true；上述 PermissionError 暂未复现 | learning-ipc-diagnostic-2ce6484f38fc4ba8a58b4a232935d358 |
| 配套 Node/npm 后的 30 题 qualify | 退出 0；30/30 题、120/120 控制通过，isolation.verified=true，摘要账本核对通过 | dataset-47690660f1b44c67b2baf46edf08a024 |
| 全题集 AppContainer preflight 复验 | 退出 0；preflight.passed=true，isolation.verified=true，摘要账本核对通过，题目启动数为 0 | preflight-22a4d7a672064f2d907b56b171cf1072 |
| 三语言 control | 退出 0；3/3 通过，isolation.verified=true，runner_errors=[]，摘要账本核对通过 | control-7fe675434ca84d809d257def3ceb2c1a |

通过的预检实际观察到候选进程和 Agent 命令均为 AppContainer、capabilities=0；公开文件可读，验收材料及观察程序文件不可读写，Agent 读取工具也拒绝越界。Agent 授权目录只包含可写项目目录与只读 Agent Python 副本，命令模式为 restricted、网络策略为 none。这些是当前本机样例环境的正反探针证据，不是仅凭目录位置作出的隔离判断。

上述一次 PermissionError 没有完整异常栈，原因尚未定位。后续合成 IPC 探针及完整预检通过只能说明新运行成功，不能证明已修复首次失败。

control 的 3 个启动记录与 3 个结束记录完整保留，contaminated_started=3、independent_completed=0、delivery_decision=blocked。预检记录了 30 个 preflight_only 未启动项；它们没有进入已启动编码分母。两次预检失败也均未启动题目，失败证据与成功复跑位于不同目录。

三题的实际终态均为 completed、run_error_code=null；功能验证、公开命令、修改范围、证据完整性和隔离检查均通过，没有事件完整性错误，也没有请求取消。本轮没有重新覆盖六种终态和取消的完整专项，不把这三题结果当作阶段 A 全量回归。

完整 qualify 留下 240 条启动/结束记录，blind_quality_eligible=false，污染登记包含 1 个覆盖全部已知题目的事件。调用现有 verify_qualification_ledger 与 verify_ledger 核对三组成功运行的日志链，并逐项复算记录关联的产物摘要，均通过。使用的只读辅助命令如下；它位于本机历史证据目录，不是跨机器安装依赖：

```powershell
.venv/Scripts/python.exe -B .run/s6-phase-b-remaining-5c4f64b2ba234de7b64a67d1db361f78/check_evidence.py .run/coding-acceptance/preflight-22a4d7a672064f2d907b56b171cf1072
.venv/Scripts/python.exe -B .run/s6-phase-b-remaining-5c4f64b2ba234de7b64a67d1db361f78/check_evidence.py .run/coding-acceptance/control-7fe675434ca84d809d257def3ceb2c1a
.venv/Scripts/python.exe -B .run/s6-phase-b-remaining-5c4f64b2ba234de7b64a67d1db361f78/check_evidence.py .run/coding-dataset-validation/dataset-47690660f1b44c67b2baf46edf08a024
```

下列 SHA256 为本机重新计算并核对的内容摘要，不是独立人员签署的回执。两份运行 manifest 和 qualification 均关联同一清单摘要。

| 产物 | SHA256 |
| --- | --- |
| [题集清单](../../../tests/coding_acceptance/external_public/catalog.json) | 533c6bc8973e22a4b4da2d9bb10176c8c800a6ba8223f6239a6b6d713fc201a3 |
| [qualification.json](../../../.run/coding-dataset-validation/dataset-47690660f1b44c67b2baf46edf08a024/qualification.json) | c41675b370b70143e5a7659ac029bda4b3854a1c258d8e4b626a38141853beb3 |
| [预检 manifest.json](../../../.run/coding-acceptance/preflight-22a4d7a672064f2d907b56b171cf1072/manifest.json) | 5c97933034708c1a5d66bd43494643db43148cdb591d42ad3d9716b73de6659d |
| [control manifest.json](../../../.run/coding-acceptance/control-7fe675434ca84d809d257def3ceb2c1a/manifest.json) | 6ab04704d8b2adcbcfbff22ad782d910a809b45ac4e5e4b7299a011cc9a3f9ce |

本轮只改动说明文档和契约入口，没有修改工具源码、样例或产品代码，因此未重跑全量 S6 acceptance、matrix、打包或完整产品回归。两项 CLI --help、文档命令语法、链接、题集分类对照和 Git 差异检查均通过；所有成绩仅限上述本轮直接运行。

## 结论边界与项目记忆

本地学习验收已完成上述工具验证及证据核对，达到本轮调整后的退出条件，并保留一次未定位的预检 PermissionError。正式阶段 B 的独立保留题和回执条件仍未满足，M3 继续阻断；没有把学习用途作为原退出条件的替代，也没有进入 C～F。

| 阶段 B 工作项 | 本轮学习用途的核对范围 |
| --- | --- |
| B-01 | 沿用严格 JSON 入口，加载现有 30 题清单并核对数量、分组和分类；未重新执行全部非法输入单测 |
| B-02 | 全题集外部清单预检、三语言 control、工作区重建、独立判定及结束摘要核对 |
| B-03 | 当前 Windows 下实际候选进程与 Agent IPC 的 AppContainer 身份、读写正反例和授权范围 |
| B-04 | 对既有 30 个已知样例执行四种控制；没有新建或认证正式保留题 |
| B-05 | 核对追加式账本、未启动项、三次已知题目尝试及摘要关联；保留失败记录，质量决议继续 blocked |

已读根 AGENTS.md、docs/project-state.md、总体路线、开发计划、阶段 A 和阶段 B 报告。项目记忆保留 2026-08-31 的 E 盘历史环境，当前 Git 已核对为 F 盘和上述 HEAD；不继承旧环境或旧测试成绩。按用户及仓库约定不自动修改 docs/project-state.md；本轮用途和实测同步到本文及契约入口。

## 2026-09-15 个人学习复验

### 范围调整

用户确认没有正式题集和独立验收方，并要求取消该项，改用现有测试集。按这一要求，本次 B 的验收内容是：30 道公开题的四种控制通过，实际 Agent 的文件修改、命令验证及保护场景通过，AppContainer 隔离和证据摘要可核对。无需独立人员出题、未污染声明或 custody 回执。

工具已有 `public_calibration` 路径，能够完成上述流程，因此本次仅调整任务文档并执行测试。题集保留已知用途标记，初始、参考、错误实现及保护文件控制均真实执行；账号和模型使用本机测试替身。没有把测试结果写成真实模型质量，也没有更改产品权限、正式用途校验或预算逻辑。

本轮 HEAD 仍为 `1dde393e29f3dbacd3647d11834b39824ac8323f`。工作区已有的源码改动按开工摘要保护。证据父目录为 `.run/s6-learning-current-1973ec4364a349bc876f3776796d7cff/`；每次实验在其中新建 UUID 目录，旧证据未覆盖。

### 本轮执行与证据

采用现有 `.venv`、已安装 Node/npm 和 Rust 工具链，不安装依赖。包装器只给测试进程提供环境白名单，临时选择 `C:\ProgramSoftware\nodejs`，并用 Windows Job 回收所属进程树。外层 1800 秒上限只用于防止验证进程遗留，题目、判定器及产品内部时限保持原值。

实际入口如下，在仓库根目录执行；原始子命令、工作目录、退出码和耗时写入对应的 `*-invocation.json`：

```powershell
.venv/Scripts/python.exe -B .run/s6-learning-current-1973ec4364a349bc876f3776796d7cff/run_learning.py qualify
.venv/Scripts/python.exe -B .run/s6-learning-current-1973ec4364a349bc876f3776796d7cff/run_learning.py preflight
.venv/Scripts/python.exe -B .run/s6-learning-current-1973ec4364a349bc876f3776796d7cff/run_learning.py control
```

qualify 使用当前判定器对全部 30 题运行 initial/reference/wrong/protected 控制。preflight/control 指定 9 月 15 日 `bundle-rechecked` 的隔离副本、完整公开题集、`--isolation appcontainer --protocol openai`；Agent 经过本机 IPC 和随包执行器，不调用真实供应商，也不启动原生桌面窗口。

| 项目 | 本轮结果 |
| --- | --- |
| 30 题四种控制 | 退出 0，30/30 题、120/120 控制通过，992.812 秒；`qualify/dataset-49797a7b565b47a9abcf71496b296535`；资格账本、120 份判定产物与当前判定器摘要已核对 |
| 当前构建的全题集预检 | 退出 0，58.219 秒；`preflight/preflight-8bf3e0393d714a9e8abfb2994c07a1ea` |
| 当前构建的 30 题 Agent 流程 | 退出 0，30/30 通过，1521.453 秒；`control/control-3e64d323348c4de2807558da09c566a1` |
| 最终账本、判定产物与身份复核 | 退出 0；120 份控制判定、90 个 Agent 关联产物、两组实验账本与当前构建均核对通过；`learning-audit.json` 中 `learning_b_passed=true` |

最终审计命令及产物如下：

```powershell
.venv/Scripts/python.exe -B .run/s6-learning-current-1973ec4364a349bc876f3776796d7cff/audit_learning.py
```

[学习验收审计结果](../../../.run/s6-learning-current-1973ec4364a349bc876f3776796d7cff/learning-audit.json)核对了当前题集、判定材料、判定器、运行器与产品输入。30 条 Agent 记录均已启动并有对应结束记录，`system_behavior_passed=true`、`failure_class=null`、`runner_errors=[]`。实际启动的随包执行器摘要一致，命令执行模式均为 `restricted`，网络策略为 `none`，命令证据关联同一 `exec-host.exe`，隔离测试数据库版本均为 schema 7。磁盘文件、启动进程身份与加载组件内存身份仍分别记录，后者保持 unknown。

**本次 B 的个人学习验收通过。** 题集四种控制、完整 Agent 流程及证据核对已完成，独立题集和回执无需用户继续准备。本轮没有真实模型调用，`real_model_quality_verified=false`；也未启动原生桌面、开展供应商质量评测或冻结最终候选。

该学习用途不需要工具生成正式交付决议。原始 `metrics.json` 的 `delivery_decision=blocked` 属于正式 M3 报表口径；本次学习验收以本节的实际测试与摘要核对为准，不修改原始报表来改变其含义。

### 客户端与下一步

本轮核对了旧安装、快捷方式和当前本机构建，详见 [验收准备记录第 6 节](s6-b-c-final-candidate-readiness.md#6-个人学习范围调整与客户端核对)。C 可在当前构建上继续准备测试账号、模型和预算，不再等待独立验收方或正式保留题。真实账号、模型调用和原生桌面性能仍按实际结果分别记录。

已完整阅读 `docs/project-state.md`，按当前源码、构建摘要与测试产物处理其历史快照差异；本次用户需求与学习验收结论同步到本文、后续计划和验收准备记录。未修改共享历史记忆文件，也未创建新的记忆体系。

文档、配置草案和工作区最终核对使用以下入口；结果写入同轮 `workspace-after.json`，原有工作文件按开工 SHA256 比对，忽略目录中的运行证据单独保留：

`review_preparation.py` 首次退出 1：开工摘要记录了 1276 个文件，未纳入 `.env.container.example`、`.env.example`、`apps/desktop/.env.example`，而首次最终清单包含这三份示例，导致范围不一致。只读 `git ls-tree` 和 `git diff --exit-code --quiet HEAD --` 已确认三份文件均存在于原 HEAD 且无差异，没有读取或展示配置正文。辅助脚本已改为对相同 1276 文件范围比对，并单独核对这三份示例的 Git 状态；未更改产品、原始测试结果或验收断言。

```powershell
.venv/Scripts/python.exe -B .run/s6-learning-current-1973ec4364a349bc876f3776796d7cff/review_preparation.py
git diff --check
git status --short --branch
git diff --stat
git diff --staged --stat
```
