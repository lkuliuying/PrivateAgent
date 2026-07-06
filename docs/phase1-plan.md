# 私人助手 Agent · 第一阶段开发计划书

> 版本：v0.3 · 日期：2026-07-04
> 定位：一个本地优先、隐私可控的桌面私人助手，第一阶段先做实"对话 + 本地知识库问答"。
>
> v0.3 决策：UI 采用 **Tauri + Vue 3**；Python 侧作为本地后端服务，负责 AI / RAG / 存储；业务数据继续使用 **MySQL**，向量数据使用 **嵌入式 ChromaDB**；第一阶段不强制完成正式安装包，云端 API 仅预留接口位。

---

## 1. 项目定位与边界

### 1.1 目标
做一个**独立桌面私人助手**，能在本机稳定运行，辅助学习与工作：
- 桌面壳采用 Tauri，界面采用 Vue 3；它不是浏览器网页产品，而是本机桌面应用。
- Python 侧作为本地后端服务，封装 AI、RAG、数据库、向量库能力。
- 能稳定多轮对话，支持上下文记忆、历史持久化与流式输出。
- 能读取本地文档，做 RAG 问答，让助手"懂你的资料"。
- 默认全部本地化，隐私可控；云端 API 作为后续可选能力。

### 1.2 第一阶段 MVP 范围
**做**：
1. 对话助手：流式输出、多轮上下文、会话历史持久化到 MySQL。
2. 本地知识库：导入文档 -> 切分 -> 向量化到 ChromaDB -> 检索增强问答。
3. 桌面 UI：Tauri + Vue 3，实现聊天、会话切换、知识库管理、基础设置、运行状态页。
4. 本地后端 API：Python async 服务承接前端请求，支持流式对话、文档导入任务、状态检查。
5. 打包预研：验证 Tauri + Python sidecar 的可行性，但不作为第一阶段硬验收。

**不做**：
- 工具调用 / Agent 自主行动，例如执行代码、联网搜索、读写系统文件。
- 多 Agent 协作。
- 任务、日程、笔记管理。
- 多用户、云同步。
- 完整云端模型切换。第一阶段只保留 Provider 接口位，主实现为本地 Ollama。
- 真正的一键绿色版安装包。第一阶段先保证开发机/个人主力机稳定运行。

### 1.3 非功能性要求
- 隐私：默认全本地；后续若启用云端 API，UI 必须明确提示数据会上云。
- 性能：本地 14B Q4 模型首 token 目标 < 3s；长文档导入允许异步排队并展示进度。
- 可演进：AI 核心、本地 API、桌面 UI 三层解耦。
- 异步优先：Python I/O 路径 async/await；阻塞解析和嵌入式向量库调用用线程隔离。
- 可诊断：模型、MySQL、ChromaDB、后端服务状态必须能在设置/状态页看到。

---

## 2. 技术栈（定版）

| 层 | 选型 | 说明 |
|---|---|---|
| 桌面壳 | **Tauri 2** | Windows 桌面应用外壳，后续可打包 |
| 前端 | **Vue 3 + TypeScript + Vite** | 负责聊天、知识库、设置、状态页 |
| 本地后端 API | **FastAPI + Uvicorn** | Tauri 前端通过 localhost API 调用 Python 能力 |
| 流式协议 | **SSE 优先**，必要时 WebSocket | 对话 token 流、导入进度、状态事件 |
| 本地 LLM 服务 | **Ollama** + Qwen2.5-14B-Instruct（Q4） | 4070(12G)+32G 可运行；第一阶段主模型 |
| 轻量任务模型 | Qwen2.5-7B（可选） | 快速问答、标题生成备用 |
| 编排框架 | **LangChain，预留 LangGraph** | M1 先用最简流式链路；复杂状态编排与后续 Agent 演进再启用 LangGraph |
| Ollama 集成 | **langchain-ollama** | 本地模型优先使用官方 LangChain Ollama 集成 |
| 向量库 | **ChromaDB 嵌入式持久化** | 存向量 + 最小元数据，路径为 `data/chroma/` |
| 业务数据库 | **MySQL 8.0+**（本机） | 存会话、消息、文档元数据、切片原文、设置 |
| ORM / 迁移 | **SQLAlchemy 2.0 async + Alembic** | AsyncSession + aiomysql；迁移可追溯 |
| 嵌入模型 | **bge-m3**（经 Ollama） | 中文检索质量好 |
| 文档解析 | pypdf / python-docx / markdown | 覆盖 PDF / Word / MD / TXT |
| 配置管理 | pydantic-settings + .env | 类型安全配置 |
| 日志 | structlog 或标准 logging | 第一阶段先本地结构化日志 |
| 打包 | Tauri build + Python sidecar 预研 | 不作为 MVP 硬验收 |

