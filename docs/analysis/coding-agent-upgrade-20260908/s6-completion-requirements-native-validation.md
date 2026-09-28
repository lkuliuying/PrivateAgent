# S6：完成要求误提取修复与原生闭环验证

日期：2026-09-15～2026-09-16。源码目录：`F:\Program\Agent`。证据根：`.run/s6-completion-fix/`。

## 1. 范围和当前结论

本轮接续 [原生任务创建修复](s6-native-run-creation-fix.md)，处理用户要求的“完成要求误提取，并完成原生任务闭环验证”。B 保持个人学习范围；C 的真实模型历史通过不重复调用，也不改绑到新候选。不开展 E～F、正式质量实验或完整性能验收。

完成要求误提取已实际复现并修复，定向测试 69 项通过，独立候选、前端及打包 IPC 检查通过。**修复候选已在真实原生窗口完成“提交 → 创建 run → 审批 → 修改目标文件 → pytest → 查看已验证结果”闭环，也完成运行中取消和进程清理。** 完整 all 首次运行触及 900 秒限额；同清单诊断复跑为 **969 passed / 1 skipped，830.97 秒，退出 0**。跳过项受 Windows 创建符号链接权限限制，未计为通过；首次超时根因仍未确认。原冻结候选及上轮修复候选保持原样。

## 2. 根因、复现和最小修复

原 `src/private_agent_core/completion.py::task_requirements()` 先对全文检查 `_WRITE`，只要出现一个写入动作，就用 `_FILE.findall(message)` 对全文文件生成 `file_changed`。它没有区分文件属于写入、读取、执行还是禁止修改的语义范围。

原生输入“仅修改 sample.py，将 double(value) 修复为返回 value * 2。随后执行 python verify.py 并等待退出码。不要修改其他文件。”因此同时生成 `sample.py` 和 `verify.py` 的修改要求。上轮原生确实已修改 `sample.py`、运行验证脚本并得到退出码 0，却继续报告缺少 `verify.py` 的实际变化，最终被取消。该历史失败与本轮修改前的定向红灯测试相互印证。

本轮新增 `_file_change_targets()`，仅提取肯定写入动作范围中的文件；读取、参考、执行与否定写入范围结束该作用域。文件名中的 `fix`、`test` 等词先用等长空白遮盖，避免将文件名误认为动作。逗号和换行仅对纯文件列表继承写入范围，覆盖中文顿号、英文连接词及 Markdown 清单。保留前置宾语、通用目标、去重、显式 requirements、仅回答/预览策略和 32 项上限。

产品改动只涉及一个共享核心文件。前端、Tauri、IPC、授权、模型路由、运行时、恢复、审批和数据库契约均沿用原实现；没有通过写数据库、代替原生界面创建任务或放宽权限完成验证。

普通 `python verify.py` 的退出码 0 仍是未分类命令的 `validation_outcome=unknown`。既有运行时可收束为 `status=completed`，同时保留 `goal_outcome=unknown`、`verification_state=failed` 和 `output_validation_failed`。本轮没有把它改成 verified；新的原生成功用例使用已有明确退出语义的 pytest，普通脚本仍保留负例断言。

## 3. 修改与测试覆盖

| 文件 | 作用 |
| --- | --- |
| `src/private_agent_core/completion.py` | 按写入动作范围提取完成目标 |
| `tests/unit/test_local_completion.py` | 28 组提取边界、显式要求和数量拒绝、真实 ASGI/SQLite/磁盘完成判定回归 |
| `docs/analysis/coding-agent-upgrade-20260908/s1-completion-and-verification.md` | 追加当前提取规则、未分类命令语义和报告链接 |
| 本报告 | 记录实际结果、候选关系和未验证项 |

