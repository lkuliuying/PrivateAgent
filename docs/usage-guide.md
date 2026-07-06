# 私人助手 Agent · 项目详细使用说明书

> 版本：v0.1 · 日期：2026-07-04
> 对应需求：`docs/requirements.md` v0.1 · 对应计划：`docs/phase1-plan.md` v0.3

---

## 阅读指引

本说明书面向两类读者，提供两条阅读路径：

- **最终用户**（希望在自己电脑上运行私人助手的个人学习者、技术用户、重隐私用户）：阅读 **第 1–5 章**，即可完成环境准备、首次配置、日常使用与故障排查。
- **开发者**（希望理解架构、二次开发、打包发布的工程师）：阅读 **第 6–12 章 + 附录**，涵盖架构概览、目录结构、开发环境搭建、开发启动、打包发布、测试与扩展点。

## 进度说明

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M0 | 环境与骨架：Tauri+Vue / FastAPI / MySQL+Alembic / Ollama+ChromaDB 连通，`/health` 全绿 | 已完成 |
| M1 | 对话助手：流式 SSE、多轮上下文、停止生成、首轮自动标题、会话历史持久化 | 已完成 |
| M2 | 知识库 RAG：导入 PDF/Word/MD/TXT、切分、向量化、检索、来源引用、删除一致性、失败重试 | 已完成 |
| M3 | 设置与打磨：设置/状态页、参数持久化、结构化日志、错误提示、pytest 基础测试 | 已完成 |
| M4 | 打包预研：Tauri sidecar + 端口协商 + PyInstaller 打包可行性验证 | 已完成 |
| 第二阶段 | 四区工作台 UI + 受控工具调用（审批状态机）+ 授权路径 + 文件/知识库增强 + 活动流 | 已完成 |
| 第三阶段 M0–M6 | 项目工作区 + 混合检索 + 学习系统 + 文档工作台 + 编码修改（补丁审批写入）+ 白名单命令执行 + 多步任务编排 + 六入口导航 | 已完成 |
| 第五阶段 | 完整安装包 / 依赖检测向导 / 配置 UI / 自动更新预研 / 跨平台 / 体积优化 | 部分完成（见下） |

第五阶段已实现：NSIS 安装包、首启依赖检测向导、连接配置 UI、sidecar 生命周期与端口协商、Tauri updater 命令接线。尚未完成：updater 发布源与签名密钥部署、跨平台（macOS/Linux）、onedir 体积优化。文中涉及尚未完成的部分仍标注「（第五阶段规划，尚未实现）」。

## 第三阶段新增能力（M0–M6）

第三阶段把产品从「受控工作台助手」升级为「学习 + 文档 + 编码」个人 Agent。导航由四入口扩展为六入口：聊天 / 知识库 / 项目 / 学习 / 任务 / 设置。

- **项目工作区（M1）**：在「项目」页授权一个代码项目目录，助手后台扫描目录树（自动忽略 `.git`/`node_modules`/`__pycache__` 等），提供目录树浏览、文件名/内容搜索（正则）、文件片段读取、git 状态/diff 查看。默认读取能力只读；写入与命令执行必须走 M5 审批工具。`rel_path` 越界访问被拒绝（403）。
- **混合检索（M2）**：知识库检索同时使用向量相似度与关键词子串匹配，RRF 融合后可插拔 rerank。引用来源展示命中关键词与分数；禁用文档在两路召回中均被排除。文档支持 `doc_type`/`topic`/`tags`/`language` 元数据筛选与编辑。
- **学习系统（M3）**：在「学习」页创建学习主题，助手基于知识库资料生成学习路线、练习题、复习卡片，并批改答题记录掌握程度。四标签页：路线 / 笔记 / 练习 / 卡片（翻卡复习）。
- **文档工作台（M4）**：知识库页支持文档多选对比（共同点/差异/冲突/阅读顺序）、单文档章节摘要与术语表、对比结果导出 Markdown（须授权目录）、生成笔记重新入库。
- **编码修改与命令验证（M5）**：`propose_patch` 只生成 diff，不写文件；`apply_patch_to_workspace` 审批后写入授权项目文件，并用 `expected_old_sha256` 防止应用过期补丁；`run_whitelisted_command` 只允许 `pytest`、`python -m pytest`、`npm run build`、`cargo check` 等白名单命令，输出会截断保存。
- **多步任务编排（M6）**：任务页支持创建计划、按步骤运行工具、在高风险步骤暂停等待批准、失败步骤重试、查看每步证据，并在完成后生成可复制的 Markdown 报告。

高风险操作（写文件、跑命令、多步任务）已经按 M5/M6 开放，仍坚持审批边界。

---

# 第一部分 · 最终用户指南（第 1–5 章）

---

## 第 1 章 · 简介与定位

### 1.1 产品一句话定义

私人助手 Agent 是一个 **本地优先、隐私可控的桌面私人助手**：它运行在你的个人电脑上，默认情况下你的对话、文档、会话历史全部保存在本机，不上传云端。

### 1.2 第一阶段目标

第一阶段聚焦两件事：

1. **稳定对话**：多轮上下文、流式输出、停止生成、会话历史持久化。
2. **本地知识库问答**：导入本地文档，基于文档回答并标注来源。

### 1.3 目标用户

| 用户类型 | 特征 | 关注点 |
|---|---|---|
| 个人学习者 | 有大量 PDF、Word、Markdown、TXT 资料 | 快速问资料、总结知识、保留历史 |
| 开发 / 技术用户 | 能接受本地模型、数据库、依赖配置 | 可控、可扩展、可调试 |
| 重隐私用户 | 不希望资料默认上传云端 | 本地存储、明确上云提示 |

### 1.4 核心能力清单

- 桌面应用（Tauri + Vue 3），不是浏览器网页。
- 流式多轮聊天，会话历史持久化，关闭重开后可恢复。
- 首轮对话后自动生成简短会话标题（失败回退为「新对话」）。
- 导入 PDF / Word / Markdown / TXT 文档，切分、向量化、入库。
- 启用知识库后，基于本地文档回答并标注来源（文档名 + 片段序号）。
- 运行状态诊断：本地后端 / Ollama / MySQL / ChromaDB 四项实时状态。
- 设置页调整温度、上下文长度、默认是否启用知识库，参数持久化。
- 打包后端为 Tauri sidecar，桌面应用启动时自动拉起后端（M4 已验证）。

### 1.5 本地优先隐私承诺

- 默认不上传文档、会话、切片到云端。
- 后续若启用云端模型，UI 会明确提示数据会上云。
- 第一阶段只实现本地 Ollama；OpenAI / Claude 字段仅在配置结构中预留，UI 不承诺完整切换。

---

## 第 2 章 · 环境准备

### 2.1 依赖关系总览

私人助手依赖三个外部组件，缺一不可：

```
┌──────────────────────────────────────────────┐
│            桌面应用（Tauri + Vue）             │
└──────────────────┬───────────────────────────┘
                   │ HTTP + SSE（localhost）
┌──────────────────▼───────────────────────────┐
│        本地后端（FastAPI，打包为 sidecar）      │
└──────┬───────────────────────┬───────────────┘
       │                       │
       ▼                       ▼
   Ollama 服务               MySQL 8
   LLM + Embedding          业务数据存储
   qwen2.5:14b-instruct     sessions/messages
   bge-m3                   documents/chunks
                            settings
       │
       ▼
   嵌入式 ChromaDB
   向量存储（后端进程内）
```

| 依赖 | 作用 | 必需 |
|---|---|---|
| Ollama + 模型 | 提供 LLM 对话与文本向量化能力 | 是 |
| MySQL 8 | 存储会话、消息、文档元数据、切片原文、设置 | 是 |
| 桌面应用 | 用户交互界面，并（打包模式）拉起后端 | 是 |

### 2.2 Ollama 安装与模型拉取

1. 从 Ollama 官网安装 Ollama。
2. 拉取对话主模型与嵌入模型：

```bash
ollama pull qwen2.5:14b-instruct-q4_K_M
ollama pull bge-m3
```

