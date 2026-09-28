# S6 阶段 D：本地开发与隔离验证准备轮

日期：2026-09-15。工作区：`F:\Program\Agent`。本报告只覆盖本轮明确授权的 D-01～D-05 本地准备；不进入 E～F，不形成真实模型质量、D 完整验收或 M3 放行结论。

## 1. 上下文与实施边界

已读根目录 `AGENTS.md`、[项目状态](../../project-state.md)、[本机直连说明](../../direct-model-execution.md)、[后续计划](s6-follow-up-development-plan.md)、[A 报告](s6-phase-a-validation-report.md)、[B 契约](s6-phase-b-contract.md)、[B 剩余项](s6-phase-b-remaining-report.md)、[B 本地学习报告](s6-phase-b-local-learning-validation.md)、[C 报告](s6-phase-c-validation-report.md) 和 [测试说明](../../../tests/coding_acceptance/README.md)。按真实调用路径核对了评测、模型交接、预算、统计、账本、审阅、IPC、桌面控制、恢复及宿主。

当前 HEAD 为 `1dde393e29f3dbacd3647d11834b39824ac8323f`，分支 `dev/1.0.0`。本轮开始时已有大量未提交的 C 阶段及直连改动；它们是本轮验证的输入，不记作本轮实现。未创建提交、分支、标签或暂存变更。

审计根目录为 `F:\Program\Agent\.run\s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670`，下文记为 **审计目录**。其中 `baseline.json`、`status-before.txt`、`worktree-before.diff`、`staged-before.diff` 和 `before/` 保存本轮前状态与直接修改文件的原始版本；所有测试与构建输出均在忽略的 `.run` 内。

实施前建立的计划：先验证现有能力和复现缺口，再补充现有身份、账本及审阅工具，修复过时打包夹具；执行定向测试、受影响回归、公开 control/matrix 和真实 600 秒专项；最后核对差异与报告。未规划 UI 重构、Provider 重设计、数据库迁移或新的证据体系。

全程使用合成账号、合成凭据、临时模型库、回环 HTTP/MockTransport 和隔离子进程。不读取系统凭据库或生产配置，不访问真实供应商，不安装依赖，不运行正式 90 次模型实验，不修改正式安装或远程资源。

## 2. D-01：候选与实验冻结准备

### 现有能力及确认缺口

- 原清单已有题集、判定材料、运行器、模型配置及预算绑定，运行前后检查产品摘要。
- 原源码身份仅覆盖部分本机 Python 源码，遗漏桌面、Rust 宿主及构建输入；原 bundle 检查可以接受空源码列表，未完整绑定桌面 EXE 和清单总摘要。
- 原尝试之间只核对部分输入；预检后产品变化仍可能进入下一次尝试。审阅未重新验证当前产品、题集、判定器和配置。
- 构建、安装、进程加载是不同证据。已有源文件和开发目录二进制不能自动成为已冻结候选或已安装客户端证明。

### 本轮修改

新增 `coding_acceptance_identity.py`，沿用现有 manifest 与 SHA256：

1. `s6-product-2` 记录桌面、本机核心、轻量运行时、exec-host、依赖锁定与构建输入的文件/组件摘要。历史服务器代理文件仅记录兼容来源；实际链路为账号认证 → 本机 IPC → 本机 Agent → Provider。
2. bundle 要求非空、无重复、安全路径的源码列表，核对列表总摘要、当前必需源码、桌面/sidecar/宿主与构建记录；摘要错误拒绝，源码缺失或变化不能冻结。
3. 每次尝试前及实验结束核对产品和运行器；审阅再次核对当前源码、构建产物、题集/判定材料、运行器及模型配置。变化使旧证据不适用于当前候选。
4. manifest 记录 OS、机器架构、Python 和启动解释器摘要、权限模式；未采样负载为 unknown。每次 IPC 产物保存能力响应、宿主能力、测试子进程 PID、启动文件摘要及只读查询得到的测试项目库 schema。
5. `build-remote-client.cjs` 只补充来源清单中的 requirements、入口 HTML、Vite/TypeScript 配置和统一构建包装入口；没有改变构建发布行为或依赖。
6. 实际构建后发现合法文件名 `modelSecrets.spec.ts` 使通用脱敏器误遮蔽摘要。`s6-product-2` 以 `source_files: [{path, sha256}]` 保存摘要，`files` 保留路径索引；历史 source 的 `sha256` 计算方式不变。读取时重建并核对索引/摘要，通用凭据脱敏规则保持原样。落盘及读回测试同时验证源码和 bundle 身份。

### 身份证据边界

| 身份层次 | 本轮处理 | 可支持的结论 |
| --- | --- | --- |
| 工作区源码 | 完整文件/组件清单、HEAD 与 dirty 状态 | 本轮测试所见源码；不推断二进制来源 |
| 独立构建产物 | 现有工具离线构建与文件 SHA256；结果见验证表 | 本地构建/打包检查范围内的产物 |
| 实际安装副本 | 未检查、未修改 | unknown |
| 运行进程 | 自己启动的合成 IPC 子进程 PID、启动文件及测试库 | 该测试子进程；加载组件内存证明仍为 unknown |
| 原生桌面及 UI 性能 | 独立列项 | 不用源码、浏览器或 IPC 推定通过 |

源码测试默认解析 `apps/exec-host/target/release/exec-host.exe`，本轮观测 SHA256 为 `91eb573430edf660bdc247a3e1cae918bb2d153e795a07061a691f7f48e65f7a`；其历史构建来源未重新证明。独立新构建宿主 SHA256 为 `dec3cb3cf81122454552f674231a9f1da83eb8fa6c13ddde820d262efe10cf94`，打包验证使用该新产物。两者不混称同一个二进制候选。

