# 私人助手 Agent · 第四阶段开发计划书

> 对应 `docs/archive/phases/phase4-requirements.md`。第四阶段定位为“个人化记忆与主动工作流增强”。注意：仓库中已有 `docs/archive/phases/phase4-sidecar-research.md`，那是第一阶段 M4 打包预研的历史文档；本文中的“第四阶段”指第三阶段完成后的产品能力阶段，不替代 sidecar 预研文档。

---

## 1. 阶段判断

当前项目已经完成三层基础：

1. **桌面工作台层**
   - Tauri + Vue 3。
   - 六入口导航：聊天、知识库、项目、学习、任务、设置。
   - 检查器、状态栏、审批卡片、活动流。

2. **个人 Agent 能力层**
   - 工具注册与审批状态机。
   - 授权路径与只读/写入/命令风险边界。
   - 项目工作区、学习系统、文档工作台、混合检索。
   - 多步任务和任务证据。

3. **本地数据层**
   - MySQL + Alembic。
   - ChromaDB。
   - 文档切片、项目索引、学习数据、工具调用、活动流、任务证据。

第四阶段不需要重建架构，而是在现有边界上补“长期使用价值”：

- 让 Agent 有可管理的长期记忆。
- 让学习系统有复习节奏。
- 让文档工作台产出结构化资料。
- 让编码任务有 patch set、回滚和项目命令配置。
- 让任务计划从固定流程升级为可编辑、可暂停、可继续的工作流。
- 让 Provider 和数据治理从预留字段变为可用能力。

---

## 2. 总体目标

第四阶段交付后，用户应能这样使用产品：

1. 进入学习页，看到今日到期复习、薄弱知识点和学习周报。
2. 在聊天或任务结束后，把“我的偏好/项目经验/学习状态”沉淀为可编辑记忆。
3. 处理一批文档时，把它们组成集合，抽取术语、行动项、表格摘要，并按模板导出。
4. 让 Agent 修改项目时，看到多文件 patch set，批准后写入，失败可回滚。
5. 让 Agent 根据目标生成任务计划，用户编辑和批准后再执行。
6. 在设置里选择 Ollama/OpenAI-compatible/Claude Provider，并看到健康状态。
7. 能备份和恢复本地数据。

---

## 3. 架构增量

### 3.1 后端模块

建议新增/扩展：

```text
src/personal_assistant/
├── api/
│   ├── routes_memories.py
│   ├── routes_learning_reviews.py
│   ├── routes_document_collections.py
│   ├── routes_patch_sets.py
│   ├── routes_providers.py
│   └── routes_backup.py
├── core/
│   ├── memories.py
│   ├── repo_memories.py
│   ├── review_scheduler.py
│   ├── document_extraction.py
│   ├── patch_sets.py
│   ├── repo_patch_sets.py
│   ├── task_planner.py
│   ├── provider_router.py
│   ├── backup.py
│   └── redaction.py
└── workers/
    ├── ocr_worker.py
    ├── extraction_worker.py
    └── backup_worker.py
```

### 3.2 前端模块

建议新增/扩展：

```text
apps/desktop/src/components/
├── MemoryWorkspace.vue
├── MemoryInspector.vue
├── LearningReviewPanel.vue
├── LearningDashboard.vue
├── WrongAnswerBook.vue
├── DocumentCollectionPanel.vue
├── ExtractionResultPanel.vue
├── TemplateReportBuilder.vue
├── PatchSetPanel.vue
├── CommandProfilePanel.vue
├── TaskPlanEditor.vue
├── EvidenceFilterPanel.vue
├── ProviderSettingsPanel.vue
└── BackupRestorePanel.vue
```

### 3.3 数据迁移

建议新增迁移：

- `0006_phase4_personal_workflows.py`

覆盖：

- `memory_items`
- `memory_events`
- `learning_reviews`
- `learning_cards` 复习字段增列
- `project_command_profiles`
- `patch_sets`
- `patch_files`
- `document_collections`
- `document_collection_items`
- `document_extractions`

---

## 4. 里程碑

### M0 · 阶段底座与清理

目标：建立第四阶段的数据结构和导航入口，并清理第三阶段留下的小债。

任务：

- [x] 新增 `0006_phase4_personal_workflows.py` 迁移。
- [x] 新增 MemoryWorkspace 导航入口。
- [x] 新增空路由：memories / reviews / collections / patch-sets / providers / backup。
- [x] 更新 `types.ts` 和 `api.ts` 类型。
- [x] 修复测试结束时 aiomysql 连接未归还警告。
- [x] 梳理 `docs/archive/phases/phase4-sidecar-research.md` 与本阶段文档的命名说明，避免“第四阶段”歧义。

