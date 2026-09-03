# PrivateAgent 换机开发交接

> 整理时间：2026-09-03（Asia/Shanghai）
>
> 适用场景：在另一台 Windows 电脑从 GitHub 重新克隆源码，并继续 PrivateAgent 开发。
>
> 本文只说明开发环境迁移，不授权服务器部署、发布、数据库迁移或生产配置变更。

## 1. 交接基线

| 项目 | 本次核对结果 | 使用边界 |
| --- | --- | --- |
| 远程仓库 | `https://github.com/lkuliuying/PrivateAgent.git` | 不要改成来历不明的镜像地址 |
| 开发分支 | `dev/1.0.0` | 默认 `main` 不是当前开发分支 |
| 远程开发分支 | `ed71f564efbd49cd1f195d169f5f33ae3c47e92f` | 2026-09-03 通过 `git ls-remote` 实时核对；新电脑以克隆时的远程 HEAD 为准 |
| 远程 `main` | `962a4f0bc6d7e054a0762687eca87305131d15d3` | 仅作分支识别，不要在换机时自行把开发分支切成 `main` |
| 本机分支关系 | `HEAD...origin/dev/1.0.0` 为 `0 0` | 只证明本次核对时本地跟踪引用一致 |
| 本机未提交内容 | `README.md` 有未提交修改；本文更新后也会成为未提交修改 | 未提交内容不会出现在另一台电脑 |

提交哈希是交接时的核对基线，不是要求永久固定版本。如果远程分支后来继续更新，新电脑应使用克隆时取得的最新 `dev/1.0.0`，并记录实际 `git rev-parse HEAD` 结果。

必须区分以下两类产品形态：

- 普通版使用完整本机 FastAPI 后端，按功能需要配置 MySQL、Ollama、ChromaDB 等组件。
- 联网版 `PrivateAgentRemote` 在用户电脑运行轻量本机执行器，项目文件与执行记录留在本机，账号和模型调用由服务器提供。它不是“把 Windows 项目目录交给 Linux 服务器执行”。

## 2. 离开旧电脑前必须完成的 Git 检查

新电脑只会取得已经提交并推送到远程仓库的内容。不要把“本机文件存在”理解为“远程仓库已有”。

先在旧电脑的仓库根目录检查：

```powershell
git status --short --branch
git diff --stat
git diff -- README.md
git diff -- docs/new-computer-development.md
git diff --staged
```

本次编写交接文档时，`README.md` 的修改已经预先存在。先确认它的来源和内容，再决定是否随换机交付一起提交；不要为了让工作区变干净而丢弃、覆盖或盲目暂存它。

至少需要把本文提交并推送，另一台电脑才能从远程仓库读到它：

```powershell
git add -- docs/new-computer-development.md

# 仅在确认 README.md 的现有改动也属于本次交付后，才执行下一行。
git add -- README.md

git diff --cached --check
git diff --cached
git commit -m "docs: refresh cross-machine development handoff"
```

提交后先核对远程变化，不要使用 `reset --hard`、`clean`、强制推送或历史重写来解决分支差异：

```powershell
git fetch origin
git rev-list --left-right --count HEAD...origin/dev/1.0.0
```

输出的第一个数字是仅本地提交数，第二个数字是仅远程提交数：

- 第二个数字为 `0` 时，可继续推送当前提交。
- 第二个数字大于 `0` 时，先确认工作区干净，再用 `git merge --no-edit origin/dev/1.0.0` 保留双方历史，处理冲突并重新验证。
- 不确定冲突归属时停止操作，不要覆盖其他会话或其他开发者的改动。

推送并核对：

```powershell
git push origin dev/1.0.0
git rev-parse HEAD
git ls-remote --heads origin refs/heads/dev/1.0.0
git status --short --branch
```

只有 `git rev-parse HEAD` 与 `git ls-remote` 返回的远程提交一致，且计划移交的文件都已提交，才能确认源码已通过 Git 交接。本文没有自动执行提交或推送。

## 3. 新电脑开发工具

### 3.1 基础工具

| 工具 | 要求与用途 |
| --- | --- |
| Git | 克隆、同步和提交代码；需要推送时使用新电脑上自己的 GitHub 登录 |
| Python | `>=3.12`；建议用 Python 3.12 作为共同开发基线 |
| uv | 按 `uv.lock` 创建和同步 Python 环境 |
| Node.js / npm | Node.js `>=20`；按 `apps/desktop/package-lock.json` 安装桌面端依赖 |
| Rust stable | 编译 Tauri/Rust 组件，Windows 目标为 `x86_64-pc-windows-msvc` |
| Visual Studio 2022 Build Tools | 安装“使用 C++ 的桌面开发”和 Windows SDK，提供 MSVC linker |
| Microsoft Edge WebView2 Runtime | 运行 Tauri 桌面客户端 |

按开发范围选装：

- MySQL 8：完整本地后端、数据库迁移或数据库集成测试需要；必须使用开发库或专用测试库。
- Ollama 和模型：仅本地模型、embedding 或对应 RAG 场景需要。
- Playwright Chromium：仅运行浏览器端到端测试时需要。
- GitHub CLI：仅需要额外的 GitHub Release 或仓库操作时使用；普通 `git clone` 不强制要求。

