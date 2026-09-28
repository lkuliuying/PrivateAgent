# 阶段 B 补充开发与验收记录

日期：2026-09-10（Asia/Shanghai）。工作区 F:\Program\Agent，分支 dev/1.0.0，HEAD 25ba4d3。承接用户“完成阶段 B 剩下的问题”的授权，仅处理 B-01～B-05，没有进入 C～F、付费模型调用、依赖升级、提交、推送、打包、安装或部署。

**阶段 B 完整退出仍不满足。** 用户已明确回复“尚未准备独立保留题”。本轮补齐可本机实施的隔离后端、独立题集验收与交接工具；公开样例及合成回执不作为独立题集或正式质量证据。首次交付记录见 [历史报告](./s6-phase-b-validation-report.md)，当前接口见 [阶段 B 契约](./s6-phase-b-contract.md)。

## B-01～B-05 状态

| 工作项 | 本轮补齐内容 | 验收边界 |
| --- | --- | --- |
| B-01 | 复用严格 JSON 与固定判定契约，增加内部用途信息，阻止正式清单使用参考脚本 | 工具完成；不接受任意 Python 配置导入 |
| B-02 | 外部运行器贯通 AppContainer、两侧工具、实际预检、工作区重建、判定、运行清单及开始/结束核对 | 工具完成；正式材料接入仍需独立回执 |
| B-03 | 真 exec-host / Agent IPC 核对令牌、权限与租约；Agent 与判定工具分开；限制观察程序读写、日志输出和进程预算 | 当前 Windows 工具验证，不代替正式保留题环境的逐次预检 |
| B-04 | 验收侧 qualify 为每题重建四种控制，输出回执模板及污染登记 | 公开 30 题供工具验证；独立正式题集、12 个保留题及独立人员回执缺失 |
| B-05 | 正负控制日志及判定产物绑定，隔离和回执进入尝试摘要，污染登记另存新版本 | 已启动失败保留；公开校准及缺证据继续 blocked |

## 实际变更文件

以下是相对本轮开工快照的增量，不把其他会话的已有改动记为本轮成果。

| 文件 | 本轮变更 |
| --- | --- |
| [coding_acceptance_isolation.py](../../../scripts/coding_acceptance_isolation.py) | 新增 Windows AppContainer 后端、分离的工具副本、真实权限/租约探针、输出和时长边界 |
| [coding_acceptance_dataset.py](../../../scripts/coding_acceptance_dataset.py) | 新增验收侧四种控制、来源回执核验、污染新版本、判定产物与日志链关联 |
| [coding_acceptance_pytest.py](../../../scripts/coding_acceptance_pytest.py) | 新增公开 pytest 收集边界适配，保留根 conftest 与标准断言 |
| [coding_acceptance_catalog.py](../../../scripts/coding_acceptance_catalog.py) | 重建和判定可接收隔离运行时；保留旧默认入口 |
| [coding_acceptance_judge.py](../../../scripts/coding_acceptance_judge.py) | 冻结候选副本、只读观察程序、隔离编译/执行和判定绑定 |
| [coding_acceptance_transport.py](../../../scripts/coding_acceptance_transport.py) | RuntimeClient 增加专用工具路径和容器临时目录定位参数 |
| [coding_acceptance_schema.py](../../../scripts/coding_acceptance_schema.py) | 载入后附加内部 purpose，原外部 schema 和任务摘要算法保留 |
| [coding_acceptance_evidence.py](../../../scripts/coding_acceptance_evidence.py) | 新记录要求实际隔离事实，完整正式实验要求独立回执 |
| [run_coding_acceptance.py](../../../scripts/run_coding_acceptance.py) | 新参数、真实隔离预检、审批模式限制、回执固定及逐次核对 |
| [run_coding_validation.py](../../../scripts/run_coding_validation.py) | 新 isolation / custody 套件并入 acceptance / all |
| [windows_sandbox.py](../../../src/private_agent_local/windows_sandbox.py) | python.cmd / python.bat 不再额外授权当前解释器目录；原生 exe 和虚拟环境解析保留 |
| [test_s6_isolation.py](../../../tests/coding_acceptance/test_s6_isolation.py) | 新增实际 Agent IPC、令牌/权限/租约、三语言公开测试、篡改与配额回归 |
| [test_s6_custody.py](../../../tests/coding_acceptance/test_s6_custody.py) | 新增完整回执、重新计算摘要后的换绑、污染与正式参考注入拒绝测试 |
| [test_windows_sandbox.py](../../../tests/unit/test_windows_sandbox.py) | 补充 cmd / bat / exe 授权范围正反对照 |
| [阶段 B 契约](./s6-phase-b-contract.md) | 同步隔离机制、固定接口、回执与污染操作及限制 |
| [首次阶段 B 报告](./s6-phase-b-validation-report.md) | 增加后续入口，保留历史测试与失败 |
| [总体路线](./README.md) | 指向本轮事实，保留原路线和门禁 |
| [后续开发计划](./s6-follow-up-development-plan.md) | 更新阶段 B 状态入口，原退出条件不变 |
| [测试入口说明](../../../tests/coding_acceptance/README.md) | 新套件和验收侧入口 |
| [本报告](./s6-phase-b-remaining-report.md) | 记录增量、实测、历史失败及未完成条件 |

