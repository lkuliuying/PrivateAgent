# 私人助手 Agent · 第三阶段开发计划书

> 版本：v0.1 · 日期：2026-07-05
> 对应需求：`docs/phase3-requirements.md`
> 阶段主题：项目工作区 + 编码助手 + 学习系统 + 文档工作台 + RAG 增强。
> 阶段原则：先做项目/学习的数据底座，再开放可审批的代码修改与命令执行。第三阶段仍不做完全自主 Agent。

---

## 1. 阶段目标

第二阶段已经完成“工作台 UI + 受控工具 + 文件/知识库/活动流”。第三阶段要把产品变成更贴近日常使用的个人 Agent：

1. 能围绕一个学习主题长期陪用户学习。
2. 能授权并理解代码项目，辅助阅读、定位和修改。
3. 能把文档处理结果沉淀成笔记和知识库资产。
4. 能用更可靠的混合检索处理技术资料、报错和代码。
5. 能执行多步任务，但每个高风险动作都可见、可审批、可审计。

---

## 2. 总体架构变化

第三阶段继续沿用当前架构：

```text
Tauri 桌面壳
  -> Vue 3 工作台 UI
    -> FastAPI 本地 API
      -> core: chat / rag / tools / files / activities / projects / learning / tasks
        -> Ollama + MySQL + ChromaDB + local indexes
```

新增核心模块：

```text
src/personal_assistant/
├── core/
│   ├── projects.py          # 项目授权、扫描、目录树、文件索引
│   ├── code_tools.py        # 代码搜索、git diff、补丁预览、命令白名单
│   ├── learning.py          # 学习主题、笔记、练习、复习卡片
│   ├── task_runner.py       # 多步任务计划与执行
│   ├── hybrid_retrieval.py  # 向量 + 关键词混合检索
│   └── exports.py           # Markdown 导出
├── api/
│   ├── routes_projects.py
│   ├── routes_coding.py
│   ├── routes_learning.py
│   └── routes_agent_tasks.py
└── workers/
    ├── project_scanner.py
    ├── code_indexer.py
    └── task_worker.py
```

前端新增/重构：

```text
apps/desktop/src/components/
├── ProjectWorkspace.vue
├── ProjectTree.vue
├── CodeSearchPanel.vue
├── DiffPreview.vue
├── CommandRunCard.vue
├── LearningWorkspace.vue
├── LearningTopicList.vue
├── LearningNoteEditor.vue
├── QuizPanel.vue
├── DocumentComparePanel.vue
├── TaskRunDetail.vue
└── EvidenceList.vue
```

导航建议从四个入口扩展为六个入口：
- 聊天
- 知识库
- 项目
- 学习
- 任务
- 设置

---

## 3. UI 与交互方案

### 3.1 项目工作区

布局：
- 左侧：项目列表 + 当前项目目录树。
- 中央：文件预览、搜索结果、diff 预览。
- 右侧检查器：文件元信息、引用证据、命令输出摘要、任务步骤。

关键交互：
- 授权项目目录。
- 点击目录树读取文件。
- 搜索代码返回文件路径、行号、上下文。
- 生成补丁后展示 diff。
- 用户批准后写入。
- 运行测试/构建命令前展示命令和工作目录。

### 3.2 学习工作区

布局：
- 左侧：学习主题列表。
- 中央：学习路线、知识节点、笔记编辑器。
- 右侧：相关资料、复习卡片、练习题、薄弱点。

关键交互：
- 从对话保存为笔记。
- 从知识库资料生成路线。
- 一键生成练习题。
- 标记掌握程度。
- 生成复习卡片。

### 3.3 文档工作台增强

知识库页增加：
- 多选文档。
- 章节摘要。
- 多文档对比。
- 导出 Markdown。
- 导出后可加入知识库。

### 3.4 多步任务页

任务页从“活动列表”升级为“任务运行台”：
- 顶部显示任务目标与状态。
- 中部显示步骤时间线。
- 每个步骤可展开输入、输出、证据、错误。
- 底部显示最终报告。

---

## 4. 数据库变更计划

### 4.1 新增表

建议新增：
- `projects`
- `project_files`
- `learning_topics`
- `learning_nodes`
- `learning_notes`
- `learning_cards`
- `learning_quizzes`
- `learning_quiz_attempts`
- `agent_tasks`
- `agent_task_steps`
- `agent_evidence`

### 4.2 现有表增强

`documents`：
- `doc_type VARCHAR(64)`
- `topic VARCHAR(255)`
- `tags_json JSON`
- `language VARCHAR(64)`
- `project_id BIGINT NULL`

