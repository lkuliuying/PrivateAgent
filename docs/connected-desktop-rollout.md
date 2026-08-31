# 联网客户端 1.0.3：服务端部署与第二台电脑验收

本次目标是：账号和模型由服务器提供，项目文件、文件修改和命令执行留在用户电脑；管理员可在「系统 → 用户 → 日志」中查看指定服务日志。

**状态（2026-08-30 21:56，Asia/Shanghai）：服务端补丁已部署，4 个日志来源已接入，应用恢复 RUNNING；第二台电脑尚未验收，1.0.3 尚未发布。** 用户已通过临时 SSH 公钥授权本次部署。下面第 2–4 节是已执行的部署流程，不要在当前服务器重复应用；现在应从第 5 节进行异机验收。Nginx 日志轮转方式仍待确认，尚未验证轮转后 ACL 保留。密码、令牌、环境文件和配置全文不要贴到聊天或上传 GitHub。

**后续交接更新（2026-08-30）：** 用户已在另一台电脑安装测试包并反馈“模型能力不可用”，根因未确认。源码、测试及工作流改动已整理到 `dev/1.0.0`，详见 [接手提示词](./next-agent-handoff-1.0.3.md)。此次仅提交、推送和更新文档，没有重新部署或发布；旧测试草稿仍指向 `debcd81`，不能仅因开发分支有新工作流就认定旧草稿发布时也会采用它。

下面压缩包摘要及服务器验证描述的是当时实际部署的归档。提交前静态检查只调整了 `main_api.py` 中新增接口的一行 import 顺序，因此当前源码与旧归档该文件的字节摘要不同，运行逻辑未变。后续重新生成补丁必须使用新清单和新摘要，不能套用下面旧归档的摘要或对当前服务器重复执行首次部署步骤。

## 1. 准备材料与维护窗口

本机文件：

- 后端补丁包：`.run/connected-rollout-1.0.3/private-agent-backend-1.0.3-20260830.tar.gz`
- 补丁包 SHA256：`40b0fbc21fd585d388f539c92eb2a08a502cfa9c2831ed36e85c407e0d0141fb`
- 测试安装包：`.run/remote-client-5DJM8U/PrivateAgentRemote_1.0.3_x64-setup.exe`
- 测试安装包 SHA256：`f8409dc1b80590b3ee707e9f25a8e32749bf4e113d63c52757cbc84ccfe3fb2f`

测试安装包没有 Windows Authenticode 签名，也没有 Tauri 更新签名；只能用于安装和功能联调，不能直接放入在线更新源。不需要另一台电脑安装 Python、MySQL 或本地模型。项目自身的 npm、pytest 等开发工具仍由用户项目环境提供。

先结束运行中的任务，安排一次后端短暂停机，并确认既有受控备份可恢复。此次补丁不读写数据库、不包含迁移和依赖升级；现有服务入口启动时仍会自动检查 Alembic，请先核对服务器没有待应用的其他迁移。**模型供应商密钥如果只在服务内存里，重启后管理员需要在客户端重新输入保存。** 不要导出密钥来做此项部署。

补丁只包含以下 5 个源码文件的差异，另有清单和只读校验工具：

```text
src/personal_assistant/config.py
src/personal_assistant/main_api.py
src/personal_assistant/api/routes_admin_logs.py
src/personal_assistant/api/routes_desktop_model.py
src/personal_assistant/core/admin_logs.py
```

基线为 `debcd81d9b6084f8ab13f4c0423b9f14696b9496` 中的前两个文件；后三个文件在部署前必须不存在。服务器其他文件可以有本地改动，尤其不要覆盖 `alembic/env.py`。若源码校验不匹配，停止并重新比对这 5 个文件，不能跳过校验、强制拉取或重置仓库。

## 2. 上传并校验后端包