本轮源码 IPC 的实际能力响应记录 repository tools `2`，recovery/evaluation/direct-evaluation 契约 `1.0`；执行会话与工具契约为 `1.0`，execution/stdin/output_streaming 为 true，测试项目库 schema 为 7。执行能力接口内 `contract.pty/model_streaming/recovery` 仍为 false，顶层 `pty` 为 `probe_on_request`。已沿 `execution_sessions.py::capabilities` 核对：该函数只设置执行、stdin 和输出能力，其余字段保留 `CapabilitySnapshot` 默认值。不能将这份接口响应改写成所有运行时能力均为 true；模型流式、关联恢复及 PTY 的行为证据分别来自对应测试，不代表原生桌面已验证。本轮记录这一接口边界，没有改动公开能力字段。

## 3. D-02：开发题管线

继续复用公开 `external_public/catalog.json` 与受控参考实现。每次由新 UUID 目录重建项目，保留初始用户内容与前后文件摘要；判定器在隔离输出中执行固定断言，候选不得读取独立判定材料。新实验不得覆盖原日志或复用上次答案。

账本在发起可能产生副作用的请求前落盘启动记录并 fsync，完成记录追加哈希链。中断后缺结束记录、不完整计划、身份变化和缺证据均保持阻断。新增检查拒绝重复计划/尝试及重复 JSON 字段；重算的 `schedule_complete` 与 `experiment_complete` 不信任被手工改成 true 的汇总。

公开题即使按 development/holdout 分组，暴露状态仍为 `public_calibration`；control/matrix 的系统行为通过不计为模型独立完成。正式完整实验仍要求每模型 30 题 × 3 次、独立题集、隔离验证及独立交接回执，条件没有放宽。

实际 control/matrix 命令、次数、摘要及证据核验结果见第 7 节。

## 4. D-03：桌面流程与关联

### 源码已有支持

工作台已有项目/工作区选择、任务创建、审批影响范围、流式输出、执行结果与测试摘要、差异审查、暂停/继续、追加约束和关联恢复：

- `privateTransport.ts` 为每次 Tauri/IPC 请求生成 ID，拒绝不匹配帧，处理超时、取消与消费过慢，并清理监听器。
- `RecoveryPanel.vue`、运行流组合函数和服务 API 传递控制 request ID、状态版本及 checkpoint；重复或过时控制由后端拒绝。恢复是关联的新运行，原运行事件不改写。
- 本机 Runtime 保留 run、operation、tool call、execution 和事件序号；exec-host RPC 有请求 ID，输出有 execution ID 与宿主序号。未知副作用只形成待确认状态，不自动重放。

### 本轮补充及边界

`RuntimeClient` 对变更请求保留 IPC ID、方法、路径及允许的业务关联 ID，标记响应是否收到；只保存白名单关联字段，不记录请求头、凭据或请求正文，记录数有上限。测试通过真实本机 IPC 验证创建请求 ID 与 run ID 对应，测试库 schema 为 7。运行产物保留 executions、events、review 与关联信息，可以沿 operation/execution 核对宿主事实。

打包夹具改为认证后通过本机模型 API 创建合成配置。旧服务端模型端点返回 410；service 标签走本机 OpenAI 适配器。保留文件写入、Python/PowerShell 执行、审批、fullaccess 显式授权、宿主篡改拒绝、退出及历史记录断言。每次保存 `verification.json`，成功和失败均保留；Windows Job 回收所属子进程。

浏览器 fixture 只证明 Vue 流程与模拟 API 契约；Python IPC 证明本机接口；PyInstaller 产物测试证明打包执行器与宿主；这些均不能替代真实安装中 Tauri 窗口的端到端操作。

浏览器实跑定位后，仅补充以下直接相关的修复：

- 三个既有 E2E 文件共用合成登录夹具，阻断未匹配的本机 API；模型设置走显式回环开发模式，不接触真实服务。补齐分支接口，快照保留终态错误字段，防止轮询覆盖事件事实。
- 普通用户 `uiFlags` 已固定使用 Coding 工作台，旧 `ui=v1` 不再恢复旧壳；断言按现有角色隔离契约核对。缺少 S1 完成证据的旧事件仍应显示“结果未确认”，不能补造成功证据。
- `App.vue` 已将下线的 projects 视图归一到 Coding，但首页仍有跳转按钮。移除空态重复且无效的入口，失效工作区使用已有新建项目对话框；目录选择与授权逻辑保持原样。单元和浏览器检查覆盖打开、空输入禁提交、取消，以及失效状态入口。
- DEV 静态运行预览有审批事件/差异，却没有审批详情，导致卡片显示已处理授权且不展示预览。按同一投影生成 pending/consumed 记录并接入原 props；五态预览全部实跑，不修改正式审批 API 或终态。

这些小改动在已定位失败后补充到实施计划。构建前重新冻结源码；初次源码记录保留为历史，不把修复前后摘要混用。

## 5. D-04：故障、执行与隔离

未修改产品核心、Rust 宿主、六种合法终态、轮询时限、取消竞争规则或安全隔离。继续执行既有用例：

| 边界 | 现有可复核入口 |
| --- | --- |
| 模型断流、超时、协议错误、未知 usage 与成本、预算、防重放 | direct-models、model-evaluation、streaming |
| 工具非零、拒绝、初始修改及并发编辑 | acceptance、repository、completion |
| 强退、未知副作用、checkpoint 与关联恢复 | recovery、execution、sandbox |
| 持续终端、stdin、Unicode、末尾/大输出、取消与进程树 | execution、host、sandbox、execution-duration |
| 文件/网络/子进程/撤权的正反对照 | isolation、host、sandbox；AppContainer 与 network_policy=none |

`all` 纳入上述相关常规套件，但不包含单独持续时长专项。真实 600 秒测试已实际执行，测试原有 `time.sleep(600)`、610000 ms 命令时限、630 秒外层等待、输出起止标记及唯一序号断言保持不变。具体结果见第 7 节。

该长时专项使用源码测试默认的 `91eb57…f7a` 宿主；新构建的 `dec3cb…f94` 宿主只取得本报告单列的打包 IPC/公开校准证据，没有在新二进制上重复 600 秒专项。两个二进制之间不继承持续时长、PTY 或取消的验证结论；后续正式候选须按最终产物重新绑定相关宿主证据。

