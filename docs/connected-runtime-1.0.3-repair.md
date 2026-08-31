# 远程版 1.0.3：安装目录错位与模型开关修复

## 已取得的证据

服务器源码目录为 `/opt/private-agent/current`，服务解释器为 `/opt/private-agent/venv/bin/python`。使用服务账号、进程环境和工作目录启动检查后，Python 将应用解析到：

```text
/opt/private-agent/venv/lib/python3.12/site-packages/personal_assistant
```

这个安装副本缺少 `api/routes_admin_logs.py`、`api/routes_desktop_model.py` 和 `core/admin_logs.py`，也没有两个新增路由的注册；同一环境加载的 `coding_permission_models_enabled` 为 `false`。源码目录的功能补丁没有同步到实际安装副本，能够解释日志 404 和模型能力关闭。日志读取权限不足在当前实现中返回 503，与此次 404 是不同检查项。

运行包的 `config.py`、`main_api.py` 已按服务器输出与历史 Git 内容逐字节摘要比对。它们与当前源码的差异恰好是四个日志路径配置和两个路由的导入、注册，不需要整体重装应用。服务器源码中 `main_api.py` 的 import 排序与当前版本不同，但运行逻辑相同。

此外，用真实 `ModelProfile` 对象替代测试替身，复现了模型代理访问不存在的 `reasoning_efforts` 属性而报 `AttributeError`。正确字段是 `reasoning_efforts_json`。修复工具会在待安装的模型代理副本中应用这一行修复；服务器已有源码文件不被改写。

以上是源码与新检查进程的证据，不是对原服务进程内存的直接观测；修复后的真实账号日志读取、模型调用仍须验收。

## 修复范围及取舍

本次使用 [repair-connected-runtime.py](../scripts/repair-connected-runtime.py) 对已核对的五个运行包文件做定向修复。

- 不修改 Git 工作区、分支、`alembic/env.py`、数据库、依赖、Nginx 或日志权限。
- 不切换 `PYTHONPATH` 或 editable 安装；这些方案会改变整个应用的加载来源，可能使未核对文件参与运行。
- 不整体重装 wheel；这可能覆盖安装副本中的其他服务器修复。后续正式发布应统一源码、构建包和安装副本。
- 这是有备份和摘要清单的运行包应急补丁，不更新 wheel 的 `dist-info/RECORD`，不能将其宣称为干净重新构建的发行包。后续重装应用可能覆盖此补丁，应使用已包含这些改动的构建版本。
- 只需开启 `PA_CODING_PERMISSION_MODELS_ENABLED`。远程客户端的 `/capabilities` 来自本机执行器，不需要顺带开启云端 `PA_CODING_AGENT_UI_ENABLED` 或其他功能开关。

固定写入目标均在上述 `site-packages/personal_assistant` 下：

```text
config.py
main_api.py
api/routes_admin_logs.py
api/routes_desktop_model.py
core/admin_logs.py
```

目标或来源存在未知摘要时，工具停止而不覆盖；仅在 Supervisor 明确报告 `private-agent STOPPED` 时允许应用或回滚。源码只读，备份仅含运行包源码和权限、摘要清单，默认保存在服务器 `/opt/private-agent/rollback-connected-runtime-1.0.3`，目录权限为 0700。后续修复可用 `--backup-dir` 指定 `/opt/private-agent` 下的独立一级绝对目录，保留旧备份；不接受链接、源码或安装目录及其上级目录。

## 在 FinalShell 中执行

先结束客户端正在执行的任务，并确认服务器现有受控数据备份可用。下面操作会短暂停止应用服务。服务入口在启动时仍执行其已有的 Alembic 检查；本补丁没有带入新迁移，也没有绕过迁移检查。服务内存中的供应商 API Key 可能在重启后丢失，届时应由用户在客户端重新保存，不导出密钥。

将 `scripts/repair-connected-runtime.py` 上传到服务器 `/tmp/repair-connected-runtime.py`。以下命令在当前 root 会话执行；任一步失败都不要继续下一步。

### 1. 在线只读预检

```bash
/opt/private-agent/venv/bin/python -I -B -X utf8 /tmp/repair-connected-runtime.py check
```

应返回 `CHECK_PASSED` 和五个固定文件的变更状态。该步骤不停止服务、不创建备份、不修改文件。如果提示摘要不匹配，保留输出供进一步核对，不修改工具中的摘要来绕过检查。

### 2. 停止单个服务，应用已核对的补丁

```bash
supervisorctl -c /etc/supervisord.conf stop private-agent
/opt/private-agent/venv/bin/python -I -B -X utf8 /tmp/repair-connected-runtime.py apply
```

