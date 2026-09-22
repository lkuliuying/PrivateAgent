# S6 冻结候选原生任务创建失败修复

日期：2026-09-15（Asia/Shanghai）。工作区 `F:\Program\Agent`，HEAD `1dde393e29f3dbacd3647d11834b39824ac8323f`；保留开工前所有未提交修改。证据根目录为 `.run/s6-native-fix/`，原冻结候选及失败材料仍在 `.run/s6-final-f146e704/`。

## 1. 范围与当前结论

本轮仅修复本机创建链路并执行隔离验证、独立构建。B 沿用个人学习范围，公开 PY01 的 C 联调通过仍属于原冻结候选的历史证据；本轮不重复云调用，不开展正式质量实验、完整性能验收或 E～F。

已复现环境准备错误及其导致的创建接口 422，并完成最小源码修复。定向测试、完整隔离回归、独立构建、打包 IPC 和前端检查均已通过。**修复候选的真实原生窗口成功创建 run，经两次审批修改 `sample.py`，执行 `python verify.py` 返回退出码 0 并查看输出。** 随后的完成判定未通过，已通过原生界面取消；整条任务没有取得 completed/verified 终态，候选仍未验收，尚不具备推进 E 的条件。

## 2. 证据与根因

### 原证据重新核对

`baseline.py` 核对了 1282 个工作区文件摘要、414 个产品构建输入及原报告绑定的 56 份证据，另记录 `final-evidence.json` 自身摘要。原源码集合与冻结清单一致，暂存区为空。没有把历史测试成绩列为本轮成绩。

重新查看两张失败截图，并用 SQLite 只读连接查询原测试项目的白名单字段：项目 3、工作区 4、会话 5 绑定正确，项目已授权且状态 active；run 和持续执行记录均为 0。原生隔离目录的显式 `roaming/`、`local/` 存在，`profile/AppData/Local` 存在，`profile/AppData/Roaming` 不存在。结果见 `old-native-inspection.json`，未读取会话令牌、系统凭据或原始请求正文。

### 实际调用链

1. `CodingThreadWorkspace.vue` 的 `send()` 提交项目、工作区、会话、权限和模型选择，并按能力声明 S4/S5 协议。
2. `features/coding/api/runs.ts` 经 `codingHttp.ts → api/http.ts → localExecutor.ts` 路由到 `/agent-runs`，本机入口补充完成契约 1.0。
3. `privateTransport.ts` 生成请求 ID；Tauri `local_executor_request` 将请求写入私有 stdio，`ipc.request_scope()` 复用受保护的 ASGI 路由。
4. `app.create_run()` 对非只读 S4 请求先调用 `execution_sessions.capabilities()`。
5. 能力探测在启动宿主前调用 `files.prepare_process()`。旧代码即使已经具有完整的 `USERPROFILE`、`APPDATA`、`LOCALAPPDATA`，仍无条件调用 `windows_process.profile_environment()`。
6. Windows `SHGetFolderPathW` 查询默认目录失败，抛出 `ValueError("无法定位系统应用数据目录，不能启动受限进程")`。能力探测据此返回 `execution=false`；创建接口在进入 `Runtime.create()` 前返回 422，正文为“执行宿主缺少 S4 持续执行能力，请升级完整客户端；仍可创建只读任务”。

原响应没有 `error_code`；前端归为 unknown 并显示通用创建失败提示。**实际失败点是宿主启动前的环境准备，不是根据提示文字推断出的宿主版本错误。** 本轮未修改提示文案。

### 可重复对照

`differential-682c669e/result.json` 对同一冻结执行器分别改变环境条件，全部使用新目录、合成账号和回环替身，生成调用均为 0：

| 条件 | 能力探测 | 创建结果 | 独立宿主握手 |
| --- | --- | --- | --- |
| 原 IPC 对照环境 | 可执行 | 创建并取消 | 成功 |
| 仅移除测试额外注入的 Python PATH | 可执行 | 创建并取消 | 成功 |
| 仅将工作目录改为数据目录 | 可执行 | 创建并取消 | 成功 |
| 改为原生隔离启动器的分离目录布局 | 不可执行 | 422 | 成功 |
| 合并上述原生启动条件 | 不可执行 | 422 | 成功 |
| 上述条件加 `inference_mode=auto`、经 API 保存本机 Ollama 配置 | 不可执行 | 422 | 成功 |

代表性拒绝请求 ID 为 `b2b56ec5cbdb4678855972a2f22056e3`（目录布局）和 `21b0a5a6c3fc45879d7bd99fb7fd958d`（本机模型目录）。失败没有 run/operation ID，因为没有到达运行创建及工具执行。

