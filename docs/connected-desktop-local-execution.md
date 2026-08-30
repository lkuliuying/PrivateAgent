# 联网客户端：本机项目执行与服务器模型服务

2026-08-30 更新：本次实现对应 **PrivateAgentRemote 1.0.3 测试包**。功能源码已分批提交并推送到 `dev/1.0.0`，服务端此前已部署定向补丁；GitHub 测试包仍为预发布草稿，正式远程更新源没有切到 1.0.3。另一台电脑反馈“模型能力不可用”，根因和真实联调验收尚未完成，接手入口见 [下一台电脑提示词](./next-agent-handoff-1.0.3.md)。

现有测试包是在提交前构建的，原构建记录 `dirty=true` 保持不变；本次源码提交没有重新打包、部署服务器或发布安装包。以下测试和构建记录保留各阶段的实际结果，不表示异机模型问题已经解决。

## 用户需要的版本

| 版本 | 项目文件与命令 | 账号与模型 | 用户需要安装什么 |
| --- | --- | --- | --- |
| 普通版（保留原有行为） | 本机完整后端 | 原有本机部署配置 | 客户端及完整后端所需环境 |
| 旧远程版（1.0.2） | 请求发送到服务器，不能使用另一台电脑的目录 | 服务器 | 旧远程安装包 |
| 新联网版（本次 1.0.3 测试包） | 本机独立执行器，项目目录、会话与任务库留在电脑 | 服务器 | 一个完整安装包；执行器和 Python 运行时已包含 |

新联网版继续使用 `PrivateAgentRemote` 的应用标识和独立更新通道，避免覆盖普通版。服务器保存账号、模型配置与 HTTP 操作审计；不为本机任务创建服务器项目、工作区或运行记录。

源码文件不会作为整个项目自动上传。用户提示词、任务中读取的代码片段及工具结果会作为模型上下文发送到服务器及配置的模型供应商。输出可能包含代码内的路径等文字，因此这不是“文件内容永不离开电脑”的离线模式。

同一账号在另一台电脑上登录，不会自动同步项目文件和历史任务。需要在该电脑上选择已有目录，或由用户自行取得项目副本。旧版服务器项目记录不会被猜测映射、移动或删除。

## 实现边界

- 联网构建启用 `VITE_LOCAL_EXECUTOR=true`。`projects`、`sessions`、`agent-runs`、`capabilities`、旧 `chat` 请求只允许走本机；本机不可用时直接报错，绝不回退到服务器处理电脑路径。当前支持 Coding 工作台，旧 chat 接口在本机返回未实现，不发送到云端执行工具。
- 账号、模型配置、管理员模块仍走构建时配置的 HTTPS 服务器。新增 `POST /desktop/model/complete` 只做认证后的模型推理，不接受项目根目录、也不执行模型返回的工具调用。
- Tauri 随安装包启动 `private-agent-local.exe`，只监听随机的 `127.0.0.1` 端口。使用每次启动生成、仅驻留内存的连接凭证，以及经过服务器确认的用户登录会话；检查 Host 和 Origin。
- 本机账号库位于应用的 `app_local_data_dir/local-projects/<服务器与账号哈希>/projects.sqlite3`。不写入模型供应商凭据或登录令牌。账号切换时取消旧任务、关闭旧库、重建前端项目状态；过期请求不能自动重新绑定旧账号。
- 模型可列目录、读取和搜索文本、申请单文件修改、申请固定测试/构建命令。读文件限制 1 MB，工具输出有界；排除凭据路径、符号链接、目录联接和硬链接读取。
- 修改以完整新文本生成 diff，逐次审批，写前核对 SHA-256；原文件采用同目录临时文件替换，新文件不覆盖并发创建的文件。父目录必须已存在。
- 命令限于 `pytest`、`python -m pytest`、`npm test`、`npm run test`、`npm run build`、`cargo test`、`cargo check`，不接受额外参数。命令逐次审批、限制时长并清理子进程。Windows 使用 Job Object 回收后台子进程，并处理打包进程继承的 DLL 搜索路径。
- **项目脚本不是操作系统沙箱**：批准测试或构建即允许该项目脚本以当前系统用户权限运行，脚本可能读写其他文件和联网。审批预览明确展示此风险；只批准可信项目。执行 Python/Node/Rust 项目仍需该项目自身的开发工具及依赖，客户端不会偷偷安装它们。
- 只开放“只读”和“总是询问”。未提供的自动批准、完全访问、Git worktree、多文件 PatchSet、计划工具和上下文压缩不宣称可用。单任务最多 24 轮模型调用、48 次工具调用；本机同时只执行一个任务。
- 取消、退出、更新和父客户端异常退出会收拢本机运行；进程重启时未完成任务标记失败，不重放不确定的写入或命令。
- 管理员日志模块位于“系统”“用户”下方，权限、固定日志源、脱敏、有界读取及部署要求见 `admin-service-logs.md`。

