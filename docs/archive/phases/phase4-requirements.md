# 私人助手 Agent · 第四阶段需求文档

> 第四阶段定位：把第三阶段已经具备的「学习 + 文档 + 编码」能力，升级为可长期陪伴使用的个人工作系统。核心不是放开更多危险权限，而是补齐长期记忆、主动复习、结构化文档处理、可回滚编码工作流、模型 Provider 扩展与数据治理。

---

## 1. 背景

第三阶段已经完成：

- 项目工作区：授权项目、扫描目录、搜索代码、读取文件、查看 git 状态与 diff。
- 学习系统：主题、路线、笔记、练习题、复习卡片。
- 文档工作台：章节摘要、多文档对比、Markdown 导出、生成笔记入库。
- 编码辅助：补丁预览、审批后写入、白名单命令执行。
- 多步任务：任务、步骤、证据、失败重试、Markdown 报告。

这些能力已经让产品从问答工具变成了受控个人 Agent。但作为长期辅助计算机学习、文档处理和编码工作的桌面助手，目前仍有几个明显短板：

1. **缺少跨会话长期记忆**：聊天历史保存在 session 中，但没有显式的用户画像、偏好、长期目标、项目经验和可管理记忆库。
2. **学习系统缺少复习节奏**：已有卡片和练习，但没有 spaced repetition、今日复习、错题本、掌握度趋势和学习周报。
3. **任务编排仍偏执行器**：已有步骤执行和审批，但计划生成较保守，缺少计划编辑、暂停/取消、模板、依赖关系和更强的证据视图。
4. **文档处理还不够结构化**：可以摘要和对比，但缺少 OCR、表格/要点/术语抽取、模板化输出、阅读笔记流水线和引用报告。
5. **编码工作流缺少回滚边界**：目前补丁以单文件替换为主，缺少多文件 patch set、变更快照、命令配置、失败诊断和项目 runbook。
6. **Provider 层仍以 Ollama 为主**：设置已预留 OpenAI/Claude 字段，但 `provider.py` 当前只实现 Ollama。
7. **数据治理不足**：知识库、学习资料、任务证据、授权路径会长期积累，需要备份/恢复、导出、清理策略和隐私控制。

第四阶段要解决的是：让这个 Agent 更懂用户、更会组织资料、更能持续辅助学习与项目维护，同时继续保持本地优先、可审批、可审计。

---

## 2. 阶段目标

第四阶段完成后，产品应具备：

1. **长期记忆系统**
   - 能从聊天、学习、文档、任务中沉淀可管理的记忆。
   - 用户可以查看、编辑、删除、禁用记忆。
   - 回答问题和规划任务时能按需检索相关记忆，并展示引用来源。

2. **主动学习闭环**
   - 每个学习主题有目标、进度、今日复习和下次复习。
   - 复习卡片支持熟悉度评分、间隔计算、到期提醒。
   - 练习题形成错题本，能生成针对性复习计划。

3. **文档深度处理**
   - 支持 OCR 或图片型 PDF 的处理入口。
   - 支持结构化抽取：术语、表格摘要、行动项、代码片段、关键公式、引用。
   - 支持模板化输出：学习笔记、读书笔记、技术文档摘要、会议纪要、对比报告。

4. **编码工作流增强**
   - 支持多文件 patch set，而不是单文件替换。
   - 写入前有完整 diff、风险提示、旧内容哈希和可回滚快照。
   - 命令白名单可在项目维度配置。
   - 能根据测试失败输出生成诊断证据和下一步建议。

5. **任务计划升级**
   - 支持 LLM 生成可编辑任务计划。
   - 用户批准计划后才执行。
   - 支持暂停、取消、从指定步骤继续、复制最终报告。
   - 任务证据可按工具、文件、命令、文档来源筛选。

6. **Provider 与数据治理**
   - 在 Ollama 之外接入 OpenAI-compatible Provider 和 Claude Provider。
   - 支持按任务选择模型，失败时可降级。
   - 支持一键备份/恢复本地数据。
   - 支持导出学习资料、知识库元数据、任务报告。

