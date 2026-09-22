# 第一阶段候选版 1.0.13 交付记录

记录日期：2026-09-19。用户明确要求生成新的安装包，用于复测 T02 及后续用例。本次仅将前两轮已完成的进展展示与界面精简改动打入候选版，不实施第二、三阶段，不安装、上传或发布自动更新。1.0.13 尚无安装后用户回执，全部人工测试初始为“未覆盖”。

## 1. 范围与来源

接手已读取根 `AGENTS.md`、[历史项目状态](../../project-state.md)、[阶段索引](./README.md)、[反馈台账](./phase-1-trial-feedback.md)及 [1.0.12 交付记录](./phase-1-trial-1.0.12.md)，核对 Git 状态、历史、暂存区和相关源码差异。分支 `dev/1.0.0`，HEAD `1dde393e29f3dbacd3647d11834b39824ac8323f`，保留大量既有未提交改动；未提交、推送、回退或清理工作区。

本次构建目录：[`.run/unified-client-wFqY4i`](../../../.run/records/run/unified-client-wFqY4i)。`build-info.json` 记录 `dirty=true`；不能将 HEAD 单独视为交付源码。对比 1.0.12 的来源清单，668 个构建输入中只有以下 8 个文件发生变化，均对应已经验证的两轮展示改动：

- `src/private_agent_local/core_adapter.py`：非流式有效公开正文补发既有事件，流式正文不重复。
- `src/private_agent_local/runtime.py`：请求提示要求工具前简述公开进展，不增加独立模型调用。
- `apps/desktop/src/features/coding/model/runProjector.ts` 及其测试：按模型轮次投影公开正文。
- `apps/desktop/src/features/coding/components/RunTranscript.vue` 及其测试：连续进展、折叠工具、去重、精简展示和必要注意提示。
- `apps/desktop/src/features/coding/components/MarkdownContent.vue` 及其测试：最终/历史回答底部复制图标，保留原始 Markdown。

这些是相对上一交付包的差异，本次打包没有再修改产品源码。前两轮的两份后端测试也保留在工作区；它们不是运行时构建输入。交付时再次核对全部来源文件摘要。

## 2. 用户可见变化与验收边界

- 过程展开后以实际公开进展段落为主，命令和工具默认折叠；完成后显示简洁耗时行和最终正文。没有公开进展的模型响应不补造内容，不读取隐藏推理。
- 去掉正文区上下文 token 行、重复进展标签与各段复制按钮、“已使用”、成功徽标、最终验收记录及常规成功校验行。失败、未验证、中断、拒绝、警告与待审批仍保留必要提示；验收数据与判定规则不变。
- 最终与历史回答底部的双页图标复制原始 Markdown；按轮次保留进展、去除相同最终正文的重复，支持任务重开和键盘折叠操作。
- T02 仍应保留“修改已完成，仍有未验证项”及 `goal_outcome=unknown`；禁止测试不等于功能已经验证。T03 根据只读工具、解释与复制结果验收。T04 展开命令查看指定 pytest、退出码 0、`4 passed`，并核对真实修改。
- Python 原始 stderr 警告可能继续出现，匹配警告文本不等于确认根因；1.0.12 回执中解释确定程度矛盾仍作为模型回答质量限制保留。

## 3. 构建与验证

所有命令从 `F:\Program\Agent` 执行。构建采用既有隔离配置，不加载真实项目环境文件；随包检查使用独立目录、合成项目和回环模拟供应商，不调用真实模型或读取生产数据库、模型密钥。

