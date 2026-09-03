# PrivateAgent｜本地优先的桌面个人智能体

> 会话接手先读 [AGENTS.md](./AGENTS.md) 和 [共享项目状态记忆](./docs/project-state.md)。下文是基础工程概览；普通版、联网版测试包及生产部署状态请分别核对，不能只按本文版本号或能力描述判断。

PrivateAgent 是一款面向个人知识管理与代码项目的桌面 Agent，使用 Tauri 2、Vue 3 和 TypeScript 构建桌面工作台，使用 Python、FastAPI 和 SQLAlchemy 实现业务服务。项目提供普通版完整本机后端，以及联网版 `PrivateAgentRemote` 的“云端账号与模型服务 + 本机轻量执行器”两种交付方式。

普通版覆盖流式对话、混合 RAG、长期记忆、学习和任务管理；联网版将项目文件操作与测试、构建命令留在用户电脑，由服务器调用模型供应商。两种方式的能力、依赖和更新通道不同，不能把完整后端的全部功能视为联网版已经支持。

> 本文按 2026-08-31 的仓库源码核对。普通版基础版本为 `1.0.0`，源码 Alembic head 为 `0038`，主交付平台为 Windows 10/11 x64。联网版安装包版本由构建参数独立指定；仓库内有 [1.0.4 测试安装包记录](./docs/releases/remote-v1.0.4-test.1-20260831.md)，不代表当前生产部署或真实账号验收状态。

## 目录