新测试覆盖原始中文任务、英文任务、前置宾语、多文件与多行列表、重复文件、空输入、读取/参考文件、禁止写入、预览、超过 32 项、显式要求冲突，以及“只修改引用文件不能满足真正目标”的负例。命令执行单测沿用现有测试替身；原生验证需要真实受限进程证据，二者不混用。

## 4. 已执行验证与首次失败

命令工作目录除特别注明外均为 `F:\Program\Agent`。证据表中省略的路径前缀为 `.run/s6-completion-fix/`。

| 实际命令 / 阶段 | 实际结果 | 证据 |
| --- | --- | --- |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite completion`，修改产品前 | 22 failed / 43 passed，23.65 秒，退出 1；包含原始任务误提取复现 | `.run/coding-agent-validation/completion-28c4b794770a4f208b548fa92bd137a5/` |
| `.venv/Scripts/python.exe -B .run/s6-completion-fix/checks.py completion`，初版修复后 | 1 failed / 64 passed；新增测试错误期待普通脚本生命周期 failed，实际既有语义为 completed/unknown | `completion-6790ed29/` |
| 同上，核对运行时后修正新增测试的生命周期期望 | 65 passed，21.26 秒；同时加强 unknown、错误码、原文件不变和命令不重放断言 | `completion-af414d99/` |
| `.venv/Scripts/python.exe -B .run/s6-completion-fix/checks.py all`，首次启动 | 自审发现多行文件列表退化为通用目标，主动停止该次所属进程；不是通过，也不是测试断言失败 | `all-329320b9/output.log`、`interrupted.json` |
| `checks.py completion`，补齐 4 组多行清单断言后 | **69 passed，22.49 秒，退出 0** | `completion-9370b48a/`；runner `completion-3e34175d2aee409b81f73d00499593c4` |
| `.venv/Scripts/python.exe -B .run/s6-completion-fix/check_public_requirements.py` | 30 道公开题 requirements/policy 与修改前精确一致；无模型调用 | `baseline.json` 和该脚本 |
| `.venv/Scripts/python.exe -B -m ruff check src/private_agent_core/completion.py tests/unit/test_local_completion.py`；`git diff --check` | 已执行，退出 0；交付复核命令也包含此检查 | `final-review.json` 保存交付检查的命令、退出码与输出 |
| `checks.py all`，最终代码第一次完整运行 | **900 秒超时，退出 124**；输出已有 597 个通过标记，尚未完成，未生成完整 pytest 汇总 | `all-35eeca10/`；runner `.run/coding-agent-validation/all-4d12ca8624d2479aa81941fd29ca93f0/` |
| `.venv/Scripts/python.exe -B .run/s6-completion-fix/diagnose_all.py collect` | 970 项收集成功；同一 all 文件清单，输出位置在宿主探测与恢复用例交界。尚不能据此确认超时根因 | `all-collect-0b0399ddfbfc4a6d977b386f7c67c0a6/` |
| `.venv/Scripts/python.exe -B .run/s6-completion-fix/diagnose_all.py execute` | **969 passed / 1 skipped，830.97 秒，退出 0**；包装耗时 831.703 秒，保持同清单、隔离插件与 900 秒限额 | `all-execute-1a68155b3fb1409aaa3b0bc2b1c8b439/` |
| `.venv/Scripts/python.exe -B .run/s6-completion-fix/build_candidate.py` | 退出 0；现有 PyInstaller 离线独立构建，414 项源码与清单一致 | `build-invocation.json`、`build-sidecar.log`、`candidate-identity.json` |
| `.venv/Scripts/python.exe -B .run/s6-completion-fix/desktop_checks.py` | Vitest **231 passed / 36 files**；`vue-tsc --noEmit` 退出 0；Chromium **7 passed** | `vitest-result.json`、`typecheck-invocation.json`、`playwright-result.json` 及三个日志 |
| `.venv/Scripts/python.exe -B scripts/verify-unified-client.py --bundle .run/s6-completion-fix/candidate --work-dir .run/s6-completion-fix/packaged --model-mode ollama` | 退出 0，打包 IPC 替身检查 passed；包括受限执行、审批及篡改宿主拒绝 | `packaged/packaged-runtime-5e455d42b0844dc19454d4e23789ebf7/verification.json` |
| `.venv/Scripts/python.exe -B .run/s6-completion-fix/native_session.py native-second-launch.json` | 原生闭环 verified；实际 pytest 3 passed，另一个运行中任务由界面取消，退出 0 | `native-b9c27a3c/`，详见第 6 节 |
| `.venv/Scripts/python.exe -B .run/s6-completion-fix/inspect_native.py native-second-launch.json`；`finish_native.py native-second-launch.json` | 最终只读核对通过：17 个已采集的 PID＋创建时间身份均已退出、替身端口关闭、租约释放、原生执行无活动记录 | `native-b9c27a3c/inspection-1789525214254.json`、`final-cleanup.json` |
| `.venv/Scripts/python.exe -B .run/s6-completion-fix/probe_symlink.py` | 命令退出 0，探测结果 blocked：`Path.symlink_to` 返回 `OSError / errno=22 / winerror=1314`；目标内容未变，未改变系统权限 | `symlink-probe-c9880dc1ea2b4d138c08913feeaa6734/result.json` |

前端包装脚本按顺序执行以下现有命令，工作目录 `apps/desktop`，配置文件均在本轮独立目录，禁止加载环境文件：

```text
C:/ProgramSoftware/nodejs/node.exe node_modules/vitest/vitest.mjs run src/features/coding src/services/localExecutor.spec.ts src/services/privateTransport.spec.ts src/api/http.spec.ts --config F:/Program/Agent/.run/s6-completion-fix/vitest.config.ts
C:/ProgramSoftware/nodejs/node.exe node_modules/vue-tsc/bin/vue-tsc.js --noEmit
C:/ProgramSoftware/nodejs/node.exe node_modules/@playwright/test/cli.js test coding-run.spec.ts --config F:/Program/Agent/.run/s6-completion-fix/playwright.config.ts
```

全部首次失败、中断和复跑独立保存；未延长既有超时，未增加 skip、弱化或删除有效断言。完整回归、构建、打包检查和原生任务依次执行。

all 的唯一跳过项是现有 `tests/unit/test_local_file_ranges.py::test_actual_symlink_rejected`，其原有分支在无法创建真实符号链接时跳过。在普通本机工具权限下，用同一 `Path.symlink_to` 另作隔离探测得到 `WinError 1314`，确认当前令牌缺少该创建权限；没有修改测试或系统权限来取得绿灯。真实 Windows junction、硬链接、AppContainer 及越权路径的其他断言实际通过，但不能替代这一项。若后续要求零跳过，应在本身具备该权限的测试环境执行现有 `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite repository`，本轮不改变当前系统安全设置。

诊断复跑仅将 `-q` 改为 `-vv`、增加 `--durations=20` 以及有界进度回执；40 个测试文件与 970 个用例保持一致，业务配置守卫报告 `business_modules_loaded=[]`。复跑在 641.56 秒通过第 597 项宿主检查，642.31 秒通过第一项恢复检查，此后完整结束。主要慢项为三语言隔离、真实 IPC 与输出排空；这些耗时不能反推首次超时的确切原因。首次记录只有进度点，没有当时的调用栈，本轮保留其超时未定位结论，不因复跑退出 0 而声称已解决历史超时问题。

## 5. 候选身份及旧证据适用范围

Git HEAD 为 `1dde393e29f3dbacd3647d11834b39824ac8323f`，工作区含既有未提交改动。本轮基线记录 1283 个文件及 129 份旧证据摘要，暂存区为空。

| 候选 | 源码摘要 | sidecar 摘要 |
| --- | --- | --- |
| 原冻结 `.run/s6-final-f146e704/candidate` | `49ea144c81522c10e3098e4f75cf18e68fc4d88fe9b36023c5e722299cda01f7` | `a03f1e97b990230f34269013e0ec68ce9d3eefc18ca3fa52b3fdc67fe5332ca6` |
| 上轮创建修复 `.run/s6-native-fix/candidate` | `dd4f72188ef83d5590c8a2603e91a9973534bad4a9c453b178f941059d98c76f` | `150972e96bd6bb21015eb896bafa56ea072b4c21d47d388b050803a471b4942c` |
| 本轮 `.run/s6-completion-fix/candidate` | `db8cc0dbbd9673ec9e8a3a3576801240e1f13780e98e29433567d2cf72e236da` | `5dbeb578f81ce4476962d08d4f35a615d1f96425b6f4c1ccc8022c7b2363c08c` |

三者桌面摘要均为 `e7098d2017f6968e393cde62c1db306d89307e2aa18e675f6ff3890e613492df`，exec-host 摘要均为 `dec3cb3cf81122454552f674231a9f1da83eb8fa6c13ddde820d262efe10cf94`。本轮重建 sidecar，复用经过源码组件摘要和二进制摘要核对的桌面壳、宿主及宿主摘要文件。完整六文件摘要见 `candidate-identity.json`。

相对上轮仅 `completion.py` 一个产品构建输入变化；相对原冻结候选还包含上轮 `files.py` 的创建环境修复。原 `frozen_not_accepted` 状态保持；新候选 purpose 为 `completion_requirements_fix_not_accepted`。它不是对原候选的覆盖或追认。

B、C 历史通过保持对应时间和候选绑定。相同桌面/宿主组件的旧证据可作为组件历史，不能代替本轮新 sidecar 的完成判定和原生组合验证；旧长时宿主首次取消失败的根因限制也不能由本轮普通取消测试消除。当前没有重复 C 云调用。

## 6. 原生窗口取证

第一次独立会话 `native-b0e73529` 停在“本地服务未能启动 / 客户端连接准备失败，请重试”，未启动 sidecar、未创建 run。保留 `startup-failed.jpg`、`startup-failed.txt`、`launch.json` 和白名单 inspection。工具中断后，2026-09-16 的只读检查确认已记录进程均不存在、测试文件未改、run 为 0；没有将中断补写为正常 session-end。

随后用 `.venv/Scripts/python.exe -B .run/s6-completion-fix/probe_profile_paths.py` 在新目录复现测试环境缺口：Tauri 依赖的 `dirs-sys 0.5.0` 使用 `SHGetKnownFolderPath(..., flags=0)`，会验证标准目录存在；空白隔离 USERPROFILE 未建 `AppData/Local` 时返回 `0x80070003`，补齐空目录后返回 0，并定位在测试 profile 内。证据：`profile-path-probe-3e5f61c6806f422d922f43c6df8974a2/result.json`。该路径失败与首次原生现象一致，但首次界面未暴露底层错误码，不伪称直接抓到了那次 Tauri 返回值。

只修正本轮测试启动脚本的目录骨架后，以同一候选执行：

```text
.venv/Scripts/python.exe -B .run/s6-completion-fix/native_session.py native-second-launch.json
```

第二会话为 `native-b9c27a3c`，实际进入登录页。测试模型仅监听回环 `http://127.0.0.1:12879`，模型名 `s6-fixture`；测试项目为该目录下的 `project`。登录由用户手动完成，不读取或迁移旧登录状态。模型选择、测试目录选择、任务提交与审批均使用真实窗口完成。