安装后重新打开 PowerShell，检查工具是否进入 PATH：

```powershell
git --version
py -3.12 --version
uv --version
node --version
npm.cmd --version
rustc --version
cargo --version
```

旧电脑本次核对到的工具版本为 Git `2.45.1.windows.1`、Node.js `24.14.0`、npm `11.9.0`、uv `0.11.32`、Rust `1.97.1`。这些只是可工作的参考组合，不是锁文件之外的强制精确版本。

### 3.2 凭据原则

在新电脑使用自己的 GitHub 登录、应用账号和开发凭据。不要复制旧电脑的 GitHub token、SSH 私钥、Windows 凭据管理器内容、登录会话、生产环境文件或签名私钥。

如果 HTTPS 克隆出现 `SEC_E_NO_CREDENTIALS`，优先在普通交互式 PowerShell/Git Credential Manager 中完成自己的 GitHub 登录后重试；不要把凭据写进仓库 URL、脚本或文档。

## 4. 在新电脑克隆和核对源码

在准备存放源码的父目录执行：

```powershell
git clone --branch dev/1.0.0 --single-branch https://github.com/lkuliuying/PrivateAgent.git PrivateAgent
Set-Location PrivateAgent
git status --short --branch
git remote -v
git log -5 --oneline
git rev-parse HEAD
git rev-list --left-right --count HEAD...origin/dev/1.0.0
```

预期分支为 `dev/1.0.0`，工作区初始状态干净，ahead/behind 为 `0 0`。如果远程提交已经晚于本文的基线，以新电脑实际取得的远程提交为准。

开始开发前依次阅读：

1. [`AGENTS.md`](../AGENTS.md)：仓库级工作约定、安全边界和交付要求。
2. [`docs/project-state.md`](./project-state.md)：带日期的共享状态和未验收事项；它是历史事实索引，不是实时 Git 状态。
3. [`README.md`](../README.md)：当前架构、普通版快速开始和构建入口。
4. [`docs/testing-guide.md`](./testing-guide.md)：测试数据库隔离和各层验证命令。
5. 当前任务直接涉及的源码、测试及专题文档。

`docs/project-state.md` 当前整理日期为 2026-08-31，其中的 HEAD 快照早于本文核对到的远程提交。接手时应保留其故障和验收边界，但所有当前提交、工作区、构建和运行结论必须重新验证。

## 5. 按锁文件恢复依赖

### 5.1 Python

在仓库根目录执行：

```powershell
uv sync --locked --extra dev --python 3.12
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
```

`pyproject.toml` 是 Python 依赖规范，`uv.lock` 是锁定解析。换机初始化时不要随意改用 `uv lock --upgrade`，也不要从旧电脑复制 `.venv`。

### 5.2 Vue / TypeScript

```powershell
Push-Location apps\desktop
npm.cmd ci
if ($LASTEXITCODE -ne 0) { throw 'Desktop dependency installation failed' }
Pop-Location
```

使用 `npm ci` 恢复 `package-lock.json` 中的依赖。不要使用 `npm update`，不要删除锁文件，也不要复制旧电脑的 `node_modules`。

### 5.3 Rust / Tauri

确认 Rust 默认目标和 MSVC 环境可用：

```powershell
rustup show
rustup target list --installed
```

Tauri 编译应在“Developer PowerShell for VS 2022”中运行，确保 `cl.exe` 和 `link.exe` 已加载。仓库当前的 `scripts/run-tauri-dev.bat` 和 `scripts/cargo-check-tauri.bat` 都含旧机器的绝对路径 `F:\Program\Agent`，换机后不要直接依赖这两个脚本；从新仓库的实际目录直接运行对应的 npm 或 Cargo 命令。

## 6. 按开发目标启动

### 6.1 只开发或检查前端界面

```powershell
Set-Location apps\desktop
npm.cmd run dev
```

访问 `http://127.0.0.1:1420/?workspace-preview=running`。该入口使用开发预览数据，不等于真实 Tauri、本机执行器、服务器账号或生产模型验收。

### 6.2 开发普通版完整本机后端

返回仓库根目录：

```powershell
Copy-Item .env.example .env
```

至少把 `.env` 中的 `PA_DB_URL` 改为新电脑上的专用开发库。不要使用生产数据库，不要把密码或 API key 提交到 Git。

数据库迁移会修改所配置数据库，确认目标后再执行：

```powershell
uv run alembic upgrade head
uv run alembic current
uv run uvicorn personal_assistant.main_api:app --reload --host 127.0.0.1 --port 8000
```

另开“Developer PowerShell for VS 2022”，从新电脑的实际仓库路径启动桌面端：

```powershell
Set-Location <新电脑仓库路径>\apps\desktop
npm.cmd run tauri dev
```

不要把示例占位符 `<新电脑仓库路径>` 原样执行。

### 6.3 开发或构建联网版客户端

联网版会打包轻量本机执行器，因此开发/构建机仍需要 Python 环境、PyInstaller 依赖、前端依赖、Rust/MSVC 和 WebView2。它不要求终端用户自行安装 MySQL 或 Ollama。

