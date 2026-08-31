# PrivateAgent 1.0.2 模型配置与界面预览版

发行标签：`remote-v1.0.2-model-config-preview.1`。这是统一客户端的 Windows x64 未签名手动安装预览包，不覆盖旧 Release、旧附件或既有自动更新通道，不设为 Latest。旧 `remote-v1.0.2` 属于另一条 Remote 发行线，不能根据相同版本数字混用安装包。

[GitHub Release](https://github.com/lkuliuying/PrivateAgent/releases/tag/remote-v1.0.2-model-config-preview.1) · [下载安装包](https://github.com/lkuliuying/PrivateAgent/releases/download/remote-v1.0.2-model-config-preview.1/PrivateAgent_1.0.2_x64-setup.exe)

## 本次变化

1. 启动加载画面移除“正在连接本地服务，请稍候…”副文案，保留启动标题与加载动画。
2. 上下文弹窗显示“平均缓存命中率”，按同一会话、同一模型的有效缓存 tokens / 输入 tokens 累计计算；窗口占用仍使用最近一次请求，不把整段会话累计量当作窗口占用。
3. “模型设置”和“当前模型”不再显示独立的“模型执行设置”。模型列表与配置统一来自账号服务器；执行器依据所选模型的协议、地址及本地标记自动路由。本机模型发现也在客户端执行，不会误查服务器上的回环服务。

本机模型仍仅支持无密钥的回环 Ollama / OpenAI 兼容接口；Ollama 需要明确上下文容量。缺少配置、配置不一致、接口不可用或需要密钥时明确报错，不擅自切换到其他服务。服务器账号登录、项目数据隔离、审批和执行权限不变。

## 安装包与源码依据

- 本机产物：`.run/unified-client-oqW2q1/PrivateAgent_1.0.2_x64-setup.exe`。
- 大小：30,054,459 字节。
- SHA-256：`23915a5095cadbd53fa962af1208598fdd2e1a1090a48b0b54d9b245f76b7a1b`。
- 发布附件：安装包、未经改写的 `build-info.json`、只校验这两个附件的 `SHA256SUMS.txt`。
- 原始构建记录：基线 `9d0b2352930693b765cfae8527df0992c58bd58c` 加本次修改，`dirty=true`，构建完成时间 `2026-08-31T14:11:38.774Z`。安装包先于分批提交生成，不能将构建记录改成干净提交。发布标签指向随后纳入相应源码的提交；README 原有改动不纳入提交。
- 应用标识仍为 `com.personal-assistant.desktop`；本机执行器与前端一起打包，传输为 `stdio-v2`。预览包 updater endpoints 为空，不生成 `latest.json` 或签名附件。
- `remote-v` 标签前缀沿用已有预览发行约定，现有 SignPath 工作流排除此类标签，不触发旧完整后端打包任务。

## 改动文件与提交分组

完整功能文件清单见[运行时说明第 9 节](../unified-desktop-runtime.md#9-2026-08-31-界面与自动模型路由验证)。本次发行按以下三组提交，共 27 个文件，不包含原有 README 改动：

| 分组 | 实际文件 |
| --- | --- |
| 本机运行时与测试，10 个文件 | 修改 `src/private_agent_local/` 下的 `app.py`、`cloud.py`、`connections.py`、`context.py`、`core_adapter.py`、`local_models.py`、`runtime.py`、`store.py`；修改 `tests/unit/test_local_context.py`；新增 `tests/unit/test_local_model_routing.py` |
| 桌面界面与调用链，14 个文件 | 修改 `apps/desktop/src/RootApp.vue`、`RootApp.spec.ts`；修改 `api/modelProviders.ts`、`api/modelProviders.spec.ts`；修改 `components/ModelProvidersPanel.vue`、`components/SettingsView.vue`、`components/SettingsView.spec.ts`；删除 `components/ConnectionSettings.vue`、`components/ConnectionSettings.spec.ts`；修改 `features/agent/ContextUsageRing.vue`、`features/agent/ContextUsageRing.spec.ts`；修改 `services/localExecutor.ts`、`services/localExecutor.spec.ts`、`services/serverLogin.integration.spec.ts`。上述缩写路径均相对 `apps/desktop/src/` |
| 打包验证与发行说明，3 个文件 | 修改 `scripts/verify-unified-client.py` 和 `docs/unified-desktop-runtime.md`；新增本文 |

冻结执行器验证脚本改为与桌面入口一致的 `inference_mode=auto`，三种测试协议均通过服务器配置选路，覆盖真实打包二进制，避免只验证旧手动模式。

## 实际验证

以下命令已在开发机执行；`.run/model-config-release/` 为忽略的隔离验证目录。复跑 pytest 时应改用新 `--basetemp`，避免清理已有测试产物。

```powershell
Set-Location E:\Program\Agent\apps\desktop
node node_modules/vitest/vitest.mjs run

Set-Location E:\Program\Agent\.run\model-config-release
$env:PYTHONPATH = 'E:\Program\Agent\src'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$testFiles = @(Get-ChildItem E:\Program\Agent\tests\unit -Filter 'test_local*.py' | ForEach-Object FullName)
$testFiles += 'E:\Program\Agent\tests\unit\test_connected_server_workflow.py'
& E:\Program\Agent\.venv\Scripts\python.exe -m pytest --noconftest -p no:cacheprovider --basetemp=E:\Program\Agent\.run\model-config-release\pytest @testFiles -q

Set-Location E:\Program\Agent
.venv\Scripts\python.exe -m ruff check src/private_agent_local tests/unit/test_local_model_routing.py tests/unit/test_local_context.py scripts/verify-unified-client.py
node --test scripts/build-remote-client.test.cjs
$env:CARGO_BUILD_JOBS = '1'
.\scripts\build-client.cmd --preview-installer --version 1.0.2
```

结果：前端 81 文件、484 项通过；Python 180 项通过，1 项真实符号链接测试因当前 Windows 创建权限跳过；构建参数 9 项通过；Ruff 通过。构建脚本内的 Vue 类型检查、Vite 生产构建、PyInstaller、Rust release 编译和 NSIS 打包全部完成。

```powershell
Set-Location E:\Program\Agent\.run\model-config-release
E:\Program\Agent\.venv\Scripts\python.exe -B E:\Program\Agent\scripts\verify-unified-client.py --bundle E:\Program\Agent\.run\unified-client-oqW2q1 --work-dir E:\Program\Agent\.run\model-config-release\packaged-service --model-mode service
E:\Program\Agent\.venv\Scripts\python.exe -B E:\Program\Agent\scripts\verify-unified-client.py --bundle E:\Program\Agent\.run\unified-client-oqW2q1 --work-dir E:\Program\Agent\.run\model-config-release\packaged-ollama --model-mode ollama
E:\Program\Agent\.venv\Scripts\python.exe -B E:\Program\Agent\scripts\verify-unified-client.py --bundle E:\Program\Agent\.run\unified-client-oqW2q1 --work-dir E:\Program\Agent\.run\model-config-release\packaged-openai --model-mode openai

Set-Location E:\Program\Agent
Get-FileHash .run\model-config-release\assets\PrivateAgent_1.0.2_x64-setup.exe -Algorithm SHA256
Get-AuthenticodeSignature .run\model-config-release\assets\PrivateAgent_1.0.2_x64-setup.exe
git diff --check
```

三种自动路由均通过：模拟服务器登录/退出、本机模型发现、文件写入、人工命令审批、完全访问脚本、最近请求上下文及会话缓存统计、撤权、历史导出、宿主摘要篡改拒绝执行、进程正常关闭。测试仅使用临时目录和回环服务，没有调用生产账号或付费模型。安装包摘要匹配，Authenticode 状态为 `NotSigned`。

构建参数测试初次因沙箱 `spawn EPERM` 失败，同一命令在获准权限下重跑 9 项通过；沙箱中公开 GitHub 查询也曾受本机认证环境限制，重跑成功。Rust 保留 12 条未使用代码/链接器警告，Vite 保留大分块警告；未为消除既有警告扩大修改范围。源码阶段的测试修正记录保留在运行时说明第 9 节。

## 用户操作与验证边界

**客户端：** 正常退出旧客户端及托盘实例，备份整个 `%LOCALAPPDATA%\com.personal-assistant.desktop\local-projects` 目录后手动安装新包。服务器拉取源码不会更新已安装客户端。原来仅存在于旧“模型执行设置”中的模型，需要在统一“模型设置”中重新选择保存；旧会话失效的 `local-model` ID 需要重新选择有效模型。

**服务器：** 本次相对 `9d0b235` 只涉及桌面端、本机执行器、测试和文档，没有依赖、锁文件、数据库迁移或服务器业务代码变化。若服务器已经接入当前一键更新脚本，可由操作者执行：

```bash
/opt/private-agent/venv/bin/python -I -B /opt/private-agent/current/scripts/update-connected-server.py
```

预期只有本批差异时返回 `CODE_SYNCED_NO_RESTART`。实际分类以服务器当前 HEAD 到目标的完整差异为准；如仍使用旧更新工具、存在本地修改或发现专项审阅文件，停止并按[服务器更新指南](../server-code-update-workflow.md)核对，不修改白名单绕过保护。核对最终 HEAD 等于发行标签提交，并确认服务持续 RUNNING。

本次未操作服务器，未实际安装/升级已装客户端，未完成真实账号或供应商验收。工具权限和 SHA-256 校验不构成操作系统沙箱，打包验证中 `sandbox_available=false`。未签名预览包可能触发 Windows 提示；不将其宣称为正式签名或自动更新发行。

## 项目记忆检查

已读取 `AGENTS.md` 与 `docs/project-state.md`，并核对当前 Git、源码、测试、构建与 GitHub 发行。项目记忆中的 Git 和服务器快照属于较早记录；本轮以实时开发机及 GitHub 证据为准，不把历史生产状态改写为已验收。当前自动路由、缓存统计及旧配置兼容边界已同步至 `docs/unified-desktop-runtime.md`，本次构建与发布边界记录在本文。按仓库明确约定，本次没有改写 `docs/project-state.md` 或全局记忆。
