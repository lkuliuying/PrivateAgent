# 第一阶段 1.0.12：T02、T03 修复与复测包

记录日期：2026-09-18。按用户最新请求修复已记录的 T02、T03 问题，并将前轮尚未打包的 T01 回答质量约束一起交付。第一阶段之外的计划、记忆及并发能力未扩展。

## 交付与使用

- `PrivateAgentCandidate_1.0.12_x64-setup.exe`（历史安装包，已按[2026-09-22 保留策略](../../solutions/2026-09-22-project-cleanup.md)清理），30,838,393 字节。
- [全新 T01–T14 测试集](../../../.run/intent-trial-1.0.12/delivery/PrivateAgent-M1-TestKit-1.0.12.zip)，14 个独立项目用例、107 个文件。
- [安装说明](../../../.run/records/run/intent-trial-1.0.12/delivery/README.md)、[T02/T03 复测步骤](../../../.run/records/run/intent-trial-1.0.12/delivery/UI-RETEST.md)、[反馈模板](../../../.run/records/run/intent-trial-1.0.12/delivery/RESULTS-template.md)。
- [验证清单](../../../.run/records/run/intent-trial-1.0.12/delivery/validation.json)、[构建信息](../../../.run/records/run/intent-trial-1.0.12/delivery/build-info.json)、[来源清单](../../../.run/records/run/intent-trial-1.0.12/delivery/source-manifest.json)、[文件校验值](../../../.run/records/run/intent-trial-1.0.12/delivery/SHA256SUMS.txt)。

退出旧候选版后安装，确认窗口标题包含 1.0.12。测试 ZIP 解压到全新目录，先复测 T02、T03，再继续 T04–T14；T01 回答质量可选补测。每次选取对应 `projects/Txx` 并新建任务，不覆盖此前结果。复制回答优先使用新增“复制 Markdown”按钮。

## 问题与实现

### T02：遵守禁止测试不再被当作校验错误

原实现把有文件要求、但保留测试未验证项的 `unknown` 一律返回输出校验失败；本地任务后来转为 `completed`，仍带 `output_validation_failed`，造成遵守用户约束却报错。

现在只对下列情况正常收尾：用户明确禁止测试或命令；没有约束冲突；所有要求均为文件修改且有通过的证据；未验证项完全来自该用户禁令。校验返回 `completion_limited`，不产生通用校验错误，最终说明“修改已完成；按用户要求未运行测试，功能正确性尚未验证”。`RunOutcome.goal_outcome` 仍为 `unknown`，测试结果未升级为通过。

前端将该事件显示为“核验结束，保留未验证项”。文件修改证据完整的终态显示“修改已完成，仍有未验证项”。缺失证据、磁盘被外部修改、其他人工要求、执行失败、约束冲突及验证器异常保持原来的保守结果；旧记录缺少可选字段也不能误报完成。最终未验证摘要沿用确定性证据输出，不采信模型虚假的“测试通过”。

### T03：标题、下划线和复制

`MarkdownContent` 原标题固定为 12px，小于最终/历史正文 17px。现按正文比例区分标题级别，h2 为 1.3em、h3 为 1.15em；代码为 0.92em。三个展示位置共用该组件，无全局字号改动。

行内 `_..._` 原匹配没有词边界，可跨文件名吞掉下划线。现限制单/双下划线强调边界，保留 `tests/test_app.py`、`.pytest_cache` 等标识符；显式代码和正常强调语法仍可使用。这证明存在对应渲染缺陷，不代表已取得用户那次的原始模型文本或完全重现其复制链路。

代码语言标签移出 `<code>` 正文，并不参与选择；新增“复制 Markdown”，直接复制该回答源文本，保留代码围栏、四列表头和路径。复用现有复制工具，失败给出提示，回退路径总会回收临时节点并恢复焦点。内容更新或组件卸载后不显示旧请求的成功状态，复制进行中不允许并发写剪贴板。

### 回答准确性约束

在现有系统提示中要求用边界与反例检查相等条件，省略未证实的规律；逐字引用路径和哈希，不编造摘要简写。合入前轮的算例范围、普遍/单调结论证明要求，以及诊断不确定性和环境范围约束。Python 警告消息明确“文本匹配、本次根因尚未核实”，保留原始 stderr。