必须看到 `APPLIED_AND_VERIFIED`；如果已完整应用，则返回 `ALREADY_APPLIED`。备份目录已存在而目标又需要变更时会拒绝，不能删除旧备份重试。中途失败可能使服务保持停止，按下面的回滚说明处理，不启动未知状态的包。

### 3. 仅开启模型配置能力

在 FinalShell 文件编辑器中编辑服务器现有的 `/etc/supervisord.d/private-agent.ini`，定位 `[program:private-agent]` 的现有 `environment=` 项：

- 没有 `PA_CODING_PERMISSION_MODELS_ENABLED` 时，在现有逗号分隔列表末尾追加 `,PA_CODING_PERMISSION_MODELS_ENABLED="true"`。
- 已存在该项时，只把该项的值改为 `"true"`，不要追加重名键。
- 保留所有其他项，特别是 `PA_PARENT_PID`、日志路径、账号和秘密文件引用；不要新增第二个 `environment=`，也不要用一行示例覆盖整个原有配置。
- 记录此项原先是否存在及其值，回滚只撤销这一项。不要将配置全文、密码或令牌贴到聊天中。

此步骤只改部署配置，不能在源码 `config.py` 中把全局默认值改为 true。

### 4. 重新加载此程序并检查状态

```bash
supervisorctl -c /etc/supervisord.conf reread
supervisorctl -c /etc/supervisord.conf update private-agent
supervisorctl -c /etc/supervisord.conf status private-agent
```

不要执行 `update all` 或 `restart all`。`update private-agent` 在该程序配置变化时会启动它；若状态仍为 `STOPPED`，再执行：

```bash
supervisorctl -c /etc/supervisord.conf start private-agent
supervisorctl -c /etc/supervisord.conf status private-agent
```

`STARTING` 还不代表稳定运行，应稍后再次查询确认 `RUNNING`。遇到 `BACKOFF`、`FATAL` 或报错先停止推进，不输出生产日志全文。

## 验收与边界

1. 重新打开管理员日志页：不再返回“日志接口尚未上线”。分别检查四个来源；若变成 503 的不可读提示，应按具体路径与服务账号检查日志权限，本补丁不自动放宽权限。
2. 打开 Coding 模型页：不再显示“模型能力未开启”。若出现“尚无 Coding 模型”，在当前账号配置或导入启用的模型 profile；不要把其他账号的配置当作共享配置。
3. 如重启丢失供应商 Key，在客户端安全配置页面重新保存。以无敏感内容的测试目录和提示词验证真实模型调用、允许的推理强度以及日志读取；实际模型请求可能产生供应商费用。
4. 本次不验收在线更新、日志轮转后的权限保持或发布新安装包。它们必须另行验证，不能从 `RUNNING` 或匿名 401 推断通过。

## 回滚

仅在确需恢复时使用。先停止单个服务，然后回滚运行包：

```bash
supervisorctl -c /etc/supervisord.conf stop private-agent
/opt/private-agent/venv/bin/python -I -B -X utf8 /tmp/repair-connected-runtime.py rollback
```

必须看到 `ROLLED_BACK_AND_VERIFIED`。工具允许恢复中途失败的写入，但目标有后续未知改动、备份损坏或清单被更改时拒绝覆盖。没有完整备份清单时工具不会开始包写入；不要手工删除文件或强行回滚。

若第 3 步已修改模型开关，在现有 `environment=` 项中仅恢复该键的原值，或在原先不存在时移除该键。按第 4 步重新加载此程序；如配置未改变且仍为 `STOPPED`，执行 `start private-agent`。不回滚数据库，不覆盖其他配置。

## 1.0.4 修复复用：拉取源码后同步运行包

本节用于包含 HTTP 502 和管理员时间修复的 1.0.4 客户端配套更新，不代表服务器已应用过 1.0.3 补丁。用户应先在 `/opt/private-agent/current` 核对分支及本地修改，再拉取 `dev/1.0.0` 的最新代码；拉取报错或冲突时停止，保留现有服务器修改，不执行 `reset --hard`、`clean` 或删除冲突文件。

**只拉取源码并重启不保证生效。** 历史检查发现服务加载的是 `site-packages` 安装副本；下面只对已知的五个文件同步，不整体重装应用。新版客户端还必须安装到用户电脑，才能更新工具定义、本机错误提示和管理员上海时间显示。

使用仓库中本次更新后的工具，不继续使用 `/tmp` 中可能残留的旧脚本。先执行在线只读预检：