`profile-64a91a5b/result.json` 在真实新 Python 进程中取得 `SHGetFolderPathW` 返回值 `0x80070003`，并复现相同的环境准备异常。该诊断使用新建的完整显式环境和缺少默认 AppData 子目录的布局；没有改动原失败目录。单变量对照、原目录事实及真实异常调用栈共同指向上述根因；没有读取原服务进程内存。

最初探索记录 `diagnose-8f46ddcc/result.json` 保留：其两个模型目录用例误用了 `chat_completions` 配合 Ollama，在模型配置接口先返回 422。后续使用契约要求的 `ollama_chat` 重新建立独立对照，仍复现创建失败。这个诊断脚本错误与产品根因分别记录。

## 3. 最小修复与测试

`src/private_agent_local/files.py` 仅调整 Windows 环境回填：完整非空目录环境直接保留；缺失或空值才查询系统目录，并只回填缺项。查询失败仍抛错，环境白名单、宿主摘要校验、AppContainer、禁网、审批及禁止副作用重放的逻辑不变。

`tests/unit/test_local_executor.py` 新增真实子进程目录复现、三个目录缺失/空值回填、系统查询失败、非法命令参数，以及真实宿主能力下的创建、错误身份、错误工作区、空消息、重复请求、活动运行冲突、取消与显式重试断言。项目和运行通过产品接口建立；未通过直接写数据库制造通过。

先新增复现测试再修改产品代码：

| 实际命令（仓库根目录） | 观察结果 | 证据 |
| --- | --- | --- |
| `.venv/Scripts/python.exe -B .run/s6-native-fix/baseline.py` | 通过，原证据与源码绑定一致 | `baseline.json` |
| `.venv/Scripts/python.exe -B .run/s6-native-fix/diagnose.py` | 完成初次对照；存在上述诊断配置错误 | `diagnose-8f46ddcc/result.json` |
| `.venv/Scripts/python.exe -B .run/s6-native-fix/diagnose_v2.py` | 六种条件完成；原生布局稳定拒绝 | `differential-682c669e/result.json` |
| `.venv/Scripts/python.exe -B .run/s6-native-fix/profile_probe.py` | 真实系统 API 与旧环境准备异常复现 | `profile-64a91a5b/result.json` |
| `.venv/Scripts/python.exe -B .run/s6-native-fix/inspect_old_native.py` | 原绑定、授权、零运行与目录布局核对通过 | `old-native-inspection.json` |
| `.venv/Scripts/python.exe -B .run/s6-native-fix/run_checks.py`，修复前 | **39 passed / 4 failed**；真实目录失败及三个空值失败 | `.run/coding-agent-validation/native-create-085ba75b8a18447bb34964ccabc953fc` |
| 同一命令，修复后 | **44 passed，9.07 秒**；含额外创建/取消/拒绝回归 | `.run/coding-agent-validation/native-create-13ffcf427d7945ffb5cc88369fd4c4b5` |
| `.venv/Scripts/python.exe -B -m ruff check src/private_agent_local/files.py tests/unit/test_local_executor.py` | 通过 | 本轮命令输出 |
| `git diff --check` | 通过；交付前再次核对 | 本轮命令输出 |

IPC 与 AppContainer 测试使用经工具审批的普通本机权限，保留原有隔离入口、测试断言及超时。完整 `all` 回归结果为 **937 passed、1 skipped，800.54 秒，退出 0**；唯一跳过为 `test_local_file_ranges.py:71` 的 Windows 真符号链接权限不足。证据为 `.run/coding-agent-validation/all-b9aadd69d29940759e02dbd65f3f4b18/`，实际命令为：

```powershell
$nativeFixPathBefore = $env:PATH
try {
    $env:PATH = 'C:/ProgramSoftware/nodejs;' + $nativeFixPathBefore
    .venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all
    $nativeFixExit = $LASTEXITCODE
} finally {
    $env:PATH = $nativeFixPathBefore
}
exit $nativeFixExit
```

源码回归默认宿主 SHA256 为 `91eb573430edf660bdc247a3e1cae918bb2d153e795a07061a691f7f48e65f7a`，与冻结宿主不同。因此该回归与随后新候选的打包/原生检查分别记账，不能把默认宿主成绩移植给候选。

### 修复候选及前端的本轮验证

以下命令按顺序执行；没有同时运行完整回归、构建和长时测试，没有扩大超时或调整有效断言。