- `qwen2.5:14b-instruct-q4_K_M`：14B 参数 Q4 量化对话模型，4070(12G)+32G 内存可运行。
- `bge-m3`：中文检索质量好的嵌入模型，用于知识库向量化与检索。

> 提示：若 14B 模型在你的显存上偶尔 OOM，可降级使用 7B 模型，并适当限制上下文长度。

### 2.3 MySQL 8 安装与建库

1. 安装本机 MySQL 8.0+。
2. 创建数据库（字符集必须为 `utf8mb4`）：

```sql
CREATE DATABASE personal_assistant CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

3. 准备一个可访问该库的 MySQL 账号与密码（默认示例使用 `root`）。

### 2.4 桌面应用获取

桌面应用有两种获取方式：

| 方式 | 适用 | 说明 |
|---|---|---|
| 开发模式 | 开发者 | 从源码运行，`scripts\run-tauri-dev.bat` 启动，前端连手动启动的后端 |
| 打包模式 | 最终用户 | 安装 NSIS 安装包，桌面应用启动时按需拉起 sidecar 后端，首启引导配置连接（第五阶段已实现） |

> 一键构建 NSIS 安装包：`scripts\build-release.bat`（详见第 10 章）。安装包未签名，首次运行可能触发 SmartScreen，点「更多信息 → 仍要运行」绕过。

---

## 第 3 章 · 首次配置

### 3.1 配置文件位置对照表

后端通过 `.env` 文件读取配置，开发模式与打包模式位置不同：

| 模式 | 配置文件位置 | 说明 |
|---|---|---|
| 开发模式 | 项目根 `.env`（从 `.env.example` 复制） | 便于调试，与代码同目录 |
| 打包模式 | `%APPDATA%\personal-assistant\.env`（Windows） | 用户数据目录，由首启配置向导自动写入（第五阶段已实现） |
| 打包模式（类 Unix） | `~/.local/share/personal-assistant/.env` | Linux / macOS |

> 后端通过 `sys.frozen` 判断当前模式：打包模式读用户数据目录下的 `.env`（不存在则用代码默认值），开发模式读项目根 `.env`。

### 3.2 配置项逐一说明

从 `.env.example` 复制 `.env` 后，按本机实际情况修改。所有变量统一以 `PA_` 前缀：

| 变量 | 说明 | 示例 / 默认 |
|---|---|---|
| `PA_API_HOST` | 后端监听地址 | `127.0.0.1` |
| `PA_API_PORT` | 后端监听端口（开发模式固定 8000；打包模式由 Tauri 通过 `PA_API_PORT` 注入） | `8000` |
| `PA_DB_URL` | MySQL 异步连接串，驱动用 `aiomysql`（纯 Python） | `mysql+aiomysql://root:YOUR_PASSWORD@127.0.0.1:3306/personal_assistant?charset=utf8mb4` |
| `PA_OLLAMA_BASE_URL` | Ollama 服务地址 | `http://127.0.0.1:11434` |
| `PA_LLM_MODEL` | 对话主模型名 | `qwen2.5:14b-instruct-q4_K_M` |
| `PA_EMBED_MODEL` | 嵌入模型名 | `bge-m3` |
| `PA_LLM_TEMPERATURE` | 对话温度（0~1） | `0.7` |
| `PA_LLM_CONTEXT_LENGTH` | 上下文长度 | `8192` |
| `PA_KB_ENABLED_BY_DEFAULT` | 聊天页知识库开关默认值 | `false` |
| `PA_DATA_DIR` | 数据目录（chroma/logs 派生于此）。开发默认 `./data`，打包默认用户数据目录；留空用默认，仅在需强制指定时设置 | （留空） |
| `PA_LOG_LEVEL` | 日志级别 | `INFO` |

**最少必须修改的项**：把 `PA_DB_URL` 中的 `YOUR_PASSWORD` 改为本机 MySQL 的实际密码。

### 3.3 首次启动引导与依赖检测（第五阶段已实现）

打包模式首次启动（或配置缺失时），应用进入连接配置向导，分两步：

1. **环境检测**：探测本机默认端口的 MySQL（127.0.0.1:3306）与 Ollama（127.0.0.1:11434）是否可达，未检测到会提示先启动对应服务。
2. **填写连接**：录入 MySQL 主机/端口/用户名/密码/库名、Ollama Base URL、LLM 与嵌入模型名。
   - 「测试连接」：探测 MySQL TCP 连通 + Ollama `/api/tags`，并校验所填模型是否已 `ollama pull`；模型缺失会提示拉取命令。
   - 「保存并启动后端」：写入 `%APPDATA%\personal-assistant\.env`，启动 sidecar 并轮询 `/health`，**仅当 MySQL 与 Ollama 都就绪**才进入主界面；否则提示超时，可重试或重新配置。

> 开发模式（`tauri dev`）下不拉起打包 sidecar，自动回退到手动后端 `127.0.0.1:8000`，顶部显示 `DEV · 手动后端 8000` 标记；向导不会出现。

### 3.4 重新配置连接（第五阶段已实现）

运行中可在「设置 / 状态」页点「重新配置连接」再次打开向导。保存后**重启应用**以让 sidecar 重新加载 `.env`。

### 3.5 首次启动验证

启动桌面应用后，进入「设置 / 状态」页，确认运行状态四项全绿：

- 本地后端 API 正常
- Ollama 正常
- MySQL 正常
- ChromaDB 正常

四项全绿即表示环境就绪，可开始使用。任意一项不可用，状态页会显示红色「不可用」；若后端完全未连接，会显示「⚠ 本地后端未连接，无法获取状态」。排查方法见第 5 章。

---

## 第 4 章 · 日常使用

### 4.1 界面总览

第二阶段起，桌面应用采用「四区工作台 + 底部状态栏」布局：

```
┌────┬────────────┬──────────────────────┬──────────────┐
│导航│  列表区     │  主工作区             │  右检查器     │
│rail│（仅聊天页）│  ┌──────────────────┐ │（可折叠）     │
│    │  会话列表   │  │ 顶部标题栏        │ │ 当前会话上下文│
│ 💬 │  · 会话A   │  ├──────────────────┤ │ 引用片段详情  │
│ 📚 │  · 会话B   │  │ 聊天/知识库/任务/ │ │ 文件授权      │
│ ✅ │            │  │ 设置 视图         │ │ 会话活动      │
│ ⚙ │            │  │                  │ │              │
├────┴────────────┴──────────────────────┴──────────────┤
│ 状态栏：API · Ollama · MySQL · ChromaDB · 模型 · 任务   │
└──────────────────────────────────────────────────────┘
```

- **导航 rail（最左）**：四个主入口——聊天 💬、知识库 📚、任务 ✅、设置 ⚙。
- **列表区**：仅聊天页显示会话列表；其他页隐藏，主工作区占满。
- **主工作区**：顶部标题栏 + 当前视图内容（聊天/知识库/任务/设置）。
- **右检查器（可折叠）**：聊天页显示当前会话上下文、引用片段详情（点击对话中的来源引用查看原文）、文件授权、授权文件摘要、授权目录扫描、会话活动流。宽屏（≥1100px）可切换，窄屏自动收起避免挤压。
- **底部状态栏**：API / Ollama / MySQL / ChromaDB 四项状态点 + 当前模型 + 任务状态，每 5 秒刷新。
- **四视图**：聊天（chat）、知识库（kb）、任务（tasks）、设置（settings），点击导航 rail 切换。

### 4.2 聊天与会话管理

#### 新建会话
点击左侧栏「+ 新建」按钮。新会话标题默认为「新对话」。

#### 发送消息
- 在底部输入框输入消息，按 **Enter** 发送。
- 按 **Shift + Enter** 换行。
- 发送按钮在输入为空时禁用。

#### 流式输出
发送后，助手回复会以流式方式逐 token 显示，末尾带闪烁光标 `▍` 表示正在生成。

#### 停止生成
生成过程中，「发送」按钮变为红色「停止生成」按钮，点击可中断当前生成。已生成的部分内容会被保存到该会话（后端在连接断开时保存已生成部分）。

