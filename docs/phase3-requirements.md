# 私人助手 Agent · 第三阶段需求文档

> 版本：v0.1 · 日期：2026-07-05
> 前置阶段：第二阶段已具备四区工作台 UI、受控工具调用、授权路径、文件摘要/目录扫描、知识库增强、活动流、Tauri sidecar 与安装包基础。
> 第三阶段定位：从“受控工作台助手”升级为“学习 + 文档 + 编码”个人 Agent，重点补齐项目工作区、学习闭环、文档深度处理与 RAG 检索质量。

---

## 1. 阶段目标

第三阶段要解决的问题：
1. 用户希望用助手长期学习计算机知识，而不是只做临时问答。
2. 用户希望助手能理解一个代码项目，辅助阅读、定位、修改和验证代码。
3. 用户希望处理文档时不止摘要单个文件，还能做章节总结、多文档对比、导出笔记。
4. 当前 RAG 对语义问题可用，但对技术词、报错、函数名、配置项这类精确检索还不够稳定。
5. 当前工具调用以单步工具为主，还缺少可观察、可审批的多步任务链路。

第三阶段完成后，产品应具备：
- 项目工作区：授权项目目录、扫描结构、搜索代码、读取相关文件、查看 git diff。
- 编码助手：可生成补丁、运行只读/低风险命令、运行测试，并在写入前审批。
- 学习系统：学习主题、知识树、学习计划、学习笔记、练习题、复习卡片。
- 文档工作台：章节级摘要、多文档对比、文档问答结果导出。
- RAG 增强：关键词 + 向量混合检索、元数据筛选、重排、命中原因与来源质量展示。
- 多步任务：计划、步骤、证据、审批、执行、验证、最终报告全程可审计。

---

## 2. 用户故事

### 2.1 计算机学习辅助

作为用户，我希望创建一个学习主题，例如“操作系统”“Python 后端”“Vue/Tauri 桌面开发”，让助手帮我规划学习路线、解释资料、生成练习并记录薄弱点。

验收：
- 可以创建、编辑、归档学习主题。
- 每个学习主题包含目标、当前阶段、知识节点、资料来源和学习笔记。
- 助手能基于知识库资料生成学习路线和阶段任务。
- 助手能把一次对话沉淀为笔记或复习卡片。
- 助手能生成练习题，并记录答题结果与薄弱点。

### 2.2 项目代码阅读

作为用户，我希望授权一个代码项目目录，让助手理解项目结构，回答“这个模块做什么”“某个接口在哪里实现”“这个报错可能来自哪里”。

验收：
- 可以通过 UI 授权一个项目目录。
- 系统能扫描目录树，自动忽略 `.git`、`node_modules`、`.venv`、`dist` 等大目录。
- 支持按文件名、扩展名、内容关键词搜索。
- 支持读取多个相关代码文件，并在回答中标注文件路径与行号。
- 支持查看当前 git 分支、改动文件列表和 diff 摘要。

### 2.3 编码修改与验证

作为用户，我希望助手能根据需求提出代码修改方案，展示补丁，经过我批准后写入文件，并运行测试/构建命令验证。

验收：
- 助手在修改前展示计划、目标文件、风险级别和预计影响。
- 文件写入、批量替换、运行命令都必须审批。
- 补丁以 diff 形式展示，用户可批准或拒绝。
- 批准后写入文件，并在活动流中记录修改前后摘要。
- 可以运行白名单命令，例如 `pytest`、`npm run build`、`cargo check`。
- 命令输出会被摘要并进入任务报告。
- 失败时展示错误原因和下一步建议。

### 2.4 文档深度处理

作为用户，我希望助手能处理一组学习资料或项目文档，生成章节摘要、对比结论、阅读提纲，并导出为 Markdown。

验收：
- 支持按文档、章节、选中片段生成摘要。
- 支持多文档对比，列出相同点、差异点、冲突点。
- 支持从问答或摘要结果生成 Markdown 笔记。
- 支持把生成的笔记加入知识库或保存到本地授权目录。
- 扫描件 PDF 若无法解析，应明确提示需要 OCR，不得静默失败。

### 2.5 RAG 检索质量增强

作为用户，我希望搜索技术资料、代码、报错时能更准确命中关键词和上下文。