| 命令 | 本轮观察结果 |
|---|---|
| `.\scripts\build-client.cmd --qa --preview-installer --version 1.0.13` | 退出 0；PyInstaller、前端类型检查/Vite、Rust/Tauri 与 NSIS 完成；安装器版本资源为 1.0.13 |
| `.\.venv\Scripts\python.exe -X utf8 -B scripts/prepare_intent_trial.py --output .run/intent-trial-1.0.13/test-kit --version 1.0.13` | 生成全新独立测试集；补充新版 UI 复测说明 |
| `.\.venv\Scripts\python.exe -B scripts/verify-unified-client.py --bundle .run/unified-client-wFqY4i --work-dir .run/intent-trial-1.0.13/packaged-validation --model-mode openai` | 退出 0；最终随包程序的 IPC、审批、受限执行、宿主篡改拦截及模拟账号流程通过 |
| `.\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.13/verify-intent-package.py --bundle .run/unified-client-wFqY4i --area .run/intent-trial-1.0.13/intent-package-check` | 首轮退出 1，原 240 秒时限后报 `TimeoutError`；实际为夹具频繁轮询耗尽请求预算，详见下文，不能记为通过 |
| `.\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.13/verify-intent-package.py --bundle .run/unified-client-wFqY4i --area .run/intent-trial-1.0.13/intent-package-check-02` | 修正夹具后退出 0，T01/T02/T03/T06/T07/T08/T13/T14 八场景全部通过，公开正文事件通过 |
| `.\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.13/prepare-delivery.py --bundle .run/unified-client-wFqY4i --intent-area .run/intent-trial-1.0.13/intent-package-check-02` | 退出 0；核对构建摘要、668 个来源文件、旧交付完整性、新测试集和最终 ZIP，汇集交付文件 |
| `.\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.13/audit.py` | 退出 0；3 份仓库文档 UTF-8/差异检查、52 个本地链接、新旧各 8 项交付摘要、668 个来源文件与 100 个测试项目文件核对通过，Git 状态条目保留，暂存区为空 |

首轮失败已只读核对该次隔离 SQLite：`python --version` 38.45 秒退出 0，修复前 pytest 44.50 秒退出 1，修复后 pytest 41.78 秒退出 0、`4 passed in 0.02s`。夹具累计 64 次工具调用中有 50 次 `read_execution`，最终文本请求前运行已因 `max_model_requests` 进入 `limit_exceeded`。原检查函数漏识别此终态，继续等待才报超时；不是 240 秒一直卡在同一个命令。保留首轮脚本、失败报告及合成执行证据，仅将新的检查夹具改为现有 `read_execution(wait_ms=10000)` 长轮询并补齐终态/失败证据记录。产品源码、安装包、请求预算、240 秒时限和原业务断言不变；复跑使用全新目录，不覆盖首轮。

第二轮 [verification.json](../../../.run/records/run/intent-trial-1.0.13/intent-package-check-02/verification.json) 记录八场景全部通过：T01 最终 `verified`，T02/T06/T07 为 `unknown`，T03/T13/T14 为 `answered`，T08 为 `blocked`，各自符合定义。47 次模拟模型请求包含 9 条非空公开正文，对应 9 个正文事件；按轮次核对唯一性、顺序、结束标记和空正文不补造，T03 同时覆盖公开进展与最终正文。T02 的模拟候选文字刻意声称测试通过，最终验收仍明确未测试、没有 `output_validation_failed`；模型正文不替代验收。首轮 [失败诊断](../../../.run/records/run/intent-trial-1.0.13/intent-package-check/failure-diagnosis.json) 与 `passed=false` 报告保留。

新交付脚本的 Python 语法检查通过；`.\.venv\Scripts\python.exe -B -m ruff check --select E9,F63,F7,F82 .run/intent-trial-1.0.13/prepare-delivery.py .run/intent-trial-1.0.13/audit.py` 通过。随包夹具的语法及 Ruff 检查通过，AST 比较确认修正轮询前的 73 条断言均保留。