#### 首轮自动标题
首轮对话（用户发送第一条消息并收到助手完整回复）后，后端基于首轮内容自动生成一个不超过 12 个字的简短中文标题，会话列表实时更新。生成失败时回退为「新对话」。

#### 切换会话
点击左侧栏任一会话项即可切换。切换时会加载该会话的全部历史消息。生成进行中不允许切换会话。

#### 历史恢复
关闭应用后再次打开，左侧栏会列出全部历史会话（按最近更新时间排序），点击即可恢复查看之前的对话记录。

### 4.3 知识库导入

#### 支持的格式
| 格式 | 扩展名 | 解析方式 |
|---|---|---|
| PDF | `.pdf` | pypdf 提取文本 |
| Word | `.docx` | python-docx 提取段落 |
| Markdown | `.md` / `.markdown` | 纯文本读取 |
| 纯文本 | `.txt` | 纯文本读取 |

**扫描件 PDF 暂不支持**（第一阶段未集成 OCR）：后端会检测每页可提取文本量，平均每页过少时判定为扫描件并返回明确错误「暂不支持扫描件 PDF」。

#### 导入流程
进入「知识库」视图，点击「+ 导入文档」按钮选择文件。导入后文档进入后台处理，列表每 3 秒自动刷新状态。

#### 文档状态机
每个文档经历以下状态流转：

```
pending（等待中） → processing（处理中） → ready（已就绪）
                         │
                         └→ failed（失败，记录原因，可重试）

任意状态 → deleting（删除中） → 列表移除
```

处理流程：解析文本 → 切分（每片约 500 字符，相邻片重叠 80 字符）→ 向量化（bge-m3）→ 切片原文入 MySQL → 向量入 ChromaDB → 标记 ready。

#### 列表信息
每个文档卡片展示：文件名、状态、文件大小、切片数量、嵌入模型名；失败时额外展示失败原因。

#### 失败重试
状态为 `failed`（或 `pending`）的文档可点击「重试」按钮重新导入。重试会先清理可能残留的旧切片数据，再重新走完整导入流程。仅 `failed` / `pending` 状态可重试。

#### 删除与同步清理
点击「删除」按钮（需二次确认）。删除时：先将状态置为 `deleting` → 删除 ChromaDB 中该文档的全部向量 → 删除 MySQL 中文档记录（级联删除 doc_chunks）→ 清理上传的原始文件。删除后列表不再显示该文档，检索也不再返回其内容。

#### 重复导入检测
导入时后端计算文件内容的 SHA-256 哈希（`content_hash`）。若已有相同哈希的文档，返回 `409` 并提示「文档已导入过（文件名，状态: xxx）」，避免重复入库。

### 4.4 RAG 问答

#### 知识库开关
聊天页输入区左侧有「📚 知识库」开关复选框。开启后高亮显示。

#### 检索流程
开启知识库后发送问题，后端先对问题做嵌入，在 ChromaDB 中检索最相关的 top-5 切片，再从 MySQL 回查切片原文与文档名，注入到 system prompt 中作为「参考资料」。

#### 来源引用
回答下方展示来源引用，格式为 **`文档名 · 片段{序号}`**，多个来源以分号分隔。例如：`使用说明书.md · 片段3；使用说明书.md · 片段7`。

#### 无内容不编造
当检索不到相关内容时，助手会被指示如实告知「未在知识库中找到相关资料」，而不是编造知识库中没有的内容。

#### 关闭走普通对话
关闭知识库开关后，聊天走普通对话链路（标准 system prompt，不注入资料）。

> 注意：知识库开关是聊天页的本地开关，与设置页的「默认启用知识库」配合——后者控制每次进入应用时开关的初始值。

### 4.5 设置页

设置页（即「设置 / 状态」视图）分四个区块：

#### 运行状态
四项状态胶囊：本地后端 API / Ollama / MySQL / ChromaDB，绿色「正常」或红色「不可用」。每 5 秒自动刷新。后端未连接时显示「⚠ 本地后端未连接，无法获取状态」。

#### 当前模型（只读）
展示 LLM 模型名、嵌入模型名、Ollama 地址。这些来自配置与 settings 表，**只读**，不在 UI 修改（修改模型名需改 `.env` 中的 `PA_LLM_MODEL` / `PA_EMBED_MODEL`）。

#### 模型参数（可调并可保存）
- 温度（0~1）
- 上下文长度
- 默认启用知识库（复选框）

点击「保存」按钮持久化到 MySQL `settings` 表，下次启动后仍生效。模型参数（温度/上下文/模型名）在每次对话时从 settings 表动态读取，支持运行时调整。

#### 云端 Provider（预留，第一阶段未启用）
展示 OpenAI / Claude 是否已配置。第一阶段只实现本地 Ollama，这些字段已预留，后续阶段再开放。

### 4.6 状态页诊断

状态页即设置页的「运行状态」区块，每 5 秒轮询 `/health` 与 `/settings`。它帮助用户快速定位问题出在哪一层：

- **本地后端 API 不可用** → 后端进程未启动 / 端口协商失败。
- **Ollama 不可用** → Ollama 服务未启动，或模型未拉取。
- **MySQL 不可用** → MySQL 未启动 / 账号密码错 / 库不存在。
- **ChromaDB 不可用** → 数据目录权限或初始化问题。

排查方法详见第 5 章。

---

## 第 5 章 · 常见问题与故障排查

按「现象 → 原因 → 解决」三列表组织。

### 5.1 后端与连接问题

| 现象 | 原因 | 解决 |
|---|---|---|
| 状态页显示「本地后端未连接」 | 后端进程未启动（开发模式）；或 sidecar 拉起失败（打包模式） | 开发模式手动 `uv run uvicorn ...`；打包模式检查 sidecar 二进制是否存在、`.env` 是否就位 |
| 端口 1420 被占 | 上次 `tauri dev` 异常退出，Vite 子进程残留 | `netstat -ano \| grep :1420` 找 PID，`taskkill /PID <pid> /F`；或直接运行 `scripts\run-tauri-dev.bat`（已内置预清理） |
| sidecar 启动失败 | `binaries/` 下为占位文件（dev 模式正常现象）；或真实 sidecar 缺依赖 | dev 模式忽略并手动起后端；打包模式先执行 `scripts\build-sidecar.bat` 生成真实二进制 |

### 5.2 Ollama 与模型问题

| 现象 | 原因 | 解决 |
|---|---|---|
| Ollama 不可用 | Ollama 服务未启动 | 启动 Ollama 应用 / `ollama serve` |
| 模型不可用 | 未拉取所需模型 | `ollama pull qwen2.5:14b-instruct-q4_K_M` 和 `ollama pull bge-m3` |
| 首 token 很慢 | 14B 模型首次加载需载入显存 | 等待首次加载完成；目标首 token < 3s |
| 生成时 OOM | 14B 模型在 12G 显存上偶尔爆显存 | 降级为 7B 模型（改 `PA_LLM_MODEL`）；限制上下文长度（调小 `PA_LLM_CONTEXT_LENGTH`） |

### 5.3 MySQL 问题

| 现象 | 原因 | 解决 |
|---|---|---|
| `Access denied for user` | `.env` 中 `PA_DB_URL` 的用户名/密码错误 | 确认账号密码正确，改 `.env` |
| 库不存在 | 未执行建库 SQL | `CREATE DATABASE personal_assistant CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;` |
| 表不存在 | 未执行数据库迁移 | 开发模式 `uv run alembic upgrade head`；打包模式由 sidecar 启动时自动迁移 |
| 编码相关乱码 | 库字符集非 utf8mb4 | 重建库并指定 `utf8mb4_unicode_ci` |

### 5.4 知识库问题

| 现象 | 原因 | 解决 |
|---|---|---|
| 提示「暂不支持的文件类型」 | 文件扩展名不在 `.pdf/.docx/.md/.markdown/.txt` 内 | 转换为支持的格式后重试 |
| 提示「暂不支持扫描件 PDF」 | PDF 为扫描图片，无可提取文本 | 第一阶段不支持 OCR，使用可复制文本的 PDF |
| 重复导入返回 409 | 相同内容（content_hash）已导入过 | 无需重复导入；如需重新索引，先删除旧文档再导入 |
| 导入一直 processing | 大文档向量化耗时；或 Ollama 嵌入服务异常 | 等待；检查 Ollama 与 bge-m3 模型是否可用 |
| 导入 failed | 解析失败 / 向量化失败 / 切片为空 | 查看文档卡片的「失败原因」；修复后点「重试」 |