验收：

- `alembic upgrade head` 成功。
- 应用能打开记忆页。
- 空 API 返回稳定结构。
- 现有测试继续通过。

### M1 · 长期记忆系统

目标：让 Agent 有可管理、可引用、可删除的长期记忆。

任务：

- [x] 实现 `memory_items` / `memory_events` 仓储。
- [x] 实现记忆 CRUD API。
- [x] 实现记忆搜索：先用 MySQL LIKE + 类型过滤，后续可接向量。
- [x] 实现记忆候选生成：
  - [x] 从聊天消息生成候选。
  - [x] 从任务报告生成候选。
  - [x] 从学习复习结果生成候选。（M2 已实现：`generate_from_learning_review` 从近 7 天复习/错题/薄弱抽取 draft 记忆）
- [x] 在 ChatService / task planner 中接入记忆检索。（ChatService 已接入；task planner 记忆检索留待 M5 任务计划 2.0）
- [x] 回答中展示使用的记忆来源。
- [x] 前端实现记忆列表、详情、编辑、禁用、删除。

验收：

- 保存一条“我喜欢用类比解释操作系统”的偏好记忆。
- 新会话提问相关问题时能使用该记忆。
- 禁用该记忆后不再使用。
- 任务报告能生成候选项目记忆。

### M2 · 学习系统 2.0

目标：让学习系统从“生成资料”变成“每天能复习和跟踪进度”。

任务：

- [x] 给 `learning_cards` 增加 due/review 字段。（M0 迁移已加列，M2 接入调度）
- [x] 实现复习调度算法：
  - again：短间隔。
  - hard：略延长。
  - good：正常延长。
  - easy：明显延长。
- [x] 新增 `learning_reviews` 表和仓储。（M0 建表，M2 实现仓储 + 调度写入）
- [x] 新增今日复习 API。
- [x] 新增卡片评分 API。
- [x] 新增错题本 API。
- [x] 新增学习主题 dashboard API。
- [x] 学习页新增：
  - 今日复习。
  - 错题本。
  - 掌握度。
  - 周报生成。

验收：

- 复习一张卡片后，`due_at` 变化。
- 今日复习只显示到期卡片。
- 答错题进入错题本。
- 主题 dashboard 显示进度和薄弱点。

已知 defer 项（相对 requirements §5.2，留待后续里程碑或专项）：

- 错题本错因标签 + 按知识节点/错因筛选（需 migration 加 error_cause 列）。
- 错题生成针对性复习卡片（§5.2 验收「能生成针对性复习卡片」）。
- 每日学习报告（仅实现周报；§5.2「每日/每周」）。
- 掌握度根据卡片复习/练习/笔记数量自动更新（当前仅手动 POST /nodes/{id}/mastery）。
- 今日学习「待做练习」专项视图（当前概览仅展示练习题总数）。

### M3 · 文档工作台 2.0

目标：把文档从“可摘要”升级为“可整理、可抽取、可输出”。

任务：

- [x] 实现文档集合：
  - collection CRUD。
  - 添加/移除文档。
  - 集合摘要。（由集合级结构化抽取 + 模板报告覆盖）
- [x] 实现结构化抽取：
  - 术语。
  - 行动项。
  - 关键观点。
  - 表格摘要。
- [x] 实现模板报告：
  - 学习笔记。
  - 技术摘要。
  - 论文阅读。
  - 项目资料整理。
- [x] 预留 OCR worker 接口。（POST /documents/{id}/ocr 返 unavailable，未引引擎依赖）
- [x] 文档页新增集合和抽取结果视图。（KnowledgeView 加「文档/集合」切换 + CollectionWorkspace）

验收：

- 多文档集合可创建。
- 可对集合生成术语表和关键观点。
- 模板报告能导出 Markdown。
- 抽取结果保留来源 doc/chunk。

已知 defer 项（相对 requirements §5.3，留待后续）：

- 来源引用点击穿透到 doc/chunk（当前仅文本展示；GET /chunks/{id} 已存在但未接 UI）。
- 集合级对比（§5.3「对比可按 collection 操作」；当前对比仅支持手动选文档）。
- 引用来源（citations）抽取类型（§5.3 列 6 种，已实现 5 种；需 migration 扩 ENUM）。
- OCR 引擎实际接入（M3 仅预留接口返 unavailable）。

