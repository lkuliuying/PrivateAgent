# 私人助手 Agent

本地优先、隐私可控的桌面私人助手。当前已完成到第六阶段：**长期记忆 + 学习复习 + 文档集合 + 可回滚编码工作流 + 可编辑任务计划 + Provider 路由 + 安装包与发布工程化 + 主动个人中枢**。

> 详细需求见 `docs/requirements.md`（一阶段）/ `docs/phase2-requirements.md` / `docs/phase3-requirements.md` / `docs/phase4-requirements.md` / `docs/phase5-requirements.md` / `docs/phase6-requirements.md`，开发计划见 `docs/phase1-plan.md` / `docs/phase2-plan.md` / `docs/phase3-plan.md` / `docs/phase4-plan.md` / `docs/phase5-plan.md` / `docs/phase6-plan.md`。

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

## 打包与发布（第五阶段）

将 Python 后端打包为 Tauri sidecar，桌面应用启动时自动拉起后端，无需手动开终端。第五阶段已形成可复现的 Windows 发布闭环：构建脚本不再硬编码本机路径，提供发布前校验、发布清单与 updater 清单自动生成。

### 0. 发布前校验
```bash
scripts\release-check.bat        # pytest / npm build / cargo check / alembic current
```

### 1. 打包后端 sidecar
```bash
scripts\build-sidecar.bat
```
用 PyInstaller（`personal_assistant.spec`）把后端打成 `personal-assistant-server.exe`（onefile，~85MB），复制到 `apps/desktop/src-tauri/binaries/`。脚本自动从 PATH 查找 `uv`、按脚本位置推导项目根，无需改本机路径。

### 2. 一键构建 NSIS 安装包
```bash
scripts\build-release.bat
```
串联：sidecar 打包 → 自动检测 MSVC `vcvars64.bat`（vswhere + 常见路径）→ 可选 updater 签名（`%USERPROFILE%\.tauri\personal-assistant.key`）→ `tauri build` → 生成发布清单 `dist\release-manifest-<ver>.md`（含 sha256 / git commit / 校验项）。

> 首次 `tauri build` 从 GitHub 下载 NSIS 工具链；不可达时先 `set HTTPS_PROXY=http://127.0.0.1:10808`。

### 3. 生成 updater 发布清单
```bash
uv run python scripts\generate-latest-json.py --notes "<发布说明>" --out dist\latest.json
```
自动从 `tauri.conf.json` 读版本、从 git remote 读 repo、从 `.sig` 读签名，并对安装包文件名做百分号编码（updater 要求 ASCII URL）。

### 4. 上传 GitHub Release
上传三个资产到 `v<version>` Release：安装包、`.sig`、`latest.json`。应用内"检查更新"即从 `.../releases/latest/download/latest.json` 拉取。详见 `docs/release-checklist.md`。

### 5. 运行时依赖（打包后仍需本机具备）
- **Ollama** + 模型（`qwen2.5:14b-instruct-q4_K_M`、`bge-m3`）
- **MySQL 8**（建库见上文）
- **配置文件** `%APPDATA%/personal-assistant/.env`（首启向导自动写入）

启动后 Tauri 自动分配空闲端口拉起 sidecar，前端动态连接；退出时清理 sidecar 进程。

### 相关文档
- `docs/phase5-plan.md` / `docs/phase5-requirements.md`：第五阶段计划与需求。
- `docs/phase6-plan.md` / `docs/phase6-requirements.md`：第六阶段主动个人中枢规划。
- `docs/release-checklist.md`：发布 QA 矩阵与回滚。
- `docs/signing-and-keys.md`：updater 签名与 Windows 代码签名。
- `docs/cross-platform.md`：macOS / Linux 预研（Windows 为第五阶段硬验收）。
- `docs/phase4-sidecar-research.md`：sidecar 机制预研历史归档。

## 当前进度

**第一阶段（M0–M3）核心已完成** ✅
- M0 环境与骨架：Tauri+Vue / FastAPI / MySQL+Alembic / Ollama+ChromaDB 连通，`/health` 全绿。
- M1 对话助手：流式 SSE、多轮上下文、停止生成、首轮自动生成标题、会话历史持久化到 MySQL。
- M2 知识库 RAG：导入 PDF/Word/MD/TXT、切分、向量化、检索、来源引用、删除一致性、失败重试。
- M3 设置与打磨：设置/状态页、参数持久化、结构化日志、错误提示、pytest 基础测试。

