# S5 阻断项补充验收

> 后续收尾已完成普通 ConPTY 修复、真实桌面协作组合、真实符号链接和前台 p95 复测，全部适用门禁通过，可进入 S6。最新证据见 [S5 剩余门禁验收记录](./s5-remaining-gates-validation-report.md)。本文保留上一轮完整事实，以下 343/2/0、未放行结论和候选摘要均按当时日期及环境解释，不替代最终记录。

日期：2026-09-09。仓库：`F:\Program\Agent`；基线：`dev/1.0.0` / `d0250ee`。接手时保留前轮 S5 未提交改动。本报告用于用户要求的原生隔离、真实 Tauri 恢复流程及安装候选包验收，不启动 S6 评测开发，不包含业务代码推送或部署。用户后续另行授权调整 Nginx 的 HTTP 监听，范围和实际执行状态见下文。

## 状态

本次指定的原生隔离、匹配安装候选，以及真实 Tauri 强退、重启、关联恢复和审查流程已有通过证据。原先两个 strict xfail 已移除，并在实际 Windows AppContainer 中观察到文件、网络正反对照通过。最终源码完整回归为 **343 passed、2 skipped、0 xfail**，包含历史导出、日志失败锁释放与硬链接拒绝修复；两项跳过分别为 ConPTY 环境探针失败和真实符号链接权限不足。当前候选通过完整冻结运行流程、636 个源码文件及 4 个产物摘要核对，并已安装；真实界面验收后再次核对仍匹配。临时模型已保存、使用后删除，重新加载确认删除，回环服务已停止。Nginx HTTP 80 → 8081、HTTPS 443 保留的调整及公网复测已完成。

上述结论只覆盖下文的具体流程，不等于 S5 全部退出项通过。真实桌面追加约束/暂停组合流程、ConPTY 及 UI 延迟等剩余项目仍未全部验收；本次还观察到 Python 大工具目录和 Node 默认入口解析的严格沙箱兼容限制。**仍不放行 S6，不提交或推送 S5，不开展 S6 开发。**

## 原生隔离修复

