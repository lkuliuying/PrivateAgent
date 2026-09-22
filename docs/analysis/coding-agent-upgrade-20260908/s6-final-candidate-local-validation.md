# S6 个人学习候选冻结与本机验证

日期：2026-09-15（Asia/Shanghai）。范围沿用用户确认：B 使用已有公开测试集；C 使用本机客户端直连云 API；后续验证绑定同一份候选产物。本文不构成独立质量验收、正式发布或最新公开版本证明。

**当前结论：本次公开单题 C 联调通过，候选已冻结；原生任务创建失败，性能样本为 0，最终验收尚未完成。** 汇总回执为证据根目录的 `final-evidence.json`，状态是 `frozen_not_accepted`，绑定冻结清单及 56 份选定证据、测试脚本和测试材料的 SHA256。

## 1. C 的实际结果与冻结身份

用户执行的 `probe-03f47eff5f7b4515a159047d2862a248` 已核对原始启动账本、工具事件、补丁、验证记录、配置及产物摘要：`openai-PY01-1` 为 `completed / verified`，实际只修改 `src/domain.py`，Agent 内 `python -m pytest` 退出 0，外置功能判定通过，范围、隔离和预算检查通过。

目标为 `openai` 兼容协议、`https://api.deepseek.com`、`deepseek-flash`，公开 `PY01` 一次。实际 10 次模型请求、11 次工具调用、65,401 tokens（输入 63,767，输出 1,634）；活动时间 13.187 秒。请求上限 12、工具上限 20、token 上限 100,000、活动时间上限 60 秒。费用和不可变模型版本仍未知。本次取证未重新发起云模型调用。

证据根目录：`F:\Program\Agent\.run\s6-final-f146e704`。原 C 记录保留在 `.run/coding-local-probe/probe-03f47eff5f7b4515a159047d2862a248`。`phase-c-receipt.json` 是本次事实核对回执，明确为非独立审阅；原正式评审中的独立验收门禁保持原样。

冻结使用 C 实际运行的六个配套文件，未重建或替换其中组件。414 项产品源码输入匹配；HEAD 为 `1dde393e29f3dbacd3647d11834b39824ac8323f`，工作树有既有未提交修改。版本 1.0.0，Windows x64，`portable / unsigned / dirty=true`。

| 对象 | SHA256 |
| --- | --- |
| 冻结清单 `candidate-freeze.json` | `f4bf402afcffbbb66f5abcb5ef214a386e11c25c8f8d51991cf69a92ca417934` |
| `PrivateAgent-windows-x64.exe` | `e7098d2017f6968e393cde62c1db306d89307e2aa18e675f6ff3890e613492df` |
| `private-agent-local.exe` | `a03f1e97b990230f34269013e0ec68ce9d3eefc18ca3fa52b3fdc67fe5332ca6` |
| `exec-host.exe` | `dec3cb3cf81122454552f674231a9f1da83eb8fa6c13ddde820d262efe10cf94` |
| 配置 `retry-model.json` | `394fd3d72bd12f672f14bc46ae924805d5550396a0e35db6d28fbe87ad8af157` |
| 产品源码集合 | `49ea144c81522c10e3098e4f75cf18e68fc4d88fe9b36023c5e722299cda01f7` |

文件位于证据根目录的 `candidate/`。`exec-host.sha256`、`build-info.json`、`source-manifest.json` 的摘要也在冻结清单中。原构建记录中的 `phase_c_local_probe_candidate_not_final_frozen` 和未启动桌面标志保留其历史含义；后续冻结和实际启动由新记录证明，不能改写旧记录制造更早的验收。

## 2. 同一宿主的实际测试

使用现有测试和正式 `ExecHostClient`。取证插件只将宿主路径绑定为冻结目录中的 `exec-host.exe`，记录真实启动路径、PID、SHA256 和协议；没有替换测试断言或使用模拟宿主。命令均在仓库根目录、经工具审批的普通本机权限下执行。

命令前缀：`.venv/Scripts/python.exe -B .run/s6-final-f146e704/run_host_checks.py`。

| 参数 | 实际结果 | 证据子目录 |
| --- | --- | --- |
| `host` | 34 passed / 1 failed，134.57 秒 | `host-67ec73d7` |
| `duration` | 1 passed，601.24 秒；实际 600 秒持续执行 | `duration-735d7796` |
| `legacy` | 1 passed，150.56 秒；原测试的 130 秒命令及内部时限断言通过 | `legacy-05d1fe51` |
| `cancel-timing` | 3 passed / 2 failed，59.42 秒；首次诊断，计时方法存在局限 | `cancel-timing-72ab3b24` |
| `cancel-timing-v2` | 5 passed，33.47 秒；并行观测 PID 和进程创建身份 | `cancel-timing-v2-1a653a9c` |
| `cancel-original` | 1 passed / 8 deselected，16.35 秒；原失败测试原样复跑 | `cancel-original-29a74736` |

