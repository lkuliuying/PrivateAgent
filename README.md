# 私人助手 Agent

本地优先、隐私可控的桌面私人助手。第一阶段目标：**稳定对话 + 本地知识库问答**。

> 详细需求见 `docs/requirements.md`，开发计划见 `docs/phase1-plan.md`。

## 技术栈

| 层 | 选型 |
|---|---|
| 桌面壳 | Tauri 2 |
| 前端 | Vue 3 + TypeScript + Vite |
| 本地后端 | FastAPI + Uvicorn（async） |
| LLM | Ollama（Qwen2.5-14B-Instruct Q4 + bge-m3） |
| 业务库 | MySQL 8 + SQLAlchemy 2.0 async + Alembic |
| 向量库 | 嵌入式 ChromaDB |

## 目录结构

```text
Agent/
├── apps/desktop/            # Tauri + Vue 3 桌面端
├── docs/                    # 需求与计划
├── alembic/                 # 数据库迁移
├── scripts/
│   └── run-tauri-dev.bat    # Windows 下带 MSVC 环境启动 Tauri dev
├── src/personal_assistant/  # Python 后端
│   ├── api/                 # HTTP/SSE 边界
│   └── core/                # AI 与业务核心（零 UI 依赖）
├── data/                    # 运行时数据（chroma / logs，gitignore）
├── pyproject.toml
└── .env                     # 本地配置（gitignore，从 .env.example 复制）
```

## 依赖准备

### 1. Ollama 与模型
安装 Ollama 后拉取：
```bash
ollama pull qwen2.5:14b-instruct-q4_K_M
ollama pull bge-m3
```

### 2. MySQL
本机 MySQL 8.0+，建库：
```sql
CREATE DATABASE personal_assistant CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 3. Python
Python 3.12+，推荐用 [uv](https://github.com/astral-sh/uv) 管理依赖：
```bash
winget install --id astral-sh.uv -e
```

### 4. Tauri 桌面端编译依赖（Windows）
- **Rust**（rustup，msvc target）：`winget install --id Rustlang.Rustup -e`
- **MSVC Build Tools**（提供 `cl.exe`/`link.exe`，Tauri 编译必需）：
  ```bash
  winget install --id Microsoft.VisualStudio.2022.BuildTools --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
  ```
- WebView2（Windows 11 自带）

## 开发启动

### 后端（Python FastAPI）
```bash
# 复制并填写环境变量（改 .env 里的 MySQL 密码、模型名等）
copy .env.example .env       # Linux/macOS: cp

# 安装依赖
uv sync --extra dev

# 数据库迁移（建 5 张表）
uv run alembic upgrade head

# 启动后端（默认 127.0.0.1:8000）
uv run uvicorn personal_assistant.main_api:app --reload --port 8000
```

> **Windows + Python 3.13 编码**：若遇中文 `UnicodeDecodeError`，启动前设
> `set PYTHONUTF8=1`（cmd）或 `export PYTHONUTF8=1`（bash）。

### 桌面端（Tauri + Vue）
```bash
cd apps/desktop
npm install
```
Windows 下 `tauri dev` 需要 MSVC 环境，已封装为脚本（项目根目录执行）：
```bash
scripts\run-tauri-dev.bat
```
该脚本会先 `call vcvars64.bat` 设置 MSVC 环境，再把 `%USERPROFILE%\.cargo\bin` 加入 PATH，最后 `npm run tauri dev`。

## 数据库迁移

```bash
uv run alembic upgrade head                          # 应用迁移
uv run alembic revision -m "xxx"                     # 新建空迁移
uv run alembic revision --autogenerate -m "xxx"      # 自动生成（需连库）
```

## 健康检查

后端启动后：
- `GET http://127.0.0.1:8000/health` —— 返回 API / Ollama / MySQL / ChromaDB 四项状态
- `GET http://127.0.0.1:8000/docs` —— API 文档

桌面端状态页每 5 秒自动刷新 `/health` 并展示四项状态；后端未连接时显示「本地后端未连接」提示。

## 打包（M4 预研）

将 Python 后端打包为 Tauri sidecar，桌面应用启动时自动拉起后端，无需手动开终端。详见 `docs/phase4-sidecar-research.md`。

