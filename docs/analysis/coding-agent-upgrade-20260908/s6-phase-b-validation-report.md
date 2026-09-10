# 阶段 B：外部题集、独立判定与证据交付记录

> 本文保留阶段 B 首次交付的实现、测试和隔离缺项，不是后续补充开发的新成绩。2026-09-10 的 AppContainer 后端、独立题集交接及最新退出核对见 [阶段 B 补充验收记录](./s6-phase-b-remaining-report.md)。用户已确认尚未准备独立保留题；原始失败和阻断原因保留作为当时证据。

日期：2026-09-10（Asia/Shanghai），本轮从 2026-09-09 开始。工作区 F:\Program\Agent，分支 dev/1.0.0，HEAD 25ba4d3。范围限 [后续开发计划](./s6-follow-up-development-plan.md) B-01～B-05；没有进入 C～F、提交、推送、打包或部署。

**退出结论：工具开发与本轮自动化验证完成，阶段 B 完整验收不通过。** 外部 JSON、独立比较与证据工具及公开样例已经实现；尚无独立未污染保留题和可保护验收材料的独立执行环境。最终 S6 acceptance 为 241 passed，完整隔离回归为 590 passed、1 项既有权限跳过，旧接口为 106 passed；新旧 control 各 30/30、新旧 matrix 各 15/15。本报告将工具验证与阶段退出分开，不降低原退出条件。本轮完成交付后停止。

## 工作项与验收边界

| 工作项 | 实施结果 | 完整验收状态 |
| --- | --- | --- |
| B-01 | 标准库实现严格 JSON schema；验证完整必填集合、来源/许可、语言/分类/分组、内容 revision、逐文件摘要、命令、预算、目标与行为；拒绝未知/重复字段和路径别名，无外部 Python 配置导入 | 工具完成 |
| B-02 | 外部加载、依赖预检、全新工作区重建、独立判定、运行清单及开始/结束核对贯通；旧 Namespace、control、matrix 与打包 --s6 的调用方式兼容 | 公开外部管线完成；正式独立用途因隔离缺项在预检阻断 |
| B-03 | 工作区物化与验收材料分离；候选进程只接收输入，父进程比较期望值；抑制验收原始输出，核对判定器及候选前后摘要；正式 IPC 读取、命令身份和日志泄露探针 | 工具与正反探针完成；实际可信命令可读取外部材料，真实隔离条件不满足 |
| B-04 | 公开外部样例 30 题，Python/Vue/TS/Rust 各 10；18/12、六分类各 5；验证初始拒绝、参考通过、错误/固定答案拒绝和用户文件保护 | 公开样例完成；独立来源及未污染的 12 个保留题缺失，不能宣称正式题集通过 |
| B-05 | 启动前 fsync 留痕，追加式尝试及摘要链；计划决定分母，污染和身份改变不能提高成功数；题集、验收、运行器、产品及候选快照关联；审阅不改写原记录 | 工具完成；公开校准和部分任务保持正式实验及交付阻断 |

完整字段、固定判定接口、命令与统计定义见 [阶段 B 契约](./s6-phase-b-contract.md)。当前支持三个现有样例接口，不声明任意仓库通用判定能力。重构样例的旧片段约束只校准验收流程，不证明算法复杂度或真实大型项目代表性。

## 开工基线与范围审查

已完整读取根 AGENTS.md、docs/project-state.md、总体路线、阶段 B 和阶段 A 报告，并核对当前源码、测试和已有差异。未发现下级 AGENTS.md。开工已有 24 个已修改或未跟踪文件；它们及未修改项目记忆的 25 项摘要和相关原内容存于 .run/s6-phase-b-393c061cdb5a48458ed4620f34605e89/baseline.json 和 before/，用于本轮增量审查。该目录被 Git 忽略，不保证跨机器存在。

阶段 A 的历史成绩 128 passed、477 passed/1 skipped、106 passed 是开工输入。本报告下面列出的本轮命令和成绩独立记录，不把历史成绩当成本会话执行结果。没有修改阶段 A 的传输模块或两份原专项测试，没有修改产品运行时、前端、Rust 宿主、协议生成物、依赖、锁文件或项目 Git 状态。

## 实际变更文件

下面仅列本轮在开工基线上的增量，共 16 个文件；部分脚本在 Git 中本来就是其他会话留下的未跟踪文件。