### 5.5 Windows 编码与依赖问题

| 现象 | 原因 | 解决 |
|---|---|---|
| 中文 `UnicodeDecodeError` | Python 3.13 默认编码非 UTF-8 | 启动前设 `set PYTHONUTF8=1`（cmd）或 `export PYTHONUTF8=1`（bash） |
| alembic 报 `UnicodeDecodeError: 'gbk'` | Windows 控制台默认 GBK 编码 | `alembic.ini` 已改英文注释；运行前设 `PYTHONUTF8=1` |
| `asyncmy` 装不上 | Python 3.13 + Windows 无预编译 wheel，源码编译需 MySQL 开发头文件 | 本项目已改用纯 Python 的 `aiomysql`（默认），无需 asyncmy |
| `tauri dev` 报 `link.exe not found` | 未安装 MSVC Build Tools | 安装 MSVC Build Tools（见第 8 章），用 `scripts\run-tauri-dev.bat` 启动 |

---

# 第二部分 · 开发者指南（第 6–12 章 + 附录）

---

## 第 6 章 · 架构概览

### 6.1 整体架构图

```text
┌─────────────────────────────────────────────────────┐
│            Tauri 桌面层（apps/desktop/src-tauri）     │
│  窗口 / 权限 / 打包 / 启动本地 Python sidecar         │
└──────────────────────┬──────────────────────────────┘
                       │ invoke / sidecar spawn
┌──────────────────────▼──────────────────────────────┐
│              Vue 3 前端层（apps/desktop/src）         │
│  聊天页 / 会话列表 / 知识库管理 / 设置页 / 状态页       │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP + SSE（localhost）
┌──────────────────────▼──────────────────────────────┐
│              Python 本地 API 层（api/）               │
│  FastAPI routes / SSE streaming / 后台导入任务         │
└──────────────────────┬──────────────────────────────┘
                       │ 调用 core async 接口
┌──────────────────────▼──────────────────────────────┐
│                AI 核心层（core/）                    │
│  provider.py / chat.py / rag.py / history.py /       │
│  repo.py / settings.py / health.py / store_chroma.py │
└───────────────┬───────────────────────┬─────────────┘
                │                       │
                ▼                       ▼
          Ollama 服务              存储层
      LLM + Embedding       MySQL + 嵌入式 ChromaDB
```

### 6.2 三层解耦原则

| 层 | 职责 | 依赖约束 |
|---|---|---|
| `core/` | AI 与业务核心（provider / chat / rag / repo / history / settings / health / store_chroma） | **零 UI 依赖**：不 import FastAPI、Tauri、Vue，可被任意 async 调用方复用 |
| `api/` | HTTP / SSE 边界（routes_chat / routes_documents / routes_sessions / routes_settings / routes_health） | 只负责边界转换，不写复杂业务逻辑 |
| `apps/desktop/` | 桌面交互（Vue 组件 + Tauri Rust 壳） | 只通过本地 API 调用后端能力 |

存储分工：MySQL 管业务数据（会话/消息/文档/切片/设置），ChromaDB 管向量（embedding + 最小元数据 `doc_id`），通过 `chunk_id`（即 `doc_chunks.id`）关联。

### 6.3 sidecar 机制与端口协商（M4）

打包模式下，桌面应用启动时由 Tauri（Rust 壳）拉起 Python 后端 sidecar，全程掌握端口，避免固定 8000 冲突：

| 步骤 | 位置 | 实现 |
|---|---|---|
| 1. 分配端口 | `lib.rs` setup | `TcpListener::bind("127.0.0.1:0")` 让 OS 分配空闲端口，立即释放供 sidecar 复用 |
| 2. 传给 sidecar | `lib.rs` spawn | `.env("PA_API_PORT", port.to_string())`，pydantic-settings 自动读取 |
| 3. 等就绪 | `lib.rs` | `wait_for_port` 轮询 TCP 连通（30s 超时，200ms 间隔） |
| 4. 给前端 | `lib.rs` command | `get_api_port` 返回 `Option<u16>`，存于 `SidecarState` |
| 5. 前端取用 | `api.ts` | `ensureApiBase()` 调 `invoke("get_api_port")`，缓存 base |
| 6. dev 回退 | `api.ts` | `isTauri()` 为 false 或端口为 None → 回退 `http://127.0.0.1:8000`（手动后端） |
| 7. 退出清理 | `lib.rs` RunEvent::Exit | `child.kill()` 终止 sidecar 子进程 |

**dev 模式降级**：dev 模式下没有 PyInstaller 产物，`app.shell().sidecar()` 找不到二进制返回 Err，setup 降级为 `port: None`，前端回退 8000，开发流不变。

### 6.4 关键数据流

#### 聊天 SSE 流
```
前端 streamChat() → POST /chat/stream (session_id, message, knowledge_base)
  → ChatService.stream_reply()
    → 取历史消息 → 注入 system prompt → OllamaProvider.chat_stream() 逐 token
    → 每个 token yield {"type":"token","content":...}
    → 生成完 yield {"type":"done","message_id":...,"content":...,"sources":[...]}
    → 首轮 yield {"type":"title","title":...}
  → SSE: data: {json}\n\n
前端 fetch + ReadableStream 解析，AbortController 停止生成
```

停止生成：前端 `controller.abort()` → fetch 断开 → 后端生成器 `finally` 块保存已生成部分到 MySQL。

#### RAG 检索
```
knowledge_base=true → RagService.retrieve(query, top_k=5)
  → provider.embed_one(query) 得到查询向量
  → chroma_store.query(qvec, top_k=5) 返回 chunk_id 列表
  → DocChunkRepository.get_by_ids() 回查切片原文
  → DocumentRepository.get() 取文档名
  → 返回 [RetrievedChunk(chunk_id, doc_id, doc_name, ordinal, content)]
  → format_sources() → 注入 system prompt → 回答下方展示来源
```

#### 文档导入状态机
```
POST /documents/import → 创建 pending 记录 → 保存文件 → asyncio.create_task(import_document)
  import_document():
    pending → processing
    → parse_document() (线程隔离)
    → split_text() (500 字符 / 80 overlap)
    → provider.embed() 向量化
    → DocChunkRepository.add_many() 切片原文入 MySQL
    → chroma_store.add() 向量入 ChromaDB
    → processing → ready (记录 chunk_count, indexed_at)
  失败 → failed (记录 error_message，可重试)
```

### 6.5 数据目录策略

| 模式 | 判定 | 数据目录 | 派生 |
|---|---|---|---|
| 开发 | `python -m` / uvicorn 直接跑 | `./data`（项目根） | `./data/chroma`、`./data/logs`、`./data/uploads` |
| 打包 | `sys.frozen` 为真（PyInstaller） | Windows `%APPDATA%\personal-assistant`；类 Unix `~/.local/share/personal-assistant` | `<data_dir>/chroma`、`<data_dir>/logs` |

`PA_DATA_DIR` 环境变量可在任何模式下强制覆盖。`chroma_dir` / `log_dir` 由 `data_dir` 派生，不再单独配置。

---

## 第 7 章 · 目录结构

### 7.1 实际目录树