验收：
- 检索同时使用向量相似度和关键词匹配。
- 支持按文档类型、项目、技术栈、标签、启用状态筛选。
- 支持重排 top-k 结果，提高最终上下文质量。
- 引用中展示文档名、片段号、关键词命中、相似度或重排分数。
- 对“资料不足”场景能明确说明缺少哪些信息。

### 2.6 多步任务可视化

作为用户，我希望复杂任务不只显示最终答案，而是显示任务计划、执行步骤、使用证据、审批点和验证结果。

验收：
- 新增任务运行模型，记录任务、步骤、证据和最终报告。
- 每个步骤有状态：planned / waiting_approval / running / succeeded / failed / skipped / cancelled。
- 用户可以在任务执行中批准、拒绝、取消。
- 任务详情页能展开每一步输入、输出、错误、证据来源。
- 任务结束后生成可复制的最终报告。

---

## 3. 第三阶段范围

### 3.1 做

1. **项目工作区**
   - 授权项目目录。
   - 目录树扫描与索引。
   - 文件搜索、代码搜索、读取文件片段。
   - git 状态和 diff 读取。

2. **编码工具**
   - `search_files`
   - `grep_code`
   - `read_code_file`
   - `get_git_status`
   - `get_git_diff`
   - `propose_patch`
   - `apply_patch_to_workspace`
   - `run_whitelisted_command`

3. **学习系统**
   - 学习主题管理。
   - 知识节点与学习笔记。
   - 对话沉淀为笔记。
   - 练习题生成与答题记录。
   - 复习卡片。

4. **文档工作台**
   - 章节摘要。
   - 多文档对比。
   - Markdown 导出。
   - 生成内容加入知识库。

5. **RAG 增强**
   - 文档元数据。
   - 关键词倒排或 SQLite FTS/BM25。
   - 向量 + 关键词混合召回。
   - rerank 可插拔接口。
   - 引用质量展示。

6. **多步任务**
   - 任务计划。
   - 步骤执行。
   - 审批点。
   - 证据链。
   - 最终报告。

### 3.2 不做

- 不做完全自主 Agent。高风险操作仍必须人工审批。
- 不做任意命令执行。第三阶段只开放白名单命令。
- 不做任意路径写入。只能写入用户授权的项目目录或导出目录。
- 不自动提交 git、不自动 push、不自动创建远程 PR。
- 不默认联网搜索。若后续接入联网工具，必须单独审批并提示数据外发。
- 不把用户文件上传云端模型。若启用云端 Provider，必须二次确认。
- 不做复杂 IDE 替代品。第三阶段目标是辅助阅读、修改和验证，不替代专业编辑器。

---

## 4. 功能需求

### 4.1 项目工作区

需求：
- 用户可授权一个或多个项目目录。
- 每个项目目录记录名称、根路径、语言/框架推断、最后扫描时间。
- 扫描时默认忽略：
  - `.git`
  - `node_modules`
  - `.venv`
  - `venv`
  - `dist`
  - `build`
  - `target`
  - `__pycache__`
  - `.pytest_cache`
  - `.mypy_cache`
- 支持按扩展名、文件名、内容关键词筛选。
- 支持保存文件索引：路径、大小、mtime、hash、语言、是否二进制。

验收：
- 授权项目后能看到目录树和文件统计。
- 大目录不会卡死 UI。
- 搜索代码能返回文件路径、行号、上下文片段。
- 未授权目录不能被读取。

### 4.2 编码工具与审批

工具风险等级：

| 工具 | 风险 | 说明 |
|---|---|---|
| `search_files` | safe | 搜索授权项目文件名 |
| `grep_code` | safe | 搜索授权项目文本内容 |
| `read_code_file` | confirm | 读取授权项目文件片段 |
| `get_git_status` | safe | 读取 git 状态 |
| `get_git_diff` | safe | 读取 git diff |
| `propose_patch` | safe | 只生成 diff，不写入 |
| `apply_patch_to_workspace` | confirm | 写入授权项目文件 |
| `run_whitelisted_command` | confirm | 运行白名单命令 |

命令白名单初始建议：
- `pytest`
- `python -m pytest`
- `npm run build`
- `npm test`
- `npm run test`
- `cargo check`
- `cargo test`
- `ruff check`
- `tsc --noEmit`

验收：
- 写文件前必须展示 diff。
- 运行命令前必须展示命令、工作目录、风险说明。
- 命令运行有超时和输出截断。
- 命令输出保存到活动/任务记录。
- 任何不在白名单内的命令都被拒绝。