现有 `codingUiTelemetry` 是局部事件计数，不能给出宿主收到输出到 UI 可见的时间差。本轮没有真实前台原生 UI 的 100 个样本及负载记录，因此 UI p95、最大值、超阈值数均为 **未验证**；不以命令耗时、浏览器等待或历史 S5 成绩替代。

## 6. D-05：独立判定与报告

继续分别核对功能断言、验证命令、范围保护、最终文字真实性、人工介入及约束，不由模型自评。统计从冻结计划取得编码身份，按模型、family、category、split 汇总。新增 `failure_records` 保留每条原始失败及分组，归属未知时明确 `unresolved_requires_review`；本轮已定位的环境/工具故障在第 8 节单独说明。

审阅通过新目录追加回执和指标，不改写原始 attempts。回执必须绑定原 manifest、attempts 与逐次证据；重复字段/尝试、缺失/篡改文件、当前产品/题集/判定器/配置变化均拒绝。人工介入不能向下改写，不完整实验仍为 false。合成回执仅验证审阅机制，不是独立验收角色的真实回执。

正式独立率及分母、公开题污染、独立回执要求和 `direct_provider`/历史模式区分保持原契约。远程直连不标记 local_unbilled；缺 token、价格及中断用量继续为 unknown。M3 仍固定 blocked，本轮没有新增 F 阶段最终放行入口。

## 7. 实际验证与证据

### 7.1 工具与本轮测试

已核对 Python 3.12.13（`.venv/Scripts/python.exe`）、Node 24.14.0 / npm 11.9.0（`C:\ProgramSoftware\nodejs`）、Cargo/Rust 1.96.1（`C:\Users\likecandy\.cargo\bin`）、PyInstaller 6.21.0。主机为 `Windows-11-10.0.26200-SP0`。只给子进程补充现有工具路径；没有安装依赖、修改全局 PATH 或业务环境文件。

以下命令前缀为 `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite`，每一行均实际执行；证据目录位于 `.run/coding-agent-validation/`，含 `invocation.json`、`pytest-result.json` 和 observations。

| 套件参数 | 实测结果 | 证据目录 |
| --- | --- | --- |
| `direct-models` | 53 passed，5.30 秒 | `direct-models-2dacf39887474111a8cbe291d556110b` |
| `phase-d` | 最终 19 passed，6.26 秒 | `phase-d-c9b7e41a973540faaccb8d19f4ab7a92` |
| `model-evaluation` | 128 passed，99.51 秒 | `model-evaluation-3f14ca3278a94e9b975454649dd743ea` |
| `streaming` | 33 passed，9.36 秒 | `streaming-302f68c39e044e2584f4b197c4f5ddd3` |
| `external` | 113 passed，60.10 秒 | `external-ba0338e91206454590d25d6d31c9fe95` |
| `custody` | 27 passed，40.34 秒 | `custody-a8c46f95d01840dabbbfb4688387d367` |
| `acceptance` | 最终 426 passed，520.62 秒 | `acceptance-92a20ff3c105481bad80d927b46fb2c7` |
| `execution-duration` | 1 passed，601.17 秒，真实运行 600 秒命令 | `execution-duration-e3c7a2b467fc41079372499ea08491f5` |
| `duration` | 1 passed，151.63 秒，旧 API 130 秒脚本专项 | `duration-a5badae77c694874a41664edd550e3c5` |
| `all` | 最终 831 passed、1 skipped，877.80 秒，退出 0 | `all-11a056b41a8b4daba112c6ae0bcd091a` |

`duration` 原命令为 `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite duration`，在校准全部结束后串行执行；完整调用为审计目录 `legacy-duration-checks-1789458836066765900.json`。`observations/S4-LEGACY-DURATION.json` 记录启动准备 14.5 秒、命令观测时长 135.828 秒、退出码 0、子进程已退出，且 FINISHED 只出现一次。原 45 秒启动等待、145 秒命令等待及 129～145 秒断言不变。旧 `run_project_command` 入口仍仅在终态返回完整输出，`early_output_visible=false`；观测时 Agent run 仍为 running，此专项证明命令越过旧 120 秒限制，不证明整个 Agent 任务完成或旧入口支持流式。

`phase-d` 的递增验证另保留最初 5 failed、修复后 5/13/14 passed 以及 18 passed 的独立目录；落盘缺陷又经 1 failed / 18 passed 复现后修复，最终范围为 19 项。model-evaluation、streaming、external、custody、acceptance 和首次 all 由审计目录 `run_checks.py python` 顺序调用原入口，完整命令和原输出在 `python-checks-1789450108029852600.json` 与同前缀日志；每套启动器仍保留原 900 秒上限。早期 acceptance 为 425 passed，520.59 秒，目录 `acceptance-b5b11247604f471bb9384af4aade5717`；最终身份落盘修复及新增用例后再次运行原入口，426 passed，520.62 秒，完整调用见 `acceptance-final-checks-1789454874790856100.json`，不把早期结果混为同版。

两次 `all` 超时后，顺序使用原 `--suite` 入口补核下列分组。它们合计 326 passed、1 skipped，含重复文件，不转换为完整 `all` 成绩；各自原 900 秒上限不变。命令、日志见 `remaining-suites-checks-1789453721335482600.json`：