```text
Agent/
├── apps/
│   └── desktop/                  # Tauri + Vue 3 桌面端
│       ├── src/                  # Vue 前端源码
│       │   ├── App.vue           # 根组件，管理视图切换与会话状态
│       │   ├── api.ts            # 后端 API 封装 + sidecar 端口协商
│       │   ├── types.ts          # 前端类型定义
│       │   └── components/
│       │       ├── Sidebar.vue       # 左侧栏：会话列表 + 入口
│       │       ├── ChatView.vue      # 聊天视图：消息流 + 输入区
│       │       ├── KnowledgeView.vue # 知识库视图：导入 + 文档列表
│       │       └── SettingsView.vue  # 设置/状态视图
│       ├── src-tauri/            # Tauri Rust 壳
│       │   ├── src/lib.rs        # sidecar 生命周期 + 端口协商 + get_api_port
│       │   ├── Cargo.toml        # 依赖 tauri-plugin-shell 等
│       │   ├── tauri.conf.json   # externalBin 配置 sidecar
│       │   └── binaries/         # sidecar 二进制（dev 占位 / 打包真实产物）
│       ├── package.json
│       └── vite.config.ts
├── docs/                         # 需求与计划文档
├── alembic/                      # 数据库迁移
│   ├── env.py                    # async 迁移环境，URL 从 settings 注入
│   ├── script.py.mako
│   └── versions/
│       └── 0001_init.py          # 首个迁移：建 5 张表
├── alembic.ini                   # 迁移配置（英文注释，prepend_sys_path=src）
├── scripts/
│   ├── run-tauri-dev.bat         # Windows 下带 MSVC 环境启动 tauri dev
│   ├── build-sidecar.bat         # PyInstaller 打包后端 → 复制到 binaries/
│   └── cargo-check-tauri.bat     # Tauri Rust 编译检查
├── src/
│   └── personal_assistant/       # Python 后端
│       ├── __init__.py
│       ├── main_api.py           # FastAPI 应用入口（开发，--reload）
│       ├── server_entry.py       # PyInstaller 打包入口（自动迁移 + reload=False）
│       ├── config.py             # pydantic-settings 配置，数据目录策略
│       ├── logging_setup.py      # structlog + 文件日志
│       ├── personal_assistant.spec  # PyInstaller 打包配置
│       ├── api/                  # HTTP/SSE 边界
│       │   ├── routes_health.py     # GET /health
│       │   ├── routes_sessions.py   # GET/POST /sessions, GET /sessions/{id}/messages
│       │   ├── routes_chat.py       # POST /chat/stream (SSE)
│       │   ├── routes_documents.py  # 文档导入/列表/删除/重试
│       │   └── routes_settings.py   # GET/PUT /settings
│       ├── core/                 # AI 与业务核心（零 UI 依赖）
│       │   ├── config.py            # （注：实际配置在顶层 config.py）
│       │   ├── provider.py          # OllamaProvider：LLM + Embedding + health
│       │   ├── chat.py              # ChatService：流式回复 + 标题生成 + RAG 注入
│       │   ├── rag.py               # RagService：解析/切分/检索/引用
│       │   ├── history.py           # SessionRepository / MessageRepository
│       │   ├── repo.py              # DocumentRepository / DocChunkRepository
│       │   ├── settings.py          # SettingsService（KV 表）
│       │   ├── health.py            # HealthService：四项状态聚合
│       │   ├── store_chroma.py      # ChromaStore：嵌入式向量库封装
│       │   ├── models.py            # SQLAlchemy ORM（5 张表）
│       │   └── db.py                # async engine + session 工厂
│       └── workers/
│           └── importer.py      # 文档导入后台任务（状态机驱动）
├── data/                         # 运行时数据（gitignore）
│   ├── chroma/                   # 向量库持久化
│   ├── logs/                     # 后端日志
│   └── uploads/                  # 上传的原始文档
├── tests/                        # pytest 测试
│   ├── conftest.py               # fixtures：db / client
│   ├── test_health.py            # /health 四项
│   ├── test_repo.py              # 仓储层 CRUD
│   └── test_settings.py          # 设置服务
├── pyproject.toml                # Python 依赖与 pytest 配置
├── .env.example                  # 配置模板
└── README.md
```

### 7.2 关键文件职责

| 文件 | 职责 |
|---|---|
| `main_api.py` | FastAPI 应用入口，注册路由、CORS、lifespan 日志；开发用 `--reload` |
| `server_entry.py` | PyInstaller 打包入口，`reload=False`，启动前进程内 `alembic upgrade head`，端口由 `PA_API_PORT` 注入 |
| `config.py` | `Settings(BaseSettings)`，`PA_` 前缀，数据目录策略（`sys.frozen` 判断） |
| `core/provider.py` | `OllamaProvider`：`chat` / `chat_stream` / `embed` / `embed_one` / `health`；经 langchain-ollama |
| `core/chat.py` | `ChatService.stream_reply()`：历史注入 + 流式 + 首轮标题 + 可选 RAG；事件 token/done/title/error |
| `core/rag.py` | 文档解析（pypdf/docx/txt）、切分（500/80）、`content_hash`、`RagService.retrieve`、`format_sources` |
| `core/repo.py` | `DocumentRepository`（CRUD + 状态更新 + hash 查重）、`DocChunkRepository`（批量添加 + 按 id 回查） |
| `core/history.py` | `SessionRepository`（create/list/get/rename）、`MessageRepository`（add + touch updated_at / list_by_session） |
| `core/settings.py` | `SettingsService`：KV 表读写，`DEFAULTS` 来自 config，stored 优先 |
| `core/health.py` | `HealthService.check_all()`：并行检查 Ollama / MySQL / ChromaDB |
| `core/store_chroma.py` | `ChromaStore`：单 collection `doc_chunks`，add/query/delete_by_doc/count，全部 `asyncio.to_thread` 隔离 |
| `core/models.py` | ORM：`ChatSession` / `Message` / `Document` / `DocChunk` / `Setting` |
| `core/db.py` | `create_async_engine`（pool_pre_ping + pool_recycle=3600）+ `async_session_factory` + `get_session` 依赖 |
| `workers/importer.py` | `import_document()` 状态机：pending→processing→ready/failed；`retry_import()` 清理旧数据后重导 |
| `api/routes_*.py` | 各路由模块，仅做边界转换 |
| `api.ts` | `ensureApiBase()` 端口协商；`streamChat()` SSE 解析；CRUD 封装 |
| `App.vue` | 根组件：会话/消息状态、视图切换、发送/停止逻辑 |
| `lib.rs` | sidecar 生命周期：pick_free_port / spawn / wait_for_port / get_api_port / Exit kill |

---

## 第 8 章 · 开发环境搭建

### 8.1 Python 3.12+ 与 uv

```bash
# 安装 uv（推荐）
winget install --id astral-sh.uv -e
```

Python 要求 3.12+。项目用 `uv` 管理依赖与虚拟环境。

### 8.2 Rust（rustup msvc）+ MSVC Build Tools

Tauri 编译 Rust 壳需要 MSVC 工具链（`cl.exe` / `link.exe`）：

```bash
# Rust（rustup，msvc target）
winget install --id Rustlang.Rustup -e

# MSVC Build Tools（提供 cl.exe/link.exe，Tauri 编译必需）
winget install --id Microsoft.VisualStudio.2022.BuildTools --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

WebView2：Windows 11 自带，无需单独安装。

### 8.3 Node.js

桌面前端构建需要 Node.js（用于 npm install / vite / tauri cli）。

### 8.4 Ollama + 模型 + MySQL

见第 2 章。开发环境同样需要 Ollama（拉取两个模型）与本机 MySQL 8（建库）。

### 8.5 环境检查清单

| 项 | 检查命令 | 期望 |
|---|---|---|
| Python | `python --version` | 3.12+ |
| uv | `uv --version` | 已安装 |
| Rust | `rustc --version` | 已安装（msvc target） |
| MSVC | `where link.exe`（在 vcvars 环境下） | 存在 |
| Node.js | `node --version` | 已安装 |
| Ollama | `ollama list` | 含 qwen2.5 与 bge-m3 |
| MySQL | `mysql -u root -p -e "SHOW DATABASES"` | 含 personal_assistant |

---

## 第 9 章 · 开发启动

### 9.1 后端（Python FastAPI）

```bash
# 1. 复制并填写环境变量（改 .env 里的 MySQL 密码）
copy .env.example .env       # Linux/macOS: cp .env.example .env

# 2. 安装依赖（含 dev 额外依赖：pytest / httpx / pyinstaller）
uv sync --extra dev

# 3. 数据库迁移（建 5 张表）
uv run alembic upgrade head