### 6.1 首次容量拒绝与显式重试

原生项目 `project_id=1` 已授权，工作区 `workspace_id=2`、会话 `session_id=3`。第一次任务创建成功，但默认 Ollama 参数 `llm_context_length=8192` 不足以容纳本次工具上下文，run `3babdd33-bbb1-49a4-b2b6-52d44c34ead4` 在 `context_manager.py` 返回 `context_limit`，状态 `limit_exceeded`。模型生成、工具、补丁、命令和审批均为 0。该 run 已正确提取仅修改 `sample.py` 以及 pytest 测试两项要求，没有要求修改测试脚本。

`direct_models.py` 取模型元数据和会话长度配置的较小值，因此本机替身即使声明 `131072`，会话默认值仍会限为 `8192`。通过此独立测试会话的原生参数设置改为替身已声明的 `131072` 后，再从界面显式提交一次任务。没有修改产品默认配置、正式用户模型设置或任何超时。保留 `first-run-context-limit.jpg/.txt`、`model-capacity-corrected.jpg`、`model-capacity-saved.jpg`，不删除首次失败。

### 6.2 实际成功闭环

成功 run：`22ce5684-fe76-4fb9-a5f4-7225a25e1a36`。

1. 原生选择测试项目和 `s6-fixture`，提交“仅修改 sample.py，并执行 python -m pytest -q tests/test_sample.py，不修改其他文件”。
2. 窗口展示补丁预览，确认仅将 `double(value)` 修正为 `return value * 2`，批准补丁；patch set `59094723-4955-4f9b-bf91-b1167b277c25` 为 `applied`，实际应用 operation `2cf17be5-0d97-4b30-a172-4db3116d8a98`。
3. 审阅并批准命令 `python -m pytest -q tests/test_sample.py`，保持 `restricted`、`network_policy=none`、`retention=run`、`timeout_ms=60000`，cwd 为该测试项目。
4. managed execution `03159f00-7d13-4a8e-8b73-30dfbf54a00d`，operation `704a7cf9-b34a-440f-9625-c220cb4a30c3`，实际 stdout 为 **3 passed in 0.01s**，退出码 0；执行结果 `command_kind=test`、`validation_outcome=succeeded`。
5. 原生最终显示“已验证完成”。SQLite 只读回执为 `status=completed`、`goal_outcome=verified`、`verification_state=passed`，两项要求均通过，第一次输出检查即通过。