先查看构建参数并做无产物检查：

```powershell
node scripts/build-remote-client.cjs --help
node scripts/build-remote-client.cjs "https://api.example.com" --preview-installer --version 1.0.4 --dry-run
```

示例域名必须替换为已确认的 HTTPS API origin，不能包含路径、查询参数、令牌或账号。真正构建、签名、上传和发布是独立操作，按 [`docs/remote-client-updates.md`](./remote-client-updates.md) 执行，不要仅凭 dry-run 宣称安装包已生成或已发布。

## 7. 新电脑首次验证

先做不依赖生产服务的检查：

```powershell
git status --short --branch
git diff --check
uv run --with ruff ruff check src tests scripts
uv run python -m compileall -q src scripts
node --test scripts/build-remote-client.test.cjs

Push-Location apps\desktop
npm.cmd run test
npm.cmd run build
Pop-Location

Push-Location apps\desktop\src-tauri
cargo check --locked
Pop-Location
```

逐条保留退出码和失败摘要。只有实际运行并通过的项目才能记为通过；本文不预填测试数量，也不把旧电脑的历史成绩当作新电脑成绩。

全量 Python 测试和迁移往返需要先配置独立测试库：

```powershell
uv run pytest -q
```

执行前确认 `PA_TEST_DB_URL` 指向专用测试库，并与 `PA_DB_URL` 隔离。不要为了跑通测试而连接生产数据库、关闭鉴权、删除有效测试或放宽安全检查。

Playwright 首次运行需要浏览器组件：

```powershell
Push-Location apps\desktop
npx.cmd playwright install chromium
npm.cmd run e2e
Pop-Location
```

浏览器模拟测试通过不等于真实 Tauri 安装、自动更新、账号登录、付费模型调用或服务器部署验收通过。

## 8. 不通过 Git 迁移的内容

以下内容被忽略、与机器绑定或可能包含敏感数据，不应提交到远程仓库，也不应整目录复制到新电脑：

| 内容 | 处理方式 |
| --- | --- |
| `.env`、`.env.local`、`.env.container`、`smtp.env`、`.secrets/` | 在新电脑按示例重新创建，只填写新环境自己的值 |
| `.tauri/`、`*.key`、`*.pfx` 等签名材料 | 不复制、不提交；确需签名时走独立密钥交接流程 |
| `.venv/`、`node_modules/`、各 Cargo `target/`、`dist/` | 从锁文件重新生成 |
| `data/`、日志、数据库文件、`.run/`、`.tmp/`、缓存目录 | 默认不迁移；需要数据迁移时另行定义脱敏、备份和恢复方案 |
| Windows 凭据管理器、GitHub 凭据、应用登录会话 | 在新电脑重新登录，不导出旧凭据 |
| 联网版本机 SQLite 与用户项目目录 | 不随源码仓库同步；用户项目需要单独的安全备份/版本控制方案 |
| 本机测试 EXE、安装包和旧 Release 下载目录 | 不作为源码基线；需要时从可信发布渠道重新取得并校验 |

如果确实要迁移个人项目文件或开发数据库，应作为独立任务确认数据范围、敏感性、备份、校验和回滚；不要把它们塞进 PrivateAgent 源码提交。

## 9. 当前项目边界与待确认项

- 当前远程开发分支已经包含统一模型路由、联网版本机执行、服务器更新工具、Git/PowerShell 权限和执行时间线等后续提交；不要只按 2026-08-31 的旧 HEAD 判断功能是否存在。
- `docs/project-state.md` 记录的联网版模型/管理员日志故障，本机修复、服务器运行副本、真实账号与生产验收状态属于不同证据层。没有新的服务器回执时继续标记“待确认”。
- 当前本机 `README.md` 修改尚未提交；如果它未被提交并推送，新电脑看到的 README 会是远程版本。
- 新电脑完成依赖安装、静态检查和本地测试，不代表服务器已更新，也不代表任何发布产物已重新构建或上传。
- 不要从换机需求扩展到服务器部署、生产重启、GitHub Release、签名或远程数据库操作。

## 10. 换机完成检查表

- [ ] 旧电脑计划交接的修改已经逐文件复核、提交并推送。
- [ ] 新电脑克隆的是 `dev/1.0.0`，并记录了实际 HEAD。
- [ ] `git status --short --branch` 显示预期分支和干净初始状态。
- [ ] 已阅读 `AGENTS.md`、`docs/project-state.md` 和当前任务相关文档。
- [ ] Python、Node、Rust/MSVC 和 WebView2 已按开发范围安装。
- [ ] Python 与前端依赖均从锁文件重新安装。
- [ ] 本地配置使用开发环境自己的值，没有复制或提交秘密。
- [ ] 已运行并记录与当前改动范围相匹配的验证命令。
- [ ] 普通版、联网版、本机代码、安装包、服务器部署和真实账号验收结论没有混用。

完成以上项目后，才可把“换机后的源码开发环境已恢复”作为结论；尚未执行的构建、测试、服务器操作和真实业务验收仍需分别记录为未验证。
