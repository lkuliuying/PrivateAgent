# 开发机提交、服务器拉取的更新流程

适用部署：CentOS Stream 9，仓库 `/opt/private-agent/current`，分支 `dev/1.0.0`，服务账号 `privateagent`，Supervisor 程序 `private-agent`，Python `/opt/private-agent/venv/bin/python`。其他部署不能直接套用这些命令。

目标流程：**开发机修改并测试 → 提交和推送 GitHub → 服务器检查目标提交 → 停止单个服务 → 快进代码 → 启动并验收。** 服务器不再承担日常代码编写、提交和推送。

本说明及工具已在开发机验证，尚未在生产服务器完成首次切换。服务器之前加载的是虚拟环境内的安装副本，因此目前不能只执行 `git pull` 就认为运行代码已更新。先完成下述一次性整理。

> 2026-08-31 服务器历史核对：收到 `server-history-20260831-104455.bundle`，其中服务器分支头为 `b7fccfbd3bfb68458fd85b5d7445b815d58e227e`。该提交已经合并服务器补丁 `43b63c0` 与远端 `1496153`，其完整 Git 文件树与 `1496153` 相同。此次收拢保留这两个服务器提交和开发机后续的更新工具，不改变业务代码。该服务器不必重复下述冲突处理和 bundle 导出；在包含 `b7fccfb` 的开发分支推送后，先 fetch 并确认可快进，再进入第 2 节。bundle 仅证明导出时的已提交历史，不证明当前工作区干净、服务已切换或生产验收通过。

## 1. 一次性整理服务器 Git 历史

服务器曾有本地提交 `43b63c0`，并在合并远端时出现三个冲突；本次 bundle 已证实它们在 `b7fccfb` 中完成合并。以下步骤保留用于尚未完成整理的其他副本；已经包含该提交的服务器不重复发起 merge。

在服务器 root 会话检查：

```bash
runuser -u privateagent -- git -C /opt/private-agent/current status --short --branch
runuser -u privateagent -- git -C /opt/private-agent/current diff --name-only --diff-filter=U
runuser -u privateagent -- git -C /opt/private-agent/current log -5 --oneline
```

如果仍是此前贴出的三个冲突，已逐项核对过的结论是：这三个文件可采用此次合并的远端版本；其他服务器补丁和本地提交保留。**仅适用于该次已核对的冲突，不是通用的冲突解决办法。**

```bash
runuser -u privateagent -- git -C /opt/private-agent/current restore \
  --source=MERGE_HEAD --staged --worktree -- \
  scripts/repair-connected-runtime.py \
  src/personal_assistant/api/routes_desktop_model.py \
  src/personal_assistant/main_api.py
runuser -u privateagent -- git -C /opt/private-agent/current diff --name-only --diff-filter=U
runuser -u privateagent -- git -C /opt/private-agent/current diff --cached --check
runuser -u privateagent -- git -C /opt/private-agent/current diff --cached --stat
```

只有无未解决冲突、检查成功且暂存内容已核对，才完成提交：

```bash
runuser -u privateagent -- git -C /opt/private-agent/current commit -m "合并远端修复并保留服务器补丁"
```

若未配置提交身份，键名为 `user.name`，不是 `user.user`。应配置 `privateagent` 的仓库身份，不能用 root 的 Git 配置替代。不要执行 `reset --hard`、`clean` 或强推来消除分叉。

### 把服务器独有历史带回开发机

即使代码内容相同，服务器本地提交仍可能让历史分叉。建议用离线 Git bundle 搬回历史，服务器不必配置 GitHub 写权限。先确认工作区干净、提交中没有凭据或环境文件，再执行：

```bash
install -d -m 700 -o privateagent -g privateagent /opt/private-agent/handoff
runuser -u privateagent -- git -C /opt/private-agent/current bundle create \
  /opt/private-agent/handoff/server-history.bundle dev/1.0.0
runuser -u privateagent -- git -C /opt/private-agent/current bundle verify \
  /opt/private-agent/handoff/server-history.bundle
```