| 实际命令 | 观察结果 | 证据（相对 `.run/s6-native-fix/`） |
| --- | --- | --- |
| `.venv/Scripts/python.exe -B .run/s6-native-fix/build_candidate.py` | 退出 0；使用现有 PyInstaller 重建 sidecar，配套文件摘要一致 | `build-invocation.json`、`build-sidecar.log`、`candidate-identity.json` |
| `.venv/Scripts/python.exe -B .run/s6-native-fix/verify_environment.py` | 六种环境均有执行能力，均创建并取消；模型生成调用 0 | `differential-3f28dbd0/result.json` |
| `.venv/Scripts/python.exe -B .run/s6-native-fix/desktop_checks.py` | 下列三个前端检查退出 0 | `*-invocation.json`、对应日志和结果 JSON |
| `C:/ProgramSoftware/nodejs/node.exe node_modules/vitest/vitest.mjs run src/features/coding src/services/localExecutor.spec.ts src/services/privateTransport.spec.ts src/api/http.spec.ts --config F:/Program/Agent/.run/s6-native-fix/vitest.config.ts`，工作目录 `apps/desktop` | 36 个文件、231 项测试通过 | `vitest-result.json`、`vitest.log` |
| `C:/ProgramSoftware/nodejs/node.exe node_modules/vue-tsc/bin/vue-tsc.js --noEmit`，工作目录 `apps/desktop` | 类型检查通过 | `typecheck.log` |
| `C:/ProgramSoftware/nodejs/node.exe node_modules/@playwright/test/cli.js test coding-run.spec.ts --config F:/Program/Agent/.run/s6-native-fix/playwright.config.ts`，工作目录 `apps/desktop` | 7 项 Chromium 用例首跑通过，15.0 秒 | `playwright-result.json`、`browser.log` |
| `.venv/Scripts/python.exe -B scripts/verify-unified-client.py --bundle .run/s6-native-fix/candidate --work-dir .run/s6-native-fix/packaged --model-mode ollama` | 退出 0；打包 sidecar 和候选宿主完成文件写入、pytest、PowerShell、逐次审批、授权正反例及宿主摘要篡改拒绝，最后撤销临时授权并退出 | `packaged/packaged-runtime-8b5bfd5bdd894ed598d12438022d67ec/verification.json` |

前端检查禁用环境文件，使用已有 Node、浏览器和完整路由 fixture。打包检查使用全新数据及合成身份，不连接真实服务或模型。六变量复验中的代表性原生布局请求 `c3575bb3a5354945a0cd38d60b1d8d78` 创建 run `698a9402-3339-4fd0-990a-1b3d804c427c`；本机模型目录请求 `3842e21c605943b28185b2137d648b97` 创建 run `12013faa-7646-42a6-b7f9-2aa18138529d`。这些 IPC ID 与原生 UI 证据分别保留。

## 4. 候选身份及证据适用性

原候选状态保持 `frozen_not_accepted`，冻结清单 SHA256 为 `f4bf402afcffbbb66f5abcb5ef214a386e11c25c8f8d51991cf69a92ca417934`。

| 对象 | 原冻结候选 SHA256 | 本轮修复候选 SHA256 |
| --- | --- | --- |
| 产品源码集合 | `49ea144c81522c10e3098e4f75cf18e68fc4d88fe9b36023c5e722299cda01f7` | `dd4f72188ef83d5590c8a2603e91a9973534bad4a9c453b178f941059d98c76f` |
| 桌面 | `e7098d2017f6968e393cde62c1db306d89307e2aa18e675f6ff3890e613492df` | 相同，复用 |
| sidecar | `a03f1e97b990230f34269013e0ec68ce9d3eefc18ca3fa52b3fdc67fe5332ca6` | `150972e96bd6bb21015eb896bafa56ea072b4c21d47d388b050803a471b4942c` |
| exec-host | `dec3cb3cf81122454552f674231a9f1da83eb8fa6c13ddde820d262efe10cf94` | 相同，复用 |

修复候选位于 `.run/s6-native-fix/candidate/`，状态为 `native_run_creation_fix_not_accepted`。414 项产品输入中只有 `files.py` 改变；在独立输出、缓存和工作目录重建 sidecar，未重新编译来源未变的桌面与 exec-host。构建前后及复用时核对源码清单和配套摘要。`candidate-identity.json` 另记录 `exec-host.sha256`、`build-info.json`、`source-manifest.json` 的文件摘要。它是 1.0.0 便携未签名本地验证候选，没有替换原冻结清单或正式安装。

原 B 学习结论和 C 的公开单题通过保留历史含义。`files.py` 影响 C 使用的本机执行准备，因此不能把原 C 的二进制绑定改成新候选；本轮按用户要求不重复真实模型调用。旧宿主长时证据只适用于相同宿主组件，首次取消失败及其原因未确认的限制仍保留；不由本次创建修复宣布解决。