### 1. 打包后端 sidecar
```bash
scripts\build-sidecar.bat
```
用 PyInstaller（`personal_assistant.spec`）把后端打成 `personal-assistant-server.exe`（onefile，~85MB），复制到 `apps/desktop/src-tauri/binaries/`。

### 2. 启动 / 构建
```bash
scripts\run-tauri-dev.bat                # 开发模式（binaries/ 为真实 sidecar 时自动拉起；占位时后端手动起）
cd apps/desktop && npm run tauri build    # 打包安装程序
```

### 3. 运行时依赖（打包后仍需本机具备）
- **Ollama** + 模型（`qwen2.5:14b-instruct-q4_K_M`、`bge-m3`）
- **MySQL 8**（建库见上文）
- **配置文件** `%APPDATA%/personal-assistant/.env`，至少：
  ```
  PA_DB_URL=mysql+aiomysql://root:<密码>@127.0.0.1:3306/personal_assistant?charset=utf8mb4
  ```

启动后 Tauri 自动分配空闲端口拉起 sidecar，前端动态连接；退出时清理 sidecar 进程。

## 当前进度

**第一阶段（M0–M3）核心已完成** ✅
- M0 环境与骨架：Tauri+Vue / FastAPI / MySQL+Alembic / Ollama+ChromaDB 连通，`/health` 全绿。
- M1 对话助手：流式 SSE、多轮上下文、停止生成、首轮自动生成标题、会话历史持久化到 MySQL。
- M2 知识库 RAG：导入 PDF/Word/MD/TXT、切分、向量化、检索、来源引用、删除一致性、失败重试。
- M3 设置与打磨：设置/状态页、参数持久化、结构化日志、错误提示、pytest 基础测试。

**M4 打包预研（非硬验收）已完成** ✅：Tauri sidecar + 端口协商 + PyInstaller 打包可行性验证通过，详见 `docs/phase4-sidecar-research.md`。

**第五阶段（安装包与分发）已部分完成** ✅：
- NSIS 安装包（`installMode: currentUser`，简中/英文）+ 一键构建 `scripts/build-release.bat`。
- 首启依赖检测向导 + 连接配置 UI（`ConfigWizard.vue`），写入 `%APPDATA%/personal-assistant/.env`。
- sidecar 生命周期重构：`start_sidecar` 按需拉起、重试时先终止旧进程避免孤儿、dev 模式回退手动后端。
- 启动引导状态机（`App.vue`：checking/wizard/starting/done/dev/error）+ `/health` 依赖就绪判定。
- Tauri updater 命令接线（`check_for_updates`/`download_and_install_update`/`relaunch_app`）+ `UpdateChecker.vue`。
- 详见 `docs/phase5-installer-updater.md` 与 `docs/usage-guide.md`。

> 待续：代码签名、updater 发布源（需生成签名密钥对 + 部署 `latest.json`）、跨平台、onedir 体积优化。

## 常见问题

- **alembic 报 `UnicodeDecodeError: 'gbk'`**：`alembic.ini` 已改为英文注释；运行前设 `PYTHONUTF8=1`。
- **`asyncmy` 装不上**：Python 3.13 + Windows 无预编译 wheel，本项目改用纯 Python 的 `aiomysql`（已默认）。
- **`tauri dev` 报 `link.exe not found`**：未装 MSVC Build Tools，见上文「依赖准备」。
- **端口 1420 被占**：`netstat -ano | grep :1420` 找 PID，`taskkill /PID <pid> /F`。
- **MySQL `Access denied`**：确认 `.env` 的 `PA_DB_URL` 中用户名/密码正确。
- **构建安装包**：`scripts\build-release.bat`（需 MSVC + uv + Node；自动打包 sidecar → NSIS 安装包 + 更新签名 `.sig`）。
- **`tauri build` 下载 NSIS 超时（`timeout: global`）**：GitHub 不可达，先设代理 `set HTTPS_PROXY=http://127.0.0.1:10808`（端口换成你本地代理）再跑 `build-release.bat`；首次下载后缓存在 `%LOCALAPPDATA%\tauri\`。