这个 bundle 包含分支历史，不包含未跟踪文件、虚拟环境或外部数据；但已经提交过的内容会在里面，因此不能用来传递含秘密的提交。通过已有安全文件传输方式下载到开发机，例如 `E:\Program\Agent\.tmp\server-history.bundle`；不要公开上传。

开发机 PowerShell，在当前开发改动已经提交、工作区干净后执行：

```powershell
Set-Location E:\Program\Agent
git status --short --branch
git fetch origin dev/1.0.0
git merge --ff-only origin/dev/1.0.0
git bundle verify .tmp/server-history.bundle
git fetch .tmp/server-history.bundle dev/1.0.0
git merge --no-ff --no-commit FETCH_HEAD
git status --short
git diff --cached --check
git diff --cached --stat
```

如有冲突，在开发机逐项保留有用修复并测试，再提交合并；如提示已经包含该历史，不需要新建提交。不要把 Git 的失败输出当作成功继续后续步骤。确保这些更新工具和文档也已提交，再推送：

```powershell
git commit -m "整理服务器补丁并统一开发与部署历史"
git push origin dev/1.0.0
```

后续服务器 fetch 后必须满足“服务器 HEAD 是远端提交的祖先”。若服务器还有独有提交，继续在开发机合并共享历史，不能硬覆盖。服务器今后只需要仓库读取权限；私有仓库可使用只读部署密钥，不必在服务器保存个人写入令牌。

## 2. 一次性切换为加载仓库源码

安排维护窗口，等待当前任务结束。此阶段会改变整个应用的加载来源，不能只确认五个应急补丁文件。外部数据库、数据目录、密钥文件、日志权限及 Nginx 均保持原配置。

### 2.1 保存旧配置并取得已核对代码

先在服务器检查当前程序为 `private-agent`、账号为 `privateagent`、解释器和仓库路径符合本文。停止前记下当前提交。备份放在仓库外且仅 root 可读：

```bash
umask 077
SOURCE_BACKUP="/opt/private-agent/source-switch-backup-$(date +%Y%m%d-%H%M%S)"
install -d -m 700 "$SOURCE_BACKUP"
cp -p /etc/supervisord.d/private-agent.ini "$SOURCE_BACKUP/private-agent.ini"
runuser -u privateagent -- git -C /opt/private-agent/current rev-parse HEAD > "$SOURCE_BACKUP/before-commit.txt"
printf '配置备份目录：%s\n' "$SOURCE_BACKUP"
runuser -u privateagent -- git -C /opt/private-agent/current fetch origin dev/1.0.0
runuser -u privateagent -- git -C /opt/private-agent/current status --short --branch
runuser -u privateagent -- git -C /opt/private-agent/current merge-base --is-ancestor HEAD origin/dev/1.0.0
```

最后一条退出码必须为 0，且工作区无改动、无合并中的状态；否则停在这里处理历史。记录并核对目标提交后，在维护窗口停止服务，再更新源码：

```bash
runuser -u privateagent -- git -C /opt/private-agent/current rev-parse origin/dev/1.0.0
supervisorctl -c /etc/supervisord.conf stop private-agent
supervisorctl -c /etc/supervisord.conf status private-agent
```

只有显示 `STOPPED` 才继续。注意 Supervisor 查询已停止程序时可能返回非零退出码，不能仅用退出码判断停止失败。

```bash
runuser -u privateagent -- git -C /opt/private-agent/current merge --ff-only origin/dev/1.0.0
runuser -u privateagent -- git -C /opt/private-agent/current status --short --branch
```

### 2.2 核对完整运行包、依赖和迁移

以下工具仅输出 Python 文件路径及摘要，不导入应用、不读取环境配置、不连接数据库、不复制或改写安装副本：

```bash
runuser -u privateagent -- /opt/private-agent/venv/bin/python -I -B \
  /opt/private-agent/current/scripts/start-connected-server.py \
  --audit-installed /opt/private-agent/venv/lib/python3.12/site-packages/personal_assistant
```

- `PYTHON_FILES_MATCH` / 退出码 0：Python 文件内容一致，忽略 CRLF/LF 行尾差异。
- `REVIEW_REQUIRED` / 退出码 2：有差异，不能直接忽略。`source_sha256=null` 表示仅安装副本存在，尤其要排查服务器补丁；`installed_sha256=null` 表示仓库新增文件。对照 Git 历史与服务器修复记录逐项确认；有用的安装副本修复先在开发机纳入仓库并测试。
- 退出码 1：目录、权限、文件类型等检查失败，未完成比较。