- `network_policy=none` 必须走 AppContainer。缺少独立身份、旧直接 ACL 接口、allowlist 网络策略或受限 PTY 请求均拒绝；不降级到普通进程。
- Python 授权协调器为每次执行创建唯一 `pa.execution.<uuid>` 身份，只给工作区修改权限和实际解释器/依赖目录读取执行权限。祖先目录不增加授权；系统目录沿用系统权限。
- 运行时拒绝驱动器根、用户根、包含控制目录的工作区、链接/目录联接及超过 50000 项的授权树；可写工作区额外拒绝硬链接文件，防止共享文件 ACL 导致外部文件被授予写权限。只读工具目录保留已安装运行时的硬链接兼容性。第一版不自动下载开发工具；已有工具必须在当前机器可用。
- ACL 读改写使用当前用户的跨进程命名互斥体，避免不同账号数据目录同时修改共享工具目录造成权限丢失。清理仅撤销本次 SID，不用旧 DACL 快照覆盖其他主体的修改。未实际添加 ACE 的失败授权不再次修改该路径。
- 修改 ACL 之前写入清理意图，绑定宿主 PID 与创建时间；正常退出/取消后撤销权限，启动时核对遗留租约。活进程、损坏记录或清理失败均阻止重新授权，不按 PID 数字或超时夺取身份。
- Rust 用挂起态创建 AppContainer 子进程，继承宿主 Job 后恢复；只继承三条标准管道。错误路径释放创建中的句柄，主线程句柄由子进程所有者统一释放。
- Windows 参数使用 CRT 引号/反斜杠规则，已验证引号、尾部反斜杠、空格、中文及子进程转交。受控批处理保持既有独立转义约定。
- 受控 PowerShell 使用指向授权工作区的 `PrivateAgentWorkspace:` PSDrive，避免 FileSystem Provider 因磁盘根不可访问而错误切回 `C:\`。没有扩大磁盘根或祖先目录权限。

AppContainer 的身份、能力及 ACL 交集依据 [Microsoft AppContainer 文档](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)。本轮通过真实父子进程读取令牌，观察 `TokenIsAppContainer=1`、能力数量为 0；实际网络探针只覆盖本机回环 TCP，不冒称已逐一测试所有网络协议。

## 验证口径和过程失败

原生门禁必须先证明允许路径实际执行成功。文件测试在同一进程成功写工作区文件，再观察外部写入 PermissionError；网络测试依次执行获准连接、受限连接、再次获准连接，并核对监听器只收到两次获准数据。这台机器的受限回环连接表现为超时丢弃，不能只凭未输出 CONNECTED 判断通过。

新增测试覆盖独立身份不共享工作区授权、外部读取和写入被拒绝、工具目录不可写、真实子进程继承令牌、参数传递、目录联接拒绝、崩溃日志清理及持续执行会话的受限启动。保留 ConPTY 环境探针失败与符号链接权限不足的独立限制。

过程中发现并保留以下失败证据：

1. 沙箱工具环境缺少用户目录变量，原生启动返回 `ERROR_ENVVAR_NOT_FOUND (203)`。现从 Windows 用户配置目录 API 补齐目录变量，不读取用户配置正文或凭据。
2. 虚拟环境启动器转交实际 Python PID，崩溃测试不能把启动器 PID 当作租约所有者；改为核对创建租约的进程自行输出的 PID、创建时间和退出事实。
3. Low MIC 下的用户目录 Python 无法启动。启动对照改用系统自带 `cmd.exe /d /s /c`，其结论仅为 Low MIC 启动，不代表第三方 Python 在 Low MIC 可用。实际文件和网络隔离使用 AppContainer。
4. 前轮 PowerShell 测试替身未接收新增 `trusted` / `sandbox_directory` 参数；修正签名并断言 workspace 模式保持受限。
5. 旧冻结执行器验收替身仅提供 4096 tokens，无法容纳当前 S2 工具定义；现提供 65536 tokens，保留预算断言。
6. pytest 向祖先目录查找配置触发外部访问拒绝；验收项目自带 `pytest.ini`，将用例放入 `tests`，使用 `testpaths=tests`、`--confcutdir=tests` 和 `--import-mode=importlib`，不放宽沙箱。只设置 `--noconftest` 仍不足以避免 pytest 根收集节点访问父目录属性。这是严格隔离下的工具配置约束，普通项目需要显式限定实际测试目录。
7. PowerShell 默认文件系统盘符初始化失败；通过真实专用 PSDrive 探针定位和修复。尝试祖先目录授权的方案已撤回，失败租约由本次 SID 清理逻辑核对。
8. 旧安装测试要求篡改宿主后的 `output is None`，与 S1 保留参数和结构化失败的契约不一致。现验证 `environment_unavailable`、failed outcome、空退出码且无标准输出；保留宿主摘要篡改负例。探索性的计数脚本会改变工作区并使 S1 要求重新验证，已恢复原来的只输出脚本场景，不修改产品完成验证规则。
9. 历史导出器只接受 schema 0/2/3，导致当前 schema 7 返回 422。这是既有 S2–S5 升级后的实际兼容缺口，本轮为安装验收补上 4–7，保留字段白名单、账号归属与未来版本拒绝。交换包仍是历史记录，不包含可恢复授权或完整 S5 检查点备份。新增当前布局投影、源库不变和未来 schema 拒绝测试；原备份测试的 v2 断言同步为当前 `SCHEMA_VERSION`。
10. 最终审查用隔离临时文件确认：工作区中预先存在的硬链接会让外部同一文件获得写权限，旧候选命令退出码为 0 且 `outside_changed=true`。现授权前扫描可写工作区并拒绝硬链接，回归断言外部文件不变，且没有创建授权日志或锁。修复后重新构建候选，不沿用已通过冻结流程但缺少此修复的上一版。

早期结果：`.run/coding-agent-validation/all-9a1530e0205c4290b04710c1a595d24d` 为 **329 passed、2 failed、2 skipped**，不是最终通过证据；失败为上述 Low MIC 对照及测试替身签名。首轮打包验证失败保留在 `.run/s5-blockers/packaged-validation.log` 和 `packaged-validation-2.log`。

已完成的命令与结果：

| 命令 | 观察结果 |
| --- | --- |
| `.run/s5-blockers/build-host.cmd` | `cargo build --release --locked --manifest-path apps/exec-host/Cargo.toml` 成功。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all` | `.run/coding-agent-validation/all-61134e752a9e44d5abcc97ffbea2cacf`：332 passed、2 skipped，368.90 秒；此结果早于后续历史导出及日志失败锁释放修复。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all 2>&1 \| Tee-Object -FilePath .run/s5-blockers/source-validation-final.log; exit $LASTEXITCODE` | 最终源码完整复跑：`.run/coding-agent-validation/all-71c5a82a9ee54e85bb29db786ce11d4b`，343 passed、2 skipped、0 xfail，259.27 秒，退出码 0。包含历史导出、日志失败锁释放与硬链接拒绝修复；跳过原因为 ConPTY 环境探针失败和真实符号链接权限不足。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite history` | `.run/coding-agent-validation/history-ff001c3a16094525ab59ba989954c84c`：9 passed，0.87 秒。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite sandbox` | `.run/coding-agent-validation/sandbox-180416d6a97748dd828c4ca23f4f8778`：14 passed、1 skipped，50.07 秒；包含日志写失败锁释放与硬链接拒绝。ConPTY 环境探针仍未通过。 |
| `node --test scripts/build-remote-client.test.cjs` | 10 passed。 |
| `node node_modules/vitest/vitest.mjs run src/features/coding/model/runProjector.spec.ts src/features/coding/components/RecoveryPanel.spec.ts` | 在 `apps/desktop` 运行，19 passed。 |
| `node node_modules/@playwright/test/cli.js test e2e/coding-run.spec.ts --grep '恢复\|暂停\|追加\|归属'` | 在 `apps/desktop` 运行，1 passed；是浏览器替身回归，不能代替 Tauri 验收。 |
| `.venv/Scripts/python.exe -m ruff check src/private_agent_local/windows_sandbox.py src/private_agent_local/migration.py tests/unit/test_windows_sandbox.py tests/unit/test_local_history.py scripts/verify-unified-client.py` | All checks passed。 |
| `git diff --check` | 通过；保留 Git 换行规范提示。 |
| `.venv/Scripts/python.exe -B scripts/verify-unified-client.py --bundle .run/unified-client-kCt6U0 --work-dir .run/s5-blockers/packaged-hardened --model-mode openai` | `passed=true`；文件写入、工作区自动批准、命令人工批准、PowerShell、显式 full_access 脚本、上下文用量、篡改宿主拦截及 4 条历史运行导出均通过。固定本机账号/模型替身，没有真实模型调用。日志 `.run/s5-blockers/packaged-validation-hardened.log`，隔离结果目录 `packaged-hardened/packaged-runtime-0k8sc52i`。 |

完整冻结测试复跑入口为 `.venv/Scripts/python.exe -B scripts/verify-unified-client.py --bundle <本次候选目录> --work-dir <新的隔离输出目录> --model-mode openai`。历史失败记录不覆盖。候选 `unified-client-u2x1vV` 已通过完整冻结流程，包括 4 条运行历史导出；它早于硬链接修复，不能作为最终产物。

## 安装产物与真实界面

构建命令：

```powershell
scripts/build-remote-client.cmd --unified --qa --preview-installer --version 1.0.0
```

`--qa` 仅允许统一版未签名预览安装。产品名 `PrivateAgentCandidate`，应用标识 `com.personal-assistant.desktop.candidate`，配置和凭据命名空间独立，不生成更新清单或配置更新端点。安装器为当前用户 NSIS，首轮实际安装目录为 `.run/s5-candidate-install-20260909`。

构建前后核对产品源码文件摘要，产物附带 `source-manifest.json`、`build-info.json` 和 `SHA256SUMS.txt`。Git 未提交状态明确记录 `dirty=true`，不把 HEAD 当作完整源码身份。

首份候选位于 `.run/unified-client-G5UTN7`，已安装并打开真实 `http://tauri.localhost` WebView；它不包含后续修复，不能作为最终匹配候选。中间构建 `unified-client-5AJvCH` 和 `unified-client-u2x1vV` 保留为过程证据。最终候选是 `.run/unified-client-kCt6U0`，构建日志为 `.run/s5-blockers/candidate-build-hardened.log`。

