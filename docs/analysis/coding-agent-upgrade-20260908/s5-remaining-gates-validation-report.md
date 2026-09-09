# S5 剩余门禁验收记录

日期：2026-09-09（Asia/Shanghai）。仓库 `F:\Program\Agent`，分支 `dev/1.0.0`，接手 HEAD `d0250ee`，暂存区为空。完整读取本目录交接提示词，保留前轮 S5 源码、未跟踪文件、安装候选和失败现场；没有推送、部署或进入 S6 开发。

## 当前结论

**S5 及 S0–S4 全部适用阻断门禁已通过，可进入 S6。** 普通 ConPTY、真实安装客户端的运行中协作与关联恢复、持续执行和故障注入均有通过证据。最后的界面修复已重新构建、安装并严格核对；前台 120 条完整样本的 p95 为 **386.70 ms ≤ 1000 ms**。用户创建的真实符号链接已实际验证读取与补丁预览拒绝、目标摘要不变，独立证据补足了自动套件的权限 skip，未篡改套件统计。

本机 Windows QA 范围内满足 M1/M2 和 S6 开工前置条件；M3、真实模型质量及完整交付演练仍属于 S6。临时回环模型已从实际 UI 删除并重新加载核对，原有两个供应商保留；服务已停止，验收命令全部停止、工作区租约已释放、沙箱租约为 0。本轮交付边界是仅在本地提交 S5 后停止；没有推送、部署、发布或进入 S6 开发。

## 实施范围与必要修复

1. 沿既有 exec-host 实现修复 ConPTY：空环境块保证双 NUL；伪控制台句柄使用 `ClosePseudoConsole`；属性缓冲区对齐并按正确 API 释放；创建期间保留管道端点，关闭 stdin 的模式保留内部输入端；设置 `STARTF_USESTDHANDLES` 和空标准句柄，避免继承宿主重定向后绕过伪控制台。进程退出后在执行表锁之外关闭伪控制台，再等待输出读线程完成，防止末尾输出被误判不完整。
2. 能力探针使用系统 `cmd.exe` 正对照，并以实际 PTY 输出判断能力。普通 PTY 的控制台输入、中文输出、末尾排空及取消回收已验证。**受限 AppContainer 仍只支持禁网 argv；受限 PTY 明确拒绝。** 没有放宽工具目录扫描、祖先目录 ACL 或网络权限。
3. 本机接收泵在读取宿主完整 JSONL 帧后立即记录 UTC 毫秒时间，作为 `ExecEvent` 私有属性，不接受宿主伪造的同名协议字段。现有轻量 `execution.output` 事件附加首块宿主序号和接收时间，复用原输出事实与游标，不新增数据库表或第二套日志内容。
4. `ExecutionPanel.vue` 仅在用户位于尾部时跟随内外两层滚动，保留用户向上翻阅的位置。`RecoveryPanel.vue` 限制可滚动高度，防止长审查列表挤压后溢出并遮挡恢复操作。宽窄窗口浏览器回归及最新实际安装复测通过；真实审查面板高度 486.71 / 1082 px、滚动高度 589 px，未侵入输入区，刷新按钮命中并实际点击成功。
5. 修复十分钟专项的夹具导入与未推进输出游标的问题。旧 API 专项原来仍断言 S0 的 120 秒超时，和已提交 S4 的默认 600 秒契约冲突；改为验证实际命令跨过 120 秒并在 130 秒正常退出，启动准备与后续模型等待分别计时。受限 Node 使用已验证的 `--preserve-symlinks-main`，没有扩大 Python 超过 50000 项的工具授权范围。
6. 在真实宿主输出到本机监控的边界注入旧执行 ID、重复序号、缺失序号，验证结果记 unknown、错误输出不入当前任务、原执行记录不变且新进程回收。

