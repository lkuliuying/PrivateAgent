# 阶段 B：外部题集与独立判定契约

日期：2026-09-10（Asia/Shanghai）。范围限 B-01～B-05，承接阶段 A 的六种终态、单次取消及连续事件检查。本文说明实际工具契约，不表示正式盲评或 M3 通过。

## 入口与来源

旧入口省略新参数时继续加载固定的公开 Python fixture；外部入口只解析 UTF-8 JSON，不接受模块名、Python 配置、判定器脚本或任意验证命令。

在仓库根执行：

~~~powershell
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode preflight --catalog tests/coding_acceptance/external_public/catalog.json
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode control --catalog tests/coding_acceptance/external_public/catalog.json
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode matrix --catalog tests/coding_acceptance/external_public/catalog.json --tasks PY01,PY09,PY10,VT07,RS01
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite external
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite isolation
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite custody
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode control --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer
.venv/Scripts/python.exe -B scripts/coding_acceptance_dataset.py qualify --catalog tests/coding_acceptance/external_public/catalog.json
~~~

--catalog 为本地 JSON 路径。--tasks 只选择清单内的唯一 ID，重复、未知或空 ID 拒绝。运行器保持原 Namespace 调用兼容，打包验证的 --s6 无需增加参数。每次运行新建 UUID 目录，不复用以前的产物、审批或尝试。

当前提供的 [catalog.json](../../../tests/coding_acceptance/external_public/catalog.json) 和 [assessment.json](../../../tests/coding_acceptance/external_public/assessment.json) 是 CC0-1.0 公开合成样例，由既有 s6-calibration-1 改编。Python、Vue/TypeScript、Rust 各 10 题，每类语言 6 个 development、4 个 holdout；bug、feature、refactor、long_context、recovery、boundary 各 5 题。**这里的 holdout 只是分组标签，所有题目均已公开、用于本轮调试，不能作为正式未知保留题。**

## 严格 JSON 结构

所有层级拒绝未知字段、缺失字段、重复 JSON 键与非有限数值。顶层、任务及验收材料必须符合下面的完整字段集合；本文表格不表示可以省略字段。

| 顶层字段 | 类型与约束 |
| --- | --- |
| schema_version | 整数 1，布尔值不视为整数 |
| version | 非空版本标识，最长 120 字符 |
| purpose | public_calibration 或 independent_evaluation |
| repetitions / quality_target | 固定整数 3 / 浮点数 0.8 |
| budget | 下述完整预算对象 |
| tasks | 30 个唯一任务，满足语言、分类及分组分布 |
| assessment | 仅有 path、sha256：相对清单目录的验收 JSON 路径及原始字节 SHA256 |

| 任务字段 | 类型与约束 |
| --- | --- |
| id | 字母起始，后续为字母、数字、下划线或连字符，最长 64 字符；大小写冲突也拒绝 |
| source / license / title | 非空来源、许可、题目标题；来源声明本身不证明独立性 |
| family | python、vue-typescript、rust |
| category / split | 六种分类之一；development 或 holdout |
| source_revision | 初始文件映射的摘要：Python json.dumps(files, sort_keys=True, ensure_ascii=False) 的 UTF-8 SHA256，与既有重建版本算法一致 |
| files | 相对路径到 UTF-8/LF 文本的映射；必须包含题面 README.md 和保护文件 user-notes.txt |
| file_sha256 | 与 files 键集合完全相同，逐文件 UTF-8 内容的 SHA256 |
| editable_files | 非空、唯一且已经存在的 src/ 文件；不能修改测试、题面或用户保护文件 |
| validation_command | Python 为 ["python","-m","pytest"]；Vue 为 ["npm","test"]；Rust 为 ["cargo","test","--offline"] |
| judge_contract | 分别为 python-response-v1、vue-ssr-v1、rust-vector-v1 |
| coding_goal | 严格布尔值，独立于任务是否预期受阻 |
| expected_system_behavior | verified_change 或 blocked_without_write |
| scenario | normal、deny、pause_resume、failure_then_fix；deny 与受阻预期必须一致 |
| holdout_exposure | public_calibration、unexposed、contaminated；公开用途只能声明 public_calibration |
| budget | 完整预算对象，不得高于题集总配置 |