运行 `node .run/s5-blockers/verify-integrity.cjs .run/unified-client-kCt6U0`，实际核对 636 个产品源码文件和以下 4 个产物，均匹配。源码清单摘要为 `f82f47259829e6cb6e1a3cf815dcdd68d3e560cde174e13c7494977248eeeef8`，结果保存在 `.run/s5-blockers/candidate-integrity-hardened.json`。

| 产物 | SHA-256 |
| --- | --- |
| `PrivateAgent-windows-x64.exe` | `dd5279313cc30bbeae6d4de183f20d5629a7c58b03f01a079eaeb16f5c8a67f1` |
| `private-agent-local.exe` | `304f86d734efd06ec51590b3243d2688260fd92e85de995f60624939a947aa51` |
| `exec-host.exe` | `da696b06df5f0876d6307a5fa828be500f7ada9c6fef98a88cfbf80f278d148a` |
| `PrivateAgentCandidate_1.0.0_x64-setup.exe` | `e0e6e4e4d8b4802ce71d20ae40453ede0e69a7e870dc9b60d8b02cb6e3485772` |

安装器未签名，仅用于本机验收，不是正式更新包。构建保留现有 Rust 未使用项及 Vite 包体积警告，没有隐藏或通过升级依赖消除这些警告。

用户授权后的最终安装已完成：`.run/s5-blockers/install-final.ps1` 使用当前候选 NSIS `/S /D=F:\Program\Agent\.run\s5-candidate-install-20260909`，安装器退出码为 0。首次直接对比独立 EXE 与安装 EXE 的摘要失败；随后逐字节核对发现仅 3 个字节从 `__TAURI_BUNDLE_TYPE_VAR_UNK` 改为 `__TAURI_BUNDLE_TYPE_VAR_NSS`。已核对本机依赖 `tauri-utils 2.9.3/src/platform.rs`，这是打包器写入的 NSIS 类型标记，不能据此断定装了旧版本。