两次审批分别为 `b0f4f1d4-d579-4b46-abe3-cd24e55b1ea5` 和 `9a020a7c-c5e7-45e2-bf60-bc7c7300f6ef`，均为 `consumed`。成功 run 共 7 次本机替身请求、6 次工具调用，其中两次 `read_execution` 是只读状态轮询；只创建 1 次受管命令、应用 1 份补丁，没有重放副作用。

`sample.py` 最终摘要为 `5948aa57ac423657d6b4c673410c2f1402675ca2a45fbaf091049a1b46fa9468`；`tests/test_sample.py`、`pytest.ini` 和 `wait.py` 均与开工摘要一致。stdout/stderr 的有界原始片段和 run/operation/execution 关联见 `inspection-1789524778899.json` 及最终 inspection。受限 Python 同时输出了 `warning: Failed to set cwd to temp dir`，本轮保留该警告；命令实际退出 0，未因此删去输出或宣称警告根因已解决。

可见证据：`project-selected.jpg`、`model-loopback-configured.jpg`、`task-before-submit.jpg/.txt`、`patch-reviewed.jpg/.txt`、`pytest-approval.jpg/.txt`、`native-verified.jpg/.txt`、`pytest-output-visible.jpg/.txt`。

### 6.3 运行中取消、重复运行与清理

