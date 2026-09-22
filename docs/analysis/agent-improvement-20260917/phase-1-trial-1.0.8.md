# 第一阶段候选版 1.0.8：T01 完成验收修复

日期：2026-09-18。用户在 1.0.7 手工试用中反馈 T01 异常，并明确要求修复。范围仅为完成验收误阻塞、对应回归及新的本机候选安装包；第二、三阶段仍未实施。

## 1. 问题与修复范围

用户截图中原始要求为修改 app.py 和执行 python -m pytest -q，两项证据已通过，但验收记录扩展为 14 项。其中包含一条未登记的 PowerShell 请求，以及多条相同的历史证据过期提示。此前 1.0.7 随包冒烟只走读取、修改、测试的直接路径，遗漏了模型探查和错误工具尝试后的完成流程。

根因位于 private_agent_local/completion.py：全部命令尝试会自动追加为必过要求。未启动的 local_tool_rejected 和修复前正常结束的辅助读取，因而可以阻塞已经满足的原始目标。前端只显示验证消息，缺少命令名称时多条记录难以区分。

本次沿用公开 Requirement/RunOutcome、SQLite schema 7 和现有执行事件，不新增接口或依赖：

- 用户原始、追加、显式要求继续严格核验；诊断命令若由用户指定为验收目标，也仍需满足当前版本检查。
- local_tool_rejected 在没有 tool.started 且没有执行/文件/补丁事实时不生成额外义务。拒绝记录不删除，原始要求不会被删掉。
- 对应完成事件存在、进程正常退出、不是已分类测试、工作区摘要可用且执行未改变工作区的辅助命令，保留在执行审计中，不自动变成当前代码的验收条件。正常退出不被改写为业务验证通过。
- 按规范化命令查看最新尝试，同时保留该命令先前产生或无法核对的工作区副作用；后一次观察不能抹掉这些事实。
- 测试、未恢复的失败、未知结果和实际文件变化继续验收。修改后没有重跑的测试仍会过期，用户拒绝、禁止项和沙箱边界不变。
- 未通过的命令验证消息包含对应命令，便于对照执行过程。

## 2. 本轮实际文件

| 文件 | 本轮变化 |
|---|---|
| [completion.py](../../../src/private_agent_local/completion.py) | 区分辅助观察与验收义务，保留副作用和错误证据，补充命令定位 |
| [test_local_completion.py](../../../tests/unit/test_local_completion.py) | 新增 12 项回归：三种 T01 历史组合、辅助命令恢复、三种未恢复失败、脚本写盘、未知结果、重复命令副作用、显式诊断过期和显式命令拒绝 |
| [README.md](./README.md) | 更新用户反馈和修复入口 |
| [第一阶段细则](./step-1-intent-and-constraints.md) | 第 11 节记录缺陷与修复边界 |
| [S1 完成设计](../coding-agent-upgrade-20260908/s1-completion-and-verification.md) | 第 11 节同步现行审计与验收规则 |
| 本文 | 记录验证、产物与复测范围 |

构建前与 1.0.7 的 667 个产品输入逐项比较，仅 src/private_agent_local/completion.py 发生变化。仓库原有其他未提交内容保持；未创建提交、分支或发布。

## 3. 源码验证

以下套件均在仓库根目录实际运行 `.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite <名称>`。最后一次运行使用最终源码，退出码均为 0。

| 套件 | 结果 | 日志 |
|---|---|---|
| completion | 174 passed | .run/t01-fix-completion-final.log |
| local | 71 passed | .run/t01-fix-local-final.log |
| recovery | 38 passed | .run/t01-fix-recovery-final.log |
| execution | 19 passed | .run/t01-fix-execution-final.log |
| contracts | 15 passed | .run/t01-fix-contracts-final.log |

合计 317 passed。测试使用隔离 SQLite、合成项目和模型替身，不访问真实账号、生产数据库或付费模型。执行会话套件包含真实宿主及沙箱边界检查。

其他实际检查：

