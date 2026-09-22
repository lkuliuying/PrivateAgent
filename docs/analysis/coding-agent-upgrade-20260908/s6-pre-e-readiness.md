# S6：本机学习使用检查与历史准入记录

> **当前范围：2026-09-17，见第 36 节。用户已取消 E、F，目标仅为当前电脑上的 Agent 学习使用。** 不再判断“能否进入 E”，不要求虚拟机、旧安装包、多系统验证或发布材料。已有构建、测试与失败记录保留；本机使用按 [调整后的计划](s6-follow-up-development-plan.md#1-目标与完成边界) 核对。第 1–35 节的 E 准入、正式 D/M3 及五项缺口结论是范围调整前的历史记录，不再作为当前学习前置；取消阶段不等于这些检查已通过。

> **范围调整前的续轮：2026-09-17，见第 35 节。** 当时源码候选重建为 `.run/s6-gap-closeout-20260917/build-01/candidate/`；完整回归在 900.001 秒超时，939 passed call / 1 skipped call 不等于整套通过。原生窗口交由用户手测。已准备 15 份合成旧数据库和 E 环境方案，但未执行 E/F；当时五项缺口未全部关闭。原始证据及当时结论保留。

> **最新续轮：2026-09-17，见第 25 节以后，本机服务调整见第 32 节，最新准入状态与 build-06 见第 34 节。** 用户“进入下一步”指继续补齐严格采样与原生故障入口，不是执行 E/F。用户随后要求后续测试全部使用本机服务。本续轮证据位于 `.run/s6-pre-e-probes-20260916/`（下文 `P/`），当前探针候选为 `P/build-06/candidate/`，在全本机账号/模型入口基础上修正创建响应丢失时的事实提示。第 1–24 节及全部旧候选、四份手工回执、旧 C 绑定均保留历史语境，不计为本续轮成绩。build-05 完整 all 在 900.029 秒超时，只有 890 个 passed call 和 1 个 skipped call，不能记为整套通过；build-04 的历史 973 passed / 1 skipped 不替代它。原生测量尚无有效样本，四项历史异常及新的 Python 崩溃仍未解决。**个人学习 E 准入和正式 D/M3 仍阻断，不执行 E/F**。

记录日期：2026-09-16。仓库：`F:\Program\Agent`。本轮证据根目录：`.run/s6-pre-e-20260916/`，下文记作 `R/`。结论基于已经执行并保存的检查；首次原生运行明细审计截止北京时间 15:02，之后交由用户手工测试。16:38 完成的并发编辑回执及只读核对见第 12 节，16:46 完成的人工拒绝审批见第 13 节，16:53 强退及随后重开恢复见第 14 节，17:05 正常关闭与原树清理见第 15 节。尚无回执的操作不计为通过，当前剩余输入见第 16 节。

## 1. 准入结论与执行边界

**个人学习范围内，当前尚不具备进入 E 的工程准入条件。** 已修复前端重复创建与未知创建结果重试的关联问题，构建新候选，并完成隔离回归、候选宿主专项、600 秒运行及十次取消诊断。原生并发编辑、人工拒绝审批、运行中强退后关联恢复与禁止自动重放、正常关闭后的原树清理，经用户手测和关联核对已通过所列场景；阻断仍包括早前自动点击拒绝的异常观察尚未归因、严格“宿主收到输出至 UI 可见”性能边界未验证，以及未解释的历史失败。未知副作用仍保持待核对，不自动释放工作区或继续执行。本轮形成可核对的候选身份清单，状态为 **`candidate_not_accepted`**，不生成已验收冻结决议。

B 已按用户确定的个人学习范围完成；不重新要求独立保留题或独立验收回执。C 的公开 PY01 真实模型联调保留原候选绑定，仍为个人联调通过；本轮没有重新初始化或调用真实供应商。正式 D/M3 质量门禁与个人学习准入分别判断，见第 9 节。

用户随后要求“不要操控我的电脑了，告诉我怎么测试，我来进行”。已停止原生窗口操作；之后只整理本地文档、证据和手工测试入口。后续点击、输入、审批、关闭与强退均由用户执行。最后重开的隔离窗口已有用户正常关闭及 11 个原进程身份清理的实际证据；未收到的其他手工结果仍保持未验证。

未执行 E/F、正式 90 次实验、安装升级、系统安全设置变更、依赖安装、提交/分支/推送/发布。未读取或导出真实密钥、凭据、会话令牌；没有修改正式安装、生产数据或正式用户配置。合成命令保留 AppContainer、`execution_mode=restricted`、`network_policy=none` 和审批；既有打包测试中的可信执行正对照单独记录，不作为受限执行成绩。

## 2. PLAN：入口、基线与历史适用性

修改前已读取根 `AGENTS.md`、完整 `docs/project-state.md`，以及用户指定的五份文档：

- `s6-follow-up-development-plan.md`；
- `s6-b-c-final-candidate-readiness.md`，重点第 10 节；
- `s6-final-candidate-local-validation.md`；
- `s6-native-run-creation-fix.md`；
- `s6-completion-requirements-native-validation.md`。

只读核对 Git、暂存区、源码/测试、候选、原始账本与证据后，已提出并执行计划：保存基线；先补失败测试再最小修复；独立构建；按序执行受影响检查、完整隔离 all、构建和长时专项；分别记录浏览器、打包 IPC、原生窗口与性能；保留失败并审查 E 准入。本页为该计划的收尾，未将用户接手手测视为自动通过。

进入本轮时 HEAD 为 `1dde393e29f3dbacd3647d11834b39824ac8323f`，分支 `dev/1.0.0`，暂存区为空，已有 72 个 tracked 修改及多份未跟踪文件。`R/baseline.json` 保存 1284 个安全白名单文件摘要及 265 个受保护历史证据摘要；排除凭据类文件。后续 `R/review-evidence.json` 核对全部 265 项未变，HEAD/暂存区未变，产品输入只新增本轮两个前端文件的增量。最终文档检查另见 `R/final-review.json`。

| 历史事实 | 原始证据及核对 | 本轮解释 |
| --- | --- | --- |
| B：30 题、120 次控制、30/30 Agent 流程 | `.run/s6-learning-current-1973ec4364a349bc876f3776796d7cff/`；账本、90 个逐次产物摘要核对；`R/history-audit.json`、`qualification-audit.json` | 个人学习历史结果仍适用。题集/评估口径摘要匹配，当前 judge 摘要不同；不把旧控制记为当前判定器重新执行通过，不据此恢复正式盲评资格。 |
| C：公开 PY01，completed/verified | `.run/coding-local-probe/probe-03f47eff5f7b4515a159047d2862a248/`；账本及 3 个产物摘要核对 | 原候选源码摘要 `49ea144c81522c10e3098e4f75cf18e68fc4d88fe9b36023c5e722299cda01f7`，10 次请求、11 次工具、65401 tokens、13.187 秒活动时间。费用、不可变模型版本未知；不改绑新候选。 |
| 原冻结候选 | `.run/s6-final-f146e704/`；冻结清单 SHA256 `f4bf402afcffbbb66f5abcb5ef214a386e11c25c8f8d51991cf69a92ca417934` | 保留原 `frozen_not_accepted`。 |
| 原生创建与完成要求误提取修复 | `.run/s6-native-fix/`、`.run/s6-completion-fix/`，当前入场候选为后者 `candidate/` | 已核对来源与摘要；历史原生提交、审批、改 sample.py、pytest 三项、completed/verified、取消/清理均保留历史属性。 |
| 上轮 all 969 passed / 1 skipped | `.run/s6-completion-fix/all-execute-1a68155b3fb1409aaa3b0bc2b1c8b439/`，830.97 秒 | 是历史执行结果；本轮另有全量执行，不能互相替代首败。 |
| 历史宿主取消首败 | `.run/s6-final-f146e704/host-67ec73d7/`，34 passed / 1 failed | 原失败保留；复跑与新诊断不等于确认根因。 |
| 历史 all 900 秒超时 | `.run/s6-completion-fix/all-35eeca10/`，底层 `.run/coding-agent-validation/all-4d12ca8624d2479aa81941fd29ca93f0/` | 原日志无逐用例定位，根因仍未解决。 |

## 3. EXECUTE：最小修复及新候选身份

### 3.1 已定位的产品问题

`useRunStream.startRun` 在创建响应未返回时可再次递增 generation，导致首个成功响应被视为过期，同时再次发送创建；前端也没有为创建结果未知时的同输入重试保持请求标识。先增加四个定向用例，得到 **4 failed / 10 passed**，再修改现有 composable：

- 创建中或已有活动运行时保留当前创建、投影与流连接；
- 同输入的未知结果重试复用 `client_request_id`；成功后新的显式提交使用新标识；
- 输入改变、attach/detach 清理待创建关联，调用方显式标识继续保留。

产品增量只有 `apps/desktop/src/features/coding/composables/useRunStream.ts` 与对应 `.spec.ts`。没有修改核心、IPC、schema、审批或副作用恢复契约。完整增量见 `R/turn-diff.patch`。原有完成要求修复和其他会话修改均保留。

### 3.2 新候选清单

产品输入改变后，在 `R/candidate/` 独立重建桌面。既有 sidecar、exec-host 源码输入未改变，复用 `.run/s6-completion-fix/candidate/` 中已核对的二进制；新 `build-info.json` 记录此来源。原候选和原清单未覆盖。414 项产品源码输入与新清单匹配。

| 对象 | SHA256 |
| --- | --- |
| 产品源码汇总 | `c6af2704c390df240bc4302784ffe0325e7c5fa600562040be922f03d8e7dcd7` |
| `PrivateAgent-windows-x64.exe` | `45d9760468e06591c71ca1c2c2e05c57f83aae271f40c8b49261f262e6c105cc` |
| `private-agent-local.exe` | `5dbeb578f81ce4476962d08d4f35a615d1f96425b6f4c1ccc8022c7b2363c08c` |
| `exec-host.exe` | `dec3cb3cf81122454552f674231a9f1da83eb8fa6c13ddde820d262efe10cf94` |
| `exec-host.sha256` 文件 | `dbffb1ad8b37862893b73b98cce1dc1ab72d513cd416f33635167e0b84449dd1` |
| `build-info.json` | `cd8b34e412e4e89ccc129a9f089442ef8cbdb74cbedde112b506577c891de666` |
| `source-manifest.json` | `393036a9504cd03c0c79afc8f4cca9d59e5e2b3565ffb570e9af90d56dc9ae82` |

版本为 **1.0.0 / Windows x64 / portable / unsigned / dirty=true**，应用标识 `com.personal-assistant.desktop`，私有传输 `stdio-v2`。实际原生记录的 SQLite `user_version=7`；execution/completion/recovery 契约均为 `1.0`。健康响应 `protocol=1` 是另一层字段，不混写为传输版本。

候选实际 `/capabilities` 包括 repository tools `2`、recovery/evaluation/direct evaluation `1.0`；execution contract `1.0`，五个执行工具版本 `1`、session protocol `1.0`，stdin/output streaming 与文件/网络隔离能力声明。PTY 为按请求探测，workspace/account limit 为 2/4。contract 中 `pty/model_streaming/recovery=false` 等字段如实保留，不用其他层同名能力覆盖。完整响应位于打包契约证据；能力声明本身不等于所有组合已实测。

原生取证另外核对了候选路径、PID、创建时间及磁盘文件摘要。构建时 `launched_desktop=false` 保留原时点含义；后续原生启动有独立记录。没有宣称读取进程内存或验证正式安装副本。

## 4. TEST：实际命令、首败与复跑

以下命令的工作目录均为 `F:\Program\Agent`。路径前缀 `R` 在命令中写全。各 `invocation.json` 保存展开后的 argv、cwd、限额、来源摘要、退出码；`output.log` 保留原输出。完整回归、构建及长时执行串行进行，all 总限额始终 900 秒。

| 实际命令 | 实际结果及证据 |
| --- | --- |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/desktop_checks.py target` | `target-c0325f39`：工具沙箱 spawn EPERM，未运行测试；普通本机权限 `target-077a2e6f`：4 failed / 10 passed（新增定向首败）；修复后 `target-c636ff39`：14 passed，1.49 秒。 |
| 同入口 `full` | `full-68e3ae2f`：36 文件、235 passed，13.96 秒。范围为 coding、localExecutor、privateTransport、http；不是整个仓库所有前端文件。 |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/validate.py native-create` | `native-create-a19cfa19b31c4b379bd79bd2e5e7c611`：44 passed，10.58 秒。 |
| 同入口 `all`，首次 | `all-0a61e9be13574c15acf50d54c3602b9a`：333.477 秒退出 `3221225477 / 0xC0000005`，位于 VT01 文件摘要检查；不是正常通过，也不是旧 900 秒超时的根因证明。 |
| 同入口 `vt01`，诊断 | `vt01-1ae7850976f3491183de758f9c49a6d3`：1 passed / 10 deselected，75.59 秒。保留原断言，减轻观测器后台采样。 |
| 同入口 `all`，复跑 | `all-474f0a11c87a4421b2063673fddf75b7`：**969 passed / 1 skipped，812.60 秒**，外层 813.523 秒。真实 symlink 权限跳过。记录 612 条逐用例进度。 |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/build_candidate.py` | 退出 0；独立 typecheck、Vite、离线 Tauri 构建，总 166.902 秒。vue-tsc 15.39 秒、Vite 17.765 秒；保留既有 Rust/大 chunk 警告。 |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/validate.py host` | `host-92011382119f4430baa4552111271e68`：35 passed，117.49 秒，候选同摘要宿主。 |
| 同入口 `restricted-duration` | `restricted-duration-fa57f4c140c745f4b885f11cb122f47c`：1 passed，608.45 秒；实际执行 600 秒命令，单测调用 607.544 秒。未提高原 610000 ms 命令、630 秒等待及外层 900 秒限额。 |
| 同入口 `cancel` | `cancel-d1cbb93210484bcf972646e301c4c927`：10 passed，90.50 秒；5 次直接宿主、5 次托管会话，全部 restricted/none。 |
| 同入口 `packaged-contracts` | 首次 `packaged-contracts-760aecab4e6c4edcabe7ae663742db4a`：3 failed / 3 passed，36.56 秒。采证辅助代码错误：空 output 未归一化、分页读取了快照终点以后的事件。保留 `test-first.py`；修正采集且保留断言，复跑 `packaged-contracts-5aeb5395c06e43f388860e2c9f0e2352`：6 passed，41.83 秒。 |
| `.venv/Scripts/python.exe -B scripts/verify-unified-client.py --bundle .run/s6-pre-e-20260916/candidate --work-dir .run/s6-pre-e-20260916/packaged-smoke --model-mode ollama` | 退出 0；`packaged-smoke/packaged-runtime-0622ceacf2eb4caa93e992666b74e270/verification.json`。回环模拟账号/模型，打包 IPC、写入审批、宿主篡改拒绝及权限正反对照。不是正式安装或真实模型验收。 |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/browser_check.py` | `browser-0b425de6`：实际 Playwright 7 passed，17.0 秒，node exit 0。Python 外层打印含 `\u203a` 的日志触发 GBK `UnicodeEncodeError`，外层 exit 1；两层结果分别保留。只修正辅助脚本 stdout UTF-8，未再次执行浏览器测试。 |
| `.venv/Scripts/python.exe -B -m ruff check src tests scripts` | 失败：13 个 I001，涉及 12 个入场时已存在文件；逐文件摘要与基线相同。没有用排序清理覆盖其他会话修改。 |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/static_checks.py` | `static-checks.json`：Ruff 再次记录上述失败；`scripts/protocol_codegen.py --check`、`scripts/check_agent_v2_imports.py`、`git diff --check` 均退出 0。辅助入口退出 0 不表示其每个子检查全绿。 |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/review_evidence.py` | 退出 0；候选、历史保护摘要、Git 和增量核对；当时 20 份 Python 辅助脚本 AST 解析通过。 |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/final_review.py` | 首次审阅辅助脚本退出 1：误将新增文档 `git diff --no-index --check` 的差异退出码 1 当作检查失败，实际无诊断输出；保留 `final-review-first.py/json`。修正为该命令允许差异退出码且必须无诊断输出，产品测试断言不变；最终结果见 `final-review.json`。 |

**二进制适用范围：** all 沿用现有源码测试套件，默认加载源码构建宿主，摘要与发布候选宿主不同，因此其结果是当前源码回归，不是“全量测试均执行候选二进制”。host/cancel/restricted-duration 显式绑定旧完成修复候选中与新候选完全同摘要的 `dec3cb…cf94` 宿主；打包契约与打包冒烟实际加载新候选 sidecar/host；原生案例加载新桌面。三类证据不互相冒充。

600 秒执行关联为 run `a3b55261-5dd8-4e56-b645-248fd9ecea03`、execution `4006688a-afed-4713-a50c-62509a7b7aed`，restricted/none、输出 dropped=0、租约已收束。35 项宿主专项覆盖持续服务、stdin、Unicode、大输出、末尾输出以及受限/可信模式的各自正反对照；并不声明其中每项均使用同一种权限模式。

## 5. 原生窗口、打包 IPC 与故障关联

独立合成项目：`R/native-526b38de/project/`；隔离用户数据目录位于同一测试根。原生入口使用 Ollama 协议本机替身 `http://127.0.0.1:6000`、模型 `s6-fixture`。登录由用户手工完成，测试人员没有取得凭据。原生输出、审批、事件和截图保存在该目录及 `reopen-68cf5b91/`、`reopen-ea6a95f4/` 中。`R/review-evidence.json` 为只读 SQLite 白名单快照，不包含账号、凭据表。

| 场景 | 原生事实和关联 | 结论 |
| --- | --- | --- |
| 快速重复提交、修改及差异审查 | run `f7d50754-7ae6-49aa-9981-d915d8ecb354`，client request `be66202b-cbde-4217-b29e-5907b91c1189`；快速重复操作仅形成一个 run。审查 sample.py 补丁后审批，pytest 三项通过；两项审批 consumed。测试 execution `4dea0e92-2702-4bc4-b258-885ba397f719`，operation `021236c9-a2bb-43c7-a7d1-04d636ac64f0`。 | 本轮原生通过，completed/verified。创建响应丢失的定向注入仅单元/IPC 通过，不能称原生故障注入完成。 |
| 暂停、追加约束、继续 | run `ea902693-cd5b-4e91-b060-3d9b4683eb59`，在待审批命令处暂停，旧审批 cancelled；添加只读约束后恢复同一 run，最终 answered，无 command execution。三个 control request 均 applied，result_run_id 相同。 | 本轮原生通过。此前 25 秒只读操作结束后才点击暂停的尝试单列，不算暂停成功。 |
| 模型断流与显式纠错 | `d71fa273-d7ce-4a57-af30-a2f4a8240235`：`model_stream_interrupted`，1 次模型、0 工具；用户界面的显式新请求 `8473a2f3-5e41-46fc-94a3-c4f0165d17ec` answered。 | 本轮原生通过已覆盖情形；无自动模型重放。 |
| 工具非零退出 | `f83441cb-a7f6-40bc-bb2c-14e9770c5d70`；execution `b0001254-efcc-4c2b-819d-533539b1b322`，operation `8f0b11fd-c5fd-452f-a1f4-e03a44fc8df1`；真实 exit 7，unmet。 | 本轮原生通过错误反馈，不把失败声明 verified。模型收尾有重复文本请求，但命令只执行一次。 |
| 审批拒绝 | `707b9667-d55a-48ad-975a-da95e084e5ce`；工具尝试点击拒绝，后续审批 `2d4e05e6-30d3-4d58-a427-5f46959e8ec0` 却为 consumed，execution `6fa4a6f6-b327-4c88-b236-77d1e92244ef` 确实退出 7。 | **未解决，阻断。** 首次坐标点击偏移，后一次访问树元素标为“拒绝”；无法证明实际触发的是拒绝路径。源码事件绑定检查正确、IPC/浏览器拒绝测试通过均不能关闭本次原生异常。禁止据此宣称全部无越权执行。 |
| 人工拒绝审批补测 | 用户手工拒绝 `manual_deny_8310021f.py`，run `537fc791-d221-4d51-a5bb-3f73323ba25b`；审批 rejected，0 个托管执行，文件摘要不变，租约 released。 | **本次人工原生拒绝场景通过**，见第 13 节；不把上行历史异常改成通过，也不推断旧点击必然误触。 |
| 并发编辑 | 首次交接时未执行；后续用户以独立 `manual_concurrent_cf6c66bb.py` 完成手测，run `dc9846a5-2fd8-4947-b522-08a3dbf11e75`。批准前更改脚本，审批后的再校验拒绝启动；0 个托管执行、租约 released。 | **已通过本次原生并发编辑保护场景**。完整回执见第 12 节；原用户接手时的未验证快照保留。 |
| 强退、关联恢复、未知副作用 | 初次交接时只验证等待审批中断。后续用户实际强退 run `a062cb78-b03c-409d-8356-dacc04d5587e` 的执行中桌面，16 个原进程身份 145.6844 ms 内消失；重开保留原 run/execution，unknown、不重放、计数仍一次。 | **第 14 节所列原生强退恢复场景通过**。工作区租约为 reconcile，不冒称已释放；人工消解 unknown 后继续未执行。 |

暂停三个 control request 为 `77e327c1-52af-4991-b84b-2c5f12a8ee51`、`7924a015-21a6-45ea-9a7a-7c6e54a42f5d`、`cb8a9017-a5f0-41f2-9d1f-d8547d425f67`。native 快照中 execution 的 run/operation 关联、host 摘要、restricted/none 和输出引用均可追查；不从缺少字段的摘要推断传输 request ID。

打包 IPC 六项独立证据覆盖同 request 去重、活动冲突、暂停/steer/resume、新请求、断流与显式重试、拒绝/非零/并发变更、强退 sidecar 后 unknown 与禁止重放。它们实际执行候选 sidecar，但没有操作原生 UI，故原生缺项继续保留。浏览器七项 fixture 也单独归类。

## 6. 取消计时、性能样本与未解决失败

### 6.1 取消和首败诊断

`R/cancel-d1cbb93210484bcf972646e301c4c927/cancel-samples.jsonl` 保留全部十次。以 `perf_counter` 在发出取消请求之前计时，用 PID 加进程创建时间识别原父子进程，每 5 ms 左右观察，检查原树消失和租约清理。十次均在 5 秒内，原树消失观察上界最大 **19.1571 ms**；取消 API 返回最大 **3106.7721 ms**。两种耗时分别报告，不能从 API 返回后重新起表。该循环未复现历史裸 PID 检查失败；不能反推历史首败必然是 PID 复用。

历史取消首败和历史 all 超时均进行了有界核对；历史 all 只有约 61% 的点状输出，缺少逐用例时间。当前首次 all 又在 VT01 中发生 Python 原生崩溃，`R/python-crash-event.json` 的 Windows Event 1000 与测试子 PID 匹配，模块为 Python312.dll、异常 `0xc0000005`。这证明崩溃事件存在，不证明观察线程是根因。保留原观察器/脚本；轻量观察器禁用后台 CPU 线程和周期 faulthandler 后，VT01 与 all 各复跑一次通过。产品断言、总超时和套件未放宽。

**三项均保留未解决：历史首次取消失败、历史首次 900 秒超时、本轮首次 Python 崩溃。** 后续最小诊断是保留逐用例起止与同一进程身份，按同一 900 秒限额在可记录崩溃转储的独立环境复现；不无限重跑、不将后续绿色结果覆盖原失败。

### 6.2 原生前台延迟：仅代理测量，严格门禁未验证

合成脚本连续输出 `LATENCY_000` 至 `LATENCY_099`，间隔 0.35 秒，最后输出 FINISHED。每条包含子进程 UTC 与 QPC 信息。观察器保存每次 UIA 树、截图、采样时刻与负载，以首次出现标记的 UIA 观察配对执行事件；每次调用结束后约 100 ms 再采样。所有帧和样本保留，不选最快记录。

起点取 `ExecHostClient` 收到 exec-host JSONL 后的 sidecar 时间戳，输出事件还可能使用批次首条时间；**不是 Rust 宿主读取子进程管道的时刻**。终点是 UIA 首次可读取，**不是有同步时间戳的首次可见像素**。UTC 在同机配对，第四会话同时保留 `performance.now`，与 UTC 增量差最大约 0.805 ms；这不证明其他进程的时钟校准或显示合成误差。不能把时间数字的小数位解释为真实测量精度。

机器为 Windows 11 Pro 10.0.26200、i7-13700K、16 核/24 逻辑处理器、32 GB。负载由观察器 `os.cpus()` 增量计算，非独立性能实验环境。

| 尝试及原始路径 | 全部样本 | p95（nearest rank） | 最大值 | >1 秒 | 负载及结果 |
| --- | --- | --- | --- | --- | --- |
| `native-526b38de/reopen-68cf5b91/latency-analysis.json` | 56，218 帧 | 11604.942 ms | 12306.908 ms | 38 | CPU 均值 20.781%、最高 53.414%；最小空闲内存 15593295872 B。替身无间隔轮询耗尽 64 次模型预算，run limit_exceeded、命令取消，未达到 100 样本。 |
| `native-526b38de/reopen-ea6a95f4/latency-analysis.json` | 100，178 帧 | 884.732 ms | 1077.146 ms | 1 | CPU 均值 21.718%、最高 52.120%；最小空闲内存 16412286976 B。替身固定 0.8 秒响应节奏，100 条和 FINISHED 完整，真实 exit 0。 |
| 两次全部样本的诊断汇总 | 156 | 9854.074 ms | 12306.908 ms | 39 | 两次负载/替身节奏不同，此汇总不作为同一工作负载合格判定；用于明确未丢弃慢样本。 |

第二次 run 为 `ffdd66bc-4eaf-4408-af1a-0bea0dbc1276`，execution `121c7a93-6665-4535-abee-022dcbebea5b`，operation `d06d37c7-1420-4465-b36a-e390184cca82`。输出 3424 bytes、SHA256 `db19dd1f1545d50fd4a273761c6c8c2e05edcc8d9c25b565b26fc498ebcb6f5d`；unclassified 命令验证为 unknown，不能称整体 verified。另有一次未实际批准、零样本的限时结束尝试也保留。

第二次代理测量 p95 小于 1 秒，但严格边界未满足，**S6-T07 仍未验证**。最小后续为明确 Rust 接收时刻与原生绘制可见时刻的测量机制、校准同机时钟并记录探针对负载的影响，再在固定候选/固定场景采集至少 100 个完整样本。新增产品测量代码如改变构建输入，须新目录构建和相应复验；不把截图肉眼计时、浏览器 DOM 时间或该代理测量替代严格门禁。

## 7. 符号链接与环境前提

当前 all 的一项跳过为真实 symlink 的 `WinError 1314`。`R/symlink-environment.json` 显示当前令牌没有 `SeCreateSymbolicLinkPrivilege`，未检测到启用开发者模式的值；没有修改系统设置。AppContainer 等隔离测试通过不等于真实符号链接已测。

本机没有已核实可用且具有适当权限的第二个隔离环境，因此本轮未执行权限补测。仅在已经具备适当创建符号链接权限的独立 Windows 测试环境中，保留相同源码/候选摘要，执行：

```powershell
Set-Location F:\Program\Agent
.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/validate.py symlink
```

该命令尚未在上述权限环境执行。应取得实际 passed 和链接拒绝证据；再次 skipped 仍为未验证。不得为补测开启开发者模式、修改策略或放宽产品隔离。

## 8. 逐项准入矩阵

“已通过”只指所列层次及本轮执行；“历史证据仍适用”不增加本轮测试数；“需复验”指已有相邻证据但目标层次尚未闭合；“未验证”没有满足目标的实际执行；“阻断项”禁止据此放行。

| 项目 | 状态 | 适用范围与剩余缺口 |
| --- | --- | --- |
| B 个人学习范围 | 历史证据仍适用 | 120 控制及 30/30 流程已审计，不增加个人独立保留题要求。 |
| C 公开 PY01 真实联调 | 历史证据仍适用 | 保留原来源与候选；新候选没有新增真实模型质量成绩。 |
| 新候选源码/桌面/sidecar/host/契约 | 已通过 | 414 输入、六个文件摘要、运行路径和 schema/能力可核对；正式安装身份未验证。 |
| 重复提交与未知创建重试修复 | 已通过 | 先红后绿，受影响前端 235 passed；原生重复提交一 run；创建响应丢失注入仅单元/IPC。 |
| 活动运行冲突 | 需复验 | 单元和真实候选 IPC 拒绝通过；独立原生冲突路径未完整采证。 |
| 原生补丁、差异审查、pytest、完成真实性 | 已通过 | 独立合成项目 completed/verified；不是模型独立完成率。 |
| 原生暂停/追加约束/继续 | 已通过 | 同一 run，旧审批失效，无命令执行。 |
| 原生断流、显式纠错、非零退出 | 已通过 | 所列具体场景通过，无命令重复执行或伪造 verified。 |
| 原生审批拒绝（人工补测） | 已通过 | rejected、consumed_at=null、决定早于过期、0 个托管执行、租约 released；见第 13 节。 |
| 早前自动点击拒绝的异常 | 阻断项 | 旧点击观察与 consumed/执行事实冲突，根因未解决；后续人工通过不覆盖旧记录。 |
| 原生并发编辑 | 已通过 | 用户手测、文件前后摘要及原生 SQLite 记录一致；更改后的脚本未启动，无托管执行，租约 released。见第 12 节。 |
| 原生强退与未知副作用恢复 | 已通过（所列场景） | 第 14 节：原树 16 身份退出、原 run/execution 关联、unknown、计数一次、无新运行或副作用重放；租约保持 reconcile。人工消解未知状态后继续未验证。 |
| 600 秒、持续服务、stdin、Unicode、大输出与尾部完整性 | 已通过 | 候选同摘要宿主专项 35 项及受限 600 秒专项；不继承为正式安装成绩。 |
| 取消请求起点、PID+创建时间、5 秒树退出 | 已通过 | 十次新诊断通过、最大观察上界 19.1571 ms；历史首败单独保留。 |
| 原生前台延迟严格边界 ≥100 样本 | 阻断项 | 有 100 个完整代理样本及 56 个失败尝试样本；起终点不满足指定边界。 |
| 首次取消失败/首次 900 秒超时 | 阻断项 | 有界诊断后仍未解决，不能因复跑通过关闭。 |
| 本轮首次 all Python 崩溃 | 阻断项 | 原生崩溃已证实，根因未定；后续 all 969/1 不关闭。 |
| 真实 symlink | 未验证 | 当前 WinError 1314；仅适当权限隔离环境补测。 |
| all 及静态检查 | 需复验 | 当前源码 all 969/1；Ruff 13 个既有 I001 未清零，未冒称静态全绿。 |
| 原生会话最终退出/清理 | 已通过（所列进程树） | 第 15 节：用户正常关闭后，11 个已记录 PID+创建身份全部消失；会话 desktop_exited。未知工作区仍为 reconcile，不将物理退出等同于副作用核清。 |
| E 安装、旧数据迁移、程序回退 | 未验证 | 按要求未开始，需先关闭上面工程阻断，并确定目标环境与旧版本材料。 |

## 9. 正式 D/M3 尚未满足的门禁

个人 B/C 完成不等于正式 D/M3 通过，仍缺少：

1. **D-01/D-02/D-05、S6-T09：** 正式题集与开发/保留集隔离、冻结的模型身份/配置和统计口径、完整 30 题各 3 次的 90 次实验、独立审阅、默认模型预定义编码分母上至少 80% 独立完成率。公开 PY01 单题与本机替身不能替代；当前不可变模型版本、费用也未知。本轮不启动该实验。
2. **D-03/D-04、T02/T03/T05/T07/T08：** 早前自动点击拒绝的异常尚未归因，严格 UI 延迟、真实 symlink 和未解释失败尚未闭合。并发编辑、人工拒绝、执行中强退后关联恢复及不重放的原生场景已补齐；人工核清未知副作用后的继续、独立原生活动冲突等剩余范围仍按矩阵记录。已有单元、浏览器和 IPC 证据不能提升为完整原生证明。
3. **D-01、T08/T10：** 当前仅一台开发机器和便携候选；声明支持的 Windows、标准用户权限、真实安装与旧新组件组合没有完整实测矩阵。
4. **T11：** E 的无源码/无开发 `.venv` 干净安装、schema 3–6 与同版本 7 独立副本升级/重开、旧程序拒绝或安全回退尚未进行。准备材料至少需要目标 Windows/架构范围、干净测试机或快照、明确旧安装包及脱敏独立数据副本；不需要真实凭据进入报告。
5. **T12/F：** 匹配最终候选的交付决议、分发身份/签名策略、文档和更新回退材料未形成；本轮停止在 E 前。

T01/T04/T06 等已测路径有通过证据，但正式门禁按完整声明范围审核；未测保护项不能由其他通过率抵消。上面正式题集/独立审阅材料只属于正式 D/M3，不重新作为本次个人学习 B 的门槛。

## 10. 用户手工测试：按一项一项进行

以下步骤只是交接说明，**尚未执行的步骤不得记为通过**。无需重新跑 969 项或 600 秒专项。请只操作本轮隔离版，项目位于 `R/native-526b38de/project/`，模型必须为 `S6 本机受控替身 / s6-fixture`。保持受限模式、无网络和逐次审批，不切换真实供应商。

### 10.1 首次交接时已准备好的并发编辑

首次交接的会话索引为 `R/native-fourth.json`，原有 30 分钟期限约在北京时间 **15:14:21** 到达。超时/窗口退出不等于产品测试失败；到期后按下一小节重新打开测试会话。用户后续已重开 `native-manual-01.json`，实际测试唯一脚本的结果见第 12 节，不要求重复本小节的旧脚本。

1. 在隔离窗口输入：`请运行 python native_concurrent.py，报告真实退出码，不修改文件。`
2. 出现审批卡后先不批准。用编辑器打开 `F:\Program\Agent\.run\s6-pre-e-20260916\native-526b38de\project\native_concurrent.py`，将内容改为 `print("USER_EDIT_MUST_NOT_RUN")` 并保存。
3. 回到窗口，确认审批仍引用修改前的请求，再点击“批准执行”。
4. 预期：发现文件摘要变化，使旧审批失效或要求重新审批；不能执行修改后的脚本，不能显示任务已验证通过。若出现新的审批，先不要继续批准。
5. 记录界面原文、是否出现上述输出、终态、可见的 run ID；如失败保留原现场，不删文件或重试覆盖。

### 10.2 会话过期后的启动及准备命令

由用户在 PowerShell 执行。先确认上一测试窗口和启动终端已结束，再用新的索引名，避免多个进程争用替身端口。此脚本仅重开同一隔离数据目录，固定本机 6000 端口、原 30 分钟限额，不安装、不升级；命令运行期间保留该终端。

```powershell
Set-Location F:\Program\Agent
.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/resume_native.py native-manual-01.json
```

重开后确认测试项目和替身模型。如果提示登录，请自行完成，不发送凭据。`native-manual-01.json` 不能覆盖；再次重开用 `native-manual-02.json` 等新名字。

在第二个 PowerShell 窗口逐次准备一个场景。例如：

```powershell
Set-Location F:\Program\Agent
.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/manual_case.py native-manual-01.json deny
```

`manual_case.py` 只创建唯一名称的合成文件和本机替身响应，不操作窗口、不提交任务。复制其输出的 `prompt` 到隔离应用；输出的 `project/files` 给出本次文件与原摘要。上一场景已经终止、替身响应消费完再准备下一项。首次交接时该入口仅完成语法/帮助检查；后续用户已经通过它完成一次并发编辑原生用例，其他待测场景仍须各自取得回执。不要对已经存在的数据重复执行旧 `queue_native.py` 的同名文件场景。

### 10.3 重点补测顺序与通过条件

| 顺序/准备参数 | 用户操作 | 预期及记录 |
| --- | --- | --- |
| 1：`deny` | 复制 prompt，等待审批；仔细确认可见“拒绝”按钮并手动点击一次。 | 审批 rejected/取消、无 command execution、无 `MANUAL_ORIGINAL_EXECUTED` 输出。保留拒绝前后界面；若命令仍执行，立即停止其他测试并保留提示。 |
| 2：`concurrent` | 等待审批；修改本次唯一脚本为 `print("USER_EDIT_MUST_NOT_RUN")`；保存后批准原审批。 | 原审批不得执行新内容，应失效或重新要求审批；新审批先不批准。已完成 10.1 可先回传结果，不必重复。 |
| 3：`stream`，再 `correction` | 第一项提交后等断流错误；确认没有自动重试，再准备 correction 并手动提交新的 prompt。 | 第一次明确失败；第二次仅解释，不运行命令、不写文件；保存两个 run 的关联和错误。 |
| 4：`nonzero` | 审核命令只针对本次唯一脚本，再批准。 | 输出 `MANUAL_ORIGINAL_EXECUTED`、退出码 7，目标 unmet/失败，不能显示 verified。 |
| 5：`crash` | 准备、提交、批准；仅在看到 `NATIVE_CRASH_READY` 且命令仍运行时执行下一小节。 | 需要同时记录强退前身份、恢复关联、未知状态与“只执行一次”计数，不能只看重开后能登录。 |

快速重复提交、暂停/继续/追加约束、补丁审查已有本轮原生记录，不要求用户无差别重做。额外冲突补测需另设仍活动的任务与第二请求，核对原 run 不被替换且未创建第二个活动执行；当前交接脚本未自动完成该动作，继续记需复验。

### 10.4 强退与恢复：只针对测试候选

此步骤会故意结束**本轮隔离候选及其运行中任务**，只在上述 crash 场景已启动、看到 `NATIVE_CRASH_READY` 后执行；不要对正式应用或其他进程使用通用强退命令。

```powershell
.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/crash_native.py native-manual-01.json
```

该脚本在终止前核对候选完整路径、PID 和创建时间，记录原进程树 5 秒观察与 `native-starts.txt` 的唯一 `once` 行。任何断言失败即停止，不改断言、不重新强杀。原启动终端结束后，使用 `resume_native.py native-manual-02.json` 重开同一隔离数据目录，不重提原任务、不再次批准。

预期：关联原 run，明确 interrupted/unknown 等真实状态，不自动重放未知操作；`native-starts.txt` 仍只有一行 `once`，无新 execution，旧审批不可复用，租约与原进程身份已收束。保存恢复提示；仅“程序成功打开”不算通过。

需要保存机器可核对的关联时，由用户执行只读白名单采集：

```powershell
.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/inspect_native.py native-manual-02.json
```

它写入新的 inspection 文件，不采集凭据；不要上传整个 profile/webview 或数据库。每项回传“场景、界面原文、是否执行、退出码/终态、证据文件路径”即可。截图若含账号信息请先遮挡。完成后由用户正常关闭隔离窗口并保留终端退出记录；此次正常关闭证据已于第 15 节核对，不要求重复执行。

严格性能和有权限的 symlink 补测依赖前述测量/环境条件，不要求用户凭秒表或更改系统设置凑齐结果。

## 11. DELIVER：记忆同步和最终审查

已读取指定历史记忆 `docs/project-state.md`。其内容是 8 月 31 日 E 盘历史快照，与当前 F 盘 S6 验证的时点及范围不同；用源码摘要、Git 和本轮原始证据核实后，在本页记录新事实，未将历史文件改写为当前状态。五份 S6 文档的旧失败及旧结论保留，后续事实由本页追加说明，不删除原证据。

本轮持久变化为前端创建去重/重试关联与定向测试，以及本页的候选身份、失败诊断、准入矩阵和人工补测步骤。`.run` 下脚本、样本及截图是隔离验证材料，不是生产代码或真实模型质量数据；没有新增记忆体系。首次交付复核见 `R/final-review.json`，人工回执后的复核见第 12–15 节：仅有上述两份前端增量及本页新增，历史保护项与 project-state 不变。

收尾结论为“**工程证据已整理，仍有明确阻断；等待用户手工测试及必要诊断，不进入 E/F**”。任何后续回执先核对实际候选、run/request/operation/execution、摘要、审批、进程身份与租约后追加新记录，不直接将本表状态改为通过。

## 12. 用户手工回执：并发编辑保护通过

2026-09-16，用户自行启动 `R/native-manual-01.json` 对应会话，使用 `manual_case.py` 准备唯一测试脚本 `manual_concurrent_cf6c66bb.py`。用户在原生审批等待期间将其改为 `print("USER_EDIT_MUST_NOT_RUN")`，保存后批准原审批。截图显示 16:33:46 开始等待、16:38:16 工具失败，原文为 `local_tool_rejected: 项目脚本、环境或程序位置在审批后变化，请重新审查`，最终只回答保留实际结果，不声明未执行的测试通过。

仅进行文件及 SQLite `mode=ro` 白名单核对，没有点击、输入、审批、重新提交或启动/终止应用。执行 `.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/review_manual_concurrent.py` 退出 0；证据位于 `R/manual-concurrent-review-6f576908/`，其中 `result.json` 保存关联与 29 条完整事件，`user-concurrent-result.png` 保存用户截图，`readiness-before.md` 保留修改前本页。该核对验证既有手工运行，没有再次执行模型或命令。

| 核对项 | 实际结果 |
| --- | --- |
| 候选 | 六个文件摘要与第 3 节完全一致，414 项源码输入仍匹配；不重新绑定旧 C 成绩。 |
| run / client request | `dc9846a5-2fd8-4947-b522-08a3dbf11e75` / `179efe9a-6cbf-4f9f-b287-02f8af5dd1f3`；该唯一脚本仅对应一个 run。 |
| operation / tool call | `edaeea34-e367-4259-ba64-b54d5a466b9e` / `3ab7e33b4713419586c98f0534c8b0f3`。 |
| 审批 | `c70e4113-1b46-4da2-a8be-d7eb3bd1576e` 为 **consumed**：用户确实点击批准，随后执行前再校验拒绝。本次没有将数据库审批状态伪写成 rejected/cancelled。 |
| 工具调用记录 | `f2a1e144-f8bb-42e6-a732-29bb81848807`，failed / local_tool_rejected，output=null；这是被拒绝的工具调用记录，不是已经创建的操作系统命令进程。 |
| 托管命令执行 | `managed_executions` 中该 run 为 **0 条**；没有可归属该命令的 execution PID/创建时间。源码 `execution_tools.py` 在创建会话前进行同一摘要再校验，与此记录一致。 |
| 权限 / 租约 | 审批预览 restricted / network_policy=none / retention=run，工作区租约 released。 |
| 原始文件 SHA256 | `1c9bab408db149867f6864c24bb9a3327b27c29ca82915f0bcb2ddf600834155`，与场景 setup 文件一致。 |
| 编辑后文件 SHA256 | `996baf60b667ddef867fa355e2d7eb02521a7a58dc56fe64bc7740181405cbbb`；内容与用户按步骤修改的单行脚本一致。 |
| 终态与真实性 | completed / **answered**，不是 verified；无成功 execution 证据引用。29 条事件序号连续，只有一个 run.completed。 |

结论：**本次“审批等待中脚本被并发编辑，批准旧请求不得执行新内容”的原生保护场景通过。** 没有重试或副作用重放；不因此放行审批拒绝、执行中强退或其他未测场景。

采证时 `.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/inspect_native.py native-manual-01.json` 首次退出 1，停在 CIM 进程清单查询；随后只读查询 PID 14744 得到 `Get-CimInstance: 拒绝访问`。转用 SQLite 只读核对后上述断言通过，两个读取失败保存在 result 中。没有提升权限、修改系统设置或将权限错误当作产品失败；**该采证时点的桌面进程身份和全局清理未验证**，不能从零托管执行推断整个桌面进程树已经退出。后续用户提供的独立进程身份证据分别见第 14、15 节，不改写本次 CIM 失败。

本次仅补充回执与文档，不修改产品代码，没有重复执行 all、构建或长时测试。文档空白检查、增量/候选/265 项历史保护摘要及 project-state 保持不变的复核见同目录 `post-doc-review.json`。个人 E 准入与正式 D/M3 仍维持第 1、9 节的阻断结论。

## 13. 用户手工回执：显式拒绝审批通过

用户在同一隔离会话中执行 `manual_case.py native-manual-01.json deny`，生成 `manual_deny_8310021f.py`，在原生审批卡上手动点击“拒绝”。16:46:43 界面显示 `local_tool_rejected: 命令执行已拒绝或审批过期`，随后回答保留实际结果，不声明未执行的测试通过。

执行 `.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/review_manual_denial.py`，退出 0。此命令仅核对既有隔离文件和 SQLite 只读记录，不启动模型/命令、不操作窗口。证据为 `R/manual-denial-review-6d5f4d82/result.json`、`user-denial-result.png`、`readiness-before.md`。首轮自动点击异常仍保留在原目录，本次没有复写该运行或其结果。

| 核对项 | 实际结果 |
| --- | --- |
| run / client request | `537fc791-d221-4d51-a5bb-3f73323ba25b` / `e1fc1af0-aa74-4c34-be83-9e360ffe8173`；唯一脚本只关联一个 run。 |
| operation / tool call | `f630f62e-a54a-46b1-b76e-46f2c23b24f0` / `b1d801fca52c4de7a288c67d6fecbc1b`。 |
| 审批 | `a137c0c8-1681-40fe-a3c8-ee9cfef3683d`，**rejected**，consumed_at=null；决定时间 16:46:43.684 早于过期时间 16:56:41.869，因此能确认是用户拒绝而非等待过期。 |
| 工具调用 | `8ddd8e5f-0064-4f9a-8ade-c24ce9758477`，failed / local_tool_rejected，output=null；与审批 operation 一致。 |
| 托管执行 / 租约 | managed_executions 为 **0 条**，workspace lease 为 released；没有被拒绝命令的操作系统 PID/创建身份。 |
| 文件摘要 | 保持 `1c9bab408db149867f6864c24bb9a3327b27c29ca82915f0bcb2ddf600834155`，与场景准备时相同。 |
| 权限与终态 | confirm，restricted / network_policy=none；completed/answered，不是 verified，无成功执行证据引用。29 条事件连续，单一 run.completed。 |
| 候选 | 六份候选文件摘要和 414 项源码输入仍匹配第 3 节；没有新产品构建或真实模型调用。 |

**本次人工原生拒绝审批场景通过。** 该回执证明当前场景的拒绝路径生效，不足以解释旧自动点击案例为何出现 consumed 和实际执行，因此旧异常仍为未解决。没有再次尝试已经受限的 CIM 进程查询，该采证时点的进程身份和全局清理单列未验证；后续用户提供的进程取证见第 14、15 节。

本次只更新本页及隔离回执，无产品代码修改，不重跑已经完成的全量/构建/长时测试。文档检查及候选、历史保护项、Git、project-state 不变的复核保存为同目录 `post-doc-review.json`。下一项交由用户手工执行原生运行中强退与重开恢复，仍不进入 E/F。

## 14. 用户手工回执：运行中强退、关联恢复与不重放

用户依次执行下列命令并提供终端与重开后的原生界面截图；首次窗口的关闭动作由用户调用强退脚本完成，助手没有操作窗口或终止进程：

```powershell
.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/manual_case.py native-manual-01.json crash
.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/crash_native.py native-manual-01.json
.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/resume_native.py native-manual-02.json
```

第一条创建 `manual_crash_3af861de.py`，脚本将 `once` 写入 `native-starts.txt`，输出进程 PID 后等待 60 秒。原始强退记录为 `R/native-526b38de/reopen-5f8580c5/forced-exit.json`；该会话 `session-end.json` 记录 desktop_exited、无 fixture 错误。重开索引为 `R/native-manual-02.json`，新证据目录为 `R/native-526b38de/reopen-60d323a4/`，复用相同隔离项目和用户数据目录。

执行 `.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/review_manual_crash.py` 退出 0，只读核对用户已经执行的记录。归档为 `R/manual-crash-review-996b8adf/`：`result.json`、`user-forced-exit.png`、`user-recovery.png`、修改前本页及最终 `post-doc-review.json`。

| 核对项 | 实际结果 |
| --- | --- |
| 原 run / client request | `a062cb78-b03c-409d-8356-dacc04d5587e` / `1079a055-da08-44c9-a361-b268618c4cf0`。重开继续显示同一记录，不新建 run。 |
| operation / execution | `654eee0a-effc-43ca-994d-7b8c3c818c43` / `294f761e-6f3c-4623-8f86-0206612e52d6`；只有一个 exec_command 和一个 managed execution。 |
| 审批 | `29c70df1-eb5c-40b2-8b3f-570a10081b4d`，consumed，operation 匹配；没有新审批或复用旧审批发起第二次执行。 |
| 原桌面身份 | PID 14744，创建时间 FILETIME `134340211247999167`，路径为本轮 candidate exe；与 16:32:04 启动时点相符。 |
| 执行宿主与脚本身份 | 宿主 PID 29512，创建身份 `134340224266060275`；脚本实际 Python PID 31772，创建身份 `134340224311555048`，与持久化 `NATIVE_CRASH_READY 31772` 输出一致。 |
| 强退时点 | 16:53:56.095694 发出 TerminateProcess；脚本进程存活约 4940.190 ms，尚未达到 60 秒等待或命令超时。不是命令自然结束后才强退。 |
| 进程树退出 | 强退前记录 16 个 PID+创建时间，包含桌面、WebView、sidecar、exec-host 和 Python 子进程。以发出强退前的 QPC 起表，约 10 ms 观察间隔；最后原身份全部消失的上界为 **145.6844 ms**，小于 5 秒。此项为故意强退后的树退出，不冒充 UI 取消请求计时。 |
| 文件与副作用 | 脚本 SHA256 `7b79c09a30d07e307fc67f2e7f035a381ceb5ddfc635e66f6919a9a4592af463` 不变；命令前 manifest 的 12 个文件摘要仍一致；`native-starts.txt` 在强退前、强退后及重开审计时均只有一行 once。 |
| 恢复状态 | run 为 interrupted / desktop_restarted / goal_outcome=unknown；execution 为 unknown、exit_code=null、stopped=false。42 条事件连续，唯一 run.interrupted 声明 replayed=false，无 run.completed 或派生新 run。 |
| 控制请求 | 关停期间 legacy-cancel 记录保留 interrupted、“未确认生效”，不伪写成取消完成；与界面提示一致。 |
| 权限与租约 | AppContainer、restricted、network_policy=none，宿主摘要仍为 `dec3cb…cf94`。workspace lease 为 **reconcile，generation=15**；未知副作用仍待核对，不冒称 released。 |

结论：**本次真实原生运行中强退、原进程树退出、重开关联和禁止自动副作用重放通过。** 界面中“结果未知”“已中断，待核对”“未恢复或重放进程”是保留不确定性的预期行为。源码 `Recovery.inspect/validate_resume` 对 unknown 执行添加阻断项，`RecoveryPanel` 根据 can_resume 禁用继续；本次未通过私有 IPC 绕过该面板，也未修改数据库把状态改成已核实。

UI 显示的 1 分 23 秒跨越审批等待与重启恢复；实际脚本在强退前运行约 4.94 秒，不能把界面时长写成另一次 60 秒长时验证。外部记录已经证明旧树退出，产品自身仍保留停止未确认，二者证据来源不同。人工消解未知副作用后的受控继续未执行；新打开会话的正常关闭与最终树清理在本节首次写入时未核验，后续回执见第 15 节。

### 手工收尾：只观察正常关闭

用户可执行以下命令，等终端显示“进程身份已记录”，再在 60 秒内手动关闭当前隔离窗口。该辅助脚本只观察 PID+创建时间，不操作窗口、不发出终止命令、不改恢复记录：

```powershell
Set-Location F:\Program\Agent
.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/observe_manual_close.py native-manual-02.json
```

预期终端输出 `all_original_identities_gone: true`。若报错或超时，保留输出，不自行强杀其他进程；窗口已经退出则无法补采关闭前树，不将空列表当作通过。此处计时从观察器启动开始，**不能用于取消请求 5 秒门禁**。

本节首次写入时，该辅助入口只实际执行了 `--help`（退出 0）及 AST/文档检查，未执行观察会话；用户之后实际执行的结果见第 15 节。产品与候选未改动，265 项历史保护证据及 project-state 不变；E/F 仍未开始。

## 15. 用户手工回执：正常关闭与原树清理通过

用户执行 `observe_manual_close.py native-manual-02.json`，待进程身份记录后手工关闭隔离窗口，回传 `all_original_identities_gone=true`、`original_processes=11`、`remaining=[]`。已只读核对原始文件 `R/native-526b38de/reopen-60d323a4/manual-close-5b72a108.json` 及同目录 `session-end.json`。

执行 `.venv/Scripts/python.exe -B .run/s6-pre-e-20260916/review_manual_close.py` 退出 0。归档为 `R/manual-close-review-904246bd/result.json`、修改前本页和 `post-doc-review.json`。实际核对结果如下：

- 关闭前有 11 个不重复的 PID+创建身份，包含桌面、WebView 和 sidecar；桌面 PID 3112、FILETIME 创建身份 `134340224803257885`，候选路径及启动时点匹配。
- 观察记录从仍存活到全部消失，最后 remaining 为空，未由观察器关闭窗口或终止进程。
- 从观察器开始到原树全消失为 10412.6545 ms，包含用户手动关闭前的等待；首次观察到桌面退出至最后原树全消失相差 50.5513 ms。**二者都不是从点击关闭或取消请求发出起算的时延，不用于证明 5 秒取消门禁。**
- 会话于北京时间 17:05:03.476 左右以 desktop_exited 结束，fixture_errors 为空。重开后到关闭期间 **0 次替身模型请求、0 个未消费响应**，补强没有自动模型重试的证据。
- 脚本计数仍只有一行 once，原 run 保持 interrupted/unknown，只有原 execution、没有派生运行。工作区租约仍为 reconcile，generation=15；这是保留未知副作用的持久化状态，不是仍有命令进程运行，也没有被辅助脚本清空。
- 六个候选文件、414 项产品输入、265 项历史保护证据、HEAD/暂存区和 project-state 均未改变。本次只追加回执、辅助核对脚本及本页，未执行新的模型任务、重建或回归套件。

**本次正常关闭后，所记录原进程树的清理通过。** 用户本轮补测的并发编辑、人工拒绝、运行中强退恢复及正常关闭四项均已有对应证据，不要求重复这些案例。原生自动点击旧异常、严格性能边界及其他未解决/未验证项继续保留，不据此进入 E/F。

## 16. 当前缺口与最小后续输入

| 缺口 | 最小后续输入或工作条件 |
| --- | --- |
| 严格宿主收到输出至 UI 可见的 100 样本 | 可核对 Rust 收到输出时刻和原生可见帧时刻的测量机制，明确同机时钟校准和观察开销；由用户触发固定场景，保留完整样本与负载。当前 UIA 代理样本继续留档，不能直接换名放行。若产品输入改变，须新候选及受影响复验。 |
| 首次取消、旧 all 超时、本轮 Python 崩溃 | 需要失败时的精确用例、PID/创建时间、调用栈或受控复现证据；旧材料没有这些信息时保留未解决。同限额诊断不放大 900 秒、不删除或降低断言。 |
| 早前自动点击拒绝后实际执行的异常 | 需要当次点击目标与实际提交审批请求的关联证据，才能区分操作工具与产品；人工拒绝新回执已通过，不能据此断言旧异常根因。遵守用户要求，不再通过操控其窗口复现。 |
| 真实 symlink | 已具备适当权限的独立 Windows 隔离环境及相同版本输入，执行第 7 节命令；不改变当前系统安全设置。 |
| 独立原生活动冲突、创建响应丢失注入 | 分别需要可控的仍活动任务/第二请求和创建响应中断场景；不能把已完成的快速重复提交、单元或 IPC 结果当作全部原生故障已测。继续保留最小独立测试数据，不能清空当前 reconcile 记录凑出可运行环境。 |
| 全仓库 Ruff 未全绿 | 13 个既有 I001 的逐文件归属与定向整理；本轮已证明这些文件未因当前修复改变，没有借检查做无关格式化。 |
| 正式 D/M3 | 第 9 节的正式题集/模型身份/预算/90 次实验与独立审阅，以及目标 Windows、旧安装包、脱敏升级数据和 E/F 证据。它们不重新作为个人学习 B 的要求，本轮也不自动执行。 |

**最终状态：个人学习范围的 E 工程准入仍未通过；正式 D/M3 仍未满足。** 当前用户手工回执已经核对并归档，无需继续重复这四项测试。保留未知副作用状态及所有原失败，候选仍为 candidate_not_accepted；不形成已验收冻结清单，不启动 E/F。

## 17. 本次 PLAN / EXECUTE：基线、归属和最小修复

本次按用户请求重新读取根 `AGENTS.md`、完整 `docs/project-state.md` 和本页准入矩阵及第 12–16 节；按引用核对原计划 D/E、历史失败、B/C 与 S5 真实链接材料。只读检查后以简体中文说明计划，继续执行已授权的本地工作。未操作任何原生窗口，未让用户重复已收到回执的四项场景。使用 `vue-desktop-code` 技能检查前端/私有传输与状态边界；没有改动前端产品代码。

入场 HEAD 为 `1dde393e29f3dbacd3647d11834b39824ac8323f`，分支 `dev/1.0.0`，暂存区为空，已有 **74 个 tracked 修改**及未跟踪内容。`Q/baseline.json` 保存 1285 个安全白名单文件摘要、396 个受保护历史证据摘要、原候选身份和四份手工回执摘要；`Q/before/` 保存本次实际触及文件的入场副本。没有清理、回退或替换其他会话改动。

全仓库 Ruff 门禁来自 `pyproject.toml` 的 `E/F/I`（忽略 E501）及 `docs/testing-guide.md` 第 2、7 节。实际重现 **13 个 I001 / 12 个文件**后，仅对以下文件执行 I001 修复，没有全仓库格式化、规则豁免或依赖升级：

```text
src/personal_assistant/agent_v2/application/model_probe.py
src/personal_assistant/agent_v2/domain/tool_catalog.py
src/personal_assistant/api/routes_model_providers.py
src/personal_assistant/api/routes_providers.py
src/personal_assistant/core/model_metadata.py
src/personal_assistant/core/model_profile_probe.py
src/personal_assistant/core/provider.py
src/personal_assistant/llm/adapters.py
src/personal_assistant/main_api.py
src/private_agent_local/model_routes.py
tests/unit/test_direct_models.py
tests/unit/test_local_model_routing.py
```

增量仅为相邻 import 排序、分组空行及多行排版。`Q/lint-only.patch`、`lint-changes.json` 记录逐文件前后摘要；归一化相邻 import 的顺序和别名分组后，AST 一致。第一版 AST 比较器未处理 Ruff 拆分别名导入，曾在 Ruff 成功后退出 1；保留 `lint_fix.py`、`lint-review-first-failure.json`，由独立 `lint_review.py` 核实，不将辅助脚本首败隐去。AST 比较本身不证明导入时副作用等价，另以定向测试、完整隔离 all 和打包链路复验。

未核实出需要修改的产品行为根因。新增隔离 IPC 取证测试位于 `Q/test_packaged_contracts.py`；其自身两次错误假设及修正见第 19 节。核心、IPC、执行权限、完成真实性和恢复契约均未修改。项目记忆同步只更新本页；按用户要求，`docs/project-state.md` 保持 2026-08-31 历史快照，不把其旧机器路径、安装形态或旧成绩改写为本轮事实。

## 18. 严格宿主收到输出至原生 UI 可见：仍未验证

本次沿 Rust `spawn_stream_reader` → ExecHostClient → `execution.output` → 原生工作台回查。现有 Rust `pipe.read` 返回处没有可关联输出字节的接收时钟；`ExecEvent` 拒绝未声明字段。旧测量在 sidecar 收到宿主 JSONL 后记时，终点为 UIA 首次读到文本，异步截图未提供首次合成可见帧。不能在不核验契约的情况下随意增加字段，也不能把旧代理分数改名为严格分数。

已明确后续采样口径，记录于 `Q/latency-boundary-audit.json`：

1. 起点：Rust `pipe.read` 返回完整唯一标记最后一个字节后、复制/序列化前的 QPC；跨次读取保留字节偏移和片段关联，不使用命令自行打印的时间代替宿主收到时间。
2. 终点：候选窗口前台、未最小化、未遮挡时，首次包含完整标记的桌面合成可见像素帧；保存原始帧和帧采集起止 QPC。UIA、DOM、`requestAnimationFrame` 仅辅助定位。
3. 时钟：同机 QPC/frequency；开始和结束均校准，UTC 仅关联日志。记录跨进程校准误差、采集区间、探针开销、采样间隔和漏帧，给出观测上界。
4. 样本：固定候选、固定输出节奏，一次完整前台尝试至少 100 个唯一编号；每次从 000 开始保留全部尝试。超时、缺失、后台、慢样本都留档；不拼凑多轮最快 100 个。采用 nearest-rank p95，同时报告最大值、严格 `>1000 ms` 数量、CPU 和可用内存。

实际执行 `clock_calibration.py` 完成 32 次父子进程 QPC 往返预检：frequency 均为 10,000,000，子时间均落在父进程前后区间内；最大往返上界 102.0905 ms，包含首个冷启动样本且未丢弃。`Q/clock-calibration.json` 保存全部 32 次。**这只是时钟预检，没有完成 Rust 探针/可见帧校准，不是 UI 延迟成绩。**

本次按原始样本重新计算的旧代理成绩如下，原尝试全部保留；它们均不满足严格边界：

| 历史尝试（路径以 `R/` 为根） | 样本 / 帧 | p95 / 最大值（ms） | >1 秒 | 原机器负载 |
| --- | --- | --- | --- | --- |
| `native-526b38de/reopen-68cf5b91/latency-analysis.json` | 56 / 218，运行未完整结束 | 11604.942 / 12306.908 | 38 | CPU 均值 20.781%、最大 53.414%；最小可用内存 15593295872 B |
| `native-526b38de/reopen-ea6a95f4/latency-analysis.json` | 100 / 178 | 884.732 / 1077.146 | 1 | CPU 均值 21.718%、最大 52.120%；最小可用内存 16412286976 B |
| 第 6 节另记未批准、限时结束尝试 | 0 | 不可计算 | 不可计算 | 原记录保留，不计通过 |

两轮 156 个代理样本合并仅作诊断：p95 9854.074 ms、最大 12306.908 ms、39 个超过 1 秒；两轮工作负载不同，合并值不作准入统计。更早 S5 数据也不能直接变成本轮严格测量。

**本次新增严格前台完整样本 0；p95、最大值、超过 1 秒数量及对应负载均无本轮有效数据。无法核对 p95≤1 秒。** 合格的 Rust 接收点与被动可见帧配对采集器尚未实现，这是剩余工程工作，不只是缺少用户回执。实现后需先验证跨读标记、时钟及采集开销；若改变产品输入，另建候选并按原限额执行受影响链路和完整 all，再由用户触发原生场景。本次没有将此项标为完成。

## 19. 独立冲突、创建响应丢失及恢复范围

### 19.1 本次新增打包 IPC 证据

新候选使用回环 OpenAI 协议替身，真正启动打包 sidecar 与受限 exec-host；项目、账号替身和数据库均为 `Q/packaged-contracts-*/tmp/` 中的独立合成数据。调用方丢弃创建响应的注入发生在 `RuntimeClient.request` 已收到结果后、调用方取得结果前；**不是原生窗口传输丢包**。活动冲突是在命令已经写入计数且 run 为 running 时发送另一请求；**不是原生窗口点击证明**。

最终原始证据根为 `Q/packaged-contracts-6d0ee7c598654a709251a7acf193dfb1/`：

| 事实 | 创建响应丢失后显式重试 | 运行中独立请求冲突 |
| --- | --- | --- |
| 原始证据 | `tmp/7dfac785508346398096f8506507b522/response-loss-evidence.json` | `tmp/a0a36cb808de48f3b278225b178049e3/active-conflict-evidence.json` |
| run | `ecf1573e-fe87-45f9-83ec-f64d8d7646f7`，重试同一 run | `c7977267-6d2c-4662-960d-60c9f718745d`，无第二 run |
| client_request_id | 两次均为 `c5dacdef0ef14380aef6ce60967127c2` | 原 `76d1aba959db463e8c3a4994ff7ba9ef`；第二个 `da5770c0dde741619e75204c87b12cc7` 被 422 拒绝 |
| IPC request ID | `8170d35e2afb43dda12b8b27a80fda5d` → `41946daa04e94d5e9f1fb5b9a4f6d34f` | 原 `5039d8b53bec483bb3298c61fe7eed8c`；冲突 `2285ec21906140e680ade24367b94f59` |
| operation | `92829c7a-55a7-49ce-bf20-753751364739` | `b38e61ba-f224-4c07-8613-3c0111a66ebe` |
| execution | `0de9be29-1db3-4867-bb13-3acefb6e486f` | `cda60ef0-a1a6-4b42-b5aa-193b397a0cc5` |
| 审批 | 唯一 `541880fa-8762-4226-bfa2-2743956259ac`，重试前后同一 pending，之后 consumed 一次 | 唯一 `dc28dab7-e1d7-42fb-8e19-1ba70cec9b59`，consumed 一次 |
| 文件及租约 | once.py 摘要不变；once.txt 只有一行；唯一 managed execution、exit 0、stopped=true；租约 released/generation 1 | active.py 摘要不变；once.txt 只有一行；唯一 managed execution、exit 0、stopped=true；租约 released/generation 1 |

两项均核对 `execution_mode=restricted`、`network_policy=none`、宿主摘要 `dec3cb3c…cf94`、实际启动 sidecar 摘要 `5f137614…758e` 和本次库 schema 7。`Q/closeout-results.json` 保存脚本与计数文件完整 SHA256、原始证据 SHA256 及完整关联；数据库仅 `mode=ro` 读取，没有修改审批、执行或租约记录。

一次性计数命令会改变工作区，现有 `completion.py` 明确使此前命令验证证据过期。最终两项 run 均为 `failed / output_validation_failed / goal_outcome=unmet`，并精确断言“执行后工作区发生变化或无法完整核对，旧验证证据已过期”。**唯一执行门禁通过不代表合成任务完成；没有把 exit 0 或替身回复冒充 verified。**

新增测试共三次执行，全部保留：

- `packaged-contracts-74e5cb50ced04996b614993d00166424`：7 passed / 1 failed。首次断言错误地从公开快照读取内部幂等键，`KeyError: 'client_request_id'`；`runtime.snapshot` 明确排除此字段。原测试另存 `test_packaged_contracts-first.py`，修正为核对同一 run、只读账本和两次实际发送记录。
- `packaged-contracts-80824e897981472784d0344b1da07e6e`：7 passed / 1 failed。第二次将写计数文件的任务预期为 completed，与已有工作区证据过期规则不符；原库证实一次 exit 0 且 output_validation_failed。原测试另存 `test_packaged_contracts-second.py`；依据上述完成契约精确断言 failed、错误类型及未满足项，所有唯一 run/审批/执行/文件/租约断言保留。没有改产品让测试通过。
- `packaged-contracts-6d0ee7c598654a709251a7acf193dfb1`：8 passed，63.72 秒。其余六项覆盖原有重复/暂停/追加约束/继续、断流后新请求、拒绝、非零、并发编辑及强退后 unknown 禁止重放。

### 19.2 原计划范围和历史手工证据

原计划 D-03 仍要求暂停/继续、运行中追加约束、重启关联；D-04 还包括断流、非零、拒绝、并发编辑、强退、未知副作用，以及持续终端、stdin、Unicode、末尾输出和权限正反对照。S5 恢复测试另覆盖 model.requested/response_confirmed、tool.requested、approval.required、补丁意图/落盘/记录、tool result 等进程中断边界，部分补丁、审批过期/撤销、旧 PID/迟到输出、控制幂等和预算、工作区租约及版本能力。这些用例仍在原完整 all 范围内，没有只挑新两项就宣布恢复整体通过。

第 12–15 节四份原生手工回执已核对与 `R/candidate/` 的完整产物摘要一致，仍是该历史候选的所列场景成绩。本次只改 model_routes.py 导入排版，相关桌面、宿主、运行时/恢复/文件保护输入未变；据此保留历史适用性说明，不改写回执里的 sidecar 摘要，不把它们登记为新候选原生复跑。

旧强退 run `a062cb78-b03c-409d-8356-dacc04d5587e` 仍为 interrupted/unknown；execution `294f761e-6f3c-4623-8f86-0206612e52d6` 为 unknown，lease 为 reconcile/generation 15，无派生重放 run。`Recovery.inspect/validate_resume` 会因未知执行、尚未 stopped 或 uncertain_operations 阻止继续；检查点并不是可重放授权。原计划不要求通过清空 reconcile 或手改数据库使这一未知操作继续。本次没有“核清”其副作用，也没有新增绕过入口。

**独立原生活动冲突、原生创建响应丢失后的显式重试仍未补齐。** 本次没有原生故障注入器或实际窗口操作记录，不能以以上 IPC 或已有 Vitest 证明替代。最小后续需在独立合成会话中准备可控活动任务、第二原生请求，以及只丢弃一次创建返回且保留请求关联的原生边界注入；先验证注入器，再由用户操作。旧 reconcile 现场不能用来当作可随意清空的测试夹具。

## 20. 四项历史异常的有界诊断结论

原始证据摘要、选定字段、调用链和只读数据库事实见 `Q/historical-diagnosis.json`。本次完整 all 为相关源代码路径提供一次同限额复跑；没有无限反复运行以寻找绿色结果，没有修改系统 WER 配置，也没有执行自动点击拒绝复现。

| 异常 | 核实的事实及本次诊断 | 结论及缺失材料 |
| --- | --- | --- |
| 首次宿主取消失败 | `.run/s6-final-f146e704/host-67ec73d7/` 为 34 passed / 1 failed，失败用例是 `test_real_host_timeout_and_cancel_stop_process`；测试文件摘要仍匹配。本次普通权限 all 中该用例通过，15.48 秒；历史十次取消成绩仅保留历史属性。 | **未解决。** 首败缺 PID+创建时间、完整断言栈及取消前后连续时间线，不能断言 PID 复用或某个清理竞态。最小诊断材料是在同限额独立运行中取得这些事实。 |
| 首次 all 900 秒超时 | `.run/s6-completion-fix/all-35eeca10/` 外层 900.172 秒退出 124；底层日志约 61% 的点状输出，无逐用例位置。本次两个 all 均保留逐用例开始/结束。 | **未解决。** 后续 799.90 秒通过没有解释首次卡在哪一项；需当时或受控复现的用例位置、线程/子进程身份和栈，900 秒不扩大。 |
| 本页此前 Python 0xC0000005 | `R/all-0a61e9be13574c15acf50d54c3602b9a/`；Event 1000 匹配 PID 39376、Python312.dll、offset 0xc9723，12:14:55.4105011 +08:00；末个用例 VT01，Python 栈为 pathlib.lstat→plain_path→tree_hash→verify→judge_external。首版观察器未显式指定 ctypes argtypes，但关联不证明因果。 | **未解决。** 缺故障线程原生栈/转储和受控复现。轻量观察器不启动后台 CPU 线程或周期 traceback；本次同范围 all 包含 VT01 并通过，也不能据此关闭崩溃根因。 |
| 自动点击“拒绝”却执行 | run `707b9667-d55a-48ad-975a-da95e084e5ce` 的审批实际 consumed，execution `6fa4a6f6-b327-4c88-b236-77d1e92244ef` exit 7；离线检查旧截图/UIA 和源码，拒绝按钮绑定到 reject 路由。后来的人工拒绝 run 仍为 rejected、零执行。 | **未解决。** 缺当次点击目标→原生/DOM 事件→实际 approve/reject 请求的因果链。不能据此断言自动工具误点击，也不能断言产品绕过拒绝；不再操控用户窗口复现。 |

新出现的本轮工具令牌 all 首败和新增测试取证错误分别在第 19、22 节单列，未混成以上四项历史异常的根因证明。未核实出产品根因，因此本轮没有伪造“先红后绿”的产品修复闭环。

## 21. 真实 symlink：权限核对及已有隔离链接补测

普通用户令牌未列出 SeCreateSymbolicLinkPrivilege；Developer Mode 的 AllowDevelopmentWithoutDevLicense 注册表值不存在。没有改变权限、开发者模式或系统安全设置；完整 all 的“现场创建链接”测试仍因权限跳过。

只读发现 S5 已由用户创建并归档的真实链接仍存在，因而不需要新建链接即可验证访问拒绝：

- 链接：`.run/s5-remaining-20260909/symlink/captured-link.txt`，reparse tag `0xA000000C`，inode `1125899907928445`；原归档记录 SHA256 `a2e85334b33ebfd55d12b1299964af10750b796139e613604bcfe2127bccbfff`。
- 目标：`F:\Program\test\s5-remaining-20260909\symlink\outside.txt`，SHA256 `23d95b3c7d97b39d9cb972d48a8cecee0af690b11f0fcd83b6893b4a465a4d12`。这是既有隔离合成夹具；仅核对字节摘要，没有修改目标。
- 实际执行 `Q/verify_existing_symlink.py`：当前源码的 Repository.read 和 patch_preview 均以“项目工具不访问符号链接或目录联接”拒绝；前后链接身份及目标 SHA256 一致。`Q/existing-symlink-result.json` 保存源码摘要和结果；辅助 Store 仅位于 Q 的新合成数据库。

**当前源码对该真实 symlink 的读取/补丁拒绝已通过。** 不声称具有创建符号链接权限，不声称重新执行了完整 all 的 skipped 用例，也不提升为安装副本或任意链接拓扑都已验证。若需补做“新建后拒绝”的原用例，条件仍是已具备相应权限的独立 Windows 环境和相同源码输入；不要求用户更改本机安全设置。

## 22. TEST：实际命令、全量首败/复跑与新候选

所有命令工作目录为 `F:\Program\Agent`，使用既有 `.venv`，没有安装或升级依赖。完整回归、构建与打包运行按序执行；两个 all 的测试清单、源码/观察器摘要和 900 秒限额完全相同（`Q/closeout-results.json`）。`validate.py` 保留既有隔离配置与断言，all 仍按既有 SUITES 合并、排除另列 duration/execution-duration 的定义；不将它称为全仓库所有 Python 测试或正式发布全门禁。

| 实际命令 | 本次观察结果与原始证据（以 `Q/` 为根） |
| --- | --- |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-closeout-20260916/audit.py` | 基线建立；1285 文件、396 历史证据、四份匹配回执，`baseline.json`。 |
| 同解释器执行 `Q/lint_fix.py`，继而 `Q/lint_review.py` | 前者底层 `ruff check --no-cache --select I001 --fix` 仅带第 17 节 12 文件，13 I001 修复；辅助 AST 检查首次退出 1；后者修正比较方法后退出 0。`ruff-before.json`、`ruff-fix.json`、`ruff-after.json`、`lint-only.patch`、`lint-changes.json`。 |
| 同解释器执行 `Q/validate.py direct-models` | **53 passed，5.05 秒**；`direct-models-13dbe39168104621a7e53d6ae2e7c733/`。 |
| 同解释器执行 `Q/validate.py all`，首次工具受限令牌 | **890 passed / 79 failed / 1 skipped，489.01 秒，exit 1**；`all-4d424cfd0d9e4f9ab96b99f423cb3261/`。日志有 47 行 WinError 5 和 40 行 ExecHostClient 无法启动宿主，另有 422/runner_error 等级联失败；这些行数不是独立失败用例数。 |
| 同一 `Q/validate.py all`，普通用户令牌复跑 | **969 passed / 1 skipped，799.90 秒，exit 0**；`all-1085cb0cc77e487597c37033052252d9/`。只有现场创建真实 symlink 因权限跳过。源码、测试和观察器摘要与首次一致，两轮 business_modules_loaded 均为空。 |
| 同解释器执行 `Q/build_candidate.py` | 33.328 秒、exit 0；新目录离线 PyInstaller sidecar 构建，`build-sidecar.log`、`build-invocation.json`、`build-source-before.json`。没有覆盖原候选或旧清单。 |
| 同解释器执行 `Q/validate.py packaged-contracts`，三次 | **7/1（57.43 秒）→7/1（69.89 秒）→8 passed（63.72 秒）**，目录及首败原因见第 19 节。三次均在原 900 秒内，产品输入未变化。 |
| 同解释器执行 `Q/run_smoke.py` | 底层为 `scripts/verify-unified-client.py --bundle .run/s6-pre-e-closeout-20260916/candidate --work-dir .run/s6-pre-e-closeout-20260916/packaged-smoke --model-mode ollama`；22.562 秒，exit 0，`packaged-smoke/packaged-runtime-cee47318290e44ddb919974394a4befb/verification.json` passed=true。 |
| 同解释器执行 `Q/verify_existing_symlink.py` | 当前源码对既有真实链接的 read/patch_preview 拒绝通过，前后摘要一致，第 21 节限定范围。 |
| 同解释器执行 `Q/diagnose_history.py`、`Q/latency_audit.py`、`Q/clock_calibration.py` | 原始失败/代理性能/同机时钟预检取证脚本均 exit 0；这不表示其检查的四项异常或严格性能门禁通过。 |
| 同解释器执行 `Q/environment_audit.py`，受限及普通令牌；`Q/installed_metadata.py` 两次 | 得到 `environment.json`、`environment-ordinary.json`、`installed-metadata.json`、`installed-metadata-normalized.json`。首次未剥离 InstallLocation 引号而未列出二进制，修正读取方法后核对摘要；保留首次记录，不以空列表证明未安装。 |
| 同解释器执行 `Q/final_static.py` | `ruff check --no-cache src tests scripts`、`scripts/protocol_codegen.py --check`、`scripts/check_agent_v2_imports.py`、`git diff --check` 均 exit 0；`final-static.json`，Ruff 为 All checks passed。12 个文件和当时 14 个辅助脚本 AST 解析通过。 |
| 同解释器执行 `Q/collect_results.py` | `closeout-results.json` 汇总实际六次测试尝试、同输入比对、两个 IPC 完整关联、旧包材料、smoke 和最新辅助脚本 AST 检查；exit 0。 |

表中 `Q/` 是本页路径缩写，实际完整 argv 保存在各 invocation/静态报告中；不声称执行过名为 Q 的目录。普通用户复跑只解除外层工具令牌对测试进程启动的限制，并非管理员运行，也未降低产品 AppContainer/审批/network_policy。相同输入、明确 PermissionError 和普通权限通过支持本轮首败为测试环境限制；不据此替历史取消、超时或崩溃认定根因。

打包 smoke 只用回环账号/模型替身；它包含既有受控 trusted 正对照，单独保留，不作为 restricted 的成绩。新增两个副作用场景始终 restricted/none。smoke 的 real_model_called、native_desktop_verified、installed_copy_verified 均为 false；“server_login”字段指本机账号替身，未使用真实凭据。

### 22.1 新候选身份清单（不是已验收冻结）

产品清单 414 项中只有 `src/private_agent_local/model_routes.py` 改变，前后摘要分别为 `3fd1fefe046bca5309842fb9d28f1571025ea11fb26f98917c4ee0d928ff331a`、`3883b1721ad602f489c473d483c61030fe6b857210e98d28c66678b493499540`。因此重建 sidecar；其他组件输入未变，桌面、exec-host 和宿主 sha 文件复用 R 中相同字节。新清单与当前 414 项源码全部匹配，版本仍为 **1.0.0 / Windows x64 / unsigned / portable / dirty=true**，应用标识 `com.personal-assistant.desktop`，私有传输 stdio-v2、SQLite schema 7、execution/completion/recovery 1.0。

| `Q/candidate/` 对象 | SHA256 |
| --- | --- |
| 产品源码汇总 | `0d0b97121b8cd3fd01b0dfc2be2fb582b7540b467eb1e3c24b80d77d6279472e` |
| `PrivateAgent-windows-x64.exe` | `45d9760468e06591c71ca1c2c2e05c57f83aae271f40c8b49261f262e6c105cc` |
| `private-agent-local.exe` | `5f137614e529c99c82b4588d817524fa332debf15196548a23b1371fae97758e` |
| `exec-host.exe` | `dec3cb3cf81122454552f674231a9f1da83eb8fa6c13ddde820d262efe10cf94` |
| `exec-host.sha256` 文件 | `dbffb1ad8b37862893b73b98cce1dc1ab72d513cd416f33635167e0b84449dd1` |
| `build-info.json` | `80315051c3e1b4d615cac1a0e1c73492a9a7cef626813ec6cbaf2d4c81bbc1e1` |
| `source-manifest.json` | `0cbe0b2935aa2378e5254b2bbf799abadb36f4aa89115a196a9cc8ff5c3dffd5` |

`build-info.json` purpose 为 `pre_e_lint_closeout_candidate_not_accepted`，记录 reusedArtifactSource 与摘要，installed=false、launched_desktop=false。运行证据只证明本次 IPC 子进程启动路径/文件摘要和独立数据库 schema，不宣称读取了旧原生进程内存或完成 loaded-component attestation。

原 `R/candidate/` 的六个文件及旧源码清单不变；其源码清单对应修复前输入，不能因当前 import 排版改变而重写它。旧 C 仍绑定 `.run/coding-local-probe/probe-03f47eff5f7b4515a159047d2862a248/` 的原候选，不绑定 Q。当前只形成身份清单，**不形成 accepted/frozen 决议**。

## 23. E 材料准备：按用户指定“本机”检测，未执行 E

用户已明确目标就是本机，因此不再次询问机器类型。`Q/environment-ordinary.json`、`installed-metadata-normalized.json` 与 `closeout-results.json` 记录只读检测；没有安装、打开旧应用、迁移、回退或读取正式配置/数据库。

| 材料 | 本次核实 | 准备状态 |
| --- | --- | --- |
| Windows / 架构 | Windows 11 Pro 25H2，10.0.26200.9445，AMD64/x64；i7-13700K、24 逻辑处理器、34063396864 B 物理内存。注册表兼容 ProductName 仍显示 Windows 10 Pro，与实际系统版本区分。 | 本机目标明确；不外推其他 Windows/ARM64。 |
| 权限与工具 | 普通用户、非管理员，未具备新建 symlink 特权；本机有源码和既有开发 `.venv`。 | 标准用户前提已记录；干净机外部 Python/Node/Rust/rg 等工具缺失行为留待 E，开发机通过不能替代。 |
| 干净机器或快照 | 当前机器有源码及开发运行时；未核实到可供本次验收使用的无源码/无开发 `.venv` 独立快照。 | **未准备/未核实**；未创建或清理系统。 |
| 已安装旧形态 | HKCU 中 PrivateAgentCandidate 1.0.0，路径 `.run/s5-candidate-install-20260909-layout`；另有 PrivateAgentRemote 1.0.2。 | 仅安装元数据和二进制摘要；不是当前候选的运行/安装验证。QA 候选、Remote 与普通统一客户端不能混作同一升级通道。 |
| 旧安装包 | 见下表，文件存在、摘要已取证。 | “旧包存在”已确认；**支持的升级起点未确认**。 |
| 脱敏独立数据副本 | 未验证到来源明确、与选定旧包/产品标识匹配的 schema 3–6 或同版本 7 独立副本及一致性清单。 | **未准备/未核实**；未读取或复制正式数据来补齐。合成 Store 单测不是该材料。 |

已核对旧包如下，均没有执行：

| 路径 | SHA256 | 适用性 |
| --- | --- | --- |
| `dist/upgrade-smoke/0.1.2/PrivateAgent_0.1.2_x64-setup.exe` | `a948cfb93b4689d611fccf28d59115eed111ef5dce7988a2f0af96291c356943` | 历史普通版，未确认本次 SQLite 3–7 升级适用性。 |
| `dist/upgrade-smoke/0.2.0/PrivateAgent_0.2.0_x64-setup.exe` | `8468a705ef316c9d305d9261be334d7e27c11f51d48acf676bfad66b9074380b` | 同上。 |
| `dist/rollback-archive/PrivateAgent_0.3.0-alpha.2_x64-setup.exe` | `2b7d5cca214d7527405a52eebe030363ea6e6274ef2d441d40727496ebe47540` | 同上。 |
| `dist/test-builds/PrivateAgent_1.0.0_x64-setup-installer-fix1.exe` | `e59be03d5ad7b95d38e57d8f214ecac4c1fededf01416073e3e6525940d593b5` | 历史 full-backend 安装包不能仅凭 1.0.0 版本号视为当前统一客户端。 |
| `.run/unified-client-gHXwHg/PrivateAgentCandidate_1.0.0_x64-setup.exe` | `525f05397ef54bc649e9038fdbac5213537f2ec51036dbc57bcd99fa4d2287bc` | 明确 QA=true、`com.personal-assistant.desktop.candidate`；和当前 `com.personal-assistant.desktop` 标识不同，不能静默选为升级起点。 |

`dist/clean-install-1.0.0.json` 与 `dist/upgrade-smoke/upgrade-rollback-0.9.0-to-1.0.0.json` 是旧 full-backend/MySQL/Alembic 记录（后者 0033→0035），不支持宣称本机 SQLite schema 3–7 已升级/回退。真实升级起点、每个独立副本的来源/schema/脱敏状态/一致性摘要，以及干净快照标识仍是最小材料；不要提供凭据。本次只给材料审查结论，不执行 E-01～E-05。

## 24. 最新准入矩阵、交付边界与最小后续

| 门禁 | 最新结论 | 依据与适用范围 |
| --- | --- | --- |
| B 个人学习范围 | 历史完成，保留 | 不重新要求正式保留题或独立回执，不记成本次 30 题重跑。 |
| C 公开 PY01 真实联调 | 原候选历史绑定保留 | Q 的替身和打包检查不能替代真实模型质量；本次零真实供应商调用。 |
| 原生并发编辑、人工拒绝、运行中强退关联/禁止重放、正常关闭清理 | 历史所列场景通过，适用性已核对 | 四份回执原摘要保留；无无差别重做，无改绑。 |
| 严格宿主至原生可见 UI ≥100 前台样本、p95≤1 秒 | **阻断，未完成** | 第 18 节：合格采集器未实现，本次有效样本 0，旧代理数据不替代。 |
| 独立原生活动冲突、创建响应丢失后的显式重试 | **阻断，原生未完成** | 两项新候选 IPC 证明唯一执行；原生边界注入及用户操作记录仍缺，第 19 节。 |
| 首次取消、首次 all 900 秒超时、Python 崩溃、自动拒绝异常 | **未解决，继续阻断** | 第 20 节有界调查保留原失败；没有可核验因果链，不因后来通过关闭。 |
| unknown / reconcile 禁止重放 | 保护状态保留 | 旧未知操作仍不能继续；只读核对且无新派生执行，不清数据库。 |
| 真实 symlink 拒绝 | 当前源码、已有真实夹具场景通过 | 第 21 节 read/patch_preview 真实拒绝且目标不变；新建权限用例仍 skipped。 |
| 全仓库 Ruff | 本次通过 | 13 个 I001 定向最小修复；E/F/I 口径和 E501 既有豁免未变。 |
| 完整隔离 all | 普通用户复跑 969 passed / 1 skipped | 原 900 秒；保留受限令牌首败和同输入比对；不是原生或正式质量成绩。 |
| 新候选受影响链路 | 构建、8 项打包 IPC、打包 smoke 通过 | 414 项输入匹配，未安装、未启动桌面；首败/修正/复跑完整留存。 |
| E 材料 | **目标本机明确，材料未齐** | Windows/x64/普通权限明确；干净快照、兼容升级起点、来源明确的脱敏副本未核实。 |
| E/F 执行 | 未开始 | 本次请求明确到此停止。 |

**个人学习范围是否具备进入 E 的工程条件：否。** 本次实际关闭 Ruff 及限定场景的真实 symlink 缺口，补充 IPC 唯一执行和新候选证据；没有完成严格原生性能、两个独立原生故障场景，也没有核实四项异常根因和全部 E 材料。不能将本次收尾说成全部剩余要求完成，不豁免安全、数据保护或完成真实性门禁。`Q/candidate/` 保持 candidate_not_accepted，只有可核对身份清单，没有已验收冻结清单。

**正式 D/M3 仍缺：** 上述工程保护/原生门禁；正式开发/保留题隔离及候选/模型身份/预算/介入口径冻结，默认模型完整 30 题×3 次实验、预定编码分母上 ≥80% 独立完成率和独立审阅（D-01/02/05、T09）；真实安装和声明 Windows/权限/组件组合范围（D-03、T08/T10）；E 的干净安装、schema 3–6/7 独立来源数据验证、升级/重开/安全程序回退及不兼容拒绝（T11）；F 的匹配候选交付决议、分发/签名策略和更新回退文档（T12）。这些正式质量材料不重新加入个人 B 的范围，本次不启动正式 90 次或 E/F。

最小后续按依赖顺序如下，未准备好的工程入口不转嫁为要求用户重复点击：

1. **工程侧先完成采集器和原生注入器。** 按第 18、19 节验证后，再建立新候选/新证据目录。现在不能让用户运行旧 performance 脚本并称其满足严格门禁。
2. **工具准备并核验后，用户只需逐项操作独立候选：** 启动给定隔离入口；提交一个固定 100 编号输出任务并批准一次，保持前台直到 FINISHED；另开合成场景，在首任务仍活动时触发独立请求并记录明确冲突；在“创建结果未知”场景中保持输入不变，仅显式重试一次，随后批准同一审批。每项完成再进入下一项；预期分别为完整配对样本、无第二执行、同一 run/幂等键及一次审批消费。具体可执行入口尚未形成，因此这些是后续操作约束，**不是已可立即运行或已完成的测试**。
3. **异常取证：** 最小材料分别是取消首败的 PID+创建时间/完整栈、900 秒超时中的用例与栈、Python 原生故障栈/转储、旧拒绝点击与实际审批请求关联。拿不到历史材料时保留未解决；不要求重做已通过的人工拒绝来代替因果证据。
4. **E 材料：** 只需补齐本机独立干净快照标识、同产品旧包与支持升级起点、来源可核对的脱敏独立数据副本路径/schema/一致性清单。当前已检测到的系统和旧包无需重复提供；不发送任何凭据，不在本任务安装、迁移或回退。

最终差异与保护性复核见 `Q/final-review.json`：对照入场字节摘要检查本次 12 个 import 文件及本页增量，核对旧候选/396 份历史证据、HEAD/暂存区和 `docs/project-state.md`；记录结果而不清理原始失败或旧测试现场。本页是用户授权更新的准入记忆，保留第 1–16 节历史、以本节说明被本次证据修正的状态。

## 25. “进入下一步”续轮：实际实现观测与注入入口

本续轮重新核对适用 AGENTS、完整 `docs/project-state.md`、本页及引用的实现/回执；按已说明的计划执行，没有进入 E/F。`P/baseline.json` 保存 1285 个入场文件摘要、454 个受保护旧证据摘要、HEAD、暂存区及 Q 候选身份。入场 HEAD 仍是 `1dde393e29f3dbacd3647d11834b39824ac8323f`，分支 `dev/1.0.0`，暂存区为空。`P/before/` 保留所涉产品文件与本页的原字节。

实际产品增量仅在 Rust 宿主和 Tauri 私有通道：两个 Cargo manifest 新增默认关闭的 `readiness-probe` feature；`readiness_probe.rs` 记录合成标记对应的真实管道读取 QPC；`readiness_transport.rs` 记录指定合成创建请求的关联，并可单次丢弃成功创建响应的全部帧。`main.rs`、`lib.rs`、`local_executor.rs` 只接入上述边界。不新增 IPC 字段、Tauri command、数据库字段、依赖或前端交互；审批、AppContainer、`network_policy=none`、完成判定和禁止重放契约保留。

探针必须同时具备编译 feature 和 exe 同目录的 `readiness-probe.json`；缺少配置时关闭。配置只接受 schema 1、八位合成编号、`.run` 内的绝对隔离根及一次丢包布尔开关；exe/路径祖先不能是 reparse point。桌面在启动 UI 前核对 USERPROFILE、APPDATA、LOCALAPPDATA、WebView 数据目录，在创建本机数据目录前再次核对目标归属。日志仅保存合成编号、QPC、请求/运行/执行标识和状态，不保存输出正文、请求正文或授权头。行数及单行字节数有固定上限；采集缺失不能当作通过。

复核发现新探针初版在创建数据目录之后才校验路径。先添加 `isolation_is_checked_before_creating_a_new_application_directory`，于 `P/host-test-2fb6e525766f44ccbb35e4a6d4a0fca6/` 实际复现 **4 passed / 1 failed**；随后把路径校验移到创建前，并让校验器只读解析尚未创建的尾部目录，拒绝越界、父目录跳转及已有重解析点。`P/host-test-9faa6e4a4ef4497fa95f4eeb590fd562/` **5 passed**，`P/desktop-test-c341f4205a2e4104a3a297a5373ccca0/` **8 passed**。这是本续轮新探针的已定位问题，不是四项历史异常的根因。

## 26. 严格测量方法与当前有效样本

**原生门禁样本尚未采集，当前严格有效样本为 0；p95、最大值及超过 1 秒数量均为未测。** 以下是已实现并自检的采样方法，不是把旧 sidecar→UIA 结果重新命名。

1. 起点 `t0`：Rust `spawn_stream_reader` 的 `pipe.read` 返回后立即读取 QPC，位于拼接、UTF-8 处理和事件发送之前。合成一行先输出 `PAE <编号> <000..099> END`，后接 `sample <编号> <两个校验词> visible`。跨多次读取时保留短尾部的读取边界，以标记**首字节**所属读取的 QPC 为起点，同时保存完整标记到齐的 `complete_qpc`；不把首字节与末字节时间混淆。
2. 终点 `t1`：被动观察器只在指定候选 PID 为前台、未最小化/隐藏、客户区无上层可见窗口遮挡，且捕获前后窗口/区域一致时保留客户区原始像素。用屏幕 DC 的 BitBlt 和 GetDIBits 保存 PNG；终点取首次出现该完整合成校验词的原帧捕获结束 QPC，属于保守上界。没有点击、输入、前台切换、UIA 文本时间或 DOM 回调。DWM 像素观察不等于显示器物理发光测量。
3. 时钟：宿主和观察器都直接使用本机 QPC/QPF，同一启动周期；捕获前后各做 32 次父子进程往返夹逼，逐次保留 before/child/after、频率与最大夹逼区间，不做推测性 offset 扣减。频率不一致、夹逼失败或缺少后校准即不放行。实现依据为 Microsoft [QPC API](https://learn.microsoft.com/en-us/windows/win32/api/profileapi/nf-profileapi-queryperformancecounter) 与[同机高分辨率时钟说明](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps)。
4. 固定场景：用户批准一次后先输出 READY，预留 8 秒让原生执行面板稳定；随后顺序输出全部 100 个标记，间隔 350 ms，总命令限额仍为 60 秒。观察器目标间隔 50 ms，活动采集至多 90 秒，等候最多 1800 秒。所有帧尝试、前台/遮挡失效、捕获开销、缺样本和重复标记均保留；不删除失败重取“最佳 100 个”。每秒记录全机 CPU 累计时钟、物理内存和逻辑处理器数。脚本只会结束自身观察，不会关闭用户窗口。
5. 原帧先保存、后离线 OCR。内建 Windows en-US OCR 按词框重组水平行；不能修补识别错字。低字号未完整识别的合成行可从**同一原始帧**裁出原像素并以固定三倍 LANCZOS 放大再识别，记录原帧 SHA、矩形、派生图 SHA 和全部配对；终点仍用原帧时间，不扣减观察开销。其他文本不进入 OCR 结果日志。
6. `analyze_pixels.py` 用全部原帧与宿主日志核对身份、连续编号、QPC、OCR 摘要和前台观察；nearest-rank p95 使用 `ceil(0.95*n)`，同时报告最大值、`>1000 ms` 个数及机器负载。必须至少 100 个完整前台样本，且 p95 上界≤1000 ms、无缺帧/重复/身份错误。输出 `strict_gate_passed=false` 也可以是一次成功的分析命令，不能被当作门禁通过。

测量器自检命令为 `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/test_tools_runner.py`，实际使用已经安装的 Codex bundled Python/Pillow 和 Windows OCR，没有安装语言包或依赖。保留以下全部尝试：

| `P/tool-tests-.../` | 实际结果及处理 |
| --- | --- |
| `32eafe7722724a8d8310cbf1668f5779` | 3 项通过、1 项错误；PowerShell 5.1 按本机代码页误读无 BOM 中文脚本，错误日志再按 UTF-8 读取触发解码错误；校准器还提示管道未关闭。已补 BOM 和资源关闭。 |
| `176db5f061d442909f5a2b3c69dd9648` | 3 项通过、1 项失败；OCR 把等宽数字识别错且按列分段，完整编号为 0。 |
| `3f908e8257a84854b019ac5c667f5abd`、`a870b9dd164847e0af74f1ac68dc5fe5` | 校验词与词框重组后，12 px 图像仍漏 7 个；20 px 图像完整。仍按失败保留，没有放宽 100 个断言。 |
| `07b88e1dc0464fc2ab4aad9a0ba627da` | 加入固定的原像素区域放大后 **4 项通过**，12 px 与 20 px 图像均完整识别 100 个标记；缺失、重复、错误摘要、后台样本和 p95 超标的统计器反例均拒绝。 |

这些是自检图像和统计器/FFI 校验，**不是原生前台样本，也不是模型质量成绩**。原始诊断保留在 `ocr-diagnostic*.json`；其中两次诊断因继承的 PowerShell module path 不匹配而失败，后改用与测试一致的白名单环境；只处理合成图片，没有读取窗口内容。

## 27. 新候选、构建与定向回归

每次产品输入改变后均在新目录构建。首次宿主 4 项、桌面 7 项探针测试通过后构建了 P 初版；构建脚本自身的两次失败完整保留：组件名错写为 `apps/desktop`（实际身份键为 `apps/desktop/src-tauri`）在前检即停止；首次清单把新摘要写入 `execHostSha256` 而保留旧 `executionHostSha256`，身份核验拒绝。旧 `P/candidate/` 不改写，另存 `P/candidate-02/` 修正清单。原始错误见 `build-preflight-first-failure.json`、`build-finalization-first-failure.json` 和各 build invocation。

路径前置校验修正后，执行 `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/build_v3.py`，在 **`P/build-03/`** 串行离线重建宿主、vue-tsc、Vite、Tauri release。每步仍限 900 秒，无安装包、签名、安装或窗口启动。Rust/Tauri 有 dead_code 等编译警告，未隐藏。没有变更 sidecar 输入，因此复用 Q 中已核对的 sidecar。`P/active-candidate.json` 指向此候选；此前全部目录与清单保留。

| 当前 `P/build-03/candidate/` | SHA256 |
| --- | --- |
| 产品源码汇总 | `66db5cbf969d9a3f8b5d7b3349e1cb796d99cef992b34798a1d161de26c74ea6` |
| `PrivateAgent-windows-x64.exe` | `a469718dfc75e76d91402f62a2b61fb4341f5ce3001e9b83038ace815e867df9` |
| `private-agent-local.exe` | `5f137614e529c99c82b4588d817524fa332debf15196548a23b1371fae97758e` |
| `exec-host.exe` | `fd0f289b33f707d061fb6ca2c3a1c164d97a465f5325485dd2d1ecf8b9c9d9d6` |
| `exec-host.sha256` 文件 | `df69349ea302b3ce6d7c756273f8654057dc933f908925d0986ea42d35bf5984` |
| `build-info.json` | `d96bf7088c64d019ed00fbccd6def5b9d290870f0621a02501092fb3ed3ef2a3` |
| `source-manifest.json` | `9e1b6e75b99b665c80bbc3535c881912e3351fdc089393a542e4eb6f90b9b161` |

版本/架构/产品标识仍为 1.0.0、Windows x64、`com.personal-assistant.desktop`、unsigned portable、dirty=true、stdio-v2；探针 feature 明确写入构建信息，purpose 为 `pre_e_instrumented_candidate_not_accepted`。只形成候选身份清单，不形成已验收冻结决议，不改绑原 C。

`.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/validate.py probe` 首次 `P/probe-9c57e79b9f6c4275b91ee8fff91131b0/` **8 passed / 1 failed**：新增宿主测试的裸 `python` 解析到全局环境，触及沙箱 50,000 项扫描上限。改用已有 `.venv` 的绝对解释器后，对新候选复跑 `P/probe-6dadc5c926334c89bb27496761cd443e/` **9 passed，88.77 秒**。扫描限额、AppContainer 和断言未放宽；首轮测试源码由记录的 SHA 验证后保留为 `test_host_probe-first.py`。后续每次验证还复制相应测试源码到本次证据目录。

上述 9 项包含真实 Rust 宿主收齐 100 个合成标记的读边界记录，以及现有打包 IPC 的重复/活动冲突、显式重试、流中断/纠错、拒绝/非零/并发编辑、强退未知保护。后八项用于变更后回归，不替代原生手测或重记此前用户的四项回执。宿主测试本身没有原生 UI，100 条记录不能算严格延迟样本。

现有完整隔离命令 `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/validate.py all` 以普通用户令牌运行，使用现有 SUITES 并集（原来单独限时的 duration 套件仍单列），上限仍为 900 秒。候选宿主路径与每次实际启动摘要由 observer 记录。该候选两次 all 均未通过，实际结果见第 29 节。

## 28. 原生场景入口与安全状态

`P/native_probe_session.py` 分开准备 latency、active、loss 三个独立目录；仅 `--prepare` 创建夹具、复制对应候选并保存摘要。**`--launch` 必须由用户运行**，由其手动打开候选、选择本机替身模型与合成项目、提交/审批/重试/关闭。脚本没有点击、输入、前台切换、关闭或强退窗口的代码；只检查已有 PrivateAgent 进程名以避免单实例转交到别的副本。30 分钟或 64 次替身请求到限后停止发出新的命令响应，并等待用户自行退出，不强退窗口。

本机推理替身固定为 `http://127.0.0.1:6002`、Ollama、`s6-fixture`。连接探测不会消费命令响应；固定场景只装载一次 `exec_command`，活动时自动读取执行状态的替身响应保持 0.85 秒节奏，避免无间隔循环耗尽既有产品预算。所有合成命令仍为 restricted/none/retention=run/timeout=60000 ms，审批必须经真实原生卡片由用户处理。未知结果或 reconcile 记录不能通过此入口清除。

- **latency**：用户提交 `prepared.json` 中的固定 prompt，批准一次；保持候选前台并让底部“本机进程”输出面板可见，等待 `PIXEL_MEASUREMENT_FINISHED`，然后自行正常关闭。后台仅被动取像素；关闭后按原限额串行 OCR、分析，原始帧、所有尝试、负载、前后校准和结果均保存。
- **active**：首任务运行 `active.py`，追加一次 `once.txt`、输出带 QPC 标记的 READY 后等待 45 秒；用户在同一合成工作区的新会话提交固定 conflict prompt。预期原生提示工作区活动冲突，没有第二运行或第二审批/执行。必须结合用户实际提示与 Tauri 422 响应、独立 request key、宿主活动区间和 SQLite 只读关联核验，不能只看到 422 就认定原因。
- **loss**：只对匹配编号的首个成功 `POST /agent-runs` 丢弃状态、正文和 done 帧；前端原有 20 秒超时后应显示创建结果未知。用户保持输入不变，显式重试一次，再批准同一审批。预期两个 transport request id、同一 client_request_id、同一 run/operation/execution、一次审批消费和一次 `once.txt` 写入。非 2xx 响应不丢弃；未知副作用不重放。写计数文件导致原工作区验证证据过期时，完成判定继续如实保留 failed/unmet，不伪造 completed。

`P/inspect_native_probe.py` 仅对该新会话的 schema 7 独立数据库使用 `mode=ro`，读取固定白名单字段及租约；核对 run/request/operation/execution、审批、候选/脚本/计数文件摘要，保留 unknown/reconcile。机械检查通过也不会自动把 `native_case_accepted` 写成 true，仍须核对用户本次回执。没有对旧未知运行 `a062cb78-b03c-409d-8356-dacc04d5587e` 或其 reconcile 记录执行更新。

## 29. 续轮首败、隔离缺陷修正与 build-04

### 29.1 build-03 的完整 all 首败与一次诊断复跑

| 实际命令 | 结果与原始证据 |
| --- | --- |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/validate.py all`，首次 | `P/all-78e63ace21074d5986e761a46751628a/`：**exit 124，900.045 秒**。900 秒内完成 call 的结果为 927 passed / 1 skipped，最后开始的是宿主取消用例；没有完整套件通过结论。 |
| 同命令，仅增加 `-o faulthandler_timeout=60` 的一次诊断复跑 | `P/all-15a7b77a33354678a0a9eb6034fd9bdb/`：**exit 3221225477（0xC0000005），396.130 秒**；崩溃前完成 319 个 call，均 passed。VT01 已用 97.724 秒通过，最后进入 RS01；其约 60 秒诊断转储过程中出现 access violation。 |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/diagnose_all_timeout.py` | `P/all-timeout-diagnostic.json`：取消用例在第 890.503 秒才开始，剩余 9.497 秒；Q 中同用例曾耗时 15.477 秒。多个隔离复制/摘要用例较 Q 慢 2–12 秒。能说明本次累积用时用尽预算，**不能确认变慢根因，也不能解释早前约 61% 的旧超时**。 |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/diagnose_current_failures.py` | `P/all-crash-diagnostic-2b623406d28a446bbe1a5776db2c29e2/`：核对两次逐用例日志、输入摘要、Windows Event 1000。只读取字段，不改 WER，不继续盲跑同一候选。 |

两次产品 Python 源码、测试清单和观察器摘要一致，均保留原 900 秒和全部断言。首轮机器负载只有一次普通权限只读观测：北京时间 19:57:26，CPU 15%、可用内存 12,441,844 KiB；不是全程负载，也不是慢测根因。最初受限 CIM 查询失败保留于 `all-machine-observation.json`，成功单点观测另存 `all-machine-observation-ordinary.json`。

新 Event 1000 时间为 **20:06:30.6753492 +08:00**、RecordId 530135，`python312.dll`、`c0000005`、offset `0x00000000000c9723`，进程字段 `0x3e80`。pytest 外层 `.venv` 启动记录与实际基础解释器进程字段分开保留，不以外层 PID 替代事件 PID。VT01 的诊断栈为 `ntpath.realpath → pathlib.resolve → plain_path → tree_hash → verify → judge_external`；RS01 的故障输出未提供完整原生栈。故障偏移与早前崩溃相同，属于相关线索，**未证明同一根因**。轻量观察器关闭 CPU 后台线程仍发生崩溃，不能归因或免责任何组件；周期转储的影响也未获因果证明。缺少故障线程原生栈/受控复现，状态仍为 **unresolved**。

历史首次取消、旧 all 900 秒超时、早前自动点击拒绝后执行的三项诊断仍按第 20 节保留未解决；新的通过或不同失败都不关闭它们。

### 29.2 原生入口启动前的隔离保护与路径判断更正

准备 `P/native-latency-b602915a/` 后，尚未启动任何窗口时，源码复核确认：当前 Tauri 2.11.5 的 `app_local_data_dir()` 经 dirs 6.0.0 / dirs-sys 0.5.0 使用 Windows Known Folder；Tauri 会在 `.setup` 前为默认 WebView 建立数据目录。最初由源码推断“环境重定向不足、本机会落到正式目录”，**该推断后来被实际 API 查询纠正，不能作为已复现的越界根因**。实际执行 `P/known_folder_audit.py` 及 `--ordinary`，在受限和普通用户令牌下，`SHGetKnownFolderPath(FOLDERID_LocalAppData)` 均返回本次隔离 profile 下的 AppData/Local，HRESULT=0，原始记录为 `known-folder-audit.json`、`known-folder-audit-ordinary.json`；没有读取或创建该目录内容。原生会话原本同时重定向 USERPROFILE/APPDATA/LOCALAPPDATA，不能只凭未直接读取 LOCALAPPDATA 就否定其效果。

仍然保留显式路径绑定，使探针不依赖环境展开的隐含行为，并在默认 WebView 创建之前落实隔离位置；这是隔离保障增强，**不是本机已发生正式数据读写的修复证明**。系统凭据入口此前缺少探针保护，经源码确定并加以拒绝。旧未启动目录的原始 `blocked-before-launch.json` 不改写，后续更正与 API 实测并存；该入口从未交给用户运行。

先把三个既有行为提取到可测试边界，新增定向断言：探针数据目录显式绑定隔离根、禁用默认 WebView 自动创建、拒绝系统凭据库入口。执行 `P/rust_checks.py desktop-test`，`desktop-test-96023b3169f64dc2b135b41bc19c1bd4/` 实际 **8 passed / 3 failed**；这三个失败证明原代码未满足新增显式保护要求，不证明原生窗口发生过越界。凭据测试只建立入口对象，没有读取、写入或删除任何凭据。随后最小修正：

- `readiness_probe.rs` 在激活时显式选择已校验隔离根下的 `profile/AppData/Local/<applicationIdentifier>/local-projects`，创建前继续检查归属与重解析点；不激活时沿用原路径。
- `lib.rs` 在激活时先禁用配置窗口的自动创建，再以相同窗口配置及显式绝对 `webview` 数据目录建立窗口。这里是应用自身初始化；助手没有启动或操控窗口。
- `credentials.rs` 的探针入口在触及系统凭据库之前明确拒绝；无探针配置时原有行为不变。本机 Ollama 替身不需要密钥，不从正式配置或凭据库复制材料。

修复后的 `P/rust_checks.py desktop-test`：`desktop-test-0fb0536e00784045a49d86f71baac7df/` **11 passed**；`P/rust_checks.py host-test`：`host-test-e899688fb69d4114a1c3645b5e694032/` **6 passed**。这些是本续轮探针保护的验证，不能作为四项历史异常的根因。

测量器另发现“只要宿主日志文件存在就开始 90 秒计时”会让空闲/审批等待消耗采样窗口。新增反例后 `tool-tests-1d2f05cf4d5a478bbcdf6858e156266e/` 为 **4 passed / 1 failed**；改为等到首个完整 `host_received` 行，保留半行写入边界与等待上限；`tool-tests-68af1b993786453aa4d42f21e25bce2a/` **5 passed，2.673 秒**。开始观察前的等待间隔至多 100 ms，不从测量值扣除；第一个完整可见样本仍使用真实宿主 QPC 与原帧时间。此前本轮工具自检 `bff5568b5e2745fe925352633a57c00a/` 的 4 项通过也单独保留。

`P/native_helpers_runner.py` 实际运行 `native-helper-tests-83aeffc705834adf96a6229888ec3598/`，**2 passed，1.973 秒**：连接探测不消费命令、冲突不发出新命令；只读审计器检查一次写入、审批/operation/request 绑定，并对合成单元夹具的 reconcile 正确阻断。该单元夹具是新建的测试数据库；未修改任何产品运行或旧 reconcile，检查前后数据库摘要不变。它仍不是原生场景回执。

### 29.3 新目录构建与当前候选身份

实际执行 `P/prepare_build_04.py`、`P/build_v4.py`、`P/activate_04.py`（均使用 `.venv/Scripts/python.exe -B`）。`P/build-04/` 四个阶段串行完成，总计 **112.047 秒**：宿主 release 9.283 秒、vue-tsc 9.545 秒、Vite 9.774 秒、Tauri 83.267 秒，均 exit 0、每阶段限额仍 900 秒。没有依赖安装、签名、打包安装或窗口启动。当前 416 项产品输入匹配；Rust/Tauri 原有及探针共享模块的 dead_code 警告保留。

| 当前 `P/build-04/candidate/` | SHA256 |
| --- | --- |
| 产品源码汇总 | `ea1396a6f36a67e55a8ca051c9518ecf5238b553116419e98ed02833ab2bd7d5` |
| `PrivateAgent-windows-x64.exe` | `4f61d0480e76646a28900ba105ac1e1fc194c45f9fbecbe63e0bf11bab88a084` |
| `private-agent-local.exe` | `5f137614e529c99c82b4588d817524fa332debf15196548a23b1371fae97758e` |
| `exec-host.exe` | `73d30a1ce54fe062dee5a8e2c71d8bc0d32a249ad0b13fdf047b8bd028485353` |
| `exec-host.sha256` 文件 | `29e90b4e33503fcdb07d7ae435c8e2a089863abfd409a10e741f6642d5fad4ac` |
| `build-info.json` | `9d086817c149d211b8fb87ae21c3f7d670e56c9ccf5448b6efc805e7982d150b` |
| `source-manifest.json` | `e4c7faca4bb15704fe03b76ac59accb3b9c043c4ba9dd7d52526f80948784d2d` |

保持 1.0.0 / Windows x64 / unsigned portable / dirty=true / `com.personal-assistant.desktop` / stdio-v2 / schema 7 / execution、completion、recovery 1.0。构建开关为默认关闭的 `readiness-probe`，邻接配置不存在时关闭探针；标记仍为 `pre_e_instrumented_candidate_not_accepted`。原 R、Q、P 初版、candidate-02 和 build-03 的候选及旧清单全部保留。`active-candidate.json` 只是当前选择指针，其前值和更新记录分别为 `active-candidate-03.json`、`active-selection-04.json`；没有重写旧候选身份或改绑 C。

### 29.4 新候选受影响链路的实际复验

| 实际命令（工作目录 `F:\Program\Agent`） | 观察结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/validate.py probe` | `probe-23ac959aa9634934b65b42573c09c6eb/`：**9 passed，70.85 秒**，真实宿主 100 个读取标记及八项现有打包 IPC 契约；不算原生窗口成绩。 |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/desktop_checks.py target` | `target-86119fb9/`：四文件 **21 passed，2.19 秒**；useRunStream、useRunStreamBlocker、privateTransport、ExecutionPanel，既有 300 秒上限。 |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/final_static.py` | `static-b09e0f4b36514e66b116c0179a088e36/`：全仓库既有 Ruff 范围 `src tests scripts`、协议代码生成同步、agent_v2 依赖边界、git diff 空白检查均 exit 0；当时 34 个辅助 Python 文件 AST 通过。 |

新候选另执行 `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/validate_04.py all`，因本次确实改变了产品输入而重新验证，不是为了刷掉 build-03 的失败。该入口只撤去诊断复跑额外加的 `faulthandler_timeout=60`，恢复首轮既有诊断配置；测试清单、断言、AppContainer、权限及 900 秒不变，差异记录为 `all-04-diagnostic-configuration.json`。结果在第 30 节单独登记，不据撤去周期诊断声称修复了崩溃。

## 30. build-04 全量首败及租约采证竞态的定向修复

`P/all-b24d43bbe9a348ddbe739c98467cfa6b/` 完整执行结束为 **968 passed / 1 failed / 1 skipped，780.08 秒，exit 1**（包装器 780.991 秒）。没有超时或崩溃；真实 symlink 创建权限仍为唯一 skip。失败用例为 `test_actual_agent_ipc_restricted_material_boundary`，栈落在 `agent_probe.approve → read_live_journal → read_json → file_hash`，对象是该次临时运行的 `sandbox-leases/pa.execution.….json`，报 `ValueError: 清单输入不是有界普通文件`。首败原始 invocation、逐用例事件、pytest 结果和完整输出全部保留，不能把其余 968 项通过写成完整 all 通过。

源码核对发现 `file_hash` 在 `plain_path` 后调用 `Path.is_file()`；如果活动日志恰在两者之间被租约清理，`is_file()` 返回 False，将正常的文件消失误分类为坏清单。原 `approve` 只对 `FileNotFoundError` 跳过已消失日志，仍要求至少采到一份完整且范围正确的授权记录。租约写入/替换/删除来自现有 `windows_sandbox.py`，未更改它，也未更改 `read_live_journal` 的 1 秒权限冲突重试。

先新增定向失败测试，在新建合成日志经过真实 `plain_path` 后立即删除，确定复现同一异常；同时保留目录、超限文件、坏 JSON 的拒绝反例。随后只将 `scripts/coding_acceptance_schema.py:file_hash` 的两次元数据读取改为一次 `stat()` 加 `stat.S_ISREG`，让文件消失的 `FileNotFoundError` 自然传播。没有捕获并忽略任意 ValueError，没有忽略真实坏清单，没有弱化链接/硬链接/重解析点、8 MiB 限额或授权范围断言。首败没有记录删除瞬间的文件元数据，不能声称还原每一步时序；该错误分类机制已用确定性测试复现并修复。

| 实际命令 | 结果与证据 |
| --- | --- |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/validate_journal.py journal`，修复前 | `journal-86bf4f41cde742be9db375354e1a8bdc/`：**1 failed / 3 passed**；文件消失反例得到同一 ValueError，其他拒绝反例通过。 |
| 同命令，最小修复后 | `journal-b08ec07dd17e46b59d1215435a0bd5f3/`：**4 passed，0.20 秒**；原有安全拒绝仍成立。 |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/validate_journal_live.py journal` | `journal-f3e27c3f25834e2eafbb26ae0e2329fa/`：**5 passed，21.94 秒**；包含原失败的真实 Agent IPC/AppContainer 材料隔离场景及四项新测试。 |
| `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/final_static.py` | `static-01fb1d8709bc4971a14cbbd5c4747dd6/`：Ruff、协议同步、依赖边界、git diff 空白检查全部 exit 0；当时 41 个辅助 Python 文件 AST 通过。 |

该修复只改变评测辅助模块和 `tests/coding_acceptance/test_s6_isolation.py`，不改变候选的 416 项构建输入；build-04 产物与源码汇总仍为第 29.3 节的摘要，无须改写或重建候选。两文件原字节保存在 `P/before-journal-fix/`，原有其他会话改动保留。评测器输入已改变，旧实验/首败清单仍保持原绑定，不能据此重记 B/C 的历史成绩。

修复后再执行原 `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/validate_04.py all`，目录为 `P/all-c5174897069b4a44a8baaa80420204dc/`，900 秒及全部原断言不变，只增加四项上述反例。最终结果在第 31 节登记；无论该复跑如何，四项历史异常及第 29.1 节新崩溃根因仍不能据此关闭。

## 31. 修复后完整 all 结果与原生补测交接

2026-09-16 本机实际执行的 `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/validate_04.py all` 已结束：`P/all-c5174897069b4a44a8baaa80420204dc/` **973 passed / 1 skipped，849.64 秒，exit 0**；包装器耗时 **850.548 秒**，未超过原 900 秒上限。唯一 skip 为 `tests/unit/test_local_file_ranges.py::test_actual_symlink_rejected`，原因仍是 Windows 未授予创建真实符号链接权限。没有超时扩大、断言弱化、AppContainer 或网络限制关闭。真实 Agent IPC 材料隔离首败场景本次通过，宿主取消用例本次通过；这些结果不关闭历史首败或新的 Python access violation。

原始命令、输入摘要与保护结果见该目录 `invocation.json`，完整输出见 `output.log`，逐用例开始/结束与耗时见 `test-events.jsonl`，汇总见 `pytest-result.json`，实际候选宿主启动摘要见 `actual-hosts.jsonl`。`test_sources_unchanged=true`；88 条宿主观察记录的 SHA256 均为第 29.3 节的 `73d30a1c…8485353`，没有混用旧候选。测试范围新增的四个确定性反例已在第 30 节说明，不把 973 项当成正式模型实验数量。完整 all、构建和长时场景按原限额串行；用户只在回归期间打开隔离窗口并准备模型/项目，完整 all 返回 exit 0 后才发出原生采样的提交步骤。

原生测量入口为 `P/native-latency-33eff827/`，编号 `22347547`，绑定第 29.3 节 build-04 的六个文件、416 项输入及独立工具摘要。首条用户复制命令丢失 `Agent` 后的路径分隔符，得到 `CommandNotFoundException`，没有启动进程或产生样本；改用 PowerShell 支持的正斜线绝对路径后，用户回报“已成功打开”，且该目录存在对应 `launch.json`。两次回执均保存在 `P/user-launch-receipts-01.json`，没有把输入错误删掉或改写为产品失败。

用户随后分别回报本机 Ollama 替身“已配置”和隔离项目“项目就绪”，保存于 `P/user-model-config-receipt-01.json`、`P/user-project-receipt-01.json`。这些仅证明所述人工准备回执，不是模型质量、执行完成或性能达标证据。助手没有点击、输入、批准、前台切换、关闭或强退窗口。提交固定任务、批准一次、展开本机进程输出、保持前台以及正常退出均由用户完成；原生采样结果须另按原始证据和用户回执登记。

截至发出测量步骤时的最新矩阵如下，后续实际原生结果另节追加；不能把“准备完成”写成“门禁通过”。

| 门禁 | 当前结论 | 依据或剩余缺口 |
| --- | --- | --- |
| B 个人学习范围 / C 公开 PY01 | 历史完成与原绑定保留 | 不要求重做 B，不改绑旧 C；本续轮仅本机替身。 |
| 四项既有原生人工回执 | 历史所列场景保留 | 第 12–15 节摘要和适用性已核对，不记成本续轮成绩。 |
| 严格宿主至原生像素可见，100 个前台样本、p95≤1 秒 | **待本次原生采样核验，仍阻断** | 采样器和时钟校准已实现、自检通过；此时无已核准的原生统计结果，旧代理数值不替代。 |
| 独立原生活动冲突 / 创建响应丢失显式重试 | **原生场景未完成，仍阻断** | 打包 IPC 及注入器定向测试已通过；仍需两项独立用户操作与完整关联。 |
| 四项历史异常与本续轮 Python 崩溃 | **未解决，仍阻断** | 第 20、29.1 节有界诊断未获得可核验根因，后来的通过不能关闭。 |
| 租约采证文件消失的错误分类 | 定向机制已修复，回归通过 | 先 1 failed / 3 passed，再 4 passed、真实 IPC 5 passed、完整 all 973 passed / 1 skipped；不宣称还原首败删除瞬间。 |
| unknown / reconcile | 保护状态保留 | 原未知运行没有被改库、清记录、释放或重放；人工消解后继续仍未验证。 |
| 真实 symlink | Q 已有真实链接的 read/patch 拒绝适用 | 新建权限仍未具备，唯一 skip 如实保留；只在已有适当权限的隔离环境补测。 |
| 全仓库 Ruff | 本续轮检查通过 | Q 的 13 个 I001 最小修复保留；本续轮 Rust 与采证竞态改动后的 Ruff 仍 exit 0。 |
| build-04 身份与受影响链路 | 构建、17 项 Rust 定向、9 项打包、21 项前端、完整 all 通过 | 各自是已执行层次，不能替代原生测量或真实模型质量。候选仍为未验收探针候选。 |
| E 材料 | **目标本机明确，材料仍未齐** | Windows 11 Pro 25H2 / AMD64 / 普通用户已记录；本机干净快照、兼容旧包起点与来源明确的脱敏独立 schema 3–7 副本尚未核实。 |
| E/F / 正式 90 次实验 | 未执行 | 保持用户要求的停止边界。 |

**个人学习范围仍不具备进入 E 的工程条件。** 正式 D/M3 还缺上述工程门禁，以及第 24 节所列正式题集隔离/身份与预算冻结、30 题×3 次的默认模型实验和独立审阅、声明 Windows/权限/安装范围、E 的干净安装与独立数据升级/重开/安全回退、F 的匹配候选交付决议。后几项是正式后续阶段要求，本任务不执行。没有生成已验收冻结清单，也没有豁免安全、数据保护或完成真实性门禁。

## 32. 用户改为全本机测试：保留空尝试并构建 build-05

### 32.1 原生空尝试与新增约束

用户在 2026-09-17 报告“服务器出现了问题”，要求之后都使用本机服务，并明确回报“尚未发送”“已退出”。未诊断或连接远端服务器，不能据此认定远端故障的具体状态码或根因。源码确认 build-04 的账号入口仍固定为远端，项目执行前继续请求 `/auth/me`；这与本机模型替身是不同依赖。

`P/native-latency-33eff827/` 保留全部现场：`desktop-exited.json` 为 exit 0；`session-end.json` 为模型请求 0、夹具错误 0；`capture/end.json` 为 activated=false、frames=0、等待 1556.610 秒、desktop_control_actions=0。离线 OCR 命令结束后，分析命令因缺少宿主 QPC 日志明确 exit 1，原始 `analyze_pixels.py.log` 中的 `AssertionError: 宿主 QPC 原始记录缺失` 保留。它是未提交任务的空尝试，不是有效样本、性能通过或产品运行崩溃。用户新要求及回执存于 `P/user-local-service-receipts-01.json`。

### 32.2 PLAN / EXECUTE：只给隔离探针使用的本机账号入口

只读确认原生入口、前端地址约束、sidecar 身份绑定与现有本机认证夹具后，已向用户说明具体调整方案。`P/before-local-account/` 先保存三个新增涉及的产品文件、已改 `local_executor.rs` 和辅助工具的修改前字节；不覆盖入场基线或旧候选。

- `server.rs` 沿用现有 `account_server_origin` command。只有 Windows `readiness-probe` feature 且已通过隔离根/相邻配置校验、探针激活时，返回固定 `http://127.0.0.1:6003`；未激活时仍为原内置 HTTPS 入口。没有任意环境变量或用户地址覆盖。
- `local_executor.rs` 启动 sidecar 时复用同一入口函数，保证界面登录和 sidecar `/auth/me` 使用同一账号服务。没有更改私有协议或数据库 schema。
- `http.ts` 仅接受原生后端返回的该字面固定回环入口；其余 HTTP 地址、其他端口、用户信息、路径、query 和 fragment 继续拒绝。非探针生产入口不变，没有禁止证书验证或设置系统信任例外。
- `P/local_account_service.py` 只绑定 127.0.0.1，提供合成账号登录、`/auth/me`、注销和健康检查。公开合成测试码仅是本会话编号；会话 bearer token 随机生成、驻留内存且不记入证据，错误登录、错 Host/Origin、失效 token 和超限请求均拒绝。30 分钟、256 个账号请求、4096 字节登录正文、5 秒连接期限均有界。服务不提供模型、注册、代理或真实账号接口。该模拟账号不代表真实服务器认证质量验收。
- 原生启动器同时启动本机账号服务和本机模型替身；新会话将绑定该工具源码摘要、全新 profile/WebView/项目。任何本机服务无法绑定时明确失败，不回退远端。模型仍为 `127.0.0.1:6002` 的 `s6-fixture`，原 64 次模型请求、1800 秒会话、60000 ms 命令、AppContainer、network_policy=none 和人工审批保留。候选更新检查 endpoints 为空；未改 hosts、DNS、证书库、系统安全设置或正式用户配置。

### 32.3 定向失败、最小修改与实际复验

| 实际命令（均在仓库根，使用 `.venv/Scripts/python.exe -B`） | 原始证据及结果 |
| --- | --- |
| `P/account_checks.py target`，修改前 | `account-target-508bdc31/`：**50 passed / 1 failed**，前端拒绝指定本机账号入口。 |
| `P/rust_checks.py desktop-test`，修改前 | `desktop-test-9cb42edaa81f4463bf2b00faa62c084b/`：**11 passed / 1 failed**，探针入口仍返回远端。该反例验证新增全本机要求，不把原固定服务器设计说成历史崩溃根因。 |
| `P/account_checks.py target`，修改后 | `account-target-ba01fdb9/`：八文件 **52 passed，2.51 秒**，含新增本机登录、身份绑定和失效清理；既有拒绝地址、账号调用链与私有传输反例保留。这些前端测试使用受控替身，不是真实服务器账号验收。 |
| `P/rust_checks.py desktop-test`，修改后 | `desktop-test-cf04820a0ab84f7b8d90b0079225aa7b/`：**12 passed**，原探针隔离与新入口默认关闭边界通过。 |
| `P/account_service_runner.py` | `account-service-tests-03adca43e8054dd6b0d319ac5ed97072/`：**3 passed，2.033 秒**；真实回环 HTTP 检查登录/轮换/撤销、Host/Origin/CORS、未提供接口、请求体/时间/次数限额和无 token 落盘。 |
| `P/native_helpers_runner.py` | `native-helper-tests-5aeeee02e4fb433294fc2c966fdc7e8e/`：**2 passed，1.964 秒**；连接预检不消费命令，只读审计器保留 reconcile 拒绝。 |
| `P/validate_05.py account-ipc` | `account-ipc-4afe0826615a4322a4b528b9e46de282/`：**1 passed，3.80 秒**，使用真实候选 sidecar 和两个独立回环服务；不是原生 UI 测试。 |

打包账号用例先验证无效 token 得到 401，随后用合成登录建立 schema 7 独立数据、创建一项待审批命令；在账号服务注销后再批准该命令。最终 run `84c34b90-045a-4fad-811a-6b05f0188253` 为 failed / `cloud_auth_required`，托管执行 0，目标副作用文件不存在，原脚本摘要不变；清除本次运行时身份后，原 token 再绑定仍得 401。只在本次测试 API 中完成登录/注销及审批，没有操作原生窗口，也未修改数据库绕过认证。完整关联位于该目录 `tmp/05489e49b3a24f59b950337ce75b7b0c/local-account-ipc-evidence.json`；不保存 token、密码或请求正文。

### 32.4 build-05 身份与回归状态

实际执行 `P/build_v5.py`、`P/activate_05.py`。`P/build-05/` 新目录构建共 **169.984 秒**，四阶段均 exit 0，原每阶段 900 秒上限：宿主 10.812 秒、vue-tsc 14.744 秒、Vite 14.742 秒、Tauri 129.576 秒。只复用输入未变的 sidecar；不安装、签名或发布，旧 build-04 及此前所有产物不改写。

| 当前 `P/build-05/candidate/` | SHA256 |
| --- | --- |
| 产品源码汇总 | `a2cfe217286658ec5928ae1a7e71e721b0770f7a5a5a6edb493595647de2841f` |
| `PrivateAgent-windows-x64.exe` | `1ad9879758e95c2720f11d959ceb25e4b6eacd1757e7bde79d43ada9fa9ca249` |
| `private-agent-local.exe` | `5f137614e529c99c82b4588d817524fa332debf15196548a23b1371fae97758e` |
| `exec-host.exe` | `3a26124f1ba59de620df23c6e3e31757c1b46d01c44212c371b2b12b67a28300` |
| `exec-host.sha256` 文件 | `d474e96c49813a7455c78f02e31944304e93093c37c5b71a4015124a5125949f` |
| `build-info.json` | `3cf09bdfcda4a737d388c1f70e300cb298d3dfd1ed223ac026e08939ae982320` |
| `source-manifest.json` | `7d32a6c39558f71fadc95b833167606b226ae94eab41261d79181b460b3c3fd6` |

purpose 为 `pre_e_loopback_account_probe_not_accepted`，账号模式 `isolated_local_test`，版本/架构/应用标识/schema/协议仍沿用第 29.3 节。C 的原候选绑定不变；本机合成账号或模型成绩不冒充真实账号与真实模型质量。

`P/validate_05.py probe` 首次目录 `probe-b3115b344b664b008a493d686850df03/` 在会话中断前完成 **7 项 passed**，停在第八项并发编辑的 setup，未产生 invocation 终态或最终退出码。恢复后只读核对 Python/sidecar/宿主进程均已退出；`interruption.json` 将退出码保留为 null、full_suite_passed=false。没有清除原输出或补写虚假终态。于是用原 900 秒及全部断言，在 `probe-d7bfa62af47047ed8acf70e29d101dc1/` 重新执行完整 9 项，结果另行登记。build-05 的完整 all 尚需独立结果，不能引用第 31 节的 build-04 成绩代替。

上述完整复跑实际为 **9 passed，77.45 秒，exit 0**（包装器 78.638 秒）。随后串行执行 `P/final_static.py`，`static-19f298f3a33248648afdbdc020e45f56/` 的 Ruff、协议同步、依赖边界、git diff 空白检查全部 exit 0，50 个辅助 Python 文件 AST 通过。Git 原有 CRLF 提示单列保留，没有为消除提示格式化文件。

本机服务调整后的完整回归命令为 `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/validate_05.py all`，目录 `P/all-3aaf072c426747c28607e06c8cdd111c/`，维持既有 SUITES 并集、900 秒、轻量观察器和全部断言；最终状态另节登记。原生新入口已用 `P/native_probe_session.py --prepare latency` 准备为 `P/native-latency-d0860c85/`，编号 `33744233`，账号和模型都为本机服务；准备不等于启动或验收。

本节对应阶段审查 `P/review_05.py` 得到 `review-a877d03ce62542f5b60509707d02b006/result.json`：416 项当前构建输入匹配，454 项受保护历史证据、build-03/build-04 六个旧产物、HEAD/暂存区和 `docs/project-state.md` 不变，修改范围符合入场基线。该检查按当时文件快照记录；后续最终审查另行保存，不覆盖它。

## 33. build-05 完整 all 超时与原生补测前的准入矩阵

### 33.1 TEST：本轮全量失败与有界离线诊断

`.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/validate_05.py all` 的 `P/all-3aaf072c426747c28607e06c8cdd111c/` 已实际结束：**exit 124，900.029 秒**。逐用例日志中只有 **890 个 passed call / 1 个 skipped call**，没有产生完整 `pytest-result.json`；不称为“890 项通过的完整回归”。最后开始的 `test_migration_preserves_ids_content_backup_and_is_idempotent` 在第 899.400 秒进入，只剩 0.600 秒总预算，记录到 setup 通过后被总时限终止。这里是新建合成 Store 的单元测试，未执行 E 的安装、真实数据迁移或回退。

实际执行 `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/diagnose_all_05.py`，只读对比该轮与 `all-c5174897069b4a44a8baaa80420204dc/`，保存 `P/all-05-timeout-diagnostic.json`，exit 0。测试文件、观察器及记录的三个 Python 运行时输入摘要相同，运行期间测试源码不变；候选宿主不同，不能称整套输入完全相同。79 条实际宿主记录全部为 build-05 的 `3a26124f…a28300`。

对比中本机 probe 的 bad_key、request_limit、产品 IPC probe 和 VT01 分别较 build-04 增加约 12.595、11.774、11.763、11.935 秒，其他用例也有累计增量。最后被打断用例此前 call 为 0.097 秒；缺少本轮故障栈，不能将它认定为超时根因。无全程机器负载记录，不能把“累计变慢”解释成已核实的 CPU、磁盘或特定组件故障。**速度变化原因仍 unresolved**；不扩大 900 秒，不减少用例，不启动刷通过的无因复跑，也不据本轮无 access violation 关闭旧崩溃。

结束后用普通用户只读 `Get-CimInstance Win32_Process` 检查带本轮目录或已知外层 PID 的 Python/sidecar/宿主记录，未返回匹配项；此检查仅说明所列关联过滤结果，不能代替所有子进程的创建时间核验。原生后续测试与该 all 串行。本轮日志、invocation、逐用例事件及宿主身份原样保存。

### 33.2 EXECUTE：已准备的全本机原生场景

延迟入口为 `P/native-latency-d0860c85/`（编号 `33744233`）。另外实际执行 `P/native_probe_session.py --prepare active` 和 `--prepare loss`，得到 `P/native-active-f3f51af9/`、`P/native-loss-4aa9c66d/`；三个目录各自拥有全新的合成项目、profile/WebView 和候选副本，`prepared.json` 固定 build-05 产物和八个辅助工具的摘要。prepare 没有启动窗口或提交任务。

all 结束后已将延迟入口的单步启动/合成登录说明交给用户。只有用户自行执行 `--launch` 才启动该窗口，助手不点击、输入、批准、切换前台、关闭或强退。尚未收到本轮原生执行回执时，严格样本仍为 0、p95/max/超过 1 秒数量均未测，不能填写 0 ms 或通过；活动冲突和丢响应显式重试亦仍未验收。后续用户回执与原始结果另节追加。

### 33.3 当前准入矩阵与最小后续输入

| 门禁 | 当前判定 | 依据及最小剩余条件 |
| --- | --- | --- |
| B 个人学习范围 / C 公开 PY01 | 历史结论、原候选绑定保留 | 没有重新扩大 B；旧 C 不绑定本机替身或 build-05。 |
| 四项既有原生人工回执 | 原历史候选所列场景保留 | 第 12–15 节回执不变；当前受影响链路定向回归不冒充原生重测。 |
| build-05 构建、账号失效保护与受影响链路 | 所列定向检查通过 | 第 32 节构建、Rust 12 项、前端 52 项、账号服务 3 项、账号 IPC 1 项、打包 probe 9 项；各自层次独立。 |
| build-05 完整隔离 all | **阻断，900 秒超时** | 本节首败与离线比较保留；需要能核验的变慢原因和不改原门槛的后续完整结果，不能搬用 build-04。 |
| 严格宿主至原生像素可见 | **阻断，尚无完整前台样本** | 用户运行已准备入口并按步骤提交/批准一次、保持前台；必须取得 ≥100 个完整样本，报告 p95/max/>1 秒数与负载，p95≤1 秒。 |
| 独立原生活动冲突 / 丢失创建响应显式重试 | **阻断，尚未验收** | 用户分两次独立场景操作；需同时核对 UI 回执、run/request/operation/execution、审批、文件摘要和租约。 |
| 历史取消、旧 all 超时、Python access violation、自动拒绝异常 | **未解决，继续阻断** | 第 20、29.1 节已有有界诊断；最小缺失为对应首败进程身份/栈、原生故障栈或点击到审批请求因果链。后来的通过不能关闭。 |
| unknown / reconcile | 保护状态保留 | 原未知操作未核清，不改库、不清记录、不释放并重放；人工消解后继续仍未验证。 |
| 真实 symlink | 既有真实链接的 read/patch 拒绝证据保留 | 当前没有新建特权；现场创建用例仍 skip，只能在已具备权限的隔离环境补做，不改系统安全设置。 |
| Ruff 13 个 I001 | 最小修复保留，当前检查通过 | 第 17、22、32 节；未追加无关格式化或改变既有门禁。 |
| E 目标与材料 | **目标本机已核实，材料未齐** | Windows 11 Pro 25H2 / AMD64 / 普通用户明确；仍缺本机干净快照、同产品支持升级起点/旧包匹配、来源明确的脱敏独立数据副本及 schema/一致性清单。 |
| E/F、正式 90 次、真实供应商/付费调用 | 未执行 | 保持本任务停止边界；所有新增模型调用都是本机受控替身。 |

**个人学习范围仍不具备进入 E 的工程条件。** 不能因账号改为本机或定向测试通过，就豁免未完成的原生门禁、未解决异常、当前全量超时和 E 材料缺口。build-05 只有匹配身份清单，仍为 `pre_e_loopback_account_probe_not_accepted`，没有已验收冻结决议。

**正式 D/M3 仍缺上述工程门禁，以及正式开发/保留题隔离、候选/模型身份与预算冻结、默认模型 30 题×3 次和 ≥80% 独立完成率及独立审阅、声明的 Windows/权限/真实安装组合验证。** E 的干净安装与独立数据升级/重开/安全回退、不兼容拒绝，以及 F 的匹配候选交付、签名/分发与更新回退材料仍是后续阶段要求；本任务不执行它们，也不将这些正式质量门槛重新加入个人 B。

## 34. 创建结果误报的定向修复、build-06 与当前交接

### 34.1 PLAN / EXECUTE：纠正可定位的事实提示

在核对原生丢响应步骤时，源码证实 `privateTransport` 在状态帧缺失 20 秒后抛出普通 Error；`useRunStream` 保留待确认的 client_request_id，但 `describeRunBlocker(null)` 却统一返回“执行创建失败 / 后端拒绝了本次执行创建”。当后端已创建、仅响应丢失时，这个拒绝断言没有依据。该缺陷可由现有调用链与定向测试验证，区别于没有根因证据的四项历史异常。

已向用户说明暂缓未启动的 build-05 入口，并建立具体方案：先补反例，再只区分没有结构化拒绝码时的显示文案；请求、审批和恢复逻辑不变。三个文件的入场字节先与 `P/baseline.json` 比对，再保存在 `P/before-create-copy-fix/`。随后修改：

- `apps/desktop/src/features/coding/model/runBlocking.ts`：无错误码时显示“执行创建结果未知”，要求保留原输入显式点击“重试”，不要另建任务重复提交。已有结构化后端拒绝码及其恢复入口保留。
- `runBlocking.spec.ts`：区分未确认结果与未知的结构化拒绝码。
- `composables/useRunStreamBlocker.spec.ts`：定向模拟创建响应超时，验证不声称后端拒绝、没有假 run 投影、没有自动重试，且仍给出原输入显式重试入口。

先执行 `.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/creation_copy_checks.py target`，`creation-copy-target-caa32d41/` 实际 **56 passed / 2 failed**，两处均得到旧的“执行创建失败”。再最小修改后用同命令复验，`creation-copy-target-80f77cd5/` 九文件 **58 passed，2.97 秒，exit 0**（包装器 3.687 秒）。包括原有幂等键重试、私有传输、账号和本机进程面板断言；原 300 秒上限不变。该修复只有显示事实的选择，不改变核心、IPC、运行时或恢复契约，也不关闭 all 超时。

### 34.2 TEST：新目录构建、首个工具预检失败与候选身份

`.venv/Scripts/python.exe -B .run/s6-pre-e-probes-20260916/build_v6.py` 首次在输入清单预检处退出 1：辅助脚本误以为清单仅包含 `runBlocking.ts`，实际还绑定上述两份 spec 源码。此时尚未创建 build-06 目录、未开始构建；保留 `P/build_v6-first.py`、`P/build-06-preflight-first.json`。经核对后将预期精确改为这三个已审查文件，其他组件输入、旧候选六个摘要断言不变，没有放宽为任意文件集合。

同命令复跑成功，`P/build-06/` 三阶段串行 **124.875 秒，exit 0**：vue-tsc 12.037 秒、Vite 12.669 秒、Tauri 100.062 秒，原每阶段 900 秒上限。只有桌面重建，宿主、宿主摘要文件和 sidecar 在组件输入与旧产物摘要核对后复用 build-05 的相同字节；复用来源明确保存在 build-info 与 invocation。没有安装、签名、发布或启动窗口。

| 当前 `P/build-06/candidate/` | SHA256 |
| --- | --- |
| 产品源码汇总 | `870354024788f4d4d107ea8d1dcaff1c5cd9c5e3f00fdf7001358bc3c07f4f92` |
| `PrivateAgent-windows-x64.exe` | `0bfa0138b4a64f0f5cb7d824653c0c1fb87dcd555cfef34113c5e6094fec25b7` |
| `private-agent-local.exe` | `5f137614e529c99c82b4588d817524fa332debf15196548a23b1371fae97758e` |
| `exec-host.exe` | `3a26124f1ba59de620df23c6e3e31757c1b46d01c44212c371b2b12b67a28300` |
| `exec-host.sha256` 文件 | `d474e96c49813a7455c78f02e31944304e93093c37c5b71a4015124a5125949f` |
| `build-info.json` | `9d9b85c6611e77af9040ef296a9fd9602f8ba891ce2e764a1270d96274f347e3` |
| `source-manifest.json` | `d3763455d11abcf57d481bd7b9215ad9327ddd1c349ce85b5fffd4bf720cc3cd` |

416 项输入匹配；版本、架构、产品标识、schema、协议、默认关闭的 probe feature 与第 32 节一致，purpose 仍为 `pre_e_loopback_account_probe_not_accepted`。实际执行 `P/activate_06.py` 保存选择前值并切换当前指针；所有旧产物与清单不变。

实际执行 `P/final_static.py`：`static-e09511df030c4ebf8f46f45b4763aa5c/` 中 Ruff `src tests scripts`、协议生成同步、agent_v2 依赖边界、git diff 空白检查均 exit 0，58 个辅助 Python 文件 AST 通过。此前 build-05 涉及运行链路变更已经执行完整 all，并如实失败；本次仅修提示，复验范围为上述前端链路、类型与新桌面构建，**没有给 build-06 补写或移植完整 all 通过成绩，也没有因此解除第 33.1 节阻断**。

### 34.3 原生入口与最新准入结论

再次实际执行 `P/native_probe_session.py --prepare latency`、`--prepare active`、`--prepare loss`，准备了三个绑定 build-06 的独立目录（`P/native-entries-06.json`）：

| 场景 | 目录 | 合成编号 | 当前成绩 |
| --- | --- | --- | --- |
| 严格前台延迟 | `P/native-latency-374834c4/` | `22228847` | 尚无有效样本，p95/max/>1 秒数量未测。 |
| 独立活动冲突 | `P/native-active-ed4bcbab/` | `63557335` | 待用户操作及只读关联，不记为通过。 |
| 创建响应丢失显式重试 | `P/native-loss-c10e5ec5/` | `57835883` | 待用户操作及唯一执行核验，不记为通过。 |

build-05 的三个 prepared 目录均核对未产生 launch.json，原文件全部保留，仅追加 `superseded-before-launch.json` 指向新入口。用户应使用本节的新入口，不再运行第 33 节的旧准备目录。合成账号名均为 `pre-e-local`，密码框只填该场景公开编号；账号和模型服务固定本机回环地址，不读取真实凭据。新延迟目录 `MANUAL.md` 给出逐阶段步骤，所有窗口动作由用户完成。

| 当前门禁 | 最新状态 |
| --- | --- |
| 个人学习 B / 原 C / 四份既有原生回执 | 原结论和历史候选绑定保留，不重记成本轮成绩。 |
| 创建结果事实提示 | 先红后绿的定向修复完成，58 项前端及新构建通过；真实原生丢响应场景仍待测。 |
| 严格 100 前台样本 / 原生活动冲突 / 原生显式重试 | **仍阻断**，等待用户对本节三份独立入口的实际操作与原始证据。 |
| 完整隔离 all / 历史取消、超时、崩溃和自动拒绝异常 | **仍阻断且未解决**；第 20、29.1、33.1 节失败保留。 |
| unknown / reconcile、symlink、Ruff | 未知副作用保护不变；既有真实链接限定验证保留，新建特权仍无；当前 Ruff 通过。 |
| E 材料 | **仍未齐**；本机系统/架构/权限已知，干净快照、兼容升级起点/旧包和脱敏独立数据材料仍缺。 |
| E/F、正式模型实验 | 未执行；无真实供应商或付费调用。 |

**个人学习范围目前仍不具备进入 E 的工程条件；正式 D/M3 也未准入。** 正式范围另缺第 33.3 节列明的题集/身份/预算冻结、30×3 默认模型实验、≥80% 独立完成率与独立审阅、声明安装组合及 E/F 后续验收材料。最小后续输入仍是本节三个场景的逐项人工操作、未解决异常的缺失因果证据，以及第 23 节列明的独立 E 准备材料；不要求重做已有四份手工回执或再次提供本机系统信息。

本页同步了本机服务模式、候选身份、误报根因与修复、首败和当前阻断，保留原始历史章节；已读取的 `docs/project-state.md` 按用户要求保持历史快照，不改写为新的准入结论。所有结论以对应候选和原始证据为界，没有生成已验收冻结清单。

本节实际汇总命令 `P/collect_results_06.py` 得到 `P/results-cb864d64765a495d92fa034d3c3103ce/result.json`：逐次保留 14 份 pytest 尝试（包括未完成的 probe 和各类失败）、两次本节前端首败/复跑、新构建的预检首败，以及当前无原生样本的状态；每轮候选宿主与当前候选分开记录。`P/review_06.py` 的阶段结果 `P/review-0d22b4b038e84e1b9ef852ac43b83d9e/result.json` 全部检查通过：416 项当前输入匹配，454 份保护证据、build-03/04/05 六个产物、HEAD、暂存区和历史项目状态均不变。相对 P 入场基线，现有文件仅为已列明的 15 个、新增 2 个 Rust 探针文件；另有 P 下独立工具和证据。该结果不代表未执行的原生门禁通过。

## 35. 五项缺口补齐续轮与用户手测交接

### 35.1 PLAN / EXECUTE：范围与当前候选

用户要求补上当前候选身份、完整回归、三项原生场景、历史异常与 E 材料五项缺口，随后确认没有现成干净虚拟机/快照或旧数据，要求准备可行方案。本轮先核对根指令、项目状态记忆、相关 S6 文档、Git 与既有改动，建立计划：保留原始失败和用户改动；诊断累计耗时及崩溃；按当前源码重建候选并验证；准备独立原生入口；生成来源明确的合成材料及环境方案。未放宽断言、隔离或 900 秒上限，未执行 E/F。

本轮证据根目录 `.run/s6-gap-closeout-20260917/`，下文 `G/`。`G/baseline.json` 保存 1154 项安全文件摘要、571 项历史保护证据、HEAD、暂存区及旧候选身份。入场 HEAD 仍为 `1dde393e29f3dbacd3647d11834b39824ac8323f`，已有大量未提交工作。本轮没有修改产品源码、依赖、锁文件、数据库 schema、Git 引用或系统安全设置。

当前源码已加入本机免登录入口等既有修改，与 build-06 不匹配。实际执行 `.venv/Scripts/python.exe -B .run/s6-gap-closeout-20260917/build_candidate.py`，在 `G/build-01/` 重建 sidecar 与桌面，typecheck、Vite、PyInstaller 与 Tauri 均完成；仅在组件输入和产物摘要匹配后复用原 exec-host。419 项输入与当前源码匹配。

| `G/build-01/candidate/` | SHA256 |
| --- | --- |
| 产品源码汇总 | `a43891d39598de77935a164fff9955d7698d5c58dc023af8fbcc3b213a1ef4b4` |
| `PrivateAgent-windows-x64.exe` | `6d4d0dca069e5e2f0a9cd1b7c3c9c6e31a42da160da4038d04d1a926d8ec53a3` |
| `private-agent-local.exe` | `fe6c2c5fd0717740f55bbf9ab01fa1b95e01e0f5a1d4bad41f2f6abbe56f2fe7` |
| `exec-host.exe` | `3a26124f1ba59de620df23c6e3e31757c1b46d01c44212c371b2b12b67a28300` |
| `exec-host.sha256` 文件 | `d474e96c49813a7455c78f02e31944304e93093c37c5b71a4015124a5125949f` |
| `build-info.json` | `aa6286ffcf28de2456c3c2225a3b73f06b6c8840d2785daf914cce057426cb4a` |
| `source-manifest.json` | `3fa504d942413906e64f563b6684f1df5de4b42ed3395678c83479cfa6c17f67` |

标准产品标识、1.0.0 / x64、portable、未签名，purpose 为 `pre_e_current_source_candidate_not_accepted`。构建成功解决了当前源码与候选不一致的问题，不表示验收完成。

### 35.2 TEST：实际结果及未完成的完整回归

以下命令前缀均为 `.venv/Scripts/python.exe -B .run/s6-gap-closeout-20260917/`，完整底层参数保存在对应 invocation 中。

| 实际入口 | 观察结果 |
| --- | --- |
| `frontend.py` | `frontend-5431d40be16c4a3b923663b1160caa55/`：Vitest 94 文件、566 tests passed，26.97 秒，底层 exit 0。包装器随后打印 Unicode 勾号时发生 GBK 编码错误；已把包装器 stdout 设为 UTF-8，不把包装器首败隐藏，也没有因此重复整套测试。 |
| `validate.py cancel` | `cancel-191efae47ae24f9eb8a6856edce24b24/`：原取消/超时用例 1 passed，18.69 秒，exit 0；不替代历史首败的因果解释。 |
| `validate.py profile` | 首次辅助入口缺少 json 导入，在测试前失败；下一次受限工具令牌下执行宿主启动失败，测试 1 failed。原 cProfile 命令又未正确传播 pytest 退出码；分别保留原记录，修正辅助包装器。普通用户权限的 `profile-a6c8c98582544c0798665a1c13481492/` 实际 1 passed，51.06 秒，退出码正确传播。 |
| `validate.py all` | `all-fd29ba2f57bf4254b7532eef3c040963/` 收集 981 项；900.001 秒超时，invocation exit 124；939 passed call、1 skipped call，其余未完成。最后正在执行 `test_real_host_nonzero_exit_is_preserved`，不能认定它是超时根因。没有 pytest 完整通过结果。 |
| `inspect_crash_metadata.py`、`unwind_crashes.py` | 均 exit 0，离线核对两份历史转储的异常、匹配模块及原生调用栈，只保存必要元数据与模块偏移，不导出进程内存。 |
| `prepare_upgrade_materials.py`、`prepare_e_bundle.py` | 五版历史数据生成均 exit 0；15 份 SQLite 完整性检查通过。74 项介质文件摘要和 `.wsb` XML 校验通过，未运行虚拟机。 |

all 的逐用例事件、宿主进程身份、每秒机器 CPU 采样均保留。较慢的实际 call 包括 bad_key 72.833 秒、request_limit 59.517 秒、VT01 55.264 秒、local probe pass 49.800 秒、产品 probe 46.865 秒、RS01 42.423 秒。定向 cProfile 显示路径校验、运行时复制和摘要校验占用较多时间，但不足以证明某一安全检查可删除或缓存。尚未完成可靠的性能修复；保留当前超时，不扩限、不减测试、不把部分通过改为完整通过。

### 35.3 历史异常：新增原生栈证据，不夸大归因

找到对应 PID 39376、16000 的两个历史 Windows minidump，SHA256 分别为 `75d73ba40aeaf3dabc3b301404f6d179be11c2fd1ec49ac56b9d43d5381e5fb5`、`be83604a840490113b3421f798a1093ab02cb7acabd31f87e719a14e906a1e81`。`G/crash-metadata.json` 核对两者均为读访问冲突 `0xc0000005`、`python312.dll+0xc9723`，本地 DLL 的时间戳及映像大小与转储相符。

`G/crash-native-stacks.json` 使用已安装的 DbgHelp `StackWalk64`、转储中的线程上下文/内存和匹配 PE 的展开表离线展开。两个故障点均位于已匹配函数边界的 `PyCode_Addr2Line+43`，调用链包含已匹配的 `_Py_DumpTracebackThreads`；PID 16000 的栈中还出现异常派发后再次进入相同转储链。没有 PDB 的内部帧只记录模块偏移，最近导出符号不被当作真实函数名。

这把崩溃现场缩小到了 traceback 转储链，而不是此前日志最后打印的 `pathlib.lstat`。仍未证明坏对象的最初来源或具体竞争条件，也未证明项目代码无关。展开方式依据 [Microsoft StackWalk64 文档](https://learn.microsoft.com/en-us/windows/win32/api/dbghelp/nf-dbghelp-stackwalk64)；CPython [类似 faulthandler 崩溃报告](https://github.com/python/cpython/issues/116008)仅作为调查线索，不作为本机根因已证实的依据。

历史取消首败缺少完整原始栈/进程身份，旧 all 缺少逐用例时间，早前自动拒绝缺少点击到请求的完整关联；这些历史缺失不能通过新测试补造。本轮没有宣称四项异常均已关闭，也没有更换解释器或禁用安全逻辑。

### 35.4 原生场景改由用户手测

助手启动了 `G/native-latency-e128e227/` 的隔离候选与本机替身；获取窗口状态的应用授权请求超时，未发生点击、输入、批准或关闭。用户随后明确要求不再操控电脑。已停止所有窗口自动操作，`operator-handoff.json` 记录实际边界，原始准备及启动记录不覆盖。

| 场景 | 当前目录 | 编号与状态 |
| --- | --- | --- |
| 延迟 | `G/native-latency-e128e227/` | `32435733`；窗口已启动，待用户操作与有效采样核对，尚未验收。 |
| 活动冲突 | `G/native-active-a139f43f/` | `84522337`；用户手测启动器准备完毕，未启动。 |
| 丢响应显式重试 | `G/native-loss-c4a5c617/` | `48227258`；用户手测启动器准备完毕，未启动。 |

完整步骤与逐项预期见 [当前原生手册](s6-current-native-manual-20260917.md)。使用免登录本机入口和 Ollama 合成服务，不填写真实账号或密钥。后两项启动命令使用 `G/native_probe_manual.py`；该辅助脚本明确记录 `window_operator=user_manual`、助手输入动作数 0。更早 prepared 目录全部保留，但不再作为当前操作入口；没有给任何未操作场景补写通过结果。

### 35.5 E 材料、记忆同步与当前结论

按用户“没有现成材料，请准备可行方案”的回复，已完成 [E 环境准备方案](s6-e-environment-preparation-20260917.md)、schema 3–7 各三份独立合成起点、来源/完整性清单、只读介质和可选 Sandbox 配置。完整 E 推荐使用可保存快照的标准用户虚拟机；Sandbox 只用于明确标注的一次性冒烟。真实旧安装包匹配、实际干净快照、安装/升级/回退仍未验证，不把 QA Candidate 安装包当标准产品升级起点。

当前五项状态为：**候选与源码一致性已补齐；完整回归仍超时；三项原生场景待用户手测；历史异常有新增栈证据但未全部闭合；E 准备方案与合成材料已交付，真实环境尚未执行。** 因此仍不具备宣布进入 E 的工程条件。

本轮修改仅为本节和两份关联说明，另有 G/ 下隔离工具、候选及证据。项目记忆已读取并核对；发现此前“当前候选 build-06”的描述不再匹配本轮源码，用本节当前身份纠正，历史记录保留。`docs/project-state.md` 继续按仓库约定保留历史快照，不改写为验收完成。原始失败、旧候选、B/C 绑定及已有四项用户回执不变。

## 36. 本机学习范围调整：E/F 阶段取消

2026-09-17，用户明确要求“把这两个阶段给去掉，只要能在本机上运行即可”，用途为学习 Agent 知识，不发布或适配各种系统。该决定替代第 35 节末尾继续补齐 E 准入材料的任务方向。

| 项目 | 当前处理 |
| --- | --- |
| E：干净安装、旧数据升级、程序回退和多版本组合 | 已从活动计划取消，不再准备或执行相关环境与材料；没有记为验收通过。 |
| F：正式汇总、签名分发及服务器/客户端更新 | 已从活动计划取消，不再准备正式 M3 决议或更新发布任务。 |
| 本机 Agent 功能 | 保留当前电脑上的启动、模型连接、读取/修改/验证、diff 与结果查看、退出和历史重开检查。 |
| 数据与权限保护 | 保留审批/拒绝、取消、用户文件保护、明确报错及未知操作禁止自动重放；学习用途不改变产品保护行为。 |
| 正式模型与性能评测 | 沿用个人学习口径；正式 90 次/80%、独立审阅和严格 100 样本性能测量是可选实验，不作为开始学习的条件。 |
| 900 秒完整回归超时、历史异常和待测原生场景 | 真实结果原样保留为已知问题或未验证范围。后续按本机实际影响定位修复，不据取消 E/F 宣称它们通过或已解决。 |
| 已准备的 E 方案及 15 份合成旧数据库 | 历史存档，停止追加，不删除或改造旧证据；用户无需创建虚拟机或寻找旧安装包。 |

本机学习以 [主计划第一部分](s6-follow-up-development-plan.md#1-目标与完成边界) 的四项基本标准收尾，A–D 的已有功能与成果保留。先完成当前机器的实际练习流程；只有遇到相关问题或用户希望深入研究时，才使用 [原生专项手测说明](s6-current-native-manual-20260917.md)。窗口操作继续由用户完成，助手不操控电脑。

本次只调整计划和说明，没有新增运行测试或修复产品代码，因此不新增“本机全部通过”结论，也不更改测试断言、超时配置或正式报告中的历史状态。后续无需等待 E/F，也不将停止发布准备解释为正式发布已获批准。

项目记忆同步：已读取根指令、`docs/project-state.md`、主计划和本页历史记录。核实旧描述仍要求 E/F，与本轮明确的学习目标冲突；已同步主计划、总体路线、本页和手测说明，并将 E 方案标为取消后的历史存档。`docs/project-state.md` 继续保留其既定历史快照，未创建新记忆体系。
