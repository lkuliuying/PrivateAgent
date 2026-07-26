# PrivateAgent 私人助手

PrivateAgent 是一个本地优先、隐私可控的桌面个人 Agent。它使用 Tauri + Vue 构建桌面工作台，以 FastAPI sidecar 提供本地服务，并通过 Ollama、MySQL 与嵌入式 ChromaDB 完成对话、知识库、长期记忆、学习复习、任务编排和受控编码工作流。

当前版本：`0.1.2` · 数据库迁移：`0011 (head)` · 主平台：Windows 10/11 x64

## 核心能力

- 今日工作台：收件箱、提醒、目标、简报、快速捕获、全局搜索和通知中心。
- 本地 AI：Ollama 对话、流式输出、会话历史、Provider 路由及远程发送审计。
- 知识与学习：PDF/Word/Markdown/TXT 导入、混合检索、来源引用、文档集合、学习计划、测验、复习卡片和长期记忆。
- 项目 Agent：授权目录、代码检索、Git 状态、白名单命令、补丁审批、多文件 patch set、回滚及可编辑任务计划。
- 数据治理：隐私预览、诊断包脱敏、完整性检查、备份/恢复演练、ICS 日历导入和扩展注册表。
- 桌面发布：Python sidecar、动态端口与 256-bit 会话令牌协商、NSIS 安装包、应用内更新清单、发布检查及可选代码签名。

所有文件访问、命令执行和写入能力都受授权路径、风险等级与审批流程约束。

## 技术栈

| 层 | 技术 |
|---|---|
| 桌面端 | Tauri 2、Vue 3、TypeScript、Vite |
| 本地 API | Python 3.12+、FastAPI、Uvicorn |
| Agent / LLM | LangGraph、LangChain、Ollama、可配置 Provider |
| 数据库 | MySQL 8、SQLAlchemy 2 async、Alembic |
| 向量检索 | 嵌入式 ChromaDB、bge-m3 |
| 测试 | pytest、Vitest、Playwright、Cargo check |

## 目录结构

```text
Agent/
├── apps/desktop/             # Vue 前端与 Tauri 桌面壳
├── src/personal_assistant/   # FastAPI API、业务核心与后台任务
├── alembic/                  # MySQL 数据库迁移（当前 head: 0011）
├── tests/                    # 后端、发布和升级测试
├── scripts/                  # 开发、验证、sidecar 和安装包脚本
├── docs/                     # 需求、阶段计划、使用与发布文档
├── pyproject.toml            # Python 项目与依赖的规范来源
├── requirements.txt          # pip 兼容依赖清单
└── uv.lock                   # uv 锁文件
```

## 环境要求

完整功能需要：

