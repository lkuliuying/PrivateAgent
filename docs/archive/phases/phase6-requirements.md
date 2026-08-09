# 私人助手 Agent · 第六阶段需求文档

> 第六阶段定位：把已经具备聊天、知识库、项目、学习、任务、记忆、Provider 与发布工程化能力的桌面 Agent，升级为可主动组织一天工作的“个人中枢”。核心不是继续堆更多工具，而是补齐今日视图、统一收件箱、提醒与例行回顾、长期目标追踪、主动简报和隐私治理，让它从“用户点哪里才做哪里”的工作台，变成能持续陪伴、提醒、汇总和接住上下文的私人助手。

---

## 1. 背景

前五个阶段已经完成：

- 第一阶段：桌面端、FastAPI 后端、Ollama、MySQL、ChromaDB、聊天与知识库闭环。
- 第二阶段：受控工具调用、审批状态机、授权路径、活动流和工作台 UI。
- 第三阶段：项目工作区、学习系统、文档工作台、编码工具和多步任务编排。
- 第四阶段：长期记忆、学习复习、文档集合、patch set、可编辑任务计划、Provider 路由和备份/恢复预览。
- 第五阶段：Windows 安装包、sidecar 生命周期、updater 清单、发布脚本、签名策略、发布 QA 与跨平台预研。

当前项目已经像一个“强大的本地工作台”，但作为个人助手 Agent 仍有明显缺口：

1. **缺少每日入口**：学习复习、待审批任务、失败导入、候选记忆、未完成任务分散在不同页面，用户每天打开应用时不知道先看哪里。
2. **缺少主动提醒**：已有 `due_at` 学习复习，但没有通用提醒、日程、例行任务、系统通知或错过提醒。
3. **缺少统一收件箱**：聊天里产生的 TODO、文档里的行动项、任务失败、记忆候选、学习复习都没有进入一个可处理队列。
4. **缺少长期目标层**：学习主题、文档集合、任务各自有 goal，但没有统一的目标、里程碑、周回顾和进度视图。
5. **缺少主动简报**：系统不会主动汇总“今天该做什么、最近哪些项目停滞、哪些记忆需要确认、哪些资料值得复习”。
6. **远程 Provider 治理仍偏粗**：已有远程发送范围提示，但没有按请求审计、成本/用量记录、敏感内容提醒、远程上下文预览。
7. **数据生命周期还轻量**：已有备份和恢复预览，但没有定期备份提醒、备份校验、归档/清理建议、跨模块数据体检。
8. **输入入口仍偏重文件和聊天**：暂不支持扫描件 OCR、快速摘录、剪贴板收集、网页/邮件类轻量捕获。

第六阶段要解决的是：让用户每天打开应用时，能看到一个可靠的个人中枢；系统能基于已有数据主动提出下一步，但所有行动仍由用户掌控。

---

## 2. 阶段目标

第六阶段完成后，产品应具备：

1. **今日中枢**
   - 一个新的“今日”入口，集中展示到期复习、待审批任务、失败活动、候选记忆、近期未完成任务、待处理收件箱。
   - 每个卡片都能跳转到来源页面，并可标记完成、稍后、忽略或归档。
   - 支持“今日简报”生成：基于本地数据给出当天优先级建议。

2. **统一收件箱**
   - 用户可手动创建 inbox item，也可从聊天、文档抽取、任务报告、活动失败和记忆候选生成。
   - 收件箱项支持类型、来源、优先级、状态、截止时间、关联对象和处理动作。
   - 收件箱是“待处理事项”的唯一入口，不替代各业务页面。

3. **提醒与例行回顾**
   - 支持一次性提醒、重复提醒和轻量例行任务。
   - 到期提醒进入今日中枢，可选 Windows 桌面通知。
   - 支持每日/每周回顾例行：学习复习、目标进展、未完成任务、失败活动、待确认记忆。