预算字段为 max_model_requests、max_tool_calls、max_active_seconds、max_attempt_tokens、max_total_tokens、cost_usd。前五个必须为正整数，上限依次为 24、48、600、120000、10800000；总 token 配额不能低于单次配额。费用计量尚不能作为硬预算，cost_usd 必须为 null。每题请求、工具、活动时长传给现有运行时；评测 token 观察使用该题配额，保留阶段 A 的单次有界取消。

清单及验收文件各不超过 8 MiB；每个文件映射至多 1000 项、内容至多 8 MiB。拒绝目录穿越、绝对路径、反斜线、驱动器/ADS、空路径段、Windows 保留设备名、尾点/空格、大小写或父子路径冲突、符号链接、重解析点及多链接文件。初始文件不能占用 .git、target、__pycache__、node_modules、环境配置或运行器生成的 .s6-tools.json。

## 验收侧与工作区

验收 JSON 顶层仅有 schema_version: 1 和 tasks。任务 ID 集合须与清单完全一致，每项字段如下：

| 字段 | 内容 |
| --- | --- |
| cases | 1～100 个 [输入, 期望输出]；Rust 只支持有界 i64 向量 |
| exception_cases | 至多 20 个 {input, error}；当前只支持 Python ValueError、TypeError |
| reference_files | 与可修改文件集合完全一致的参考实现 |
| forbidden_fragments | 可编辑文件上的旧实现片段禁留约束，每文件至多 20 项；是重构样例的附加约束，不能代替功能判定 |
| timeout_seconds / output_bytes | 大于 0 且不超过 30 秒；整数 1～64000 字节 |

当前三种固定契约复用现有样例接口：Python src.service.respond，feature 类别返回 items、其他返回 result；Vue 执行 TypeScript 编译和真实组件 SSR；Rust 执行 src/lib.rs 导出的 solve，feature 使用 evaluate。不声明支持任意仓库接口。扩展契约需新增受审查的代码及测试，不能通过外部配置导入 Python 模块。

重建仅物化 files。Vue 另生成公开 .s6-tools.json 以定位当前已安装编译器；Rust 沿用已有工具链配置及离线锁文件；保护场景沿用独立题目目录中的 intent-to-add。运行前快照记录这些环境相关文件，原始文件摘要和实际物化摘要分别保存，不把不同机器的工具路径说成同一文件摘要。重建只接受全新目录。

初始清单禁止提供 .cargo 配置；已有 Cargo.lock 原样保留。快照允许 Cargo 在生成目录内部复用硬链接，但会按文件身份和链接总数核对全部链接都位于该工作区生成目录。源码硬链接、生成目录指向外部的硬链接以及所有重解析点仍拒绝。

外部题的初始工作区只包含公开材料。public_calibration 的 control/matrix 会把验收侧的参考实现交给确定性替身，因此这些运行必然是已污染的公开校准。independent_evaluation 明确拒绝 control/matrix 及参考脚本注入；它的正负控制必须使用验收侧 qualify，quality 的候选模型不使用参考脚本。

候选执行子进程只取得测试输入与固定观察程序，预期结果由父验收进程比较。Rust 编译和执行共用一次时长上限。结束后核对候选快照、观察程序、判定器和验收 JSON 摘要；候选修改验证输入、用户文件或判定材料即失败。进程使用既有 Job/进程组回收。报告仅返回状态、配额原因及摘要，不输出隐藏输入、期望值、候选 stdout、命令正文或异常正文。

## 隔离结论与正式门禁

当前 trusted_project 命令继承当前用户的文件访问权。将参考材料移动到工作区外、清除环境变量、只允许固定测试命令，都不足以证明其不可读取；测试脚本仍能执行代码。