**第二阶段（M0–M5）已完成** ✅：从"问答应用"升级为"受控工作台助手"。详见 `docs/phase2-plan.md`。
- M0 UI 大改造：四区工作台（导航 rail / 列表区 / 主工作区 / 右检查器 / 状态栏）+ 设计令牌系统（`design/tokens.css`）。
- M1 工具调用底座：`ToolRegistry`/`ToolExecutor` + 审批状态机 + `tool_calls` 审计表 + `ToolApprovalCard`。
- M2 文件工具：`read_file`/`summarize_file`/`import_to_kb` 三工具（支持 PDF/Word/MD/TXT）+ `trusted_paths` 授权校验 + Tauri 原生文件选择器 + 检查器内文件摘要/目录扫描（`/files/summarize`、`/files/scan`，扫描 200 上限）。
- M3 知识库增强：搜索/状态筛选/启用禁用 + 批量导入 + 单文档/全量重建索引 + 引用片段详情（`/chunks/{id}`）+ 禁用文档不参与 RAG 检索。
- M4 活动流：工具调用/文档导入/索引重建统一写入 `activities` + 活动页（筛选/展开输入输出/失败重试）+ 聊天页检查器显示会话活动。
- M5 测试与收尾：`pytest` 39 通过（工具/审批/路径校验/知识库增强/活动流/文件处理）+ `npm run build` + `cargo check` 全绿。

**第三阶段（M0–M6）已完成** ✅：从"受控工作台助手"升级为"学习 + 文档 + 编码"个人 Agent。详见 `docs/phase3-plan.md`。
- M0 数据底座：迁移 0004（`projects`/`project_files`/`learning_*` 表 + `documents`/`doc_chunks` 元数据增列）+ ORM + 导航扩展为六入口（聊天/知识库/项目/学习/任务/设置）+ 项目/学习骨架页。
- M1 项目工作区（只读）：授权项目目录、后台扫描索引（忽略 `.git`/`node_modules` 等）、目录树、文件名/内容搜索、文件片段读取、git status/diff；5 个代码工具注册（`search_files`/`grep_code`/`read_code_file`/`get_git_status`/`get_git_diff`）；越界 `rel_path` 拒绝（403）。
- M2 混合检索：向量召回 + 关键词 LIKE 召回 + RRF 融合 + 可插拔 rerank 接口 + 命中原因（`matched_via`/`matched_keywords`）；禁用文档两路均排除；文档元数据（`doc_type`/`topic`/`tags`/`language`/`project_id`）筛选与编辑；引用展示命中关键词。
- M3 学习系统：学习主题 CRUD、基于知识库资料生成学习路线/练习题/复习卡片、答题批改记录；5 个学习工具注册（`create_learning_plan`/`save_learning_note`/`generate_quiz`/`grade_quiz_answer`/`create_review_cards`）；学习工作台四标签 UI（路线/笔记/练习/卡片，含翻卡动画）。
- M4 文档工作台：章节摘要、多文档对比（共同点/差异/冲突/阅读顺序）、术语表、Markdown 导出（授权目录+不覆盖）、生成笔记入库；4 个文档工具注册；知识库页多选 + 对比浮层 + 摘要浮层。
- M5 编码修改与命令验证：`propose_patch` 只读生成 diff；`apply_patch_to_workspace` 审批后写入授权项目文件并校验旧内容哈希；`run_whitelisted_command` 审批后在项目根运行白名单命令（`pytest` / `python -m pytest` / `npm run build` / `cargo check` 等），输出自动截断。
- M6 多步任务编排：新增迁移 0005（`agent_tasks` / `agent_task_steps` / `agent_evidence` + `tool_calls.task_id/step_id`）；任务页可创建计划、运行步骤、批准高风险步骤、失败重试、查看证据与 Markdown 最终报告。
- 测试：`pytest` 76 通过（含项目工作区/混合检索/学习系统/文档工作台/编码工具/任务编排）+ `npm run build` + `cargo check` 全绿。

**第四阶段（M0–M6）已完成** ✅：从"学习 + 文档 + 编码"个人 Agent 升级为"长期记忆 + 主动复习 + 可回滚工作流 + 可配置 Provider"个人系统。详见 `docs/phase4-plan.md`。
- M0 底座：迁移 0006/0007/0008（长期记忆、学习复习、文档集合、patch set、任务计划状态扩展）+ 七入口导航（新增记忆）。
- M1 长期记忆：记忆 CRUD、搜索、候选生成、启用/禁用/敏感过滤、聊天注入并展示引用来源。
- M2 学习 2.0：due_at 复习调度、今日复习、错题本、主题 dashboard、学习周报、学习复习候选记忆。
- M3 文档工作台 2.0：文档集合、结构化抽取、模板报告、OCR 入口占位与来源 refs。
- M4 编码工作流 2.0：项目命令配置、多文件 patch set、审批 apply/reject/rollback、命令失败诊断。
- M5 任务计划 2.0：`task_planner.py`、计划草稿、计划编辑、整体审批、暂停/取消/继续、从指定步骤继续、证据筛选。
- M6 Provider 与数据治理：`ProviderRouter`、OpenAI-compatible/Claude Provider、远程发送范围提示、备份导出、恢复预览、学习主题/任务报告导出。
- 测试：`pytest` 123 通过 + `npm run build` + `cargo check` 全绿，`alembic current -> 0008 (head)`，健康检查 API/Ollama/MySQL/ChromaDB 全绿。