`node .run/s5-blockers/verify-installed.cjs` 严格检查唯一标记的精确替换及其余全部字节一致，同时要求执行器、宿主和摘要文件完全相同，结果通过。安装后 `privateagent-candidate.exe` 的 SHA-256 为 `b370e3510a008562b4de70842f4cde6fb5bbe477869598de540243723c2368b0`，证据 `.run/s5-blockers/installed-integrity-final.json`。安装验证当时仅打开登录页，没有将“安装成功”写成“恢复验收通过”；后续真实流程见下文。

验收准备期间曾观察到候选和回环测试进程均已退出，未取得退出原因，不能作为运行中强退证据。已通过 `.run/s5-blockers/launch-final.ps1` 和回环模型入口重新启动；启动脚本保留进程等待句柄记录后续退出码。尚未开始真实运行任务，账号登录由用户完成。

### 登录连接失败诊断

用户随后报告 `Failed to fetch`。检查时最终候选、WebView 调试端口和回环模型均在运行。登录服务源码沿浏览器 `fetch` 访问固定 HTTPS 账号服务，尚未取得可供账号校验的 HTTP 响应；未读取认证字段、令牌或提交登录表单，也未修改代理、证书或服务器配置。

| 实际检查 | 观察结果 |
| --- | --- |
| `node .run/s5-blockers/ui.cjs ./.run/s5-blockers/diagnose-network.cjs` | 在真实 WebView 对 `/health`、`/auth/me` 发起 `credentials: omit` 的匿名 GET，两者均 `Failed to fetch`；CDP 网络错误均为 `net::ERR_CONNECTION_REFUSED`，没有 HTTP 状态码。证据 `.run/s5-blockers/login-network-diagnosis.json`。 |
| `Resolve-DnsName www.liuyingapi.top -Type A` | DNS 返回 A 记录；没有域名解析失败。 |
| `curl.exe --noproxy '*' --head --silent --show-error --max-time 20 https://www.liuyingapi.top/health` | 443 连接失败，curl 错误 7。没有关闭 TLS 证书验证。 |
| `curl.exe --noproxy '*' --head --silent --show-error --connect-timeout 5 --max-time 10 http://www.liuyingapi.top/health` | 80 连接失败，curl 错误 7；仅匿名端口对照，不通过明文登录。 |
| `curl.exe --proxy http://127.0.0.1:10808 --head --silent --show-error --connect-timeout 5 --max-time 15 https://www.liuyingapi.top/health` | 现有代理建立隧道后 TLS 握手失败，curl 错误 35。 |
| `curl.exe --head --silent --show-error --max-time 15 https://www.microsoft.com` | HTTPS 对照返回 200，不能归结为全部 HTTPS 断网。 |

最初结论只限于本机已测网络路径：账号域名入口无法连接，不能归因于账号密码或 S5 尚未提交，也不能仅凭这些结果断言 Nginx、后端进程或防火墙的具体状态。当时已请求服务器侧 `systemctl is-active nginx`、`ss -lntp '( sport = :80 or sport = :443 )'`、`supervisorctl -c /etc/supervisord.conf status private-agent` 三项只读回执；后续 Nginx 与监听回执见下一节，后端状态仍待确认。

### Nginx HTTP 监听调整

用户说明 80 端口已有其他服务使用，并明确选择仅将 Nginx 的 HTTP 80 监听改为 8081，保留 HTTPS 443。客户端继续使用原 HTTPS 账号服务地址；不修改后端 8000 端口、TLS 证书或业务代码。

仓库的 `deploy/centos-stream9/private-agent.nginx.conf` 是 `agent.example.com:6000` 的历史模板，不是服务器实际配置。历史运维文档提到宝塔配置路径，后续用户回执确认了实际入口和监听位置；不能用历史模板覆盖线上配置或全局替换数字 `80`。