# 4. 启动后端（默认 127.0.0.1:8000）
uv run uvicorn personal_assistant.main_api:app --reload --port 8000
```

> **Windows + Python 3.13 编码**：若遇中文 `UnicodeDecodeError`，启动前设 `set PYTHONUTF8=1`（cmd）或 `export PYTHONUTF8=1`（bash）。

### 9.2 前端（Tauri + Vue）

```bash
cd apps/desktop
npm install
```

Windows 下 `tauri dev` 需要 MSVC 环境，已封装为脚本（在 **项目根目录** 执行）：

```bash
scripts\run-tauri-dev.bat
```

该脚本会先预清理可能残留的 1420 端口，再 `call vcvars64.bat` 设置 MSVC 环境，把 `%USERPROFILE%\.cargo\bin` 加入 PATH，最后在 `apps/desktop` 下执行 `npm run tauri dev`。

### 9.3 dev 模式 sidecar 降级

dev 模式下 `binaries/` 中是占位文件（让 `build.rs` 编译通过），`app.shell().sidecar()` spawn 占位失败 → `get_api_port` 返回 None → 前端 `ensureApiBase()` 回退 `http://127.0.0.1:8000` → 连接手动启动的后端。开发流不受影响。

### 9.4 验证启动

后端启动后验证：

- `GET http://127.0.0.1:8000/health` —— 返回 API / Ollama / MySQL / ChromaDB 四项状态。
- `GET http://127.0.0.1:8000/docs` —— FastAPI 自动生成的 API 文档。
- 桌面端「设置 / 状态」页四项全绿。

### 9.5 数据库迁移命令

```bash
uv run alembic upgrade head                          # 应用迁移到最新
uv run alembic revision -m "xxx"                     # 新建空迁移（手写 upgrade/downgrade）
uv run alembic revision --autogenerate -m "xxx"      # 自动生成（需连库，对比 ORM metadata）
```

迁移环境（`alembic/env.py`）从 `settings.db_url` 注入 URL，不硬编码在 `alembic.ini`；`target_metadata` 指向 `core.models.Base.metadata`，支持 autogenerate。

---

## 第 10 章 · 打包发布

### 10.1 sidecar 打包

将 Python 后端打包为 Tauri sidecar 单可执行文件：

```bash
scripts\build-sidecar.bat
```

该脚本执行：

1. `uv run pyinstaller personal_assistant.spec --noconfirm`（已设 `PYTHONUTF8=1`）。
2. 复制 `dist\personal-assistant-server.exe` 到 `apps\desktop\src-tauri\binaries\personal-assistant-server-x86_64-pc-windows-msvc.exe`（覆盖 dev 占位）。

产物为 onefile 单文件自包含二进制，**约 ~85MB**（含 chromadb + onnxruntime + langchain + sqlalchemy + fastapi + uvicorn）。启动时解压到临时 `_MEIPASS`，首启略慢，sidecar 全生命周期只启动一次，可接受。

#### `personal_assistant.spec` 关键点

- **`collect_submodules("personal_assistant")`**：`server_entry.py` 用 `uvicorn.run("personal_assistant.main_api:app", ...)` 是字符串引用，PyInstaller 静态分析看不到，必须显式收集整个包，否则运行时 `No module named 'personal_assistant.core'`。
- `collect_submodules("chromadb" / "onnxruntime" / "langchain" / "langchain_ollama" / "langchain_chroma" / "langgraph")`：这些库大量动态 import。
- `hiddenimports` 含 `aiomysql` / `pymysql`。
- `datas`：`alembic.ini` + `alembic/` 目录（进程内迁移需要）、`chromadb` / `onnxruntime` 数据文件。
- `pathex=["src"]`。
- 模式 onefile，`console=True`（便于查看 sidecar 输出，Tauri 会转发其 stdout/stderr 到主进程日志）。

### 10.2 tauri build

```bash
cd apps/desktop
npm run tauri build
```

`tauri.conf.json` 中 `bundle.externalBin: ["binaries/personal-assistant-server"]` 声明 sidecar；`beforeBuildCommand` 先执行 `npm run build`（vue-tsc + vite build），产物在 `apps/desktop/dist`。

### 10.3 运行时依赖

sidecar 不打包这些，需用户本机具备：

| 依赖 | 说明 |
|---|---|
| Ollama + 模型 | `ollama pull qwen2.5:14b-instruct-q4_K_M` + `ollama pull bge-m3` |
| MySQL 8 | 建库 `CREATE DATABASE personal_assistant CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;` |
| 配置文件 | `%APPDATA%\personal-assistant\.env`，至少 `PA_DB_URL=mysql+aiomysql://root:<密码>@127.0.0.1:3306/personal_assistant?charset=utf8mb4` |

### 10.4 数据目录与自动迁移

打包模式 `sys.frozen` 为真 → 数据目录用 `%APPDATA%\personal-assistant`（Windows），`.env` 也从该目录读取。

`server_entry.py` 启动前进程内调用 `alembic.command.upgrade(cfg, "head")`：

- `cfg.set_main_option("script_location", <_MEIPASS>/alembic)`。
- `env.py` 从 `settings.db_url` 注入 URL。
- 迁移失败不阻断启动（MySQL 可能未就绪），前端状态页展示 MySQL 不可用。

### 10.5 安装包与分发（第五阶段已部分实现）

第五阶段已落地：NSIS 安装包（`installMode: currentUser`，简中/英文）、首启依赖检测向导、连接配置 UI、sidecar 生命周期与端口协商、Tauri updater 命令接线。一键构建：`scripts\build-release.bat`。详见 `docs/phase5-installer-updater.md`。

尚未完成（第五阶段规划，尚未实现）：

1. **代码签名**：当前无证书，安装包未签名，SmartScreen 会警告（绕过：更多信息 → 仍要运行）。长期对策见 `phase5-installer-updater.md` §7。
2. **Updater 发布源**：签名密钥对已生成、`plugins.updater`（pubkey/endpoints）与 `createUpdaterArtifacts` 已写入 `tauri.conf.json`，构建已产出 `.sig`。尚未部署：需把 `endpoints` 中的 `OWNER/REPO` 替换为实际 GitHub 仓库，并把 `docs/updater-latest.json` + 安装包 + `.sig` 上传到该仓库的 Release。部署完成后「检查更新」即可用。
3. **onedir + Tauri resources**：onefile 首启解压慢，可切 onedir（启动快）+ Tauri `resources` 打包整个目录，sidecar 用绝对路径调起。
4. **跨平台**：macOS / Linux 的 sidecar target triple + PyInstaller 产物。
5. **体积优化**：排除 onnxruntime（若确认 chromadb 用 Ollama embedding 不触发默认 embedding）可显著减小体积，需运行时验证。

---

## 第 11 章 · 测试

### 11.1 测试现状

`tests/` 目录现有基础测试：

| 文件 | 覆盖 |
|---|---|
| `conftest.py` | fixtures：`db`（独立 engine 的 session，测试结束 dispose）、`client`（ASGITransport，不走真实端口） |
| `test_health.py` | `GET /health` 返回四项（api/ollama/mysql/chroma），每项含 `ok` |
| `test_repo.py` | 会话/消息 CRUD（创建、重命名、列表）、文档状态更新与 hash 查重 |
| `test_settings.py` | 设置默认值存在、更新持久化、未知 key 被忽略 |
| `test_tools.py` | M1 工具调用底座：ToolRegistry、审批状态机、is_trusted_path 越界、/tools/plan、approve/reject、tool_result 注入聊天、活动 started_at |
| `test_chat_rag_e2e.py` | 聊天 SSE 流式 + RAG 端到端 |
| `test_phase2.py` | M2/M3/M4：工具注册（summarize_file/import_to_kb）、批量导入、启用禁用、引用片段、禁用文档不参与检索、活动流列表与重试、文件扫描/摘要 |

### 11.2 运行测试

```bash
uv run pytest
```

`pyproject.toml` 中 `asyncio_mode = "auto"`，`pythonpath = ["src"]`，`testpaths = ["tests"]`，无需额外标记即可跑 async 测试。

### 11.3 前端测试建议

