# 私人助手 Agent · 第七阶段开发计划书

> 对应 `docs/phase7-requirements.md`。第七阶段定位为“可信赖的日常操作层”：在第六阶段已经完成主动个人中枢的基础上，把今日页、搜索、捕获、通知、诊断、Provider、数据体检和端到端 QA 打磨到真实可长期使用的状态。

---

## 1. 阶段判断

当前项目已经具备：

1. **核心工作台能力**
   - 聊天、知识库、项目、学习、任务、记忆、设置、今日八个主入口。
   - 受控工具调用、审批、活动流、项目文件读取、patch set、命令白名单和多步任务。

2. **长期个人系统**
   - 长期记忆、学习复习、文档集合、目标、check-in、收件箱、提醒和简报。
   - 简报可转任务，聊天消息可保存收件箱。

3. **发布与运行底座**
   - Tauri sidecar、首启配置向导、Windows NSIS 构建、updater 清单、发布清单、发布检查脚本。
   - `/health` 可检查 API、Ollama、MySQL 和 ChromaDB。

4. **隐私与治理底座**
   - trusted paths、工具审批、Provider 路由、远程发送范围提示、隐私预览和 Provider 调用审计。

第七阶段启动时识别出的主要缺口，以及本阶段对应处理：

| 缺口 | 影响 | 第七阶段对应 |
|---|---|---|
| 今日页仍有静态演示内容 | 用户无法完全相信第一屏 | M1 |
| 缺少全局搜索/命令入口 | 功能多后找东西困难 | M2 |
| 捕获入口分散，OCR 不可用 | 零散信息难沉淀，扫描件难处理 | M3 |
| 前端反馈依赖 alert/prompt/confirm | 体验粗糙，错误不可追踪 | M4 |
| 诊断与日志不可视 | 出问题后难排障 | M5 |
| Provider 远程能力不够生产级 | 失败、成本、审计不够清楚 | M6 |
| 软引用和索引一致性缺少治理 | 长期使用后容易堆积脏数据 | M7 |
| 缺少端到端 smoke | 发布前缺少用户路径证据 | M8 |

---

## 2. 总体目标

第七阶段交付后，用户应能完成四个代表场景：

### 场景 A：可信的今日页

1. 打开应用进入“今日”。
2. 页面只展示真实提醒、收件箱、复习、任务、目标、简报、健康状态和最近来源。
3. 没有真实数据时显示空状态和下一步动作。
4. 用户能从今日页直接生成简报、创建提醒、快速捕获或跳转来源。

### 场景 B：一处搜索所有上下文

1. 用户打开全局搜索。
2. 输入关键词。
3. 系统返回会话、文档、切片、任务、证据、记忆、目标、简报等结果。
4. 用户直接打开结果、复制引用、转收件箱或继续聊天。

### 场景 C：快速捕获并安排后续

1. 用户复制一段文字或导入扫描件。
2. 打开快速捕获。
3. 系统建议保存为收件箱、提醒、记忆候选、学习笔记或文档。
4. 扫描件进入 OCR 队列；OCR 不可用时给出明确降级。

### 场景 D：出现故障时能自助排查

1. 健康检查发现 MySQL、Ollama、ChromaDB 或 Provider 异常。
2. 用户打开诊断中心。
3. 看到错误分类、最近日志、迁移状态、版本、备份状态和数据体检。
4. 用户导出脱敏诊断包，或按建议修复配置。

---

## 3. 里程碑

### M0 · 第七阶段文档与范围校准

目标：把阶段边界写清楚，避免第七阶段漂成“更多 AI 功能”。

任务：

- [x] 新增 `docs/phase7-requirements.md`。
- [x] 新增 `docs/phase7-plan.md`。
- [x] 更新 README 第七阶段引用。
- [x] 更新 `docs/requirements.md` 后续阶段表。
- [x] 更新 `docs/usage-guide.md` 路线图。
- [x] 明确第七阶段不重写架构、不引入云同步账户、不把 OCR 大依赖作为硬内置。

验收：

- 第七阶段需求文档和计划书是两份独立文档。
- 后续若出现未实现内容，必须保持未勾选；本次阶段验收只勾选已由代码和验证覆盖的条目。
- 文档明确来自当前代码缺口，而不是泛化路线图。

### M1 · 今日页真实数据化

目标：移除生产模式下的演示型今日内容，让今日页成为可信入口。

任务：

- [x] 梳理 `TodayView.vue` 中所有固定文案/固定数据：
  - 日程安排。
  - 记忆洞察。
  - 相关来源。
  - 隐私与安全状态。
  - 模型名称展示。
- [x] 后端扩展 `/today` 或新增聚合服务，返回：
  - 最近目标 check-in。
  - 最近简报。
  - 最近使用文档。
  - 最近会话摘要。
  - 最近失败活动。
  - 维护健康摘要。