4. **目标与周回顾**
   - 建立统一 `personal_goals`：目标、领域、状态、时间范围、关联学习主题/项目/任务/文档集合。
   - 支持目标里程碑、进度记录、周回顾和下一步建议。
   - Agent 可基于目标上下文生成任务草稿，但不得自动执行高风险动作。

5. **主动简报与上下文包**
   - 提供“今日简报”“项目简报”“学习简报”“周回顾”。
   - 简报必须标注数据来源：学习卡片、任务、活动、记忆、文档集合、项目。
   - 支持把简报作为聊天上下文，用户可一键继续追问或生成任务计划。

6. **隐私与远程 Provider 审计**
   - 远程 Provider 调用前可预览将发送的上下文类别与估算大小。
   - 记录远程调用审计：provider、模型、时间、发送类别、估算 tokens、是否包含知识库/记忆。
   - 支持“敏感记忆/敏感文档不进入远程上下文”的硬规则。

7. **数据体检与备份提醒**
   - 今日中枢展示备份状态、最近备份时间、失败导入、Chroma/MySQL 不一致风险。
   - 支持定期备份提醒和备份包校验。
   - 提供归档建议，不自动删除用户数据。

---

## 3. 非目标

第六阶段不做：

- 不做云同步账户体系。
- 不做完整手机 App。
- 不做全自动无人值守 Agent。提醒、简报和计划可以主动生成，但执行仍需用户确认。
- 不接入商业日历生态作为硬验收。可预留 ICS 导入/导出，但不把 Google Calendar、Outlook 登录作为本阶段必须项。
- 不做复杂项目管理系统替代品。目标层只服务个人助手上下文和每日行动。
- 不承诺扫描件 OCR 全量高精度识别；OCR 可作为预研或轻量文本提取能力，不能阻塞今日中枢。
- 不把远程 Provider 作为默认路径。默认仍本地优先。

---

## 4. 用户场景

### 4.1 早晨打开应用

用户启动私人助手后进入“今日”：

1. 看到今日复习卡片数量、待审批任务、失败导入、待确认记忆、提醒事项。
2. 点击“生成今日简报”。
3. 助手总结：今天最值得处理的 3 件事、卡住的任务、该复习的学习主题。
4. 用户把其中一条建议转为任务计划草稿。
5. 用户批准计划后再执行。

### 4.2 临时记录一个事项

用户在聊天中说：“明天下午提醒我整理这份 MySQL 笔记。”

系统应：

1. 识别为提醒候选，插入可确认卡片。
2. 用户确认后创建 reminder 和 inbox item。
3. 到期时今日页显示，打包模式可选桌面通知。
4. 完成后可沉淀为学习/记忆/任务记录。

### 4.3 周末回顾

用户点击“生成周回顾”：

1. 系统汇总本周学习复习、错题、任务完成、失败活动、候选记忆、目标进展。
2. 输出可编辑 Markdown。
3. 用户可保存为记忆、导出 Markdown、或生成下周任务计划。

### 4.4 远程模型前的隐私确认

用户启用 OpenAI-compatible Provider 后，请求基于知识库和记忆回答。

系统应：

1. 显示本次将发送：最近消息、选中知识库片段、非敏感记忆。
2. 明确不会发送：敏感记忆、禁用文档、未授权文件。
3. 记录审计事件。
4. 用户可取消或继续。

---

## 5. 功能需求

### 5.1 今日中枢

需求：

- 新增导航入口“今日”。
- 汇总以下来源：
  - 到期学习复习。
  - `waiting_approval` / `failed` / `paused` Agent 任务。
  - `failed` 文档导入与 reindex 活动。
  - draft 记忆候选。
  - 到期 reminders。
  - 未处理 inbox items。
  - 最近备份状态。
- 支持过滤：
  - 全部 / 学习 / 任务 / 文档 / 记忆 / 提醒 / 系统。
  - 今天 / 逾期 / 本周 / 已忽略。