| 文件 | 本轮内容 |
| --- | --- |
| [coding_acceptance_schema.py](../../../scripts/coding_acceptance_schema.py) | 新增严格清单、验收数据、摘要及路径契约 |
| [coding_acceptance_judge.py](../../../scripts/coding_acceptance_judge.py) | 新增三语言观察程序、独立比较、权限探针、输出抑制及篡改检查 |
| [coding_acceptance_catalog.py](../../../scripts/coding_acceptance_catalog.py) | 增加外部入口，复用重建/执行并强化链接与输出配额处理 |
| [run_coding_acceptance.py](../../../scripts/run_coding_acceptance.py) | 贯通外部源、逐题预算、启动日志和冻结绑定，保留六终态与单次取消 |
| [coding_acceptance_evidence.py](../../../scripts/coding_acceptance_evidence.py) | 增加追加账本、冻结分母、污染处理与正式实验完整性条件 |
| [coding_acceptance_review.py](../../../scripts/coding_acceptance_review.py) | 审阅验证摘要链、启动记录和候选产物绑定；保留旧证据审阅边界 |
| [run_coding_validation.py](../../../scripts/run_coding_validation.py) | 新增 external 直接套件，并纳入 acceptance/all |
| [test_s6_external.py](../../../tests/coding_acceptance/test_s6_external.py) | 新增清单、30 题正负控制、链接、配额、Unicode、IPC 泄露和账本测试 |
| [catalog.json](../../../tests/coding_acceptance/external_public/catalog.json) | 新增 s6-external-public-1 的题面、初始文件与公开测试 |
| [assessment.json](../../../tests/coding_acceptance/external_public/assessment.json) | 新增单独的公开参考实现与验收材料；明确已暴露 |
| [测试入口 README](../../../tests/coding_acceptance/README.md) | 增加直接测试与外部样例说明 |
| [阶段 B 契约](./s6-phase-b-contract.md) | 新增实际字段、隔离边界、统计及调用说明 |
| [本报告](./s6-phase-b-validation-report.md) | 新增本轮实施、失败过程、验证与未完成条件 |
| [S6 评测协议](./s6-acceptance-protocol.md) | 链接阶段 B 新契约，保留原公开校准和阶段 A 内容 |
| [后续开发计划](./s6-follow-up-development-plan.md) | 追加阶段 B 状态入口，保留原退出条件和历史证据 |
| [总体路线](./README.md) | 增加本轮报告入口及正式验收仍阻断的边界 |

## 测试环境与失败修复

使用现有 Python 3.12.13、Vue/TypeScript/SSR 和 Rust/MSVC 工具链，不安装依赖。测试由既有隔离入口创建 UUID 目录，禁用仓库 conftest、自动插件和业务配置导入；所有产品数据库均为新建合成 SQLite，模型仅用回环替身。旧接口入口沿用专门的固定测试配置与网络守卫，不读取生产配置或连接生产数据库。

本轮实际失败及处理：

1. 首次 external 为 80 passed、22 failed。新判定器未创建 TEMP/TMP 指向的目录，Python 警告混入结构化输出，Rust 链接器不能创建临时文件；修复为每个判定区明确创建临时目录。首次 IPC 用例另被工具沙箱阻止执行宿主启动。
2. 经正常审批在常规权限复跑后为 101 passed、1 failed。合成命令探针使用了被现有策略拒绝的内联代码/绝对程序名；依次改为项目 probe.py 和已登记的 python 后，单项直接复验通过。没有绕过产品策略或放宽断言。
3. 旧接口首次在默认工具沙箱为 103 passed、3 failed，均为命名管道 WinError 5；常规权限重跑 106 passed。保留首次失败，不把权限不足计为通过。
4. 第一轮外部 control 为 21/30 系统行为通过；9 个已启动 Rust 失败均保留。真实 Cargo 在 target 内生成内部硬链接，新快照检查误拒绝；核对文件身份和全部链接位置后，仅允许完整位于工作区生成目录的内部链接，仍拒绝源码/外部硬链接和重解析点。两项直接测试及 RS01、RS09 正式 IPC 定向复验通过。
5. 追加的中文/emoji 公开探针复现：Python -I 忽略环境 UTF-8 设置，参考实现输出失败。观察进程增加显式 -X utf8 后直接测试通过；最终候选重新执行相关验证。

既有回归跳过与最终完整结果已单独核对，不以上述中间成绩代表最终状态。唯一跳过仍为 tests/unit/test_local_file_ranges.py:71：当前 Windows 环境未授予创建真实符号链接权限；新增的实际 Windows junction、内部/外部硬链接检查均通过，没有将该跳过记为成功。

