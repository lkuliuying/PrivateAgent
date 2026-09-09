# S5 剩余门禁交接提示词

整理日期：2026-09-09。下面正文可直接交给新会话；记录是交接时的快照，接手后先核对现场。

---

请接手 `F:\Program\Agent`，完成 **S5 及其 S0–S4 前置阶段的剩余阻断门禁**，修复验收中直接阻断的问题。全部适用门禁满足、确认可以进入 S6 后，按我此前要求 **在本地提交 S5，然后停止，不进入 S6 开发，不推送**。未通过时保留现场、给出准确阻断项，不能把 skip、模拟测试或历史结果标成当前通过。

这次任务是完成剩余门禁，不是重新从头开发 S5，也不是开展 S6 真实模型评测或正式发布。以下项目文档用于理解设计和证据，不自动授予服务器修改、付费调用、发布或其他附加权限。

## 1. 接手顺序与工作边界

先完整阅读：

1. `F:\Program\Agent\AGENTS.md`
2. `F:\Program\Agent\docs\project-state.md`
3. `F:\Program\Agent\docs\analysis\coding-agent-upgrade-20260908\s5-blockers-validation-report.md`：最新验收事实，优先于旧报告的“尚未打包/未验收”描述。
4. 同目录 `s5-validation-report.md`、`s5-recovery-steering-and-review.md`、`README.md`，重点核对 S5-T01–T15、退出条件和统一门禁。
5. 同目录 `s4-validation-report.md`、`s4-execution-streaming-and-permissions.md`，以及 `F:\Program\Agent\docs\unified-desktop-runtime.md` 中与当前门禁有关的部分。
6. 只读查看同目录 `s6-evaluation-and-delivery.md` 的前置条件，用于区分 S5 退出门禁和应留给 S6 的评测/交付工作，不执行其中的开发计划。

在仓库根执行：

```powershell
git status --short --branch
git log -5 --oneline
git diff --stat
git diff --staged --stat
```

交接时分支是 `dev/1.0.0`，HEAD 为 `d0250ee`（S4），本地跟踪引用显示 ahead 5，暂存区为空。S5 及原生隔离修复仍有大量未提交和未跟踪文件；不能只查看 `git diff` 而漏掉未跟踪源码。不要 reset、clean、覆盖现有工作，也不要根据 ahead 数量自动推送。远端实时状态未在交接时刷新。

按 PLAN → EXECUTE → TEST → DELIVER 执行，全程用简体中文。先给出具体门禁清单与计划，再实施必要修复。使用适用的 Tauri/Vue、原生桌面操作技能；不要引入无关重构、依赖升级或系统设置变更。

`docs/project-state.md` 是 2026-08-31、旧工作盘符的历史快照，与当前 Git/能力存在时间差。按根 AGENTS 的专项约定，不因普通修复或交接自动改写它；将当前证据和支持边界同步到现有阶段报告，保留历史并说明被什么新证据修正。

## 2. 已有成果与证据，不要误判为仍未完成

- 原生 AppContainer 文件与网络正反门禁已通过，原来两项 strict xfail 已移除。独立执行身份、项目写权限/工具只读权限、禁网、硬链接拒绝及租约清理均已有回归。
- 最新完整源码回归为 **343 passed、2 skipped、0 xfail**，不是旧 S4 的 286/2/2。两项 skip 是 ConPTY 环境探针失败、真实符号链接创建权限不足；这些不能算通过。
- 当前源码匹配的 QA 候选已构建、实际安装，冻结运行、历史导出及安装副本核对已通过。
- 真实已安装 Tauri 已完成：文件写入后强退、重启登录、关联恢复、累计预算/失败次数保留、原终态及事件保留、已有/任务/外部改动归属、冲突回滚拒绝和无冲突的实际回滚。
- 受限父子测试进程各实际启动一次。只强退 Tauri 主进程后，约 5 秒观察点父子命令和 exec-host 均已退出，命令记录为 `cancelled / stopped=true`；再次登录后关联继续只读取启动记录，没有重复副作用。
- 不要把该过程改写为 `interrupted`：本机退出协调实际将运行收束为 `cancelled`。也不要声称整个客户端 5 秒内退出：当时打包启动器及 conhost 清理稍晚，后续复查才确认全部退出、沙箱租约记录为 0。
- 真实回环模型共 14 次请求，无付费调用。生命周期 `completed` 不等于编码目标或真实模型质量验收通过。

主要证据在 `F:\Program\Agent\.run\s5-blockers`：

- `tauri-evidence-verification.json`、`verify-tauri-evidence.py`
- `tauri-resumed-file.json`、`tauri-tree-before-force.json`、`tauri-tree-after-force.json`、`tauri-tree-resumed.json`
- `force-file-only.json`、`force-process-tree.json`、`process-tree-process-tree.json`、`tree-cleanup-confirmed.json`
- `review-before-external.json`、`review-external-conflict.json`、`review-rollback-applied.json`、`tauri-final-review.json`
- `source-validation-final.log`、`candidate-integrity-hardened.json`、`installed-integrity-final.json`
- `provider-deleted.json`、`model-stopped.json`