前端当前无自动化测试。建议引入 **Vitest** 对 `api.ts`（端口协商、SSE 解析）与各 Vue 组件（ChatView 发送/停止、KnowledgeView 状态展示、SettingsView 轮询）做单元/组件测试。

### 11.4 覆盖缺口

当前未覆盖的关键路径（后续补全）：

- **chat SSE 流式**：`/chat/stream` 端到端流式输出与事件类型（token/done/title/error）。
- **导入状态机**：`import_document` 全流程（pending→processing→ready/failed）与重试。
- **删除一致性**：删除文档后 MySQL（documents/doc_chunks）与 ChromaDB 同步清理。
- **sidecar 端口协商**：Tauri 分配端口 → sidecar 监听 → `get_api_port` 返回值的集成验证。

---

## 第 12 章 · 扩展点

### 12.1 Provider 扩展

第一阶段 `core/provider.py` 只实现 `OllamaProvider`（LLM + Embedding 经 langchain-ollama）。`Settings` 与 `SettingsService` 已预留 `openai_api_key` / `openai_base_url` / `claude_api_key` 字段，设置页展示为「已配置 / 未配置」但不开放修改。

扩展新 Provider 的方式：

1. 在 `core/provider.py` 新增实现类（如 `OpenAIProvider`），提供与 `OllamaProvider` 一致的接口：`chat` / `chat_stream` / `embed` / `embed_one` / `health`。
2. `ChatService._get_provider()` 与 `RagService._get_provider()` 根据 settings 选择具体 Provider。
3. 上层 `chat.py` / `rag.py` 编排逻辑无需改动（依赖 Provider 接口而非具体实现）。

### 12.2 工具调用（第二阶段已实现）

第二阶段已实现受控工具调用（不执行代码、不联网搜索、不写系统文件，所有 confirm 工具需审批）：

- **工具底座**：`core/tools.py` 的 `ToolRegistry`/`ToolExecutor` + `core/approvals.py` 审批状态机 + `tool_calls` 审计表。
- **三个工具**：`read_file`（读取授权文件）、`summarize_file`（LLM 摘要）、`import_to_kb`（导入知识库），均支持 PDF/Word/MD/TXT，均为 confirm 风险（执行前展示审批卡片，批准后才执行）。
- **文件授权**：`trusted_paths` 表记录用户授权路径，工具只能访问授权路径（`core/permissions.py` 防 `..` 越界）。前端用 Tauri 原生文件选择器（`tauri-plugin-dialog`）授权，并可在检查器内直接对授权文件生成摘要、扫描授权目录下的可处理文件。
- **活动流**：工具调用、文档导入、索引重建统一写入 `activities` 表，任务页与聊天页检查器展示，失败活动可重试。
- **不做的边界**：第二阶段不开放 restricted 工具（写文件、删除、执行命令），不做完全自主 Agent。

### 12.3 云端能力预留

- 默认全本地，隐私可控。
- 后续若启用云端模型，UI 必须明确提示数据会上云。
- Provider 接口位已预留（见 12.1），第一阶段不承诺云端可用。

### 12.4 后续阶段路线图

| 阶段 | 方向 | 说明 |
|---|---|---|
| 第二阶段 | 工具调用与本地自动化 | 文件检索、代码辅助、联网搜索、命令执行审批 |
| 第三阶段 | 任务与个人工作流 | 日程、待办、笔记、长期记忆 |
| 第四阶段 | 多 Agent 与高级编排 | 研究 Agent、执行 Agent、总结 Agent 协作 |
| 第五阶段 | 安装包与分发 | NSIS 安装包、依赖检测向导、配置 UI 已实现；自动更新接线完成（发布源待部署）、跨平台/体积优化待续 |

---

# 附录

---

## 附录 A · 环境变量参考表

所有变量统一 `PA_` 前缀，由 `pydantic-settings` 从环境变量 / `.env` 读取。