## 测试记录

以下命令均从 F:\Program\Agent 执行。阶段 A 的 128 / 477 + 1 skip / 106，以及首次阶段 B 的 241 / 590 + 1 skip / 106 均为历史证据，不作为本轮成绩。下表运行均已结束，按实际退出结果记录。

| 命令 | 本轮观察结果 | 证据目录末级名称 |
| --- | --- | --- |
| .venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite external | 113 passed，44.94 秒，退出 0 | external-081b7b9e4d854267817dc16197675f7e |
| .venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite custody | 27 passed，48.23 秒，退出 0 | custody-7b8ae9ed86154d189dfa15606884f435 |
| .venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite sandbox | 20 passed，107.66 秒，退出 0 | sandbox-3164a2be94744adba3672105b714f6e1 |
| .venv/Scripts/python.exe -B .run/s6-phase-b-remaining-5c4f64b2ba234de7b64a67d1db361f78/direct.py actual_agent test_s6_isolation.py | 最后一次权限/租约修正后的直接测试：1 passed、10 deselected，20.91 秒，退出 0 | b-remain-direct-10384c4ef05b4fd29c73965e1bbfa427 |
| .venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite acceptance | 279 passed，431.78 秒，退出 0 | acceptance-b3881262ca2542fcb69d4d0eb889c717 |
| .venv/Scripts/python.exe -B scripts/run_coding_legacy_validation.py | 106 passed，9.74 秒，退出 0 | legacy-da1f062412fd4eb5bf335672c627ba86 |
| .venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode control | 30/30，退出 0；尝试累计 147.881 秒 | control-1ccc87c856be43cba908aad99b532837 |
| .venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode matrix --tasks PY01,PY09,PY10,VT07,RS01 | 15/15，退出 0；尝试累计 68.174 秒 | matrix-04ff32e944ce45219675de63ed565d2f |
| .venv/Scripts/python.exe -B scripts/coding_acceptance_dataset.py qualify --catalog tests/coding_acceptance/external_public/catalog.json | 30 题、120/120 控制通过，退出 0；日志链及全部判定产物摘要复核通过 | dataset-750104b8e1164d4993a021f04babc72e |
| .venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode control --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer | 30/30，退出 0；尝试累计 1314.982 秒，日志链与产物摘要复核通过 | control-ac8c14d9685b4f33a8642eda75b3b230 |
| .venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode matrix --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer --tasks PY01,PY09,PY10,VT07,RS01 | 15/15，退出 0；尝试累计 564.905 秒，日志链与产物摘要复核通过 | matrix-4a4aeaded47b4986b4d3a64fba742a7b |
| .venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all | 631 passed、1 skipped，677.55 秒，退出 0 | all-ea097fe0d85a4a6e8a68f3a1febe6fce |