- `.\.venv\Scripts\python.exe -B -m ruff check src/private_agent_local/completion.py tests/unit/test_local_completion.py`：All checks passed!。
- `.\.venv\Scripts\python.exe -B scripts/protocol_codegen.py --check`：protocol codegen in sync: OK。
- `node F:/Program/Agent/apps/desktop/node_modules/vitest/vitest.mjs run src/features/coding/model/runOutcome.spec.ts src/features/coding/model/runProjector.spec.ts`：工作目录为 F:/Program/Agent/apps/desktop，24 passed。由现有 managed_process 包装，隔离环境和 120 秒超时；日志 .run/t01-fix-frontend-final.log。
- `node scripts/build-client.cjs --qa --preview-installer --version 1.0.8 --dry-run`：版本、独立候选身份和空更新端点符合预期。
- `.\.venv\Scripts\python.exe -B scripts/prepare_intent_trial.py --output .run/intent-trial-1.0.8/test-kit --version 1.0.8`：生成 14 项。100 个项目文件和采集器与 1.0.7 最终测试包逐字节相同，保留原测试标准。

红灯记录：新增回归首次为 7 failed、165 passed；其中 4 项重现错误判定，3 项指出错误消息缺少命令定位。修复后 173 passed；继续检查发现“同一命令先写盘、后无变化”的副作用保留边界，新增用例先得到 1 failed，补齐后最终 174 passed。失败记录分别保存在 .run/t01-fix-completion-red.log 和 .run/t01-fix-side-effect-red.log。

首次前端 npm 检查的工具调用未返回，已终止等待，不能计为通过；随后以有时限和进程回收的隔离启动器重新执行上述 Vitest，24 项全部通过。没有跳过、删除或放宽原有断言。

## 4. 构建与随包验证

以下命令从 F:/Program/Agent 实际执行，退出码均为 0：

| 命令 | 结果 |
|---|---|
| `.\scripts\build-client.cmd --qa --preview-installer --version 1.0.8` | exec-host、PyInstaller、Vue 类型检查/Vite、Tauri/NSIS 完成，生成新安装器；保留既有 Rust 未使用代码警告 |
| `.\.venv\Scripts\python.exe -B scripts/verify-unified-client.py --bundle .run/unified-client-ksRG2d --work-dir .run/intent-trial-1.0.8/packaged-validation --model-mode openai` | passed=true；合成账号、项目操作、命令审批、执行宿主和历史记录验证通过 |
| `.\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.8/verify-intent-package.py --bundle .run/unified-client-ksRG2d --area .run/intent-trial-1.0.8/intent-package-check-01` | 8/8 场景通过，覆盖 T01/T02/T03/T06/T07/T08/T13/T14 |

T01 使用新 sidecar 和真实 exec-host，启用持续执行契约、受限执行及命令审批：读取 app.py → 拒绝未登记的 Get-Date → 正常 PowerShell 读取与 Python 版本检查 → 真实 pytest 4 failed（退出 1）→ 修复文件 → 同一 pytest 4 passed（退出 0）→ 最终 verified。结果只有 app.py 和指定 pytest 两项要求；未登记请求保留审计且没有 tool.started。其他约束场景保持各自预期的 answered、unknown 或 blocked，不一律冒称 verified。

上述模型均为回环测试替身，不调用真实供应商，不读取用户应用数据库。源码测试和随包验证不等于安装副本或真实模型验收通过。T01 合成执行证据位于 .run/intent-trial-1.0.8/intent-package-check-01/T01-evidence.json，随包场景摘要位于同目录 verification.json。

交付目录：F:/Program/Agent/.run/intent-trial-1.0.8/delivery/