| 套件参数 | 实测结果 | 证据目录 |
| --- | --- | --- |
| `history` | 9 passed，0.92 秒 | `history-ad94e7001abf4eb280aa516d8ee8d8c0` |
| `sandbox` | 20 passed，93.80 秒 | `sandbox-e9c4d72456594c8fa8ef40f3de24373e` |
| `recovery` | 35 passed，47.94 秒 | `recovery-dfabf56f6f9c4ae284ac767785e567dc` |
| `execution` | 19 passed，23.77 秒 | `execution-9045fe89da304c158ff4ab103f33ee8b` |
| `repository` | 44 passed、1 skipped，9.39 秒 | `repository-7a468592681c4f04b0d21bc3943b0601` |
| `context` | 30 passed，10.04 秒 | `context-ca6f912187a94c379d13f4101b24e58b` |
| `completion` | 37 passed，18.37 秒 | `completion-ca41705a2963438c87258e497efb3930` |
| `local` | 58 passed，18.06 秒 | `local-5e460c95c9274d0a90c4da18742cd7ca` |
| `contracts` | 15 passed，0.70 秒 | `contracts-bbb1fa67d2c847e88d78bd42f3f0ebe8` |
| `baseline` | 8 passed，5.50 秒 | `baseline-78bc68d3b0e640bfb80a0ba61cd732c6` |
| `host` | 16 passed，140.73 秒 | `host-c055d28984b6489e8fe7651228853749` |
| `tooling` | 35 passed，9.48 秒 | `tooling-834ca1e612444f2f82ca703e09e5d496` |

符号链接分支跳过原因为 `当前 Windows 环境未授予创建真实符号链接权限`，不是本轮新增跳过；没有更改权限或跳过标记。

最终身份落盘修复后，待公开校准、完整候选校准及 duration 全部结束，再独立执行原 `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all`，在 900 秒原上限内通过。CLI 墙钟为 878.921 秒，完整调用/输出为 `all-final-checks-1789459019061568900.json`、`all-final-all-1789459019061568900.log`。`freeze_validation_inputs.py before/after` 核对产品来源及 56 个测试/运行器输入前后一致，结果见 `final-all-inputs-before.json`、`final-all-inputs-after.json`；没有把较早 425 项 acceptance 或分组覆盖替代本次整体结果。两次早期 all 超时仍保留在第 8 节。

桌面定向命令在 `apps/desktop` 执行：

```powershell
& 'C:\ProgramSoftware\nodejs\node.exe' node_modules/vitest/vitest.mjs run src/features/coding src/services/localExecutor.spec.ts src/services/privateTransport.spec.ts --config F:/Program/Agent/.run/s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670/vitest.config.ts
```

结果：35 文件、225 项通过，13.37 秒。独立配置继承原测试集合/setup，仅关闭 `.env` 加载、隔离缓存和报告；`vitest-result.json` 保留逐项结果。Vite CJS 弃用提示记录为工具警告，未升级依赖。

项目入口及预览修复后，使用同一集合和 `vitest-final.config.ts` 复跑，35 文件、225 项通过，11.56 秒；完整命令记录在 `desktop-tests-checks-1789452729922180600.json`，结果为 `vitest-final-result.json`。原结果未覆盖。

最终核对预览审批的 `confirm/filesystem.write` 元数据后，使用 `vitest-verified.config.ts` 对同一集合再验，35 文件、225 项通过，11.17 秒；记录为 `desktop-tests-checks-1789454147707639700.json` 和 `vitest-verified-result.json`。此后没有再修改桌面源码。

浏览器命令由审计目录 `run_browser.py` 调用，在 `apps/desktop` 执行：

```powershell
& 'C:\ProgramSoftware\nodejs\node.exe' node_modules/@playwright/test/cli.js test coding-run.spec.ts coding-artifact.spec.ts coding-workbench.spec.ts --config F:/Program/Agent/.run/s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670/playwright-1789452670806743200.config.ts
```

结果：27 passed，38.1 秒，无重试通过项。报告为 `playwright-result-1789452670806743200.json`，原始日志为 `browser-1789452670806743200.log`。独立 Vite 端口 14821、`envDir=false`、`reuseExistingServer=false`、合成 HOME；仅子进程设置 `VITE_LOCAL_FULL_BACKEND=true`，API 全部使用路由替身。保持原 60 秒用例超时、20 秒断言超时和一次重试规则；此处没有宿主到 UI 的延迟样本。

最终增加审批风险/能力和“未被标成已处理”的断言后，以 `playwright-1789454185790641400.config.ts` 再执行同一命令集合，27 passed，37.7 秒，无重试通过项。最终结果、日志、调用记录以相同 `1789454185790641400` 后缀保留；前轮结果未覆盖。

### 7.2 构建、打包与公开校准

独立宿主构建实际执行并退出 0，10.31 秒：

```powershell
& 'C:\Users\likecandy\.cargo\bin\cargo.exe' build --release --locked --offline --manifest-path apps/exec-host/Cargo.toml --target-dir .run/s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670/host-target
```

轻量 sidecar 由审计目录 `build_local_sidecar.py` 使用既有 PyInstaller 构建，退出 0。原命令为：

```powershell
.venv/Scripts/python.exe -B -m PyInstaller --noconfirm --onefile --console --name private-agent-local --paths F:/Program/Agent/src --distpath F:/Program/Agent/.run/s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670/bundle --workpath F:/Program/Agent/.run/s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670/pyinstaller-work --specpath F:/Program/Agent/.run/s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670 --exclude-module personal_assistant --exclude-module torch --exclude-module numpy F:/Program/Agent/src/private_agent_local/entry.py
```

`build-sidecar-invocation.json`、`build-sidecar.log` 保留调用与输出。sidecar SHA256 为 `5e61a83108412191b49497db9195ae4ed4216d6a2386aacc554f84d773230888`，新宿主摘要见第 2 节；这些都是审计目录内的新产物。

打包基础验证原命令：

```powershell
.venv/Scripts/python.exe -B scripts/verify-unified-client.py --bundle .run/s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670/bundle --work-dir .run/s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670/packaged-after --model-mode openai
```

OpenAI 替身通过，目录 `packaged-after/packaged-runtime-9000daa5f4f64763ba2777cfae2ef19c`，测试子进程 PID 8484；`verification.json` 的 `passed/sandbox_available=true`，4 条历史 run、合成登录退出、文件写入、Python/PowerShell、审批、fullaccess 授权及篡改宿主拒绝断言通过。基础命令只使用 sidecar/host，不要求桌面 EXE，故不能解释为完整候选冻结。