单测根目录为 .run/coding-agent-validation，评测为 .run/coding-acceptance，验收侧为 .run/coding-dataset-validation。pytest 结果和实际调用保存在各目录的 pytest-result.json / invocation.json；评测保留 manifest.json、starts.jsonl、attempts.jsonl、metrics.json 及产物。acceptance 运行末尾补充了回执对沙箱/宿主客户端源码的摘要覆盖，最终 all 复验该增量。

完整回归唯一跳过是 tests/unit/test_local_file_ranges.py:71：`当前 Windows 环境未授予创建真实符号链接权限`。这项既有环境限制没有被当作通过，也没有为本轮增加跳过；Windows 重解析点的拒绝逻辑及其他实际隔离检查由相应直接测试覆盖。

完整回归的 pytest-result.json 记录 business_modules_loaded=[]，平台 Windows-11-10.0.26200-SP0，Python 3.12.13；测试未导入生产业务配置入口。筛选过的直接测试只用于定位问题，随后 acceptance / all 包含完整的 11 个隔离用例。

验收侧 qualification.json 的 SHA256 为 ab2850d3046df93e8df83de5c05af2911ec7e27335249763c3dd5c59b321305b；其 blind_quality_eligible=false，contamination.json 中登记了全部公开题。120 次控制通过只证明初始失败、参考实现成功、固定错误对照被拒绝、用户文件保护机制有效。未将空保管人、空来源摘要、未确认独立性的 custody-template.json 作为正式回执。

两套 control 均 30/30、两套指定 matrix 均 15/15；外部隔离运行的 runner_errors=[]、isolation.verified=true，开始和结束摘要核对通过。它们的 coding_denominator=0、independent_completed=0、delivery_decision=blocked、experiment_complete=false，未把回环校准转为正式质量决议。耗时列仅汇总尝试内计时；准备工具及尝试之间的身份复核另计。

预检反例实际执行：

~~~powershell
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode preflight --catalog .run/s6-phase-b-remaining-5c4f64b2ba234de7b64a67d1db361f78/synthetic-formal-preflight/catalog.json --isolation appcontainer --tasks PY01
~~~

观察为退出 1；isolation.verified=true，唯一缺项 independent_curator_receipt_and_unexposed_holdout，starts.jsonl 长度 0、started=0、coding_denominator=0。证据目录 preflight-fdd171a83616438c83819c11d1902c4f。该清单是公开题复制出的拒绝测试，不是正式题集，未执行质量尝试。旧 control、旧 matrix 和该反例的日志链、产物摘要均另行只读复核，delivery_decision=blocked、experiment_complete=false。

以下静态检查实际退出 0：

~~~powershell
.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check
.venv/Scripts/python.exe -B scripts/check_agent_v2_imports.py
.venv/Scripts/python.exe -B -m ruff check scripts/coding_acceptance_catalog.py scripts/coding_acceptance_dataset.py scripts/coding_acceptance_evidence.py scripts/coding_acceptance_isolation.py scripts/coding_acceptance_judge.py scripts/coding_acceptance_pytest.py scripts/coding_acceptance_schema.py scripts/coding_acceptance_transport.py scripts/run_coding_acceptance.py scripts/run_coding_validation.py src/private_agent_local/windows_sandbox.py tests/coding_acceptance/test_s6_custody.py tests/coding_acceptance/test_s6_isolation.py tests/unit/test_windows_sandbox.py
git diff --check
~~~

测试统一使用新 UUID 目录及合成数据；模型服务为本机确定性回环，不读取生产配置、生产数据库、真实账号凭据或日志。真实宿主 / 命名管道在获准的常规执行权限下运行，保留工具沙箱环境限制及失败记录。AppContainer 是被测产品边界，未以 trusted_project 降级替代。