## 本轮验证记录

持久入口在仓库根执行：

~~~powershell
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite external
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite acceptance
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all
.venv/Scripts/python.exe -B scripts/run_coding_legacy_validation.py
.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check
.venv/Scripts/python.exe -B scripts/check_agent_v2_imports.py
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode control
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode matrix --tasks PY01,PY09,PY10,VT07,RS01
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode control --catalog tests/coding_acceptance/external_public/catalog.json
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode matrix --catalog tests/coding_acceptance/external_public/catalog.json --tasks PY01,PY09,PY10,VT07,RS01
.venv/Scripts/python.exe -B -m ruff check scripts/coding_acceptance_schema.py scripts/coding_acceptance_judge.py scripts/coding_acceptance_catalog.py scripts/coding_acceptance_evidence.py scripts/coding_acceptance_review.py scripts/run_coding_acceptance.py tests/coding_acceptance/test_s6_external.py scripts/run_coding_validation.py
git diff --check
~~~

下表为实际观察并核对的结果。最终环境为 Windows-11-10.0.26200-SP0、Python 3.12.13；未执行的行为不计作成功。

| 检查 | 已观察结果 | 证据 |
| --- | --- | --- |
| external 直接套件 | 109 passed；之后新增边界以直接筛选及最终 acceptance 覆盖 | external-f79d849c0e9d464aa22ff5a67954d7d0 |
| 启动/污染/候选换绑直接检查 | 3 passed、108 deselected | b-direct-5c03246f0abf46aaa787e2cfa3d6e275 |
| 内部/外部链接直接检查 | 2 passed、110 deselected | b-direct-5137a9e862aa4615985094ef6321b8d0 |
| Unicode 修复直接检查 | 1 passed、112 deselected | b-direct-800b1967342e41dfb0c8460f3ce04c94 |
| 正式 IPC 合成权限探针 | 1 passed、101 deselected | b-direct-ee39f0642dff4108b456274d490b68a5 |
| 旧接口最终复验 | 106 passed，6.07 秒 | legacy-29d32ca9cb9e4084993f0bbf0a064fdf |
| 最终 S6 acceptance | 241 passed，111.43 秒 | acceptance-d1e92832cfe64541b002deaf22d0fd30 |
| 编码修复前完整回归 | 589 passed、1 项既有权限跳过，364.29 秒；最终版本另行复跑 | all-dff1b05df27646158e0198d83decbd01 |
| 最终完整隔离回归 | 590 passed、1 项既有权限跳过，364.88 秒，退出 0 | all-3181c6e8cdbb42498fd27469b5dd324c |
| 协议生成 / 导入边界 / Ruff | 全部退出 0 | 命令输出及本轮审查记录 |

上述直接套件证据位于 .run/coding-agent-validation/。本机 direct.py 只复用既有隔离守卫进行 -k 筛选；deselected 不是从 acceptance/all 跳过测试。直接命令为：

~~~powershell
.venv/Scripts/python.exe -B .run/s6-phase-b-393c061cdb5a48458ed4620f34605e89/direct.py actual_ipc
.venv/Scripts/python.exe -B .run/s6-phase-b-393c061cdb5a48458ed4620f34605e89/direct.py "ledger or contamination or rebound"
.venv/Scripts/python.exe -B .run/s6-phase-b-393c061cdb5a48458ed4620f34605e89/direct.py "hardlink or directory_link"
.venv/Scripts/python.exe -B .run/s6-phase-b-393c061cdb5a48458ed4620f34605e89/direct.py isolated_python
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode control --catalog tests/coding_acceptance/external_public/catalog.json --tasks RS01,RS09
~~~

最终判定器的新旧入口校准（证据位于 .run/coding-acceptance/）：

| 入口 | 结果 | 逐次耗时合计 | 证据目录 |
| --- | --- | --- | --- |
| 外部 JSON control | 30/30，退出 0 | 156.812 秒 | control-4e5f65ad1ffa4178831e2facc29171ce |
| 旧 fixture control | 30/30，退出 0 | 156.062 秒 | control-52a146ad4dae409f83238a3d11a31d34 |
| 外部 JSON matrix | 15/15，退出 0 | 71.453 秒 | matrix-ba66efe521ac4f16bc60707e45ee5cf0 |
| 旧 fixture matrix | 15/15，退出 0 | 71.174 秒 | matrix-8f84fa48c9e44455b7e9f38e404504ca |