- 支持动作：
  - 跳转来源。
  - 标记完成。
  - 稍后提醒。
  - 忽略。
  - 生成任务草稿。

验收：

- 今日页可在一个屏幕内看清“今天要处理什么”。
- 卡片点击能跳到对应页面或打开详情。
- 不同来源的卡片状态变化不会破坏原业务数据。

### 5.2 统一收件箱

需求：

- 新增 `inbox_items` 数据模型：
  - title
  - body_md
  - item_type
  - status
  - priority
  - due_at
  - source_type/source_id
  - target_type/target_id
  - created_at/updated_at/handled_at
- 支持手动创建、编辑、完成、归档。
- 支持从以下来源创建：
  - 聊天消息。
  - 任务最终报告。
  - 文档抽取结果。
  - 学习错题/薄弱点。
  - 活动失败。
  - 记忆候选。
- 收件箱项可以转为：
  - reminder。
  - Agent task plan draft。
  - memory candidate。
  - learning note。

验收：

- 用户能把任意聊天建议保存成待处理项。
- 失败导入和待审批任务能自动出现在待处理列表。
- 完成/归档 inbox item 不删除原始聊天、文档、任务或记忆。

### 5.3 提醒与例行任务

需求：

- 新增 `reminders`：
  - title/body_md
  - due_at
  - recurrence_rule（轻量规则：none/daily/weekly/monthly/custom interval）
  - status（active/done/snoozed/cancelled）
  - source_type/source_id
  - last_fired_at/next_fire_at
- 新增后台 tick 机制：
  - FastAPI 进程内轻量轮询即可，不依赖外部服务。
  - 打包模式跟随 sidecar 生命周期。
  - dev/test 环境可关闭或手动触发。
- 支持 snooze：
  - 10 分钟后。
  - 今天晚些时候。
  - 明天。
  - 自定义时间。
- Windows 桌面通知作为可选能力：
  - 无通知权限时仍进入今日中枢。
  - 通知点击可回到今日页。

验收：

- 到期 reminder 能进入今日页。
- 重复提醒完成一次后生成下一次 `next_fire_at`。
- 重启应用后未处理提醒不丢失。

### 5.4 目标与周回顾

需求：

- 新增 `personal_goals`：
  - title
  - description
  - domain（learning/project/health/work/life/custom）
  - status（active/paused/done/archived）
  - start_date/target_date
  - priority
  - success_criteria_md
- 新增 `goal_links`：
  - goal_id
  - target_type/target_id
  - relation（supports/blocks/evidence/result）
- 新增 `goal_checkins`：
  - goal_id
  - checkin_date
  - progress_note_md
  - confidence
  - blockers_json
  - next_actions_json
- 支持目标页面或今日页中的目标区块。
- 支持 Agent 基于目标生成：
  - 本周总结。
  - 下周建议。
  - 任务计划草稿。
  - 候选记忆。

验收：

- 用户能建立一个目标并关联学习主题、项目、文档集合或任务。
- 周回顾能引用真实关联对象。
- 目标完成/归档后不再默认进入今日待办。

### 5.5 主动简报

需求：

- 支持生成：
  - 今日简报。
  - 学习简报。
  - 项目简报。
  - 周回顾。
- 简报输入来自本地数据快照：
  - 到期复习、错题、薄弱点。
  - 活动失败。
  - 任务状态和证据。
  - 记忆候选。
  - 目标 check-in。
  - 最近文档集合抽取结果。
- 简报输出结构：
  - 重点摘要。
  - 建议优先级。
  - 风险/阻塞。
  - 可执行下一步。
  - 来源列表。
- 简报可保存为 `briefings`：
  - kind
  - title
  - body_md
  - sources_json
  - created_at

验收：

- 简报不凭空捏造未存在的数据。
- 每条建议至少能追溯到一个来源或标注“模型推断”。
- 简报可以转为任务计划草稿。

### 5.6 远程 Provider 隐私审计

需求：