```bash
/opt/private-agent/venv/bin/python -I -B -X utf8 /opt/private-agent/current/scripts/repair-connected-runtime.py check --backup-dir /opt/private-agent/rollback-connected-runtime-1.0.4
```

必须看到 `CHECK_PASSED`。工具接受已核对的旧包、旧字段修复版及本次模型代理摘要；任何来源或安装副本摘要未知、链接路径、权限异常都必须停止，不能修改白名单摘要绕过。预检不证明模型配置正确或真实请求成功。

若任一文件 `change` 为 `true`，确认 `/opt/private-agent/rollback-connected-runtime-1.0.4` 尚不存在，再结束客户端任务，确认现有受控数据备份可用，并逐条执行：

```bash
test ! -e /opt/private-agent/rollback-connected-runtime-1.0.4
supervisorctl -c /etc/supervisord.conf stop private-agent
/opt/private-agent/venv/bin/python -I -B -X utf8 /opt/private-agent/current/scripts/repair-connected-runtime.py apply --backup-dir /opt/private-agent/rollback-connected-runtime-1.0.4
```

任一步失败都不执行下一步。旧的 1.0.3 备份原样保留；若新的备份目录已经存在而目标仍需更新，应先核对该目录属于哪次操作，不能删除或覆盖它。需再次更新时，选另一个尚不存在的独立目录，并在应用和回滚时使用同一目录。

取得 `APPLIED_AND_VERIFIED` 或 `ALREADY_APPLIED` 后，核对本说明第 3 步的必要模型开关：已启用时保留，不重复添加。配置有变更时按第 4 步重新加载；配置未变更且服务已停止时，只执行：

```bash
supervisorctl -c /etc/supervisord.conf start private-agent
supervisorctl -c /etc/supervisord.conf status private-agent
```

稍后再次确认稳定为 `RUNNING`。若预检五个文件全为 `change: false`，无须重复应用或为此停服；仍需确认当前服务是否已在上次安装包更新后重启，并完成真实账号验收。检查模型 profile 与 Key；重启后内存 Key 可能需要在客户端安全配置页重新保存。

若本次应用失败且需要回滚，保持服务停止，使用**本次**备份路径：

```bash
/opt/private-agent/venv/bin/python -I -B -X utf8 /opt/private-agent/current/scripts/repair-connected-runtime.py rollback --backup-dir /opt/private-agent/rollback-connected-runtime-1.0.4
```

必须看到 `ROLLED_BACK_AND_VERIFIED` 后才按前述配置和启动流程恢复。该回滚恢复的是本次更新前的包，不会删除旧备份；不能直接使用默认的 1.0.3 备份跨版本回滚。没有完整备份、备份损坏或目标已有未知后续修改时保持停止，先核对原因，不强行启动。

## 本机验证记录

以下前四项为最初 1.0.3 修复阶段的记录；1.0.4 的补充回归在其后单独列出。

- 替换测试替身后，旧模型代理确实因不存在的字段而失败；修复后支持的强度正常通过，不支持或未声明的强度返回 422。
- 运行包正常更新、重复执行、未知来源与目标拒绝、旧代理字段迁移、模拟磁盘写入失败后的回滚、后续改动拒绝回滚、备份篡改拒绝、服务未停止拒绝均已验证。
- 相关五组隔离 pytest：45 passed、1 skipped；跳过项为 Windows 无权限创建真实符号链接的既有测试。
- 相关 Ruff 与 `git diff --check` 通过。测试不连接生产，也没有从本机执行服务器修复。

2026-08-31 的 1.0.4 补充验证：新增默认 CLI 兼容、新旧备份共存升级与回滚、危险备份路径拒绝用例。八组隔离回归合计 **127 passed、2 skipped**；两个跳过项均为当前 Windows 用户无权创建真实符号链接。Ruff 和差异格式检查通过。命令、构建与上传证据见[1.0.4 交付记录](./releases/remote-v1.0.4-test.1-20260831.md)。没有在生产运行本脚本，也未验证 Linux 上的实际服务状态和文件权限。

诊断脚本 v1/v2 将 `PYTHONINSPECT` 设为非空字符串 `"0"`，会开启 Python 的交互检查，因而在终端会话中可能出现“已经输出完整结果，随后等到超时”。本机终端测试已复现这一现象；移除该变量并将子进程 stdin 设为 DEVNULL 后正常退出，本机 v3 已修正。非交互管道下的测试不能复现此问题，因此此前的本机检查遗漏了这一点。无需因退出超时否定之前已取得的完整模块和配置结果。依据：[Python 3.12 的 PYTHONINSPECT 说明](https://docs.python.org/3.12/using/cmdline.html#envvar-PYTHONINSPECT)。