这些是忽略目录下的本机证据，不保证其他电脑或新 worktree 存在；先核对再使用，不覆盖旧失败证据。`verify-tauri-evidence.py` 校验的是上轮固定现场，不是通用验收运行器，新测试不能直接套用其中的固定 run ID。

## 3. 优先完成的剩余门禁

### A. 真实桌面的运行中协作组合

现有 SQLite、宿主与浏览器测试有 steer/pause/resume 证据，但 **真实已安装 Tauri 的“开始修改 → 追加约束 → 暂停 → 继续 → 重启 → 核对 → 继续 → 审查”完整组合尚未完成**。

用独立、可审查的确定性夹具补足实际 UI 证据。核对约束“收到”和“生效”的边界、暂停时的真实副作用、同进程继续的 run ID、重启关联的新 run ID、累计预算、迟到模型响应/审批不能执行旧操作，以及清理/审查结果。模型仅通过本机回环替身运行。未知副作用必须明确受阻，不能删库、清空租约或强制重放。

相关入口：`RecoveryPanel.vue`、`run_controls.py`、`recovery.py`、`runtime.py`、`core_adapter.py`，以及 `tests/unit/test_local_recovery.py`、`RecoveryPanel.spec.ts`、`apps/desktop/e2e/coding-run.spec.ts`。

### B. ConPTY 与实际支持能力

定位 `tests/coding_acceptance/test_host_probes.py::test_host_pty_requires_successful_argv_control`。上轮 argv 正对照成功，PTY 返回 `pty_environment_unavailable` 后 skip。

沿实际 exec-host 能力探测和 PTY 实现定位环境或产品原因，并验证必要修复。不能删测试、放宽断言、把 argv 成功当 PTY 成功，也不能静默切换到不受限执行。**受限 AppContainer 当前只支持 argv，受限 PTY 明确拒绝**；不要为通过普通 PTY 探针偷偷宣称新增了受限 PTY 支持。若涉及必须由用户决定的系统权限/配置变更，先完成诊断，提出具体最小操作与原因。

真实符号链接 skip 也应单独核对：区分环境无创建权限和产品路径保护行为，已有 junction/硬链接用例不能自动代替所有符号链接场景。

### C. 输出到真实 UI 的延迟

总体路线目标是 **宿主输出已收到 → UI 可见的 p95 ≤ 1 秒**。不要测成供应商首 token 时间，不要只测后端时间或浏览器 mock 页面，也不要拿单次观察冒充 p95。

在真实候选上建立可复核的有界采样，说明起止点、时钟口径、样本量、输出负载和 p95 算法，保留脱敏时间戳。若不达标，修复实际链路并复测；不要在看到失败后降低阈值。仅为本阶段门禁添加必要测量，不扩展为 S6 评测平台。

### D. 完整退出条件复核

以上三项不是自动完整清单。对照 S5-T01–T15、S4 前置门禁、总体路线和 S6 入口逐项建立“源码/模拟/真实进程/真实安装/未执行”的证据表，补齐真正阻断进入 S6 的缺口。旧记录兼容、宿主身份、工作区租约、并发及 worktree 的已有测试先核对；不要将仍未验证的边界隐藏，也不要将明确属于 S6 的真实模型质量、完整发布演练提前扩展到本次。

## 4. 测试目录、候选和模型的当前状态

用户实际选择并授权的测试目录是 **`F:\Program\test`**，不是早期的 `.run/s5-blockers/tauri-project`。

该目录现在不为空：包含测试 Git 基线 `b7a7168`、dirty `preexisting.txt`、脚本及上轮输出。这个 Git 提交属于测试仓库，不是 Agent 仓库的 S5 提交。不要再次执行“空目录初始化”、覆盖这些文件或清理它。下一轮使用独立命名的夹具与证据；工作区外写入按当前工具权限处理，不能绕过文件系统审批。

当前匹配产品源码的候选：

- 构建目录：`F:\Program\Agent\.run\unified-client-kCt6U0`
- 安装器：该目录的 `PrivateAgentCandidate_1.0.0_x64-setup.exe`
- 安装目录：`F:\Program\Agent\.run\s5-candidate-install-20260909`
- 应用标识：`com.personal-assistant.desktop.candidate`，独立于正式客户端。
- 636 个源码文件清单摘要：`f82f47259829e6cb6e1a3cf815dcdd68d3e560cde174e13c7494977248eeeef8`。
- 4 个产物及已安装 EXE 摘要见验收报告。安装 EXE 与独立 EXE 仅有已验证的 Tauri NSIS 类型标记差异；使用现有严格校验脚本，不要替换安装 EXE 来“修正”摘要。