没有新增模型调用、依赖、协议字段、数据库迁移或自然语言答案替换规则。工具注册与硬性权限仍由原有架构负责。提示缩短了重复措辞以保持小上下文预算，未修改预算上限或放宽测试断言。

## 实际验证

命令执行目录为 `F:\Program\Agent`，前端类型检查目录为 `F:\Program\Agent\apps\desktop`。使用独立目录与本地模拟供应商，无真实模型或账号调用。

| 检查 | 结果 |
|---|---|
| `python -B scripts/run_coding_validation.py --suite completion` | 180 passed |
| `python -B scripts/run_coding_validation.py --suite local` | 88 passed |
| `python -B scripts/run_coding_validation.py --suite context` | 35 passed |
| `python -B scripts/run_coding_validation.py --suite execution` | 35 passed |
| `.run/intent-trial-1.0.12/check-frontend.py` | 8 个文件，127 passed |
| `node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` | 退出 0 |
| `node .run/intent-trial-1.0.12/visual-check.mjs` | 1200px、480px、模拟 150% 缩放，三个展示位置均通过；剪贴板正文一致 |
| Ruff、协议生成、`git diff --check` | 通过 |
| 候选构建 | Vue 类型检查、Vite、PyInstaller、Rust、NSIS 完成；退出 0 |
| 通用随包检查及 T01/T02/T03/T06/T07/T08/T13/T14 | 最终二进制均通过 |

后端共 338 项通过，无跳过；前端 127 项通过。浏览器实测最终/历史正文 17px，h2 为 22.1px、h3 为 19.55px、代码为 15.64px；公开输出按其现有正文 12px 计算。Windows 剪贴板将 LF 转为 CRLF，比较只统一该换行差异，没有修补正文。缩放检查采用 CSS 缩放与相应收窄的应用容器，不能代替安装后所有系统缩放组合。

本轮发现并修正的验证失败：新增测试最初使用了当前 Vitest 不支持的断言名，改为同等次数和参数断言；新增提示最初使连续压缩测试超限，等义缩短后原 26,000 预算的 35 项测试通过；首次构建发现可选字段缺少防护，补充防护和缺失字段用例后类型检查与 127 项前端回归通过，再重新完整构建。浏览器夹具也纠正了历史去重、过程折叠、系统换行和缩放容器的模拟方式。失败日志保留在本轮 `.run` 目录，不使用失败构建的可执行文件作为交付。

随包 T01 用真实 Python/pytest 执行：修复前 `4 failed` / 退出 1，修复后 `4 passed` / 退出 0，最终两项要求 verified。T02 保留 unknown、无错误码，不发出 `output.validation_failed`，禁止测试的尝试在启动前被拦截；T03 只读取文件，禁止写入及命令，结果 answered。此处模拟供应商主动尝试禁止操作，用于验证硬性约束，不能当作真实模型回答的语义验收。

完整可追溯命令：

```powershell
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite completion
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite local
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite context
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite execution
.\.venv\Scripts\python.exe -B .run/intent-trial-1.0.12/check-frontend.py
node .run/intent-trial-1.0.12/visual-check.mjs
.\.venv\Scripts\python.exe -m ruff check src/private_agent_local/completion.py src/private_agent_local/runtime.py src/private_agent_local/execution_diagnostics.py tests/unit/test_local_task_constraints.py tests/unit/test_local_model_contract.py
.\.venv\Scripts\python.exe -B scripts/protocol_codegen.py --check
git diff --check
.\scripts\build-client.cmd --qa --preview-installer --version 1.0.12
.\.venv\Scripts\python.exe -X utf8 -B scripts/prepare_intent_trial.py --output .run/intent-trial-1.0.12/test-kit --version 1.0.12
.\.venv\Scripts\python.exe -B scripts/verify-unified-client.py --bundle .run/unified-client-bgWGuw --work-dir .run/intent-trial-1.0.12/packaged-validation --model-mode openai
.\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.12/verify-intent-package.py --bundle .run/unified-client-bgWGuw --area .run/intent-trial-1.0.12/intent-package-check
.\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.12/prepare-delivery.py
.\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.12/audit.py
```

