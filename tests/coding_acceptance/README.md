# Coding S0–S6 可复现验收入口

阶段 B 增加 external_public/ 下的 30 题严格 JSON 公开样例、独立输出比较及泄露/篡改测试。直接检查使用 scripts/run_coding_validation.py 的 external、isolation、custody 套件，均已纳入 acceptance/all。isolation 通过实际 AppContainer 与 Agent IPC 核对令牌、材料权限、两侧工具目录及命令限额；custody 验证来源回执、判定产物绑定和污染记录，合成回执不作为独立性证据。新增参数、严格字段与统计规则见 [阶段 B 契约](../../docs/analysis/coding-agent-upgrade-20260908/s6-phase-b-contract.md)，本轮成绩见 [补充验收记录](../../docs/analysis/coding-agent-upgrade-20260908/s6-phase-b-remaining-report.md)。样例全部已暴露，18/12 仅为分组，不能声明为未污染保留题。

验收侧可运行 scripts/coding_acceptance_dataset.py qualify --catalog <清单路径>，为每题产生初始、参考、错误和用户文件保护四个控制及独立回执模板。公开题集使用 --mode control 或 --mode matrix --isolation appcontainer 可复验原生受限链路；正式 independent_evaluation 禁止参考脚本注入，需要验收方交接回执及固定摘要。该检查不启动真实模型质量实验，也不代表安装包验收。

## S6 当前入口（2026-09-09）

新增 `s6_fixtures.py` 的 30 题、三类语言、18/12 划分；S0 `tasks.json` 保留原样。正式 IPC 校准用 `scripts/run_coding_acceptance.py`，新测试用 `scripts/run_coding_validation.py --suite acceptance`，并入 `all`。准确预算、命令、可信项目边界、审阅流程和退出码见 [S6 评测协议](../../docs/analysis/coding-agent-upgrade-20260908/s6-acceptance-protocol.md)，实际成绩见 [开发报告](../../docs/analysis/coding-agent-upgrade-20260908/s6-validation-report.md)。

下文 S0–S3 数字是历史记录。当前 `all` 包含 execution、streaming、sandbox、recovery、history、acceptance；`duration` 是约 130 秒旧 API 探针，`execution-duration` 是 600 秒持续命令，均单独运行。G10 旧 xfail 已在 S5 收尾解决，不把下文历史状态作为当前失败。

