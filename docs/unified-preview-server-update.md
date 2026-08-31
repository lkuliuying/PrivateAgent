# 统一客户端预览版与服务器更新

本文适用于统一客户端 `1.0.0` Windows x64 预览包，以及现有 CentOS Stream 9、Supervisor 联网后端。**服务器不能只执行 `git pull` 就视为更新完成。** 必须确认加载来源、核对完整提交、停止单个服务、快进代码、重新启动并验收。客户端安装与服务器部署是两个步骤。

本文是操作说明，不表示已经连接、修改或验收生产服务器。项目状态记忆中的服务器安装副本信息是历史证据，实际启动方式应在操作前重新核对。

## 1. 预览版的发布边界

- 发行标签：`remote-v1.0.0-unified-preview.1`，对应 `dev/1.0.0` 本次分批提交完成后的提交。
- 发行名称：PrivateAgent 统一客户端 1.0.0 预览版 1（Windows x64）。
- 安装包：`PrivateAgent_1.0.0_x64-setup.exe`，30,078,408 字节，SHA-256 为 `e926d4e0eac93a46096b2e7c8ebbb671a31e000f9569aefd9f1d410b3bb561d0`。
- 附件还包括仅列出该安装包摘要的 `SHA256SUMS.txt`，以及原始 `build-info.json`。
- 未签名、手动测试安装，不标记 Latest，不发布自动更新清单，不覆盖旧 Release、旧附件或旧标签。正式安装升级、卸载和真实账号验收仍未完成。
- `remote-v` 前缀用于匹配现有 SignPath 工作流对本机执行器发行的排除规则，避免触发旧完整后端打包任务；该预览包本身是统一客户端，不是旧 `PrivateAgentRemote` 的自动升级包。
- 原始构建信息记录基线 `62413698bfc30435a958fb6c87c59ce6bc020082` 和 `dirty=true`：安装包在本次分批提交前生成。保留这份真实构建记录，不把它改写成提交后重新构建。本次提交将相应实现纳入 Git；提交检查仅清理了两个新共享模块末尾的多余空行，未改变功能。后续新增发行说明也不改变安装包。