`sandbox_available=true` 是宿主能力信号；基础夹具包含既有 `full_access` 兼容正例，该分支使用现有可信执行路径，不能作为 AppContainer 隔离证据。本轮没有修改该权限契约。公开 control/matrix 及完整候选校准另行核对实际 `execution_mode=restricted`、`network_policy=none`，不由基础夹具的成功推导隔离门禁通过。

相同基础命令再分别使用 `--model-mode service`、`--model-mode ollama`，均退出 0，墙钟分别 36.219 / 33.843 秒。对应目录为 `packaged-after/packaged-runtime-794e44269f6548d7b5cfeded4db93f8c`（PID 35828）、`packaged-after/packaged-runtime-03ed69bbb2ec4010bf6edd28146db5bb`（PID 29692）。完整命令见 `packaged-checks-1789454382140506200.json`。两者 `real_model_called/native_desktop_verified=false`；历史 service 标签实际走本机 OpenAI 协议。

桌面构建使用独立前端/target/输出目录，实际调用审计目录 `build_desktop.cjs`；其中在 `apps/desktop` 执行：

```powershell
& 'C:\ProgramSoftware\nodejs\node.exe' node_modules/vue-tsc/bin/vue-tsc.js --noEmit
& 'C:\ProgramSoftware\nodejs\node.exe' node_modules/vite/bin/vite.js build --outDir F:/Program/Agent/.run/s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670/web
```

类型检查退出 0，11.779 秒；前端构建退出 0，CLI 墙钟 10.963 秒。随后 Tauri CLI 使用 `build --no-bundle --no-sign --ci --target x86_64-pc-windows-msvc --config <独立 JSON> -- --locked --offline`，退出 0，99.840 秒。实际完整 argv（含 JSON）保存于 `desktop-build-invocation.json`；JSON 副本为 `tauri-build.json`。未生成安装器或更新清单，未签名或启动窗口。原 Vite 大 chunk 警告与 Rust 10 条未使用代码警告保留，未改阈值或做无关清理。

初次构建后的身份写回失败不是源码变化，而是上文摘要脱敏误判；该失败保留。修复后先执行 `freeze_local_build.py before`，再执行 `node .run/s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670/build_desktop.cjs --recheck`，最后执行 `freeze_local_build.py after`。重新执行同一 Tauri 参数，退出 0，33.379 秒；新副本在 `bundle-rechecked/`，原 `bundle/` 未覆盖。前后源码身份一致，完整 bundle 的 `source_matches=true`，记录为 `bundle-identity.json` 与 `desktop-build-recheck-invocation.json`。

最终源码包含 414 个文件，工作区来源 SHA256 为 `d49c6e56453a5a44b51325bcdae201c63333f91c9152304114ad90953c2bf287`，详见 `source-before-desktop-build-serialized.json`。bundle 的源码记录数组摘要为 `293952ab9a33e50a57fd37a1025fb83e52aa444e1dc6be4eed8aaceb46dd9c42`，计算对象不同，不能与工作区映射摘要混淆。

| 独立最终构建文件 | SHA256 |
| --- | --- |
| `PrivateAgent-windows-x64.exe` | `e7098d2017f6968e393cde62c1db306d89307e2aa18e675f6ff3890e613492df` |
| `private-agent-local.exe` | `5e61a83108412191b49497db9195ae4ed4216d6a2386aacc554f84d773230888` |
| `exec-host.exe` | `dec3cb3cf81122454552f674231a9f1da83eb8fa6c13ddde820d262efe10cf94` |

公开 control/matrix 使用原命令串行执行，未提供模型配置，`connection_mode=fixture`。本轮调用记录为审计目录 `calibration-invocation-1789455632857972200.json`：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode control --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer --repetitions 1
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode matrix --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer --tasks PY01,PY09,PY10,VT07,RS01 --repetitions 1
```

control：30/30 系统行为通过，退出 0，CLI 墙钟 2078.969 秒。新目录为 `.run/coding-acceptance/control-9df9bd03d66f44c9b96f88168bf42bbd`；Python、Vue/TypeScript、Rust 各 10 题。PY09 实际应用暂停/继续控制，PY10 拒绝写入后保留文件；负例的系统行为通过不表示原编码目标完成。

全量审计实际执行 `audit_calibration.py .run/coding-acceptance/control-9df9bd03d66f44c9b96f88168bf42bbd`，退出 0：账本与全部引用证据摘要匹配、当前源码身份一致，30 条记录均 scope/evidence 完整、权限为 confirm，189 条变更 IPC 关联可核对。采集到的执行模式与网络策略均为 restricted/none；测试库 schema 为 7。`schedule_complete=true`、`experiment_complete=false`、`real_model_called=false`、`delivery_decision=blocked`；编码分母与独立完成计数均为 0，不能计算模型独立完成率。

control 的题集 SHA256 为 `533c6bc8973e22a4b4da2d9bb10176c8c800a6ba8223f6239a6b6d713fc201a3`，运行器集合摘要为 `6982d51e0ecb5f9ee3c8c67d28db800f8a9782af6d652e63b02e9c093cc9e5a5`，源码摘要为上述 `d49c6e…bf287`。manifest / attempts SHA256 分别为 `7fe04c56c11cfe4945069cb48b17d0ca229a99b9e03ba2ddb5ba23ff626f1746`、`39bf5c02d7d8fe5addaa4a021b65f7379dfd77aa723ddf7a66b54817d37f14e1`；逐文件完整身份及汇总见 `calibration-observations.json`。

实际追加审阅命令为：

```powershell
.venv/Scripts/python.exe -B scripts/coding_acceptance_review.py --evidence .run/coding-acceptance/control-9df9bd03d66f44c9b96f88168bf42bbd --reviews .run/s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670/public-development-review.json
```

退出 0，产生该 control 目录下的 `review-070dd072dc204dffaa5d80bc2e9d5cd7`。开发侧实际核对公开 PY01 的实现差异、验证输入/用户内容摘要、执行和最终文字，审阅仅针对这一条；manifest/starts/attempts 原摘要均未改变。角色为 `development_synthetic_pipeline_review`，不是验收侧独立回执；审阅后实验完整性仍为 false，M3 仍 blocked。调用与复核结果见 `public-development-review-invocation.json`、`public-development-review-observation.json`。

matrix：15/15 系统行为通过，退出 0，CLI 墙钟 954.656 秒。目录为 `.run/coding-acceptance/matrix-bf0e9595556543cebf1326e74fb6a051`；service/OpenAI/Ollama 标签各执行 5 题。全量审计退出 0，15 个工作区身份互不重复，93 条变更 IPC 关联可核对；证据摘要、当前源码与隔离约束均通过复核。service/OpenAI 实际路径都是 `/v1/chat/completions`，Ollama 为 `/api/chat`，不能把两个 OpenAI 标签说成两种独立线协议；此 matrix 不含 Claude，Claude 的替身协议测试范围另见 direct-models。真实供应商均未调用。

matrix 与 control 的源码、题集和运行器集合摘要相同。matrix 的 manifest / attempts SHA256 分别为 `81c242b8f151aba23e6b5654eab14b28638283ad5ef7f974cccd4676457963df`、`7e0812d8de7169bde380c82016c6f0d037e4d3ac313276d5230d4f90bc32a68c`。两轮共同审计还确认工作区身份数分别为 30/15；无失败记录，公开角色、零编码分母/独立计数、实验不完整和 M3 blocked 均保留。

一个可核对的源码 IPC 关联样例是 control 的 `service-PY01-1`：创建请求 ID `b4a32ed7c937477b9c1476c477cfc5c7` → run `04206b24-d2bc-4dbd-8ce3-c80311ebc219` → 验证命令 operation `d77a1d86-99d4-4fef-9915-e6e234117fbd` / execution `44218646-f007-446c-aabe-e05c50b5b631`。同一 artifact 的运行完成证据和命令输出引用这些 ID；该样例属于合成 IPC，不属于 Tauri 窗口操作。

完整 bundle 在基础三协议验证完成后，单独使用受限校准入口，不重复基础夹具：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode control --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer --tasks PY01,PY10 --protocol openai --repetitions 1 --bundle .run/s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670/bundle-rechecked --work-dir .run/s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670/packaged-full
```