成功收束后，使用同一测试项目从原生界面另行提交 `python wait.py` 取消用例，不要求文件修改。批准受限命令后，真实进程输出 `NATIVE_CANCEL_READY 14804`；取证到 PID `14804` 的创建时间为 `1789525145207` ms。此时 run 和 managed execution 均为 `running`，随后通过原生“取消任务”取消，未等到 60 秒自然结束。

- run：`13ecf072-ebf4-42b3-b4f2-ec359897faa6`，最终 `cancelled`。
- execution：`12acbf3b-3945-44d6-aacf-895655b37819`，operation：`ccba12ad-c650-4459-820d-38cb9e848da7`，最终 `cancelled`；没有伪造退出码或 verified。
- 审批 `eb9f2f0a-a47d-45fc-9143-ab777eae5cb8` 为 `consumed`；保持 `restricted/none/run/60000`。
- `cancel-running.jpg/.txt`、`native-cancelled.jpg/.txt` 保存界面“已取消”和“0 个运行中”；运行前后只读回执为 `inspection-1789525153737.json`、`inspection-1789525176055.json`。

全会话仅 3 个符合三次显式提交的 run：一次无副作用的容量拒绝、一次已验证完成、一次运行中取消。全会话共 9 次本机替身生成调用、0 次真实模型调用、1 份补丁、2 次命令、3 次已消费审批。显式重试与取消未产生额外 run 或重复写入。三个 run 的 `client_request_id` 实际均为 null；不能将不同 run ID 写成客户端幂等键验证。本轮没有原生快速双击测试，接口层幂等测试与该人工界面边界分别记录。