`doc_chunks`：
- `heading VARCHAR(512)`
- `keywords_json JSON`

`tool_calls`：
- 可选增加 `task_id BIGINT NULL`
- 可选增加 `step_id BIGINT NULL`

`activities`：
- 保持作为轻量活动流。
- 多步任务详情放在 `agent_tasks` / `agent_task_steps`。

---

## 5. 工具设计

### 5.1 项目与代码工具

| 工具 | 风险 | 说明 |
|---|---|---|
| `search_files` | safe | 按文件名/扩展名搜索授权项目 |
| `grep_code` | safe | 搜索授权项目文本内容 |
| `read_code_file` | confirm | 读取授权项目文件片段 |
| `get_git_status` | safe | 读取当前 git 状态 |
| `get_git_diff` | safe | 读取 git diff |
| `propose_patch` | safe | 生成 diff，不写入 |
| `apply_patch_to_workspace` | confirm | 审批后写入文件 |
| `run_whitelisted_command` | confirm | 审批后运行白名单命令 |

### 5.2 学习工具

| 工具 | 风险 | 说明 |
|---|---|---|
| `create_learning_plan` | safe | 生成学习路线 |
| `save_learning_note` | confirm | 保存学习笔记 |
| `generate_quiz` | safe | 生成练习题 |
| `grade_quiz_answer` | safe | 批改用户答案 |
| `create_review_cards` | confirm | 保存复习卡片 |

### 5.3 文档工具

| 工具 | 风险 | 说明 |
|---|---|---|
| `summarize_document_sections` | safe | 章节摘要 |
| `compare_documents` | safe | 多文档对比 |
| `export_markdown` | confirm | 导出 Markdown 到授权目录 |
| `import_generated_note_to_kb` | confirm | 生成内容加入知识库 |

---

## 6. 开发里程碑

### M0 · 数据模型与导航骨架

目标：先建立第三阶段的结构，不改变现有功能。

- [x] 新增 Alembic 迁移：projects / learning / agent_tasks 基础表。
- [x] 新增 API 空壳：projects / learning / agent_tasks。
- [x] 前端导航增加“项目”“学习”入口。
- [x] 新增 ProjectWorkspace / LearningWorkspace / TaskRunDetail 基础页面。
- [x] 保持聊天、知识库、任务、设置功能不回退。

验收：
- 应用可打开六个主入口。
- 新表迁移成功。
- 旧测试继续通过。

### M1 · 项目工作区只读能力

目标：让助手能安全理解一个代码项目，但不写入。

- [x] 实现项目目录授权。
- [x] 实现目录树扫描，带默认忽略规则。
- [x] 实现 project_files 索引。
- [x] 实现 `search_files`。
- [x] 实现 `grep_code`。
- [x] 实现 `read_code_file`。
- [x] 实现 `get_git_status`、`get_git_diff`。
- [x] 前端实现项目树、搜索结果、文件预览、git 状态面板。

验收：
- 授权项目后可查看目录树。
- 可搜索代码并返回行号上下文。
- 未授权目录读取失败。
- 可查看 git status/diff，但不会修改任何文件。

### M2 · RAG 混合检索

目标：提高技术资料、报错、函数名、配置项的命中率。

- [x] 为文档/切片增加元数据字段。
- [x] 建立关键词索引。
- [x] 实现 hybrid_retrieval：向量召回 + 关键词召回 + 合并去重。
- [x] 实现可插拔 rerank 接口。
- [x] 引用展示命中原因。
- [x] 知识库页支持标签、主题、文档类型筛选。

验收：
- 精确关键词查询能命中包含原词的片段。
- 禁用文档不参与向量和关键词召回。
- 引用能显示命中原因。

### M3 · 学习系统

目标：让助手从问答工具变成学习教练。

- [x] 实现学习主题 CRUD。
- [x] 实现学习路线生成。
- [x] 实现知识节点展示。
- [x] 实现从聊天保存为学习笔记。
- [x] 实现练习题生成和答题记录。
- [x] 实现复习卡片保存。
- [x] 前端实现学习主题、笔记、练习、卡片 UI。

验收：
- 用户能创建学习主题。
- 能基于资料生成学习路线。
- 能保存对话为笔记。
- 能生成练习题并记录结果。

### M4 · 文档工作台增强

目标：把知识库从“文档列表”升级为“资料处理工作台”。

- [x] 文档多选。
- [x] 章节摘要。
- [x] 多文档对比。
- [x] 术语表生成。
- [x] Markdown 导出。
- [x] 生成内容加入知识库。

验收：
- 多文档对比可运行。
- 输出包含引用来源。
- 导出 Markdown 必须审批。
- 导出文件可重新导入知识库。