## 验证与构建

没有新增或升级依赖。使用仓库已有 Python、PyInstaller、Node、Tauri 和 MSVC 工具。

隔离 Python 检查必须从空的测试工作目录执行，避免载入开发环境配置：

```powershell
$env:PYTHONPATH='F:\Program\Agent\src'
# 当前目录为 F:\Program\Agent\.run\admin-logs-verification
& 'F:\Program\Agent\.venv\Scripts\python.exe' -X utf8 -B -m pytest `
  F:\Program\Agent\tests\unit\test_local_executor.py `
  F:\Program\Agent\tests\unit\test_desktop_model.py `
  F:\Program\Agent\tests\unit\test_admin_logs.py `
  --noconftest -p no:cacheprovider `
  --basetemp F:\Program\Agent\.run\local-executor-test-5 -q
```

实际结果：**27 passed, 1 skipped**。跳过项为 Windows 无符号链接创建权限时的真实链接测试；路径重定向模拟检查仍执行。覆盖本机建项目、审批前不写、拒绝/取消/过期文件不覆盖、重复批准拒绝、账号隔离、旧请求拒绝、重启不重放、HTTPS 禁止重定向、模型接口鉴权/限额/错误脱敏/断连取消，以及日志权限与脱敏。Windows 命令测试实际启动临时进程并确认退出后没有后台后代。

前端定向测试（在 `apps/desktop` 下）：

```powershell
npm.cmd test -- src/services/localExecutor.spec.ts src/api/http.spec.ts src/services/backendStartup.spec.ts src/stores/auth.spec.ts src/features/coding/model/codingWorkspaceStore.spec.ts src/components/AdminLogsPanel.spec.ts src/pages/AdminPage.spec.ts
```

实际结果：**43 passed**。包含 Windows 路径只发送本机、断连不回退云端、请求体与取消信号保留、账号/模型/日志仍走云端、普通版兼容。

随后扩大到整个 Coding 工作台和根应用生命周期：

```powershell
npm.cmd test -- src/services/localExecutor.spec.ts src/api/http.spec.ts src/services/backendStartup.spec.ts src/stores/auth.spec.ts src/features/coding src/components/AdminLogsPanel.spec.ts src/pages/AdminPage.spec.ts src/RootApp.spec.ts
```

实际结果：**30 个测试文件、196 项测试全部通过**。

```powershell
node --test scripts/build-remote-client.test.cjs
.venv\Scripts\python.exe -m ruff check src/private_agent_local src/personal_assistant/api/routes_desktop_model.py tests/unit/test_local_executor.py tests/unit/test_desktop_model.py scripts/verify-local-executor.py
git diff --check
scripts\build-remote-client.cmd https://www.liuyingapi.top --preview-installer --version 1.0.3
.venv\Scripts\python.exe -X utf8 -B scripts/verify-local-executor.py <打包输出目录>\private-agent-local.exe
```

打包配置测试 **8 passed**；Ruff 和 diff 检查通过。构建运行 vue-tsc、Vite、PyInstaller、Rust release 编译和 NSIS。独立执行器实测在 PATH 不包含 Python 的情况下启动，验证启动凭证、来源限制、账号要求及优雅退出，无生产请求。

构建保留 Vite 大于 500 KB 分块警告、PyInstaller 可选 `importlib_resources.trees` 未找到警告；实际独立执行器启动检查通过。测试安装包未做 Authenticode 签名，也未生成在线更新 manifest，不能作为已完成线上验收的版本发布。

最终本地安装包：`.run/remote-client-5DJM8U/PrivateAgentRemote_1.0.3_x64-setup.exe`，25,519,903 字节。

SHA-256：`f8409dc1b80590b3ee707e9f25a8e32749bf4e113d63c52757cbc84ccfe3fb2f`。

最终执行器实测记录：`.run/local-executor-smoke-1166fa8d/result.json`。NSIS 生成脚本确认将执行器安装为 `private-agent-local.exe`，与客户端相邻；`Get-AuthenticodeSignature` 的实际结果为 `NotSigned`。没有在本机覆盖安装，也没有在另一台电脑安装验收。

## 上线仍需完成

1. 审核并部署服务端新增模型接口和日志接口，沿用现有账号认证和模型配置；本次没有数据库迁移。确认反向代理转发 `/desktop/model/complete`，推理超时设置覆盖实际模型延时。
2. 按服务器实际 Supervisor/Nginx 日志路径配置四个日志源，并给应用用户只读权限，包含日志轮转后的文件。不要让应用以 root 身份运行。
3. 用真实账号和服务器模型，在另一台 Windows 电脑安装测试包，选择本机测试目录，完整验收读取、修改审批、运行测试、取消、退出、账号切换和管理员日志。当前只有模拟云端的业务回归及打包执行器实测，没有真实服务器端到端验收。
4. 验收后用既有受保护的 updater 签名流程生成正式更新包，再发布 GitHub Release 和远程更新源。继续区分普通版与 Remote 更新通道；系统代码签名证书到位后再加入 Authenticode 签名。

## 本次文件清单

- 桌面路由及身份：`apps/desktop/src/api/http.ts`、`src/services/backendStartup.ts`、`src/services/localExecutor.ts`、`src/services/localExecutor.spec.ts`、`src/stores/auth.ts`、`src/features/coding/model/codingWorkspaceStore.ts`（后五项同属 `apps/desktop`）。
- 桌面进程与构建：`apps/desktop/src-tauri/src/lib.rs`、`apps/desktop/src-tauri/src/local_executor.rs`、`apps/desktop/vite.config.ts`、`scripts/build-remote-client.cjs`、`scripts/build-remote-client.test.cjs`、`scripts/verify-local-executor.py`。
- 本机执行器：`src/private_agent_local/__init__.py`、`app.py`、`cloud.py`、`entry.py`、`files.py`、`runtime.py`、`store.py`、`windows_process.py`。
- 云端模型：`src/personal_assistant/api/routes_desktop_model.py`、`src/personal_assistant/main_api.py`。
- 管理员日志：`apps/desktop/src/pages/AdminPage.vue`、`AdminPage.spec.ts`、`apps/desktop/src/components/AdminLogsPanel.vue`、`AdminLogsPanel.spec.ts`、`apps/desktop/src/services/adminLogs.ts`、`src/personal_assistant/config.py`、`src/personal_assistant/api/routes_admin_logs.py`、`src/personal_assistant/core/admin_logs.py`。
- 验证与说明：`tests/unit/test_local_executor.py`、`tests/unit/test_desktop_model.py`、`tests/unit/test_admin_logs.py`、`docs/admin-service-logs.md`、本文件。

Windows 子进程处理参考：[Microsoft Job Object 限制](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information)、[PyInstaller 外部程序注意事项](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html)。