## 5. 原生窗口与剩余条件

### 实际操作与产物身份

运行 `.venv/Scripts/python.exe -B .run/s6-native-fix/native_session.py`，在新目录 `native-b89dc948/` 建立独立 profile、WebView 数据、回环替身及三个测试文件，未读取或复制旧登录配置。用户在可见窗口完成登录、测试项目授权和目录选择；自动化曾遇到最小化/用户输入保护，用户恢复窗口后继续。本轮自动化确实操作了原生 Tauri 窗口，没有用浏览器 fixture 或直接 IPC 代替提交与审批。

桌面 PID `34016`、sidecar PID `47312/50884` 的实际路径位于新 `candidate/`，路径文件摘要与第 4 节一致。持续执行记录保存的宿主摘要为 `dec3cb3cf81122454552f674231a9f1da83eb8fa6c13ddde820d262efe10cf94`。依据是进程路径、磁盘摘要及业务记录，没有检查进程内存；`launch.json` 中 `loaded_component_attestation=unknown` 保留原含义。

测试项目根目录为 `F:\Program\Agent\.run\s6-native-fix\native-b89dc948\project`，项目/工作区/会话 ID 为 `3/4/5`。模型通过新原生配置页选用 `S6 本机替身 / s6-fixture`，协议 Ollama，端点 `http://127.0.0.1:8512`。模型元数据和生成均来自本机固定替身，7 次合成生成调用、fixture 错误 0、真实供应商生成调用 0；不构成模型质量证据。

| 原生步骤 | 实际观察 | 证据（相对 `native-b89dc948/`） |
| --- | --- | --- |
| 选择测试项目和模型并提交 | 创建 run `9d9b047d-83c5-4818-872a-766826f0b24f`，进入补丁审批 | `model-configured.jpg`、`task-before-submit.jpg`、`run-created-awaiting-patch.jpg`、`run-created-visible.txt` |
| 展开补丁并批准 | 只有 `sample.py` 的 `return value` 改为 `return value * 2`；补丁状态 applied | `patch-preview.jpg`、最终只读回执 |
| 批准命令 | 原生审批 `python verify.py`；`restricted / network_policy=none / retention=run / timeout_ms=60000` | `command-approval.jpg` |
| 执行并查看结果 | execution `79c89fda-d190-4a3d-a778-2e6de7ac83e9`，operation `99c30b3e-3ab3-4dff-b60e-50486016a0ee`；退出码 0，输出 `NATIVE_FIX_VERIFIED` | `verification-output.jpg`、`verification-output-visible.txt`、`native-final-receipt-1789486133425.json` |
| 完成判定 | 显示“缺少实际文件变化证据：verify.py；命令已退出，但其业务含义无法自动判定”，进入重试 | `completion-check-retry.jpg`、`completion-check-visible.txt` |
| 取消后续审批 | 原生点击取消；`local_tool_rejected`，待处理审批失效，run 终态 cancelled，本机进程 0 个运行中 | `cancelled-no-active-process.jpg`、`cancelled-visible.txt`、最终只读回执 |

三个版本契约字段均为 `1.0`，权限为 `confirm`，明确模型 ID 持久化。原生入站 IPC 请求 ID 未另外持久化，run 的 `client_request_id` 为 null；此处保留实际 run/execution/operation ID，不补造请求关联。私有 IPC 对照的请求 ID 见第 2～3 节。

### 下游未通过的原因与适用限制

原生输入明确要求“仅修改 sample.py……随后执行 python verify.py……不要修改其他文件”。源码 `src/private_agent_core/completion.py:72` 在检测到修改动词后，把整段文本匹配的所有文件都转成 `file_changed` 要求，因此错误地增加 `verify.py`。`src/private_agent_local/completion.py:251` 据实际补丁证据拒绝该要求。这是本轮新发现的完成要求提取问题，未扩大本次创建修复去修改它，也没有修改验证脚本来迎合错误要求。

同时，`command_kind()` 按既有保守契约将普通 `python verify.py` 归为 `unclassified`，所以退出码 0 的业务结论仍为 `unknown`。人工核对预置脚本包含正数、零、负数三条断言，且实际输出标记已出现；这证明该脚本执行成功，不等于运行的完成契约自动验证通过。输出还保留 `warning: Failed to set cwd to temp dir`，其具体来源未进一步诊断。