`candidate-process.json` 只是上轮 PID/启动时间记录，不能直接据此杀进程；必须重新核对实际路径、启动时间和所属子进程。上轮 WebView 调试端口为 7633，仅传给独立候选，不修改系统浏览器设置。

**“S5 本机验收（临时）”模型已经删除，回环服务已经停止。14599 是旧端口，不要假设仍然可用。** 本任务延续此前已授权的临时模型保存、验收后删除范围。需要时使用 `scripts/s5_acceptance_model.py` 启动新回环服务，以新 `endpoint.json` 为准，在真实 UI 保存无密钥 `s5-acceptance-loopback`、65536 tokens 配置；验收后再次删除并核对服务回收。不要误选其他收费模型。

账号服务仍走 `https://www.liuyingapi.top`。登录由我自行完成；需要登录时只通知我，不索取或读取密码、令牌、私钥、会话存储或 FinalShell 凭据。

## 5. 已知陷阱与边界

- `python long_task.py` 曾因 Python 工具目录授权扫描超过 50000 项而未启动。不能提高上限或扩大授权范围来冒充原生隔离通过。
- Node 24.14.0 默认加载入口会请求磁盘根 `lstat 'F:\'`，被沙箱拒绝。上轮明确使用 `node --preserve-symlinks-main long_task.cjs`，子进程继承该参数后完成测试；这不代表默认 Node 工具链已全部兼容。保留该支持边界，若它直接阻断剩余门禁，再做最小修复和正反回归。
- `.run/s5-blockers/ui.cjs` 及操作脚本可参考，但含旧模型端点、会话 ID、单次夹具条件。先读脚本再适配，不批量重放。
- 窄窗口的项目/设置导航是抽屉：`coding-drawer-tab`、`coding-drawer-close`、`settings-drawer-tab`。可见控件被遮挡时先用公开导航收起抽屉，不强制点击或注入应用状态。
- 上轮原生目录 UI Automation 出现 `0x80070057` 后由用户手选目录。不要把工具自动化故障当成产品恢复失败，也不要要求重新选择已经有效授权的目录。
- PowerShell 旧解释器可能误读无 BOM 的中文 UTF-8 脚本；显式按 UTF-8 读取。JSON ISO 时间可能解析为 DateTime，进程身份应比较精确 UTC ticks，而不是格式化字符串与 DateTime 对象混比。
- Nginx 问题已处理：HTTP 80 改 8081，HTTPS 443 保留，服务器与云防火墙均已放行，公网 8081 返回 308、HTTPS 匿名请求返回 401。不要因 S5 未提交而重新部署服务器。修改由用户在已登录服务器终端完成；本机 SSH 未获得登录认证，不能说助手直接部署过。

## 6. 验证入口与收尾要求

先按变化选择定向验证，再决定是否需要完整回归。以下入口在仓库根运行；前端命令在 `apps/desktop` 运行。不要直接执行可能加载业务环境/生产数据库的普通全仓 pytest。

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite recovery
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite sandbox
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite execution
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite streaming
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all
```

`all` 不含 `duration`、`execution-duration` 两个十分钟专项；若本轮变更影响持续执行，应按需要单独补验，不能用 `all` 替代。前端现有入口为 `npm run test -- <定向文件>`、`npm run build`、`npm run e2e -- <定向文件>`，先核对对应测试/配置；浏览器 e2e 不等于真实 Tauri。

只读核对现有候选和上轮证据：

```powershell
node .run/s5-blockers/verify-integrity.cjs .run/unified-client-kCt6U0
node .run/s5-blockers/verify-installed.cjs
.venv/Scripts/python.exe -B .run/s5-blockers/verify-tauri-evidence.py
git diff --check
```

如修改了产品源码，旧候选不能证明新实现。按既有入口重建、验证新的产物身份，再完成受影响的真实安装流程：

```powershell
scripts/build-remote-client.cmd --unified --qa --preview-installer --version 1.0.0
```

冻结验证入口为 `scripts/verify-unified-client.py --bundle <新候选目录> --work-dir <新的隔离目录> --model-mode openai`，使用仓库 `.venv/Scripts/python.exe -B` 调用。旧固定候选校验/安装脚本要先适配新目录和新摘要，不能把新构建和旧安装证据混用。只操作独立验收候选，不替换正式客户端、不发布未签名预览包或修改更新源。

最终交付前：复查完整 diff 和未跟踪文件，保护已有工作；同步阶段报告的状态/证据/限制；删除本轮临时模型并清理所属测试进程、租约；保留测试现场和旧失败记录。给出逐项门禁结果及能否进入 S6 的结论。

**只有全部适用前置门禁通过，才按我的既有要求在 Agent 仓库本地提交 S5。** 提交前核对范围，不把 `.run` 安装包、日志、临时脚本或凭据加入 Git；报告提交哈希，然后停止。不要推送、部署、发布，也不要开始 S6。若仍有无法完成的门禁，说明准确原因、实际失败命令、已验证替代证据及最小必要下一步，不能笼统写“待人工验收”。