四组实验均独立核对 manifest、starts、attempts 摘要链、产物/事件/diff 引用、候选快照与当前运行器摘要。真实模型调用为 false、编码质量分母为 0、正式实验完整性为 false、交付决议为 blocked；这些是公开校准系统行为成绩。

冻结题集版本为 s6-external-public-1。catalog.json 的 SHA256 为 533c6bc8973e22a4b4da2d9bb10176c8c800a6ba8223f6239a6b6d713fc201a3；assessment.json 为 49415efb5ba7f0697a939fced07b6f3451229e7effc5886d89cb849597d40fdb。文件内容、逐题摘要与运行器摘要还可从每个 manifest 和逐次记录交叉核对。

第一轮 external 与外部 control 的失败证据分别保留于 external-2b7d6ddc40384b6f8a5225259f87281f 和 control-73bc27048a4c40c0af43f3779aedbb3e。修复 TEMP 后的 101 passed/1 failed 为 external-d5da9d53b99945ec81884dc9a78471b2；探针绝对程序名被拒绝的直接记录为 b-direct-7af7717ec4a64a14a92242323ebb37a0。首次旧接口权限失败为 legacy-9b7407a21b7f4b859c37c7936b5a1062。

## 隔离、保留题与未完成条件

实际 IPC 探针的合成标记位于任务工作区外：读取工具拒绝 ../ 越界，工作区内公开文件正常读取；获批 trusted_project 命令能读取外部标记，命令结果日志包含标记。whoami 用户身份结果仅保存摘要，与验收探针一致；没有输出真实用户名、凭据或生产日志。直接证据是测试目录内 ipc-isolation.json；它证明当前同身份执行**不具备所需材料隔离**，不能包装成隔离通过。

独立比较器的正反测试证明期望值不进入生成的观察程序、原始候选验收输出不进入公开结果，并拒绝持久修改观察程序、验收 JSON 和候选输入。它不证明当前用户运行的恶意代码无法通过其他路径访问文件、进程或网络，前后摘要也不能替代 OS 隔离或独立审阅。

未完成条件保持原要求：

- 独立来源和许可可核对的正式题集，尤其是未在本会话生成、调试或暴露的 12 个保留题，以及验收侧的独立正负控制回执。
- 与实际 Agent 命令身份隔离的验收账号/机器或受审查的执行后端；取得材料不可读、不可改、命令和日志不泄露的正反证据。当前运行器的同身份路径只放行公开校准，正式用途预检明确阻断，不能仅改 JSON 标志启用。
- 在这些前提具备后重新核对阶段 B 退出条件。本轮不会自动进入 C 的真实模型联调或 D～F。

本轮工具和公开样例可以使用；阶段 B 完整验收仍不通过，M3 保持 blocked。未执行真实模型质量实验、原生桌面验收、新安装包验证、600 秒持续命令复验、安装升级或生产发布。

## 项目记忆与交付核对

已读取 docs/project-state.md，确认其日期为 2026-08-31、工作区为 E:\Program\Agent、HEAD 为旧快照。本轮 Git 确认为 F:\Program\Agent、25ba4d3；两者是不同时间环境的记录。按用户明确约定，未改写该文件日期、状态或历史结论，也未建立新的记忆体系。

本轮持久事实写入阶段 B 契约、验证报告及原路线/协议入口。已按开工摘要核对所有未涉及文件、阶段 A 原实现、完整增量 diff、文档链接、四组最终校准证据及 Git 状态：9 个既有文件修改、7 个新增，开工其他 15 个改动文件及项目记忆摘要保持不变。未引入无关源码修改、依赖或锁文件改动、凭据、调试产物或新的记忆体系。

审查材料位于 .run/s6-phase-b-393c061cdb5a48458ed4620f34605e89/phase-b.diff 和 final-review.json，均为本机忽略文件。完整审查命令实际执行：

~~~powershell
.venv/Scripts/python.exe -B .run/s6-phase-b-393c061cdb5a48458ed4620f34605e89/final_review.py control-4e5f65ad1ffa4178831e2facc29171ce control-52a146ad4dae409f83238a3d11a31d34 matrix-ba66efe521ac4f16bc60707e45ee5cf0 matrix-8f84fa48c9e44455b7e9f38e404504ca
~~~

所有已有授权且不依赖独立保留题/隔离环境的阶段 B 工作已交付。用户如需阶段 B 完整退出，仍需准备上述独立题集和隔离验收条件，再进行针对这些缺项的验收；本次工具使用无需提交、部署或修改系统账号权限。
