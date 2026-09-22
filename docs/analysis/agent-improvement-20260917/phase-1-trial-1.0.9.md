# 第一阶段候选版 1.0.9：T01 调用与展示修复

日期：2026-09-18。用户提供 1.0.8 的 T01 复测过程：补丁已应用，pytest 四项通过，最终验收通过；同时出现无效游标、命令参数拒绝、调用次数误标为重试、执行结果重复展示，以及模型对夹具和环境警告的无依据定性。用户随后明确要求修复。

## 1. 已确认问题与边界

- 分页工具的 `cursor` 默认值为 null，但严格模型协议要求所有字段必填；运行时又删除字段说明，模型无法从字段说明了解首次查询和翻页的差别。复测记录没有原始调用参数，因此不能认定用户这次一定传入了字符串 null 或 0，也不能将报错等同于真实文件变化。
- 前端按工具名称累计次数并显示“重试”，成功读取不同文件也受影响。`read_execution` 的退出码触发命令卡，读取记录自身没有独立验证结果，因此显示“结果未验证”。原测试通过并没有被撤销。
- `propose_project_patch` 只生成预览，却被通用名称匹配显示为“编辑了文件”；文件搜索也误显示为读取。
- 测试包的 autouse fixture 是执行审计标记，供禁止测试场景核对，不能单独证明断言通过。忽略注释不等于 pytest 没有执行该夹具。
- `Failed to find real location...` 的具体成因尚未核实。退出码 0 和测试通过不足以认定警告无害；本次修复证据表述，不宣称修复了尚未定位的 Python 环境问题。

## 2. 实现

| 文件 | 改动 |
|---|---|
| [runtime.py](../../../src/private_agent_local/runtime.py) | 保留严格工具 schema 的字段说明；说明分页和 PowerShell 参数格式；区分参数纠正与用户拒绝；要求夹具和警告的判断依据实际证据 |
| [repository.py](../../../src/private_agent_local/repository.py) | 无效或过期游标仍失败，明确以 JSON null 重启查询、仅复用同查询的 next_cursor；不静默替换游标 |
| [policy.py](../../../src/private_agent_local/policy.py) | PowerShell 参数拒绝给出独立数组元素、具名路径参数及当前命令的允许参数；不扩大登记集合 |
| [execution_tools.py](../../../src/private_agent_local/execution_tools.py) | 明确 restricted / none / tty=false 组合和整数读取游标；错误消息区分受限执行与可信执行，保持审批和启动前拒绝 |
| [RunTranscript.vue](../../../apps/desktop/src/features/coding/components/RunTranscript.vue) | 显示调用次数，记录不同步时不编造序号；读取执行结果不生成第二张命令卡；预览、应用补丁和搜索各自准确标记 |
| [test_local_model_contract.py](../../../tests/unit/test_local_model_contract.py) | 验证说明实际进入严格 Provider 请求，并覆盖无效游标反馈进入下一轮请求及显式恢复 |
| [test_local_search_pagination.py](../../../tests/unit/test_local_search_pagination.py) | 覆盖非法游标、跨工具复用、查询变化及重启，不绕过版本绑定 |
| [test_local_permissions.py](../../../tests/unit/test_local_permissions.py) | 覆盖位置参数、合并参数、管道仍被拒绝，正确具名参数可接受 |
| [test_local_execution_sessions.py](../../../tests/unit/test_local_execution_sessions.py) | 覆盖三种非法模式组合在审批和进程启动前被拒绝 |
| [RunTranscript.spec.ts](../../../apps/desktop/src/features/coding/components/RunTranscript.spec.ts) | 覆盖成功读取次数、缺失记录、原测试成功/失败、读取错误及预览成功/失败的展示 |
| [prepare_intent_trial.py](../../../scripts/prepare_intent_trial.py) | 澄清夹具注释的审计用途，保留原断言、标记位置和执行行为 |
| [README.md](./README.md)、本文 | 同步用户回执、当前规则、验证与复测范围 |

沿用原工具参数类型、默认值、公共协议、SQLite schema 7、权限与验收边界。没有增加模型调用、依赖或第二、三阶段功能。前端没有凭借退出码自行判定业务验收通过。

## 3. 源码验证

在仓库根目录实际执行 `.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite <名称>`：