- 新增 `provider_call_audits`：
  - provider_type
  - model
  - purpose（chat/title/briefing/planning/extraction）
  - remote
  - context_types_json
  - estimated_input_chars/tokens
  - estimated_output_chars/tokens
  - sent_at
  - status/error_message
- 在远程 Provider 启用时，支持请求级隐私预览：
  - 最近聊天消息。
  - 知识库片段数量。
  - 记忆条数。
  - 是否含敏感记忆。
  - 是否含文档原文。
- 默认规则：
  - `sensitive=true` 的 memory 不进入远程上下文。
  - 未授权文件不进入远程上下文。
  - 用户禁用的文档不进入远程上下文。
- 设置页展示最近远程调用审计。

验收：

- 远程 Provider 调用有审计记录。
- 敏感记忆不会出现在远程上下文。
- 用户能看到最近一次远程调用发送了哪些类别的数据。

### 5.7 数据体检与备份提醒

需求：

- 今日页展示数据体检：
  - 最近备份时间。
  - 失败导入数量。
  - ChromaDB collection 与 MySQL 文档状态大致一致性。
  - 孤立任务证据数量。
  - draft 记忆候选数量。
- 支持定期备份提醒。
- 支持备份包校验：
  - manifest 是否存在。
  - schema version 是否匹配。
  - 核心表数量摘要。
- 支持归档建议：
  - 已完成很久的任务。
  - 已处理的 inbox item。
  - 已取消活动。

验收：

- 用户能在今日页看到“数据是否健康”。
- 备份提醒不会自动删除或覆盖数据。
- 备份校验失败时给出明确错误。

### 5.8 轻量捕获与 OCR 预研

需求：

- 支持快速记录：
  - 手动粘贴文本到 inbox。
  - 从当前聊天消息保存到 inbox。
  - 从文档抽取结果保存到 inbox。
- OCR 作为预研：
  - 扫描件 PDF 仍可返回“需要 OCR”的明确状态。
  - 评估本地 OCR 方案（如 PaddleOCR / Tesseract / Windows OCR）体积、准确率、打包影响。
  - 不把 OCR 作为第六阶段硬验收。

验收：

- 用户至少能通过手动粘贴和聊天消息创建收件箱项。
- 扫描件 PDF 不再只是失败，可进入“待 OCR/手动处理”队列。

---

## 6. 数据需求

建议新增迁移 `0009_phase6_proactive_hub.py`：

```sql
CREATE TABLE inbox_items (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  title VARCHAR(255) NOT NULL,
  body_md MEDIUMTEXT NULL,
  item_type ENUM('todo','reminder','review','approval','failure','memory','note','system') NOT NULL,
  status ENUM('open','snoozed','done','ignored','archived') NOT NULL DEFAULT 'open',
  priority ENUM('low','normal','high','urgent') NOT NULL DEFAULT 'normal',
  due_at DATETIME(3) NULL,
  source_type VARCHAR(64) NULL,
  source_id BIGINT NULL,
  target_type VARCHAR(64) NULL,
  target_id BIGINT NULL,
  meta_json JSON NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  handled_at DATETIME(3) NULL,
  INDEX idx_inbox_status_due (status, due_at),
  INDEX idx_inbox_source (source_type, source_id)
);
```

```sql
CREATE TABLE reminders (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  title VARCHAR(255) NOT NULL,
  body_md MEDIUMTEXT NULL,
  status ENUM('active','snoozed','done','cancelled') NOT NULL DEFAULT 'active',
  due_at DATETIME(3) NOT NULL,
  recurrence_rule JSON NULL,
  next_fire_at DATETIME(3) NULL,
  last_fired_at DATETIME(3) NULL,
  source_type VARCHAR(64) NULL,
  source_id BIGINT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  INDEX idx_reminder_next (status, next_fire_at),
  INDEX idx_reminder_source (source_type, source_id)
);
```