关闭该独立会话后，`session-end.json` 记录真实退出，`finish_native.py` 只读断言通过：已采集的 **17 个 PID＋创建时间**身份均不存在，包含 wait.py、exec-host、sidecar、WebView 和启动器；替身端口关闭、活动执行为 0、工作区租约释放、sandbox lease 文件为 0；参考文件仍未变化。进程可执行路径及磁盘摘要与新候选相符，这属于路径/文件绑定证据，不宣称检查了原进程内存或正式安装。

## 7. 未验证项与阶段边界

原生基本闭环、运行中取消和清理已通过。完整 all 诊断复跑退出 0，保留 1 项符号链接权限跳过和首次超时未定位两项限制；浏览器 fixture、打包 IPC 和纯单测各自独立记录，均没有替代原生结果。

候选保持未验收，目前不具备推进 E 的条件。异常重启恢复、纠错/审查、完整性能及历史长时取消限制仍需按适用候选分别核对；原生高频重复提交也未验证。自然语言规则只覆盖已明确测试的动作范围，普通脚本退出 0 不等于目标 verified。本轮不自动开展这些后续工作。

## 8. 项目记忆

已读根 AGENTS、`docs/project-state.md`、直接模型执行说明及 S1/S6 相关计划、readiness 与验证报告，并对照源码、Git 和原始证据。项目状态记忆是历史快照，本轮保持不改。当前修订追加到 S1 说明和本报告；上轮两份报告受旧证据摘要绑定，保持原文，不把它们当作本轮验证成绩。

## 9. 交付复核与证据入口

最终检查命令为 `.venv/Scripts/python.exe -B .run/s6-completion-fix/final_review.py`，命令、结果及断言回执写入 `.run/s6-completion-fix/final-review.json`。检查范围为：仅本报告和第 3 节列出的 3 个文件有本轮增量；其余 1280 个开工文件、129 份旧证据、两套旧候选共 12 个产物摘要保持；暂存区为空；S1 原正文与 `docs/project-state.md` 历史快照不变；414 项产品输入与新候选一致；原生成功、取消、无重复副作用及最终进程清理事实与白名单回执一致。脚本还检查辅助脚本语法、文档 UTF-8/空白/相对链接，并执行 Ruff、`git diff --check` 和 30 道公开题要求一致性核对。

证据索引命令为 `.venv/Scripts/python.exe -B .run/s6-completion-fix/finalize_evidence.py`，输出 `.run/s6-completion-fix/final-evidence.json`。索引只绑定本轮源码与文档增量、脚本、首败/复跑回执、构建身份和脱敏原生证据，不遍历或收录 profile、登录配置、凭据、业务 SQLite 原库、WebView 数据、请求头或模型提示正文。证据保留在本机忽略目录，没有上传、提交或发布。