比较仅覆盖包内 `.py`，不证明依赖、非 Python 资源、配置或原进程内存一致。保留原虚拟环境及安装副本，首次切换不执行卸载、覆盖或 `pip install -e .`。

初次切换前还应检查：

```bash
runuser -u privateagent -- /opt/private-agent/venv/bin/python -m pip check
runuser -u privateagent -- git -C /opt/private-agent/current diff --name-only \
  debcd81 HEAD -- pyproject.toml uv.lock requirements.txt alembic.ini alembic
runuser -u privateagent -- /opt/private-agent/venv/bin/python -I -B \
  /opt/private-agent/current/scripts/start-connected-server.py --check
```

`debcd81` 是此前部署基线，只有确认实际环境仍对应此基线才能使用。本机核对该基线到 `1496153` 的上述依赖及迁移文件无差异，不保证未来提交也如此。`pip check` 仅检查已安装包之间的依赖关系；不能代替按当前锁文件准备环境与功能验收。若 pip 不存在、检查失败、基线不符或存在依赖/迁移差异，停在这里，转第 5 节专项更新。

`SOURCE_ENTRY_OK` 只证明新检查进程的解析位置正确；不会导入 FastAPI、运行 Alembic 或启动第二个服务。

### 2.3 修改现有 Supervisor 配置中的指定项

在服务器本机编辑 `/etc/supervisord.d/private-agent.ini`，定位现有 `[program:private-agent]`，仅核对或修改以下三项，**不能用此片段覆盖整份配置**：

```ini
directory=/opt/private-agent/current
command=/opt/private-agent/venv/bin/python -I -B /opt/private-agent/current/scripts/start-connected-server.py
user=privateagent
```

保留现有 `environment=` 全部必要内容，特别是 `PA_PARENT_PID="1"`、`PA_CODING_PERMISSION_MODELS_ENABLED="true"`、外部数据和日志路径、密钥文件引用。不要新增第二个 `environment=`，不要打开新的功能开关，不要将完整配置贴到聊天或提交 Git。确认现有 `.env` / `smtp.env` 的相对路径仍相对于 `/opt/private-agent/current`；保持原外部存储或链接安排。