---

## 3. 非目标

第四阶段不做：

- 不做无人值守自动改项目。所有写入、命令执行、外部网络模型调用仍要明确授权或配置。
- 不做完整 IDE。编码能力仍定位为辅助阅读、生成补丁、运行验证、产出报告。
- 不做云端同步账户体系。默认本地单机，云同步只作为后续可能方向。
- 不做复杂团队协作权限。用户仍是单人使用者。
- 不替代专业笔记软件。学习/文档能力围绕 Agent 使用闭环，不追求成为通用 Notion。

---

## 4. 用户场景

### 4.1 计算机学习

用户正在学习操作系统、数据库、网络、编译原理等知识：

1. 导入教材、课程讲义、博客文章。
2. 创建学习主题。
3. Agent 生成路线、卡片、练习题。
4. 用户每天进入学习页看到今日复习和薄弱知识点。
5. Agent 根据错题和笔记生成复习计划。
6. 长期记忆记录用户偏好的解释方式、当前基础和常错点。

### 4.2 文档处理

用户需要处理论文、技术文档、PDF、项目说明：

1. 导入多份资料。
2. Agent 自动抽取术语、章节结构、表格摘要、行动项。
3. 用户选择模板导出为学习笔记、摘要报告或对比文档。
4. 输出可以重新入库，成为后续问答和学习的资料。

### 4.3 编码工作

用户让 Agent 帮忙理解项目、定位错误、生成修改建议：

1. 授权项目目录。
2. Agent 读取相关文件和历史任务记忆。
3. 生成任务计划和多文件 patch set。
4. 用户看 diff 后批准写入。
5. Agent 运行白名单测试命令。
6. 如果失败，生成诊断证据和下一轮修复计划。
7. 最终报告沉淀为项目记忆。

---

## 5. 功能需求

### 5.1 长期记忆

需求：

- 新增记忆类型：
  - 用户偏好：解释风格、语言、常用技术栈。
  - 学习状态：当前学习主题、薄弱点、目标。
  - 项目经验：项目结构、常用命令、历史问题、修复记录。
  - 文档洞察：重要概念、常用引用、资料关系。
- 记忆来源：
  - 用户手动保存。
  - 对话中显式说“记住”。
  - 任务完成后由用户确认沉淀。
  - 学习复习结果自动生成候选记忆。
- 记忆管理：
  - 列表、搜索、按类型/来源/项目/主题过滤。
  - 编辑、禁用、删除。
  - 显示创建时间、更新时间、来源对象。
- 记忆检索：
  - 聊天、任务规划、学习推荐时可检索相关记忆。
  - 回答中展示“使用了哪些记忆”。

验收：

- 用户能手动保存一条记忆，并在新会话中被检索到。
- 用户能删除或禁用记忆，禁用后不再进入上下文。
- 任务报告能一键生成候选项目记忆。
- 回答中能展示记忆引用来源。

### 5.2 学习系统 2.0

需求：

- 卡片复习：
  - 每张卡片记录 `due_at`、`interval_days`、`ease_factor`、`review_count`、`lapse_count`。
  - 支持评分：忘记 / 模糊 / 记得 / 熟练。
  - 根据评分更新下次复习时间。
- 今日学习：
  - 首页或学习页显示今日到期卡片、待做练习、薄弱节点。
  - 支持“今日 20 分钟复习计划”。
- 错题本：
  - 记录错误题、用户答案、参考答案、错因标签。
  - 可按主题、知识节点、错因筛选。
- 掌握度：
  - 学习节点根据卡片复习、练习结果、笔记数量更新掌握度。
  - 显示主题进度和薄弱知识点。
- 学习报告：
  - 生成每日/每周 Markdown 学习报告。
  - 报告可保存为学习笔记或导出。

验收：

- 复习卡片完成评分后，下次复习时间会变化。
- 今日复习列表只展示到期卡片。
- 错题会进入错题本，并能生成针对性复习卡片。
- 学习主题能展示进度、薄弱点和近期学习记录。

### 5.3 文档工作台 2.0

需求：