发行页：[统一客户端预览版](https://github.com/lkuliuying/PrivateAgent/releases/tag/remote-v1.0.0-unified-preview.1)。以 GitHub 页面实际发布状态及附件摘要为准。[GitHub 预发布与 Latest 参数说明](https://docs.github.com/en/rest/releases/releases#create-a-release)。

客户端升级前正常退出旧程序，保存其整个账号数据目录。统一版与旧 Remote 的应用目录不同，记录不会因为安装新包自动迁移；按[历史迁移说明](./unified-desktop-runtime.md#5-两类旧历史如何迁移)操作。该包默认没有预置云服务地址，使用账号服务时在连接设置中配置服务地址。

## 2. 本次为什么需要专项更新

| 变化 | 对服务器的影响 |
| --- | --- |
| 新增 `src/private_agent_core/`，旧模块保留兼容入口 | 后端需要能导入仓库中的新共享包，不能只替换旧包里的几个文件 |
| 新增 `GET /desktop/history/export` | 用于当前账号的旧历史导出；客户端发布不能代替部署这个接口 |
| `pyproject.toml` wheel 包清单扩展 | 本次未改变依赖版本，但旧 wheel 不包含新共享包；继续使用安装副本需要重新打包安装 |
| SQLite 和本机执行器 | 属于客户端数据；不能用它替换服务器 MySQL、ChromaDB 或外部数据目录 |
| 构建脚本、Rust 执行宿主和新目录 | 现有例行更新脚本按保守规则要求人工审阅 |

已核对本次从 `6241369` 开始的改动：没有依赖版本、锁文件或 Alembic 迁移文件变更。**这不证明服务器当前环境与这个基线一致。** 应核对服务器实际 HEAD 到目标提交的全部差异，并检查现有依赖。若已经使用源码启动入口，且已有依赖满足目标代码，本次无需机械执行 `pip install -U` 或重建环境。

现有 `scripts/update-connected-server.py check/apply` 会将 `private_agent_core`、`pyproject.toml` 等列为专项审阅文件。本次不要直接运行 `apply`，也不要修改白名单跳过保护。首次引入更新脚本的旧服务器同样需要按下述人工流程操作。

## 3. 操作前检查与备份

以下命令仅适用于仓库 `/opt/private-agent/current`、Python `/opt/private-agent/venv/bin/python`、Git 账号 `privateagent`、Supervisor 程序 `private-agent`。在服务器 root 运维会话逐步执行；任何检查失败立即停止，不能无人值守整段执行。安排维护窗口、等待正在执行的任务完成，并避免其他人同时修改仓库或服务。

```bash
PA_REPO=/opt/private-agent/current
PA_TAG=remote-v1.0.0-unified-preview.1
runuser -u privateagent -- git -C "$PA_REPO" status --short --branch
runuser -u privateagent -- git -C "$PA_REPO" log -5 --oneline
supervisorctl -c /etc/supervisord.conf status private-agent
PA_BEFORE=$(runuser -u privateagent -- git -C "$PA_REPO" rev-parse HEAD)
runuser -u privateagent -- git -C "$PA_REPO" fetch origin dev/1.0.0
runuser -u privateagent -- git -C "$PA_REPO" fetch origin "refs/tags/$PA_TAG:refs/tags/$PA_TAG"
PA_TARGET=$(runuser -u privateagent -- git -C "$PA_REPO" rev-parse "refs/tags/$PA_TAG^{commit}")
printf 'before=%s\ntarget=%s\n' "$PA_BEFORE" "$PA_TARGET"
runuser -u privateagent -- git -C "$PA_REPO" merge-base --is-ancestor "$PA_BEFORE" "$PA_TARGET"
runuser -u privateagent -- git -C "$PA_REPO" merge-base --is-ancestor "$PA_TARGET" origin/dev/1.0.0
runuser -u privateagent -- git -C "$PA_REPO" diff --stat "$PA_BEFORE" "$PA_TARGET"
runuser -u privateagent -- git -C "$PA_REPO" diff "$PA_BEFORE" "$PA_TARGET" -- pyproject.toml uv.lock requirements.txt alembic.ini alembic
runuser -u privateagent -- /opt/private-agent/venv/bin/python -m pip check
```

确认：当前分支为 `dev/1.0.0`；无已修改、暂存、未跟踪文件或 merge/rebase 等未完成操作；两次祖先检查均为退出码 0；`target` 与本次发布的完整提交一致；依赖差异只有已审阅的 wheel 包清单变化，且迁移文件无差异。若服务器存在额外补丁或不同基线，先审阅保留，不执行 reset/clean 或强制合并。不要用不确定的最新分支头替代本次固定目标。

按现有运维流程备份数据库和外部数据，并确认可恢复；备份仅保存在服务器受限目录，不上传聊天或 Git。首次切换源码入口还需按[现有指南第 2.1 节](./server-code-update-workflow.md#21-保存旧配置并取得已核对代码)在服务器本机保存 Supervisor 配置与旧提交号。保持旧虚拟环境及安装副本不变，以备核对和恢复。

## 4. 停止单个服务并快进源码

```bash
supervisorctl -c /etc/supervisord.conf stop private-agent
supervisorctl -c /etc/supervisord.conf status private-agent
```

只有状态明确为 `STOPPED` 才继续；Supervisor 查询停止状态可能返回非零退出码，不能仅凭退出码判断。再次检查工作区仍干净、HEAD 仍等于已记录的 `PA_BEFORE` 后执行：

```bash
runuser -u privateagent -- git -C "$PA_REPO" status --short --branch
runuser -u privateagent -- git -C "$PA_REPO" rev-parse HEAD
runuser -u privateagent -- git -C "$PA_REPO" merge --ff-only "$PA_TARGET"
runuser -u privateagent -- git -C "$PA_REPO" rev-parse HEAD
runuser -u privateagent -- /opt/private-agent/venv/bin/python -I -B \
  /opt/private-agent/current/scripts/start-connected-server.py --check
```

HEAD 必须等于 `PA_TARGET`，入口检查必须返回 `SOURCE_ENTRY_OK`。入口检查只验证新检查进程的解析路径，不读取配置、不运行迁移、不证明业务可用。再检查新共享包可从指定源码目录解析：

```bash
runuser -u privateagent -- /opt/private-agent/venv/bin/python -I -B -c 'from importlib.machinery import PathFinder; from pathlib import Path; root=Path("/opt/private-agent/current/src"); spec=PathFinder.find_spec("private_agent_core", [str(root)]); expected=root/"private_agent_core/__init__.py"; assert spec is not None and spec.origin == str(expected), "CORE_SOURCE_CHECK_FAILED"; print("CORE_SOURCE_OK", spec.origin)'
```

此检查同样不导入应用，也不证明既有服务进程已经加载新代码。

## 5. 根据现有加载方式启动

**已经使用源码启动入口：** 确认现有 Supervisor 的 `directory`、`command`、`user` 与下表一致，无配置变更时直接启动刚停止的单个服务。

```ini
directory=/opt/private-agent/current
command=/opt/private-agent/venv/bin/python -I -B /opt/private-agent/current/scripts/start-connected-server.py
user=privateagent
```

```bash
supervisorctl -c /etc/supervisord.conf start private-agent
supervisorctl -c /etc/supervisord.conf status private-agent
```

**仍使用 site-packages 安装副本：** 拉取代码不会替换安装副本，先按[源码切换指南第 2.2～2.3 节](./server-code-update-workflow.md#22-核对完整运行包依赖和迁移)比较完整包并完成首次切换。只修改现有 `[program:private-agent]` 中上述三项，保留全部外部配置、环境变量、数据路径和密钥引用，不能用此片段覆盖整份配置。共享模块提取造成的预期差异应与本次提交核对；安装副本独有的其他补丁不能忽略。

配置修改后执行以下命令；单纯 restart 不会重读配置：

```bash
supervisorctl -c /etc/supervisord.conf reread
supervisorctl -c /etc/supervisord.conf update private-agent
supervisorctl -c /etc/supervisord.conf status private-agent
```

`update private-agent` 可能已启动程序，只有仍为 `STOPPED` 才另行 start。若为 `BACKOFF` / `FATAL`，先检查服务器本机的脱敏错误，不循环启动。不得使用 `reload` 或 `restart all`。启动入口仍调用原 `server_entry` 并保留自动迁移流程；出现迁移失败不能跳过迁移强行启动。

若必须保留 wheel 部署，需在隔离候选环境打包、安装包含 `personal_assistant`、`private_agent_core` 和所需资源的同一版本 wheel，验证依赖与资源后切换并重启；不建议在现有运行环境直接执行无版本限制的安装升级。该替代部署路径未在本次进行 Linux 验证。

## 6. 验收、后续更新与恢复

1. Git HEAD 等于已核对目标，工作区干净；Supervisor 持续 `RUNNING`，无反复退出。核对实际进程账号、启动参数与工作目录。
2. 统一客户端配置正确的账号服务地址并登录，核对账号、模型配置、历史页面；需要迁移时验证当前账号的旧历史导出。禁止将其他账号的数据或凭据当测试样本。
3. 本地模型模式不依赖服务器模型接口；账号服务模式需另行进行真实模型验收，可能产生费用。构建、进程 RUNNING 或匿名 `/health` 返回 401 都不等于业务验收通过。
4. 记录提交、时间和脱敏验收结论，不复制生产日志正文。若重启使仅存内存的供应商 Key 丢失，在客户端安全设置中重新保存。

本次专项更新完成后，未来仅包含已支持普通后端路径、且依赖及迁移未变化的提交，可以使用现有例行工具：

```bash
/opt/private-agent/venv/bin/python -I -B \
  /opt/private-agent/current/scripts/update-connected-server.py check
```

只有 `CHECK_PASSED` 才按[日常更新指南](./server-code-update-workflow.md#3-今后的日常更新)使用其给出的完整 target 执行 apply。未来修改 `private_agent_core` 仍会被现有规则拦截，继续按专项更新审阅，不能默认所有 Python 改动都支持自动更新。

失败后先查清停在哪一步，保留源码、数据库与旧环境。首次切换失败且没有不兼容数据变化时可按原指南恢复已备份的入口配置；后续优先在开发机提交经测试的修复或回退提交，再让服务器快进。不要 `git reset --hard`、删除未跟踪文件或修改数据库版本表。

## 7. 验证与记忆范围

实现阶段的 Python、前端、Rust 和真实打包产物验证详见[实现验收记录](./unified-desktop-runtime.md#7-实际验证与未验证事项)。发行前另行核对安装包 SHA-256、提交文件范围、服务器更新工具回归和远端发布结果；测试成功不代表执行过以上服务器命令。

已读取 `AGENTS.md`、`docs/project-state.md`、服务器更新指南及对应源码。项目记忆中的提交与部署状态属于历史快照；本说明按当前源码描述更新条件，不将未验证的服务器切换写为已完成。按照项目入口约定，本次没有修改 `docs/project-state.md` 或全局记忆。

### 发布前本机复验（2026-08-31）

在 `.run/unified-tests` 隔离目录执行，没有读取生产配置或连接生产数据库：

```powershell
$env:PYTHONPATH='E:\Program\Agent\src'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$testFiles=@(Get-ChildItem -LiteralPath 'E:\Program\Agent\tests\unit' -Filter 'test_local*.py' | ForEach-Object FullName)
Set-Location E:\Program\Agent\.run\unified-tests
& E:\Program\Agent\.venv\Scripts\python.exe -m pytest --noconftest -p no:cacheprovider --basetemp=E:\Program\Agent\.run\unified-tests\publish-python-1 @testFiles E:\Program\Agent\tests\unit\test_desktop_history.py E:\Program\Agent\tests\test_agent_runtime.py E:\Program\Agent\tests\test_model_gateway.py E:\Program\Agent\tests\test_v100_ct6_exec_host_client.py E:\Program\Agent\tests\test_v100_ct6_rust_host_e2e.py E:\Program\Agent\tests\test_v100_ct6_sandbox_enforcement.py E:\Program\Agent\tests\unit\test_connected_server_workflow.py -q -rs
```

结果：165 passed、1 skipped；跳过项是 Windows 当前用户不能创建真实符号链接。重复验证应使用新的 basetemp 路径，避免覆盖其他测试证据。

在桌面目录执行以下命令，结果为 80 个测试文件、463 项通过，类型检查退出码 0：

```powershell
Set-Location E:\Program\Agent\apps\desktop
node node_modules/vitest/vitest.mjs run
node node_modules/vue-tsc/bin/vue-tsc.js --noEmit
```

在仓库根目录执行：

```powershell
Set-Location E:\Program\Agent
node --test scripts/build-remote-client.test.cjs
.venv/Scripts/python.exe -I -B scripts/verify-unified-client.py --bundle .run/unified-client-z96sXu --work-dir .run/unified-tests
.venv/Scripts/python.exe -I -B scripts/start-connected-server.py --check
.venv/Scripts/python.exe -m ruff check src/private_agent_core src/private_agent_local src/personal_assistant/api/routes_desktop_history.py src/personal_assistant/main_api.py tests/unit/test_local*.py tests/unit/test_desktop_history.py scripts/verify-unified-client.py
git diff --check
Get-FileHash -Algorithm SHA256 -LiteralPath .run/unified-client-z96sXu/PrivateAgent_1.0.0_x64-setup.exe
```

构建规则 9 项通过；实际打包验证返回 `passed=true`，包括文件写入、人工审批、限时完全访问、上下文用量、损坏宿主摘要拒绝和 3 次运行的历史导出。使用回环模型替身，`real_model_called=false`，`sandbox_available=false`。Ruff 和差异检查通过，入口返回 `SOURCE_ENTRY_OK`，安装包摘要与第 1 节一致。本文 7 个 Bash 命令块通过 Git Bash `bash -n` 语法检查，没有在服务器执行。

最初在沙箱内运行 Node 构建规则遇到 `spawn EPERM`，Git Bash 遇到无法创建信号管道；在获准的本机环境重跑相同检查后通过，属于环境权限限制。暂存后差异检查发现两个新文件末尾有多余空行，清理后复验通过，没有修改执行逻辑。以上结果不包含真实安装升级、生产启动、生产历史导出或真实账号验收。