实测 2/2 系统行为通过，退出 0，87.141 秒，目录为审计目录下 `packaged-full/control-0b07c6eaa46f4d2e9edd340917a2c311`。完整调用记录为 `bundle-calibration-checks-1789458716702398400.json`。全量审计退出 0，候选类型为 bundle、源码与产物摘要仍匹配、2 个工作区独立、11 条变更请求关联可核对；测试库 schema 为 7。实际启动文件 SHA256 为 sidecar 的 `5e61a8…0888`，命令事实中的宿主为新构建 `dec3cb…f94`，执行方式 restricted、网络策略 none；PY10 未获准写入。仍无真实供应商调用、安装或进程组件内存证明，桌面 EXE 仅构建和哈希核对，未启动窗口。

bundle 校准 manifest / attempts SHA256 为 `277d7cef41a46bcdf649eec57a932c3cf71670308e324a655c35398c8f9ab8fa`、`7345cf59c89ca0f3c16ebb42507de824db9e7226177aa79bfa44bd1c780c9504`。最终 `calibration-observations.json` 同时保存 control、matrix、bundle 三轮复核数据：47 条公开替身尝试均通过系统行为核验，各轮 `experiment_complete=false`、独立完成计数与编码分母为 0、M3 blocked。三轮校准未与完整回归或长时专项并行。

### 7.3 静态与差异检查

实际执行 `.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check`，结果 `protocol codegen in sync: OK`；执行 `.venv/Scripts/python.exe -B scripts/check_agent_v2_imports.py`，结果 `agent_v2 dependency rules: OK`。

实际执行 `C:\ProgramSoftware\nodejs\node.exe --test scripts/build-remote-client.test.cjs`，获准环境中 10 项通过；首次受限环境的 `spawn EPERM` 原错误保留。针对本轮 9 个 Python 文件运行 Ruff，通过。

最终 Ruff 命令如下，观察到 `All checks passed!`，退出 0：

```powershell
.venv/Scripts/python.exe -B -m ruff check --no-cache scripts/coding_acceptance_identity.py scripts/run_coding_acceptance.py scripts/coding_acceptance_schema.py scripts/coding_acceptance_evidence.py scripts/coding_acceptance_review.py scripts/coding_acceptance_transport.py scripts/verify-unified-client.py scripts/run_coding_validation.py tests/coding_acceptance/test_s6_phase_d.py
```

审计目录 `audit_workspace.py` 按开工 SHA256 核对增量并输出 `workspace-audit.json` 和 `incremental.diff`。未单独复制的 schema 原版本从开工 diff 重建并逐字节匹配开工 SHA256 后才用于审阅。初始路径清单漏记一个含中文名的既有 PDF，已只读核对它与 HEAD 的内容摘要相同；没有改动该文件。已核对的轮询、事件收集、终态完整性和独立完成判定 AST 与开工相同。

最终执行 `.venv/Scripts/python.exe -B .run/s6-phase-d-cbbf1d442bfa47d08e1c5034c2cc5670/audit_workspace.py`，退出 0：相对开工修改 18 个文件、新增 4 个文件，`unexpected_changes=[]`，其余开工文件摘要一致。`docs/project-state.md` 逐字节未变；HEAD 保持上述提交，暂存区为空。已审阅完整增量，`git status --short --branch` 核对既有工作区改动，`git diff --check` 退出 0；本轮文件清单见第 11 节。

已执行审计目录 `summarize_validation.py`，依据本轮 33 个 invocation/result 生成 `validation-observations.json`：最终 all 在原时限内通过且冻结输入未变，因此 `all_command_passed=true`；39 个测试文件全部纳入，业务配置/数据库模块未加载。各分组含重复文件，不能累加为唯一通过数，两个早期整体超时也没有被覆盖。