### M4 · 编码工作流 2.0

目标：让编码辅助更接近真实项目工作流：多文件、可回滚、可诊断。

任务：

- [x] 实现项目命令配置：
  - 测试命令。
  - 构建命令。
  - lint/format/typecheck 命令。
- [x] `run_whitelisted_command` 改为项目命令配置 + 全局安全默认值。（命令配置即预授权直接运行；ad-hoc 仍走全局白名单；抽出 `_execute_command` 复用）
- [x] 实现 patch set：
  - 多文件 diff。
  - old/new hash。
  - 写入前快照。
  - 单文件/整组审批。（整组 apply/reject/rollback；单文件审批 defer）
- [x] 实现 rollback patch set。
- [x] 命令失败诊断：
  - 输出摘要。
  - 错误文件/行提取。
  - 下一步建议。
- [x] 项目页新增 command profile / patch set / runbook 面板。（ProjectWorkspace 加浏览/编码切换 + CodingWorkflowPanel；runbook 面板 defer）

验收：

- 多文件 patch set 可预览。
- 批准后写入多个文件。
- 回滚需要审批，并能恢复旧内容。
- 非配置命令被拒绝。
- 命令失败后生成诊断证据。

已知 defer 项（相对 requirements §5.4，留待后续）：

- patch set 单文件级审批（当前整组 apply/reject/rollback）。
- 项目 runbook 面板（§5.4「项目 runbook」；命令配置已可复用，独立 runbook 视图 defer）。
- 命令失败诊断自动接入任务证据流（当前为独立端点，手动触发）。

### M5 · 任务计划 2.0

目标：把任务从“按步骤执行”升级为“可规划、可编辑、可控执行”。

任务：

- [x] 新增 `task_planner.py`，根据目标生成计划。
- [x] 计划生成时使用：
  - 项目命令配置 / runbook 雏形。
  - 相关记忆。
  - 可用工具列表。
  - 文档/学习上下文预留在 plan context 中。
- [x] 任务新增状态：
  - plan_draft。
  - plan_approved。
  - paused。
- [x] 新增计划编辑 API。
- [x] 新增整体计划审批 API。
- [x] 新增暂停、取消、继续、从某步骤继续 API。
- [x] 任务页新增 TaskPlanEditor 和 EvidenceFilterPanel。

验收：

- 输入“帮我分析这个项目为什么测试失败”能生成可编辑计划。
- 用户批准计划前不会执行。
- 用户能删改步骤。
- 执行中可暂停/取消。
- 失败后可从指定步骤继续。

### M6 · Provider、备份与阶段收尾

目标：补齐长期使用需要的模型选择和数据治理。

任务：

- [x] 抽象 `ProviderRouter`。
- [x] 实现 OpenAI-compatible Provider。
- [x] 实现 Claude Provider。
- [x] 设置页支持 Provider 选择和健康检查。
- [x] 远程 Provider 调用前展示隐私提示。
- [x] 实现备份导出。
- [x] 实现恢复预览。
- [x] 实现学习主题/任务报告导出。
- [x] 更新 README / usage-guide。
- [x] 全量测试和视觉 QA。

验收：

- Ollama 默认可用。
- OpenAI-compatible Provider 配置后可用于聊天。
- 远程 Provider 关闭时不发送内容。
- 备份包可创建。
- 恢复预览能展示将覆盖的数据。

---

## 5. 推荐开发顺序

1. M0：先建表、空 API、导航入口，修复测试清理警告。
2. M1：先做记忆系统，因为任务计划、学习推荐、编码 runbook 都依赖记忆。
3. M2：做学习复习闭环，这是用户长期学习计算机知识的核心价值。
4. M3：做文档集合和结构化抽取，让资料处理能力更稳定。
5. M4：做 patch set 和命令配置，提升编码安全性。
6. M5：做任务计划 2.0，把前面的能力串起来。
7. M6：做 Provider 和备份，作为阶段收尾和长期使用保障。

---

## 6. 当前短板到任务映射

| 当前短板 | 第四阶段任务 |
|---|---|
| 没有跨会话长期记忆 | M1 记忆系统 |
| 学习卡片没有复习节奏 | M2 due_at + learning_reviews |
| 任务计划偏固定 | M5 task_planner + 计划编辑 |
| 文档只能摘要/对比 | M3 结构化抽取 + 模板报告 |
| 代码修改是单文件替换 | M4 patch set |
| 缺少回滚 | M4 patch_files old_content + rollback |
| 命令白名单硬编码 | M4 project_command_profiles |
| Provider 只有 Ollama | M6 ProviderRouter |
| 数据长期积累无治理 | M6 backup/export/cleanup |
| 测试中有 aiomysql 清理警告 | M0 测试 fixture / engine 生命周期修复 |