### 开发期间的失败与修正

这些是本轮实际失败，保留在独立目录，未覆盖为后续成功记录。最终成绩取上表所列的新运行。

| 失败位置 | 观察与修正 |
| --- | --- |
| 初期 isolation 直接测试 | UV 解释器入口为链接；复制前解析已安装运行时，复制结果逐文件拒绝链接/重解析点。Vue 的全局路径解析和 Rust 的路径、临时目录也在原生隔离中失败，随后改为专用工具副本与容器临时目录。 |
| control-069780e69f9847c2a678c34bd8525e94 | 三语言 0/3：Python 缺 py.py 兼容入口、Node 子测试进程超时、Rust 临时目录失败。补齐已有依赖的副本，并限定公开 Node 测试同进程执行。 |
| control-0e551ae96245443cbfdeb80a99b5dda7 | 三语言 1/3，Vue 通过；Python pytest 收集越过项目父目录、Rust 缺 rustdoc。补充收集边界适配和现有 rustdoc 副本，保留普通测试及 doctest。 |
| isolation-5ca3926580814336b9a7d96f2be02d04 | 10 passed、1 failed；曾尝试的 pytest namespace 收集方式丢失根 conftest fixture，未采用该方案。最终测试同时要求根 fixture 可用及失败断言仍失败。 |
| 早期 Agent IPC 探针 | 临时 HOME 覆盖触发产品能力预检失败，已撤回；越界读取产生的真实终态/错误码独立保存。权限验证不再依赖把刻意失败的读取解释为功能任务成功。 |
| 实际租约核对 | 发现 python.cmd 被额外授予当前解释器目录，按 B-03 收紧运行时根解析；判定工具和 Agent 工具再分开，防止下一次 Agent 读取先前观察程序。 |
| isolation-c512d25ecda549a396af52cbcbee0c5c | 10 passed、1 failed；读取权限符合预期，但证据收集遗漏 records 下的账号目录，导致租约集合为空。修正实际路径匹配后，直接 IPC 测试及最终 acceptance / all 均通过。 |

另有早期 Ruff 导入顺序检查失败，已在涉及文件内修正并实际复验通过。没有删除断言、缩短题集、扩大 AppContainer 权限、降级执行模式或提高配额以绕过失败。

只读证据定位也曾失败：一次查询了不存在的 observations 目录，一次 check_evidence.py 路径中的 UUID 抄写错误，返回 `No such file or directory`。改用已落盘的 pytest-result.json 和正确目录后核对成功；两次均未修改实验记录，不归为产品测试失败。

## 隔离证据与限制

此前可信模式的负向证据保持有效：工作区外的材料仍可被同用户可信命令读取，日志也可出现合成标记。新增后端使用独立 AppContainer 令牌和专用工具目录，实际探针同时检查公开文件可读、保护材料不可读写、零 capability、两个预期授权目录及进程退出。Agent 工具副本不包含验收侧观察程序；参考及期望值留在验收父进程。判定原始输出不进入 Agent 日志或公开 verdict。

权限探针故意包含一次越界读取工具请求。其实际 run_status、run_error_code 单独保存；权限 verified 只表示令牌、访问及授权范围符合要求，不将可能出现的 output_validation_failed 改写为功能任务成功。

全量隔离 control 的 manifest.json 中保存了以下直接事实：

| 证据 | 观察结果 |
| --- | --- |
| Agent 实际命令 | execution_mode=restricted、network_policy=none；宿主进程 exited、error=null |
| 实际访问令牌 | Agent 与判定侧均 appcontainer=1、capabilities=0，各自身份摘要已记录 |
| 读取工具 | 公开题面可读，越界读取被拒 |
| 保护材料 | Agent 对验收 JSON、判定器、题集验收工具及判定侧观察标记四项均不可读写；判定侧对前三项也不可读写 |
| 实际临时授权 | 仅 agent-probe/project 可写、tools/a/p 可读；grant_scope_verified=true |
| 探针运行与权限分开 | 实际 run_status=completed、run_error_code=output_validation_failed；由刻意无效读取形成，不充作功能成功记录 |

