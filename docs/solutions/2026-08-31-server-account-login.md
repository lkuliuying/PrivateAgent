# 固定服务器账号入口与本机模型修复

本说明记录 2026-08-31 本地源码修复与验证，不代表服务器部署或真实账号验收。根目录 README.md 的既有用户改动保持不变；AGENTS.md 与 docs/project-state.md 已读取，后者按仓库约定保留历史快照，本次不改写项目记忆。

## 问题与原因

初版统一安装包允许构建时不传服务器地址，默认进入 local 模式。账号恢复会调用本机 /auth/local 创建“本机用户”；该模式的请求分流把所有接口送到轻量执行器。退出后用户名密码登录也被送到本机 /auth/login，而执行器没有该接口，所以返回 404 Not Found。

这是客户端账号模式和接口分流耦合导致的问题，不能用删除数据库、重试密码或关闭证书校验解决。

## 当前修复边界

- 只使用服务器账号登录，删除自动本机身份、/auth/local 和完整本机后端启动入口；退出后回到登录页。
- 不提供账号服务器地址设置。Tauri 后端 src/server.rs 是账号入口的唯一来源，前端读取它，后端也用它启动轻量执行器；安装包忽略旧缓存地址和前端环境变量覆盖。
- 保留模型执行设置：服务器模型，或本机 Ollama / OpenAI 兼容接口。模型参数不再携带服务器源站或账号模式。
- 模型配置损坏时暂停推理并在设置页提示，不阻断账号登录，也不自动把本机请求改发服务器。
- 本机模型只接管模型清单和推理；账号、注册、登录与管理接口仍访问服务器。账号令牌不会发送给本机模型。
- 本机项目、任务、SQLite、审批、文件 SHA-256 和命令执行保留。数据仍按服务器源站及用户 ID 隔离，切换模型不另建数据库。
- 旧配置仅迁移有效模型参数，清除旧登录模式、服务器覆盖和旧会话。不删除原数据库、不自动把旧本机身份记录合并进服务器账号。
- 登录接口返回 404 时显示部署错误说明，不再裸显 Not Found，不会回退到本机账号。

## 已确认的服务器入口

匿名只读检查的结果：

| 请求 | 结果 |
| --- | --- |
| HTTP 43.163.232.238 /auth/me | 404，HTML |
| HTTPS 43.163.232.238 /auth/me | 证书校验失败 |
| HTTPS www.liuyingapi.top /auth/me | 401，JSON，符合未登录行为 |
| GET HTTPS www.liuyingapi.top /auth/login | 405，接口存在但不接受 GET |

2026-08-31 用户已确认：后端固定使用 https://www.liuyingapi.top，用户不能修改账号服务地址。该域名在检查时解析为 43.163.232.238，保留域名用于站点路由及证书校验，不禁用 TLS 验证、不发送明文密码。本次没有修改服务器。

## 验证

- 前端完整回归：82 文件、482 项通过。含旧账号升级、登录/退出/再次登录、固定入口防覆盖、模型设置界面及请求分流。
- Python 完整相关回归：134 项通过。含账号隔离、SQLite 恢复与迁移、本地模型两种协议、令牌隔离、切换模型保留历史、私有管道及命令宿主。
- 构建选项测试：9 项通过。默认沙箱首次报 Node spawn EPERM，使用获准的子进程环境后通过。
- Ruff 通过。首次候选构建在类型检查阶段发现旧测试引用查询接口；保留既有只读查询接口后修复。第二次构建发现旧校验仍要求服务器地址嵌入前端；现改为验证前端调用后端取址命令，并在原生可执行文件中校验固定账号入口。不能把失败目录内的部分产物当作安装包。

实际测试命令：

```powershell
Set-Location E:\Program\Agent\apps\desktop
node node_modules/vitest/vitest.mjs run
node node_modules/vue-tsc/bin/vue-tsc.js --noEmit
Set-Location E:\Program\Agent
node --test scripts/build-remote-client.test.cjs
.venv/Scripts/python.exe -m ruff check src/private_agent_local tests/unit/test_local_models.py tests/unit/test_local_ipc.py scripts/verify-unified-client.py

Set-Location E:\Program\Agent\.run\unified-tests
$env:PYTHONPATH='E:\Program\Agent\src'
$env:PYTHONDONTWRITEBYTECODE='1'
$testFiles=@(Get-ChildItem E:\Program\Agent\tests\unit -Filter test_local*.py | ForEach-Object FullName)
& E:\Program\Agent\.venv\Scripts\python.exe -m pytest @testFiles E:\Program\Agent\tests\unit\test_desktop_history.py E:\Program\Agent\tests\test_agent_runtime.py E:\Program\Agent\tests\test_model_gateway.py E:\Program\Agent\tests\test_v100_ct6_exec_host_client.py E:\Program\Agent\tests\test_v100_ct6_rust_host_e2e.py E:\Program\Agent\tests\test_v100_ct6_sandbox_enforcement.py --noconftest -p no:cacheprovider --basetemp E:\Program\Agent\.run\unified-tests\fixed-account-regression-1 -q -rs
```

复测时为 basetemp 使用新的独立目录，避免覆盖既有验证数据。测试不读取生产配置、真实账号或真实项目，不发起付费模型调用。原生安装升级、真实账号登录、实际安装的本机模型以及服务器部署仍需分别验收。

## 最终候选包验证

候选安装包：`.run/unified-client-6IIl0v/PrivateAgent_1.0.1_x64-setup.exe`，30048579 字节，SHA-256：