- Python 3.12 或更高版本（推荐配合 [uv](https://docs.astral.sh/uv/)）
- Node.js 20 LTS 或更高版本
- MySQL 8.0+
- [Ollama](https://ollama.com/) 及所需模型
- Rust stable、MSVC Build Tools 和 WebView2（仅 Tauri 开发/打包需要）

Windows 安装常用工具：

```powershell
winget install --id astral-sh.uv -e
winget install --id Ollama.Ollama -e
winget install --id Rustlang.Rustup -e
winget install --id Microsoft.VisualStudio.2022.BuildTools `
  --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

拉取默认模型：

```powershell
ollama pull qwen2.5:14b-instruct-q4_K_M
ollama pull bge-m3
```

创建数据库：

```sql
CREATE DATABASE personal_assistant
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

## 快速开始

### 1. 配置环境变量

```powershell
Copy-Item .env.example .env
```

至少修改 `.env` 中的 `PA_DB_URL`。默认 API 地址为 `127.0.0.1:8000`，默认模型为 `qwen2.5:14b-instruct-q4_K_M` 和 `bge-m3`。`.env` 已被 Git 忽略，不要提交密码或密钥。

### 2. 安装 Python 依赖

推荐使用锁文件安装：

```powershell
uv sync --extra dev
```

也可以使用标准 pip：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`pyproject.toml` 是依赖的规范来源，`requirements.txt` 用于 pip 兼容安装；修改依赖时应同步两者并更新 `uv.lock`。

### 3. 迁移数据库并启动后端

```powershell
uv run alembic upgrade head
uv run uvicorn personal_assistant.main_api:app --reload --host 127.0.0.1 --port 8000
```

启动后可访问：

- `http://127.0.0.1:8000/health`：API、Ollama、MySQL、ChromaDB 健康状态
- `http://127.0.0.1:8000/docs`：OpenAPI / Swagger 文档

后端可以在 Ollama 暂不可用时启动，但对话、摘要和嵌入等 AI 功能需要 Ollama 恢复后才能正常工作。

### 4. 启动桌面端

```powershell
Set-Location apps\desktop
npm ci
Set-Location ..\..
scripts\run-tauri-dev.bat
```

`run-tauri-dev.bat` 会定位 MSVC 环境、补充 Cargo PATH，并执行 `npm run tauri dev`。开发模式连接固定的 `127.0.0.1:8000`；安装版由 Tauri 自动选择空闲端口并拉起 sidecar。

## 验证

分别运行：

```powershell
uv run pytest -q

Set-Location apps\desktop
npm run build
npm run test
npm run e2e
Set-Location ..\..

uv run alembic current
```

需要 Rust/MSVC 的 Tauri 格式、编译与 Rust 单测门禁：

```powershell
scripts\cargo-check-tauri.bat
```

发布前快速检查：

```powershell
scripts\release-check.bat
```

完整证据流水线会额外执行前端测试、E2E、诊断包脱敏和更新清单校验，并在 `dist/` 生成 JSON/Markdown 报告：

```powershell
scripts\release-check-full.bat
```

pytest 和完整证据流水线会自动创建唯一的 `pa_test_*` MySQL 数据库与隔离数据目录，结束后只清理本次运行拥有的目标。测试账号需具备创建/删除测试数据库的权限；也可通过严格命名的 `PA_TEST_DB_URL` 指定由 CI 管理、测试不会删除的数据库。测试流程绝不会回退到开发数据库。

## 构建 Windows 安装包

构建 Python sidecar：

```powershell
scripts\build-sidecar.bat
```

一键构建发布包：

```powershell
scripts\build-release.bat
```

构建流程包含 sidecar 打包、MSVC 检测、Tauri/NSIS 构建、可选签名和发布清单生成。主要产物位于：

```text
apps/desktop/src-tauri/target/release/bundle/nsis/
dist/release-manifest-<version>.md
dist/codesign-status-<version>.json
```

没有配置代码签名证书时仍可生成安装包，但状态会明确记录为 `code_signed: no`，Windows SmartScreen 可能显示未知发布者。更新发布、签名顺序和真实升级验证步骤见：

- `docs/release-checklist.md`
- `docs/signing-and-keys.md`
- `docs/cross-platform.md`

## 配置与运行时数据

| 场景 | 配置 | 数据 |
|---|---|---|
| 源码开发 | 项目根目录 `.env` | 项目根目录 `data/` |
| Windows 安装版 | `%APPDATA%\personal-assistant\.env` | `%APPDATA%\personal-assistant\` |

安装版首次启动会通过配置向导写入配置。退出桌面应用时，Tauri 会清理它启动的 sidecar 进程。

## 当前交付边界

- Windows NSIS 构建、sidecar smoke、发布清单和无证书透明策略已实现。
- Windows 真实 `vN -> vN+1` 安装升级、正式代码签名证书实签仍需在发布环境执行。
- macOS/Linux 构建脚本和差异说明已准备，实机构建与 smoke 尚未作为当前发布的硬验收。
- `externalBin` 发生变化后，同版本覆盖安装应先完成真实验证；未验证前建议卸载旧版本再安装新包。

## 文档导航

- `docs/usage-guide.md`：完整使用说明
- `docs/requirements.md`：第一阶段需求基线
- `docs/phase2-requirements.md` ～ `docs/phase8-requirements.md`：各阶段需求
- `docs/phase1-plan.md` ～ `docs/phase8-plan.md`：各阶段开发与验收计划
- `docs/phase5-installer-updater.md`：历史入口，当前发布规范以 phase 5 正式文档为准

## 常见问题

- `UnicodeDecodeError: 'gbk'`：PowerShell 运行 `$env:PYTHONUTF8='1'` 后重试。
- MySQL `Access denied`：检查 `.env` 中 `PA_DB_URL` 的用户名、密码、端口和数据库名。
- `link.exe not found`：安装 MSVC Build Tools，并使用 `scripts\run-tauri-dev.bat`。
- `tauri build` 首次下载 NSIS 超时：确认 GitHub 网络可达，必要时为当前终端设置 `HTTPS_PROXY`。
- Ollama 状态异常：确认 `ollama serve` 正在运行，且默认对话与嵌入模型已经拉取。

## 安全说明

本项目默认只监听 loopback 地址。安装版每次启动由 Tauri 使用系统 CSPRNG 生成 256-bit 临时 Bearer token，只在桌面进程、WebView 内存和 sidecar 环境中传递，不写入 `.env`、localStorage 或日志；API CORS 仅允许 Tauri WebView 与 loopback 开发来源。WebView 同时启用严格 CSP，脚本只允许应用自身来源，并禁用对象、子框架和表单提交。源码开发模式在 `PA_API_TOKEN` 为空时保持兼容，生产部署不应关闭令牌校验。

请勿把本地 API 直接暴露到公网，也不要提交 `.env`、Tauri updater 私钥、PFX 证书或其他凭据。执行文件写入、命令运行、补丁应用及远程 Provider 调用前，请核对授权范围和审批信息。