- [x] 今日页支持筛选：
  - 类型。
  - 优先级。
  - 时间范围。
  - 状态。
- [x] 今日简报按钮直接创建或打开简报，不只跳聊天。
- [x] 空状态动作真实可用：
  - 新建提醒。
  - 快速捕获。
  - 导入文档。
  - 生成简报。

验收：

- 空数据库今日页不显示演示文档名、固定日程和虚假洞察。
- 有数据时今日页展示真实来源。
- 今日页所有卡片能跳转或执行明确动作。

### M2 · 全局搜索与命令面板

目标：给多模块系统一个统一入口，降低用户寻找成本。

任务：

- [x] 设计搜索结果统一结构：
  - type。
  - id。
  - title。
  - snippet。
  - source。
  - updated_at。
  - action。
- [x] 新增后端 `search.py` 服务，初版使用 MySQL LIKE + 已有项目搜索/文档切片查询。
- [x] 新增 API：
  - `GET /search`
  - `GET /commands`
  - `POST /commands/{id}/run`
- [x] 新增前端：
  - `GlobalSearch.vue`
  - `CommandPalette.vue`
- [x] 命令面板支持：
  - 新建会话。
  - 新建收件箱。
  - 新建提醒。
  - 导入文档。
  - 生成今日简报。
  - 运行健康检查。
  - 打开设置/诊断中心。
- [x] 支持快捷键打开命令面板。

验收：

- 搜索文档名能命中文档和切片。
- 搜索任务关键词能命中任务和证据。
- 命令面板能创建提醒和收件箱项。
- 搜索结果点击能跳转到正确页面或打开详情。

### M3 · 快速捕获与 OCR 队列

目标：把零散输入变成统一可处理对象，并给扫描件明确处理路径。

任务：

- [x] 新增数据模型草案：
  - `capture_items`
  - `ocr_jobs`
- [x] 新增 API：
  - `POST /capture`
  - `GET /capture`
  - `POST /capture/{id}/to-inbox`
  - `POST /capture/{id}/to-reminder`
  - `POST /capture/{id}/to-memory`
  - `POST /documents/{id}/ocr`
  - `GET /ocr-jobs`
- [x] 新增前端：
  - `CapturePanel.vue`
  - `OcrJobsPanel.vue`
- [x] 支持剪贴板文本捕获。
- [x] 支持捕获类型建议：
  - 收件箱。
  - 提醒。
  - 记忆候选。
  - 学习笔记。
  - 文档笔记。
  - 任务草稿。
- [x] OCR 初版策略：
  - 检测是否安装本地 OCR 引擎。
  - 未安装时记录明确状态。
  - 已安装时进入队列并记录结果。
  - 失败写入维护报告。
- [x] 扫描件 PDF 导入失败时可创建 OCR job 或收件箱候选。

验收：

- 剪贴板文本可转为收件箱和提醒。
- OCR 未安装时 UI 给出明确原因和下一步。
- OCR job 状态可查看、失败可重试或归档。

### M4 · 统一反馈、确认与通知中心

目标：替换粗糙弹窗，给用户稳定、可回看、可重试的操作反馈。

任务：

- [x] 新增 `app_notifications` 数据模型或前端本地通知 store。
- [x] 新增前端基础组件：
  - `ToastHost.vue`
  - `NotificationCenter.vue`
  - `ConfirmDialog.vue`
  - `InlineError.vue`
- [x] 替换关键路径原生弹窗：
  - `KnowledgeView.vue` 导入/删除/重建/OCR/元数据编辑。
  - `TaskWorkspace.vue` 任务执行和证据操作。
  - `CodingWorkflowPanel.vue` 命令与补丁操作。
  - `SettingsView.vue` Provider 测试、备份、恢复预览。
  - `App.vue` 聊天保存收件箱和候选记忆。
- [x] 通知中心记录：
  - 异步操作开始。
  - 成功。
  - 失败。
  - 可重试动作。
  - 跳转来源。
- [x] 危险操作确认 modal 显示影响范围。

验收：

- 关键路径不再依赖 `window.alert` / `prompt` / `confirm`。
- 用户可查看最近通知历史。
- 删除/恢复/命令/补丁等危险操作有统一确认。

### M5 · 诊断中心与脱敏诊断包

目标：把“哪里坏了”从日志里搬到产品里。

任务：

- [x] 新增后端 `diagnostics.py` 服务。
- [x] 新增 API：
  - `GET /diagnostics`
  - `POST /diagnostics/export`
- [x] 诊断中心展示：
  - `/health` 四项状态。
  - 版本。
  - 构建信息。
  - migration head。
  - 最近错误日志摘要。
  - 失败活动。
  - Provider 调用失败。
  - 提醒 tick 状态。
  - 导入队列。
  - 备份状态。
  - 数据完整性摘要。