前两轮已实际执行的源码回归为：后端 streaming 40、local 88、context 35，共 163 项；前端 8 个文件、151 项；Ruff、类型检查/前端构建及隔离浏览器检查通过。本轮没有重复运行这些源码套件；具体命令和首轮失败处理保留在[反馈台账](./phase-1-trial-feedback.md#本轮源码改进与验证)和[精简展示记录](./phase-1-trial-feedback.md#2026-09-19补充按用户标记精简展示)。浏览器证据保留在 [`.run/progress-minimal-20260919/visual-results.json`](../../../.run/records/run/progress-minimal-20260919/visual-results.json)，覆盖宽窄窗口、缩放、折叠、审批、失败/未知、复制入口及重开；这是合成数据下真实组件的验证，不是安装副本人工验收。

构建保留与 1.0.12 相同的三类非致命提示：PyInstaller `Hidden import "importlib_resources.trees" not found!`、前端 chunk 大于 500 kB、Rust 10 条未使用代码警告。未为消除提示扩大修改范围；本轮随包验证与构建结果分别记录，不据此承诺全部未覆盖功能均可用。安装器 Authenticode 状态为 `NotSigned`，没有生成自动更新清单。

## 4. 交付文件

交付目录：[`.run/intent-trial-1.0.13/delivery`](../../../.run/intent-trial-1.0.13/delivery/)。

| 文件 | 用途或核验值 |
|---|---|
| `PrivateAgentCandidate_1.0.13_x64-setup.exe`（历史安装包，已按[2026-09-22 保留策略](../../solutions/2026-09-22-project-cleanup.md)清理） | Windows x64 未签名候选安装器，30,836,650 字节 |
| [PrivateAgent-M1-TestKit-1.0.13.zip](../../../.run/intent-trial-1.0.13/delivery/PrivateAgent-M1-TestKit-1.0.13.zip) | 14 个用例、107 个文件，全部人工结果初始未覆盖 |
| [UI-RETEST.md](../../../.run/records/run/intent-trial-1.0.13/delivery/UI-RETEST.md) | T02 起的新版界面与取证步骤 |
| [RESULTS-template.md](../../../.run/records/run/intent-trial-1.0.13/delivery/RESULTS-template.md) | 人工反馈表 |
| [validation.json](../../../.run/records/run/intent-trial-1.0.13/delivery/validation.json) | 自动检查范围、首轮失败记录引用及人工验收边界 |
| [SHA256SUMS.txt](../../../.run/records/run/intent-trial-1.0.13/delivery/SHA256SUMS.txt) | 全部交付文件 SHA256；同目录附说明、构建信息和来源清单 |

- 安装器 SHA256：`4915432a2ffb11ab10a29d78505b197656515a3e2d293fd096b731727b2dccfb`。
- 测试 ZIP SHA256：`3327a36198aa4310b88e39cd9f5b15552a685287bf67aa39eab85f4a57b5ac27`。
- 来源集合 SHA256：`b968d5a3f60996f4a4119feaf6ac4921f52382d11f5528686b1a97944ee768c1`。

新测试集 100 个项目文件、采集脚本、超长输入及所有 `baseline.cases` 与 1.0.12 原始交付 ZIP 一致；仅更新版本、复测顺序和 UI 观察说明。没有复制已执行/修改过的旧测试工作目录。新 ZIP 逐文件回读及 CRC 核验通过，旧安装包和旧 ZIP 摘要仍一致。

候选身份继续为 `com.personal-assistant.desktop.candidate`，与旧候选版相同、与普通版独立。用户手工安装将按既有机制升级旧候选版；本轮不自动安装，也未实际验证该安装副本或数据迁移。

## 5. 复测与记忆同步

先关闭旧候选程序，再安装并确认窗口版本 1.0.13。测试 ZIP 解压到全新目录，按 `UI-RETEST.md` 先做 T02/T03/T04，再继续 T05–T14；每项使用对应 `projects/Txx` 和独立任务。T01 可选补测。保留旧包、旧测试目录和回执，不能将 1.0.12 的回执直接视为 1.0.13 通过。

本次同步本记录、阶段索引和反馈台账，记录实际新交付及待人工复测状态。此前“未打包”属于前两轮源码完成时的历史状态，按日期保留并由本交付记录补充；`docs/project-state.md` 仍为 2026-08-31 历史快照，没有改写，也没有新增记忆系统。

最终仓库变更仅为本交付记录、阶段 `README.md` 和反馈台账；产物、验证脚本及日志均留在忽略的 `.run/intent-trial-1.0.13/` 与新构建目录。本轮差异保存为 `current-turn.diff`，审计结果保存为 `audit.json`，旧代码工作和交付文件均保留。