覆盖真实 AppContainer 文件和网络权限正反例、stdin、Unicode、PTY、服务、后代进程和并发等。每个目录保留 `pytest-result.json`、`invocation.json`、`actual-hosts.jsonl`；失败没有删除。

### 取消测试中的失败与复核

首次 `host` 的 `test_real_host_timeout_and_cancel_stop_process` 在取消返回后检查父 PID 时观察到存活，导致失败。未修改产品代码，原测试复跑通过；不能把首次失败改成通过，也尚不能确定其原因。

首次诊断在取消调用返回后才轮询 PID，混入了随后发生的清理时间，并且无法排除 PID 复用。它记录过约 8.875 秒的取消包装调用和 5 秒截止点仍存活的子 PID；这些原始记录继续保留，但不作为准确的进程树终止计时。

第二版诊断从发出取消的同时开始观测，以 PID 加创建时间识别原进程。五次原进程身份消失的观测上界分别为 1.364、0.910、1.254、1.068、1.031 毫秒；取消包装调用返回用时约 1.958～2.366 秒。它说明本轮五次原进程退出符合 5 秒阈值，并区分了后续清理耗时；它不能反推出首次失败的唯一原因。

## 3. 原生桌面与性能取证

### 已观察到的步骤

- 实际打开冻结目录中的 Tauri 程序，首次 desktop PID 为 46216。首次出现本地服务启动错误页；用户手动重试并登录后进入项目页，最初启动失败的根因未确认。
- 使用 `.run/s6-final-f146e704/native-acb4f148` 下的新用户目录、WebView 目录和本地数据目录。实际执行器数据位于该目录的 `profile/AppData/Local/com.personal-assistant.desktop/local-projects`；先前另建的系统目录联接没有成为实际数据入口，已移除，目标测试数据保留。
- 用户手动授权 `S6 原生验证` 项目，根目录为 `.run/s6-final-f146e704/native-project`。白名单核对项目 3、工作区 4、会话 5，目录一致且状态为 active、authorized。未对用户另外创建的项目目录执行测试。
- 原生窗口配置了本机 `Ollama` 替身 `S6 本机模拟 / s6-fixture`，端点为 `http://127.0.0.1:14867`，无需 Key。该替身只提供固定响应，不能作为模型质量或云 API 证据。
- 首次窗口达到测试启动器的 30 分钟期限后自动退出。用同一二进制和测试目录恢复，desktop PID 为 32692，执行器启动进程 44600、运行子进程 42960；用户再次手动登录，项目及模型配置保留。启动路径和磁盘摘要已核对，没有读取进程内存，不声明已证明内存中所有组件身份。

### 原生任务创建失败

任务要求修复 `sample.py` 的翻倍函数，并执行预置 `verify.py` 与 `stream.py`。原生界面三次提交均显示：

> 执行创建失败：后端拒绝了本次执行创建；请检查后端连接与配置后重试。

三次分别是默认模型首次提交、界面重试、明确选择 `S6 本机模拟 / s6-fixture` 后重新提交。相关测试库中 run 为 0、持续执行记录为 0；两段本机替身会话都没有生成调用，六个预置响应均未消费。`sample.py` 仍保持初始错误内容。错误文案本身不能证明具体 HTTP 状态或真实拒绝位置，根因保持未确认。

已保留首次错误截图 `native-acb4f148/task-create-failed.png`、明确模型后的截图 `task-create-explicit-model-failed.png`、白名单观察 `native-visible-failure.json` 和进程记录。没有通过修改数据库、代跑脚本或放宽审批来替代原生操作。

对照命令 `.venv/Scripts/python.exe -B .run/s6-final-f146e704/diagnose_native_create.py` 退出 0：同一冻结执行器在新的临时账号和私有 IPC 下返回持续执行能力可用，并成功创建相同任务文本和执行协议的 run，随后取消；模型调用为 0。证据为 `create-diagnostic-50a3e34b/result.json`。该对照的账号来源、启动环境及模型配置方式与原生窗口不同，只能排除“这份执行器在所有环境都不能创建任务”，不能替代原生通过或确定其失败原因。

### 未取得的证据与清理