| 产物 | 用途 |
|---|---|
| [PrivateAgentCandidate_1.0.8_x64-setup.exe](../../../.run/intent-trial-1.0.8/delivery/PrivateAgentCandidate_1.0.8_x64-setup.exe) | Windows x64 候选安装器，30,828,726 字节 |
| [PrivateAgent-M1-TestKit-1.0.8.zip](../../../.run/intent-trial-1.0.8/delivery/PrivateAgent-M1-TestKit-1.0.8.zip) | 14 个独立项目和反馈材料，106 个条目，41,062 字节 |
| [README.md](../../../.run/intent-trial-1.0.8/delivery/README.md) | 安装和复测入口 |
| [SHA256SUMS.txt](../../../.run/intent-trial-1.0.8/delivery/SHA256SUMS.txt) | 7 个交付文件的校验值 |
| [build-info.json](../../../.run/intent-trial-1.0.8/delivery/build-info.json)、[source-manifest.json](../../../.run/intent-trial-1.0.8/delivery/source-manifest.json)、[validation.json](../../../.run/intent-trial-1.0.8/delivery/validation.json) | 构建身份、667 个来源摘要和验证汇总 |

安装器 SHA256：4a71309a2f0899bd1d0dd62322c1259b87c27db85c79f6220dd203b1c37a5144

测试 ZIP SHA256：057812342b0d8cb736876547c2b0adb391face65a05ef309a6214cc63105e074

构建来源：HEAD 1dde393e29f3dbacd3647d11834b39824ac8323f，dirty=true；原始构建目录 .run/unified-client-ksRG2d，来源集合摘要 ee892379924ed879556f821a9aee297fc442acbc8b0544877cc129981d5e28a8。交付时逐项复核 667 个来源未变化，ZIP CRC 和全部 106 个条目逐字节一致。

最终复核：7 个 SHA256SUMS 条目一致，14 项提示词基线保持不变，四份本轮文档共 70 个本地链接有效；git diff --check 退出 0。只读进程检查确认先前中断等待的结果投影测试没有残留进程。产物均在 Git 忽略的 .run 目录中，没有把二进制加入源码变更。

身份继续使用 PrivateAgentCandidate / com.personal-assistant.desktop.candidate，沿用候选数据命名空间。Get-AuthenticodeSignature 返回 NotSigned，这是本地未签名预览包，更新端点为空；未安装、上传、发布或修改正式更新源。

## 5. 复测步骤与限制

1. 退出正在运行的旧候选版，安装新的 PrivateAgentCandidate 1.0.8，确认窗口标题版本。
2. 将新版测试 ZIP 解压到新目录。选择其中 projects/T01，并创建新任务，沿用 CASE-SHEETS.md 中的原提示词和“替我批准”权限。
3. 如指定 pytest 命令要求审批，核对后批准；检查原测试 4 项通过、文件实际修复、整体任务通过，辅助工具记录仍能在执行过程中查看。
4. 优先复测 T01、T02、T03、T06、T08，再继续余下用例。记录版本号、用例编号、结果及失败截图。

旧任务终态不会被回写；此轮不自动安装、清理旧数据或重跑用户项目。测试包文件应使用新副本，避免已经修复的 app.py 导致没有新文件变化证据。

该规则不推断不同测试命令的覆盖关系，也不把普通脚本退出 0 当成任意业务断言成立；额外未恢复的测试失败和未知副作用仍会阻止 verified。用户截图中的每一条真实命令尚未逐条取证，本轮以确定性回归和随包合成场景核验已定位缺陷。真实模型行为仍需用户复测。

## 6. 项目记忆同步

已读取根 AGENTS.md、docs/project-state.md、第一阶段计划、1.0.7 交付记录和 S1 设计，并对照当前源码与构建来源。project-state.md 是 2026-08-31 的旧环境快照，本轮不据此推断当前 F:/Program/Agent 的运行状态，也按专门约定不改写它。

用户新回执修正了“1.0.7 仅自动验证、等待试用反馈”的现状：现已收到 T01 失败反馈。最新状态和可复用的验收规则同步到本目录索引、第一阶段细则及 S1 第 11 节；原始构建和自动通过记录保留，并明确其覆盖缺口，没有将用户试用问题掩盖为已验收。