- [x] 诊断包包含：
  - `diagnostics.json`
  - `health.json`
  - `settings.redacted.json`
  - `recent-errors.log`
  - `version.txt`
  - `migration.txt`
- [x] 脱敏规则覆盖：
  - API key。
  - 数据库密码。
  - 远程 Provider key。
  - 完整聊天内容。
  - 文档原文。
  - 敏感记忆。

验收：

- 任一依赖异常时，诊断中心能展示错误分类。
- 诊断包可生成到用户指定目录。
- 测试覆盖诊断包脱敏。

### M6 · Provider 生产化治理

目标：让远程 Provider 可用、可审计、可降级，而不是只“能调用”。

任务：

- [x] 扩展 `provider_call_audits`：
  - duration_ms。
  - estimated_input_tokens。
  - estimated_output_tokens。
  - error_code。
  - fallback_used。
- [x] Provider 失败分类：
  - missing_api_key。
  - unauthorized。
  - network_error。
  - timeout。
  - rate_limited。
  - model_not_found。
  - provider_error。
- [x] 远程调用前后对比：
  - planned_context_types。
  - sent_context_types。
  - filtered_sensitive_count。
- [x] OpenAI-compatible / Claude 调用接入统一错误映射。
- [x] 失败后支持：
  - 回退 Ollama。
  - 保存为待重试收件箱。
  - 复制诊断摘要。
- [x] 评估远程流式支持，若实现则保持审计完整。

验收：

- API key 缺失、认证失败、模型不存在、超时均有明确错误分类。
- 审计记录能看到耗时和失败原因。
- 敏感上下文过滤规则继续生效。

### M7 · 数据完整性体检与修复计划

目标：让长期使用后的软引用和索引状态可检查、可解释、可修复。

任务：

- [x] 扩展 `MaintenanceHealthReport`。
- [x] 新增 `data_integrity_findings` 或等效结构。
- [x] 检查项：
  - goal_links 悬空。
  - briefings sources 悬空。
  - inbox source/target 悬空。
  - agent_evidence 悬空。
  - document_collection_items 悬空。
  - Chroma chunk 与 MySQL doc_chunks 不一致。
  - 长期已完成对象可归档。
  - 备份包 manifest 和 schema。
- [x] 新增 API：
  - `GET /maintenance/integrity`
  - `POST /maintenance/repair-plan`
  - `POST /maintenance/repair-plan/{id}/apply`
- [x] 修复计划必须先预览：
  - 可归档。
  - 可忽略。
  - 可重建索引。
  - 可删除孤立向量。
  - 可重新关联。
- [x] 今日页和诊断中心展示体检摘要。

验收：

- 至少三类悬空软引用能被检测。
- 修复计划不默认删除用户数据。
- 用户确认后才执行修复。

### M8 · 端到端 QA 与发布前证据

目标：让第七阶段交付有可重复的自动化用户路径证据。

任务：

- [x] 选择自动化 smoke 路径：
  - 当前已采用后端/API smoke + 前端构建验证覆盖第七阶段主路径。
  - Playwright 浏览器模式和 Tauri 桌面 smoke 可作为后续增强。
- [x] 新增 smoke：
  - 启动前端。
  - mock 或启动后端。
  - 进入今日页。
  - 读取真实 `/today` 数据。
  - 打开全局搜索。
  - 创建收件箱或提醒。
- [x] 前端关键组件测试：
  - CommandPalette。
  - CapturePanel。
  - NotificationCenter。
  - ConfirmDialog。
  - DiagnosticsView。
- [x] 更新发布前脚本或 release checklist：
  - pytest。
  - npm build。
  - cargo check。
  - alembic current。
  - 自动化 smoke 或人工发布 smoke。
- [x] 失败时输出截图、日志或诊断包路径。

验收：

- 至少一条自动化 smoke 在本地可重复运行；桌面窗口级 Playwright/Tauri E2E 作为后续增强。
- 发布 checklist 包含第七阶段新增路径。
- 文档记录验证命令和失败分流。

### M9 · 文档收束与阶段验收

目标：把第七阶段收束到可交付、可维护、可验证。

任务：

- [x] 更新 `README.md`。
- [x] 更新 `docs/usage-guide.md`。
- [x] 更新 `docs/release-checklist.md`。
- [x] 更新 API 列表。
- [x] 更新数据模型说明。
- [x] 更新常见问题：
  - OCR 未安装。
  - 远程 Provider 失败。
  - 诊断包脱敏。
  - 全局搜索不命中。
  - 数据体检发现悬空引用。
- [x] 运行阶段总验收：
  - `uv run pytest -q`
  - `npm run build`
  - `cargo check`
  - `uv run alembic current`
  - 自动化 smoke / 发布 smoke
  - `git diff --check`