最终 all 运行期间另作一次 `--collect-only`，只收集 832 个用例顺序，未执行额外用例。调用与日志位于审计目录 `all-collection-e15efd79e95445e2bef99274b3eb5f11/`，汇总为 `all-collection-order.json`、`all-progress-observations.json`，不计入测试通过数。早期 all 的 phase-d 集合少一项，故只保留其进度字符数，不使用当前顺序冒充早期逐节点轨迹。进度字符不能用来认定具体耗时根因。

## 8. 失败归因与复验范围

1. 定向测试先复现 5 个工具缺口：源码范围不足、空候选清单被接受、预检后产品变化仍启动尝试、审阅丢失不完整状态、重复 JSON 字段被接受。完成对应修复后扩大到冻结输入、二进制篡改及实际 IPC 正反验证。

   最初失败目录为 `.run/coding-agent-validation/phase-d-direct-5f49d40a38fc480cad872fcb723449ed`（5 failed）；之后原 `--suite phase-d` 入口的 5 / 13 / 14 / 18 passed 目录分别为 `phase-d-6df6113eded04916bb86e0433b5ee353`、`phase-d-1d14865f91764132ab089de2b8087273`、`phase-d-308fc06fc90a4ab6be4b65bccd057857`、`phase-d-dec6113dce3e4604b0b080758db43529`。这些均为本轮范围逐步扩充的历史结果，最终 19 项结果在验证表单列。

2. 受限工具运行的 600 秒专项在创建 Windows asyncio 管道时出现 `PermissionError: [WinError 5]`，尚未启动 600 秒命令。原目录 `execution-duration-e693254a2e9c41a291f464665f6e06a7` 保留。按正常权限运行原命令后通过；没有改变产品 AppContainer，也不宣称历史权限问题已修复。
3. 旧打包夹具沿服务器配置模型，新打包执行器返回 `model_not_configured`。归属为过时测试工具；修正为本机配置 API 后继续验证。
4. 首次新版夹具配置请求因未保留 GET profile 返回的 `is_local` 字段触发 422；按真实模型契约保留该字段，未放宽产品验证。
5. 两次后续运行的 Python/PowerShell 工具失败，提示无法定位系统应用数据目录。只改 LOCALAPPDATA 定位尚不足；合成 HOME 必须实际创建 `AppData/Roaming` 和 `AppData/Local`，与现有 RuntimeClient 约定一致。修正夹具目录布局后原断言通过。未读取用户目录内容或修改正式数据。
6. 旧 `tempfile` 私有目录在受限工具中遍历出现 PermissionError，与命名管道及产品工具失败分开记录。新夹具使用既有继承 ACL 的 UUID 目录；旧目录与失败数据库保留，没有改旧 ACL 或清理。
7. Node 测试在受限工具中出现 `spawn EPERM`，同一现有命令在获准的子进程环境通过；不是构建逻辑失败。Ruff 定位到新增导入排序问题后作最小修正并复查。
8. 只读检索 acceptance 输出时，三个 `pytest-cache-files-*` 私有目录返回访问拒绝；这是取证目录遍历限制，不能改写为测试失败或测试通过。原测试结果与可读 invocation 独立核对；未修改这些目录权限。
9. 前两次完整 `all` 均在 900 秒触及既有上限，退出 124，目录分别为 `all-b186775210df4f67958c3a9831dc6bd5`、`all-869a86d9bc4046f281134f1957fb2184`。第二次独占执行，墙钟 900.234 秒，期间无并行构建、浏览器测试或校准。两次进度均超过 95%，但没有生成最终 pytest 汇总，不能记为完整通过；未观察到断言失败不能排除当次未完成用例的缺陷。原上限和断言不变，随后分组补核并在最终身份格式修复后第三次独立执行 all，831 passed / 1 skipped，877.80 秒。第三次通过仅证明这次最终输入下的结果；没有定位系统级耗时变化原因，不能说历史超时已经修复。
10. 浏览器原夹具缺合成认证、使用旧导航/输入选择器，且终态快照丢失错误字段；前两次定位运行由本轮主动中止，保留日志/trace，不给出完整通过数。第三次 `1789451998186068600` 为 21 passed / 6 failed；补齐分支 API 及现有文案后，第四次 `1789452475890569200` 为 25 passed / 2 failed。剩余两项实际定位到静态预览详情缺失与无效 projects 跳转，作上述小修复；最终 27 passed。没有删除有效断言、增加超时或把缺证据终态改成成功。
11. 首次构建后 `freeze_local_build.py after` 返回 AssertionError。逐文件核对确认 `modelSecrets.spec.ts` 的开工/当前摘要均为 `35df75c9f88d3d3a42d77a5a02a3a9b077838e178e14e1f58735f0cb172d46ac`，文件没有变化；落盘映射中的摘要被写成 `[REDACTED]`。因此撤回初步的“源码变化”归因，确定为本轮身份工具与既有脱敏器的格式冲突。目录 `phase-d-c791228c690f42b790f8ff325164b645` 以 1 failed / 18 passed 复现；改用路径/摘要数组后，`phase-d-5c71f2c7c336446694a8d159afc3dc3a` 19 passed，再加入 bundle 读回核验，最终 19 passed。未修改该用户测试文件，也未放宽凭据脱敏。

打包失败目录与脱敏数据库诊断保存于审计目录 `packaged-before/`、`packaged-after/`、`packaging-diagnostic.json`。查询只针对本轮合成库，未读取生产日志或账户数据。复跑使用新目录，原始失败未覆盖。

## 9. 项目记忆与历史差异

`docs/project-state.md` 是 2026-08-31 的 E 盘工作区、旧提交和当时联网代理/部署状态快照。当前 F 盘源码、HEAD、本机直连路径及 schema 通过 Git、实现、合成 IPC 和测试交叉核对；这些新证据不证明旧服务进程或实际安装已更新。

按本轮明确要求保留该快照，不更新日期或历史结论；相关持久说明只同步到本报告、测试 README、直连说明及后续计划 D 的旧调用链描述。未创建新记忆体系。最终摘要审计已确认历史快照及其他非本轮文件未被修改，结果见第 7.3 节；历史环境与当前源码的差异在本节记录，没有将旧环境状态改写为新环境已验收。