```sql
CREATE TABLE personal_goals (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  title VARCHAR(255) NOT NULL,
  description MEDIUMTEXT NULL,
  domain VARCHAR(64) NOT NULL DEFAULT 'custom',
  status ENUM('active','paused','done','archived') NOT NULL DEFAULT 'active',
  priority ENUM('low','normal','high') NOT NULL DEFAULT 'normal',
  start_date DATE NULL,
  target_date DATE NULL,
  success_criteria_md MEDIUMTEXT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  INDEX idx_goal_status (status, priority)
);
```

```sql
CREATE TABLE goal_links (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  goal_id BIGINT NOT NULL,
  target_type VARCHAR(64) NOT NULL,
  target_id BIGINT NOT NULL,
  relation VARCHAR(64) NOT NULL DEFAULT 'supports',
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_goal_target (goal_id, target_type, target_id, relation),
  INDEX idx_goal_links_goal (goal_id)
);
```

```sql
CREATE TABLE goal_checkins (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  goal_id BIGINT NOT NULL,
  checkin_date DATE NOT NULL,
  progress_note_md MEDIUMTEXT NULL,
  confidence FLOAT NULL,
  blockers_json JSON NULL,
  next_actions_json JSON NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  INDEX idx_goal_checkins_goal_date (goal_id, checkin_date)
);
```

```sql
CREATE TABLE briefings (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  kind ENUM('today','weekly','learning','project','goal') NOT NULL,
  title VARCHAR(255) NOT NULL,
  body_md MEDIUMTEXT NOT NULL,
  sources_json JSON NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  INDEX idx_briefing_kind_time (kind, created_at)
);
```

```sql
CREATE TABLE provider_call_audits (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  provider_type VARCHAR(64) NOT NULL,
  model VARCHAR(255) NULL,
  purpose VARCHAR(64) NOT NULL,
  remote BOOLEAN NOT NULL DEFAULT 0,
  context_types_json JSON NULL,
  estimated_input_chars INT NULL,
  estimated_output_chars INT NULL,
  status ENUM('planned','sent','succeeded','failed','cancelled') NOT NULL DEFAULT 'planned',
  error_message TEXT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  finished_at DATETIME(3) NULL,
  INDEX idx_provider_audit_time (created_at),
  INDEX idx_provider_audit_remote (remote, created_at)
);
```

---

## 7. API 需求

