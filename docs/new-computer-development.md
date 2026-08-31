# 在另一台 Windows 电脑继续开发

> 历史适用范围提示（2026-08-31 补充）：本文包含早期远程测试 EXE、草稿入口及原机工具版本。当前联网版 1.0.3 捆绑本机执行器，工作区也有未提交修复；接手先读 [共享项目状态记忆](./project-state.md)，不要直接套用旧产物入口或默认工作区干净。

适用：本次 CentOS 服务端已部署，主要在 Windows x64 上修改 Tauri/Vue/Python 源码。先取得源码和工具，再按需配置独立开发后端。不要把生产数据库作为测试库。

## 1. 取得正确分支

安装 Git；如果要推送或下载草稿附件，再安装 GitHub CLI，并在新电脑通过 `gh auth login --web` 自己完成登录。不要复制旧机器的 GitHub token、SSH 私钥或凭据存储。

```powershell
git clone --branch dev/1.0.0 https://github.com/lkuliuying/PrivateAgent.git
Set-Location PrivateAgent
git status --short
git log -1 --oneline
```

当前改动保存在 `dev/1.0.0`，不是默认 main。开始新任务前保持工作区干净，再 `git pull --ff-only`。后续功能建议在此基础上新建自己的分支，不要改旧发布标签。

若只需要使用客户端：登录 GitHub 后打开仓库的 Releases 页面，查看 `v1.0.0` 草稿；普通匿名访客看不到草稿。也可用：

```powershell
gh release view v1.0.0 --repo lkuliuying/PrivateAgent
gh release download v1.0.0 --repo lkuliuying/PrivateAgent --dir .\release-download
```

使用新目录下载，不加覆盖选项。客户端压缩包附带校验值与使用说明；它是未签名测试 EXE，需要 WebView2，不包含 MySQL/Python。不要使用应用内更新覆盖此远程构建。

## 2. 工具前置条件

| 工具 | 用途与版本口径 |
|---|---|
| Git / GitHub CLI | 拉代码；推送和草稿下载需你自己的 GitHub 登录 |
| Node.js / npm | 前端依赖和构建；本次实测 Node 24.14.0 / npm 11.9.0 |
| Rust MSVC 工具链 | Tauri；本次实测 rustc/cargo 1.96.1，目标 `x86_64-pc-windows-msvc` |
| Visual Studio 2022 Build Tools | “使用 C++ 的桌面开发”及 Windows SDK；脚本会查找 vcvars64.bat |
| Microsoft Edge WebView2 Runtime | 运行 Windows Tauri 客户端 |
| uv / Python | 修改后端与运行后端测试时使用；项目 Python >=3.12；本机测试 Python 3.13.13，服务器 Python 3.12 系列 |
| MySQL 8.x | 仅完整本地后端/数据库集成测试需要，使用独立开发数据库 |
| Ollama | 仅测试本地模型或相应 embedding 场景需要；远程客户端构建不需要 |