## 10. 五项结论与最小后续依赖

| 问题 | 本轮结论 |
| --- | --- |
| 1. D 本地开发与隔离验证是否完成 | 已完成本轮授权且可独立执行的 D-01～D-05 准备工作：必要改动、定向及完整回归、公开校准、独立构建、长时专项和证据审阅均实际执行。最终 all 为 831 passed / 1 项原有权限跳过；保留历史失败和各项证据边界，不代表 D 正式启动或退出 |
| 2. 原生桌面、性能和安装证据 | 已取得 225 项桌面单测、27 项浏览器测试、合成 IPC、独立构建与打包校准，以及默认宿主上的 600/130 秒专项。真实 Tauri 前台操作、安装/升级/回退、至少 100 个宿主到 UI 样本、加载组件内存证明未取得；新宿主没有继承旧二进制的长时/PTY/取消结论 |
| 3. B/C 是否仍有缺项 | 是。B 缺独立未暴露保留题及验收侧来源/控制/交接回执；C 缺授权目标模型的真实正负联调、版本/参数/用量/价格证据 |
| 4. D 正式实验前置条件是否满足 | 否。B/C 完整退出未满足，正式候选、题集及适用环境尚未共同冻结 |
| 5. D 完整退出条件是否满足 | 否。没有正式质量实验或原生桌面/性能完整结论，M3 继续 blocked |

建议后续顺序与最小输入：

1. 验收方准备未用于开发的正式题集、隐藏判定材料、来源/许可/污染记录及绑定摘要的独立回执；保持原 30 题、重复次数与编码分母契约，不能换用本轮公开校准成绩。
2. 为 C 明确专用测试账号、本机 profile/provider 非敏感 ID、协议/模型版本、上下文和采样设置、单次/总预算及真实请求授权。按 C 报告已有 schema 2 模板填写 `.run/s6-phase-c-direct-model.json`；会话仅在本机交互终端隐藏输入，供应商凭据由正式产品安全配置，不放入 JSON、CLI 或聊天。
3. 完成 C 预检及逐模型真实联调、独立审阅后，重新核对 A～C 状态。再冻结正式候选、正式题集、Windows/架构与权限组合，按最终宿主产物补齐持续执行、PTY/取消证据，并开展 D 原生流程及前台性能采样。本轮产物不能自动晋升为正式安装候选。
4. E～F 另有授权与退出条件，本轮停止在 D 本地准备边界。

下列命令已核对当前 argparse 和 C 直连路径，**本轮没有执行**；第二条会产生真实请求，须另行取得目标模型及预算授权，不能因本报告存在就直接执行：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode preflight --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer --tasks PY01 --model-config .run/s6-phase-c-direct-model.json
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode probe --catalog tests/coding_acceptance/external_public/catalog.json --isolation appcontainer --tasks PY01 --repetitions 1 --model-config .run/s6-phase-c-direct-model.json --authorize-model-calls
```

预检仅验证会话、冻结配置和实际隔离，不执行推理；预检成功不代表 C 退出。上述仍使用公开开发题，probe 成功也不证明正式独立完成率或 D/M3 通过。

## 11. 本轮实际修改文件

| 文件 | 本轮增量 |
| --- | --- |
| `scripts/coding_acceptance_identity.py`（新增） | 源码、组件、构建产物与未知安装/加载身份；当前身份复核 |
| `scripts/run_coding_acceptance.py` | 接入身份、逐次冻结检查、环境与 IPC 关联证据 |
| `scripts/coding_acceptance_schema.py` | 复用严格 JSON 解码，拒绝重复字段/非有限值 |
| `scripts/coding_acceptance_evidence.py` | 重复/身份校验、完整性复算函数及原始失败分组 |
| `scripts/coding_acceptance_review.py` | 严格回执、当前输入失效检查及完整性重算 |
| `scripts/coding_acceptance_transport.py` | 白名单 IPC 关联、测试启动文件/PID/数据库 schema |
| `scripts/verify-unified-client.py` | 本机模型夹具、独立目录、逐次结果及资源回收 |
| `scripts/run_coding_validation.py` | 增加 phase-d 并纳入 acceptance/all |
| `scripts/build-remote-client.cjs` | 补足构建来源清单 |
| `tests/coding_acceptance/test_s6_phase_d.py`（新增） | 19 项定向正反、落盘身份及实际 IPC 测试 |
| `apps/desktop/e2e/coding-auth-fixture.ts`（新增） | 合成账号与未匹配 API 阻断 |
| `apps/desktop/e2e/coding-run.spec.ts` | 本机登录、现有控件、终态快照及缺完成证据断言 |
| `apps/desktop/e2e/coding-artifact.spec.ts` | 本机登录、现有验证文案与终态快照 |
| `apps/desktop/e2e/coding-workbench.spec.ts` | 分支 API、现有导航、空态对话框、旧参数边界 |
| `apps/desktop/src/features/coding/components/CodingHome.vue` | 修复下线项目页的无效入口，复用新建项目对话框 |
| `apps/desktop/src/features/coding/components/CodingHome.spec.ts` | 空态与失效工作区的新建项目行为 |
| `apps/desktop/src/features/coding/components/CodingThreadWorkspace.vue` | DEV 预览接入审批详情 |
| `apps/desktop/src/features/coding/dev/codingRunPreview.ts` | 由原事件投影生成一致的静态审批记录 |
| `tests/coding_acceptance/README.md` | D 工具命令与证据边界 |
| `docs/direct-model-execution.md` | D 的直连兼容与身份说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s6-follow-up-development-plan.md` | 仅修订 D 旧代理措辞，链接准备报告，退出条件不变 |
| 本报告（新增） | D-01～D-05 实证、失败归因、限制与后续依赖 |

源码目录中的原有桌面、服务端、本机模型与阶段 C 测试改动均保留，未归为本轮修改。没有变更锁文件、产品 schema、安装配置或生产数据；`.run` 为隔离取证输出，不纳入提交。