证据位于 `.run/intent-trial-1.0.12/`；原始失败与最终成功日志分开保留。所有测试数据与用户目录隔离，旧候选安装器和测试 ZIP 未覆盖。测试集 100 个项目文件与采集脚本对旧 1.0.9 ZIP 逐字节核验一致，仅版本/说明类文件变化。

## 变更范围

相对本轮开始保存的工作区基线，修改以下文件，保留其他会话的既有未提交工作：

| 文件 | 变更 |
|---|---|
| `src/private_agent_local/completion.py` | 用户禁止验证时的窄范围正常收尾分支 |
| `src/private_agent_local/runtime.py` | 确定性未验证摘要、回答准确性约束与提示压缩 |
| `tests/unit/test_local_task_constraints.py` | 正常收尾与四类不得放行情形 |
| `tests/unit/test_local_model_contract.py` | 新约束传到首次与工具后实际模型请求 |
| `apps/desktop/src/features/coding/model/runProjector.ts` 及 `.spec.ts` | 限制性收尾事件与回放 |
| `apps/desktop/src/features/coding/model/runOutcome.ts` 及 `.spec.ts` | 终态标签、缺失字段、失败与取消边界 |
| `apps/desktop/src/features/coding/components/RunTranscript.vue` 及 `.spec.ts` | 未验证事件说明 |
| `apps/desktop/src/features/coding/components/MarkdownContent.vue` 及 `.spec.ts` | 字号、下划线、代码与原文复制及并发状态 |
| `apps/desktop/src/features/agent/model/copyAnswerText.ts` 及 `.spec.ts` | 复制失败的节点与焦点清理 |
| 阶段 `README.md`、`phase-1-trial-feedback.md`、`phase-1-answer-quality-follow-up.md`、本文 | 当前状态、修复边界、合包与验证证据 |

前轮 `execution_diagnostics.py` 与执行会话测试的既有改动已随本包合入，本轮重新验证，没有再次修改这些文件。临时基线、截图、验证脚本与交付物均在 `.run/intent-trial-1.0.12/`；没有修改依赖、锁文件、服务器、系统权限、生产数据或 Git 历史。

## 完整性与限制

安装器 SHA256：`4faeb72fecca2223e70d99d42f2866ccaa2843fecaa3048c39a5c2972091eada`。

测试 ZIP SHA256：`59d019b55c330b338eb44c0a14a4dba8724600ac7ecb87045017c7c0b3aedd7d`。

来源集合 SHA256：`ab464b2e9e20036b90fc63239785a862873063c47e00a8d52fd09363920b5771`；随包二进制与通过验证的副本一致，668 个来源文件逐项核对一致。相对 1.0.11 的 13 个构建输入差异均属于本次修复及前轮合入项，无其他来源变化。最终审查的 18 个文件 UTF-8 无 BOM、41 个本地文档链接及新旧两份交付清单各 8 个文件 SHA256 全部通过。Git HEAD 为 `1dde393e29f3dbacd3647d11834b39824ac8323f`，`dirty=true`。候选身份 `com.personal-assistant.desktop.candidate`，更新端点为空，签名检查为 `NotSigned`；没有自动安装或发布。

模型提示不能保证每次算术、相等条件和引用都正确，需要用户使用配置的真实模型复测。第三方软件手选富文本转换并未全面验证；新增按钮提供保留 Markdown 结构的路径。Python 路径警告仍可能出现，本次只保留警告和限定原因，没有修改系统 Python 或消除第三方沙箱兼容问题。构建保留既有 10 条 Rust 未使用代码警告。

## 项目记忆同步

读取根 `AGENTS.md`、`docs/project-state.md` 的 2026-08-31 历史快照、本阶段索引、反馈台账、1.0.11 交付和回答质量修复记录；以当前源码、用户回执及本轮测试交叉核对。原阶段记录的“只记录、待修复/合包”已被新授权和验证证据更新，保留历史回执与当时结论，不把真实模型效果改写为已验收。更新本阶段四份记录；按入口约定未改写共享历史快照 `docs/project-state.md`，未建立新记忆系统。