**解耦原则**：
1. `core/` 不依赖 FastAPI、Tauri、Vue；只暴露 Python async 服务接口。
2. `api/` 只负责 HTTP/SSE 边界，不写业务逻辑。
3. `apps/desktop/` 只负责桌面交互，通过本地 API 调用后端。
4. MySQL 管业务数据，ChromaDB 管向量，通过 `chunk_id` 关联。

---

## 3. 系统架构

```text
┌─────────────────────────────────────────────────────┐
│            Tauri 桌面层（apps/desktop/src-tauri）     │
│  窗口 / 权限 / 后续打包 / 启动本地 Python sidecar       │
└──────────────────────┬──────────────────────────────┘
                       │
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
│  provider.py / chat.py / rag.py / history.py / repo.py │
└───────────────┬───────────────────────┬─────────────┘
                │                       │
                ▼                       ▼
          Ollama 服务              存储层
      LLM + Embedding       MySQL + 嵌入式 ChromaDB
```

**关键抽象**：
- `Provider` 封装 LLM 与 Embedding。第一阶段只实现 Ollama，后续再接 OpenAI / Claude 兼容实现。
- `ChatService` 负责会话上下文、消息保存、流式输出。
- `RagService` 负责文档导入、切片、向量化、检索、引用生成。
- `HealthService` 负责 Ollama、MySQL、ChromaDB、本地 API 状态检测。

---

## 4. 存储层设计

### 4.1 分工

| 存储 | 职责 | 内容 |
|---|---|---|
| MySQL | 业务数据 | 会话、消息、文档元数据、切片原文、设置、导入状态 |
| ChromaDB | 向量数据 | embedding + 最小元数据：`chunk_id`、`doc_id` |

关联机制：ChromaDB 检索返回 `chunk_id` 列表 -> MySQL 查回切片原文与来源信息 -> 注入 prompt 并展示引用。

### 4.2 MySQL 表结构草案

> 字符集统一 `utf8mb4`，`utf8mb4_unicode_ci`。所有表 InnoDB。首版主键用 BIGINT 自增。