预检执行合成权限探针，记录执行身份摘要、实际打开材料文件的结果和系统报告的写访问状态。探针范围标为同继承身份的运行器子进程；单独的正式 IPC 测试核对该身份与 Agent 可信命令身份一致。读取工具的路径拒绝、可信命令可以读出外部合成标记、命令日志可含该标记，是分别验证的事实。探针不读取业务配置、账户信息或生产日志。

--isolation appcontainer 使用现有 exec-host、AppContainer 零 capability 令牌和可恢复 SandboxLease。每次实验复制本机已安装的三语言工具，不安装依赖。Agent 工具副本与判定工具副本分开；只有判定侧副本包含观察程序。单次命令授权当前工作区写入、该侧工具副本读取，结束后回收进程树、应用容器配置与租约。它创建的是临时应用容器标识，不是系统用户，不授权系统盘、用户根目录或共享开发运行时。

为落实这个边界，windows_sandbox.runtime_roots 不再因 python.cmd / python.bat 的名字追加当前 Python base_prefix；原生 .exe 及已有虚拟环境目录解析保留。依赖其他目录的自定义批处理可能因此被拒绝，必须使用范围明确的工具副本，不能回退为 trusted_project。

预检分别运行判定侧令牌探针和实际 Agent IPC 读取/命令探针，核对 AppContainer=1、capabilities=0、公共文件可读、验收材料读写被拒、Agent 无法读判定工具中的材料、实际租约只有预期两个目录。读取保护材料只尝试打开并关闭，不修改内容；日志只保留权限结果和摘要。不能用清单自报 isolation_verified=true 放行。--bundle 仍沿原产品核验入口执行；若候选内的授权行为不同，真实预检拒绝它。

Python 副本包含已安装 pytest 及依赖，python.cmd 设置 --confcutdir=. 并加载受摘要保护的 s6_pytest_boundary：仅省略 pytest 对已知根目录父级的类型探测，正常收集测试及根 conftest，不跳过失败断言。该适配依赖本机已验证的 pytest 接口。Node 副本使用 preserve-symlinks 选项和 --test-isolation=none，公开 Node 测试在同一进程内执行；Rust 包含 rustdoc，Cargo 的 target 放在本次容器临时目录，仍执行普通测试和 doctest。LOCALAPPDATA 由 Windows API 定位并匹配容器临时目录，只用于定位，不读取用户配置。原始 HOME、APPDATA、测试数据库与记录仍指向新目录。

判定侧只执行候选文件的冻结副本，验收父进程比较预期输出。候选输出不回传 Agent，也不进入公开判定日志；观察程序、宿主、两侧工具、候选与材料分别核对摘要。时长上限针对候选命令，Rust 编译与运行共用判定预算；宿主通信额外有 5 秒等待边界，工具复制、授权和回收时间另计。输出超过配额时失败并回收所属进程树。前后摘要不能替代操作系统隔离或人员独立性。

正式预检同时要求 appcontainer 和 --custody-receipt / --custody-sha256。缺少实际隔离或独立题集回执时，记录预检未启动并保持阻断。用户已确认尚未准备独立保留题；现有公开样例不能通过改标签补足该条件。当前后端的支持范围为实际验证过的 Windows 和工具链，不声明任意平台、任意项目依赖或现有安装副本已经通过。

## 独立题集交接与污染登记

独立验收方在其保管的 30 题目录运行 coding_acceptance_dataset.py qualify。它先核对材料权限，然后对每题分别重建 initial、reference、wrong、protected 四个候选，产生 120 次有摘要链的启动/结束记录、逐次 verdict、qualification.json、contamination.json 和 custody-template.json。只有 reference 应通过；initial/wrong 的断言、程序或接口错误才能作有效反例，超时、输出超限、隔离失败或判定器变化不能算“正确拒绝”。protected 必须因用户保护文件改变被拒绝。

qualify 本身不证明人员独立或题目代表性。wrong 是固定契约的错误实现对照，不能代替独立验收方审查更多取巧实现。回执模板默认留空保管人、独立性说明和来源产物摘要，并将未调试声明设为 false，因此模板不能直接放行。公开校准的污染记录自动登记所有题目。