工具安装遵循 [Tauri 官方 Windows 前置条件](https://v2.tauri.app/start/prerequisites/#windows)。这些是开发机组件，不需要在 CentOS 上安装 Windows 构建工具。本次没有替新电脑安装软件，也没有升级当前项目依赖。

安装后新开 PowerShell 检查：

```powershell
git --version
node --version
npm.cmd --version
rustc --version
cargo --version
uv --version
```

## 3. 按锁文件安装依赖

在新克隆的仓库根目录执行，任一命令失败就先解决该错误：

```powershell
uv sync --locked --extra dev --python 3.12
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
Push-Location apps\desktop
npm.cmd ci
if ($LASTEXITCODE -ne 0) { throw 'Desktop dependency installation failed' }
Pop-Location
```

`--locked` 会检查并使用已有锁文件；不会悄悄更新版本解析。参见 [uv 锁定与同步](https://docs.astral.sh/uv/concepts/projects/sync/)。不要使用 `npm update`、删除锁文件或直接复制旧机的 `.venv/node_modules/target`。

只改前端时可以暂不安装 Python/MySQL；只编译本次远程客户端无需 Python sidecar。完整后端集成测试需要另建本地数据库和测试配置，见 [测试指南](./testing-guide.md)。不要导出或复制生产秘密文件到源码目录。

## 4. 最小验证

下面的后端回归脚本预先替换配置与数据库模块，并只执行 Alembic 的 URL 赋值语句，不读取环境文件、不连库、不执行迁移：

```powershell
.\.venv\Scripts\python.exe -B scripts\verify-deployment-regressions.py
.\.venv\Scripts\python.exe -m ruff check src/personal_assistant/api/routes_health.py tests/test_health_visibility.py scripts/verify-deployment-regressions.py
```

预期：Alembic 编码/普通 URL 两个往返断言通过，健康权限 9 项通过。此脚本只用于部署回归，不能替代完整 pytest。

`alembic/env.py` 另行纳入 Ruff 时会报告原有导入排序 `I001`；已用修改前的 Git 版本复现相同结果。本次仅修 URL 转义，没有顺手重排导入；回归脚本覆盖该行真实行为和语法。

前端在 `apps/desktop` 执行：

```powershell
npm.cmd test -- src/components/SettingsView.spec.ts src/components/SettingsModuleNav.spec.ts src/pages/AdminPage.spec.ts src/router/index.spec.ts src/api/modelProviders.spec.ts src/api/http.spec.ts src/stores/health.spec.ts --maxWorkers=1 --minWorkers=1
node node_modules/vue-tsc/bin/vue-tsc.js --noEmit
```

完整预期为 7 文件 32 项通过，类型检查退出码 0。本轮交接实测是 31 项通过、1 项路由测试默认 5 秒超时；修改前 `2d48efd` 的独立源码副本同样复现该超时，尚未修复。保留该测试，不提高阈值来掩盖失败；六个其他文件共 30 项通过。详见部署总结的验证范围。

可选真实浏览器检查（第一次需为 Playwright 安装 Chromium）：

```powershell
npx.cmd playwright install chromium
npm.cmd run e2e -- e2e/coding-workbench.spec.ts --grep '设置按模块切换' --retries=0
```

该用例使用模拟会话/API，不访问生产服务器；预期 1 项通过。

## 5. 构建远程客户端

本节为未签名便携测试包。需要客户端内“检查更新”的远程安装版，请使用[远程客户端更新流程](./remote-client-updates.md)，不要把便携 EXE 当作 updater 安装包发布。

在仓库根目录运行，将示例地址替换为自己的 HTTPS API 域名；仅填 origin，不带路径、查询串、令牌或账号：

```powershell
.\scripts\build-remote-client.cmd "https://api.example.com"
if ($LASTEXITCODE -ne 0) { throw 'Remote client build failed; do not run an old EXE' }
```

构建输出为新的 `.run/remote-client-*` 目录，其中包含：

- `PrivateAgent-remote-windows-x64.exe`：远程客户端。
- `SHA256SUMS.txt`：EXE 的 SHA256。
- `build-info.json`：源码提交、工作区是否干净、远程地址、目标平台等非秘密来源信息。
- `web/`：本次嵌入的前端资源，供排障。

脚本先类型检查和 Vite 构建，再用锁定的 Cargo 依赖构建 x64 EXE，检查当前前端入口已嵌入。它不修改 Tauri 配置文件、不打包 sidecar、不读取签名私钥、不生成安装包或自动更新文件。共享 Cargo 构建缓存可能更新；以前输出目录中的客户端不会被覆盖。首次构建需要下载依赖并可能较慢，不要并行在同一个 checkout 构建多个 Tauri 包。

正式交付应先提交源码，再从干净工作区构建，确认 `build-info.json` 中 `dirty=false`。哈希因工具链/时间等因素可能不同，不要求在另一台机器上按字节复现同一 EXE。

不要把服务令牌设置为 `VITE_API_TOKEN`；前端构建变量可被用户从 EXE 中提取。脚本强制该变量为空，登录使用个人账号。

## 6. 日常开发与远程联调

最安全的第一步是前端本地预览：

```powershell
Set-Location apps\desktop
npm.cmd run dev
```

打开 `http://127.0.0.1:1420/?workspace-preview=running` 可用预览数据检查工作台。没有必要为了改 UI 接入生产账号或数据库。

完整本地功能调试使用独立本地 API、开发数据库和本地配置，按 [README 开发步骤](../README.md#快速开始) 配置；注册验证码和模型能力需要开发者自己的凭据。不要把生产备份导入随意运行的测试环境。

远程功能验收使用上节编译的客户端登录。开发浏览器的 `localhost:1420` Origin 不等于打包客户端的 `tauri.localhost`，生产服务不一定允许前者，不能通过关闭鉴权或放宽为任意 Origin 来绕过。

新电脑需要重新登录应用，并按需重新输入自己的模型 Key。不要迁移浏览器本地存储、Windows 密钥库或复制旧会话当作登录方式。服务器端重启也可能清空运行时模型 Key，保存后再验收聊天。

## 7. 提交和发布前

```powershell
git status --short
git diff --check
git diff --stat
```

只显式暂存本次源码和测试文件，检查差异后提交推送。不要 `git add -f` 强行加入忽略目录；不要上传 `.env`、smtp.env、数据库、日志、用户文档、令牌文件或私钥。

本次 `v1.0.0` 仍是草稿联调交付，不是新稳定版。公开发布会触发另一个签名安装流程，不能以点击 Publish 替代远程客户端验证。后续按 [发布清单](./release-checklist.md) 单独做发布工作。