- OCR 入口：
  - 对图片型 PDF 或图片文件给出 OCR 处理入口。
  - OCR 失败时状态和错误清晰可见。
- 结构化抽取：
  - 术语表。
  - 表格摘要。
  - 行动项。
  - 关键观点。
  - 代码片段。
  - 引用来源。
- 文档集合：
  - 多文档可组成 collection。
  - collection 可拥有主题、标签、阅读目标。
  - 对比、摘要、导出可按 collection 操作。
- 模板化输出：
  - 学习笔记模板。
  - 技术文档摘要模板。
  - 论文阅读模板。
  - 项目资料整理模板。
  - 会议纪要模板。
- 引用与溯源：
  - 输出报告中的观点能回到 doc/chunk。
  - 导出 Markdown 时保留来源列表。

验收：

- 用户能为多份文档创建集合，并生成集合摘要。
- 抽取结果能展示来源 chunk。
- 模板化导出能生成结构稳定的 Markdown。
- OCR 处理失败不会破坏原文档状态。

### 5.4 编码工作流 2.0

需求：

- Patch set：
  - 支持一个任务中生成多个文件的补丁集合。
  - 每个文件有旧哈希、新哈希、diff、风险等级。
  - 支持单文件批准或整组批准。
- 回滚：
  - 写入前保存旧内容快照。
  - 支持回滚某个 patch set。
  - 回滚也必须走审批。
- 命令配置：
  - 项目维度配置命令白名单。
  - 命令可分组：测试、构建、格式化、类型检查、静态检查。
  - 每条命令记录工作目录、超时、输出截断上限。
- 诊断：
  - 命令失败后抽取错误摘要。
  - 把失败输出与相关文件、历史任务、项目记忆关联。
  - 生成下一步建议。
- 项目 runbook：
  - 记录项目如何安装依赖、运行测试、启动服务、构建发布。
  - Agent 规划任务时优先使用 runbook 命令。

验收：

- 多文件修改能在同一 patch set 中预览。
- 用户批准后才写入；拒绝后不写入。
- 写入后可通过审批回滚。
- 非白名单命令仍被拒绝。
- 命令失败后能生成诊断摘要并进入任务证据。

### 5.5 任务计划 2.0

需求：

- 计划生成：
  - 用户输入目标后，Agent 结合项目、文档、学习主题和记忆生成计划。
  - 计划展示步骤、工具、输入、风险、预期产出。
- 计划编辑：
  - 用户可新增、删除、调整步骤。
  - 可修改命令、文件、文档范围。
- 计划审批：
  - 整体计划先审批。
  - 高风险步骤执行前再次审批。
- 执行控制：
  - 暂停。
  - 取消。
  - 从某一步继续。
  - 失败步骤重试。
- 证据视图：
  - 按步骤、工具、文件、命令、文档来源过滤。
  - 支持复制单步证据和最终报告。

验收：

- “帮我修复这个项目的测试失败”能生成可编辑计划。
- 用户批准计划后才开始执行。
- 命令步骤仍需要审批。
- 任务失败后能从失败步骤继续。
- 最终报告包含目标、步骤、证据、结论、后续建议。

### 5.6 Provider 与模型路由

需求：

- Provider 接口扩展：
  - OllamaProvider 保持默认。
  - OpenAI-compatible Provider。
  - Claude Provider。
- 模型路由：
  - 按用途配置模型：聊天、摘要、代码、检索 query rewrite、embedding。
  - 支持任务级临时选择模型。
  - 支持失败降级：远程不可用时回到 Ollama。
- 成本与隐私提示：
  - 调远程 Provider 前显示模型和可能发送的内容范围。
  - 用户可关闭远程 Provider。

验收：

- 设置页可配置 Provider 类型。
- Chat/RAG/工具规划能使用选中的 Provider。
- Provider 健康检查能展示可用性。
- 远程 Provider 关闭后不会发送内容。

### 5.7 数据治理

需求：

- 备份：
  - 导出 MySQL 业务数据、Chroma 元数据/索引、配置、授权路径。
  - 支持手动备份和定期提醒。