| 变量 | 默认值 | 说明 | 开发模式 | 打包模式 |
|---|---|---|---|---|
| `PA_API_HOST` | `127.0.0.1` | 后端监听地址 | 项目根 `.env` | `%APPDATA%\personal-assistant\.env` |
| `PA_API_PORT` | `8000` | 后端监听端口；打包模式由 Tauri 注入覆盖 | 固定 8000 | Tauri 分配的空闲端口 |
| `PA_DB_URL` | `mysql+aiomysql://root:@127.0.0.1:3306/personal_assistant?charset=utf8mb4` | MySQL 异步连接串 | 必填密码 | 必填密码 |
| `PA_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama 服务地址 | — | — |
| `PA_LLM_MODEL` | `qwen2.5:14b-instruct-q4_K_M` | 对话主模型 | — | — |
| `PA_EMBED_MODEL` | `bge-m3` | 嵌入模型 | — | — |
| `PA_LLM_TEMPERATURE` | `0.7` | 对话温度（0~1） | — | — |
| `PA_LLM_CONTEXT_LENGTH` | `8192` | 上下文长度 | — | — |
| `PA_KB_ENABLED_BY_DEFAULT` | `false` | 知识库开关默认值 | — | — |
| `PA_DATA_DIR` | 开发 `./data`；打包用户数据目录 | 数据目录（chroma/logs 派生） | 留空用 `./data` | 留空用 `%APPDATA%\personal-assistant` |
| `PA_LOG_LEVEL` | `INFO` | 日志级别 | — | — |

> 注：温度 / 上下文长度 / 知识库默认开关 / 模型名等运行时可调参数，启动后从 MySQL `settings` 表读取（stored 优先，否则用 `.env` 默认）。在设置页修改温度/上下文/知识库开关会写入 settings 表并持久化。

---

## 附录 B · API 端点表

| 方法 | 路径 | 说明 | 请求 | 响应 |
|---|---|---|---|---|
| GET | `/health` | 四项状态（api/ollama/mysql/chroma） | — | `{api:{ok}, ollama:{ok,base_url,models...}, mysql:{ok}, chroma:{ok,path,collections}}` |
| GET | `/sessions` | 会话列表（按 updated_at 倒序） | — | `[{id,title,created_at,updated_at}]` |
| POST | `/sessions` | 新建会话（标题默认「新对话」） | — | `{id,title,created_at,updated_at}`（201） |
| GET | `/sessions/{id}/messages` | 指定会话的消息历史（时间正序） | — | `[{id,session_id,role,content,created_at}]` |
| POST | `/chat/stream` | SSE 流式对话 | `{session_id,message,knowledge_base}` | SSE：`data: {type:token/done/title/error,...}\n\n` |
| GET | `/documents` | 文档列表（支持 search/status/enabled 筛选） | query | `[{id,name,status,enabled,chunk_count,...}]` |
| POST | `/documents/import` | 上传文档（multipart `file`） | `file` | 文档对象（201）；重复返回 409 |
| POST | `/documents/batch-import` | 批量导入（multipart `files`，上限 200） | `files` | `[{name,status,doc_id,error}]` |
| PATCH | `/documents/{id}` | 启用/禁用文档 | `{enabled}` | 文档对象 |
| POST | `/documents/{id}/reindex` | 重建单个文档索引 | — | 文档对象 |
| POST | `/documents/reindex-all` | 重建全部文档索引 | — | `{triggered,skipped}` |
| DELETE | `/documents/{id}` | 删除文档（同步清 ChromaDB + MySQL + 文件） | — | `{ok,id}` |
| POST | `/documents/{id}/retry` | 重试失败/待处理导入（仅 failed/pending） | — | 文档对象 |
| GET | `/chunks/{id}` | 引用片段详情 | — | `{id,doc_id,ordinal,content,...}` |
| GET | `/tools` | 可用工具列表 | — | `[{name,description,risk_level,input_schema,...}]` |
| POST | `/tools/plan` | LLM 规划是否需工具 | `{session_id,message}` | `{tool_call}` |
| POST | `/tool-calls/{id}/approve` | 批准并执行工具 | — | 工具调用对象 |
| POST | `/tool-calls/{id}/reject` | 拒绝工具（不执行） | — | 工具调用对象 |
| GET | `/tool-calls` | 工具调用记录（可按 session 过滤） | query | `[工具调用对象]` |
| POST | `/files/authorize` | 授权路径到 trusted_paths | `{path,kind}` | 授权对象（201） |
| GET | `/files/trusted` | 已授权路径列表 | — | `[授权对象]` |
| POST | `/files/summarize` | 总结已授权文件 | `{path}` | `{summary,name,size_bytes,...}` |
| GET | `/files/scan` | 扫描授权目录可处理文件（上限 200） | query:path | `{path,files,count,truncated}` |
| GET | `/activities` | 活动列表（可按 session/kind/status 过滤） | query | `[活动对象]` |
| GET | `/activities/{id}` | 活动详情 | — | 活动对象 |
| POST | `/activities/{id}/retry` | 重试失败活动（文档导入/索引重建） | — | 活动对象 |
| GET | `/settings` | 获取设置 | — | `{llm_model,embed_model,llm_temperature,llm_context_length,kb_enabled_by_default,openai_api_key,openai_base_url,claude_api_key}` |
| PUT | `/settings` | 更新设置（部分字段） | 同上结构的子集 | 更新后的完整设置 |

---

## 附录 C · 数据库表结构

共 8 张表，字符集 `utf8mb4` / `utf8mb4_unicode_ci`，引擎 InnoDB，主键 BIGINT 自增。由 `alembic/versions/0001_init.py`（5 张）、`0002_phase2_tools.py`（tool_calls/trusted_paths/activities 3 张）、`0003_phase3_documents.py`（documents 增强）创建。

### sessions（会话）
| 列 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK AI | 主键 |
| title | VARCHAR(255) | 标题，默认「新对话」 |
| created_at | DATETIME(3) | 创建时间 |
| updated_at | DATETIME(3) | 更新时间（ON UPDATE 自动更新） |

索引：`idx_updated(updated_at)`。

### messages（消息）
| 列 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK AI | 主键 |
| session_id | BIGINT FK→sessions(id) ON DELETE CASCADE | 所属会话 |
| role | ENUM('user','assistant','system') | 角色 |
| content | MEDIUMTEXT | 消息内容 |
| created_at | DATETIME(3) | 创建时间 |

索引：`idx_session_time(session_id, created_at)`。

### documents（文档元数据）
| 列 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK AI | 主键 |
| name | VARCHAR(512) | 文件名 |
| source_path | VARCHAR(1024) | 来源路径（可空） |
| mime_type | VARCHAR(128) | MIME 类型（可空） |
| size_bytes | BIGINT | 文件大小（可空） |
| content_hash | CHAR(64) | 内容 SHA-256，用于查重（可空） |
| embedding_model | VARCHAR(128) | 嵌入模型名（可空） |
| chunk_count | INTEGER | 切片数，默认 0 |
| status | ENUM('pending','processing','ready','failed','deleting') | 状态，默认 pending |
| error_message | TEXT | 失败原因（可空） |
| indexed_at | DATETIME(3) | 索引完成时间（可空） |
| enabled | BOOLEAN | 启用/禁用，默认 true；禁用后不参与 RAG 检索（0003 迁移新增） |
| last_error_at | DATETIME(3) | 最近失败时间（可空，0003 迁移新增） |
| created_at / updated_at | DATETIME(3) | 创建/更新时间 |

索引：`idx_doc_status(status)`、`idx_doc_hash(content_hash)`。

### doc_chunks（文档切片原文）
| 列 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK AI | 主键（即 chunk_id，与 ChromaDB 关联） |
| doc_id | BIGINT FK→documents(id) ON DELETE CASCADE | 所属文档 |
| ordinal | INTEGER | 片段序号（从 1 起） |
| content | TEXT | 切片原文 |
| token_count | INTEGER | token 数（可空） |
| created_at | DATETIME(3) | 创建时间 |

约束：`uk_doc_ordinal(doc_id, ordinal)` 唯一；索引 `idx_chunk_doc(doc_id, ordinal)`。

### settings（应用设置，KV）
| 列 | 类型 | 说明 |
|---|---|---|
| key | VARCHAR(128) PK | 设置键 |
| value | TEXT | 设置值（可空） |
| updated_at | DATETIME(3) | 更新时间 |

### tool_calls（工具调用审计，0002 迁移新增）
| 列 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK AI | 主键 |
| session_id | BIGINT FK→sessions(id)（可空） | 关联会话 |
| tool_name | VARCHAR(128) | 工具名 |
| risk_level | ENUM('safe','confirm','restricted') | 风险等级 |
| status | ENUM('pending_approval','approved','rejected','running','succeeded','failed','cancelled') | 审批/执行状态；当前 approve 接口会原子占用 `pending_approval` 并直接进入 `running` 执行，避免并发重复执行 |
| input_json / output_json | JSON | 输入/输出（可空） |
| error_message | TEXT | 错误信息（可空） |
| created_at / updated_at | DATETIME(3) | 创建/更新时间 |

索引：`idx_tool_session(session_id, created_at)`、`idx_tool_status(status)`。

### trusted_paths（授权路径，0002 迁移新增）
| 列 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK AI | 主键 |
| path | VARCHAR(2048) | 授权的文件/目录绝对路径 |
| kind | ENUM('file','directory') | 路径类型 |
| granted_at | DATETIME(3) | 授权时间 |

### activities（活动流，0002 迁移新增）
| 列 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK AI | 主键 |
| session_id | BIGINT FK→sessions(id)（可空） | 关联会话 |
| kind | ENUM('tool','document_import','reindex','system') | 活动类型 |
| title | VARCHAR(255) | 标题 |
| status | ENUM('pending','waiting_approval','running','succeeded','failed','cancelled') | 状态 |
| ref_type / ref_id | VARCHAR(64) / BIGINT | 关联对象类型与 id（如 tool_call / document_import） |
| detail_json | JSON | 输入/输出摘要（可空） |
| error_message | TEXT | 错误信息（可空） |
| started_at / finished_at | DATETIME(3) | 开始/结束时间（可空） |
| created_at / updated_at | DATETIME(3) | 创建/更新时间 |

索引：`idx_activity_session(session_id, created_at)`、`idx_activity_status(status)`。

---

## 附录 D · 文档导入状态机图

```
                 POST /documents/import
                          │
                          ▼
                     ┌─────────┐
                     │ pending │  （创建记录 + 保存文件 + 启动后台任务）
                     └────┬────┘
                          │ import_document()
                          ▼
                   ┌─────────────┐
            ┌──────│ processing  │──────┐
            │      └─────────────┘      │
            │ 成功                      │ 失败（解析/切分/向量化/入库）
            ▼                           ▼
       ┌───────┐                   ┌────────┐
       │ ready │                   │ failed │  （记录 error_message）
       └───────┘                   └────┬───┘
                                        │ POST /documents/{id}/retry
                                        │ （清理旧切片后重新导入）
                                        └──→ 回到 processing

   任意状态：DELETE /documents/{id}
                          │
                          ▼
                   ┌───────────┐
                   │ deleting  │  （清 ChromaDB → 删 MySQL → 删文件）
                   └─────┬─────┘
                         │ 成功
                         ▼
                   列表移除（检索不再返回）
                         │ 失败
                         ▼
                   状态回写 failed（保留 error_message）
```

合法状态转换：
- `pending → processing → ready`
- `pending / processing → failed`
- `failed / pending → processing`（经 retry，重导）
- `任意 → deleting → 删除 / failed`

---

## 附录 E · 版本记录

| 版本 | 日期 | 内容 |
|---|---|---|
| v0.1 | 2026-07-04 | 第一阶段初始说明书。对应 requirements.md v0.1 与 phase1-plan.md v0.3。覆盖 M0–M3 已完成功能、M4 打包预研结论；第五阶段 NSIS 安装包/依赖检测向导/配置 UI 已实现，自动更新接线完成（发布源待部署）。 |

---

> 本说明书基于项目实际代码与文档编写，不包含未实现功能的虚假承诺。第五阶段尚未完成的部分（代码签名、updater 发布源部署、跨平台、体积优化）以「（第五阶段规划，尚未实现）」明确标注。如发现描述与实际行为不符，以代码为准并以本文档版本为基准进行修订。