宿主 SHA256 为 91eb573430edf660bdc247a3e1cae918bb2d153e795a07061a691f7f48e65f7a。租约、事件、执行记录、探针源文件及保护材料均关联摘要；上述操作只尝试打开保护文件，未改写文件内容。

本轮发现 python.cmd 名称会触发开发解释器目录的额外授权，因直接阻碍 B-03，做了四行范围收紧；仅新批处理语义变化，原生 Python 和虚拟环境路径保留。依赖未声明外部运行时的自定义批处理可能被拒绝。没有创建系统账号或修改全局授权策略；初期探针沿旧产品路径产生的临时解释器授权随租约回收，最终后端以实际租约检查确保只授权专用副本。

工具副本、宿主、判定代码、任务、候选及控制记录均有关联摘要。摘要验证不能证明保管人员身份或来源真实性。新登记的污染需要独立保管方交接最新版本，离线旧副本无法自动发现外部污染事件。固定 wrong 对照和公开取巧反例不构成任意恶意实现的完备证明。

当前只验证本机 Windows AppContainer 与已安装工具链；pytest 适配依赖其当前接口，Node 公开测试在同进程执行，Rust 保留普通测试和 doctest。未验证新安装包、干净机器、多平台、真实模型质量或桌面 UI；这些没有被算作 B 的本轮工具成绩。

## 项目记忆与工作区保护

已读根 AGENTS.md、docs/project-state.md、总体路线、后续计划阶段 B、阶段 A 及首次 B 报告，未发现下级 AGENTS.md。项目记忆中的旧环境与当前 F 盘源码有时间和环境差异，按 Git、源码及本轮运行证据核对，不把旧状态冒充当前事实。

依用户明确约束，不自动改写 docs/project-state.md。持久接口、权限边界与已知限制同步到阶段 B 契约、测试说明和阶段文档。开工摘要位于 .run/s6-phase-b-remaining-5c4f64b2ba234de7b64a67d1db361f78/baseline.json，原文件在 before/；该目录被 Git 忽略，不能假设跨机器存在。按摘要核对，本轮增量为上表 20 个文件，另外 19 个已有改动文件及 docs/project-state.md 均保持原样。

已检查完整增量、Git 状态及暂存区，未新增暂存内容。六份变更文档的 145 个仓库链接均有效。另按开工快照比较 AST：TERMINAL、TERMINAL_EVENTS、events、control、poll_run、run_failure、event_integrity 保持一致；传输模块只有 RuntimeClient.__init__ 变化。阶段 A 的终态、取消、迟到回执、事件检查及副作用处理没有改写，实际回归结果见上表。

## 剩余退出条件与操作

1. 独立验收方准备并保管有可核对来源、许可、初始版本的正式 30 题，Python / Vue-TypeScript / Rust 各 10、development 18 / holdout 12、六分类各 5。不得复用本会话生成、已公开或已用于 Agent 调试的保留题。
2. 验收方按契约运行 qualify，独立审查代表性及取巧反例；保留原始控制证据，填写并交接新的 receipt.json 和独立核对的 SHA256，不向 Agent 提供隐藏答案。
3. 在正式材料所在环境运行 --mode preflight --catalog <正式清单> --isolation appcontainer --custody-receipt <回执> --custody-sha256 <已核对SHA256>，复核直接权限证据和版本关联后重新判断 B 退出条件。预检不启动 C 的真实模型联调。

这些输入尚未具备，所以阶段 B 完整验收与 M3 继续 blocked。本轮完成已授权技术工作后停止，不自动进入 C～F。