验收方保留整个证据目录，在新 receipt.json 中补齐模板，核对 prepared_at 时区、逐题来源/许可和 source_artifact_sha256，确认 not_used_for_agent_debugging。运行人员经独立交接核对 receipt.json 的 SHA256，并通过 --custody-sha256 固定它。JSON 字段和摘要只能证明交接内容一致；保管角色、来源真实性及未污染声明仍由独立人员审查负责。不得把本会话生成的合成测试回执提交为正式证据。

工具检查回执固定摘要、30 题完整控制、启动/结束链、候选/判定器/验收材料绑定、逐个判定产物摘要及无污染登记；已知公开样例的原文件内容即使更改任务 ID 或来源声明也拒绝。内容查重不是通用污染鉴定，修改几行公开题同样不能产生独立性。清单和判定器改变后必须重新资格验证及交接，不能复用旧回执。

污染后使用下面的入口写入新版本，原记录保留；source-sha256 必须是当前冻结版本。示例中的路径和摘要需替换为验收侧实际值：

~~~powershell
.venv/Scripts/python.exe -B scripts/coding_acceptance_dataset.py contaminate --source F:/Evaluation/contamination.json --source-sha256 <当前文件SHA256> --output F:/Evaluation/contamination-2.json --tasks PY09 --cause "保留题用于 Agent 调试"
~~~

新污染版本记录时间、任务、原因及前版本摘要；重复输出路径拒绝。使用新版本的回执无法继续盲评，运行中更新已固定回执或其引用也会导致摘要核对失败。登记流程要求保管方同步最新版本；旧版本离线副本无法自动得知外部发生的新污染事件。

## 统计与证据规则

统计版本为 s6-attempt-ledger-1：

1. 计划为每模型 30 题各 3 次。编码分母取**冻结计划中 coding_goal=true 且已启动**的 quality 次数；不读取事后被更改的行内分类。只有清单确实有 27 个编码目标时，完整计划的分母才可能为 81。
2. 预检、依赖或候选身份失败且尚未尝试启动的记录单列，分母为 0；它们会使完整实验不成立。preflight 成功仅说明所选预检成功，不是完整实验成功。
3. 发出可能产生副作用的 /agent-runs POST **之前**，将启动事实追加到 starts.jsonl 并 flush/fsync。启动回执丢失或父进程随后中断按“已经尝试启动、结果待确认”保守计入，不能当成预检未启动。
4. 已启动后的超时、预算结束、权限拒绝、模型/工具失败、取消、异常、人工介入和污染均保留记录。缺少结束行的启动记录进入失败分母，报告完整性失败；不重放启动、审批或工具。
5. attempts.jsonl 只追加，每行链接上一行摘要；同一尝试重复追加或重复启动拒绝。重跑生成新实验 UUID；不能覆盖原行，也不能用重跑替换首次实验。不同实验之间没有自动“选最好一次”的合并入口。
6. 清单、逐题内容、验收材料、运行器及判定器文件集合、产品身份、实际隔离探针与独立回执都绑定到冻结 schedule 和逐次记录。实际候选快照再生成候选摘要，与产物证据关联；事件、产物和 diff 各自记录摘要。
7. 开始、每次尝试之前及实验结束核对实际选中的题集和验收材料，结束核对不固定引用 s6_fixtures.py。题集或判定器改变后旧成绩不能与新版本关联。
8. 人工审阅核对原清单、尝试、启动日志及产物摘要，追加新审阅目录；不改写原记录。人工次数只能增加，公开或污染暴露状态不能被审阅改为未知。未核对自然语言真实性的结果不能算独立完成。
9. public_calibration 和 contaminated 不能贡献独立完成分子。公开题上的 quality 仅供诊断，其分母不产生正式质量决议。所有公开校准、局部矩阵及人工审阅继续输出 delivery_decision=blocked。

完整实验通过与 M3 通过仍是不同状态。阶段 B 的退出还要求独立来源及未污染保留题，工具验证和公开样例不能补足这些条件。最新实测、历史失败及剩余门禁见 [阶段 B 补充验收记录](./s6-phase-b-remaining-report.md)。