| 实际检查 | 观察结果 |
| --- | --- |
| `ssh -n -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=8 root@43.163.232.238 'command -v nginx'` | 首次 SSH 主机密钥校验失败：`REMOTE HOST IDENTIFICATION HAS CHANGED`、`Host key verification failed`，未执行远程命令。用户随后通过云厂商服务器控制台返回 ED25519 公开指纹，与服务端收到的指纹一致。 |
| `ssh-keyscan -T 8 -t ed25519 43.163.232.238`，随后在本机计算公钥 SHA-256 并与用户控制台指纹精确比较 | 核对一致；保存本次任务专用 `.run/s5-blockers/verified-server-known-hosts`。未改写用户原有 `known_hosts`，未关闭主机身份校验。 |
| 使用 `BatchMode=yes`、`StrictHostKeyChecking=yes`、上述 `UserKnownHostsFile` 和 `HostKeyAlgorithms=ssh-ed25519` 再连接执行只读检查 | 主机校验通过，登录认证返回 `Permission denied (publickey,gssapi-keyex,gssapi-with-mic,password)`。未执行远程命令；不提取已有终端凭据，改请用户在已登录的服务器终端返回限定指令摘要。 |
| `curl.exe --noproxy '*' --head --silent --show-error --connect-timeout 5 --max-time 10 http://www.liuyingapi.top:8081/health` | 连接超时，curl 错误 28；不能据此判定服务器本机端口空闲或防火墙状态。 |

用户随后在已登录终端返回只读检查结果：实际二进制 `/www/server/nginx/sbin/nginx` 报告 `nginx/1.30.3`；主配置 `/www/server/nginx/conf/nginx.conf` 包含 `/www/server/panel/vhost/nginx/*.conf`。HTTP 80 监听分别位于 `0.default.conf:3`、`phpfpm_status.conf:2` 和 `private-agent.conf:13`；默认站点与项目站点各有 HTTPS 443，主配置另有 888。该次 `ss` 回执未显示 80、8081 或 443 的监听，`systemctl is-active nginx` 返回 `inactive`。这些是用户提供的服务器现场证据，不冒称助手已经 SSH 登录；该快照也不能证明 80 争用就是启动失败根因。

为让这一 Nginx 实例释放 HTTP 80，需要一起调整上述三处监听；只改项目站点仍会保留 80。用户随后提供 `/www/server/nginx/sbin/nginx -t; ls -l /etc/init.d/nginx` 回执：现有主配置 `syntax is ok`、`test is successful`，宝塔 `/etc/init.d/nginx` 启动脚本存在且可执行。这证明修改前配置校验通过，不等于 Nginx 已启动。

已准备单行操作命令，副本保存在忽略目录 `.run/s5-blockers/nginx-http-8081.sh`；在本机 Git Bash 使用 `-n -c` 检查该命令，退出码 0，没有执行服务器操作。命令限定上述三个常规配置文件，要求每个文件恰有一处 HTTP 80 监听，先保存到独立 `/root/s5-nginx-8081.XXXXXX` 备份目录，再定向修改 HTTP 监听，保留 443、888、上游和其他参数。替换或修改后 `nginx -t` 失败时恢复三个备份；检查通过才通过宝塔脚本启动并输出监听状态。

此前已在本机 Git Bash 验证 `sed` 表达式只将 `listen 80;` 改为 `listen 8081;`，保留行内注释及 443、888、8000、8080 和 `proxy_pass` 对照文本。首次 Git Bash 受沙箱管道创建限制无法启动，经授权在正常宿主环境重跑成功；该文本替换检查与服务器语法检查分别记录。

用户已在服务器终端执行该命令并返回结果：备份目录 `/root/s5-nginx-8081.3gW9f4`；修改前后配置检查均通过，`Starting nginx... done`；`ss` 显示 Nginx 监听 `0.0.0.0:8081` 与 `0.0.0.0:443`，未显示 80 监听。上述三个服务器配置的修改和启动有用户回执，本机会话未通过 SSH 执行它们。

随后验证：

| 实际检查 | 观察结果 |
| --- | --- |
| `curl.exe --noproxy '*' --silent --show-error --output NUL --write-out 'url=%{url_effective} status=%{http_code} tls_verify=%{ssl_verify_result}\n' --connect-timeout 5 --max-time 15 <URL>`，依次检查 HTTPS `/health`、HTTPS `/auth/me` 和 HTTP `:8081/health` | 两个 HTTPS 请求均返回 401，TLS 校验结果均为 0；证明请求可达鉴权入口，不等于真实账号登录通过。HTTP 8081 仍连接超时，curl 错误 28。 |
| `node .run/s5-blockers/ui.cjs ./.run/s5-blockers/diagnose-network-after-nginx.cjs` | 最终候选真实 WebView 中，匿名 `/health` 与 `/auth/me` 均返回 401，`networkErrors=[]`；原连接拒绝问题已解除。证据 `.run/s5-blockers/login-network-after-nginx.json`，原失败证据保留。 |