ConPTY 生命周期依据 [Microsoft 伪控制台会话说明](https://learn.microsoft.com/en-us/windows/console/creating-a-pseudoconsole-session) 与 [ClosePseudoConsole](https://learn.microsoft.com/en-us/windows/console/closepseudoconsole)；具体结论来自本机诊断和回归，而非仅凭文档推断。

## 实际验证

后端命令均在仓库根执行，使用现有隔离运行器，不加载业务环境或生产数据库。前端命令在 `apps/desktop` 执行。以下结果按执行时的源码记录，不能相加当成独立覆盖率。

| 实际命令 | 结果与证据 |
| --- | --- |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite host` | 16 passed，78.96 秒，无 PTY skip；`host-adfb262ac55e4bd0882ef5b1ec1fd0ba`，`host-after-2.log`。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite execution` | 第一轮 16 passed，18.61 秒；补充身份故障注入后 19 passed，19.26 秒，`execution-24e4b66844f345ffaa4504dbf773ca43`，`execution-identity-final.log`。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all` | 346 passed、1 skipped、0 xfail，256.49 秒，`all-f471c4b10d2b48c389b3103fcbf217f9`，`all-final-1.log`。唯一 skip 是真实符号链接创建权限不足。本次结果早于之后新增的 3 项身份注入测试；这些新增项由上行专项验证。后端产品源码此后未变。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_legacy_validation.py` | 106 passed，10.02 秒，`legacy-472e4670dda04653905d38167d24e275`，`legacy-final.log`。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite execution-duration` | 1 passed，601.07 秒，真实命令持续 600 秒，STARTED/FINISHED 各一次、游标无重复、退出码 0、进程已停止；`execution-duration-bde5e4701574436c8dfd87e51636f325`，`execution-duration-final-3.log`。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite duration` | 1 passed，142.67 秒；命令约 130 秒正常退出，单独记录沙箱准备耗时，旧 API 输出仍为结果完成后返回；`duration-ffe746c5a8cd42b2a3f60f01932ca572`，`legacy-duration-final-boundary.log`。此专项本身不是十分钟测试。 |
| `npm run test -- src/features/coding src/services/localExecutor.spec.ts src/services/privateTransport.spec.ts` | 35 文件、223 passed，10.94 秒；`frontend-final.log`。 |
| `npm run test -- src/features/coding/components/ExecutionPanel.spec.ts src/features/coding/components/RecoveryPanel.spec.ts` | 最后一次界面裁剪修复后 8 passed，1.98 秒；`frontend-layout.log`。 |
| `npm run e2e -- e2e/coding-run.spec.ts --grep S5 --retries=0` | 最后一次界面修复后 1 passed，6.1 秒；新增长审查列表在 1365×900 与 760×700 的控件命中及面板边界检查；`e2e-layout.log`。浏览器真实渲染、HTTP 替身，不能代替实际 Tauri。 |
| `node --test scripts/build-remote-client.test.cjs` | 10 passed；`build-script-final-native.log`。 |
| `.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check` | `protocol codegen in sync: OK`。 |
| `.venv/Scripts/python.exe -B scripts/check_agent_v2_imports.py` | `agent_v2 dependency rules: OK`。 |
| 下方 Ruff 命令 | `All checks passed!`，包含最终身份注入及两个持续时间专项。 |
| `git diff --check` | 检查通过；Git CRLF 规范提示不计作失败。 |
| `.venv/Scripts/python.exe -B .run/s5-remaining-20260909/verify-symlink.py` | 真实符号链接检查通过，`symlink/validation-result.json`；执行时链接位于用户指定的测试目录，随后单独归档。 |
| `.venv/Scripts/python.exe -B .run/s5-remaining-20260909/verify-combination.py` | `passed=true`，`combination-verification.json`。 |
| `.venv/Scripts/python.exe -B .run/s5-remaining-20260909/verify-latency-final.py` | 120 个样本逐条关联通过，p95 386.7043 ms，`latency-final-verification.json`。 |
| `node .run/s5-remaining-20260909/ui-layout.cjs .run/s5-remaining-20260909/review-layout-final.cjs` | 最新安装客户端的审查列表、控件命中与实际刷新通过；`review-layout-final.json/png`。 |
| `.venv/Scripts/python.exe -B .run/s5-remaining-20260909/verify-final-state.py` | 原 60 个工作文件仍存在，原测试目录 7 个文件摘要和 HEAD 不变；任务/执行停止、租约及模型清理检查通过，`final-state-verification.json`。 |

```powershell
.venv/Scripts/python.exe -B -m ruff check src/private_agent_local src/private_agent_core/execution/contracts.py src/private_agent_core/execution/exec_host_client.py scripts/run_coding_validation.py scripts/verify-unified-client.py scripts/s5_acceptance_model.py tests/unit/test_local_recovery.py tests/unit/test_local_store.py tests/unit/test_local_context_history.py tests/unit/test_local_patchsets.py tests/unit/test_windows_sandbox.py tests/unit/test_local_execution_sessions.py tests/unit/test_local_exec_host.py tests/unit/test_local_history.py tests/coding_acceptance/recovery_process.py tests/coding_acceptance/test_baseline.py tests/coding_acceptance/test_host_duration.py tests/coding_acceptance/test_host_probes.py tests/coding_acceptance/test_s4_duration.py
```

原生命名管道和 Node 子进程在工具沙箱下出现过 WinError 5 / EPERM，随后经工具审批在本机运行隔离测试。未改操作系统权限设置。旧失败日志均保留在 `.run/s5-remaining-20260909`：ConPTY 参数错误/输出绕过、十分钟夹具导入错误及游标忙循环造成的 900 秒运行器超时、旧 API Python 授权树超限、旧 120 秒断言和把模型等待误计进命令耗时等，不写成产品测试通过。

## 候选身份与冻结运行

构建入口：`scripts/build-remote-client.cmd --unified --qa --preview-installer --version 1.0.0`。两次都实际执行 vue-tsc、Vite、Rust release 与 NSIS，成功；保留现有 Vite 大 chunk 及 Rust 未使用项警告。

| 候选 | 用途与证据 |
| --- | --- |
| `.run/unified-client-OZ2FIp` | ConPTY 与时间戳修复后的候选；636 文件摘要 `256d685fae2d98525471a3239824f4505b20abb0e6a9f1577cf37d09d346fdf5`。已实际安装于 `.run/s5-candidate-install-20260909-remaining`，完成下节协作组合。 |
| `.run/unified-client-gHXwHg` | 补齐内外层滚动和恢复面板高度约束的最新候选；636 文件摘要 `c76f8a84d421a661eecc4419d2d6ba9e84a4e48d7ffcdc9bdf4c12d39ba7d658`。已安装于 `.run/s5-candidate-install-20260909-layout`，实际前台输出与审查复测通过；收尾再次核对源码、4 个产物及 4 个安装文件。 |

最新产物：

| 文件 | SHA-256 |
| --- | --- |
| `PrivateAgent-windows-x64.exe` | `55aefbb246f23d0fa88681de120e726164502596b367101fd51e1707662a00c5` |
| `private-agent-local.exe` | `513d062f270ce4139f330b9c291cbb5efd896e2627d98bb0cb903f2eede4c91c` |
| `exec-host.exe` | `e508c9e6965126b66f1652051c7468642498b825f32daeabf91779a9eb5cc57b` |
| `PrivateAgentCandidate_1.0.0_x64-setup.exe` | `525f05397ef54bc649e9038fdbac5213537f2ec51036dbc57bcd99fa4d2287bc` |

实际运行：

```powershell
node .run/s5-remaining-20260909/verify-integrity-layout.cjs .run/unified-client-gHXwHg
.venv/Scripts/python.exe -B scripts/verify-unified-client.py --bundle .run/unified-client-gHXwHg --work-dir .run/s5-remaining-20260909/frozen-layout --model-mode openai
node .run/s5-remaining-20260909/verify-integrity-closeout.cjs .run/unified-client-gHXwHg
node .run/s5-remaining-20260909/verify-installed-closeout.cjs
```

冻结结果 `passed=true`，隔离目录 `frozen-layout/packaged-runtime-hjjuovrl`。账号/模型均为本机替身；文件写入、人工批准命令、PowerShell、显式 full_access 脚本、用量、篡改宿主拦截、4 条历史运行导出、登录退出清理通过，`real_model_called=false`。前一候选也通过同入口，证据 `frozen/packaged-runtime-ydxrknib`。两次安装副本核对均只允许唯一 `__TAURI_BUNDLE_TYPE_VAR_UNK` → `NSS` 标记的精确差异，其余字节及三个附属文件完全相同，不替换已安装主 EXE。最新安装主 EXE SHA-256 为 `263b2c763273263d439a221b5c3801a574c530da2a79c141289a80c193adbb78`；证据 `candidate-integrity-closeout.json`、`installed-integrity-closeout.json`。

## 真实已安装客户端的协作组合

通过实际 Tauri WebView 可见控件操作；未注入应用状态、未模拟本机 API。项目为用户已选择的 `F:\Program\test`，仅增加独立 `s5-remaining-20260909` 子目录。用户自行登录。临时模型为经真实 UI 保存的 `S5 剩余门禁验收（临时）` / `s5-acceptance-loopback`，65536 tokens，回环端口 2321，无密钥；收尾已删除并核对其他供应商保留。

| 阶段 | 实际观察 |
| --- | --- |
| 开始修改和命令 | 会话 11，run `8cd0c988-dc6d-4112-b342-71a46a51fd64`。任务补丁写入 result.txt；经实际审批启动受限 Node 父子夹具，禁网。父进程 PID 2920、子进程 PID 21508，各仅一条启动记录。 |
| 追加约束 | 分别有 received_at 和 applied_at；有效的停止写入/只解释约束于 09:10:35 UTC 生效，generation 随控制推进。中间一次过期 state_version 返回 409，未自动重试或误记生效；刷新现场后重新操作。 |
| 暂停与迟到响应 | generation 3、状态 paused。父子均已退出，tick 文件不再增长。模型请求 s5-5 的延迟写入响应在约束生效后 56 秒尝试返回，`stale-after-control.txt` 始终不存在，执行记录未增加。 |
| 同进程继续 | 保留原 run ID，暂停时模型 5 / 工具 3 的预算未清零；下一请求使模型预算增至 6。 |
| 强退、重启和核对 | 先核对 PID、绝对路径与创建时间，只终止 Tauri 主进程 24204。11 个所属进程全部退出，实际 875 毫秒，非仅取消请求返回。旧 run 由退出协调收束为 cancelled，generation 4，清理已确认；未伪称 interrupted。原父子命令在此前暂停时已经退出，此 875 毫秒不冒充长命令强退回收时长。 |
| 关联继续 | 用户重启登录后核对文件/变更；创建新 run `30eb99e5-bb3c-48ca-9913-3c584fa82f20`，logical_task_id / resumed_from_run_id 指回旧 ID。三个已注册的 `read_code_file` 实际执行成功，读取 result.txt 和父子启动记录，非仅模型提出读取请求。 |
| 预算与审查 | 累计模型 10 / 工具 6 / 活动 224.36 秒，费用仍未知；没有新启动命令。旧终态、63 个事件序号、原已采集的 8 个控制/输出事件内容保持一致。界面区分两组任务补丁、8 项起始改动和命令候选变化，保留 preexisting.txt。 |

证据位于 `.run/s5-remaining-20260909/scenario-*.json`、`ui-*.json/png`、`model/model-events.jsonl`、`paused-processes.json`、`force-remaining-combination.json`。独立验证命令 `.venv/Scripts/python.exe -B .run/s5-remaining-20260909/verify-combination.py` 返回 `passed=true`，结果 `combination-verification.json`。原七个测试文件 SHA-256 与基线 HEAD `b7a71686b018dab66695752e3717196e1e91cf44` 均未改变。

组合过程保留两项无效证据的正确归因：第一次延迟夹具 s5-3 在停止约束之前已经返回并写入 `late-forbidden.txt`，不能拿它证明迟到响应被拒绝；随后 s5-5 才是真正的约束后迟到探针。最早一次自动化等待 15 秒短于受限启动准备，脚本超时不等于命令未启动。晚到禁止写入文件未被删除以掩盖执行事实。

前轮固定审查脚本曾被误用于新 run，覆盖 `.run/s5-blockers/review-before-external.json`。已立即保存本轮结果到 `review-final.json`，从前轮任务完整工具输出恢复原 JSON 内容，715 字节，SHA-256 `3cf4afc77999d9247f53c8139bec0764e24121de171a8fae4c16c87fbaa3f247`；恢复来源与核对步骤保存在 `review-recovery-provenance.json`。原修改时间元数据未保留，不能声称该文件从未被改动。前轮脚本仅以模型请求数量判断读取，且工具名为未注册的 `read_project_file`；本轮改用实际执行结果为 completed 的 `read_code_file` 证据，不继续沿用旧计数作为“读取成功”的证明。

## 前台输出延迟与真实符号链接

延迟预先固定目标为 **p95 ≤ 1000 ms**，负载为真实受限 Node 命令在 4 秒准备后每 250 ms 输出一个 UTF-8 中文标记，共 120 个。起点是宿主帧抵达本机接收泵；终点是实际 WebView 中标记连续两次 requestAnimationFrame 均处于可视区域、未被祖先裁剪且 elementFromPoint 未被遮挡后的 UTC 毫秒时间。同机 Windows UTC 时钟，另记录 performance 时钟差的最大变化；p95 使用排序后 `ceil(0.95 * N)` 的 nearest-rank，不计模型首 token 延迟。

第一次采样在最小化窗口进行，不具备原生前台可见前提；WebView 的 visibility/hasFocus 仍可能返回可见，因此必须结合原生窗口状态，不能据此放行。保留 `ui-latency-samples.json`（118 个标记，119/120 被外层裁剪）、`ui-latency-final.png` 和 `ui-latency.log`（等待全部 120 个标记超时）。诊断值 p95 1710.09 ms、最大 9990.64 ms，**不是通过结果**。对应命令退出码 0，随后回环模型保持等待到超时使 run 失败；命令与任务终态分开记录。

最终前台复测 run `ce412d1e-a5d4-4266-87fb-bfe3e08a5b4e`、execution `c2f0f950-0335-48a3-9737-1c99b2256179`。用户还原窗口后，原生截图在批准前和采样期间确认可见；120 个标记、120 个宿主序号和 120 条持久化输出事件一一对应，未丢弃或筛选样本。p95 **386.7043 ms**，最小 46.6582 ms，最大 5034.1030 ms，超过 1 秒的样本 1 个；隐藏帧 0，时钟差最大变化 1 ms。长尾仍完整披露，此门禁判据是预设 p95。命令退出码 0、stopped=true，随后通过实际“取消任务”停止模型等待，run 收束为 cancelled、工作区租约 released。

采样入口为 `node .run/s5-remaining-20260909/ui-layout.cjs .run/s5-remaining-20260909/start-latency.cjs`，随后执行同入口的 `measure-latency-final.cjs`。原始证据为 `ui-latency-final-samples.json`、`ui-latency-final-visible.png`、`scenario-latency-final.json`；逐项关联和完整时间戳见 `latency-final-verification.json`。观测的是实际安装 WebView，没有使用浏览器 HTTP 替身页面。

自动创建真实符号链接曾返回 WinError 1314。用户在独立目录创建 `F:\Program\test\s5-remaining-20260909\symlink\project\link.txt` 后，实际验证其为 reparse tag `0xA000000C`、准确指向 `outside.txt`；Repository 读取与补丁预览均返回“项目工具不访问符号链接或目录联接”，目标 SHA-256 未变。证据 `symlink/validation-result.json`。这项独立真实检查补足门禁，但原 `all` 的 1 skipped 统计保持原样。

链接夹具自身令后续命令的有界工作区版本扫描失败关闭，一次可信项目尝试也在审批前被拒绝，没有启动命令；记录 `scenario-latency-symlink-rejected.json`。验证后只将该链接移动至 `.run/s5-remaining-20260909/symlink/captured-link.txt` 归档，原目标和其他测试文件不变，详见 `symlink/archive-record.json`。最终延迟负载恢复使用 restricted / network=none；没有放宽链接检查或通过可信权限绕开它。

## S5-T01–T15 与前置门禁

“通过”限于表中声明的实现和证据层级；不宣称通用活进程重新附着、任意系统 PID 复用演练、全部平台或真实模型质量。

| 用例 | 当前证据 | 结果 |
| --- | --- | --- |
| S5-T01 模型/工具提交边界退出 | 当前 all 内 8 种真实子进程退出边界及 SQLite 事务故障；检查点与事件同步、不重放。 | 通过，真实进程/SQLite。 |
| S5-T02 多文件中途退出 | patch.intent/disk/record 注入，逐文件事实、部分写入、未确认状态阻断；原有文件保留。 | 通过，真实文件/SQLite。 |
| S5-T03 命令结果前退出 | 真实宿主启动后服务退出记 unknown，阻止 resume 与第二写入者；实际安装组合未重复启动命令。 | 通过，真实进程及安装。 |
| S5-T04 宿主身份与迟到输出 | 原通道失去后不凭 PID 重新附着；真实新宿主边界注入旧执行 ID、重复/缺失序号，拒绝串流、回收新进程、旧记录不变。 | 通过，协议故障注入；未制造内核 PID 复用。 |
| S5-T05 审批、撤权、账号切换 | 重启关闭旧审批；新授权前拒绝继续；账号未绑定 401、其他账号旧记录 404；安装重启由用户重新登录。 | 通过，隔离 HTTP/SQLite 与安装认证。 |
| S5-T06 steer 幂等与迟到模型 | 重复消息只应用一次；真实 s5-5 在已应用约束后尝试返回，旧写入没有执行。 | 通过，源码故障注入及安装。 |
| S5-T07 冲突约束 | 首文件落盘后注入 steer，第二文件不写；真实组合保留已写结果与控制生效边界。 | 通过，真实文件与安装。 |
| S5-T08 pause/cancel/批准竞态 | 审批后暂停取消、启动宿主期间暂停、迟到批准不启动旧操作；真实 UI 暂停父子夹具。 | 通过，隔离回归与安装。 |
| S5-T09 累计预算 | 关联继续、预算耗尽、verification_retries 保留；真实组合 5/3 → 6/3 → 10/6。 | 通过，SQLite/安装；真实组合失败计数为 0，非非零计数演练。 |
| S5-T10 同目录与跨仓库并发 | 规范路径/Git 子目录锁键一致、同仓库串行、跨仓库并发及账号归属。 | 通过，真实 Git/SQLite。 |
| S5-T11 旧持有者与未知宿主 | 很旧的账号标记不超时夺锁，缺失工具终态但宿主未核实也不释放；独立所有权 OS 锁。 | 通过，真实文件锁及故障注入。 |
| S5-T12 dirty 与外部修改保护 | 当前回归拒绝冲突回滚，前轮安装记录保存外部修改并实际完成无冲突回滚；本轮原七文件摘要一致。 | 通过，真实 Git/文件及前轮安装证据。 |
| S5-T13 worktree | 真实 detached worktree、显式 ref、幂等/冲突、dirty/未跟踪文件清理拒绝和干净清理。 | 通过，真实 Git；无未提交内容搬运或自动修复失败目录。 |
| S5-T14 检查点/能力兼容 | 摘要/格式/未来 schema/模型配置变化失败关闭；旧宿主拒绝可写但保留只读；当前包篡改宿主拦截。 | 通过，SQLite/协议与冻结包。 |
| S5-T15 重连与关联历史 | 当前投影、重复帧/缺口/快照测试；真实同 ID 继续及新 ID 关联恢复，原事件序号不变。 | 通过，浏览器与实际安装。 |

| S0–S4 / 统一门禁 | 当前结论 |
| --- | --- |
| 完成真实性、上下文约束/预算、历史、补丁与迁移 | 当前 all 及旧协议 106 项通过；生命周期 completed 未冒充编码目标通过。 |
| 零自动重复未知副作用、零静默覆盖 | 当前故障矩阵、原文件摘要、回滚保护与真实组合通过。 |
| 原生文件/网络与子进程边界 | 当前 all 内 AppContainer 正反对照、独立 SID、硬链接/目录联接拒绝、撤权及清理通过；真实符号链接以用户创建的夹具独立验证通过。 |
| 普通 ConPTY、stdin、Unicode、大输出、服务、取消 | host 与 execution 专项通过；受限 PTY 不支持并明确拒绝，未静默降级。 |
| 十分钟持续命令与旧 120 秒限制 | 两个独立专项通过，分别 600 秒与 130 秒命令。 |
| 宿主收到至实际 UI 可见 p95 ≤ 1 秒 | 新候选真实前台完整 120 样本 p95 386.70 ms，通过。保留首轮失败和本轮最大值。 |
| 匹配的可安装候选 | 最新 636 文件源码摘要、产物、冻结运行、实际安装及受影响的界面复测均通过。 |
| S6 真实模型质量与交付演练 | 每模型 90 次任务、真实 Provider 支持矩阵、干净环境安装/升级/回退及正式签名发布属于 S6，未开展，也不是本轮回环模型能证明的能力。 |

## 文件、记忆与收尾边界

本轮在原 S5 工作上修改的产品文件是 `apps/exec-host/src/main.rs`、`sandbox.rs`，`src/private_agent_core/execution/contracts.py`、`exec_host_client.py`，`src/private_agent_local/execution_sessions.py`，`ExecutionPanel.vue` 与 `RecoveryPanel.vue`；对应修订宿主/持续执行测试、两个持续时间专项、ExecutionPanel 单测与 S5 浏览器回归，扩展回环模型夹具的有界延迟。没有升级依赖、改锁文件、修改正式更新源或服务器配置。

完整读取 `docs/project-state.md`、根 AGENTS、S4/S5 阶段材料、总体路线与统一客户端说明，只读核对 S6 入口。历史记忆记录 2026-08-31 的旧盘符/HEAD，与当前 Git 和实际安装证据存在时间差；按根 AGENTS 的专项约定保留历史记忆原文，将新能力、失败归因、支持边界与门禁状态同步到本报告、S5 报告入口、路线和统一客户端说明。未新建项目记忆系统。

收尾核对原工作区清单、最新源码和安装摘要，原 60 个工作文件仍保留；原测试目录七文件和 HEAD 不变。临时模型删除后第一次列表校验早于异步加载完成而失败，未重复删除；等待原有 Ollama / deepseek 条目后精确比对通过，`provider-deleted.json` 记录事实。本轮模型服务经 PID、路径和精确创建时间确认后停止，端口 2321 无监听，证据 `model-stopped-final.json`。全部本轮任务已终结、命令 stopped=true、工作区租约 released、候选沙箱租约记录 0，见 `final-state-verification.json`。

最后通过实际退出确认框正常关闭候选，退出码 0；按退出前记录的 PID 与创建时间核对，11 个所属进程均已结束，证据 `candidate-tree-before-normal-close.json`、`candidate-normal-close-final.json`。采样后取消脚本最初使用不存在的 test ID 而超时，改用页面实际的“任务恢复与协作”区域后正常取消；没有重复启动负载或把定位超时当产品取消失败。

完整 diff 和未跟踪源码按 S5 范围审查，临时脚本、安装产物、日志与验收数据全部保留于忽略目录，不加入 Git。所有适用门禁通过后仅本地提交 S5；提交哈希以本地 Git 记录及交付答复为准。停止于 S6 开发之前，不推送、部署或发布。

## S5 本地提交文件清单

以下 65 个文件对应接手以来的完整 S5 变更集，包含保留的前轮实现和本轮必要修复；未把读取过的历史记忆或 `.run` 证据列作源码改动。

| 文件 | 状态 | S5 关联 |
| --- | --- | --- |
| `apps/desktop/e2e/coding-run.spec.ts` | 修改 | 运行中协作和长审查面板宽窄窗口回归。 |
| `apps/desktop/src-tauri/Cargo.toml` | 修改 | 增加独立 QA 构建特征。 |
| `apps/desktop/src-tauri/src/credentials.rs` | 修改 | 隔离候选凭据命名空间。 |
| `apps/desktop/src-tauri/src/lib.rs` | 修改 | 隔离 Windows 候选配置目录。 |
| `apps/desktop/src/features/coding/api/recovery.ts` | 新增 | 恢复、控制、审查及 worktree 接口类型。 |
| `apps/desktop/src/features/coding/components/CodingHome.vue` | 修改 | 接入显式 worktree 入口。 |
| `apps/desktop/src/features/coding/components/CodingThreadWorkspace.vue` | 修改 | 接入恢复与协作面板及关联继续。 |
| `apps/desktop/src/features/coding/components/ExecutionPanel.spec.ts` | 修改 | 验证内外层尾部跟随和保留历史阅读位置。 |
| `apps/desktop/src/features/coding/components/ExecutionPanel.vue` | 修改 | 修复持续输出及末尾文字被裁剪。 |
| `apps/desktop/src/features/coding/components/RecoveryPanel.spec.ts` | 新增 | 控制幂等、失效响应及关联恢复回归。 |
| `apps/desktop/src/features/coding/components/RecoveryPanel.vue` | 新增 | 恢复现场、追加约束、暂停继续与有界审查滚动。 |
| `apps/desktop/src/features/coding/components/ThreadHeader.vue` | 修改 | 显示新增运行状态。 |
| `apps/desktop/src/features/coding/components/WorktreePanel.vue` | 新增 | 显式创建和受保护清理独立工作区。 |
| `apps/desktop/src/features/coding/model/runContracts.ts` | 修改 | 恢复契约及排队、暂停、中断类型。 |
| `apps/desktop/src/features/coding/model/runOutcome.ts` | 修改 | 区分过程状态和完成结果。 |
| `apps/desktop/src/features/coding/model/runProjector.spec.ts` | 修改 | 验证控制事件和旧帧收敛。 |
| `apps/desktop/src/features/coding/model/runProjector.ts` | 修改 | 投影排队、暂停、继续和中断事件。 |
| `apps/exec-host/src/main.rs` | 修改 | 独立 AppContainer 身份、真实 PTY 能力和退出排空。 |
| `apps/exec-host/src/sandbox.rs` | 修改 | 原生隔离启动和 ConPTY 管道、句柄及探针修复。 |
| `docs/analysis/coding-agent-upgrade-20260908/README.md` | 修改 | 同步当前能力与 M1/M2、S6 入口结论。 |
| `docs/analysis/coding-agent-upgrade-20260908/s5-blockers-validation-report.md` | 新增 | 保留前轮阻断修复事实并链接最终证据。 |
| `docs/analysis/coding-agent-upgrade-20260908/s5-recovery-steering-and-review.md` | 修改 | 记录 S5 实现边界与最终退出状态。 |
| `docs/analysis/coding-agent-upgrade-20260908/s5-remaining-gates-handoff-prompt.md` | 新增 | 保留用户指定的剩余门禁交接快照。 |
| `docs/analysis/coding-agent-upgrade-20260908/s5-remaining-gates-validation-report.md` | 新增 | 记录修复、分层门禁、失败证据、最终验证和清理。 |
| `docs/analysis/coding-agent-upgrade-20260908/s5-validation-report.md` | 新增 | 保留首次 S5 开发和兼容验证记录。 |
| `docs/unified-desktop-runtime.md` | 修改 | 同步 schema 7、恢复和最终已验证能力。 |
| `scripts/build-remote-client.cjs` | 修改 | 隔离 QA 安装身份和冻结源码摘要。 |
| `scripts/build-remote-client.test.cjs` | 修改 | 验证 QA 不配置正式更新通道。 |
| `scripts/run_coding_validation.py` | 修改 | 增加恢复、沙箱、历史专项并去重完整套件。 |
| `scripts/s5_acceptance_model.py` | 新增 | 无密钥回环模型及有界延迟、响应尝试元数据。 |
| `scripts/verify-unified-client.py` | 修改 | 冻结运行、沙箱内测试配置与最终契约断言。 |
| `src/private_agent_core/execution/contracts.py` | 修改 | 独立沙箱身份协议及本机私有接收时间。 |
| `src/private_agent_core/execution/exec_host_client.py` | 修改 | 暴露宿主存活 PID 并记录接收帧时间。 |
| `src/private_agent_local/app.py` | 修改 | 公开恢复、控制、审查和 worktree 能力及接口。 |
| `src/private_agent_local/completion.py` | 修改 | 关联任务证据复核与恢复后的目标验证。 |
| `src/private_agent_local/context_manager.py` | 修改 | 跨关联继续保留累计预算及用户约束。 |
| `src/private_agent_local/core_adapter.py` | 修改 | 在模型、工具和压缩边界应用控制代次。 |
| `src/private_agent_local/execution_sessions.py` | 修改 | 执行身份核对、控制竞态、独立沙箱和输出计时引用。 |
| `src/private_agent_local/execution_tools.py` | 修改 | 命令授权、代次保护和候选变化归属。 |
| `src/private_agent_local/executor.py` | 修改 | 命令接入原生租约及失败清理。 |
| `src/private_agent_local/files.py` | 修改 | 准备 AppContainer 所需的受控系统目录环境。 |
| `src/private_agent_local/migration.py` | 修改 | 允许 schema 4–7 基础历史投影并拒绝未来版本。 |
| `src/private_agent_local/policy.py` | 修改 | 受限 PowerShell 工作目录与文件系统边界。 |
| `src/private_agent_local/recovery.py` | 新增 | 检查点、恢复兼容、预算归属和副作用核对。 |
| `src/private_agent_local/run_controls.py` | 新增 | 持久化幂等控制和安全边界应用。 |
| `src/private_agent_local/run_review.py` | 新增 | 已有、任务及外部变化的有界归属审查。 |
| `src/private_agent_local/runtime.py` | 修改 | 接入控制、恢复、租约及统一收束。 |
| `src/private_agent_local/store.py` | 修改 | schema 7 迁移、所有权锁和事务检查点。 |
| `src/private_agent_local/windows_process.py` | 修改 | 由系统 API 获取沙箱启动目录。 |
| `src/private_agent_local/windows_sandbox.py` | 新增 | 独立 SID 授权、路径检查、清理日志与恢复。 |
| `src/private_agent_local/workspaces.py` | 新增 | 真实仓库锁、并发配额及显式 worktree 管理。 |
| `tests/coding_acceptance/recovery_process.py` | 新增 | 真实子进程退出与落盘边界故障夹具。 |
| `tests/coding_acceptance/test_baseline.py` | 修改 | 核对当前恢复与 worktree 能力。 |
| `tests/coding_acceptance/test_host_duration.py` | 修改 | 实际旧 API 命令跨过 120 秒并正常退出。 |
| `tests/coding_acceptance/test_host_probes.py` | 修改 | 原生隔离对照和真实 PTY 输入、输出、取消。 |
| `tests/coding_acceptance/test_s4_duration.py` | 修改 | 修复 600 秒专项夹具及游标推进，验证无重复。 |
| `tests/unit/test_local_context_history.py` | 修改 | 适配 schema 7 的旧上下文迁移夹具。 |
| `tests/unit/test_local_exec_host.py` | 修改 | 核对原生隔离、真实启动后取消和兼容错误路径。 |
| `tests/unit/test_local_execution_sessions.py` | 修改 | 真实沙箱会话、输出计时和迟到身份/序号注入。 |
| `tests/unit/test_local_history.py` | 修改 | 覆盖 schema 4–7 只读导出及未来版本拒绝。 |
| `tests/unit/test_local_patchsets.py` | 修改 | 所有权锁与旧补丁 schema 迁移回归。 |
| `tests/unit/test_local_permissions.py` | 修改 | 核对权限适配器将受限租约传至命令执行。 |
| `tests/unit/test_local_recovery.py` | 新增 | S5 状态、崩溃、控制、预算、账号与 worktree 矩阵。 |
| `tests/unit/test_local_store.py` | 修改 | 适配 schema 7 的旧存储迁移夹具。 |
| `tests/unit/test_windows_sandbox.py` | 新增 | 真实 AppContainer 正反对照、链接及租约清理。 |