| 套件 | 结果 | 日志 |
|---|---|---|
| local | 76 passed | .run/t01-followup-local-final.log |
| repository | 54 passed、1 skipped | .run/t01-followup-repository.log |
| execution | 22 passed | .run/t01-followup-execution-final.log |
| completion | 174 passed | .run/t01-followup-completion-final.log |
| context | 35 passed | .run/t01-followup-context-final.log |
| recovery | 38 passed | .run/t01-followup-recovery-final.log |
| contracts | 15 passed | .run/t01-followup-contracts.log |

合计 **414 passed、1 skipped**。跳过的是当前 Windows 环境没有创建真实符号链接权限的已有测试。测试使用隔离临时项目与 SQLite、模型替身，不访问真实账号数据或付费模型。

前端实际命令（工作目录 apps/desktop，由现有 managed_process 隔离启动并设置 120 秒上限）：

```text
node F:/Program/Agent/apps/desktop/node_modules/vitest/vitest.mjs run src/features/coding/components/RunTranscript.spec.ts src/features/coding/components/RunS0Baseline.spec.ts src/features/coding/components/CommandOutput.spec.ts src/features/coding/model/runOutcome.spec.ts src/features/coding/model/runProjector.spec.ts
```

结果 **62 passed**，日志 .run/t01-followup-frontend.log。新增 12 项后端回归、6 项前端回归，并更新原调用计数断言以符合修正后的含义。

其他实际命令：

```powershell
.\.venv\Scripts\python.exe -B -m ruff check src/private_agent_local/runtime.py src/private_agent_local/repository.py src/private_agent_local/policy.py src/private_agent_local/execution_tools.py tests/unit/test_local_model_contract.py tests/unit/test_local_search_pagination.py tests/unit/test_local_permissions.py tests/unit/test_local_execution_sessions.py scripts/prepare_intent_trial.py
.\.venv\Scripts\python.exe -B scripts/protocol_codegen.py --check
git diff --check
.\.venv\Scripts\python.exe -B scripts/prepare_intent_trial.py --output .run/intent-trial-1.0.9/test-kit --version 1.0.9
node scripts/build-client.cjs --qa --preview-installer --version 1.0.9 --dry-run
```

Ruff、协议同步和差异检查通过；测试包生成 14 项；构建预检确认候选身份、1.0.9 标题及空更新端点。

中途 context 套件为 1 failed、34 passed：首次参数说明过长，使无供应商用量数据的 26,000 窗口连续压缩场景超出预算。随后精简固定说明及重复内容，未改变预算算法、窗口、测试数据或断言，复跑 35 项通过；又复跑最终源码的 local、completion、recovery、execution。失败日志 .run/t01-followup-context.log 保留。

## 4. 构建与交付

以下命令实际运行并退出 0：

```powershell
.\scripts\build-client.cmd --qa --preview-installer --version 1.0.9
.\.venv\Scripts\python.exe -B scripts/verify-unified-client.py --bundle .run/unified-client-JzLzi8 --work-dir .run/intent-trial-1.0.9/packaged-validation --model-mode openai
.\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.9/verify-intent-package.py --bundle .run/unified-client-JzLzi8 --area .run/intent-trial-1.0.9/intent-package-check-02
.\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.9/prepare-delivery.py
```

构建完成 exec-host、PyInstaller、Vue 类型检查/Vite、Tauri/NSIS，保留既有 Rust 未使用代码警告。日志 .run/intent-trial-1.0.9-build.log。通用随包验证 passed=true；8 个场景 T01/T02/T03/T06/T07/T08/T13/T14 全部符合各自预期，不将 unknown、answered 或 blocked 统一改成 verified。日志分别为 .run/intent-trial-1.0.9-packaged.log 与 .run/intent-trial-1.0.9-intent-final.log。

T01 使用新 sidecar、真实宿主、审批和受限执行。两次非法分页游标、一个未登记命令、一组 PowerShell 位置参数、一组非法网络参数共 5 次拒绝均保留；分页纠正为 null 后查询成功；命令拒绝没有进入 tool.started。真实 pytest 在修改前为 4 failed、退出 1，修改后为 4 passed、退出 0；最终 verified，验收仍为 app.py 和指定测试两项。夹具标记存在。模型接收到参数说明、夹具与警告证据规则。此次隔离执行未观察到用户报告的 Python 路径警告，不能据此确认其原环境成因已解决。