验收：

- 第七阶段验收清单全部勾选。
- 文档与代码一致。
- 未实现内容不写成已完成。

---

## 4. 推荐开发顺序

1. M0：先把第七阶段定位写清楚，避免变成泛泛的“更多集成”。
2. M1：先清掉今日页静态内容，让第一屏可信。
3. M4：并行补统一反馈组件，因为后续所有新功能都需要稳定反馈。
4. M2：做全局搜索和命令面板，解决功能增多后的入口问题。
5. M3：做快速捕获和 OCR 队列，把输入入口补齐。
6. M5：做诊断中心，让运行问题可见。
7. M6：加强 Provider 治理，让远程调用可审计可降级。
8. M7：补数据完整性体检，服务长期使用。
9. M8：补自动化 smoke 和发布前证据。
10. M9：文档、QA、验收收束。

---

## 5. 测试计划

### M1

- 今日页空数据。
- 今日页有真实 reminders/inbox/goals/briefings。
- 不出现演示文档名或固定日程。
- 前端 build。

### M2

- 全局搜索跨对象。
- 命令面板动作注册。
- 命令面板创建提醒/收件箱。
- 键盘导航。

### M3

- capture CRUD。
- capture 转 inbox/reminder/memory。
- OCR 未安装。
- OCR job 失败。
- OCR job 状态查询。

### M4

- toast 展示。
- 通知中心历史。
- 危险操作确认。
- 原生弹窗替换回归。

### M5

- 诊断快照。
- 诊断包生成。
- 脱敏验证。
- 依赖异常分类。

### M6

- Provider 错误分类。
- 审计状态流转。
- fallback 记录。
- sensitive memory 过滤。

### M7

- 悬空 goal link。
- 悬空 briefing source。
- Chroma/MySQL 不一致。
- repair plan 预览。

### M8

- 自动化 API smoke。
- Playwright/Tauri 桌面 smoke 后续增强。
- 截图/日志输出。
- 发布前脚本串联。

### 阶段总验收

- `uv run pytest -q`
- `npm run build`
- `cargo check`
- `uv run alembic current`
- 自动化 smoke / 发布 smoke
- `git diff --check`

---

## 6. 数据迁移草案

建议新增迁移：

```text
alembic/versions/0010_phase7_reliable_daily_layer.py
```

候选表：

- `app_notifications`
- `capture_items`
- `ocr_jobs`
- `diagnostic_runs`
- `data_integrity_findings`
- `search_recent_items`

注意：

- 通知和诊断只保存摘要，不保存敏感正文。
- OCR 输出进入知识库前必须保留来源。
- integrity finding 支持 ignored/resolved，避免每天重复打扰。
- repair plan 不自动执行破坏性操作。

---

## 7. 风险与控制

| 风险 | 控制方式 |
|---|---|
| 全局搜索变慢 | 初版限定对象、分页、结果上限；后续再引入索引表 |
| 命令面板绕过审批 | 命令动作复用现有工具风险等级和审批状态机 |
| OCR 引入大体积依赖 | OCR 可选安装，未安装时明确降级，不阻塞主包 |
| 诊断包泄露隐私 | 强制脱敏测试，默认只导出摘要 |
| 通知中心变成噪音 | 按等级过滤，可标记已读，可关闭低优先级通知 |
| repair plan 误删数据 | 只预览，不默认删除；破坏性操作二次确认 |
| E2E 在 Windows 上不稳定 | 当前先用后端/API smoke 与发布 checklist 覆盖最小路径；Playwright/Tauri 桌面 smoke 后续增强 |
| Provider 远程流式破坏审计 | 先完成非流式审计闭环，再评估流式 |

---

## 8. 文档交付

第七阶段完成时至少更新：

- `README.md`
  - 第七阶段状态。
  - 相关文档链接。
- `docs/usage-guide.md`
  - 全局搜索、命令面板、快速捕获、OCR、通知中心、诊断中心、数据体检使用说明。
- `docs/requirements.md`
  - 后续阶段表补充第七阶段。
- `docs/release-checklist.md`
  - 第七阶段 smoke 和 QA 项。
- `docs/phase7-requirements.md`
  - 勾选验收清单。
- `docs/phase7-plan.md`
  - 勾选里程碑任务。

---

## 9. 阶段结论

第七阶段要把私人助手从“主动组织一天”推进到“可信赖地管理一天”。它不追求更炫的新能力，而是把已有能力之间的连接打磨到用户每天都敢依赖：真实今日、全局搜索、快速捕获、统一反馈、诊断中心、Provider 治理、数据完整性和端到端证据。

完成后，用户可以更自然地把信息丢进系统、从系统里找回上下文、理解系统为什么失败，并在长期使用后仍能修复和整理自己的数据。