固定替身队列中为后续取消用例准备的 `python wait.py` 被完成判定重试提前消费，形成第三次审批；未批准，随后在原生界面取消。数据库只有一个 managed execution 和一组 applied 补丁；`verify.py`、`wait.py` 与启动器预置字节摘要相同。等待命令没有启动，没有为通过验收而代跑或补写文件。

原生提交执行期间发送控件不可重复发送，最终只有 1 个 run；未另做原生快速双击/断线重试实验。后端定向测试覆盖同一请求并发提交、取消后同 ID 返回原运行、显式新 ID 重试及错误授权，原生实测覆盖等待审批时取消及审批失效。尚未复验原生运行中取消、异常重启恢复、纠错/审查及完整性能；原长时宿主首次取消失败的根因仍未确认。性能样本没有在本轮补采，不能从一次原生命令计算验收指标。

### 清理与取证失败保留

原生启动器达到既有 30 分钟期限后退出 0，关闭其 Job 内桌面、sidecar、WebView 和回环服务。最终回执按此前记录的 PID 加创建时间核对 11 个进程身份均已消失，启动器 PID 不存在、端口 8512 不再监听、活动执行为 0、工作区租约 released；测试目录与失败证据保留。另一个由用户在隔离界面添加的项目没有会话或 run，本轮没有在该目录运行或修改文件。

辅助命令 `.venv/Scripts/python.exe -B .run/s6-native-fix/inspect_native.py` 的初次尝试依赖不存在的 `psutil`；改用现有系统 CIM，没有安装依赖。首次受限工具调用 CIM 返回拒绝访问，原脚本未将 PowerShell 非终止错误作为失败，生成 `inspection-1789484672560.json` 的空进程列表无效，不能用于清理结论。后续设为错误即停止，并在普通本机只读权限下采集 `inspection-1789484710271.json` 等独立记录，原记录保留。

`.venv/Scripts/python.exe -B .run/s6-native-fix/native_receipt.py` 首次退出 1：业务及已记录进程身份断言通过，但裸 PID `47680` 短暂存在，清理断言失败，证据为 `native-final-receipt.json`。针对该 PID 的后续 CIM 查询为空；未终止任何额外进程。原断言不变，复跑写新回执 `native-final-receipt-1789486133425.json`，退出 0。首轮没有保存该 PID 当时的创建身份，不能确认是启动器延迟退出还是 PID 复用；复跑只证明最终没有观察到残留。

本轮原生检查已经可操作，无需用户再补做相同创建测试。推进 E 前仍需独立解决或确认完成判定、补齐适用候选的未验原生链路与性能证据，并处理原长时取消限制；本轮到此停止。

## 6. 项目记忆与交付边界

已读取根 `AGENTS.md`、`docs/project-state.md`、本机模型说明、后续计划、B/C 准备记录第 10 节、本机云联调说明及最终候选验证报告。指定记忆是 2026-08-31 的 E 盘快照，当前为 F 盘的新 HEAD 与本机直连实现；差异按日期与适用对象解释，不把历史快照当作实时状态。

遵循本轮明确要求，不修改 `docs/project-state.md`，不新建记忆系统。环境回填的持久行为变化及候选关系记录在本报告，直接相关交接只追加新结论，保留历史失败。没有真实供应商请求、依赖变更、正式安装修改、生产数据变更或 Git 提交/分支/发布操作。

## 7. 最终复核与证据索引

`.venv/Scripts/python.exe -B .run/s6-native-fix/final_review.py` 退出 0，核对 1282 个开工基线文件：本轮修改 `files.py`、`test_local_executor.py`、原候选验证报告，新增本报告；其余 1279 个原有文件保持摘要，暂存区仍为空，`docs/project-state.md` 未变。原报告第 1～5 节正文摘要保持一致，只追加第 6 节。原候选 6 份产物、57 份原证据全部未变；414 项产品输入只变更 `files.py`，当前源码与新候选清单一致。

该复核还断言六变量复验结果、原生授权绑定、单一 run/命令/补丁、两次审批消费及一次取消、工作区租约释放和原进程身份消失；再次运行 Ruff 和 `git diff --check` 均退出 0。辅助脚本完成 AST 检查，新增文档完成 UTF-8、空白与本地链接检查。

`.venv/Scripts/python.exe -B .run/s6-native-fix/finalize_evidence.py` 将本轮脚本、诊断、首次失败、复跑结果、构建身份、原生白名单回执及截图的摘要汇总为 `final-evidence.json`，并绑定三个隔离回归目录。该索引不包含登录配置、模型凭据、SQLite 原库、WebView 数据或原始请求头/正文。证据目录被 Git 忽略，仅保证本机可检查，没有上传或发布。