`-I` 隔离 Python 环境路径，启动脚本显式优先选择仓库 `src`；无需依赖 `PYTHONPATH`。`-B` 禁止生成新的字节码缓存。启动脚本随后调用原 `personal_assistant.server_entry.main()`，保留自动迁移和服务生命周期；不是绕过迁移直接运行 Uvicorn。[Python 参数说明](https://docs.python.org/3.12/using/cmdline.html)。

配置改变必须 reread/update；单纯 restart 不会重读配置。只更新这一个程序组，不能使用 `reload` 或 `restart all`。[Supervisor 说明](https://supervisord.org/running.html)。

```bash
supervisorctl -c /etc/supervisord.conf reread
supervisorctl -c /etc/supervisord.conf update private-agent
supervisorctl -c /etc/supervisord.conf status private-agent
```

`update private-agent` 可能已经启动程序；只有仍为 `STOPPED` 才另行执行 `start private-agent`。如果进入 `BACKOFF` / `FATAL`，查看服务器本机已脱敏日志，不要循环强行启动。

完成第 4 节验收后，再运行第 3 节 `check`。它会核对 Supervisor 子进程的启动参数、工作目录、运行账号，拒绝仍使用旧安装入口的服务；这不是读取原进程的 Python 模块内存。

## 3. 今后的日常更新

### 开发机

在 `E:\Program\Agent` 的 `dev/1.0.0` 完成功能修改、相关测试和差异审阅。只暂存本次文件，不把 `.env`、数据、日志、`.tmp`、虚拟环境或凭据加入 Git。确认有必要的服务变更说明，然后提交并推送：

```powershell
Set-Location E:\Program\Agent
git status --short --branch
git diff --check
git diff --stat
# 将本次已审阅的文件逐项加入暂存区，再检查暂存差异。
git diff --cached --check
git diff --cached --stat
git commit -m "描述本次修改"
git push origin dev/1.0.0
```

如果推送因远端更新被拒绝，先保留本地提交、fetch 并在开发机处理合并；不 force push。

### 服务器：检查

在 root 运维会话执行：

```bash
/opt/private-agent/venv/bin/python -I -B \
  /opt/private-agent/current/scripts/update-connected-server.py check
```

`check` 会 fetch 远端分支，因此会更新 Git 对象和远端跟踪引用；**不会修改工作区、停止服务或安装依赖**。输出 `before`、`target` 和变更路径。必须看到 `CHECK_PASSED` 才进入下一步。

工具固定执行 Git 的账号为 `privateagent`，服务名为 `private-agent`，只允许快进。Git `--ff-only` 在存在本地独有历史时拒绝合并，从而防止把服务器重新变成开发分支。[Git 合并说明](https://git-scm.com/docs/git-merge)。

### 服务器：应用

保存 `before` 完整 SHA 作为回退依据，核对 `target`，等待正在运行的任务结束。在维护窗口把下面参数替换为 `check` 输出的 **40 位 target**：

```bash
/opt/private-agent/venv/bin/python -I -B \
  /opt/private-agent/current/scripts/update-connected-server.py apply \
  --target 在此填写已核对的40位target
```

顺序为再次 fetch/核对目标 → 核对干净工作区及源码运行进程 → 停止 `private-agent` → 确认 `STOPPED` → 快进到已核对提交 → 检查源码入口 → 启动该服务 → 核对进程。

远端在 check 后改变、未提交改动、分支分叉、合并未结束、入口不符、依赖或迁移变更均会拒绝例行更新。工具用 `/run/private-agent-code-update.lock` 阻止自身并发运行；维护窗口仍须避免其他人手工改 Git、配置或服务。

成功输出 `PROCESS_RUNNING_REQUIRES_ACCEPTANCE`，随后必须执行第 4 节验收。无新提交输出 `ALREADY_CURRENT`，不会无故重启。

任何失败立即停止后续操作。工具不自动回滚、不自动清理，也不尝试启动旧版本。**停服后失败可能使服务保持停止；启动失败或中断也可能出现部分执行状态。** 先用 Git status/log 与 Supervisor status 确认停在哪一步，再处理。命令错误正文可能含远程凭据，因此工具只输出固定错误摘要；需要在服务器本机排查详细原因。

## 4. 每次更新后的验收

1. 核对 `git rev-parse HEAD` 等于目标完整 SHA，工作区干净。
2. 核对 Supervisor 为 `RUNNING`，间隔一段时间再查，确保没有反复退出重启。
3. 客户端登录，确认会话、模型配置、项目操作及管理员日志页面可用；管理员时间使用 Asia/Shanghai。
4. 使用无敏感内容发送指令，检查不再出现原 HTTP 502；真实推理可能收费，由操作者确认后执行。
5. 如果重启后供应商 Key 丢失，在客户端安全配置页重新保存。当前部分 Key 为内存状态，不能通过导出凭据解决。

匿名 `/health` 返回 401、进程 RUNNING、路由存在或源码摘要正确，都不能单独证明业务验收通过。保存提交号、时间和脱敏验收结论即可，不保存日志正文、令牌或完整环境配置。

## 5. 哪些更新不能只拉取重启

| 变化 | 操作边界 |
| --- | --- |
| 普通后端 `.py` 逻辑，既有依赖足够 | 可用例行工具；仍需测试、维护窗口和业务验收 |
| `pyproject.toml`、`uv.lock`、`requirements.txt` 或依赖实际需求变化 | 先按锁文件在隔离 Linux 候选环境准备和测试依赖，验证回退；工具不会自动安装或升级 |
| `alembic.ini`、`alembic/`、数据库模型含义变化 | 阅读迁移、备份数据库并验证恢复；原启动入口会执行迁移，不能盲目启动，参阅[数据库升级手册](./database-upgrade-runbook.md) |
| `config.py`、`server_entry.py`、启动或更新工具、其他未知文件 | 人工审阅专项更新；停止服务后快进，保留配置和旧环境，再验证入口与启动 |
| Vue/Tauri 桌面端或 `private_agent_local` | 服务器拉取不能替用户升级客户端；需单独构建、上传和安装对应联网版安装包 |
| 外部配置、密钥、数据、Nginx/Supervisor | 不由 Git 覆盖；不在本工具自动修改范围内 |

工具按文件路径保守拦截，但不能从代码推断全部依赖和数据库兼容性。即使没有迁移文件变化，只要本次功能需要新的依赖、表结构或数据调整，仍按专项更新处理。不要用跳过迁移开关绕过失败，也不要拿生产库跑测试。

首次引入这些脚本本身就是一次专项更新，因此不能要求尚未安装的新工具完成自己的首次安装。后续工具变更也不允许脚本自行升级并继续执行未审阅的部署逻辑。

## 6. 回退与恢复

### 首次源码切换失败

保留原虚拟环境和安装副本是为了回退入口。确认本次未产生不兼容的数据库迁移后，停止单个服务，在服务器本机从第 2 节保存的具体备份目录恢复 `private-agent.ini`，再 reread/update **private-agent** 并验收。不要用猜测的目录覆盖配置，不要回退数据库或整个 Git 工作区。此时源码新提交可保留，旧配置重新指向旧安装副本。

如果切换已经改过数据库或依赖，先按经审核的恢复方案处理；只恢复启动命令并不保证兼容。

### 日常更新失败

优先在开发机修复或生成回退提交、测试并推送，让服务器仍沿共同历史前进。后端依赖和迁移兼容时，可对单个有问题的提交使用 `git revert`；合并提交或一组提交必须先审阅正确的回退范围，不能机械批量 revert。

若服务仍能稳定 RUNNING，可照第 3 节应用已测试的修复目标。若服务已停止或启动失败，工具会拒绝按正常运行服务处理：保持停服，在服务器人工确认工作区干净、当前 HEAD 与失败更新记录一致，fetch 并核对修复目标是快进且依赖/数据库兼容，再按下列顺序恢复：

```bash
runuser -u privateagent -- git -C /opt/private-agent/current status --short --branch
runuser -u privateagent -- git -C /opt/private-agent/current fetch origin dev/1.0.0
runuser -u privateagent -- git -C /opt/private-agent/current log -5 --oneline
runuser -u privateagent -- git -C /opt/private-agent/current diff --stat HEAD origin/dev/1.0.0
```

确认 `private-agent STOPPED` 且目标已审阅后，才执行：

```bash
runuser -u privateagent -- git -C /opt/private-agent/current merge --ff-only origin/dev/1.0.0
runuser -u privateagent -- /opt/private-agent/venv/bin/python -I -B \
  /opt/private-agent/current/scripts/start-connected-server.py --check
supervisorctl -c /etc/supervisord.conf start private-agent
supervisorctl -c /etc/supervisord.conf status private-agent
```

每一步失败都停止，不执行后续命令。禁止靠强制 reset 到 `before`、删除未跟踪文件或修改数据库版本表恢复表面上的一致性。

## 7. 工具与旧文档的关系

- [源码启动入口](../scripts/start-connected-server.py)：选择当前仓库的包，保留原服务器入口；附只读入口检查和完整 Python 文件摘要比较。
- [例行更新工具](../scripts/update-connected-server.py)：固定部署边界，保护本地修改和分叉历史，不改外部配置、不装依赖、不操作其他服务。
- [隔离回归测试](../tests/unit/test_connected_server_workflow.py)：验证临时 Git 远端、真实快进和拒绝条件；Supervisor 使用替身，不等于 Linux 生产演练。
- [旧安装副本应急修复](./connected-runtime-1.0.3-repair.md)保留历史用途。首次源码切换验收完成后，日常更新不再执行五文件复制补丁。
- [项目状态记忆](./project-state.md)是此前记录，Git/构建/生产状态必须按当前证据核对。本次未把“准备好切换”写成“服务器已切换”。

## 8. 本次本机验证记录

2026-08-31，在 Windows 开发机、没有环境配置文件的 `.tmp/server-workflow-check` 目录中执行：

```powershell
$env:PYTHONPATH='E:\Program\Agent\src'
$env:PYTHONDONTWRITEBYTECODE='1'
E:/Program/Agent/.venv/Scripts/python.exe -m pytest E:/Program/Agent/tests/unit/test_connected_server_workflow.py E:/Program/Agent/tests/test_server_entry.py E:/Program/Agent/tests/unit/test_connected_runtime_repair.py E:/Program/Agent/tests/unit/test_connected_backend_bundle.py --noconftest -p no:cacheprovider --basetemp E:/Program/Agent/.tmp/server-workflow-pytest-5 -q -rs
```

结果：**83 passed，2 skipped**。两个跳过均因当前 Windows 用户无创建真实符号链接的权限；两个 Alembic `path_separator` 弃用警告来自现有配置，未顺带修改。初次运行遇到沙箱临时目录权限问题，改在获准的本机隔离测试环境重跑；测试里的 Windows 编码、CRLF 样本和 Linux 信号替身问题已修正后复跑通过。

在仓库根目录执行的静态与入口检查：

```powershell
.venv/Scripts/python.exe -m ruff check scripts/start-connected-server.py scripts/update-connected-server.py tests/unit/test_connected_server_workflow.py
git diff --check
.venv/Scripts/python.exe -I -B scripts/start-connected-server.py --check
.venv/Scripts/python.exe -I -B scripts/start-connected-server.py --audit-installed E:/Program/Agent/src/personal_assistant
```

Ruff、差异空白检查通过；入口返回 `SOURCE_ENTRY_OK`；最后一条用源码目录自身验证摘要工具返回 `PYTHON_FILES_MATCH`，**不是核对了服务器安装包**。指南的 Bash 命令块逐个通过 `bash -n`，PowerShell 块通过语法解析；新增本地链接有效。文档索引中原有 `vue-desktop-code/`、`webfront-code/` 目录链接缺失，已对照原 HEAD 确认为既有问题，本次未扩展修复。

未在 Linux 生产环境运行 `update-connected-server.py check/apply`，未重启服务器、验证真实 `/proc`/Supervisor 交互、执行生产迁移或付费模型推理。运行账号、进程参数、超时信号及停服失败等使用隔离替身验证；真实 Git 快进、分叉和本地修改保护使用临时远端仓库验证。生产切换与真实账号验收仍按本指南由操作者完成。

### 服务器历史收拢后的复验

2026-08-31，在独立工作区合并服务器 `b7fccfb`；合并索引与开发机 `8645bdb` 的文件树一致，没有需要补入的业务代码。随后仅更新本文中的已确认状态。以下命令在无环境文件的 `E:\Program\Agent\.tmp\server-history-validation-20260831` 执行：

```powershell
$env:PYTHONPATH='E:\Program\Agent\.tmp\server-history-merge-20260831\src'
$env:PYTHONDONTWRITEBYTECODE='1'
& E:/Program/Agent/.venv/Scripts/python.exe -m pytest E:/Program/Agent/.tmp/server-history-merge-20260831/tests/unit/test_desktop_model.py E:/Program/Agent/.tmp/server-history-merge-20260831/tests/unit/test_admin_logs.py E:/Program/Agent/.tmp/server-history-merge-20260831/tests/unit/test_connected_runtime_repair.py E:/Program/Agent/.tmp/server-history-merge-20260831/tests/unit/test_connected_server_workflow.py E:/Program/Agent/.tmp/server-history-merge-20260831/tests/test_server_entry.py E:/Program/Agent/.tmp/server-history-merge-20260831/tests/unit/test_connected_backend_bundle.py --noconftest -p no:cacheprovider --basetemp E:/Program/Agent/.tmp/server-history-pytest-20260831-1 -q -rs
```

结果：**113 passed，3 skipped**；跳过项均为 Windows 真实符号链接权限限制，两个 Alembic 警告与前次相同。相关模型/日志模块及更新工具的 Ruff、Git 差异检查通过，源码入口检查返回 `SOURCE_ENTRY_OK`。bundle 验证及完整文件树比较通过；原开发目录未提交的 `README.md` 保持原样，未包含在此次合并中。这些结果仍不代表服务器已切换或真实账号验收通过。