**M4 打包预研（非硬验收）已完成** ✅：Tauri sidecar + 端口协商 + PyInstaller 打包可行性验证通过，详见 `docs/phase4-sidecar-research.md`。

**第五阶段（安装包与发布工程化）已完成 M0–M6** ✅：
- M1 可复现构建：`build-sidecar.bat` / `build-release.bat` 去硬编码（脚本位置推导根目录、PATH 查找 uv、vswhere + 常见路径检测 MSVC）；新增 `release-check.bat`（pytest/npm build/cargo check/alembic current）与 `generate_release_manifest.py`（发布清单 + sha256）。
- M2 updater 发布源：`generate-latest-json.py` 自动产出与 `.sig` 一致的 `latest.json`（版本来自 tauri.conf.json、repo 来自 git remote、文件名百分号编码）；`UpdateChecker.vue` 区分网络/清单/签名/无更新错误；已校验 `tauri.conf.json` 公钥与本地私钥匹配、`.sig` 与清单一致。
- M3 签名与密钥：`docs/signing-and-keys.md`（updater 私钥策略 + 轮换 + Windows 代码签名方案 + 签名顺序）；`.gitignore` 覆盖密钥与证书，已确认仓库不含私钥。
- M4 发布 QA：`docs/release-checklist.md`（安装/升级/卸载 QA 矩阵、用户数据目录行为、迁移与回滚、发布清单模板、GitHub Release 上传、v0.1.0→v0.1.1 升级 smoke）。
- M5 体积与启动：`measure_sidecar_baseline.py` 实测基线（sidecar 84.7MB / 安装包 88.0MB / 启动到 /health ≈5s）；`personal_assistant_onedir.spec` 评估 onedir；发现并修复打包缺 `cryptography`（MySQL 8 认证）缺陷；结论暂不切换 onefile。
- M6 跨平台预研：`build-sidecar.sh`（macOS/Linux）+ `docs/cross-platform.md`（macOS/Linux 差异与待验证清单，Windows 为硬验收）。
- 详见 `docs/phase5-plan.md`、`docs/phase5-requirements.md`、`docs/release-checklist.md`、`docs/signing-and-keys.md`、`docs/cross-platform.md`。

> 待真实环境执行（工具与文档已就绪）：部署 GitHub Release 资产并跑通 v0.1.0→v0.1.1 升级 smoke；接入 Windows 代码签名证书；macOS/Linux 实机构建与 smoke。`cryptography` 打包缺陷已在 v0.1.1 sidecar 重新构建后验证修复，打包模式 `/health` API / Ollama / MySQL / ChromaDB 全绿。

**第六阶段（主动个人中枢）已完成 M0–M7** ✅：
- M1–M3：新增 `0009_phase6_proactive_hub.py`、Today 聚合服务、统一收件箱、通用提醒、后台 tick、桌面通知降级和 Today/Inbox/Reminder 前端。
- M4–M6：新增长期目标、目标关联、check-in、目标/今日/周回顾简报、简报转任务、隐私预览、Provider 调用审计和维护健康报告。
- M7 验证：`pytest -q` 146 通过，`npm run build`、`cargo check`、`alembic current -> 0009 (head)`、`git diff --check` 通过。
- 详见 `docs/phase6-plan.md` 与 `docs/phase6-requirements.md`。

## 常见问题

- **alembic 报 `UnicodeDecodeError: 'gbk'`**：`alembic.ini` 已改为英文注释；运行前设 `PYTHONUTF8=1`。
- **`asyncmy` 装不上**：Python 3.13 + Windows 无预编译 wheel，本项目改用纯 Python 的 `aiomysql`（已默认）。
- **`tauri dev` 报 `link.exe not found`**：未装 MSVC Build Tools，见上文「依赖准备」。
- **端口 1420 被占**：`netstat -ano | grep :1420` 找 PID，`taskkill /PID <pid> /F`。
- **MySQL `Access denied`**：确认 `.env` 的 `PA_DB_URL` 中用户名/密码正确。
- **构建安装包**：`scripts\build-release.bat`（需 MSVC + uv + Node；自动打包 sidecar → NSIS 安装包 + 更新签名 `.sig`）。
- **`tauri build` 下载 NSIS 超时（`timeout: global`）**：GitHub 不可达，先设代理 `set HTTPS_PROXY=http://127.0.0.1:10808`（端口换成你本地代理）再跑 `build-release.bat`；首次下载后缓存在 `%LOCALAPPDATA%\tauri\`。