- 恢复：
  - 从备份包恢复到当前机器。
  - 恢复前展示将覆盖的内容。
- 导出：
  - 学习主题、笔记、卡片、错题。
  - 文档元数据和报告。
  - 任务报告和证据。
- 清理：
  - 清理失败导入。
  - 清理旧活动和旧任务证据。
  - 清理已归档项目索引。
- 隐私：
  - 授权路径审计。
  - 远程模型发送内容提示。
  - 敏感记忆标记，不自动进入 prompt。

验收：

- 用户能创建备份包。
- 用户能从备份包恢复。
- 用户能导出一个学习主题为 Markdown。
- 用户能查看远程模型发送范围。

---

## 6. 数据需求

第四阶段建议新增迁移 `0006_phase4_personal_workflows.py`。

### 6.1 长期记忆

```sql
CREATE TABLE memory_items (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  kind ENUM('preference','learning','project','document','workflow','note') NOT NULL,
  title VARCHAR(255) NOT NULL,
  content_md MEDIUMTEXT NOT NULL,
  summary VARCHAR(1024),
  source_type VARCHAR(64),
  source_id BIGINT,
  project_id BIGINT,
  topic_id BIGINT,
  tags_json JSON,
  confidence FLOAT,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  sensitive BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  INDEX idx_memory_kind_enabled (kind, enabled),
  INDEX idx_memory_project (project_id),
  INDEX idx_memory_topic (topic_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE memory_events (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  memory_id BIGINT NOT NULL,
  event_type ENUM('created','used','edited','disabled','deleted') NOT NULL,
  ref_type VARCHAR(64),
  ref_id BIGINT,
  detail_json JSON,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  INDEX idx_memory_event_memory (memory_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 6.2 学习复习

```sql
ALTER TABLE learning_cards
  ADD COLUMN due_at DATETIME(3),
  ADD COLUMN interval_days INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN ease_factor FLOAT NOT NULL DEFAULT 2.5,
  ADD COLUMN review_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN lapse_count INTEGER NOT NULL DEFAULT 0;