### M5 · 编码修改与命令验证

目标：开放可审批的代码修改和测试/构建命令。

- [x] 实现 `propose_patch`。
- [x] 实现 diff 预览 UI。
- [x] 实现 `apply_patch_to_workspace`。
- [x] 实现命令白名单配置。
- [x] 实现 `run_whitelisted_command`。
- [x] 命令输出摘要与截断。
- [x] 活动流/任务记录接入。

验收：
- 写文件前能看到 diff。
- 用户拒绝后不写入。
- 用户批准后写入授权项目文件。
- 非白名单命令被拒绝。
- `pytest` / `npm run build` / `cargo check` 等命令可审批运行。

### M6 · 多步任务编排

目标：把项目阅读、代码修改、文档处理串成可观察的任务链。

- [x] 实现 agent_tasks / agent_task_steps 仓储。
- [x] 实现任务计划生成。
- [x] 实现步骤执行器。
- [x] 工具调用关联 task_id / step_id。
- [x] 任务页展示计划、步骤、证据、错误、最终报告。
- [x] 支持失败步骤重试。

验收：
- “分析项目并修复一个测试失败”能形成多步任务。
- 每一步都有状态和证据。
- 审批点明确。
- 任务结束后生成 Markdown 报告。

### M7 · 测试、视觉 QA 与文档收尾

目标：让第三阶段可交付。

- [x] 单元测试：路径授权、项目扫描、命令白名单、补丁应用。
- [x] API 测试：项目、学习、任务、文档对比。
- [x] RAG 测试：关键词命中、混合召回、禁用过滤。
- [x] 前端构建：`npm run build`。
- [x] 后端测试：`pytest`。
- [x] Tauri 校验：`cargo check`。
- [ ] 截图 QA：900px / 1200px / 1600px。
- [x] 更新 README 和 usage-guide。

验收：
- 所有测试通过。
- 主要页面无重叠、无溢出。
- 第三阶段需求文档中的验收清单全部通过。

---

## 7. 推荐开发顺序

1. M0：先建表和页面入口，确保旧功能不受影响。
2. M1：先做只读项目工作区，避免一开始就处理写入风险。
3. M2：做混合检索，因为学习、文档、代码都依赖更好的检索。
4. M3：做学习系统，把个人长期使用价值拉起来。
5. M4：做文档工作台，补齐资料处理能力。
6. M5：再开放写代码和跑命令，保持审批边界。
7. M6：把前面能力串成多步任务。
8. M7：测试、视觉 QA、文档收尾。

这样做的原因：项目扫描和混合检索是底座；学习和文档沉淀是用户价值；写文件和跑命令风险更高，应在权限、任务记录、diff 预览稳定后再开放。

---

## 8. 关键风险与对策

| 风险 | 对策 |
|---|---|
| 项目目录过大导致卡顿 | 后台扫描 + 忽略规则 + 文件大小上限 + 增量索引 |
| 助手误写文件 | 只允许授权项目目录 + diff 预览 + 用户审批 |
| 命令执行风险 | 白名单 + 工作目录限制 + 超时 + 输出截断 + 审计 |
| RAG 混合检索过复杂 | 先实现简单关键词召回，再接 rerank |
| 学习系统变成空壳 | 先做“对话保存笔记”和“主题学习路线”两个真实闭环 |
| 文档导出覆盖用户文件 | 默认新文件名 + 覆盖前二次确认 |
| 多步任务难以调试 | 每一步写入 agent_task_steps 和 tool_calls，失败可重试 |

---

## 9. 第三阶段最终验收

第三阶段完成时必须满足：
1. 项目工作区可用，能安全读取授权项目。
2. 编码助手可用，能生成补丁、审批写入、运行白名单命令。
3. 学习系统可用，能管理主题、笔记、练习、复习卡片。
4. 文档工作台可用，能章节摘要、多文档对比、导出 Markdown。
5. 混合检索可用，精确技术词查询质量明显提升。
6. 多步任务可用，计划、步骤、证据、审批、报告完整。
7. 所有高风险操作都可审批、可审计、可取消。
8. 后端测试、前端构建、Tauri 校验通过。
9. 视觉 QA 截图通过，不出现布局重叠或文字溢出。

---

## 10. 不变的边界

第三阶段仍然坚持：
- 默认本地优先。
- 默认不上传用户资料。
- 不做完全自主 Agent。
- 写文件、导出文件、运行命令必须审批。
- 命令执行只开放白名单。
- 项目访问只限用户授权目录。
- 工具调用和任务步骤必须可审计。
- UI 服务于长期学习和工作效率，不做演示型噱头。