HTTP 8081 的服务器监听已生效。用户继续提供回执：以 `Host: www.liuyingapi.top` 请求服务器 `http://127.0.0.1:8081/health` 返回 308；firewalld 为 `running`，`eth0` 属于 `public` 区域。随后执行 `firewall-cmd --zone=public --add-port=8081/tcp && firewall-cmd --permanent --zone=public --add-port=8081/tcp && firewall-cmd --zone=public --query-port=8081/tcp && firewall-cmd --permanent --zone=public --query-port=8081/tcp`，回执为 `success / success / yes / yes`。仅添加该端口的运行时及持久规则，没有重载全部规则，操作依据 [firewalld 官方说明](https://firewalld.org/documentation/howto/open-a-port-or-service.html)。

仅完成服务器防火墙放行时，从本机按上表同一 curl 参数复测：HTTP 8081 仍超时（错误 28），HTTPS `/auth/me` 仍返回 401、TLS 校验通过。命令循环的最终退出码为 0 来自最后的 HTTPS 请求，不能将整组请求判为通过。当时已请求用户核对云控制台安全组或实例防火墙的入站 TCP 8081 规则，尚未取得云入口回执，未断言具体过滤位置。客户端仍使用 HTTPS 443，不需要改服务器地址或重建客户端。

用户随后回复云入口“已放行”。最终使用同一 curl 参数复测 HTTP `:8081/health` 与 HTTPS `/auth/me`，分别返回 308 和 401，均无 curl 连接错误，HTTPS TLS 校验为 0；本次命令显式汇总所有 curl 退出码并以 0 结束。至此服务器监听、firewalld 运行时/持久规则、云入口回执和本机公网复测均已取得证据，HTTP 80 → 8081、HTTPS 443 保留的调整完成。前一段超时记录保留为放行过程证据。

HTTPS 恢复后，候选界面的账号菜单和模型设置可正常打开。已按用户此前授权，通过公开模型配置界面保存 `S5 本机验收（临时）`，模型为 `s5-acceptance-loopback`，回环端点 `http://127.0.0.1:14599/v1`、上下文 65536、无密钥。保存后重新加载配置，界面显示保存成功及对应供应商标题，证据 `.run/s5-blockers/provider-saved.json`。原生目录控件的 UI Automation 写入返回 `0x80070057`，当时未确认目录选择，也未创建项目；随后重新准备项目名称并打开选择器，请用户手动选择独立验收目录。不能把自动化工具失败记录为产品恢复验收失败。该段是验收准备阶段的历史记录；后续用户选定目录、真实恢复和临时供应商删除结果见下一节。

真实 WebView2 验收通过仅传给候选进程的 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=<本机端口>` 连接。依据 [Microsoft WebView2 调试文档](https://learn.microsoft.com/en-us/microsoft-edge/webview2/how-to/debug-visual-studio-code)；不修改系统注册表或用户浏览器配置。账号令牌留在客户端认证链路中，测试脚本不提取或记录凭据。

`scripts/s5_acceptance_model.py` 提供回环 OpenAI 替身。只读取显式工具响应队列，记录请求序号、是否流式、工具名及账号认证头不存在的事实，不记录请求正文。模型固定 `s5-acceptance-loopback`，不用真实或付费模型；真实模型质量仍属于后续 S6。

## 真实 Tauri 强退、恢复与审查结果

用户在原生目录选择器中实际选择了 `F:\Program\test`。只读检查确认它为空、不是链接或 Git 仓库，且父目录没有额外 `AGENTS.md`；随后按授权在该目录建立独立测试 Git 基线 `b7a7168`，只包含自建脚本和占位文件。这是测试仓库提交，`F:\Program\Agent` 的 HEAD 仍为 `d0250ee`，没有暂存或提交 S5。

真实 UI 核对项目“`S5 真实恢复验收`”根目录、`s5-acceptance-loopback` 模型及 `workspace` 权限。所有命令均经实际审批卡批准，使用 `restricted / network_policy=none`。账号登录由用户完成，脚本不读取密码或令牌。回环模型共收到 14 次请求，记录均确认没有 Authorization 头；没有付费模型调用。

| 场景 | 实测结果与证据 |
| --- | --- |
| 文件写入后强退、重启 | 写入 `s5-result.txt` 后只强退安装候选主进程。所属 11 个进程在 688 ms 观察结果中全部退出；运行由本机退出清理收束为 `cancelled`，不是伪称 `interrupted`。文件和原有 dirty 内容保留。证据 `force-file-only.json`、`tauri-after-force-confirmed.json`。 |
| 关联恢复与累计事实 | 用户重新登录后，通过“核对并继续”创建新运行，保留逻辑任务、祖先运行、原终态、已记录事件和失败次数。模型请求从 3 累计到 5，工具从 2 到 3；恢复只读已有文件，没有重复写入或启动命令。证据 `tauri-resumed-file.json`。 |
| 已有、任务和外部改动审查 | 界面区分 1 组任务补丁和 `preexisting.txt` 的 1 项已有改动。在自建 `s5-result.txt` 中模拟外部编辑后，界面显示外部变化；回滚预览标记冲突、保留文件，不提供应用按钮。证据 `review-before-external.json`、`review-external-conflict.json`。 |
| 长命令父子进程强退 | 使用下述 Node 入口参数后，父子进程各写出一次 PID，持久化状态为 `running / stopped=false`。强退前按候选路径、PID、精确启动时间和父子关系核对；只停止候选主进程。5 秒观察点时，测试父子进程与 exec-host 均已退出，命令记录为 `cancelled / stopped=true`。证据 `tauri-tree-before-force.json`、`process-tree-process-tree.json`、`force-process-tree.json`、`tauri-tree-after-force.json`。 |
| 进程清理边界 | 5 秒观察点仍有打包启动器及其 conhost，不能声称整个客户端在 5 秒内全部退出。后续复查确认原所属进程全部退出，候选沙箱租约记录为 0。证据 `tree-cleanup-confirmed.json`。 |
| 长命令强退后的关联恢复 | 再次登录后，“核对并继续”创建关联新运行；模型请求从 3 累计到 6，工具从 2 到 4。新运行仅读取两份 PID 记录，父子启动次数仍各为 1，无新副作用执行或 managed execution。证据 `tauri-tree-resumed.json`。 |
| 实际受保护回滚 | 在审查面板预览并确认撤销唯一的 `s5-tree-result.txt`，界面显示回滚已应用，文件实际删除；`preexisting.txt` 与先前模拟的外部编辑仍原样保留。证据 `review-rollback-applied.json`、`tauri-final-review.json`、`tauri-recovery-review.png`。 |
| 验收清理 | 临时供应商删除后，离开并重新打开模型设置，确认同名配置不存在；核对回环服务脚本与所属 PID 后停止服务，14599 不再监听。证据 `provider-deleted.json`、`model-stopped.json`。 |

这些证据位于 `.run/s5-blockers`，均为限定测试数据、字段白名单或局部界面记录，未加入 Git。`node .run/s5-blockers/ui.cjs <操作脚本>` 通过真实 WebView 控件操作；`.venv/Scripts/python.exe -B .run/s5-blockers/capture-tauri.py <阶段>` 以只读 SQLite 连接核对候选中唯一匹配的测试项目，不调用 Store 初始化或迁移。

`.venv/Scripts/python.exe -B .run/s5-blockers/verify-tauri-evidence.py` 已实际执行并通过，检查两个关联恢复、预算不清零、事件前缀保留、无副作用重放、父子关系及一次启动、已有/外部内容保护、冲突回滚拒绝、实际回滚、租约清理和临时配置删除。结果为 `tauri-evidence-verification.json`。`completed` 仅表示运行生命周期结束；本次是确定性系统行为验收，不将模型的文字声明计为真实编码目标完成或质量成绩。

### 本轮真实运行暴露的兼容限制

1. `python long_task.py` 被拒绝，实际错误为“沙箱授权扫描超过 50000 项，请缩小工作区或工具目录”。当时工作区仅有少量测试文件，实际 Python 安装目录超出授权扫描边界。命令未启动，`command-starts.txt` 未生成；保留 `tauri-start-diagnosis.json`，没有提高上限或降级执行。
2. `node long_task.cjs` 已进入受限执行，但 Node 24.14.0 在默认入口解析时请求 `lstat 'F:\'`，返回 `EPERM`、退出码 1，测试脚本未开始。随后单独使用 `node --preserve-symlinks-main long_task.cjs`，子进程继承同一参数，成功完成上述父子进程验收。该参数可由本机 `node --help` 和 [Node 官方 CLI 文档](https://nodejs.org/api/cli.html#--preserve-symlinks-main)核对；没有授予磁盘根或祖先目录权限，链接拒绝规则不变。该结果不证明未调整参数的普通 Node 项目全部兼容。
3. 部分 UI 自动化因窄窗口下项目/设置抽屉遮挡或入口收起而超时；改用公开抽屉导航完成操作，没有强制点击遮挡控件。另观察到收起侧栏的悬浮按钮会遮挡“回到首页”按钮，通过“新对话”入口继续；记录为布局观察，本轮没有扩大到界面重构。
4. 测试助手首轮 PowerShell 文件因旧解释器 UTF-8 识别失败而未执行，改为显式 UTF-8 读取。首次强退身份比较因 PowerShell 将 JSON 时间解析为 DateTime 而阻止执行；核对原值完全相同后改为精确 UTC ticks 比较，再实际强退。`tauri-after-force-file.json` 是门禁阻止时的观察，不能充当强退证据；实际强退以 `force-file-only.json` 和 `tauri-after-force-confirmed.json` 为准。

## 本轮补充变更文件

以下列出本轮阻断修复涉及的文件；前轮 S5 恢复、控制和审查源文件继续保留，不冒称它们是本轮新增。生成的安装器、完整日志、界面草稿截图和隔离测试数据均位于忽略目录 `.run`，没有加入暂存区。

| 文件 | 本轮变更 |
| --- | --- |
| `apps/exec-host/src/main.rs`、`apps/exec-host/src/sandbox.rs` | 独立 AppContainer 协议、失败关闭、真实工作目录及句柄/进程树管理。 |
| `src/private_agent_core/execution/contracts.py`、`src/private_agent_core/execution/exec_host_client.py` | 独立身份参数、协议能力与宿主 PID。 |
| `src/private_agent_local/windows_sandbox.py` | 新增身份租约、限定目录 ACL、崩溃清理与可写硬链接拒绝。 |
| `src/private_agent_local/windows_process.py`、`src/private_agent_local/files.py` | Windows 目录环境变量的原生查询和白名单补齐。 |
| `src/private_agent_local/executor.py`、`src/private_agent_local/execution_sessions.py` | 受限命令绑定租约，启动/退出/取消时正确释放。 |
| `src/private_agent_local/execution_tools.py`、`src/private_agent_local/runtime.py`、`src/private_agent_local/store.py` | 工具审批及运行边界接入原生受限执行，启动时核对遗留授权。 |
| `src/private_agent_local/policy.py` | 受限 PowerShell 的工作区 PSDrive。 |
| `src/private_agent_local/migration.py` | schema 4–7 基础记录只读导出兼容。 |
| `apps/desktop/src-tauri/Cargo.toml`、`apps/desktop/src-tauri/src/credentials.rs`、`apps/desktop/src-tauri/src/lib.rs` | 独立验收构建 feature、安装配置和凭据命名空间。 |
| `scripts/build-remote-client.cjs`、`scripts/build-remote-client.test.cjs` | QA 安装包约束、源码及产物摘要、构建选项回归。 |
| `scripts/run_coding_validation.py`、`scripts/verify-unified-client.py` | 原生/历史定向入口和当前模型/完成/沙箱契约的冻结测试。 |
| `scripts/s5_acceptance_model.py` | 新增只绑定回环、无账号认证头的确定性模型替身。 |
| `tests/coding_acceptance/test_host_probes.py`、`tests/unit/test_windows_sandbox.py` | 移除两项 strict xfail，增加原生正反对照及边界回归。 |
| `tests/unit/test_local_exec_host.py`、`tests/unit/test_local_execution_sessions.py`、`tests/unit/test_local_permissions.py`、`tests/unit/test_local_history.py` | 宿主能力、受限运行、审批参数及导出兼容测试。 |
| `docs/analysis/coding-agent-upgrade-20260908/README.md`、`s5-recovery-steering-and-review.md`、`s5-validation-report.md`、`s5-blockers-validation-report.md`、`docs/archive/legacy/unified-desktop-runtime.md` | 分开记录历史结论、当前实现、候选证据和仍未完成的真实验收。 |

## 文档与项目记忆

已完整读取根入口、`docs/project-state.md`、S4/S5 报告和相关交付文档。历史项目记忆的日期、工作盘符及能力记录与当前仓库不一致；以本机 Git、当前源码和本轮原生/安装证据核对，历史结论保留。依照根入口的专项限制，本轮不改写 `docs/project-state.md`，用本阶段补充报告记录后续证据。

## 未完成项与交接

- HTTP 8081 与 HTTPS 443 公网复测完成；本次指定的真实 Tauri 强退、进程树回收、重启、关联恢复及审查流程已按上表验收。本地候选直接从当前工作区构建，不依赖先提交或推送 S5。
- 临时模型配置已删除并重新加载确认，回环服务已停止。测试目录 `F:\Program\test` 与忽略目录下证据保留供复核，没有清理用户项目或修改正式客户端。
- 真实桌面追加约束、暂停及继续的完整组合流程尚未补验；已有相应用例的 SQLite/宿主/浏览器证据，不能替代这项实际 UI 证据。ConPTY、UI 增量延迟和其余平台/安装升级边界仍按各阶段报告保留，真实 Provider 质量属于后续 S6 范围。
- 用户要求“可进入 S6 时先提交 S5”；完整 S0–S5 门禁尚未全部通过，因此本轮不提交、推送或开始 S6。未知副作用不得通过强制解锁或重复运行制造通过结果。