将上述压缩包上传到服务器 `/tmp/private-agent-backend-1.0.3-20260830.tar.gz`。可以用已有 SFTP 工具；先确认同名文件不存在。若用 Windows PowerShell，在仓库根目录将 `<API域名>` 换为部署域名，密码只在 SSH 的交互提示中输入：

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" -o StrictHostKeyChecking=yes -o UserKnownHostsFile=F:/Program/Agent/.run/connected-rollout-1.0.3/known_hosts .run/connected-rollout-1.0.3/private-agent-backend-1.0.3-20260830.tar.gz root@<API域名>:/tmp/private-agent-backend-1.0.3-20260830.tar.gz
```

上面的主机公钥记录只适用于本次已经核对过的部署域名。换服务器时重新通过可信渠道核对指纹，不关闭主机验证。

服务器 root 终端执行以下校验和解包。每段命令遇错停止，**不要接着执行下一段**。目录已存在时不要覆盖或删除，先确认是否已部署过：

```bash
(
set -eu
cd /tmp
printf '%s\n' '40b0fbc21fd585d388f539c92eb2a08a502cfa9c2831ed36e85c407e0d0141fb  private-agent-backend-1.0.3-20260830.tar.gz' | sha256sum -c -
mkdir /tmp/private-agent-backend-1.0.3
tar --no-same-owner --no-same-permissions -xzf private-agent-backend-1.0.3-20260830.tar.gz -C /tmp/private-agent-backend-1.0.3
chmod 755 /tmp/private-agent-backend-1.0.3
chmod 644 /tmp/private-agent-backend-1.0.3/backend.patch /tmp/private-agent-backend-1.0.3/backend_tool.py /tmp/private-agent-backend-1.0.3/manifest.json
)
```

确认实际服务目录、虚拟环境和程序名；下面路径与本次交接一致，但仍要以服务器当前结果为准。不要输出 Supervisor 的 `environment=` 或 Nginx 配置全文：

```bash
supervisorctl -c /etc/supervisord.conf status
grep -nE '^\[program:|^[[:space:]]*(user|directory|stdout_logfile|stderr_logfile)[[:space:]]*=' /etc/supervisord.d/private-agent.ini
runuser -u privateagent -- git -C /opt/private-agent/current status --short
/opt/private-agent/venv/bin/python --version
```

预检只读取 5 个源码文件、检查摘要和 Python 语法，不加载应用配置、不连接数据库：

```bash
(
set -eu
runuser -u privateagent -- /opt/private-agent/venv/bin/python -B /tmp/private-agent-backend-1.0.3/backend_tool.py verify --root /opt/private-agent/current --state before
runuser -u privateagent -- git -C /opt/private-agent/current apply --check /tmp/private-agent-backend-1.0.3/backend.patch
)
```

必须看到 `PASS: 5 ... before`，且 `git apply --check` 无报错。若提示 `dubious ownership`，先核对目录所有者与服务账号；不要改用 root 直接操作仓库或设置全局 `safe.directory=*`。

## 3. 核对日志路径并授予只读权限

只输出日志和代理相关指令，用于确认真实路径；下列宝塔路径不存在时停止，找到当前 Nginx 的实际配置再操作。不要用 `nginx -T` 或 `cat` 整份配置：

```bash
grep -nE '^[[:space:]]*(logfile|stdout_logfile|stderr_logfile)[[:space:]]*=' /etc/supervisord.conf /etc/supervisord.d/private-agent.ini
grep -nE '^[[:space:]]*(access_log|error_log|proxy_pass|proxy_read_timeout|proxy_send_timeout)[[:space:]]' /www/server/nginx/conf/nginx.conf /www/server/panel/vhost/nginx/private-agent.conf
command -v getfacl
command -v setfacl
```

配置可能有继承和 include，`access_log off`、syslog、相对路径不能直接当作文件路径。确认本应用的实际普通文件，并按照下表对应；不要把其他站点或秘密文件配置进来。

| 服务端设置 | 用途 | 代码默认路径 |
|---|---|---|
| `PA_ADMIN_SUPERVISOR_LOG` | 应用 stdout/stderr | `/var/log/private-agent/supervisor.log` |
| `PA_ADMIN_SUPERVISORD_LOG` | Supervisor 自身日志 | `/var/log/supervisord.log` |
| `PA_ADMIN_NGINX_ACCESS_LOG` | 此站点访问日志 | `/var/log/nginx/private-agent-access.log` |
| `PA_ADMIN_NGINX_ERROR_LOG` | 此站点错误日志 | `/var/log/nginx/private-agent-error.log` |

实际路径不同：管理员在现有 Supervisor `[program:实际程序名]` 的 `environment=` 中追加这 4 个非秘密路径设置，保留所有原有项，尤其 `PA_PARENT_PID="1"`。不要新增第二个 `environment=` 来覆盖原值，不复制或上传原配置，不更改环境文件。默认路径正确则无需加设置。先完成下面权限检查，再在第 4 步的停机窗口中保存配置并定向更新该程序。

每个实际日志文件分别执行下段，将路径占位符换成真实绝对路径。仅授予指定文件读取权限；若缺少 `setfacl`，停止并由管理员处理 ACL 工具安装，不改成 777：

```bash
(
set -eu
PA_LOG='/替换为实际日志绝对路径'
test -f "$PA_LOG"
test ! -L "$PA_LOG"
namei -l "$PA_LOG"
getfacl -p "$PA_LOG"
setfacl -m u:privateagent:r-- "$PA_LOG"
runuser -u privateagent -- test -r "$PA_LOG"
)
```

执行前记录该文件原有 ACL，回滚时恢复原值。`namei` 显示缺少父目录遍历权限时，只对缺少权限的具体父目录增加 `u:privateagent:--x`，然后重试读取检查；不要递归授权整个 `/var/log` 或 `/www`。不让应用以 root 运行，也不授予日志写权限。日志源拒绝符号链接，包括路径中间的链接，应使用真实规范路径。

**轮转必须另验收：** 单次文件 ACL 不保证新日志权限继承。沿用现有 logrotate、宝塔或 Supervisor 轮转机制，在其已有轮转流程中对这 4 个新日志文件恢复同样的只读 ACL，再用 `runuser ... test -r` 检查。不要创建第二套竞争的轮转规则；不要给共享 `/www/wwwlogs` 或 `/var/log` 设置默认 ACL，否则其他站点的新日志也会暴露。Supervisor 自身的文件轮转也要覆盖。未确认轮转后可读时，不应标记日志接入完成。

新接口沿用已有 HTTPS API 代理，通常不需要新增 Nginx location。模型调用上限 180 秒，核对生效的 `proxy_read_timeout` 至少为 190 秒、请求体限制至少允许 2 MB；已有配置满足则不改。确需修改时仅改此站点，先用现有 Nginx 二进制 `-t` 成功，再按原管理方式 reload，不重启整台服务器或另装 Nginx。

## 4. 停止单个应用、应用补丁、启动验证

以下示例假定第 2 步确认程序名是 `private-agent`；不同则只替换程序名。不要运行 `restart all`。先停止，再复核源码，避免预检之后又有别人改动。备份只包含两个校验通过的旧源码，不包含任何运行配置、数据库或秘密文件。

```bash
(
set -eu
supervisorctl -c /etc/supervisord.conf stop private-agent
runuser -u privateagent -- /opt/private-agent/venv/bin/python -B /tmp/private-agent-backend-1.0.3/backend_tool.py verify --root /opt/private-agent/current --state before
mkdir -m 700 /opt/private-agent/rollback-connected-1.0.3
tar -czf /opt/private-agent/rollback-connected-1.0.3/source-before.tar.gz -C /opt/private-agent/current src/personal_assistant/config.py src/personal_assistant/main_api.py
runuser -u privateagent -- git -C /opt/private-agent/current apply --check /tmp/private-agent-backend-1.0.3/backend.patch
runuser -u privateagent -- git -C /opt/private-agent/current apply /tmp/private-agent-backend-1.0.3/backend.patch
runuser -u privateagent -- /opt/private-agent/venv/bin/python -B /tmp/private-agent-backend-1.0.3/backend_tool.py verify --root /opt/private-agent/current --state after
)
```

必须看到 `PASS: 5 ... after`。若此段失败，应用可能已停止；不要直接启动未知状态的代码。用校验工具检查 `before` / `after` 哪个状态成立；前者可启动旧服务，后者按下面启动；两者都不成立时暂停并核对，不强制覆盖。

没有修改 Supervisor 配置时：

```bash
supervisorctl -c /etc/supervisord.conf start private-agent
supervisorctl -c /etc/supervisord.conf status private-agent
```

如果追加了日志路径设置，停机期间保存后改为：先 `supervisorctl -c /etc/supervisord.conf reread`，确认只涉及本应用，再 `supervisorctl -c /etc/supervisord.conf update private-agent`。它可能自动启动该程序；用 `status private-agent` 确认，仍为 STOPPED 时再 `start private-agent`。不要更新所有程序。

等待进入 RUNNING，用实际域名检查匿名鉴权边界：

```bash
curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' https://<API域名>/health
curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' https://<API域名>/admin/logs
```

均应返回 401。**401 只说明鉴权边界在线，不能证明新路由或模型调用成功**；必须继续第 5 步使用真实账号验收。不要将登录密码或令牌写入 curl 参数。若服务启动失败，在服务器本地查看日志排障，分享信息前脱敏，不粘贴日志全文。

回滚仅在确需恢复旧后端时执行，先停止该程序、验证当前仍是完整 `after` 状态，再 `git apply --reverse --check`、`git apply --reverse` 同一补丁，最后验证 `before` 并启动。反向补丁只撤销这 5 个源码变更（包括删除此次新增的 3 个文件）；任何后续修改都会使前置校验失败。不要用 `git reset --hard`、`git clean` 或数据库 downgrade。源码回滚不会自动撤销 ACL 或 Supervisor 设置；按第 3 步记录逐项还原必要项，不覆盖整份配置。

## 5. 第二台 Windows 电脑真实联调

复制完整 `PrivateAgentRemote_1.0.3_x64-setup.exe` 到第二台电脑，先 `Get-FileHash -Algorithm SHA256` 与第 1 节对比。安装到远程版，启动新快捷方式，不运行以前单独复制的 EXE。未签名测试包可能被 Windows 提醒；不要关闭安全软件或跳过组织策略。

逐项记录实际结果，任何关键项失败都暂停发布：

| 检查 | 通过标准 |
|---|---|
| 版本和身份 | 显示远程版 1.0.3，可使用服务器现有普通账号登录 |
| 本地项目 | 在此电脑桌面新建测试目录及 `hello.txt`，选择该目录创建项目成功，无 HTTP 422 |
| 真实模型 | 让模型读取 `hello.txt` 中的测试文字并回答，服务器完成推理；不要使用敏感源码测试 |
| 审批写入 | 要求修改该文件，批准后只有这台电脑对应文件发生变化；拒绝时文件不变 |
| 过期审批 | 等待审批时在本机手改文件，再批准，客户端拒绝覆盖已变化内容 |
| 取消与重启 | 取消任务后不继续修改文件；退出并重开客户端，项目和本地历史仍在 |
| 账号隔离 | 退出并换另一个账号，不能看到前一账号本地项目和历史 |
| 管理员日志 | 管理员左侧有独立日志模块，4 个来源能读取；轮转一次后依然可读 |
| 普通用户权限 | 普通账号看不到日志模块；用该账号在受控接口测试中访问 `/admin/logs` 应为 403 |
| 本地命令（具备项目环境时） | 固定测试命令需批准，在此电脑执行；缺少工具时明确报错，不转交 Linux 服务器执行 |
| 旧客户端兼容 | 原 1.0.2 仍可登录、使用原有服务器功能，普通本地版安装不受影响 |

通过标准还包括：服务器不因该客户端任务创建对应服务器项目或工作目录。可用管理员的既有管理视图对比，不能只凭界面显示本地路径判断。文件不会自动同步到其他电脑；为调用模型而需要的代码片段和工具输出会发送服务器/模型提供商，文件保存在本地不代表完全离线。

记录不包含密码、令牌或项目源码。建议只提供：Windows 版本、安装包 SHA256、客户端版本、各项通过/失败、错误提示、脱敏截图和测试时间。第二台电脑若不在自动化可访问范围内，需要操作者实际完成，不能用本机单元测试替代。

## 6. 验收通过后再制作升级包和发布

1. 本功能源码与交接已分批提交到 `dev/1.0.0`。完成后续模型修复后，重新审核并提交该修复涉及的源码和测试，保留其他改动，不使用 `git add .`。不要提交 `.run`、环境文件、服务配置、日志或签名材料。记录实际待发布提交；构建要求干净工作区，不绕过检查。
2. 使用已有受控签名环境，从该提交执行：

   ```powershell
   .\scripts\build-remote-client.cmd "https://<API域名>" --release --version 1.0.3
   ```

   Windows 正式证书尚未到位，可以继续没有 Authenticode；但 **Tauri 更新签名 `.sig` 和验签必须成功**。沿用原更新公钥，不更换密钥，不复用旧包签名，不把密钥写进命令、聊天或仓库。发布包重建后 SHA256 会改变，不能沿用第 1 节的测试包摘要。
3. 在隔离测试更新地址完成旧远程安装版到新包的「检查更新 → 下载 → 验签 → 安装 → 重启」真实验收。测试源与正式 `/updates/remote/latest.json` 分开；测试客户端需要在构建时用 `--update-url` 指向该地址，不能把未经验收的清单先覆盖正式渠道。核对新增的本地执行器随更新安装，账号登录、创建本地项目和日志功能仍正常。测试专用地址的安装包不能当正式地址安装包发布；最终生产地址构建也要重新安装验证。
4. 将最终 `publish/1.0.3/` 中的 EXE 与 `.sig` 上传到现有更新根目录 `/var/www/private-agent-updates/remote/1.0.3/`，首次创建后保持不可变。通过 HTTPS 下载核对新包摘要，确认清单平台键为 `remote-windows-x86_64`、版本和签名对应。保留旧包与旧清单，最后原子替换 `latest.json`。**不要重跑以前只供 1.0.2 初次建站的一次性部署脚本。**
5. 创建 `remote-v1.0.3`，指向与 `build-info.json` 相同的已推送提交；可以先建 GitHub 草稿，验收通过后发布。只上传最终安装包、对应 `.sig` 和公开校验文件，不能上传整个输出目录。本次 SignPath 工作流的 `remote-v*` 排除条件已随开发分支提交，发布标签必须包含该改动；远程版不运行普通版构建。GitHub 的 release 事件使用发布标签对应的提交，参见 [GitHub release 事件说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#release)；条件使用 [startsWith](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#startswith)。
6. 远程 Release 标记 `latest=false`，发布后再核对普通版 Latest 没有变化。此前普通版为 `v0.2.1`，操作前重新查询；若 GitHub 自动选择了远程版，应将原普通版重新标记 Latest，不能让普通客户端收到远程包。

第 3 步是真实在线升级验收，第 5 节是本地执行和服务端联调验收，两者都要记录。仅安装预览包成功，不代表检查更新链路已通过。

## 7. 本次已完成的验证与范围

- `test_connected_backend_bundle.py`：6 项通过；实际在临时 Git 工作树应用补丁，校验前后摘要，验证服务器其他源码不变、冲突拒绝、损坏拒绝、已有产物不覆盖、反向补丁可应用。
- 部署工具及其测试的 Ruff、`git diff --check` 通过；工作流 YAML 及远程标签排除条件结构检查通过（未在 GitHub 实际触发）。指南 8 段 Bash 命令经过 `bash -n` 语法检查，没有执行服务器命令。
- 最终压缩包 SHA256、3 个归档成员、5 个源码部署后摘要与随包校验工具一致性检查通过；安装包 SHA256 已重新核对。
- 应用本身上一阶段验证为前端 196 项通过、后端 27 项通过 / 1 项 Windows 符号链接权限跳过、打包入口 8 项通过、完整预览安装包构建及独立本地执行器启动检查通过；详见 [本机执行实现记录](./connected-desktop-local-execution.md)。
- 服务器实际部署后：5 文件后置摘要和语法校验通过；目标 Supervisor 程序持续 RUNNING；原 `alembic/env.py` 与 Nginx 代理配置摘要未变；数据库仍为 `0038`，未完成 Agent 任务数为 0。
- 两个 Nginx 日志已精确授予应用账号只读 ACL，读取为 true、写入为 false；Supervisor 两个日志沿用原有读取权限。运行进程的 4 个日志路径设置已核对。
- 以 Linux 非 root 应用账号运行独立检查：4 个真实日志可读、真实符号链接拒绝、无读取权限文件拒绝、测试文本脱敏、独立路由权限与 no-store、数据库版本，共 6 组检查通过。服务器没有 pytest，未安装新依赖；独立路由测试使用模拟身份，不是生产账号登录验收，日志正文没有输出或导出。
- 公网匿名 `/health`、`/admin/logs`、`POST /desktop/model/complete` 返回 401；两个新接口的桌面来源 CORS 预检为 200。尚未使用生产账号完成日志界面、真实模型及第二台电脑测试；尚未执行真实日志轮转与在线升级验收。
- 当前服务端采用定向补丁，Git HEAD 仍是部署前提交，工作树仅有这 5 个源码变更；未提交、推送或强制拉取。后续更新仓库时应先核对补丁与目标提交，不能直接丢弃这些改动。

本次部署工具测试的实际命令如下。工作目录使用不含环境文件的 `.run/admin-logs-verification`，测试临时目录每次换一个未使用的名字：

```powershell
& 'F:\Program\Agent\.venv\Scripts\python.exe' -X utf8 -B -m pytest F:\Program\Agent\tests\unit\test_connected_backend_bundle.py --noconftest -p no:cacheprovider --basetemp F:\Program\Agent\.run\connected-bundle-test-20260830-a -q
```

仓库根目录执行的静态检查：

```powershell
.\.venv\Scripts\ruff.exe check scripts/prepare-connected-backend.py tests/unit/test_connected_backend_bundle.py
git diff --check
```

重新生成部署包（生成文件已存在时会拒绝覆盖）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B scripts/prepare-connected-backend.py build --output .run/connected-rollout-1.0.3/backend-new.tar.gz
```

重新生成后必须使用工具输出的新 SHA256，不能复用本文固定包的校验值。
