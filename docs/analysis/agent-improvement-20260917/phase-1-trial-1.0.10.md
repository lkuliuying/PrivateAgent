# 第一阶段 1.0.10：搜索参数诊断修复

日期：2026-09-18。用户提供 1.0.9 的 T01 复测记录，修复、四项 pytest 和最终验收通过，但一次搜索被拒绝。随后用户运行本轮提供的只读查询脚本，确认参数为 query="app.py"、glob=""、cursor=null，且没有额外字段。用户明确要求修复此问题。

## 1. 已确认的原因与范围

按用户参数调用实际 SearchArgs 校验，可复现 glob 的 string_too_short；只改为 "*" 即通过，cursor=null 合法。严格模型 schema 保留 minLength=1，但删除默认值，原 glob 字段没有说明不限文件类型时应填写 "*"。拒绝信息此前没有指出具体字段，工具卡也没有参数展开入口。

本次保留严格校验，不把空字符串静默改成扩大搜索范围的通配符；保留项目权限、目录边界、既有审批、验收和数据库版本。范围限定为搜索参数说明、拒绝诊断及失败参数查看，不实施第二、三阶段。

## 2. 实现文件

| 文件 | 变更 |
|---|---|
| [runtime.py](../../../src/private_agent_local/runtime.py) | glob 说明传递给严格模型协议；搜索参数校验失败时反馈已知字段及纠正提示，在原 output 中附加 parameter_errors |
| [RunTranscript.vue](../../../apps/desktop/src/features/coding/components/RunTranscript.vue) | 失败搜索卡增加“查看失败参数”，原生 details 支持展开、键盘操作和文本选择，兼容缺少诊断字段的历史记录 |
| [test_local_model_contract.py](../../../tests/unit/test_local_model_contract.py) | 验证真实适配器发出的 schema，非法 glob 仍拒绝，错误反馈进入模型请求，纠正后实际搜索成功 |
| [test_local_executor.py](../../../tests/unit/test_local_executor.py) | 通过本机 API 验证空串、null、错误类型、超长值；拒绝不启动搜索，不在诊断中回显查询文本、容器内容或未知参数 |
| [RunTranscript.spec.ts](../../../apps/desktop/src/features/coding/components/RunTranscript.spec.ts) | 验证空值展示、点击展开、旧记录和畸形数据兼容、长度限制、文本转义与再次脱敏 |
| [README.md](./README.md) | 按用户回执更新第一阶段交付状态 |
| 本文 | 记录根因、兼容边界和本轮实际验证 |

parameter_errors 只包含 field、code、received、hint。received 区分缺失、null、空字符串、类型和长度；非空字符串与容器不复制原文。该诊断不表示搜索执行成功，也不生成命令卡或新的验收要求。已有工具协议和 output 对象兼容，无数据库迁移、依赖或公共字段类型变化。

## 3. 源码验证

实际命令：

```powershell
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite local
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite context
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite completion
.\.venv\Scripts\python.exe -B .run/t01-followup-frontend.py
.\.venv\Scripts\python.exe -B -m ruff check src/private_agent_local/runtime.py tests/unit/test_local_model_contract.py tests/unit/test_local_executor.py
.\.venv\Scripts\python.exe -B scripts/protocol_codegen.py --check
git diff --check
node scripts/build-client.cjs --qa --preview-installer --version 1.0.10 --dry-run
.\.venv\Scripts\python.exe -B scripts/prepare_intent_trial.py --output .run/intent-trial-1.0.10/test-kit --version 1.0.10
```

| 验证 | 结果 | 日志 |
|---|---|---|
| local | 87 passed | .run/glob-fix-local.log |
| context | 35 passed | .run/glob-fix-context.log |
| completion | 174 passed | .run/glob-fix-completion.log |
| 前端 | 69 passed，5 个文件 | .run/glob-fix-frontend.log |

后端合计 296 项通过，无失败或跳过。新增 11 项后端、7 项前端回归。前端沿用已有 managed_process 隔离脚本，实际运行 node apps/desktop/node_modules/vitest/vitest.mjs run，目标为 RunTranscript、RunS0Baseline、CommandOutput、runOutcome、runProjector 对应的五个 spec 文件。所有测试使用合成数据和模型替身。

Ruff、协议同步、差异检查通过；构建预检确认候选身份、1.0.10 标题及空更新端点。新测试包保留 14 个用例，已对照 SHA256 核实的 1.0.9 交付 ZIP：用例定义完全一致，100 个项目文件及采集脚本共 101 个文件逐字节一致。未使用已经被用户测试修改的旧解压目录作为基线。

## 4. 构建与随包验证

以下命令实际执行并退出 0：

```powershell
.\scripts\build-client.cmd --qa --preview-installer --version 1.0.10
.\.venv\Scripts\python.exe -B scripts/verify-unified-client.py --bundle .run/unified-client-JQdR5G --work-dir .run/intent-trial-1.0.10/packaged-validation --model-mode openai
.\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.10/verify-intent-package.py --bundle .run/unified-client-JQdR5G --area .run/intent-trial-1.0.10/intent-package-check
.\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.10/prepare-delivery.py
```