首次随包脚本在 intent-package-check-01 的断言失败：误将全部工具拒绝都要求没有 tool.started。分页工具需要读取目录与内容版本后判断游标，真实只读开始事件应保留。修正脚本只对命令拒绝检查零启动，并继续检查分页明确失败后纠正成功；产品源码没有因此调整。随后在全新 intent-package-check-02 目录重跑通过。失败日志 .run/intent-trial-1.0.9-intent.log 保留。

测试包一致性最初对照已被手工测试修改的 1.0.8 工作目录而失败；随后使用 SHA256 已核对的历史交付 ZIP。确认 14 个用例的提示词、权限和预期相同，100 个项目文件的 Python AST 或非代码字节一致，采集器字节一致。新夹具注释使文件哈希发生预期变化，不将此误报为测试逻辑修改。

交付目录：F:/Program/Agent/.run/intent-trial-1.0.9/delivery/。

| 产物 | 用途 |
|---|---|
| [PrivateAgentCandidate_1.0.9_x64-setup.exe](../../../.run/intent-trial-1.0.9/delivery/PrivateAgentCandidate_1.0.9_x64-setup.exe) | Windows x64 候选安装器，30,826,077 字节 |
| [PrivateAgent-M1-TestKit-1.0.9.zip](../../../.run/intent-trial-1.0.9/delivery/PrivateAgent-M1-TestKit-1.0.9.zip) | 14 项测试集，106 文件，41,225 字节 |
| [README.md](../../../.run/intent-trial-1.0.9/delivery/README.md)、[RESULTS-template.md](../../../.run/intent-trial-1.0.9/delivery/RESULTS-template.md) | 安装、复测检查点及反馈模板 |
| [SHA256SUMS.txt](../../../.run/intent-trial-1.0.9/delivery/SHA256SUMS.txt) | 7 个交付文件的完整性校验 |
| [build-info.json](../../../.run/intent-trial-1.0.9/delivery/build-info.json)、[source-manifest.json](../../../.run/intent-trial-1.0.9/delivery/source-manifest.json)、[validation.json](../../../.run/intent-trial-1.0.9/delivery/validation.json) | 构建身份、667 个来源文件摘要、验证记录 |

安装器 SHA256：7f886862e78edc07466332158f9fe21a34c23351b27f69f72d10d8d8a1cba48a。

测试 ZIP SHA256：0cb47983e586bfecf217d81877cd7962926c11747b1f13ca6e01a91b8a6f8c04。

构建来源：HEAD 1dde393e29f3dbacd3647d11834b39824ac8323f、dirty=true；原始目录 .run/unified-client-JzLzi8；来源集合摘要 bc2e33f475a47cdd456c04309d89802b1841391d96a8858548afb5db14a38ea8。与 1.0.8 的 667 项输入对照，仅四个本机运行时模块和 RunTranscript 组件及其测试共 6 项改变。全部来源逐项核对无构建后变化，ZIP CRC 与 106 个条目字节检查通过。

`Get-AuthenticodeSignature` 返回 NotSigned；候选标识仍为 com.personal-assistant.desktop.candidate，版本 1.0.9，更新端点为空。未自动安装、上传、发布、修改正式更新源或创建 Git 提交。退出旧候选版后安装新包，将新测试集解压到新目录并创建新任务复测 T01，再继续 T02/T03/T06/T08 及其他用例。旧任务的模型回答不会被回写。

## 5. 项目记忆与复测边界

已读取根 AGENTS.md、docs/project-state.md、第一阶段索引、1.0.8 修复说明，并按当前代码核对。共享状态文件是 2026-08-31 的历史快照，按专门约定不自动改写；当前行为、测试及交付事实记录在本阶段文档，没有新建记忆系统。

索引原先写“1.0.8 用户复测待回执”，现根据用户粘贴记录更正为 T01 主流程通过、收到后续问题并修复。保留 1.0.8 的历史构建和原始验证记录，不把新回执推广成全部用例通过。

模型提示和字段说明只能降低错误调用与无依据判断的概率，确定性测试验证的是说明传递、拒绝与恢复、实际执行和界面状态；真实模型的回答仍需用户复测。本次不读取用户安装副本的私有数据，也没有确认原始无效游标参数和 Python 警告的环境成因。