```text
236bb5b7cc97a39788a9d237cbce56989e23a3e68c4874e31e3df067d795db2c
```

该包为未签名预览包，账号入口固定为用户确认的 HTTPS 域名。本机未安装或覆盖旧客户端。发行记录见[1.0.1 账号登录修复预览版](../releases/remote-v1.0.1-server-preview.1.md)。build-info.json 如实记录基线提交 71057fe43a83f3c764751b7d7ad846ca9f38576c、dirty=true 与未启用自动更新。未声称它来自干净的已提交源码。

最终构建通过 Vue 类型检查、Vite、Rust 原生编译与 NSIS 打包；产物清单内四个文件的 SHA-256 全部一致。编译仍有未调用的旧完整后端辅助函数警告，但客户端已不注册其启动命令。本次不展开无关代码清理。通过检索最终编译资源确认：登录页说明保留本机模型，启动失败提示不再要求用户修改服务器地址。

以下三个命令均已执行通过，使用的都是该候选包中的真实冻结执行器与 exec-host：

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv/Scripts/python.exe -B scripts/verify-unified-client.py --bundle .run/unified-client-6IIl0v --work-dir .run/unified-tests --model-mode service
.venv/Scripts/python.exe -B scripts/verify-unified-client.py --bundle .run/unified-client-6IIl0v --work-dir .run/unified-tests --model-mode ollama
.venv/Scripts/python.exe -B scripts/verify-unified-client.py --bundle .run/unified-client-6IIl0v --work-dir .run/unified-tests --model-mode openai
```

三条链路均验证：服务器账号登录/退出、本机账号入口移除、文件写入、人工命令审批、完全访问脚本、真实上下文 usage、撤权、导出三个运行的历史，以及篡改宿主摘要后拒绝执行。本机模型请求没有服务器账号令牌。模型和账号均为隔离回环夹具；sandbox_available=false，不把工具策略宣称为操作系统沙箱。

项目记忆核对：docs/project-state.md 是旧版本历史快照，与新代码的账号边界不同；通过本次 diff、测试和产物验证确认新边界，已在普通实现说明中标明修正及历史验收范围，未按未授权操作改写该记忆文件。README.md 既有改动的 SHA-256 始终保持 4fe795b484bbc0de0cad6bd6e882cb5f3c53dd83f01b2ecfae008bacfcd8705d。

## 安装与服务器边界

本次修复主要在客户端；服务器 git pull 不能更新已安装的桌面程序。下载修复版后，正常退出旧客户端，保留原数据目录，再安装修复包。不要删除 AppData 或 SQLite 来清除旧账号。旧完整后端历史接口是否已部署仍按服务器实际状态核对。

构建入口为 scripts/build-client.cmd --preview-installer --version 1.0.1，不需要也不接受另一个账号服务器地址。预览包不生成自动更新清单，不替换旧稳定版更新通道。

## 本次文件清单

以下仅列本次修复修改或新增的文件，不包含保留的 README.md 用户改动。没有删除项目数据、生产配置或既有功能所需的依赖。

- 修改：`apps/desktop/src-tauri/src/lib.rs`
- 修改：`apps/desktop/src-tauri/src/local_executor.rs`
- 修改：`apps/desktop/src/App.vue`
- 修改：`apps/desktop/src/api.ts`
- 修改：`apps/desktop/src/api/http.spec.ts`
- 修改：`apps/desktop/src/api/http.ts`
- 修改：`apps/desktop/src/components/ConnectionSettings.vue`
- 修改：`apps/desktop/src/components/HistoryMigration.vue`
- 修改：`apps/desktop/src/components/SettingsView.vue`
- 修改：`apps/desktop/src/pages/AuthPage.vue`
- 修改：`apps/desktop/src/router/index.ts`
- 修改：`apps/desktop/src/services/auth.spec.ts`
- 修改：`apps/desktop/src/services/auth.ts`
- 修改：`apps/desktop/src/services/backendStartup.spec.ts`
- 修改：`apps/desktop/src/services/backendStartup.ts`
- 修改：`apps/desktop/src/services/connectionProfile.spec.ts`
- 修改：`apps/desktop/src/services/connectionProfile.ts`
- 修改：`apps/desktop/src/services/localExecutor.spec.ts`
- 修改：`apps/desktop/src/services/localExecutor.ts`
- 修改：`apps/desktop/src/stores/auth.ts`
- 修改：`docs/unified-desktop-runtime.md`
- 修改：`docs/unified-preview-server-update.md`
- 修改：`scripts/build-client.cjs`
- 修改：`scripts/build-remote-client.cjs`
- 修改：`scripts/build-remote-client.test.cjs`
- 修改：`scripts/verify-unified-client.py`
- 修改：`src/private_agent_local/app.py`
- 修改：`src/private_agent_local/connections.py`
- 修改：`src/private_agent_local/entry.py`
- 修改：`src/private_agent_local/local_models.py`
- 修改：`tests/unit/test_local_ipc.py`
- 修改：`tests/unit/test_local_models.py`
- 新增：`apps/desktop/src-tauri/src/server.rs`
- 新增：`apps/desktop/src/components/ConnectionSettings.spec.ts`
- 新增：`apps/desktop/src/services/serverLogin.integration.spec.ts`
- 新增：`docs/solutions/2026-08-31-server-account-login.md`
- 新增：`docs/releases/remote-v1.0.1-server-preview.1.md`