### 4.3 学习系统

需求：
- 新增学习主题：
  - title
  - goal
  - level
  - status
  - tags
  - source_document_ids
- 新增知识节点：
  - topic_id
  - parent_id
  - title
  - summary
  - mastery_level
  - order_index
- 新增学习笔记：
  - topic_id
  - title
  - body_md
  - source_refs
- 新增练习题与答题记录：
  - question
  - answer
  - explanation
  - user_answer
  - result

验收：
- 可以从聊天结果保存为学习笔记。
- 可以基于一个主题生成学习路线。
- 可以基于知识库资料生成练习题。
- 可以记录“掌握 / 模糊 / 不会”。

### 4.4 文档工作台

需求：
- 对单文档生成：
  - 摘要
  - 章节提纲
  - 关键概念
  - 术语表
- 对多文档生成：
  - 对比表
  - 冲突点
  - 共同结论
  - 推荐阅读顺序
- 支持导出 Markdown 到授权目录。

验收：
- 用户能选择多个文档执行对比。
- 输出包含引用来源。
- 导出文件必须走审批。
- 导出的 Markdown 可重新导入知识库。

### 4.5 RAG 增强

需求：
- `documents` 增加可选元数据：
  - `doc_type`
  - `topic`
  - `tags_json`
  - `language`
  - `project_id`
- `doc_chunks` 增加可选字段：
  - `heading`
  - `keywords_json`
  - `bm25_text`
- 建立关键词索引：
  - 可使用 SQLite FTS5、本地 Whoosh-like 索引，或 MySQL FULLTEXT。
  - 以易维护优先，避免引入重型服务。
- 检索流程：
  1. 向量召回 top_n。
  2. 关键词召回 top_n。
  3. 合并去重。
  4. 可选 rerank。
  5. 返回 top_k 给 prompt。

验收：
- 精确查询函数名、报错、配置项时能命中包含原词的片段。
- 引用能展示命中原因。
- 禁用文档仍不参与任何召回。
- 检索失败时有明确提示。

### 4.6 多步任务

需求：
- 新增任务模型 `agent_tasks`。
- 新增步骤模型 `agent_task_steps`。
- 新增证据模型 `agent_evidence`。
- 任务可从聊天触发，也可从任务页创建。
- 任务计划必须先展示给用户。
- 每一步工具调用关联已有 `tool_calls`。

验收：
- 一个“读取项目并修复测试失败”的任务能拆成多步。
- 用户能看到每一步状态与证据。
- 失败后可从失败步骤重试。
- 最终报告能复制为 Markdown。

---

## 5. 数据需求

新增表草案：

```sql
CREATE TABLE projects (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  root_path VARCHAR(2048) NOT NULL,
  language VARCHAR(64),
  framework VARCHAR(128),
  status ENUM('active','archived') NOT NULL DEFAULT 'active',
  last_scanned_at DATETIME(3),
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  INDEX idx_project_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE project_files (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  project_id BIGINT NOT NULL,
  rel_path VARCHAR(2048) NOT NULL,
  language VARCHAR(64),
  size_bytes BIGINT,
  content_hash CHAR(64),
  mtime DATETIME(3),
  is_binary BOOLEAN NOT NULL DEFAULT FALSE,
  indexed_at DATETIME(3),
  UNIQUE KEY uk_project_file (project_id, rel_path(512)),
  INDEX idx_project_files_project (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE learning_topics (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  title VARCHAR(255) NOT NULL,
  goal TEXT,
  level VARCHAR(64),
  status ENUM('active','paused','completed','archived') NOT NULL DEFAULT 'active',
  tags_json JSON,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE learning_notes (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  topic_id BIGINT,
  title VARCHAR(255) NOT NULL,
  body_md MEDIUMTEXT NOT NULL,
  source_refs_json JSON,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  INDEX idx_learning_notes_topic (topic_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE agent_tasks (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id BIGINT,
  title VARCHAR(255) NOT NULL,
  status ENUM('planned','waiting_approval','running','succeeded','failed','cancelled') NOT NULL DEFAULT 'planned',
  plan_json JSON,
  final_report_md MEDIUMTEXT,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  INDEX idx_agent_task_session (session_id, created_at),
  INDEX idx_agent_task_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE agent_task_steps (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  task_id BIGINT NOT NULL,
  ordinal INTEGER NOT NULL,
  title VARCHAR(255) NOT NULL,
  status ENUM('planned','waiting_approval','running','succeeded','failed','skipped','cancelled') NOT NULL DEFAULT 'planned',
  tool_call_id BIGINT,
  input_json JSON,
  output_json JSON,
  error_message TEXT,
  started_at DATETIME(3),
  finished_at DATETIME(3),
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  INDEX idx_agent_step_task (task_id, ordinal)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 6. API 需求

### 6.1 项目 API

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/projects` | 授权并创建项目工作区 |
| GET | `/projects` | 项目列表 |
| GET | `/projects/{id}` | 项目详情 |
| POST | `/projects/{id}/scan` | 重新扫描项目文件 |
| GET | `/projects/{id}/tree` | 获取目录树 |
| GET | `/projects/{id}/files` | 文件列表/筛选 |
| GET | `/projects/{id}/search` | 文件名/内容搜索 |
| GET | `/projects/{id}/git/status` | git 状态 |
| GET | `/projects/{id}/git/diff` | git diff |