CREATE TABLE learning_reviews (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  card_id BIGINT NOT NULL,
  topic_id BIGINT NOT NULL,
  rating ENUM('again','hard','good','easy') NOT NULL,
  previous_due_at DATETIME(3),
  next_due_at DATETIME(3),
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  INDEX idx_review_topic_time (topic_id, created_at),
  INDEX idx_review_card_time (card_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 6.3 Patch set 与命令配置

```sql
CREATE TABLE project_command_profiles (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  project_id BIGINT NOT NULL,
  name VARCHAR(128) NOT NULL,
  command_json JSON NOT NULL,
  kind ENUM('test','build','lint','format','typecheck','custom') NOT NULL,
  timeout_seconds INTEGER NOT NULL DEFAULT 120,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  INDEX idx_command_profile_project (project_id, enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE patch_sets (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  project_id BIGINT NOT NULL,
  task_id BIGINT,
  title VARCHAR(255) NOT NULL,
  status ENUM('draft','waiting_approval','applied','rejected','rolled_back') NOT NULL DEFAULT 'draft',
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  INDEX idx_patch_set_project (project_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE patch_files (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  patch_set_id BIGINT NOT NULL,
  rel_path VARCHAR(2048) NOT NULL,
  old_sha256 CHAR(64),
  new_sha256 CHAR(64),
  diff_text MEDIUMTEXT NOT NULL,
  old_content MEDIUMTEXT,
  new_content MEDIUMTEXT NOT NULL,
  status ENUM('draft','applied','rejected','rolled_back') NOT NULL DEFAULT 'draft',
  INDEX idx_patch_file_set (patch_set_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 6.4 文档集合与抽取结果

```sql
CREATE TABLE document_collections (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  title VARCHAR(255) NOT NULL,
  goal TEXT,
  tags_json JSON,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE document_collection_items (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  collection_id BIGINT NOT NULL,
  doc_id BIGINT NOT NULL,
  order_index INTEGER NOT NULL DEFAULT 0,
  UNIQUE KEY uk_collection_doc (collection_id, doc_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE document_extractions (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  doc_id BIGINT,
  collection_id BIGINT,
  kind ENUM('terms','table_summary','actions','claims','code','template_report') NOT NULL,
  content_json JSON,
  content_md MEDIUMTEXT,
  source_refs_json JSON,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  INDEX idx_extraction_doc (doc_id, kind),
  INDEX idx_extraction_collection (collection_id, kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 7. API 需求

### 7.1 记忆 API

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/memories` | 记忆列表，支持 kind/project/topic/search/enabled 过滤 |
| POST | `/memories` | 手动创建记忆 |
| GET | `/memories/{id}` | 记忆详情 |
| PATCH | `/memories/{id}` | 编辑、启用禁用、敏感标记 |
| DELETE | `/memories/{id}` | 删除记忆 |
| POST | `/memories/search` | 记忆检索 |
| POST | `/memories/candidates` | 从任务/对话/学习结果生成候选记忆 |
| POST | `/memories/{id}/use` | 记录记忆被使用的审计事件 |

### 7.2 学习复习 API

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/learning/reviews/today` | 今日到期复习 |
| POST | `/learning/cards/{id}/review` | 提交卡片评分并更新 due_at |
| GET | `/learning/topics/{id}/dashboard` | 主题学习仪表盘 |
| GET | `/learning/topics/{id}/weak-points` | 薄弱点列表 |
| GET | `/learning/topics/{id}/wrong-answers` | 错题本 |
| POST | `/learning/topics/{id}/weekly-report` | 生成学习周报 |

### 7.3 文档处理 API

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/document-collections` | 创建文档集合 |
| GET | `/document-collections` | 集合列表 |
| PATCH | `/document-collections/{id}` | 更新集合 |
| POST | `/document-collections/{id}/items` | 添加文档 |
| DELETE | `/document-collections/{id}/items/{doc_id}` | 移除文档 |
| POST | `/documents/{id}/ocr` | OCR 处理 |
| POST | `/documents/{id}/extract` | 单文档结构化抽取 |
| POST | `/document-collections/{id}/extract` | 集合结构化抽取 |
| POST | `/documents/template-report` | 按模板生成报告 |

### 7.4 编码工作流 API

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/projects/{id}/commands` | 项目命令配置 |
| POST | `/projects/{id}/commands` | 新增命令配置 |
| PATCH | `/projects/{id}/commands/{command_id}` | 更新/启用/禁用命令 |
| POST | `/projects/{id}/patch-sets` | 创建 patch set |
| GET | `/projects/{id}/patch-sets` | patch set 列表 |
| GET | `/patch-sets/{id}` | patch set 详情 |
| POST | `/patch-sets/{id}/apply` | 审批后应用 |
| POST | `/patch-sets/{id}/rollback` | 审批后回滚 |
| POST | `/projects/{id}/diagnose-command-output` | 命令失败诊断 |

### 7.5 任务计划 2.0 API

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/agent-tasks/plan` | 根据目标生成可编辑计划 |
| PATCH | `/agent-tasks/{id}/plan` | 编辑计划 |
| POST | `/agent-tasks/{id}/approve-plan` | 批准整体计划 |
| POST | `/agent-tasks/{id}/pause` | 暂停 |
| POST | `/agent-tasks/{id}/cancel` | 取消 |
| POST | `/agent-tasks/{id}/resume` | 继续 |
| POST | `/agent-tasks/{id}/resume-from/{step_id}` | 从指定步骤继续 |
| GET | `/agent-tasks/{id}/evidence` | 证据筛选列表 |

### 7.6 Provider 与数据治理 API

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/providers` | Provider 配置和健康 |
| PATCH | `/providers` | 更新 Provider 设置 |
| POST | `/providers/test` | 测试 Provider |
| POST | `/backup/export` | 创建备份包 |
| POST | `/backup/restore/preview` | 恢复预览 |
| POST | `/backup/restore` | 执行恢复 |
| POST | `/exports/learning-topic/{id}` | 导出学习主题 |
| POST | `/exports/task/{id}` | 导出任务报告 |
| POST | `/maintenance/cleanup` | 数据清理 |

---

## 8. 前端需求

### 8.1 新增/增强页面

- 记忆页：
  - 记忆列表。
  - 记忆详情。
  - 候选记忆审核。
  - 类型/项目/主题筛选。
- 学习页增强：
  - 今日复习。
  - 错题本。
  - 掌握度仪表盘。
  - 周报。
- 文档页增强：
  - 文档集合。
  - 结构化抽取结果。
  - 模板报告生成器。
- 项目页增强：
  - 命令配置。
  - patch set 视图。
  - 回滚入口。
  - runbook 面板。
- 任务页增强：
  - 计划编辑器。
  - 计划审批。
  - 暂停/取消/继续。
  - 证据筛选。
- 设置页增强：
  - Provider 选择。
  - 远程 Provider 隐私提示。
  - 备份/恢复。

### 8.2 导航

建议导航从六入口扩展为七入口：

1. 聊天
2. 知识库
3. 项目
4. 学习
5. 任务
6. 记忆
7. 设置

记忆页也可以先放在设置页或检查器中，但最终建议成为独立入口，因为它是第四阶段核心能力。

---

## 9. 安全与隐私要求

- 所有长期记忆默认本地保存。
- 敏感记忆不会自动进入 prompt。
- 远程 Provider 调用前要能展示将发送的内容范围。
- 写文件、回滚、命令执行、备份恢复都必须审批。
- 备份包不要包含远程 Provider 私钥明文；如包含，必须提示用户。
- 授权路径页面必须能看到哪些目录被授权。
- 删除记忆、删除备份、恢复覆盖需要二次确认。

---

## 10. 测试需求

### 10.1 后端测试

- 记忆 CRUD、禁用过滤、检索、引用。
- 学习卡片复习算法和今日到期查询。
- 文档集合、结构化抽取、模板导出。
- 多文件 patch set 应用和回滚。
- 命令配置白名单。
- 任务计划审批、暂停、取消、继续。
- Provider 选择和健康检查。
- 备份导出/恢复预览。

### 10.2 前端测试/构建

- `npm run build` 必须通过。
- 记忆页、学习今日复习、patch set、任务计划编辑器在 900/1200/1600 宽度无明显溢出。
- 高风险操作按钮状态必须明确。

### 10.3 集成验证

- `pytest -q`
- `npm run build`
- `cargo check`
- `alembic upgrade head && alembic current`
- `/health`
- 至少一个端到端场景：
  - 创建学习主题 → 生成卡片 → 完成复习 → 生成周报 → 保存记忆。
  - 授权项目 → 生成 patch set → 审批写入 → 运行测试 → 失败诊断或成功报告。

---

## 11. 验收清单

第四阶段完成时必须满足：

- [x] 用户可以创建、搜索、编辑、禁用、删除长期记忆。
- [x] 新会话能使用已启用记忆，并展示引用。
- [x] 学习卡片有 due_at 和复习评分。
- [x] 今日复习列表可用。
- [x] 错题本可用。
- [x] 文档集合可用。
- [x] 至少 3 种结构化抽取可用。
- [x] 至少 3 种模板化报告可用。
- [x] 多文件 patch set 可预览、审批写入、审批回滚。
- [x] 项目命令白名单可配置。
- [x] 任务计划可编辑、批准、暂停、取消、继续。
- [x] OpenAI-compatible Provider 可用，Ollama 仍为默认。
- [x] 备份导出和恢复预览可用。
- [x] 后端测试、前端构建、Tauri 校验通过。

---

## 12. 定版结论

第四阶段的核心不是让 Agent 更“大胆”，而是让它更“可靠、懂你、能长期积累”。它应该把第三阶段的能力沉淀成一个稳定的个人系统：

- 学习上，它知道你学到哪里、哪里薄弱、今天该复习什么。
- 文档上，它能把资料整理成可复用的结构化知识。
- 编码上，它能生成可审查、可回滚、可验证的变更。
- 工作流上，它能把任务证据、项目经验和用户偏好沉淀为长期记忆。