- [项目概览](#项目概览)
- [交付方式与能力边界](#交付方式与能力边界)
- [核心能力](#核心能力)
- [项目亮点](#项目亮点)
- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [目录结构](#目录结构)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [测试与质量保障](#测试与质量保障)
- [构建与发布](#构建与发布)
- [安全与隐私](#安全与隐私)
- [当前交付边界](#当前交付边界)
- [开源许可与代码签名政策](#开源许可与代码签名政策)
- [常见问题](#常见问题)
- [文档导航](#文档导航)

## 项目概览

PrivateAgent 将日常信息管理、知识检索和 Agent 执行整合到同一个桌面工作台中：

- 对用户：提供邮箱验证码注册、用户名/邮箱登录，以及对话、知识库、项目、学习、任务、记忆、今日、集成、诊断、扩展和备份等工作区。
- 对 Agent：提供可编辑计划、工具审批、授权目录、白名单命令、多文件补丁、失败重试、回滚和执行证据。
- 对数据：完整后端使用 MySQL 存储业务数据、ChromaDB 存储向量；联网版本机执行器使用按服务器与账号隔离的 SQLite 保存项目、会话和执行记录。
- 对交付：提供完整 Python sidecar 和轻量执行器的独立打包入口，以及 Tauri/NSIS 安装包、更新清单、发布检查和签名流程。

## 交付方式与能力边界

| 对比项 | 普通版：完整本机后端 | 联网版：PrivateAgentRemote |
|---|---|---|
| 本机进程 | Tauri 启动完整 Python sidecar | Tauri 启动捆绑的 `private-agent-local.exe` |
| 模型调用 | 默认 Ollama，可显式配置远程 Provider | 本机通过 `/desktop/model/complete` 请求服务器，由服务器解析账号模型配置并调用供应商 |
| 项目执行 | 完整后端处理授权项目与工具任务 | 项目读取、文件写入和固定测试/构建命令在用户电脑执行 |
| 数据存储 | MySQL 业务数据、ChromaDB 向量及本机文件 | 项目文件与 SQLite 执行记录在本机；账号与模型配置在服务器 |
| 终端依赖 | 按场景配置 MySQL、Ollama 等服务 | 安装包自带执行器与 Python 运行时；无需另装 MySQL 或 Ollama，项目自身工具仍需安装 |
| 功能范围 | 下文完整后端能力，部分功能需要显式开启 | 以本机 `/capabilities` 为准；当前不支持 RAG 聊天、full_access、Git worktree、上下文预算/压缩 |
| 版本与更新 | 使用普通版配置及更新源 | 安装包使用独立应用标识、版本和更新源，不与普通版混用 |

联网版文件留在本机，但推理使用的提示词、代码片段和工具结果会发送给服务器及模型供应商，不能视为完全离线。项目和历史不会自动跨电脑同步。本机执行器不可用时项目请求直接报错，不回退到服务器处理本机路径。

上述边界可从[请求分流](./apps/desktop/src/services/localExecutor.ts)、[本机能力声明](./src/private_agent_local/app.py)、[本机存储](./src/private_agent_local/store.py)和[云端模型代理](./src/personal_assistant/api/routes_desktop_model.py)核对。

## 核心能力

第 1～6 项介绍完整后端的能力，是否可用还取决于配置开关与运行环境；第 7 项说明联网版当前的实现。功能源码、自动化测试、安装包构建和生产验收是不同证据，不相互替代。

### 1. Agent 工作台

- 以“理解任务 → 执行操作 → 整理结果 → 完成检查”组织执行计划，并把用户请求、Agent 回复、工具调用、引用来源和结果集中到活动时间线中。
- 工具卡片展示参数、风险、状态和输出；待审批期间阻止新任务交错写入，切换会话或重新加载后仍可恢复未决审批。
- 桌面端启动时读取 `/capabilities`：Agent Runtime 接管聊天后，新消息直接进入 `/chat/stream`，不会再先调用旧 `/tools/plan`；旧后端和 Runtime 关闭模式继续兼容原规划链。
- 左侧导航同时承载功能入口和最近任务，支持 `240px` 完整模式与 `72px` 紧凑模式。
- 右侧检查器提供 `Files`、`Context`、`Artifacts` 三个视图，用于授权路径、查看执行上下文和定位产物。
- 窗口宽度低于 `1320px` 时自动收起检查器，并支持键盘焦点、语义化状态和 `prefers-reduced-motion`。

### 2. 对话与模型 Provider

- 基于 SSE 的流式对话，支持多轮上下文、停止生成、会话历史、首轮自动标题和消息持久化。
- 多用户认证支持邮箱验证码注册、用户名或邮箱登录、会话撤销和账号停用；首个注册账号成为管理员，管理端可创建、检索和更新用户并查询审计日志。
- 注册验证码只持久化加盐摘要，具备有效期、重发间隔和失败次数限制；邮件通过可独立配置的 `smtp.env` / `PA_SMTP_*` 发送，SMTP 凭据不进入前端载荷。
- 默认关闭的持久化 Agent 聊天路径已接入 Ollama 原生 NDJSON delta；首个增量后不自动重试，工具回合先隔离中间草稿，最终完整回答仍持久化并可重连恢复。首次投影与并发重连通过 run 行锁和 `chat.output_persisted` 事件绑定同一 message，避免重复插入回答。
- 可信工作流启用 JSON Schema 或 RAG 引用验证时，统一模型契约会把同一固定 Schema 下发为 OpenAI Chat Completions `response_format`、Claude `output_config.format` 或 Ollama `format`；Provider 约束后仍由 Runtime 本地复核，能力不支持时在发起网络请求前失败关闭。
- 默认使用本地 Ollama；可显式启用 OpenAI-compatible 或 Claude Provider，并在远程调用前展示隐私范围。
- 对远程调用记录耗时、token 估算、失败分类和 fallback 信息；远程 Provider 异常时可降级到本地 Ollama。
- 健康检查覆盖 API、Ollama、MySQL 和 ChromaDB，后端在 Ollama 暂不可用时仍可启动并提供诊断。

### 3. 知识库与混合 RAG

- 支持 PDF、Word、Markdown、TXT 和常见 Python/JS/TS/Vue/Rust/Go/Java/C/C++/C# 代码文件导入，包含去重、结构优先切片、token 估算、向量化、失败重试、批量导入、启停控制和删除一致性。
- 组合 ChromaDB 向量召回与 MySQL FULLTEXT `ngram` 词法召回，经 RRF 融合后使用本地 embedding 批量语义重排。
- 检索支持文档类型、主题、标签、语言和项目过滤，并返回命中渠道、关键词、相关分数和原文引用。
- 版本化索引保留 PDF 页码、Markdown/DOCX 标题路径、Markdown 围栏代码块、DOCX 表格、字符/行范围、解析器版本和独立来源哈希；缺失或被篡改的来源记录拒绝参与版本化检索。
- 同时启用 Agent RAG 工具与输出验证时，引用验证只从本次 run 已成功持久化且通过 SHA-256 复核的检索工具结果加载证据；未知 chunk、伪造 quote 或被篡改的工具结果都会失败关闭。
- 同时再启用聊天 Runtime 后，`knowledge_base=true` 的兼容聊天进入同一 durable RAG 工具循环；候选 JSON 验证通过后才投影为旧 SSE 的可读答案与可信来源，任一开关未开启时仍回退旧 RAG 路径。
- 任一路召回或重排失败时保留可用链路，避免单点异常导致整个 RAG 不可用；无可靠内容时不编造来源。
- 提供文档集合、章节摘要、术语表、行动项、关键观点、代码片段抽取、文档对比和 Markdown 报告导出。

### 4. 项目 Agent 与受控编码

- 授权本地项目后，可浏览目录树、搜索文件名和内容、读取片段并查看 Git 状态与 diff。
- `propose_patch` 只生成有界变更建议，超长 diff 会显式标记截断；真正写入时校验授权路径和 `expected_old_sha256`，防止过期补丁覆盖新内容。
- 支持多文件 patch set、逐次审批、拒绝、失败诊断和回滚。
- 命令执行受白名单约束，仅允许 pytest、前端构建、Cargo check 等预定义命令，并对输出做长度控制和审计。
- 多步任务支持生成/编辑计划、批准整体计划、暂停、取消、继续、指定步骤恢复、失败重试和 Markdown 证据报告。

### 5. 学习、记忆与个人中枢

- 学习工作区支持学习路线、笔记、练习题、答题记录、复习卡片、错题本、掌握度和学习周报。
- 长期记忆支持创建、检索、编辑、禁用、删除和候选确认；敏感或禁用记忆不会被注入远程上下文。
- 今日工作台聚合提醒、收件箱、目标、简报、复习、失败活动、候选记忆和维护健康状态。
- 收件箱事项可转为任务或提醒；提醒支持一次性、每日、每周和每月规则，以及 snooze、完成和后台 tick。
- 目标支持优先级、状态、check-in 和跨对象关联，并可生成任务草稿或目标简报。

### 6. 数据治理与可扩展集成

- 全局搜索覆盖会话、文档、切片、任务、证据、记忆、收件箱、目标和简报，并提供最近搜索与命令面板。
- 快速捕获支持文本/剪贴板输入并转收件箱、提醒或记忆候选；OCR 任务使用独立队列和可诊断状态。
- 诊断中心汇总版本、健康、迁移、最近错误、Provider 失败、数据完整性和当前进程兼容路径计数，并可导出脱敏诊断包。
- 数据体检可发现软引用悬空、索引不一致等问题，先生成修复计划，再由用户确认执行。
- 扩展注册表统一管理 command、diagnostic 和 maintenance 扩展；ICS 日历导入提供预览、来源追踪和撤销能力。
- 备份包包含 manifest 和完整性信息，支持恢复预览、恢复演练和迁移 runbook。

### 7. 联网版本机执行与服务器管理

- 前端将 `/projects`、`/sessions`、`/agent-runs`、`/capabilities`、`/chat` 路径交给本机执行器，账号、模型与管理员接口使用服务器连接；路径分流不代表旧聊天接口的全部功能已实现。
- 本机请求校验 loopback Host、Origin 与每次启动生成的连接凭证；绑定服务器账号后，按服务器地址与用户标识隔离 SQLite 数据。
- 文件变更先展示 diff 并等待审批，执行前校验原文件 SHA-256；命令仅接受固定测试/构建入口，具有超时、输出上限和取消处理。进程重启后将未结束任务标记为失败，不自动重放不确定的写入或命令。
- 服务器模型代理复用账号模型配置与统一 ModelGateway，限制请求大小、消息/工具数量、并发和超时，并在客户端断开时取消推理。错误使用固定分类返回，不透传供应商异常正文。
- 管理端提供用户、模型相关管理入口与日志查看。日志接口仅管理员可访问，按固定来源读取有限尾部内容并脱敏，不接受任意文件路径。

## 项目亮点

1. 使用 Tauri 2、Vue 3、TypeScript 与 FastAPI 构建桌面 Agent，拆分桌面交互、业务服务和本机工具执行；联网版通过请求分流连接云端模型服务，并使用按账号隔离的 SQLite 保存本机执行记录。

2. 基于 FastAPI 与 SQLAlchemy Async 实现多用户 API，结合 scrypt 密码哈希、Bearer 会话摘要、数据归属过滤及管理员权限检查，实现邮箱验证码注册、会话撤销和用户数据隔离。

3. 组合 ChromaDB 向量召回、MySQL FULLTEXT/ngram 词法召回、RRF 融合与 embedding 重排，实现多格式文档检索；通过版本化索引、来源哈希和引用校验追溯回答依据，并保留检索失败时的降级路径。

4. 封装统一 ModelGateway 适配 Ollama、OpenAI-compatible 与 Claude，在完整后端实现 SSE 流式对话和持久化 Agent 执行，处理超时、有限重试、取消与重连恢复，并通过模型契约及本地结果验证约束输出。

5. 围绕授权目录、工具审批和执行记录实现受控编码流程，结合命令白名单、补丁预览与 SHA-256 校验防止越权访问和过期覆盖；完整后端支持多文件补丁及回滚，联网版在本机审批后执行文件变更。

6. 建立 pytest、Vitest、Playwright 与 Rust 检查流程，提供 PyInstaller、Tauri/NSIS 打包、独立更新通道及签名校验工具；结合健康检查、日志脱敏和发布证据报告，支持问题定位与交付核对。

这些亮点描述仓库中的工程实现，不包含未经测量的性能提升比例、用户规模或生产稳定性结论。

## 系统架构

### 普通版完整本机后端

```mermaid
flowchart LR
    UI["Tauri 2 + Vue 3<br/>桌面工作台"]
    Shell["Rust / Tauri<br/>sidecar 生命周期与端口协商"]
    API["FastAPI<br/>本地 API 与 SSE"]
    Agent["对话、任务规划<br/>工具审批与活动证据"]
    RAG["混合 RAG<br/>Vector + FULLTEXT + RRF + Rerank"]
    Workers["后台 Worker<br/>导入、OCR、项目扫描、提醒"]
    MySQL[("MySQL 8<br/>业务数据与审计")]
    Chroma[("ChromaDB<br/>本地向量索引")]
    Files["授权文件与项目目录"]
    LocalLLM["Ollama<br/>LLM / Embedding"]
    RemoteLLM["OpenAI-compatible / Claude<br/>显式启用与发送审计"]

    UI --> Shell --> API
    UI <-->|"HTTP / SSE"| API
    API --> Agent
    API --> RAG
    API --> Workers
    Agent --> LocalLLM
    Agent -. "可选" .-> RemoteLLM
    RAG --> LocalLLM
    RAG --> MySQL
    RAG --> Chroma
    Agent --> MySQL
    Workers --> MySQL
    Workers --> Chroma
    Workers --> Files
```

### 联网版云端模型与本机执行

```mermaid
flowchart LR
    UI["PrivateAgentRemote<br/>Tauri + Vue"]
    Local["本机轻量执行器<br/>FastAPI / Agent 循环"]
    Files["授权项目文件<br/>审批后写入与运行命令"]
    SQLite[("本机 SQLite<br/>账号隔离的项目与执行记录")]
    Server["服务器 FastAPI<br/>账号、模型配置、管理员接口"]
    Gateway["ModelGateway<br/>供应商适配与错误分类"]
    Provider["模型供应商"]

    UI -->|"本机项目请求 / 执行事件"| Local
    UI -->|"HTTPS：账号、模型与管理"| Server
    Local --> Files
    Local --> SQLite
    Local -->|"HTTPS：/desktop/model/complete"| Server
    Server --> Gateway --> Provider
```

### 关键数据流

| 场景 | 数据流 |
|---|---|
| 普通对话 | Vue → FastAPI SSE → Provider → 消息持久化 → 流式渲染 |
| 完整后端 RAG 问答 | 查询向量化 → 向量/词法双路召回 → RRF → embedding 重排 → 引用注入 → 回答 |
| 工具执行 | 计划工具 → 风险判断 → 用户审批 → 授权校验 → 执行 → 活动与证据入库 |
| 文档导入 | 授权文件 → 解析/切片 → MySQL 原文 → Chroma 向量 → ready/failed 状态 |
| 桌面启动 | Tauri 选择端口 → 启动 Python sidecar → 自动迁移 → `/health` 轮询 → 进入工作台 |
| 联网版启动 | Tauri 启动轻量执行器 → 本机健康检查 → 绑定服务器账号 → 打开该账号的 SQLite |
| 联网版项目任务 | 本机 Agent → 服务器模型代理 → 模型响应 → 本机工具检查/审批 → 执行结果留在本机 |

## 技术栈

| 层 | 技术 |
|---|---|
| 桌面端 | Tauri 2、Rust、Vue 3、TypeScript、Vite |
| UI 与交互 | Pinia、Vue Router、Ant Design Vue、Phosphor Icons、CSS Design Tokens、anime.js |
| API 与运行时 | Python 3.12+、FastAPI、Uvicorn、SSE、Pydantic Settings、Structlog |
| AI / Provider | LangChain、langchain-ollama、Ollama、OpenAI-compatible HTTP、Claude HTTP |
| RAG | ChromaDB、MySQL FULLTEXT/ngram、RRF、bge-m3 embedding 重排 |
| 完整后端数据层 | MySQL 8、SQLAlchemy 2 Async、aiomysql、Alembic |
| 联网版本机数据层 | Python sqlite3、SQLite WAL、按服务器与账号隔离的存储目录 |
| 文档处理 | pypdf、python-docx、Markdown、OCR Worker |
| 测试 | pytest、pytest-asyncio、Vitest、Vue Test Utils、Playwright、Cargo check |
| 构建发布 | uv、npm、PyInstaller、Tauri CLI、NSIS、updater、signtool（可选） |

> `langgraph` 已纳入依赖，但不能据此宣称使用 LangGraph 编排全部任务。完整后端保留旧聊天路径及按开关启用的持久化 Agent Runtime；联网版使用独立的本机 Agent 循环。

## 目录结构

```text
Agent/
├── apps/desktop/
│   ├── src/                   # Vue 工作台、组件、API、状态与动效
│   ├── e2e/                   # Playwright 浏览器模式 smoke
│   └── src-tauri/             # Rust 桌面壳、sidecar、NSIS 与 updater 配置
├── apps/exec-host/            # 完整后端编码执行相关的 Rust 执行宿主
├── src/personal_assistant/
│   ├── api/                   # FastAPI 路由
│   ├── core/                  # 领域服务、Repository、RAG、权限与任务编排
│   ├── agents/                # 持久化 Agent Runtime、审批、恢复和输出验证
│   ├── agent_v2/              # 编码工具协议、目录、策略与执行适配
│   ├── llm/                   # 统一模型网关及供应商适配
│   ├── mcp/                   # MCP 客户端、配置与工具管理
│   ├── workers/               # 导入、OCR、项目扫描等后台任务
│   ├── main_api.py            # FastAPI 应用入口
│   └── server_entry.py        # sidecar 启动与迁移入口
├── src/private_agent_local/   # 联网版轻量执行器、云端代理调用与 SQLite 存储
├── alembic/                   # MySQL 数据库迁移（当前 head: 0038）
├── tests/                     # 后端、RAG、治理、发布和升级测试
├── scripts/                   # 开发、构建、签名、发布检查与 smoke 脚本
├── deploy/                    # 服务端部署相关资源
├── docs/                      # 需求、阶段计划、使用和发布文档
├── pyproject.toml             # Python 项目与依赖规范
├── requirements.txt           # pip 兼容依赖清单
└── uv.lock                    # uv 锁文件
```

## 环境要求

以下要求适用于普通版源码开发与完整后端。联网版终端用户使用安装包时不需要安装 Python、MySQL 或 Ollama；开发、打包联网版仍需构建工具与依赖。

- Python 3.12 或更高版本，推荐使用 [uv](https://docs.astral.sh/uv/)
- Node.js 20 或更高版本
- MySQL 8.0+
- [Ollama](https://ollama.com/) 及所需模型
- Rust stable、MSVC Build Tools 和 WebView2（Tauri 开发/打包需要）

Windows 常用工具安装：

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

本节启动普通版开发环境。只需使用联网版的用户应使用对应安装包；联网版构建入口见[构建与发布](#构建与发布)。不要把终端项目目录配置成服务器上的工作目录。

### 1. 配置环境变量

```powershell
Copy-Item .env.example .env
```

源码开发时至少修改 `.env` 中的 `PA_DB_URL`。`.env` 已被 Git 忽略，请勿提交数据库密码、API key 或签名凭据；Windows 安装版不使用该明文密码路径。

### 2. 安装后端依赖

推荐使用锁文件：

```powershell
uv sync --extra dev
```

也可以使用 pip：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`pyproject.toml` 是 Python 依赖的规范来源；修改依赖时应同步 `requirements.txt` 并更新 `uv.lock`。

### 3. 执行数据库迁移

```powershell
uv run alembic upgrade head
uv run alembic current
```

当前源码 head 为 `0038`，迁移成功后预期输出包含 `0038 (head)`。此步骤会修改所配置数据库的结构，首次开发应使用专用开发库；已有数据的升级先按[数据库升级手册](./docs/database-upgrade-runbook.md)备份、演练。

### 4. 启动本地 API

```powershell
uv run uvicorn personal_assistant.main_api:app --reload --host 127.0.0.1 --port 8000
```

启动后可访问：

- `http://127.0.0.1:8000/health`：API、Ollama、MySQL 和 ChromaDB 健康状态
- `http://127.0.0.1:8000/docs`：OpenAPI / Swagger 文档

### 5. 启动桌面端

```powershell
Set-Location apps\desktop
npm ci
Set-Location ..\..
scripts\run-tauri-dev.bat
```

`run-tauri-dev.bat` 会定位 MSVC 环境、补充 Cargo PATH，并执行 `npm run tauri dev`。开发模式连接 `127.0.0.1:8000`；安装版由 Tauri 选择空闲端口并启动 sidecar。

### 6. 仅预览 Agent 工作台界面

```powershell
Set-Location apps\desktop
npm run dev
```

访问 `http://127.0.0.1:1420/?workspace-preview=running`。该入口仅在 Vite 开发模式下启用，使用本地预览数据，不改变生产数据路径或后端 API。

## 配置说明

下表为完整后端配置，默认值以 [`config.py`](./src/personal_assistant/config.py) 为准。本机轻量执行器的能力由自身实现声明，不能通过打开云端开关获得尚未实现的本机功能。

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `PA_API_HOST` | `127.0.0.1` | 本地 API 监听地址 |
| `PA_API_PORT` | `8000` | 开发模式 API 端口 |
| `PA_API_ALLOW_NON_LOOPBACK_BIND` | `false` | 仅允许经过认证的容器在自身网络命名空间绑定 unspecified wildcard；桌面/源码模式保持关闭 |
| `PA_API_TOKEN_FILE` | 空 | 可选容器 secret file；不能与 `PA_API_TOKEN` 同时配置 |
| `PA_ALLOW_PUBLIC_REGISTRATION` | `true` | 是否开放邮箱验证码注册；首个成功注册账号成为管理员，完成初始化后可关闭 |
| `PA_AUTH_SESSION_TTL_HOURS` | `168` | 登录会话有效期（小时） |
| `PA_CLAIM_LEGACY_DATA_ON_FIRST_USER` | `false` | 是否让首个管理员认领 owner 为空的旧数据；仅在可信迁移时开启 |
| `PA_DB_URL` | 无可用密码默认值 | 仅源码开发/测试使用的 MySQL async 连接字符串；安装版由 Rust 进程注入 |
| `PA_DB_PASSWORD_FILE` | 空 | 可选容器数据库密码文件；启用时 `PA_DB_URL` 不得再包含密码 |
| `PA_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama 地址 |
| `PA_LLM_MODEL` | `qwen2.5:14b-instruct-q4_K_M` | 默认对话模型 |
| `PA_EMBED_MODEL` | `bge-m3` | 默认 embedding 模型 |
| `PA_LLM_TEMPERATURE` | `0.7` | 生成温度 |
| `PA_LLM_CONTEXT_LENGTH` | `8192` | 上下文长度 |
| `PA_DATA_DIR` | 开发模式 `./data` | ChromaDB、日志等本地数据目录 |
| `PA_KB_ENABLED_BY_DEFAULT` | `false` | 新会话是否默认启用知识库 |
| `PA_AGENT_RUNS_API_ENABLED` | `false` | 开启持久化 AgentRun 开发 API；默认不改变旧入口 |
| `PA_CODING_PERMISSION_MODELS_ENABLED` | `false` | 启用编码模型配置能力；联网版模型配置需在服务器检查该开关 |
| `PA_CODING_AGENT_UI_ENABLED` | `false` | 完整后端对外声明编码界面能力；不替代联网版本机能力声明 |
| `PA_AGENT_RUN_READ_ONLY_TOOLS_ENABLED` | `false` | 向 Agent 注册 5 个 safe 无副作用工具及 2 个需审批的本地读取工具；与聊天 Runtime 同开时从旧 planner 排除这些工具 |
| `PA_AGENT_RAG_TOOLS_ENABLED` | `false` | 向 Agent 注册 4 个只读 RAG 工具（搜索、片段详情、文档详情、知识库列表）；模型按需调用，可按文档集合隔离 |
| `PA_AGENT_OUTPUT_VERIFICATION_ENABLED` | `false` | 对 Agent API 与兼容聊天的最终答案启用固定非空验证；失败候选不会发送给 UI |
| `PA_AGENT_OUTPUT_VERIFICATION_MAX_RETRIES` | `1` | 验证失败后的修正次数，范围 0–2；审批恢复不重置预算 |
| `PA_CHAT_AGENT_RUNTIME_ENABLED` | `false` | 让普通聊天进入持久化 AgentRuntime；RAG 工具与输出验证也开启时接管知识库请求 |
| `PA_CONVERSATION_SUMMARY_WORKER_ENABLED` | `false` | 在 schema 0017+ 上启动可追溯会话摘要 worker；保留原消息与来源哈希 |
| `PA_CONVERSATION_SUMMARY_ALLOW_REMOTE_PROVIDER` | `false` | 单独允许自动摘要把受预算约束的消息发送给已启用的远程 provider；本地 Ollama 不需要 |
| `PA_MCP_ENABLED` | `true` | MCP 注册表与客户端 API 默认开启；每个服务器仍需显式信任、启用和工具 allowlist |
| `PA_VERSIONED_RAG_INDEXING_ENABLED` | `false` | 在 schema 0021+ 使用带来源追溯的旁路版本构建；先于 retrieval 开启 |
| `PA_VERSIONED_RAG_RETRIEVAL_ENABLED` | `false` | 有 active head 的文档读取版本化索引，无 head 文档回退 legacy |
| `PA_VERSIONED_RAG_RETENTION_DAYS` | `14` | retired 索引版本的最短保留天数 |
| `PA_VERSIONED_RAG_MIN_RETIRED_VERSIONS` | `1` | 每文档至少保留的 retired 回滚版本数 |
| `PA_SMTP_HOST` | 空 | 注册验证码 SMTP 主机；为空时发送接口失败关闭 |
| `PA_SMTP_PORT` | `465` | SMTP 端口 |
| `PA_SMTP_USE_SSL` | `true` | 是否使用隐式 TLS；不能与 `PA_SMTP_STARTTLS` 同时开启 |
| `PA_SMTP_STARTTLS` | `false` | 是否在普通连接上升级 STARTTLS |
| `PA_SMTP_USERNAME` | 空 | SMTP 登录账号 |
| `PA_SMTP_PASSWORD` | 空 | SMTP 密码或授权码；应只写入不提交的 `smtp.env` 或进程环境 |
| `PA_SMTP_FROM_EMAIL` | 空 | 验证码邮件发件地址 |
| `PA_SMTP_FROM_NAME` | `PrivateAgent` | 验证码邮件发件人名称 |
| `PA_SMTP_TIMEOUT_SECONDS` | `15` | SMTP 连接和发送超时（秒） |
| `PA_LOG_LEVEL` | `INFO` | 日志级别 |

注册邮件建议从 `smtp.env.example` 复制生成本地 `smtp.env`，并仅填写真实 SMTP 配置；该文件已被 Git 忽略，不应提交授权码。服务器部署也可直接注入同名 `PA_SMTP_*` 环境变量。

运行时数据位置：

| 场景 | 配置 | 数据 |
|---|---|---|
| 源码开发 | 项目根目录 `.env` | 项目根目录 `data/` |
| 普通版 Windows 安装版 | `%APPDATA%\personal-assistant\.env`（仅非敏感字段和固定凭据引用） | `%APPDATA%\personal-assistant\`；秘密位于 Windows 凭据管理器 |
| 联网版 Windows 安装版 | 构建时指定 HTTPS 服务器，不注入供应商凭据 | Tauri 应用本地数据目录下的 `local-projects/<账号摘要>/projects.sqlite3`；项目文件仍位于用户选择的目录 |
| 可选 Compose | `.env.container`（只含 secret 路径和非敏感值） | MySQL/Chroma/Ollama 命名卷；秘密位于 `.secrets/` 挂载文件 |

普通版安装后可通过配置向导写入非敏感配置；其数据库、远程 Provider 和 MCP 凭据使用 Windows 原生凭据窗口与凭据管理器。MCP 数据库记录保存固定引用，支持 stdio secret env、HTTP Bearer 和受限 API-key header；新增或替换 MCP 凭据后需重启桌面 sidecar，缺失引用会失败关闭。联网版使用服务器账号和模型配置，不把供应商凭据打包进本机执行器。

## 测试与质量保障

### 常用验证命令

先按[测试指南](./docs/testing-guide.md)确认 `PA_TEST_DB_URL` 指向专用测试库，并与应用库 `PA_DB_URL` 隔离。全量 pytest 会加载测试配置和数据库 fixture，不能用于探测生产服务；迁移、RAG 数据审计和发布脚本也需先确认连接目标。历史测试数量不代表当前提交已通过验证。

```powershell
# 后端
uv run pytest -q
uv run alembic current

# 版本化 RAG：迁移默认只预览，评测命令只读
uv run python scripts/migrate_versioned_rag.py --limit 25
uv run python scripts/evaluate_rag.py --cases docs/examples/rag-evaluation-cases.example.json --retrieval versioned

# 实际语料审计：只输出聚合；canonicalization 仅生成干跑计划
uv run python scripts/profile_rag_data_quality.py --output data/analysis/rag-profile.json
uv run python scripts/validate_rag_data_quality.py --profile data/analysis/rag-profile.json --output data/analysis/rag-validation.json
uv run python scripts/plan_rag_canonicalization.py --output data/analysis/rag-canonicalization.json

# 前端类型检查、生产构建、组件测试与浏览器 smoke
Set-Location apps\desktop
npm run build
npm run test
npm run e2e
Set-Location ..\..

# Tauri / Rust
scripts\cargo-check-tauri.bat

# 联网版构建参数、环境过滤与更新清单测试，不生成安装包
node --test scripts/build-remote-client.test.cjs
```

### 发布前检查

```powershell
# 快速检查：pytest、前端构建、Cargo check、迁移状态
scripts\release-check.bat

# 完整证据链：pytest / Ruff / compileall / 前端构建与测试 / E2E / Rust check+test /
# sidecar smoke / 迁移 head / git diff / 诊断脱敏 / Compose 配置 / updater 清单
scripts\release-check-full.bat

# 由 release-check-<version>.json 生成/刷新发布 manifest（先跑完整检查，再刷新 manifest）
uv run python scripts/generate_release_manifest.py --write
```

完整检查会在 `dist/` 生成 `release-check-<version>.json`（机器事实源）和 `release-check-<version>.md`，记录 commit、schema、各步骤状态、耗时和错误摘要；release manifest 的 validation checklist 由该报告步骤结果生成，不人工勾选。测试覆盖包括：

- 对话 SSE、RAG、文档导入和检索降级
- 授权路径、路径穿越、审批状态机、工具调用和补丁写入
- 学习、记忆、任务、提醒、目标、简报和今日聚合
- Provider 错误分类、隐私审计、诊断脱敏和数据完整性
- 备份恢复、扩展注册、ICS 导入、性能阈值、发布签名和升级 smoke
- Vue 组件、响应式交互、后端断开场景和 Playwright 浏览器 smoke

## 构建与发布

### 构建 Python sidecar

以下两个入口用于普通版完整后端及桌面包，不能代替联网版构建。

```powershell
scripts\build-sidecar.bat
```

### 构建 Windows 安装包

```powershell
scripts\build-release.bat
```

### 构建联网版客户端

[`build-remote-client.cmd`](./scripts/build-remote-client.cmd) 会调用独立构建脚本，打包本机轻量执行器并设置 `VITE_API_BASE_URL`、`VITE_LOCAL_EXECUTOR=true`。安装包模式生成独立的 `PrivateAgentRemote` 标识、版本与更新配置，不修改普通版版本号。

```powershell
# 查看参数，不构建、不上传
node scripts/build-remote-client.cjs --help

# 仅检查示例参数；实际构建时替换为自己的 HTTPS 源站和版本
node scripts/build-remote-client.cjs "https://api.example.com" --preview-installer --version 1.0.4 --dry-run
```

`--preview-installer` 生成手动安装测试包，不生成更新清单；`--release` 要求干净工作区与 updater 签名配置。真正构建需已安装桌面依赖、MSVC/Rust，以及 `.venv` 内的 PyInstaller 和执行器依赖，产物输出到新的 `.run/remote-client-*` 目录。脚本不会自动上传或发布；完整流程见[远程客户端更新](./docs/remote-client-updates.md)。

### 可选容器后端

容器模式可作为远程多用户服务端：它使用 Compose secret files、非 root/只读 API 容器、宿主 loopback 端口、MySQL/Chroma 持久卷和可选的 NVIDIA Ollama profile。公网入口由同机 HTTPS 反向代理提供。当前联网版同时需要云端服务和捆绑的本机执行器，仅设置 `VITE_API_BASE_URL` 不能代替完整联网版构建：

```powershell
Copy-Item .env.container.example .env.container
uv run python scripts/generate_container_secrets.py --yes
docker compose --env-file .env.container --profile ollama-gpu config --quiet
docker compose --env-file .env.container up --detach --build
```

需要容器化 Ollama 时，将 `.env.container` 中的地址改为 `http://ollama:11434`，并在启动命令加入 `--profile ollama-gpu`。完整的 TLS 反向代理、首个管理员注册、客户端远程 URL、日志保留、备份和停止方式见 `docs/deployment-guide.md` §8。

CentOS Stream 9 裸机部署（Uvicorn + Supervisor + Nginx）见[部署说明](./docs/centos-stream9-deployment.md)，后续源码更新与进程加载路径检查见[服务器更新流程](./docs/server-code-update-workflow.md)。拉取源码不等于运行副本已经更新，需核对解释器、模块解析路径和服务重启结果。项目是 FastAPI/ASGI 应用，不能直接由 uWSGI 的 WSGI 加载器托管。

构建流程包含 sidecar 打包、MSVC 检测、Tauri/NSIS 构建、可选 Authenticode 签名、updater 签名和发布清单生成。主要产物：

```text
apps/desktop/src-tauri/target/release/bundle/nsis/
dist/release-manifest-<version>.md
dist/codesign-status-<version>.json
dist/latest.json
```

没有配置代码签名证书时仍可生成安装包，但发布状态会明确记录 `code_signed: no`，Windows SmartScreen 可能显示未知发布者。详细流程见：

- `docs/release-checklist.md`
- `docs/signing-and-keys.md`
- `docs/cross-platform.md`

### Windows 卸载

在 Windows“设置 → 应用 → 已安装的应用”中选择 `PrivateAgent` 并点击“卸载”，或从开始菜单运行卸载程序。默认卸载会移除应用程序文件，但保留 `%APPDATA%\personal-assistant` 中的配置和用户数据，防止误删知识库；如需完全清除，请先备份，再由用户手动删除该数据目录。

## 安全与隐私

- 本地 API 默认只监听 loopback，不应直接暴露到公网。
- 文件访问限制在已授权目录内，校验项目相对路径与实际解析位置，拒绝路径穿越和未授权访问。
- 默认审批模式下，写文件、运行命令、应用补丁和高风险任务步骤需要用户确认。完整后端的特殊权限模式需另查配置；联网版只声明 `readonly` / `confirm`，不支持 full_access。
- 补丁写入前校验旧内容哈希，降低并发修改和过期补丁覆盖风险。
- 普通版的可选远程 Provider 默认关闭；联网版依赖云端模型调用，提示词、选取的代码片段及工具结果可能离开本机。
- 注册验证码仅保存加盐摘要；登录会话仅保存 token 摘要，注销或账号停用后拒绝继续访问。
- 敏感记忆不会注入远程上下文，设置接口不回显原始 API key。
- 普通版 Windows 凭据配置使用系统原生凭据窗口和凭据管理器；联网版供应商凭据由服务器管理，本机执行器不持有供应商 Key。登录会话令牌仍属于敏感数据，不应写入日志。
- 当前基础 Tauri 配置的 `app.security.csp` 为 `null`，不能宣称已启用 CSP 防护；本机 API 的 Host、Origin 和启动凭证检查不能替代 CSP。
- 固定命令入口不构成操作系统沙箱：项目测试和构建脚本以当前系统用户权限运行，可能读写该用户可访问的文件并联网，只应批准可信项目。
- 诊断包默认不导出数据库密码、API key、完整聊天、文档原文或敏感记忆。
- `.env`、Tauri updater 私钥、PFX 证书、密码文件和其他凭据不得提交到仓库。
- 容器部署的 `.env.container` 只保存 secret 文件路径；`.secrets/` 中的 API/MySQL 秘密不得提交、复制进镜像或写入 Compose 展开结果。

## 当前交付边界

- 本文反映源码与仓库文档，未将历史测试成绩或安装包记录视为当前生产验收；联网版 1.0.4 的具体证据与未验收项见[交付记录](./docs/releases/remote-v1.0.4-test.1-20260831.md)。
- Windows NSIS、Python sidecar、动态端口、发布清单、updater、无证书透明策略和自动化检查已实现。
- Windows 真实 `v0.1.2 → v0.2.0` 安装升级、数据保留、卸载/重装回滚和 updater 签名负面验证已完成（2026-08-05，升级 smoke run #26）。GitHub Release 真实远程 updater 交付仍需仓库发布权限后以真实远程资产补一次 smoke；当前本地镜像证据不代表已部署生产 Release。
- 可选容器后端已有锁定镜像、Compose secrets、loopback 发布、持久卷、多用户会话与审计；公网仍必须由外部 HTTPS 反向代理终止 TLS，当前不包含代理容器或证书自动化。容器 GPU profile 的真实 GPU healthcheck 尚未完成（见 `docs/archive/planning/remaining-work-plan-20260806.md` §5.2）。
- Authenticode 签名逻辑已接入，但正式证书实签需要在发布环境执行；当前如实标记 `unsigned`，SmartScreen 可能显示未知发布者。
- macOS/Linux 的数据目录适配、构建脚本和发布清单结构已准备，尚未完成实机构建与 smoke，因此当前不宣称正式跨平台交付。
- `externalBin` 变化后，同版本覆盖安装应先完成真实验证；未验证前建议卸载旧版本再安装新包。

## 开源许可与代码签名政策

PrivateAgent 采用 [Apache License 2.0](LICENSE) 发布。隐私与可选网络访问边界见 [隐私政策](PRIVACY.md)。

### Code signing policy

Free code signing is provided by [SignPath.io](https://signpath.io/), with a certificate provided by the [SignPath Foundation](https://signpath.org/). 代码签名仅覆盖从本公开仓库、由 GitHub 托管执行器按入库工作流构建的 PrivateAgent 发布产物；每个签名请求均需人工批准。团队角色、可信构建、密钥隔离和事件处置规则见 [Code signing policy](CODE_SIGNING_POLICY.md)。

普通版基础配置指向本仓库的 [GitHub Releases](https://github.com/lkuliuying/PrivateAgent/releases)。联网版构建可独立指定更新清单与下载地址；测试包、草稿和正式更新源需分别核对，不能跨通道使用安装包或清单。

## 常见问题

- `UnicodeDecodeError: 'gbk'`：在 PowerShell 中设置 `$env:PYTHONUTF8='1'` 后重试。
- MySQL `Access denied`：源码开发检查项目 `.env` 的 `PA_DB_URL`；Windows 安装版在连接配置向导中重新输入系统凭据并核对主机、端口、用户名和数据库名。
- `link.exe not found`：安装 MSVC Build Tools，并使用 `scripts\run-tauri-dev.bat`。
- `tauri build` 首次下载 NSIS 超时：确认 GitHub 网络可达，必要时为当前终端配置 `HTTPS_PROXY`。
- Ollama 状态异常：确认 `ollama serve` 正在运行，并已拉取对话模型和 `bge-m3`。`/health` 的 `ollama` 项
  会区分服务未启动（`ollama_not_running`）/ 超时（`ollama_timeout`）/ 模型缺失（`missing_models`），
  详见 `docs/ollama-lifecycle.md`；可运行 `uv run python scripts/ollama_lifecycle_check.py` 自查。
- `uv` 缓存无权限：把 `UV_CACHE_DIR` 指向当前用户可写目录后重试。
- 联网版本机执行器未就绪：确认安装包内执行器存在并正常启动；不要把项目请求回退到服务器，也不要用浏览器预览代替本机执行验证。
- 联网版提示模型能力关闭、未配置或调用失败：检查服务器模型开关、当前账号的默认模型及供应商配置，再核对运行进程实际加载的代码；错误分类和修复记录见[模型请求修复说明](./docs/solutions/2026-08-31-model-502-admin-timezone.md)。

## 文档导航

- [文档中心](./docs/README.md)：按任务查找使用、开发、运维和历史记录
- [共享项目状态记忆](./docs/project-state.md)：带日期的交接快照，使用时须与当前代码核对
- [联网版 1.0.4 交付记录](./docs/releases/remote-v1.0.4-test.1-20260831.md)：测试包证据与未验收项
- [服务器代码更新流程](./docs/server-code-update-workflow.md)：源码入口、更新检查与回退边界
- [远程客户端更新](./docs/remote-client-updates.md)：联网版构建、签名与独立更新通道
- `docs/usage-guide.md`：最终用户与开发者完整使用说明
- `docs/requirements.md`：项目需求基线与已落地范围
- `docs/archive/phases/phase2-requirements.md` ～ `docs/archive/phases/phase8-requirements.md`：阶段需求
- `docs/archive/phases/phase1-plan.md` ～ `docs/archive/phases/phase8-plan.md`：阶段开发与验收计划
- `docs/release-checklist.md`：安装、升级、发布和回滚检查清单
- `docs/signing-and-keys.md`：updater、代码签名和密钥治理
- `docs/cross-platform.md`：Windows、macOS、Linux 平台状态与差异
- `docs/database-upgrade-runbook.md`：全库克隆、schema 升级、RAG 小批 rollout 与回滚
- `docs/agent-runtime.md`：持久化 Agent Runtime、ModelGateway、事件、恢复和 LangGraph 决策
- `docs/tool-system.md`：ToolSpec、权限、审批和 durable execution
- `docs/context-design.md`：上下文优先级、预算、信任边界和会话摘要
- `docs/memory-design.md`：结构化记忆、版本、冲突、候选和语义索引
- `docs/rag-design.md`：legacy/versioned RAG、真实数据质量和上线门禁
- `docs/ollama-lifecycle.md`：Ollama 外部交付模式的安装检测、故障分类与测量基线
- `docs/mcp-design.md`：MCP 客户端、审批、安全边界、回滚与未完成项
- `docs/database-design.md`：MySQL/Chroma 职责、迁移、一致性和数据保留
- `docs/security-model.md`：本地 API、凭据、工具、RAG、MCP、CSP 与发布威胁模型
- `docs/testing-guide.md`：后端、前端、Rust、迁移、RAG 和发布验证
- `docs/deployment-guide.md`：开发启动、Windows 交付、分阶段启用和回滚
- `docs/api-reference.md`：API 安全约束、端点分组和现代化能力边界
- `docs/troubleshooting.md`：启动、认证、Ollama、RAG、MCP 和构建故障排查
- `docs/archive/ui/personal-agent-ui-refactor-prompt.md`：Agent 工作台界面重构说明