```sql
CREATE TABLE sessions (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  title       VARCHAR(255) NOT NULL DEFAULT '新对话',
  created_at  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  INDEX idx_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE messages (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id  BIGINT NOT NULL,
  role        ENUM('user','assistant','system') NOT NULL,
  content     MEDIUMTEXT NOT NULL,
  created_at  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  CONSTRAINT fk_msg_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
  INDEX idx_session_time (session_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE documents (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  name            VARCHAR(512) NOT NULL,
  source_path     VARCHAR(1024),
  mime_type       VARCHAR(128),
  size_bytes      BIGINT,
  content_hash    CHAR(64),
  embedding_model VARCHAR(128),
  chunk_count     INT NOT NULL DEFAULT 0,
  status          ENUM('pending','processing','ready','failed','deleting') NOT NULL DEFAULT 'pending',
  error_message   TEXT,
  indexed_at      DATETIME(3),
  created_at      DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at      DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  INDEX idx_doc_status (status),
  INDEX idx_doc_hash (content_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE doc_chunks (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  doc_id      BIGINT NOT NULL,
  ordinal     INT NOT NULL,
  content     TEXT NOT NULL,
  token_count INT,
  created_at  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  CONSTRAINT fk_chunk_doc FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE,
  UNIQUE KEY uk_doc_ordinal (doc_id, ordinal),
  INDEX idx_chunk_doc (doc_id, ordinal)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE settings (
  `key`       VARCHAR(128) PRIMARY KEY,
  value       TEXT,
  updated_at  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 4.3 一致性约定
- 文档导入状态流转：`pending -> processing -> ready`，失败进入 `failed` 并记录 `error_message`。
- MySQL 和 ChromaDB 没有跨库事务，不能写成“事务保证一致”。第一阶段采用状态机 + 失败补偿 + 一致性校验。
- 删除文档时先将 `documents.status` 置为 `deleting`，再删除 Chroma 向量和 MySQL 记录；失败时保留错误信息，允许重试。
- ChromaDB 只保存最小元数据，不保存完整切片原文。

---

## 5. API 与异步架构

### 5.1 本地 API 草案

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 检查 API、Ollama、MySQL、ChromaDB 状态 |
| GET | `/sessions` | 获取会话列表 |
| POST | `/sessions` | 新建会话 |
| GET | `/sessions/{id}/messages` | 获取会话消息 |
| POST | `/chat/stream` | SSE 流式对话 |
| GET | `/documents` | 获取知识库文档列表 |
| POST | `/documents/import` | 导入文档 |
| DELETE | `/documents/{id}` | 删除文档与向量 |
| GET | `/settings` | 获取设置 |
| PUT | `/settings` | 更新设置 |

### 5.2 异步约定
- FastAPI route 使用 `async def`。
- SQLAlchemy 使用 `AsyncSession` + `aiomysql`。计划初版考虑过 `asyncmy`，但 Windows + Python 3.13 下编译依赖更重，第一阶段采用纯 Python 驱动降低本机开发门槛。
- LLM 流式输出通过 async generator 转为 SSE。
- 文档解析、嵌入式 ChromaDB 同步调用等阻塞操作用 `asyncio.to_thread()` 隔离。
- 前端通过 SSE 消费 token 流；用户点击停止时，前端发取消请求，后端终止当前生成任务。

---

## 6. 目录结构（规划）

```text
Agent/
├── apps/
│   └── desktop/                  # Tauri + Vue 3 桌面端
│       ├── src/                  # Vue 页面、组件、状态管理
│       ├── src-tauri/            # Tauri 配置与 Rust 壳
│       ├── package.json
│       └── vite.config.ts
├── docs/
│   └── phase1-plan.md
├── alembic/
│   ├── versions/
│   ├── env.py
│   └── script.py.mako
├── alembic.ini
├── src/
│   └── personal_assistant/
│       ├── __init__.py
│       ├── main_api.py           # FastAPI/Uvicorn 开发入口
│       ├── api/                  # HTTP/SSE 边界
│       │   ├── __init__.py
│       │   ├── routes_chat.py
│       │   ├── routes_documents.py
│       │   ├── routes_sessions.py
│       │   ├── routes_settings.py
│       │   └── routes_health.py
│       ├── core/                 # AI 与业务核心，不依赖 UI/API
│       │   ├── __init__.py
│       │   ├── config.py
│       │   ├── provider.py
│       │   ├── chat.py
│       │   ├── rag.py
│       │   ├── store_chroma.py
│       │   ├── db.py
│       │   ├── models.py
│       │   ├── history.py
│       │   ├── repo.py
│       │   └── health.py
│       └── workers/              # 文档导入、后台任务
├── data/                         # 运行时数据，gitignore
│   └── chroma/
├── tests/
├── pyproject.toml
├── .env.example
└── README.md
```

---

## 7. 开发里程碑

### M0 · 环境与骨架（目标：前后端都能跑）
- [ ] 安装 Ollama，拉取 `qwen2.5:14b-instruct-q4_K_M` 与 `bge-m3`。
- [ ] 本机 MySQL 建库：`CREATE DATABASE personal_assistant CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`。
- [ ] 建 Python 项目骨架：`pyproject.toml`、`src/` 布局、配置读取、日志。
- [ ] 建 Tauri + Vue 3 项目骨架：`apps/desktop/`、基础窗口、前端路由。
- [ ] Python 依赖：`fastapi`、`uvicorn`、`sqlalchemy[asyncio]`、`aiomysql`、`alembic`、`pydantic-settings`、`langchain`、`langchain-ollama`、`langchain-chroma`、`langgraph`、`chromadb`、`pypdf`、`python-docx`、`markdown`。
- [ ] Alembic 初始化 + 首个迁移 + 建表。
- [ ] `core/provider.py` 实现 Ollama Provider，验证 LLM 回复和 embedding 维度。
- [ ] `GET /health` 返回 API、Ollama、MySQL、ChromaDB 状态。
- **验收**：后端 API 可启动，Tauri/Vue 可启动，前端能显示后端健康状态；Ollama 和 MySQL 连通。

### M1 · 对话助手（目标：能稳定聊天）
- [ ] `core/history.py`：会话/消息 async 仓储。
- [ ] `core/chat.py`：最简流式对话编排，支持历史上下文；LangGraph 留给后续复杂状态图与 Agent 编排。
- [ ] `POST /chat/stream`：SSE 流式输出 token。
- [ ] 会话标题生成：首轮对话后自动生成简短标题，失败时回退为“新对话”。
- [ ] Vue 聊天页：消息列表、输入框、新建会话、切换会话、停止生成。
- [ ] Vue 会话侧栏：会话列表、最近更新时间、空状态。
- **验收**：可多轮对话、流式显示、停止生成、首轮后自动生成会话标题，关闭重开后从 MySQL 恢复历史。

### M2 · 本地知识库 RAG（目标：助手懂你的资料）
- [ ] `core/repo.py`：文档/切片 async 仓储。
- [ ] `core/store_chroma.py`：嵌入式 ChromaDB 封装，持久化到 `data/chroma/`。
- [ ] `core/rag.py`：文档解析、切分、向量化、检索、引用生成。
- [ ] 文档导入状态机：`pending / processing / ready / failed / deleting`。
- [ ] API：导入文档、查询文档列表、删除文档、查询导入状态。
- [ ] Vue 知识库页：导入、进度、失败提示、重试、删除。
- [ ] 聊天页加入“启用知识库”开关。
- **验收**：导入一份文档后，提问能基于文档回答并标注来源；删除文档时 MySQL 与 ChromaDB 同步清理，失败可重试。

### M3 · 设置与打磨（目标：可日常使用）
- [ ] Vue 设置页：模型名、温度、上下文长度、知识库开关、状态检查。
- [ ] Provider 接口位：保留 OpenAI/Claude 配置结构，但第一阶段 UI 不承诺完整可用。
- [ ] 友好错误处理：Ollama 未启动、模型未拉取、MySQL 未启动、导入失败、检索为空。
- [ ] 结构化日志：后端日志写入本地文件，关键操作带 session_id/doc_id。
- [ ] 基础测试：仓储层、health、chat API、文档导入状态机。
- **验收**：个人主力机可日常使用；常见失败有明确提示，不静默崩溃。

### M4 · 打包预研（非硬验收）
- [ ] 验证 Tauri 启动 Python sidecar 的方案。
- [ ] 验证前端与 sidecar 的 localhost 端口协商。
- [ ] 写清运行依赖：Ollama、MySQL、模型文件需要单独安装或启动。
- [ ] README 写开发启动、数据库迁移、模型准备、常见问题。
- **验收**：形成可行性结论和操作文档；不要求产出完美安装包。

---

## 8. 关键设计决策记录

1. **UI 采用 Tauri + Vue 3**：第一阶段直接走更产品化的桌面路线，避免先做 Flet 后重写 UI。
2. **Python 作为本地后端服务**：AI/RAG/数据库逻辑留在 Python，Tauri/Vue 只做交互层。
3. **Provider 抽象先行，但只实现 Ollama**：云端 API 只留接口位，不拖慢 MVP。
4. **AI 核心零 UI 依赖**：`core/` 不 import FastAPI、Tauri、Vue，未来可以复用到 CLI、Web 或其他桌面端。
5. **MySQL + ChromaDB 分工**：业务数据入 MySQL，向量入 ChromaDB，通过 `chunk_id` 关联。
6. **嵌入式 ChromaDB**：第一阶段少启动一个服务，降低运行复杂度；同步调用用线程隔离。
7. **切片原文入 MySQL**：检索后直接从库取文本，不依赖原文件仍在原地。
8. **消息每条一行**：便于查询、分页、统计和后续总结。
9. **Alembic 管 schema**：M0 即引入，每次结构变更可追溯。
10. **来源引用必须有**：RAG 回答必须标注来源文档与片段，这是可信度底线。

---

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| Tauri + Python sidecar 打包复杂 | 第一阶段不把正式安装包作为硬验收，M4 只做预研 |
| 前后端分离增加开发量 | M0 只做最小窗口 + health；M1 再扩聊天页 |
| 14B 模型在 12G 显存上偶尔 OOM | 降级 7B；限制上下文长度；量化用 Q4 |
| MySQL 与 ChromaDB 数据不一致 | 状态机 + 失败补偿 + 一致性校验，避免声称跨库事务 |
| 嵌入式 ChromaDB 同步 API 阻塞事件循环 | 用 `asyncio.to_thread()` 隔离 |
| aiomysql 退出时偶发 Windows event loop 清理 warning | 避免跨 event loop 复用连接；脚本型检查结束前主动 dispose engine |
| LangGraph 抽象成本 | M1 先跑通最简 LangChain/Ollama 流式链路，复杂记忆策略和 Agent 状态图后置 |
| 文档解析质量参差 | 首版支持 PDF/Word/MD/TXT，扫描件 PDF 明确暂不支持 |
| 本地端口冲突 | 后端支持可配置端口，Tauri 启动时读取配置或探测可用端口 |

---

## 10. 第一阶段最终验收

第一阶段完成时，必须满足：
1. Tauri 桌面端可打开，能看到聊天、知识库、设置/状态三个核心区域。
2. 后端 API 可启动，前端能通过本地 API 获取健康状态。
3. 可新建/切换会话，支持流式聊天，历史保存到 MySQL。
4. 可导入本地文档，完成切片、向量化、入库，导入状态可见。
5. 启用知识库后，回答能引用本地文档来源。
6. 常见故障有明确提示：Ollama 未启动、模型缺失、MySQL 未启动、文档导入失败。

确认本计划书后，从 **M0** 开始执行：搭建 Tauri/Vue 桌面骨架 + Python FastAPI 后端骨架 + MySQL/Alembic + Ollama/Chroma 连通验证。