在仓库根目录使用现有 Python 环境，无需安装依赖：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite completion
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite context
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite repository
.venv/Scripts/python.exe -B scripts/run_coding_legacy_validation.py
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite duration
```

每次自动新建 `.run/coding-agent-validation/<suite>-<uuid>`，保留 `invocation.json`、`pytest-result.json` 和 `observations/*.json`。不复用或递归删除旧目录，不使用 pytest 会清理目标目录的 `--basetemp`。

`all` 包含 local、contracts、baseline、host、tooling、completion、context、repository；`duration` 是独立约 120 秒的真实超时探针。每个子套件都可单独运行。首轮启动失败、收集错误和用例失败均非零退出；严格 xfail 和 PTY 不可用单独列出，不能计入产品通过率。意外 XPASS 会失败，要求后续修复阶段重新审查基线。S1 已将 G01/G02 改为正常回归；当前剩余两个 G10 严格 xfail，S0 的四个 xfail 是历史成绩。

## 测试隔离

启动器显式加载 `pytest_asyncio.plugin` 和 `coding_validation_plugin`，设置 `--noconftest`、禁用自动插件发现、清除外部 pytest 选项。插件拒绝导入业务配置、数据库及主 API；本机专用 API 使用临时 SQLite 和 MockTransport。子进程只继承必要系统环境，不继承 `PA_*`、模型凭据、Python/Node 注入选项；测试路径、配置文件和源码路径均为绝对路径。

专用 `tmp_path` 使用新 UUID 和继承 ACL，绕过 pytest 私有目录 ACL 的 Windows 问题。命名管道的 `WinError 5` 与目录 ACL 是不同限制：受限运行环境若仍阻止子进程，应在获准的开发终端重跑相同命令，不修改业务代码或放宽测试断言。进程采用 Windows Job/其他平台进程组回收；这不构成对恶意候选代码的 OS 沙箱。

只使用已审查的固定套件，不是通用任意测试执行入口。真实宿主测试需要先 `cargo build --release --locked --offline --manifest-path apps/exec-host/Cargo.toml`；缺少宿主按失败处理。宿主探针只写临时项目及其临时兄弟文件，仅连接自己创建的回环监听器，不访问外部网络。未运行会修改系统解释器目录 ACL 的旧 AppContainer spike。

## 30 个固定任务

`tasks.json` 是唯一任务来源，内含起始代码、提示词、可编辑文件、JSON 判定用例和判定器正对照参考实现。三类项目各 10 项：Python 小型包、Node ESM 小型包、Python/Node 混合工作区。PY07 的目标位于约 2000 行的大文件尾部；每份夹具带须保留的用户内容。没有虚构 git 提交：这些是可重建的合成项目树，实际 Git dirty 行为由单独本机回归覆盖。

固定划分为 24 开发任务、6 留出任务（每类 09/10）；留出集不用于修改提示词。参考答案和判定器不复制到候选项目，但它们在本仓库可读，因此这不是防作弊的盲评环境。S6 若用于正式质量结论，应先将留出判定器交给独立评测环境，并扩大真实项目工作流覆盖，不能将这 30 个小任务等同复杂仓库独立完成率。

预算记录：每次最多 24 模型请求、48 工具调用、3600 秒、120000 总 token，每模型 3 次。前面三个上限依据现有 Runtime；token 是评测预算，当前 Runtime 尚未执行该 token 门禁。S0 不调用模型，所有模型结果为 `not_run`，正对照仅验证任务可判定。

```powershell
.venv/Scripts/python.exe -X utf8 -B scripts/coding_task_baseline.py list
.venv/Scripts/python.exe -X utf8 -B scripts/coding_task_baseline.py rebuild --task PY01 --directory F:/Program/Agent/.run/s0-py01
.venv/Scripts/python.exe -X utf8 -B scripts/coding_task_baseline.py judge --task PY01 --directory F:/Program/Agent/.run/s0-py01
```

`rebuild` 的父目录须已存在，目标必须是新目录；复跑更换目录。初始实现应判定失败并返回 1；修改目标文件后用同一 `judge` 再判定。判定器执行候选函数、核对输出并保护非编辑文件，不采用模型自评。候选代码按当前用户权限执行，存在 10 秒超时及进程树回收；只对受信任的隔离测试项目使用。实际账号数据和生产仓库不能作为夹具目录。

`test_tooling.py` 对每个任务验证“起始实现失败、参考实现通过、用户文件被改则拒绝”，不把这些正对照算作 Agent 完成。

## 契约维护

### S6 D 本地准备（2026-09-15）

`scripts/run_coding_validation.py --suite phase-d` 验证候选身份、冻结输入变化、严格审阅、不完整实验及 IPC 关联，已纳入 `acceptance/all`。源码身份 `s6-product-2` 覆盖桌面、Rust 宿主、本机核心和构建输入。构建产物还须核对非空、无重复且完整的源码清单总摘要，以及桌面、sidecar、宿主和构建记录；源码、产物、安装和进程分别记载，缺失证据保持 `unknown`。历史身份只按原范围解释，不能补造新的验收证明。

每次尝试开始前和实验结束时核对产品、题集、判定器与配置。审阅入口重新核对当前输入和候选产物，拒绝重复 JSON 字段、重复尝试和摘要变化，重算实验完整性。`failure_records` 保留逐次原始分类和归属；尚未核实的归属为 `unresolved_requires_review`。原始尝试日志不因审阅改写，公开题独立完成分子仍为零。

新版身份的 `files` 是路径索引，`source_files` 是 `{path, sha256}` 记录数组，避免含 `Secrets` 等合法文件名使摘要被通用凭据脱敏器误遮蔽；源码与 bundle 都需通过落盘/读回验证。历史来源摘要算法不变，旧身份按其历史范围解释；缺新版完整身份时不能提升为当前候选证明。

`verify-unified-client.py --bundle <独立构建目录> --work-dir <独立输出父目录> --model-mode service|openai|ollama` 的基础验证使用合成账号和本机模型设置、回环替身及打包 sidecar/宿主；`service` 为历史标签，实际使用本机 OpenAI 传输。输出 `verification.json` 记录文件摘要、启动 PID、请求与运行关联及失败状态；它不是原生桌面或安装证据。`--s6` 另外要求完整候选清单并使用公开题 AppContainer 校准，不能给不完整二进制目录补造冻结身份。

本轮命令、600 秒专项、失败上下文、复验范围和未验证项见 [阶段 D 报告](../../docs/analysis/coding-agent-upgrade-20260908/s6-phase-d-local-development-validation.md)。UI 指标只有取得“宿主收到输出至 UI 可见”的至少 100 个前台样本及负载记录才可判断，后端耗时不替代该指标。

桌面浏览器验证使用 `coding-run.spec.ts`、`coding-artifact.spec.ts`、`coding-workbench.spec.ts` 与合成账号夹具。隔离运行须关闭 Vite `.env` 读取、使用独立端口且不复用已有服务；只在该子进程设置 `VITE_LOCAL_FULL_BACKEND=true`，全部 API 由路由替身响应。具体独立配置与已执行命令见 D 报告。没有完成证据的旧终态应显示“结果未确认”；普通用户的旧 `ui=v1` 参数不能恢复下线的兼容壳。空项目及失效工作区通过现有新建项目对话框操作，不再跳转下线的 projects 视图。

S6 阶段 C 的 `run_coding_validation.py --suite model-evaluation` 纳入 acceptance/all。2026-09-15 起覆盖 schema 2 `direct_provider` 的正式会话、IPC 配置交接、直连三协议、预算和过程指标；旧代理的纯协议测试继续解释历史兼容行为，实际 `product_proxy` 执行明确拒绝。无凭据配置、`preflight/probe` 命令及授权边界见 [阶段 C 报告](../../docs/analysis/coding-agent-upgrade-20260908/s6-phase-c-validation-report.md)。本页 S0 的历史 token 限制说明不代表 C：实际模型评测通过 `ContextLimits.max_total_tokens` 在下一请求前执行软预算门禁。

control/matrix 保留 fixture 身份和 service/OpenAI/Ollama 的历史计划标签；service 标签现通过本机 OpenAI 适配器消费回环替身，实际 wire 路径和协议单独记录。`legacy_stream` 场景在发送前选普通响应。原六种终态、取消竞争、事件连续性、独立判定和追加式账本继续复验，不能用恢复服务器推理满足旧路径断言。所有校准及公开样例保持 M3 blocked。

模型评测测试使用合成账号/密钥；正常产品交接由 Agent 查询一个系统凭据，测试子进程设置 `PA_EVALUATION_SYNTHETIC_ONLY=1` 阻止该访问。这个保护仅在 pytest 内传入，不修改全局环境，也不阻断将来已授权的交互式预检。已有 Python、Node/npm 和宿主是前提，测试不会安装依赖。

从 `private_agent_core/coding_contracts.py` 修改类型，再运行 `scripts/protocol_codegen.py`。`--check` 校验旧协议与新 Coding 生成物，`test_contracts.py` 校验 Schema、实例及业务不变量。S1 已接通本机完成要求、运行结果和命令结果；其他类型不代表能力已启用。准确责任见 [契约决议](../../docs/analysis/coding-agent-upgrade-20260908/s0-contract-decisions.md)。

## S1 事实、前端与兼容回归

`tests/unit/test_local_completion.py` 使用真实本机 ASGI、临时 SQLite 和磁盘，只替代模型端与专用命令故障。`test_s1_wire_examples_from_real_api` 导出六类运行到当次隔离目录的 `s1-wire/*.json`；仓库 `s1-wire-examples.json` 合并自真实导出，用于 Python 契约、Vue 投影和组件校验。更新时重新运行 completion，再合并该目录六个文件；禁止手编全部成功的 UI 载荷。原始输出位置记录在 S1 报告。

旧服务端兼容入口 `run_coding_legacy_validation.py` 只复跑脚本内冻结的原有纯单测，不修改原测试，也不替换业务模块。它允许导入必要业务类型，但使用新建临时用户目录、固定不可连接的测试 DB 配置及网络审计，禁止外部连接和业务数据库连接；Windows asyncio 的本机 socketpair 仍可用。它不等于业务 API/MySQL 集成验收，不能作为任意测试节点执行器。

在 `apps/desktop` 下运行：

```powershell
npm run test -- src/features/coding src/services/localExecutor.spec.ts src/services/privateTransport.spec.ts
npm run build
```

完整成绩、环境阻塞与剩余 S4 限制见 [S1 验收报告](../../docs/analysis/coding-agent-upgrade-20260908/s1-validation-report.md)。

## S3 文件操作与故障边界

`repository` 包含 `test_local_file_ranges.py`、`test_local_search_pagination.py`、`test_local_patchsets.py`。使用临时真实文件、Git 仓库、SQLite 和本机 ASGI；注入文件系统/日志故障，不假装执行过真实断电或填满磁盘。Windows junction 使用真实目录联接，symlink 创建缺权限时明确 skip。旧写入测试先读取版本；PowerShell 直接文件写 cmdlet 在所有权限档位拒绝，项目脚本的间接副作用仍由 S4 处理。

PY07 回归从固定任务夹具重建大文件，先确认判定器失败，再通过读取末尾和局部补丁修正，最后判定通过并核对前文及用户文件。它验证工具机制，不计作真实模型完成率。完整差异分页、失败重试、回滚确认和跨任务隔离由两个 Patch 组件测试验证。最新成绩与证据目录见 [S3 验收报告](../../docs/analysis/coding-agent-upgrade-20260908/s3-validation-report.md)。