原生补丁/命令审批、实际修改与测试、纠错、审查及运行中断恢复均未验证。虽然准备了 100 个输出标记和只读采样函数，但 `stream.py` 尚未执行，前台性能采样未启动：**样本数 0，p95、最大值、超过 1 秒数量和采样期间机器负载均未知**。600 秒宿主测试不能替代这些证据。

两个原生启动器和两个本机替身进程均已退出。最终按记录的 PID 与创建时间核对，原生测试进程及其后代无残留；临时联接不存在，测试目录保留。证据为 `native-acb4f148/final-cleanup.json`。原生登录配置属于隔离应用数据，汇总回执仅引用白名单证据。

## 4. 本轮命令与完整性复核

除第 2 节的六组宿主测试外，实际执行如下：

| 命令或检查 | 观察结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B .run/s6-final-f146e704/freeze_candidate.py` | 退出 0；C 原始账本、414 项源码、配置和六份候选文件核对后冻结 |
| `& .run/s6-final-f146e704/start_native_session.ps1` | 启动原生窗口，达到 30 分钟期限后退出 0，临时联接清理成功 |
| `.venv/Scripts/python.exe -B .run/s6-final-f146e704/native_resume.py` | 恢复同一隔离目录，取证结束后请求停止，退出 0；任务创建仍失败 |
| `.venv/Scripts/python.exe -B .run/s6-final-f146e704/native_fixture.py` 及 `native_fixture_resume.py` | 两个回环服务均启动并退出 0；恢复服务使用同一端点，原记录保留；生成调用均为 0 |
| 本机替身 GET `/api/tags`、POST `/api/show` | 两项元数据检查通过，不是生成调用 |
| `.venv/Scripts/python.exe -B .run/s6-final-f146e704/diagnose_native_create.py` | 退出 0；打包 IPC 对照可创建并取消任务，不等于原生 UI 通过 |
| `.venv/Scripts/python.exe -B .run/s6-final-f146e704/finalize_evidence.py` | 退出 0；56 份证据、脚本及材料，原生无运行/无命令记录、进程退出和联接清理核对完成 |
| `.venv/Scripts/python.exe -B .run/s6-final-f146e704/final_review.py` | 退出 0；1281 项基线中仅两份任务文档修改、新增本报告；其余文件、414 项产品源码、六份候选、七份原始 C 证据、配置及冻结清单保持一致；27 个本地链接可解析 |
| `git diff --check` | 通过；新增文档另行检查空白和完整内容 |

辅助 Python 脚本做过 AST 语法检查，PowerShell 启动器通过 Parser 检查；原生行为以实际运行失败为准。没有因文档变更重跑无关构建或产品单元测试。

## 5. 项目记忆与边界

已阅读 `docs/project-state.md` 及 B/C/D 任务文档。指定记忆仍为 2026-08-31 历史快照，不能替代本轮 F 盘源码、产物和运行证据。按仓库入口的明确约定，本次未获更新共享历史快照的请求，因此不改写它；本页和交接文档记录本次结论，并保留旧失败及其发生顺序。

证据目录被 Git 忽略，仅保证本机当前可检查。没有发布、安装、升级依赖、修改服务器或提交 Git；没有提取或记录真实密钥和登录令牌。

当前无需用户重复云调用、提供 Key、重新准备 B 材料或再次创建测试项目。后续需定位原生创建失败；修复若改变产品构建输入，应产生新的候选身份并重新判断 C 绑定，再继续原生和性能取证，不能直接改写本次冻结清单为通过。

## 6. 2026-09-15 修复候选后续核对

后续工作已用真实目录布局复现创建接口 422：Windows 环境准备在完整显式目录存在时仍查询缺失的默认 AppData，系统 API 返回 `0x80070003`，导致宿主能力探测失败。最小修复、先红后绿测试、完整隔离回归和独立 sidecar 构建见 [原生任务创建修复报告](s6-native-run-creation-fix.md)。

新候选位于 `.run/s6-native-fix/candidate/`，源码和 sidecar 具有新摘要，桌面与 exec-host 经摘要核对后复用。其真实原生窗口已创建 run、批准补丁与命令、修改 `sample.py`，执行 `python verify.py` 退出 0 并查看输出。下游完成要求误将 `verify.py` 列为修改目标，且普通脚本的业务结果仍未自动判定，随后原生取消，终态为 cancelled。新候选未验收，尚不能推进 E。

本页第 1～5 节仍描述原冻结候选在当时的失败，原清单及全部原证据未覆盖，状态保持 `frozen_not_accepted`。B 学习结论和原 C 单题通过保留历史适用范围；没有重做云调用，也没有把新原生结果回填为旧候选成功或取消首次失败已解决。