建议新增路由：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/today` | 今日中枢聚合快照 |
| POST | `/today/briefing` | 生成今日简报 |
| POST | `/briefings/weekly` | 生成周回顾 |
| GET | `/inbox` | 列出收件箱项 |
| POST | `/inbox` | 手动创建收件箱项 |
| PATCH | `/inbox/{id}` | 更新状态/优先级/截止时间 |
| POST | `/inbox/{id}/to-task` | 转为任务计划草稿 |
| POST | `/inbox/{id}/to-reminder` | 转为提醒 |
| GET | `/reminders` | 列出提醒 |
| POST | `/reminders` | 创建提醒 |
| PATCH | `/reminders/{id}` | 更新提醒 |
| POST | `/reminders/{id}/snooze` | 稍后提醒 |
| POST | `/reminders/tick` | 手动触发提醒扫描（测试/开发） |
| GET | `/goals` | 列出目标 |
| POST | `/goals` | 创建目标 |
| GET | `/goals/{id}` | 目标详情 |
| PATCH | `/goals/{id}` | 更新目标 |
| POST | `/goals/{id}/links` | 关联学习/项目/任务/集合 |
| POST | `/goals/{id}/checkins` | 添加目标回顾 |
| POST | `/goals/{id}/briefing` | 生成目标简报 |
| GET | `/briefings` | 列出历史简报 |
| POST | `/briefings/{id}/to-task` | 简报转任务草稿 |
| GET | `/privacy/audits` | 远程 Provider 调用审计 |
| POST | `/privacy/preview` | 预览某次请求将发送的上下文类别 |
| GET | `/maintenance/health-report` | 数据体检报告 |

---

## 8. 前端需求

建议新增/调整：

- `TodayView.vue`
  - 今日摘要区。
  - 待处理卡片列表。
  - 今日简报面板。
  - 数据体检区。
- `InboxPanel.vue`
  - 收件箱筛选、状态变更、转任务/提醒。
- `ReminderEditor.vue`
  - 创建/编辑提醒与重复规则。
- `GoalsWorkspace.vue`
  - 目标列表、目标详情、关联对象、周回顾。
- `BriefingPanel.vue`
  - 简报展示、来源列表、转任务、保存为记忆。
- `PrivacyAuditPanel.vue`
  - 远程 Provider 最近调用、上下文类别、用量估算。
- 导航从七入口扩展为八入口：

```text
聊天 / 今日 / 知识库 / 项目 / 学习 / 任务 / 记忆 / 设置
```

---

## 9. 安全与隐私要求

- 默认不发送任何数据到远程 Provider。
- 远程 Provider 的上下文预览必须在请求级别可见。
- 敏感记忆不得进入远程上下文。
- 今日简报和周回顾必须标注来源，不能把模型推断伪装成事实。
- 提醒和例行任务不得自动执行命令、写文件或上传数据。
- 系统通知只显示摘要，不显示敏感内容。
- 数据清理只给建议，删除必须由用户显式确认。

---

## 10. 测试需求

### 10.1 后端

- `pytest -q`
- 新增测试：
  - 今日聚合包含 due learning cards / failed activities / pending approvals。
  - inbox CRUD、状态流转、来源关联。
  - reminder tick、snooze、重复规则。
  - goal CRUD、link、check-in、briefing。
  - briefing sources 可追溯。
  - provider audit 记录远程调用上下文类别。
  - sensitive memory 不进入远程上下文 preview。
  - maintenance health report 能识别备份缺失与失败导入。

### 10.2 前端

- `npm run build`
- 今日页空状态、加载状态、错误状态。
- reminder editor 表单验证。
- inbox 卡片状态切换。
- goal 关联对象展示。
- privacy audit 面板敏感字段不泄露 API key。

### 10.3 Tauri / 打包

- `cargo check`
- 打包模式 reminder tick 不阻塞 sidecar 启动。
- 可选桌面通知失败时降级到今日页。

---

## 11. 验收清单

第六阶段完成时必须满足：

- [x] 新增“今日”入口，能汇总学习复习、任务、活动失败、记忆候选、提醒和数据体检。
- [x] 收件箱支持手动创建、来源创建、完成、稍后、归档、转任务、转提醒。
- [x] reminder 支持一次性提醒、snooze、重复规则和重启后持久化。
- [x] 目标系统支持目标、关联对象、check-in、周回顾。
- [x] 今日简报和周回顾可生成，且每条建议有来源或明确标注推断。
- [x] 远程 Provider 调用有审计记录和上下文预览。
- [x] 敏感记忆不会进入远程 Provider 上下文。
- [x] 数据体检能展示最近备份、失败导入、孤立数据和归档建议。
- [x] `pytest -q`、`npm run build`、`cargo check` 通过。
- [x] `docs/usage-guide.md` 更新第六阶段使用说明。

验收证据（2026-07-08）：
- `uv run pytest -q`：146 passed。
- `npm run build`：vue-tsc + Vite production build passed。
- `cargo check`：Tauri desktop crate passed。
- `uv run alembic current`：`0009 (head)`。

---

## 12. 定版结论

第六阶段的价值不是让 Agent 更“自动”，而是让它更“在场”：每天知道该提醒什么、该复习什么、哪些任务卡住了、哪些信息值得沉淀、哪些目标需要回顾，同时继续尊重用户的审批和隐私边界。

完成后，私人助手会从“功能很全的本地工作台”升级为“每天能接住上下文、组织行动、提醒回顾的个人中枢”。