构建完成 exec-host、PyInstaller、Vue 类型检查/Vite、Tauri/NSIS，保留既有 10 条 Rust 未使用代码警告。日志为 .run/intent-trial-1.0.10-build.log。通用随包验证 passed=true，证据在 .run/intent-trial-1.0.10/packaged-validation/packaged-runtime-eadf1ba1625b480e921863f3e3e0f62e/verification.json。

8 个随包场景 T01/T02/T03/T06/T07/T08/T13/T14 全部符合预期，分别保留 verified、unknown、answered 或 blocked 等真实目标状态。日志为 .run/intent-trial-1.0.10-packaged.log 与 .run/intent-trial-1.0.10-intent.log，完整场景报告在 .run/intent-trial-1.0.10/intent-package-check/verification.json。

T01 在新 sidecar 中提交用户这组 glob=""、cursor=null 参数：在 tool.started 前拒绝，返回 glob / string_too_short / 空字符串及填写 "*" 的提示；随后搜索成功。该场景保留原有游标及命令拒绝回归，总计 6 次 local_tool_rejected。真实 pytest 修改前 4 failed、退出 1，修改后 4 passed、退出 0；最终 verified，验收要求仍为 2 项。证据在 .run/intent-trial-1.0.10/intent-package-check/T01-evidence.json，运行 ID 为 07c483f4-397a-47d7-ab1b-70c9f35d5b53。

交付目录：F:/Program/Agent/.run/intent-trial-1.0.10/delivery/。

| 产物 | 用途 |
|---|---|
| [PrivateAgentCandidate_1.0.10_x64-setup.exe](../../../.run/intent-trial-1.0.10/delivery/PrivateAgentCandidate_1.0.10_x64-setup.exe) | Windows x64 候选安装器，30,834,311 字节 |
| [PrivateAgent-M1-TestKit-1.0.10.zip](../../../.run/intent-trial-1.0.10/delivery/PrivateAgent-M1-TestKit-1.0.10.zip) | 原有 14 项测试集，106 文件，41,229 字节 |
| [README.md](../../../.run/intent-trial-1.0.10/delivery/README.md)、[RESULTS-template.md](../../../.run/intent-trial-1.0.10/delivery/RESULTS-template.md) | 安装步骤、查看入口说明与反馈模板 |
| [SHA256SUMS.txt](../../../.run/intent-trial-1.0.10/delivery/SHA256SUMS.txt) | 7 个交付文件的完整性校验 |
| [build-info.json](../../../.run/intent-trial-1.0.10/delivery/build-info.json)、[source-manifest.json](../../../.run/intent-trial-1.0.10/delivery/source-manifest.json)、[validation.json](../../../.run/intent-trial-1.0.10/delivery/validation.json) | 构建来源、667 个文件摘要与实际验证 |

安装器 SHA256：974b8cd953f007003a956630ad97b1726a0847a94a1088cd8ce76c76a1dbebc3。

测试 ZIP SHA256：1832335e8db6e3c64ba099d1ddb33e13dcd8fb1fad45bd96528ff6a705a1f762。

构建来源为 HEAD 1dde393e29f3dbacd3647d11834b39824ac8323f、dirty=true，原始目录 .run/unified-client-JQdR5G；来源集合摘要 f4c6765dd6ae2749f50760adbc8a9189e2a97e12cab5dbc0f51062de362e6522。与 1.0.9 的来源集合相比，仅 runtime.py、RunTranscript.vue 和对应前端测试共 3 项输入变化；后端测试及阶段文档不在打包来源集合内。667 项来源逐项复核无构建后变化，ZIP CRC 和条目字节核对通过。

Get-AuthenticodeSignature 返回 NotSigned。候选标识仍为 com.personal-assistant.desktop.candidate，版本 1.0.10，更新端点为空；未自动安装、上传、发布、修改正式更新源或创建 Git 提交。

## 5. 记忆同步与复测边界

已阅读根 AGENTS.md、docs/project-state.md、本阶段索引及 1.0.9 修复记录，并核对当前源码、Git 状态与用户回执。共享状态记忆是 2026-08-31 的历史快照，按专门约定不自动改写；本轮行为和交付事实沿用本阶段记录。

已修正的旧信息：阶段索引的“1.0.9 用户复测待回执”已按用户新证据改为 T01 主流程通过、搜索参数问题修复及 1.0.10 待复测；1.0.9 随包 README 让用户“展开调用”的步骤不符合该版本实际界面。本版指南说明新的失败参数入口及适用范围，保留旧交付 ZIP、安装包和校验值，不改写历史产物。

新入口只显示有 parameter_errors 的失败搜索记录；旧任务不会自动补齐诊断。模型字段说明降低错误调用概率，不保证真实模型永不提交非法参数，实际搜索成功仍须由工具结果证明。当前自动验证不等于用户安装副本或真实模型验收。

本轮未处理另外发现的“约 0 tokens”字段不一致和 Markdown 表格支持问题；Python 环境警告来源仍未定位。这些不影响本次空 glob 拒绝原因的确定性复现，也不应被记成已修复。