---

## 7. 风险与控制

| 风险 | 控制方式 |
|---|---|
| 长期记忆污染回答 | 记忆必须可查看、可禁用、可删除；敏感记忆默认不进 prompt |
| 远程 Provider 泄露本地内容 | 远程调用前显示发送范围；默认 Ollama；可关闭远程 Provider |
| 自动复习打扰用户 | 只在学习页/状态栏提示，不做系统级强提醒 |
| OCR 依赖过重 | M3 先做接口和失败状态，OCR 引擎可选安装 |
| 多文件 patch 误写 | old hash 校验 + 审批 + 快照 + 回滚 |
| 回滚覆盖用户新改动 | 回滚前校验当前 hash，不一致则拒绝并提示 |
| LLM 计划不可靠 | 计划先展示，用户编辑并批准后执行；高风险步骤二次审批 |
| 备份包过大 | 支持分项备份：数据库、Chroma、上传文件、配置 |

---

## 8. 测试计划

### M0

- `alembic upgrade head`
- 空 API smoke tests。
- 旧测试全量通过。

### M1

- 记忆 CRUD。
- 禁用记忆不参与检索。
- 聊天上下文能引用记忆。
- 任务报告生成候选记忆。

### M2

- 卡片评分更新 due_at。
- 今日复习查询。
- 错题本查询。
- dashboard 统计。

### M3

- 文档集合 CRUD。
- 抽取结果保存。
- 模板报告导出。
- 来源引用存在。

### M4

- 命令配置白名单。
- 多文件 patch set 预览。
- patch set 审批写入。
- rollback 审批恢复。
- 命令失败诊断。

### M5

- 计划生成。
- 计划编辑。
- 计划审批前不执行。
- 暂停/取消/继续。
- 从失败步骤继续。

### M6

- Provider 健康检查。
- OpenAI-compatible Provider mock 测试。
- 远程 Provider 关闭时不调用。
- 备份导出。
- 恢复预览。

### 阶段总验收

- `pytest -q`
- `npm run build`
- `cargo check`
- `alembic current`
- `/health`
- 视觉 QA：900px / 1200px / 1600px。

---

## 9. 文档交付

第四阶段完成时至少更新：

- `README.md`
  - 当前进度增加第四阶段。
  - 增加记忆、复习、patch set、Provider、备份说明。
- `docs/usage-guide.md`
  - 增加记忆页。
  - 增加今日复习。
  - 增加文档集合。
  - 增加 patch set 和回滚。
  - 增加 Provider 和备份。
- `docs/archive/phases/phase4-requirements.md`
  - 勾选验收清单。
- `docs/archive/phases/phase4-plan.md`
  - 勾选里程碑任务。

---

## 10. 最终验收

第四阶段完成时，必须能跑通三个代表场景：

### 场景 A：长期学习

1. 创建“操作系统”学习主题。
2. 导入资料。
3. 生成卡片。
4. 完成今日复习。
5. 错题进入错题本。
6. 生成学习周报。
7. 保存一条学习记忆。
8. 新会话能引用该记忆。

### 场景 B：文档整理

1. 创建文档集合。
2. 添加多份资料。
3. 抽取术语和关键观点。
4. 按“技术摘要”模板生成报告。
5. 导出 Markdown。
6. 报告保留来源引用。

### 场景 C：编码修复

1. 授权项目。
2. 读取项目 runbook。
3. 生成任务计划。
4. 用户编辑并批准计划。
5. 生成多文件 patch set。
6. 用户批准写入。
7. 运行项目测试命令。
8. 失败时生成诊断；成功时生成报告。
9. 项目经验沉淀为记忆。

---

## 11. 阶段结论

第四阶段的产品方向是：从“能做很多事的受控 Agent”，变成“能陪用户长期学习和工作的个人系统”。

这一步最值得优先做的是长期记忆和学习复习，因为它们最贴近用户每天使用的真实价值。编码 patch set、任务计划 2.0 和文档集合则负责把第三阶段已有能力打磨成更可靠的工作流。Provider 和备份放在后半段，是为了让产品能长期运行、可迁移、可恢复。