### 6.2 编码任务 API

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/coding/plan` | 根据用户目标生成编码任务计划 |
| POST | `/coding/patch/preview` | 生成补丁预览 |
| POST | `/coding/patch/apply` | 审批后应用补丁 |
| POST | `/coding/commands/run` | 审批后运行白名单命令 |

### 6.3 学习 API

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/learning/topics` | 创建学习主题 |
| GET | `/learning/topics` | 学习主题列表 |
| GET | `/learning/topics/{id}` | 学习主题详情 |
| POST | `/learning/topics/{id}/plan` | 生成学习路线 |
| POST | `/learning/notes` | 保存学习笔记 |
| GET | `/learning/notes` | 学习笔记列表 |
| POST | `/learning/cards` | 生成复习卡片 |
| POST | `/learning/quizzes` | 生成练习题 |
| POST | `/learning/quiz-attempts` | 保存答题记录 |

### 6.4 任务 API

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/agent-tasks` | 创建多步任务 |
| GET | `/agent-tasks` | 任务列表 |
| GET | `/agent-tasks/{id}` | 任务详情 |
| POST | `/agent-tasks/{id}/approve` | 批准任务计划 |
| POST | `/agent-tasks/{id}/cancel` | 取消任务 |
| POST | `/agent-task-steps/{id}/retry` | 重试失败步骤 |

---

## 7. 非功能需求

- **安全**：所有文件写入、命令执行、导出都必须在授权路径内，并经过审批。
- **审计**：项目扫描、补丁应用、命令执行、学习笔记生成都要写入活动/任务记录。
- **性能**：项目扫描必须后台化；大项目不能阻塞 UI。
- **可恢复**：任务失败后保留步骤和证据，可继续分析或重试。
- **可解释**：编码建议和学习建议必须引用文件、文档或对话来源。
- **隐私**：默认本地模型；云端模型若启用，必须提示将发送哪些内容。
- **可测试**：路径权限、命令白名单、补丁预览、混合检索、学习笔记保存都要有测试。

---

## 8. 第三阶段验收清单

1. 项目工作区可用：授权目录、扫描、搜索、读取、git 状态/diff。
2. 编码助手可用：生成补丁、审批写入、运行白名单测试/构建命令。
3. 学习系统可用：主题、路线、笔记、练习、复习卡片。
4. 文档工作台可用：章节摘要、多文档对比、Markdown 导出。
5. RAG 增强可用：混合检索、元数据筛选、引用质量展示。
6. 多步任务可用：计划、步骤、审批、证据、最终报告。
7. 权限边界有效：未授权路径不可读写，非白名单命令不可执行。
8. 前端构建、后端测试、Tauri 校验通过。
9. 主要页面视觉 QA 通过，不出现布局重叠或文字溢出。

---

## 9. 定版结论

第三阶段不是把助手变成“无人值守自动程序”，而是把它升级成一个**可控、可审计、能学习、能读项目、能辅助改代码的个人 Agent**。

它的核心价值是：
- 帮用户学习计算机知识，并把学习过程沉淀下来。
- 帮用户处理文档，并形成可复用笔记。
- 帮用户理解和修改代码，但所有写入和命令执行都由用户批准。
